"""Independent numerical oracles for the complete-finance source contracts."""
from datetime import date
from decimal import Decimal

import pytest
from archive_helpers import purge_deposits, purge_handover, purge_originals
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.finance_models import ReportDefinition, SettlementCommand
from backend.models import (
    AccountCreate,
    BookingCreate,
    ContractCreate,
    InvoiceCreate,
    PortfolioCreate,
    PropertyCreate,
    ReceivableCreate,
    TenantCreate,
    UnitCreate,
)
from backend.services import finance_reports, report_service
from backend.services.maintenance_projects import work
from backend.services.maintenance_rows import Rows
from backend.services.payment_allocations import auto_allocate, tenant_account
from backend.services.receivable_residuals import allocate, residual


@pytest.fixture(autouse=True)
def clean():
    purge_deposits(store)
    purge_handover(store)
    purge_originals(store)
    store.clear_all()
    auth.clear_users()
    yield
    purge_deposits(store)
    purge_handover(store)
    purge_originals(store)
    store.clear_all()
    auth.clear_users()


@pytest.fixture
def estate():
    p = store.create_portfolio(PortfolioCreate(name="Orakel"))
    house = store.create_property(PropertyCreate(portfolio_id=p.id, name="Haus", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=house.id, label="Wohnung", unit_type="residential", cold_rent=100))
    tenant = store.create_tenant(TenantCreate(full_name="Testmieter"))
    contract = store.create_contract(ContractCreate(contract_number="V-Oracle", property_id=house.id,
        unit_id=unit.id, tenant_id=tenant.id, start_date=date(2026, 1, 1), status="active"))
    account = store.create_account(AccountCreate(portfolio_id=p.id, name="Bank", account_type="bank", opening_balance=1000))
    return p, house, unit, tenant, contract, account


def book(estate, amount, day="2026-01-10", **extra):
    _, house, unit, tenant, _, account = estate
    b = store.create_booking(BookingCreate(account_id=account.id, tenant_id=tenant.id,
        property_id=house.id, unit_id=unit.id, booking_date=date.fromisoformat(day), amount=amount, **extra))
    auto_allocate(store, b)
    return b


def claim(estate, amount=100, status="open"):
    return store.create_receivable(ReceivableCreate(contract_id=estate[4].id, due_date=date(2026, 1, 1),
                                                   amount_due=amount, status=status))


def command(r, b=None, credit=None, amount="40", day="2026-01-10", key="oracle-key-001"):
    return SettlementCommand(expected_revision=residual(store, r)["revision"], idempotency_key=key,
        booking_id=b.id if b else None, credit_id=credit.id if credit else None, amount=Decimal(amount),
        effective_date=date.fromisoformat(day), reason="Beleg geprüft")


def test_100_minus_40_minus_20_credit_dated_and_reversal_everywhere(estate):
    r, credit = claim(estate), claim(estate, -20)
    payment = book(estate, 40)
    payload = command(r, payment)
    first = allocate(store, r.id, payload)
    assert allocate(store, r.id, payload) == first
    allocate(store, r.id, command(r, credit=credit, amount="20", day="2026-01-20", key="credit-oracle-key"))
    assert residual(store, r, date(2026, 1, 9))["residual"] == "100.00"
    assert residual(store, r, date(2026, 1, 15))["residual"] == "60.00"
    assert residual(store, r, date(2026, 1, 20))["residual"] == "40.00"
    assert residual(store, credit, date(2026, 1, 20))["residual"] == "0.00"
    assert report_service.compute_receivables_aging(store, today=date(2026, 1, 20))["openTotal"] == 40
    assert report_service.compute_summary(store, today=date(2026, 1, 20))["finance"]["openReceivables"] == 40
    # Explicit cash is no longer simultaneously available as rent.
    account = tenant_account(store, estate[3].id, date(2026, 1, 20))
    assert account["totals"]["paid"] == 0
    assert account["deposit_total"] == 0  # an explicit receivable payment is never labelled as a deposit
    assert account["receivable_settlement_total"] == 40
    book(estate, -40, "2026-02-01", reverses_booking_id=payment.id)
    assert residual(store, r, date(2026, 1, 31))["residual"] == "40.00"
    assert residual(store, r, date(2026, 2, 1))["residual"] == "80.00"


def test_cas_source_budget_and_idempotency_conflicts(estate):
    r, other = claim(estate), claim(estate)
    b = book(estate, 40)
    payload = command(r, b)
    allocate(store, r.id, payload)
    with pytest.raises(HTTPException) as conflict:
        allocate(store, r.id, payload.model_copy(update={"amount": Decimal(30)}))
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException):
        allocate(store, other.id, command(other, b, amount="0.01", key="overbudget-key"))
    with pytest.raises(HTTPException):
        allocate(store, r.id, payload.model_copy(update={"idempotency_key": "stale-key-001"}))
    assert residual(store, other)["residual"] == "100.00"


def test_legacy_partial_is_explicit_evidence_never_an_invented_payment(estate):
    r = claim(estate, status="partial")
    state = residual(store, r)
    assert state["unresolved_legacy"] and state["residual"] == "100.00" and state["evidence"] == []
    with pytest.raises(HTTPException):
        allocate(store, r.id, command(r, book(estate, 40)))


def test_crash_rolls_back_cash_reservations_and_rent_changes(estate, monkeypatch):
    r, b = claim(estate), book(estate, 40)
    original = Rows.add
    def fail(self, table, record):
        original(self, table, record)
        if table == "receivable_settlements":
            raise RuntimeError("simulated crash after inserting edge")
    monkeypatch.setattr(Rows, "add", fail)
    with pytest.raises(RuntimeError):
        allocate(store, r.id, command(r, b))
    assert residual(store, r)["residual"] == "100.00"
    monkeypatch.setattr(Rows, "add", original)
    allocate(store, r.id, command(r, b))
    assert residual(store, r)["residual"] == "60.00"


def test_performance_2026_unpaid_invoice_paid_2027_once(estate):
    from backend.maintenance_models import InvoicePayment
    invoice = store.create_invoice(InvoiceCreate(property_id=estate[1].id, supplier="Handwerk",
        invoice_date=date(2026, 12, 15), performance_start=date(2026, 1, 1), performance_end=date(2026, 12, 31),
        net_amount=1200, gross_amount=1200))
    payment = store.create_booking(BookingCreate(account_id=estate[5].id, property_id=estate[1].id,
        booking_date=date(2027, 1, 20), amount=-1200))
    with work(store, None, ()) as unit:
        Rows.of(unit).add("invoice_payments", InvoicePayment(id="invoice-payment-oracle", invoice_id=invoice.id,
            booking_id=payment.id, amount=1200))
    d = ReportDefinition(kind="performance-period-v2", as_of=date(2026, 12, 31))
    result = finance_reports.compute(store, d)
    assert result["totals"]["costs"] == "1200.00"
    assert sum(Decimal(m["costs"]) for m in result["monthly"]) == 1200
    assert finance_reports.compute(store, d.model_copy(update={"as_of": date(2027, 12, 31)}))["totals"]["costs"] == "0.00"
    from backend.services.finance_ledger import FinanceFilter
    cash26 = report_service.compute_cashflow(store, FinanceFilter(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31)))
    cash27 = report_service.compute_cashflow(store, FinanceFilter(date_from=date(2027, 1, 1), date_to=date(2027, 12, 31)))
    assert cash26["expenseTotal"] == 0 and cash27["expenseTotal"] == 1200


@pytest.mark.parametrize("months, expected", [(3, "1200.00"), (6, "1500.00"), (12, "2100.00")])
def test_forecast_independent_3_6_12_month_oracles(estate, months, expected):
    # Jan 15: Jan rent payment day already passed; remaining months 100 each.
    # Opening 1000 + (N-1)*100; no historical averages are invented.
    d = ReportDefinition(kind="liquidity-v2", as_of=date(2026, 1, 15), months=months)
    result = finance_reports.compute(store, d)
    assert len(result["monthly"]) == months
    assert result["monthly"][0]["income"] == "0.00"
    assert result["closing_balance"] == expected
    assert finance_reports.compute(store, d.model_copy(update={"vacant_unit_ids": [estate[2].id]}))["closing_balance"] == "1000.00"


def test_saved_definition_owner_isolation_exports_and_replay(estate, tmp_path):
    user = auth.register_user("finance-owner", "f@example.com", "Finanzen", "Secret123", "eigentuemer")
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(user.id)})
    definition = {"kind": "liquidity-v2", "as_of": "2026-01-15", "months": 3}
    payload = {"name": "Dreimonatsplan", "idempotency_key": "save-oracle-key", "definition": definition}
    response = client.post("/api/v1/reports/v2/saved", json=payload)
    assert response.status_code == 200, response.text
    record = response.json()
    assert client.post("/api/v1/reports/v2/saved", json=payload).json()["id"] == record["id"]
    json_report = client.get("/api/v1/reports/v2/saved/" + record["id"]).json()
    assert json_report["closing_balance"] == "1200.00"
    csv_report = client.get("/api/v1/reports/v2/saved/" + record["id"] + "?format=csv")
    assert json_report["definition_hash"] in csv_report.text and "1200.00" in csv_report.text
    pdf = client.get("/api/v1/reports/v2/saved/" + record["id"] + "?format=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    from io import BytesIO

    import pdfplumber
    with pdfplumber.open(BytesIO(pdf.content)) as document:
        text = "\n".join(page.extract_text() or "" for page in document.pages)
    assert json_report["definition_hash"] in "".join(text.split()) and "1200.00" in text
    (tmp_path / "finance-v2-sample.pdf").write_bytes(pdf.content)
    other = auth.register_user("finance-other", "other@example.com", "Andere", "Secret123", "eigentuemer")
    assert TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(other.id)}).get(
        "/api/v1/reports/v2/saved/" + record["id"]).status_code == 404


def test_required_deposit_oracle_100_payment40_deposit20_and_dated_reversal():
    from test_deposits import API, BASE, _book, _client, _estate, _finalize, _paid_deposit, _settle, _user

    from backend.models import BillingPeriodCreate, UtilityStatementCreate
    client = _client(_user("deposit-oracle"))
    e = _estate()
    deposit_id = _paid_deposit(client, e, amount=20)
    period = store.create_billing_period(BillingPeriodCreate(property_id=e["property"].id, label="NK",
        start_date=date(2025, 1, 1), end_date=date(2025, 12, 31), status="finalized"))
    statement = store.create_utility_statement(UtilityStatementCreate(billing_period_id=period.id,
        contract_id=e["contract"].id, unit_id=e["unit"].id, total_cost=200, advance_paid=100, balance=100, status="finalized"))
    r = store.create_receivable(ReceivableCreate(contract_id=e["contract"].id, statement_id=statement.id,
        due_date=date(2026, 7, 1), amount_due=100))
    _book(client, e, 21000, "2026-06-01", account="rent_account", text="Miete vollständig")
    payment = _book(client, e, 40, "2026-07-02", account="rent_account", text="Nachzahlung")
    body = {"expected_revision": residual(store, r)["revision"], "idempotency_key": "required-oracle-payment",
            "booking_id": payment["id"], "amount": "40.00", "effective_date": "2026-07-02", "reason": "Nachzahlung"}
    response = client.post(f"{API}/receivables/{r.id}/settlements", json=body)
    assert response.status_code == 200, response.text
    draft = client.post(f"{BASE}/{deposit_id}/settlements", json={}).json()["settlements"][0]
    assert next(s for s in draft["suggestions"]["receivables"] if s["id"] == r.id)["open"] == 60
    draft = _settle(client, deposit_id, draft, [{"kind": "receivable", "description": "Nachzahlung",
        "amount": 20, "receivable_id": r.id}], day="2026-07-05")
    response = _finalize(client, deposit_id, draft["id"])[1]
    assert response.status_code == 200, response.text
    original = client.get(f"{BASE}/{deposit_id}/settlements/{draft['id']}/document").content
    def dunned(day):
        response = client.get(f"{API}/dunning/contracts/{e['contract'].id}", params={"as_of": day})
        assert response.status_code == 200, response.text
        return next(row["outstanding"] for row in response.json()["claims"] if row["receivable_id"] == r.id)
    assert dunned("2026-07-01") == 100
    assert dunned("2026-07-03") == 60
    assert dunned("2026-07-06") == 40
    assert residual(store, store.get_receivable(r.id), date(2026, 7, 6))["residual"] == "40.00"
    assert report_service.compute_receivables_aging(store, today=date(2026, 7, 6))["openTotal"] == 40
    response = client.post(f"{API}/bookings/{payment['id']}/reverse", json={"booking_date": "2026-07-10"})
    assert response.status_code == 201, response.text
    assert dunned("2026-07-11") == 80
    assert dunned("2026-07-06") == 40
    assert original == client.get(f"{BASE}/{deposit_id}/settlements/{draft['id']}/document").content


def test_undo_credit_restores_both_sources_on_its_date_once(estate):
    from backend.finance_models import ReverseSettlement
    from backend.services.receivable_residuals import reverse
    r, credit = claim(estate), claim(estate, -20)
    edge = allocate(store, r.id, command(r, credit=credit, amount="20"))
    payload = ReverseSettlement(expected_revision=residual(store, r)["revision"], idempotency_key="undo-credit-oracle",
                                effective_date=date(2026, 2, 1), reason="Verrechnung korrigiert")
    result = reverse(store, r.id, edge["id"], payload)
    assert reverse(store, r.id, edge["id"], payload) == result
    assert residual(store, r, date(2026, 1, 31))["residual"] == "80.00"
    assert residual(store, credit, date(2026, 1, 31))["residual"] == "0.00"
    assert residual(store, r, date(2026, 2, 1))["residual"] == "100.00"
    assert residual(store, credit, date(2026, 2, 1))["residual"] == "-20.00"


@pytest.mark.parametrize("months, expected", [(3, "1130.00"), (6, "1130.00"), (12, "1130.00")])
def test_forecast_remainder_due_day_change_end_partial_planned_bill(estate, months, expected):
    from backend.maintenance_models import InvoicePayment
    from backend.models import RentAdjustmentCreate
    c = estate[4]
    store.update_contract(c.id, ContractCreate(**{**c.model_dump(exclude={"id", "created_at", "updated_at"}),
                                                "end_date": date(2026, 3, 31)}))
    store.create_rent_adjustment(RentAdjustmentCreate(contract_id=c.id, adjustment_type="stepped",
        effective_date=date(2026, 2, 1), previous_rent=100, new_rent=200, status="pending"))
    invoice = store.create_invoice(InvoiceCreate(property_id=estate[1].id, supplier="Dach",
        invoice_date=date(2026, 1, 1), due_date=date(2026, 2, 10), net_amount=120, gross_amount=120))
    payment = store.create_booking(BookingCreate(account_id=estate[5].id, property_id=estate[1].id,
        booking_date=date(2026, 2, 10), amount=-40))
    with work(store, None, ()) as unit:
        Rows.of(unit).add("invoice_payments", InvoicePayment(id="future-partial-oracle", invoice_id=invoice.id,
                                                           booking_id=payment.id, amount=40))
    # Rest January 100*50%=50; Feb & Mar 200*50%=100 each; expense120=80 expected+40 planned.
    result = finance_reports.compute(store, ReportDefinition(kind="liquidity-v2", as_of=date(2026, 1, 1),
        months=months, rent_payment_day=20, rent_collection_percent=Decimal(50)))
    assert result["closing_balance"] == expected
    assert result["monthly"][0]["income"] == "50.00"
    assert result["monthly"][1]["expense"] == "120.00"
    assert result["baseline_monthly"][-1]["balance"] == "1380.00"


def test_prepaid_current_month_is_not_forecast_a_second_time(estate):
    book(estate, 100, "2026-01-01")
    result = finance_reports.compute(store, ReportDefinition(kind="liquidity-v2", as_of=date(2026, 1, 2), months=3))
    assert result["monthly"][0]["income"] == "0.00"
    assert result["closing_balance"] == "1300.00"  # cash1100 + Feb100 + Mar100


def test_export_conflicts_when_source_changes_after_preview(estate):
    user = auth.register_user("export-owner", "export@example.com", "Export", "Secret123", "eigentuemer")
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(user.id)})
    definition = {"kind": "liquidity-v2", "as_of": "2026-01-15", "months": 3}
    result = client.post("/api/v1/reports/v2/preview", json=definition).json()
    book(estate, 1, "2026-01-10")
    response = client.post("/api/v1/reports/v2/preview?format=csv&expected_result_hash=" + result["result_hash"], json=definition)
    assert response.status_code == 409


def test_current_portfolio_permission_and_role_apply_to_saved_definitions_and_settlements(estate):
    r, b = claim(estate), book(estate, 40)
    user = auth.register_user("scoped-finance", "scope@example.com", "Buchhaltung", "Secret123", "buchhaltung",
                              portfolio_access="selected", portfolio_ids=[estate[0].id])
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(user.id)})
    assert client.get(f"/api/v1/receivables/{r.id}/residual").status_code == 200
    report = client.post("/api/v1/reports/v2/saved", json={"name": "Privat", "idempotency_key": "scope-report-key",
        "definition": {"kind": "liquidity-v2", "as_of": "2026-01-15", "months": 3, "portfolio_id": estate[0].id}})
    assert report.status_code == 200, report.text
    identifier = report.json()["id"]
    auth.update_user(user.id, {"portfolio_access": "selected", "portfolio_ids": []})
    assert client.get(f"/api/v1/receivables/{r.id}/residual").status_code == 404
    assert client.get(f"/api/v1/reports/v2/saved/{identifier}").status_code == 404
    assert client.get("/api/v1/reports/v2/saved").json() == []
    auth.update_user(user.id, {"portfolio_access": "selected", "portfolio_ids": [estate[0].id], "role": "readonly"})
    response = client.post(f"/api/v1/receivables/{r.id}/settlements", json=command(r, b).model_dump(mode="json"))
    assert response.status_code == 403
    assert residual(store, r)["residual"] == "100.00"


def test_parallel_commands_cannot_spend_the_same_cash_twice(estate):
    from concurrent.futures import ThreadPoolExecutor
    r, b = claim(estate), book(estate, 40)
    user = auth.register_user("parallel-finance", "parallel@example.com", "Finanzen", "Secret123", "eigentuemer")
    headers = {"Authorization": "Bearer " + auth.create_access_token(user.id)}
    payload = command(r, b).model_dump(mode="json")
    def send(key):
        client = TestClient(app, headers=headers)
        try:
            return client.post(f"/api/v1/receivables/{r.id}/settlements", json={**payload, "idempotency_key": key}).status_code
        finally:
            client.close()
    # One pytest worker; two explicitly competing requests exercise independent request sessions.
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(send, ["parallel-command-one", "parallel-command-two"]))
    assert sorted(statuses) == [200, 409]
    assert residual(store, store.get_receivable(r.id))["residual"] == "60.00"


def test_snapshot_restores_canonical_links_without_creating_cash(estate):
    from backend.services.data_snapshot import clear_business_data, export_snapshot, import_snapshot
    r, b = claim(estate), book(estate, 40)
    allocate(store, r.id, command(r, b))
    before = export_snapshot(store)
    assert len(before["receivable_settlements"]) == 1
    assert "saved_finance_reports" not in before
    clear_business_data(store)
    import_snapshot(store, before, replace=True)
    after = export_snapshot(store)
    assert after["bookings"] == before["bookings"]
    assert after["receivable_settlements"] == before["receivable_settlements"]
    assert residual(store, store.get_receivable(r.id))["residual"] == "60.00"


def test_partial_return_shares_cash_with_rent_and_later_allocation_uses_only_remaining_cash(estate):
    r, b = claim(estate), book(estate, 100)
    allocate(store, r.id, command(r, b))
    book(estate, -40, "2026-02-01", reverses_booking_id=b.id)
    # Original100: rent60 + separate claim40. Return40: rent24 + claim16.
    assert residual(store, r, date(2026, 2, 2))["residual"] == "76.00"
    assert tenant_account(store, estate[3].id, date(2026, 2, 2))["totals"]["paid"] == 36
    allocate(store, r.id, command(r, b, amount="36", day="2026-03-01", key="after-return-key"))
    assert residual(store, r, date(2026, 1, 31))["residual"] == "60.00"
    assert residual(store, r, date(2026, 2, 2))["residual"] == "76.00"
    assert residual(store, r, date(2026, 3, 2))["residual"] == "40.00"
    assert tenant_account(store, estate[3].id, date(2026, 3, 2))["totals"]["paid"] == 0


def test_service_tariff_invoice_and_planned_partial_have_one_forecast_identity(estate):
    from backend.maintenance_models import InvoicePayment
    from backend.models import ContactCreate
    from backend.models_service_contracts import ServiceContractInvoiceCreate
    contact = store.create_contact(ContactCreate(contact_type="supplier", company_name="Stadtwerke"))
    user = auth.register_user("service-forecast", "service@example.com", "Finanzen", "Secret123", "eigentuemer")
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(user.id)})
    response = client.post("/api/v1/service-contracts", json={"contract_type": "electricity", "title": "Strom",
        "provider_contact_id": contact.id, "start_date": "2026-01-01", "end_date": "2026-12-31",
        "locations": [{"property_id": estate[1].id, "unit_id": estate[2].id}],
        "tariff": {"valid_from": "2026-01-01", "advance_amount": 30, "advance_interval": "monthly", "advance_day": 10}})
    assert response.status_code == 201, response.text
    contract_id = response.json()["id"]
    definition = ReportDefinition(kind="liquidity-v2", as_of=date(2026, 1, 1), months=3)
    assert finance_reports.compute(store, definition)["closing_balance"] == "1210.00"  # 1000 + rent300 - 3*30
    invoice = store.create_invoice(InvoiceCreate(property_id=estate[1].id, supplier="Stadtwerke", invoice_date=date(2026, 2, 1),
        due_date=date(2026, 2, 10), net_amount=30, gross_amount=30))
    store.create_service_contract_invoice(ServiceContractInvoiceCreate(service_contract_id=contract_id, invoice_id=invoice.id,
        period_start=date(2026, 2, 1), period_end=date(2026, 2, 28)))
    payment = store.create_booking(BookingCreate(account_id=estate[5].id, property_id=estate[1].id,
        booking_date=date(2026, 2, 10), amount=-10))
    with work(store, None, ()) as unit:
        Rows.of(unit).add("invoice_payments", InvoicePayment(id="supplier-plan-10", invoice_id=invoice.id, booking_id=payment.id, amount=10))
    assert finance_reports.compute(store, definition)["closing_balance"] == "1210.00"
    performance = finance_reports.compute(store, ReportDefinition(kind="performance-period-v2", as_of=date(2026, 12, 31), unit_id=estate[2].id))
    assert performance["totals"]["costs"] == "30.00"  # linked invoice appears in the unit; payment never adds expense


def test_performance_warm_rent_plus_latest_final_utility_difference(estate):
    from backend.models import BillingPeriodCreate, ContractRentPeriodCreate, UtilityStatementCreate
    store.create_contract_rent_period(ContractRentPeriodCreate(contract_id=estate[4].id, valid_from=date(2026, 1, 1),
        cold_rent=100, service_charge_advance=20))
    original = store.create_billing_period(BillingPeriodCreate(property_id=estate[1].id, label="NK2026", start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31), status="finalized"))
    store.create_utility_statement(UtilityStatementCreate(billing_period_id=original.id, contract_id=estate[4].id, unit_id=estate[2].id,
        total_cost=300, advance_paid=240, balance=60, status="finalized"))
    definition = ReportDefinition(kind="performance-period-v2", as_of=date(2026, 12, 31))
    assert finance_reports.compute(store, definition)["totals"]["result"] == "1500.00"  # 12*(100+20) + 60
    corrected = store.create_billing_period(BillingPeriodCreate(property_id=estate[1].id, label="NK2026 Korrektur", start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31), status="finalized", revision=2, corrects_period_id=original.id))
    store.create_utility_statement(UtilityStatementCreate(billing_period_id=corrected.id, contract_id=estate[4].id, unit_id=estate[2].id,
        total_cost=220, advance_paid=240, balance=-20, status="finalized"))
    assert finance_reports.compute(store, definition)["totals"]["result"] == "1420.00"  # correction replaces +60 with -20


def test_performance_skips_a_tenancy_that_ended_before_the_period(estate):
    """Every finished tenancy made the period result fail with a server error (its end before the period start)."""
    from backend.models import ContractRentPeriodCreate
    _, house, unit, _, contract, _ = estate
    store.create_contract_rent_period(ContractRentPeriodCreate(contract_id=contract.id, valid_from=date(2026, 1, 1),
        cold_rent=100, service_charge_advance=20))
    earlier = store.create_tenant(TenantCreate(full_name="Vormieter"))
    ended = store.create_contract(ContractCreate(contract_number="V-Vormieter", property_id=house.id, unit_id=unit.id,
        tenant_id=earlier.id, start_date=date(2024, 1, 1), end_date=date(2025, 6, 30), status="terminated"))
    store.create_contract_rent_period(ContractRentPeriodCreate(contract_id=ended.id, valid_from=date(2024, 1, 1), cold_rent=90))
    result = finance_reports.compute(store, ReportDefinition(kind="performance-period-v2", as_of=date(2026, 12, 31)))
    assert result["totals"]["result"] == "1440.00"  # 12 * (100 + 20), nothing of the earlier tenancy
    spring = finance_reports.compute(store, ReportDefinition(kind="performance-period-v2", as_of=date(2026, 12, 31),
                                                             date_from=date(2026, 3, 1), date_to=date(2026, 4, 30)))
    rent = [s for s in spring["sources"] if s["contribution"] == "rent_due"]
    assert sum(Decimal(s["amount"]) for s in rent) == Decimal(spring["totals"]["rent_due"]) == Decimal("240.00")


def test_allocated_sources_refuse_amount_change_and_deletion_and_readonly_can_read_report(estate):
    import json
    r, b = claim(estate), book(estate, 40)
    allocate(store, r.id, command(r, b))
    user = auth.register_user("guard-finance", "guard@example.com", "Finanzen", "Secret123", "eigentuemer")
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(user.id)})
    assert client.patch(f"/api/v1/receivables/{r.id}", json={"amount_due": 200}).status_code == 409
    assert client.patch(f"/api/v1/bookings/{b.id}", json={"amount": 80}).status_code == 409
    assert client.delete(f"/api/v1/bookings/{b.id}").status_code == 409
    assert store.get_receivable(r.id).amount_due == 100 and store.get_booking(b.id).amount == 40
    auth.update_user(user.id, {"role": "readonly"})
    response = client.get("/api/v1/reports/v2/preview", params={"definition": json.dumps({"kind": "liquidity-v2", "as_of": "2026-01-15", "months": 3})})
    assert response.status_code == 200, response.text


def test_hidden_source_blocks_a_fictitious_full_debt_and_still_reserves_its_cash(estate):
    other = store.create_portfolio(PortfolioCreate(name="Anderes Portfolio"))
    house = store.create_property(PropertyCreate(portfolio_id=other.id, name="Anderes Haus", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=house.id, label="B", unit_type="residential", cold_rent=100))
    contract = store.create_contract(ContractCreate(contract_number="VB", property_id=house.id, unit_id=unit.id,
        tenant_id=estate[3].id, start_date=date(2026, 1, 1), status="active"))
    foreign = store.create_receivable(ReceivableCreate(contract_id=contract.id, due_date=date(2026, 1, 1), amount_due=100))
    own, payment = claim(estate), book(estate, 100)
    allocate(store, foreign.id, command(foreign, payment))
    def client_for(name, portfolio):
        user = auth.register_user(name, name + "@example.com", name, "Secret123", "buchhaltung",
                                  portfolio_access="selected", portfolio_ids=[portfolio.id])
        return TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(user.id)})
    cash_owner = client_for("cash-source-owner", estate[0])
    state = cash_owner.get(f"/api/v1/receivables/{own.id}/residual")
    assert state.status_code == 200, state.text
    response = cash_owner.post(f"/api/v1/receivables/{own.id}/settlements", json={
        "expected_revision": state.json()["revision"], "idempotency_key": "hidden-budget-oracle", "booking_id": payment.id,
        "amount": "61", "effective_date": "2026-01-10", "reason": "Zu hoher Betrag"})
    assert response.status_code == 409, response.text  # only 60 remains, despite the hidden target
    claim_owner = client_for("claim-source-owner", other)
    response = claim_owner.get(f"/api/v1/receivables/{foreign.id}/residual")
    assert response.status_code == 403, response.text  # never pretend that all 100 is unpaid
    assert claim_owner.get("/api/v1/reports/receivables-aging").status_code == 403
