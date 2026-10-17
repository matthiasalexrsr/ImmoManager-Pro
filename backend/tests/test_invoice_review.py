"""Invoice review (Rechnungsprüfung): receipt with duplicate key, factual check against order and
contract, arithmetic and § 14 checklist, four-eyes decision, immutable history, payment state with
Skonto, credit notes and disputes, result flowing exactly once, legacy invoices untouched, roles,
portfolio boundary, snapshots and migration.

Runs on the memory store and, with TEST_STORE_BACKEND=sql, on SQLite (PostgreSQL in
test_invoice_review_postgres.py).
"""

import os
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from archive_helpers import purge_originals
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.domain import invoice_review as rules
from backend.invoice_review_models import DecisionRequest
from backend.models import (
    AccountCreate,
    AllocationKeyCreate,
    BillingPeriodCreate,
    BookingCreate,
    ContactCreate,
    ContractCreate,
    DocumentCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.services import invoice_review as service
from backend.services.data_snapshot import clear_business_data, export_snapshot, import_snapshot
from backend.services.file_storage import LocalStorage, get_file_storage

SQL = os.environ.get("TEST_STORE_BACKEND", "memory") == "sql"
API = "/api/v1"
TODAY = date.today()


# ─── the rules themselves ────────────────────────────────────────────────────

def test_duplicate_key_ignores_case_separators_legal_form_and_leading_zeros():
    assert rules.supplier_key("Dach-Müller GmbH & Co. KG") == rules.supplier_key("dach müller")
    assert rules.number_key("RE-0042") == rules.number_key("re 42") == "re42"
    base = rules.InvoiceFacts("a", "Dach Müller GmbH", "RE-0042", date(2026, 5, 1), Decimal("1190.00"))
    others = [rules.InvoiceFacts("b", "DACH MÜLLER", "re 42", date(2025, 1, 1), Decimal("5.00")),          # key
              rules.InvoiceFacts("c", "Dach Müller", "RE-0043", date(2026, 5, 10), Decimal("1190.00")),    # near
              rules.InvoiceFacts("d", "Dach Müller", "RE-0044", date(2026, 6, 30), Decimal("1190.00")),    # far
              rules.InvoiceFacts("e", "Maler Klein", "RE-0042", date(2026, 5, 1), Decimal("1190.00"))]     # other
    found = rules.duplicates(base, others, 14)
    assert [(d["invoice_id"], d["reason"]) for d in found] == [("b", "same_number"), ("c", "same_amount_near_date")]


def test_arithmetic_checks_every_rate_and_the_gross():
    lines: list[dict] = [{"rate": 19, "net": 100, "vat": 19}, {"rate": 7, "net": 50, "vat": 3.5}]
    assert rules.arithmetic_findings(150, 22.5, 172.5, 19, lines) == []
    wrong = rules.arithmetic_findings(150, 22.5, 175, 19, [{"rate": 19, "net": 100, "vat": 17},
                                                           {"rate": 7, "net": 50, "vat": 3.5}])
    codes = {f["code"]: f for f in wrong}
    assert codes["vat_mismatch"]["params"] == {"rate": 19.0, "net": 100.0, "vat": 17.0, "expected": 19.0,
                                               "difference": -2.0}
    assert codes["gross_mismatch"]["params"]["difference"] == 54.5 - 50 and "Abweichung" in codes["gross_mismatch"][
        "message"]
    # one cent is the supplier's rounding, not an error; unknown rates are a warning
    rounding = rules.arithmetic_findings(10.05, 1.92, 11.97, 19, None)
    assert [f["code"] for f in rounding] == ["vat_rounding"]
    assert [f["code"] for f in rules.arithmetic_findings(100, 12, 112, 12, None)] == ["unusual_rate"]
    # older invoices without a VAT amount: gross − net is checked
    assert [f["code"] for f in rules.arithmetic_findings(100, 0, 119, 19, None)] == ["vat_amount_missing"]


def test_section_14_checklist_with_small_invoices_and_findings():
    full = rules.checklist(gross=1190, invoice_date=date(2026, 5, 1), invoice_number=None, has_skonto=True,
                           arithmetic_ok=True, has_service_period=False, small_limit=250, manual={
                               "supplier_name_address": True, "recipient_name_address": True, "tax_number": False})
    assert full["small_invoice"] is False
    assert full["missing"] == ["tax_number", "invoice_number", "description", "service_date", "discount_agreement"]
    findings = rules.checklist_findings(full)
    assert all(f["code"] == "mandatory_field_missing" and f["severity"] == "warning" for f in findings)
    small = rules.checklist(gross=119, invoice_date=date(2026, 5, 1), invoice_number=None, has_skonto=False,
                            arithmetic_ok=True, has_service_period=False, small_limit=250,
                            manual={"supplier_name_address": True, "description": True})
    assert small["small_invoice"] and small["complete"]           # § 33 UStDV: no number, no recipient needed


def test_settlement_partial_approval_credit_dispute_and_skonto():
    pay = rules.Payment
    # partial approval: 1000 of 1190, dispute 190 open; payable 1000
    s = rules.settle(gross=1190, status="partially_approved", approved=1000, dispute_status="open")
    assert (s.payable, s.disputed, s.dispute_open, s.payment_status) == (Decimal("1000.00"), Decimal("190.00"),
                                                                          Decimal("190.00"), "open")
    # a credit note of 150 covers part of the dispute; 40 agreed to be paid after all
    s = rules.settle(gross=1190, status="partially_approved", approved=1000, credits=150, dispute_status="resolved",
                     dispute_outcome="partial_payment", dispute_settled=40, payments=[pay(date(2026, 6, 1), Decimal("1040"))])
    assert (s.payable, s.written_off, s.payment_status, s.open) == (Decimal("1040.00"), Decimal("0.00"), "paid",
                                                                     Decimal("0.00"))
    # credit beyond the dispute reduces what is owed
    s = rules.settle(gross=500, status="approved", credits=50)
    assert s.payable == Decimal("450.00")
    # Skonto: 2 % within 10 days counts when every payment was on time
    on_time = rules.settle(gross=1000, status="approved", skonto_percent=2, skonto_until=date(2026, 5, 11),
                           payments=[pay(date(2026, 5, 10), Decimal("980"))], today=date(2026, 6, 1))
    assert (on_time.payment_status, on_time.skonto_taken, on_time.flow_amount()) == ("paid", Decimal("20.00"),
                                                                                     Decimal("980.00"))
    late = rules.settle(gross=1000, status="approved", skonto_percent=2, skonto_until=date(2026, 5, 11),
                        payments=[pay(date(2026, 5, 12), Decimal("980"))], due_on=date(2026, 5, 31), today=date(2026, 6, 1))
    assert (late.payment_status, late.open, late.overdue) == ("partially_paid", Decimal("20.00"), True)
    over = rules.settle(gross=100, status="approved", payments=[pay(date(2026, 5, 1), Decimal("120"))])
    assert over.payment_status == "overpaid" and over.findings[0]["code"] == "overpaid"
    assert rules.settle(gross=100, status="rejected").flow_amount() == 0
    assert rules.settle(gross=100, status="legacy").flow_amount() is None
    assert rules.settle(gross=100, status="received").flow_amount() == Decimal("100.00")


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean():
    purge_originals(store)
    clear_business_data(store)
    auth.clear_users()
    yield
    purge_originals(store)
    clear_business_data(store)
    auth.clear_users()


def _user(name, role="verwalter", portfolios=(), mode="all"):
    return auth.register_user(name, f"{name}@example.com", name.title(), "Secret123", role,
                              portfolio_access=mode, portfolio_ids=[p.id for p in portfolios])


def _client(user) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})


def _estate(name="Nord"):
    portfolio = store.create_portfolio(PortfolioCreate(name=f"Bestand {name}"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name=f"Haus {name}",
                                                property_type="residential", address_line="Bautzner Straße 61",
                                                postal_code="01099", city="Dresden"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="WE 3", unit_type="residential", area_sqm=60))
    account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name=f"Konto {name}", account_type="bank"))
    return {"portfolio": portfolio, "property": prop, "unit": unit, "account": account}


@pytest.fixture
def estate():
    return _estate()


@pytest.fixture
def owner():
    return _client(_user("owner", "eigentuemer"))


def _ok(response, code=200):
    assert response.status_code == code, response.text
    return response.json() if response.content else None


def _error(response, code):
    assert response.status_code == code, response.text
    return response.json()["error"]["message"]


def _invoice(client, estate, gross=1190, net=1000, number="RE-1", supplier="Dach Müller GmbH",
             day=None, **extra):
    return _ok(client.post(f"{API}/invoices", json={
        "property_id": estate["property"].id, "supplier": supplier, "invoice_number": number,
        "invoice_date": (day or TODAY - timedelta(days=5)).isoformat(), "net_amount": net,
        "vat_amount": round(gross - net, 2), "vat_rate": 19, "gross_amount": gross, **extra}), 201)


def _receive(client, invoice_id, **extra):
    return client.post(f"{API}/invoices/{invoice_id}/review", json={"received_on": TODAY.isoformat(), **extra})


def _view(client, invoice_id):
    return _ok(client.get(f"{API}/invoices/{invoice_id}/review"))


def _check(client, invoice_id, kind, result="confirmed", **extra):
    return client.post(f"{API}/invoices/{invoice_id}/review/{kind}-check", json={"result": result, **extra})


COMPLETE: dict[str, bool | None] = {key: True for key in ("supplier_name_address", "recipient_name_address", "tax_number", "description",
                                  "service_date", "discount_agreement")}


def _checked(client, invoice_id, checker=None):
    _ok(_check(checker or client, invoice_id, "factual"))
    _ok(_check(checker or client, invoice_id, "arithmetic", checklist=COMPLETE))


def _decide(client, invoice_id, decision="approve", **extra):
    return client.post(f"{API}/invoices/{invoice_id}/review/decision", json={"decision": decision, **extra})


def _booking(estate, amount, day=None):
    return store.create_booking(BookingCreate(account_id=estate["account"].id, property_id=estate["property"].id,
                                              booking_date=day or TODAY, amount=amount))


def _pay(client, invoice_id, booking, amount):
    return client.post(f"{API}/invoices/{invoice_id}/payments", json={"booking_id": booking.id, "amount": amount})


def _document(estate, content=b"%PDF-1.4 Rechnung RE-1", **extra):
    key = f"documents/review-{os.urandom(4).hex()}.pdf"
    get_file_storage().save(key, BytesIO(content))
    return store.create_document(DocumentCreate(title="Rechnung", file_url=f"/uploads/{key}",
                                                property_id=estate["property"].id, **extra)), key


def _history(client, invoice_id):
    return [e["action"] for e in _view(client, invoice_id)["history"]]


# ─── receipt and duplicates ──────────────────────────────────────────────────

def test_receipt_records_original_and_refuses_a_duplicate_key_without_reason(owner, estate):
    document, key = _document(estate)
    first = _invoice(owner, estate, number="RE-0042")
    result = _ok(_receive(owner, first["id"], document_id=document.id, skonto_percent=2, skonto_days=10,
                          payment_days=30), 201)
    review = result["review"]
    assert review["status"] == "received" and len(review["document_sha256"]) == 64
    assert review["skonto_until"] == (date.fromisoformat(first["invoice_date"]) + timedelta(days=10)).isoformat()
    assert review["due_on"] == (date.fromisoformat(first["invoice_date"]) + timedelta(days=30)).isoformat()
    assert _ok(owner.get(f"{API}/invoices/{first['id']}"))["source_document_id"] == document.id
    view = _view(owner, first["id"])
    assert view["document"]["integrity"] == "unchanged" and view["status"] == "received"
    assert _receive(owner, first["id"]).status_code == 409                      # one receipt per invoice

    # same supplier and number (written differently): refused, then accepted with a reason
    twin = _invoice(owner, estate, number="re 42", supplier="DACH MÜLLER", gross=50, net=42.02)
    assert "Dublette" in _error(_receive(owner, twin["id"]), 409)
    assert _receive(owner, twin["id"], accept_duplicate=True).status_code == 422          # reason required
    _ok(_receive(owner, twin["id"], accept_duplicate=True, duplicate_reason="Teilrechnung mit gleicher Nummer"), 201)
    assert _history(owner, twin["id"]) == ["received", "duplicate_acknowledged"]

    # same supplier, same amount, near date: a warning, no refusal
    near = _invoice(owner, estate, number="RE-0043")
    _ok(_receive(owner, near["id"]), 201)
    view = _view(owner, near["id"])
    assert [d["reason"] for d in view["duplicates"]] == ["same_amount_near_date"]
    assert "possible_duplicate" in {f["code"] for f in view["findings"]}
    check = _ok(owner.get(f"{API}/invoice-review/duplicates", params={
        "supplier": "Dach Müller", "invoice_number": "RE 42", "gross_amount": 1, "invoice_date": TODAY.isoformat()}))
    assert {d["invoice_id"] for d in check["duplicates"]} == {first["id"], twin["id"]}

    # The public storage API never permits overwriting existing invoice
    # originals, even from the same name. Simulate corruption OUTSIDE the
    # application only on this disposable local QA store, then ensure the
    # invoice verifier detects the changed original without repairing it.
    storage = get_file_storage()
    assert isinstance(storage, LocalStorage)
    original = storage.get(key)
    with pytest.raises(ValueError, match="Originalbytes"):
        storage.save(key, BytesIO(b"%PDF-1.4 manipuliert"))
    assert storage.get(key) == original
    local_path = storage.base_dir / key
    assert local_path.resolve().is_relative_to(storage.base_dir.resolve())
    local_path.write_bytes(b"%PDF-1.4 manipuliert")
    view = _view(owner, first["id"])
    assert view["document"]["integrity"] == "changed" and "document_changed" in {f["code"] for f in view["findings"]}


def test_duplicate_check_and_receipt_scan_past_500_unrelated_candidates(owner, estate):
    from backend.models import InvoiceCreate

    for index in range(501):
        store.create_invoice(InvoiceCreate.model_validate({
            "property_id": estate["property"].id, "supplier": f"Anderer Lieferant {index}",
            "invoice_date": TODAY, "invoice_number": f"FREMD-42-{index}",
            "net_amount": 1000, "vat_amount": 190, "gross_amount": 1190,
        }))
    actual = _invoice(owner, estate, number="RE-0042", day=TODAY - timedelta(days=365))
    check = _ok(owner.get(f"{API}/invoice-review/duplicates", params={
        "supplier": "DACH MÜLLER", "invoice_number": "re 42", "gross_amount": 50,
        "invoice_date": TODAY.isoformat()}))
    assert [(item["invoice_id"], item["reason"]) for item in check["duplicates"]] == [
        (actual["id"], "same_number")]
    duplicate = _invoice(owner, estate, number="re 42", supplier="DACH MÜLLER", gross=50, net=42.02)
    assert "Dublette" in _error(_receive(owner, duplicate["id"]), 409)


def test_new_invoice_and_receipt_in_one_step(owner, estate):
    created = _ok(owner.post(f"{API}/invoice-review/receipts", json={
        "received_on": TODAY.isoformat(), "property_id": estate["property"].id, "cost_category": "Reinigung",
        "recoverable": True,
        "invoice": {"property_id": estate["property"].id, "supplier": "Glanz GmbH", "invoice_number": "G-7",
                    "invoice_date": TODAY.isoformat(), "net_amount": 100, "vat_rate": 19, "gross_amount": 119}}), 201)
    assert created["invoice"]["vat_amount"] == 19.0 and created["review"]["recoverable"] is True
    # a refused receipt leaves no invoice behind
    before = len(_ok(owner.get(f"{API}/invoices")))
    bad = owner.post(f"{API}/invoice-review/receipts", json={
        "unit_id": "missing", "invoice": {"supplier": "X", "invoice_date": TODAY.isoformat(), "net_amount": 1,
                                          "gross_amount": 1}})
    assert bad.status_code == 404
    assert len(_ok(owner.get(f"{API}/invoices"))) == before


# ─── factual check ───────────────────────────────────────────────────────────

def _order(client, estate, gross=1190):
    case = _ok(client.post(f"{API}/maintenance", json={"property_id": estate["property"].id, "title": "Dach"}), 201)
    base = f"{API}/maintenance/{case['id']}"
    quote = _ok(client.post(f"{base}/quotes", json={"quote_date": "2026-04-01", "net_amount": round(gross / 1.19, 2),
                                                    "gross_amount": gross, "supplier_name": "Dach Müller GmbH"}), 201)
    order = _ok(client.post(f"{base}/quotes/{quote['id']}/accept", json={"order_number": "A-7"}), 201)
    return case, order


def _link(client, case, order, invoice):
    return _ok(client.post(f"{API}/maintenance/{case['id']}/orders/{order['id']}/invoices",
                           json={"invoice_id": invoice["id"]}), 201)


def test_factual_check_against_order_change_order_and_technician_rights(owner, estate):
    case, order = _order(owner, estate, gross=1190)
    base = f"{API}/maintenance/{case['id']}"
    change = _ok(owner.post(f"{base}/orders/{order['id']}/change-orders",
                            json={"title": "Zusätzliche Rinne", "net_amount": 100, "gross_amount": 119}), 201)
    _ok(owner.post(f"{base}/change-orders/{change['id']}/approve", json={}))
    first = _invoice(owner, estate, gross=1000, net=840.34, number="T-1")
    second = _invoice(owner, estate, gross=476, net=400, number="T-2")
    _link(owner, case, order, first)
    _link(owner, case, order, second)
    _ok(_receive(owner, second["id"], change_order_id=change["id"]), 201)
    view = _view(owner, second["id"])
    assert view["assignment"]["kind"] == "maintenance_order"
    found = {f["code"]: f["params"] for f in view["factual_findings"]}
    # ordered 1190 + 119 = 1309; billed 1000 + 476 = 1476
    assert found["over_order"]["difference"] == 167.0 and found["over_order"]["ordered"] == 1309.0
    assert found["over_change_order"]["difference"] == 357.0

    tech = _client(_user("tech", "techniker"))
    books = _client(_user("books", "buchhaltung"))
    assert _check(books, second["id"], "factual").status_code == 403          # not the bookkeeper's
    _ok(_check(tech, second["id"], "factual"))                               # on site: confirmed
    assert _check(tech, second["id"], "arithmetic").status_code == 403
    assert _decide(tech, second["id"]).status_code == 403
    free = _invoice(owner, estate, number="T-3", supplier="Maler Klein")
    _ok(_receive(owner, free["id"]), 201)
    assert "Instandhaltungsauftrag" in _error(_check(tech, free["id"], "factual"), 403)
    assert _view(tech, free["id"])["abilities"]["factual_check"] is False
    assert _view(tech, second["id"])["abilities"] == {**_view(tech, second["id"])["abilities"], "decide": False}
    # a change order of another order, or not approved, is refused
    other_case, other_order = _order(owner, estate)
    proposed = _ok(owner.post(f"{API}/maintenance/{other_case['id']}/orders/{other_order['id']}/change-orders",
                              json={"title": "Fremd", "net_amount": 1, "gross_amount": 1.19}), 201)
    _ok(_receive(owner, first["id"]), 201)
    assert owner.patch(f"{API}/invoices/{first['id']}/review",
                       json={"change_order_id": proposed["id"]}).status_code == 409


def _contract(client, estate, provider):
    body = {"contract_type": "electricity", "title": "Allgemeinstrom", "provider_contact_id": provider.id,
            "start_date": "2026-01-01", "minimum_term_months": 12, "renewal_mode": "none", "recoverable": True,
            "locations": [{"property_id": estate["property"].id}],
            "tariff": {"valid_from": "2026-01-01", "advance_amount": 100, "advance_interval": "monthly"}}
    return _ok(client.post(f"{API}/service-contracts", json=body), 201)["id"]


def _bill(client, contract, gross, number, start, end, day="2026-07-05"):
    return _ok(client.post(f"{API}/service-contracts/{contract}/invoices", json={
        "period_start": start, "period_end": end,
        "invoice": {"supplier": "Stadtwerke", "invoice_date": day, "net_amount": gross, "vat_amount": 0,
                    "vat_rate": 0, "gross_amount": gross, "invoice_number": number}}), 201)


def test_factual_check_against_service_contract_tariff_and_overlapping_periods(owner, estate):
    provider = store.create_contact(ContactCreate(contact_type="supplier", company_name="Stadtwerke"))
    contract = _contract(owner, estate, provider)
    first = _bill(owner, contract, 600, "SW-1", "2026-01-01", "2026-06-30")
    second = _bill(owner, contract, 650, "SW-2", "2026-06-01", "2026-07-31")
    _ok(_receive(owner, first["invoice_id"]), 201)
    view = _view(owner, first["invoice_id"])
    assert view["assignment"]["kind"] == "service_contract" and view["factual_findings"] == []   # 6 × 100
    assert view["checklist"]["items"][6] == {"key": "service_date", "label": view["checklist"]["items"][6]["label"],
                                             "required": True, "present": True, "source": "auto"}
    _checked(owner, first["invoice_id"])
    _ok(_decide(owner, first["invoice_id"]))
    _ok(_receive(owner, second["invoice_id"]), 201)
    found = {f["code"]: f["params"] for f in _view(owner, second["invoice_id"])["factual_findings"]}
    assert found["tariff_deviation"] == {"expected": 200.0, "actual": 650.0, "difference": 450.0}
    assert found["period_overlap"]["invoice_number"] == "SW-1"


# ─── arithmetic check and checklist ──────────────────────────────────────────

def test_arithmetic_check_records_vat_lines_and_missing_fields_as_findings(owner, estate):
    invoice = _invoice(owner, estate, gross=172.5, net=150, number=None)
    _ok(_receive(owner, invoice["id"], vat_lines=[{"rate": 19, "net": 100, "vat": 19}, {"rate": 7, "net": 50,
                                                                                         "vat": 2.5}]), 201)
    view = _view(owner, invoice["id"])
    codes = {f["code"] for f in view["findings"]}
    assert {"vat_mismatch", "gross_mismatch", "mandatory_field_missing"} <= codes
    assert view["checklist"]["small_invoice"] is True
    # missing fields are findings: approving with an objection needs a partial approval or a rejection
    _ok(_check(owner, invoice["id"], "factual"))
    assert _check(owner, invoice["id"], "arithmetic", result="objected").status_code == 422     # needs a reason
    _ok(_check(owner, invoice["id"], "arithmetic", result="objected", note="7 %-Steuer falsch"))
    assert "Beanstandungen" in _error(_decide(owner, invoice["id"]), 409)
    assert _check(owner, invoice["id"], "arithmetic", checklist={"unknown": True}).status_code == 409
    fixed = _ok(owner.patch(f"{API}/invoices/{invoice['id']}/review", json={
        "vat_lines": [{"rate": 19, "net": 100, "vat": 19}, {"rate": 7, "net": 50, "vat": 3.5}],
        "reason": "Korrigierte Aufschlüsselung"}))
    assert fixed["vat_lines"][1]["vat"] == 3.5
    view = _view(owner, invoice["id"])
    assert not {"vat_mismatch", "gross_mismatch"} & {f["code"] for f in view["findings"]}
    assert _history(owner, invoice["id"]) == ["received", "factual_check", "arithmetic_check", "receipt_changed"]


# ─── decision ────────────────────────────────────────────────────────────────

def test_four_eyes_above_the_limit(owner, estate):
    assert owner.put(f"{API}/invoice-review/settings", json={"four_eyes_limit": 1000}).status_code == 200
    books = _client(_user("books", "buchhaltung"))
    manager = _client(_user("anna", "verwalter"))
    other = _client(_user("bert", "verwalter"))
    assert books.put(f"{API}/invoice-review/settings", json={"four_eyes_limit": 1}).status_code == 403
    assert _ok(books.get(f"{API}/invoice-review/settings"))["four_eyes_limit"] == 1000.0

    small = _invoice(owner, estate, gross=595, net=500, number="S-1")
    _ok(_receive(books, small["id"]), 201)
    _ok(_check(manager, small["id"], "factual"))
    _ok(_check(books, small["id"], "arithmetic", checklist=COMPLETE))
    _ok(_decide(books, small["id"]))                                     # within the limit: bookkeeping decides

    big = _invoice(owner, estate, gross=1190, net=1000, number="B-1")
    _ok(_receive(books, big["id"]), 201)
    assert "Freigabe" in _decide(books, big["id"]).text                   # checks missing
    _ok(_check(manager, big["id"], "factual"))
    _ok(_check(books, big["id"], "arithmetic", checklist=COMPLETE))
    assert _view(books, big["id"])["four_eyes"]["required"] is True
    assert "Vier-Augen" in _error(_decide(books, big["id"]), 403)
    assert "Vier-Augen" in _error(_decide(manager, big["id"]), 409)       # the one who checked
    approved = _ok(_decide(other, big["id"]))
    assert approved["status"] == "approved" and approved["approved_amount"] == 1190.0
    history = _view(owner, big["id"])["history"]
    assert [(e["action"], e["actor_name"]) for e in history][-1] == ("approved", "Bert")
    assert history[-1]["details"]["four_eyes"] is True


def test_rights_are_checked_again_inside_the_transaction(owner, estate):
    books = _user("books2", "buchhaltung")
    invoice = _invoice(owner, estate)
    _ok(_receive(owner, invoice["id"]), 201)
    _checked(owner, invoice["id"])
    auth.update_user(books.id, {"role": "readonly"})
    with pytest.raises(HTTPException) as refused:
        service.decide(store, invoice["id"], DecisionRequest(decision="approve"), books.id)
    assert refused.value.status_code == 403
    assert _view(owner, invoice["id"])["status"] == "received"


def test_partial_approval_dispute_credit_note_and_result(owner, estate):
    case, order = _order(owner, estate, gross=1190)
    invoice = _invoice(owner, estate, gross=1190, net=1000, number="P-1")
    _link(owner, case, order, invoice)
    _ok(_receive(owner, invoice["id"]), 201)
    _ok(_check(owner, invoice["id"], "factual", result="objected", note="Rinne nicht montiert"))
    _ok(_check(owner, invoice["id"], "arithmetic", checklist=COMPLETE))
    assert _decide(owner, invoice["id"], "partial", amount=990).status_code == 422          # reason required
    assert _decide(owner, invoice["id"], "partial", amount=1190, reason="x").status_code == 409
    _ok(_decide(owner, invoice["id"], "partial", amount=990, reason="Rinne fehlt (200 €)"))
    view = _view(owner, invoice["id"])
    assert (view["status"], view["review"]["dispute_status"]) == ("partially_approved", "open")
    assert view["settlement"]["payable"] == 990.0 and view["settlement"]["dispute_open"] == 200.0
    costs = _ok(owner.get(f"{API}/maintenance/{case['id']}/costs"))
    assert costs["invoiced"] == 990.0                                      # the approved amount feeds the project
    # proposed for payment: the approved part only
    proposal = {p["invoice_id"]: p for p in _ok(owner.get(f"{API}/invoice-review/payment-proposals"))["items"]}
    assert proposal[invoice["id"]]["proposed_amount"] == 990.0 and proposal[invoice["id"]]["dispute_open"] == 200.0
    _ok(_pay(owner, invoice["id"], _booking(estate, -990), 990), 201)
    assert _view(owner, invoice["id"])["settlement"]["payment_status"] == "paid"
    assert invoice["id"] not in {p["invoice_id"] for p in
                                 _ok(owner.get(f"{API}/invoice-review/payment-proposals"))["items"]}

    # the supplier's credit note of 150 links to the invoice; the rest is written off
    credit = _invoice(owner, estate, gross=150, net=126.05, number="GS-1")
    assert _receive(owner, credit["id"], kind="credit_note").status_code == 422             # names its invoice
    _ok(_receive(owner, credit["id"], kind="credit_note", credit_for_invoice_id=invoice["id"]), 201)
    assert _check(owner, credit["id"], "factual").status_code == 409                       # nothing delivered
    _ok(_check(owner, credit["id"], "arithmetic", checklist=COMPLETE))
    assert "Gutschrift" in _error(owner.post(f"{API}/invoice-review/../invoices/{credit['id']}/payments",
                                             json={"booking_id": _booking(estate, -1).id, "amount": 1}), 409)
    _ok(_decide(owner, credit["id"]))
    view = _view(owner, invoice["id"])
    assert view["settlement"]["dispute_open"] == 50.0 and view["credit_notes"][0]["status"] == "approved"
    assert owner.post(f"{API}/invoices/{invoice['id']}/review/dispute",
                      json={"outcome": "partial_payment", "amount": 60, "reason": "zu viel"}).status_code == 409
    _ok(owner.post(f"{API}/invoices/{invoice['id']}/review/dispute",
                   json={"outcome": "credit", "reason": "Gutschrift erhalten, Rest ausgebucht"}))
    view = _view(owner, invoice["id"])
    assert view["settlement"]["written_off"] == 50.0 and view["settlement"]["dispute_open"] == 0.0
    assert view["review"]["dispute_outcome"] == "credit"
    assert _history(owner, invoice["id"])[-3:] == ["partially_approved", "dispute_opened", "dispute_resolved"]
    assert _ok(owner.get(f"{API}/maintenance/{case['id']}/costs"))["invoiced"] == 990.0      # exactly once


def test_dispute_settled_by_partial_payment(owner, estate):
    invoice = _invoice(owner, estate, gross=1190, net=1000, number="D-1")
    _ok(_receive(owner, invoice["id"], property_id=estate["property"].id), 201)
    _checked(owner, invoice["id"])
    _ok(_decide(owner, invoice["id"], "partial", amount=1000, reason="Stundenzahl strittig"))
    _ok(owner.post(f"{API}/invoices/{invoice['id']}/review/dispute",
                   json={"outcome": "partial_payment", "amount": 90, "reason": "Einigung"}))
    settlement = _view(owner, invoice["id"])["settlement"]
    assert (settlement["payable"], settlement["written_off"], settlement["dispute_settled"]) == (1090.0, 100.0, 90.0)
    assert owner.post(f"{API}/invoices/{invoice['id']}/review/dispute",
                      json={"outcome": "written_off", "reason": "nochmal"}).status_code == 409


def test_reject_and_query_and_a_rejected_invoice_flows_nowhere(owner, estate):
    case, order = _order(owner, estate, gross=1190)
    invoice = _invoice(owner, estate, gross=1190, net=1000, number="R-1")
    _link(owner, case, order, invoice)
    _ok(_receive(owner, invoice["id"], recoverable=True), 201)
    assert _decide(owner, invoice["id"], "query").status_code == 422                       # reason required
    assert _ok(_decide(owner, invoice["id"], "query", reason="Aufmaß fehlt"))["status"] == "query"
    assert _ok(owner.get(f"{API}/maintenance/{case['id']}/costs"))["invoiced"] == 1190.0   # still billed
    _ok(_decide(owner, invoice["id"], "reject", reason="Leistung nicht erbracht"))
    assert _ok(owner.get(f"{API}/maintenance/{case['id']}/costs"))["invoiced"] == 0.0
    assert "abgelehnt" in _error(_pay(owner, invoice["id"], _booking(estate, -1190), 1190), 409)
    assert invoice["id"] not in {p["invoice_id"] for p in
                                 _ok(owner.get(f"{API}/invoice-review/payment-proposals"))["items"]}
    period = store.create_billing_period(BillingPeriodCreate(property_id=estate["property"].id, label="BK",
                                                             start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)))
    key = store.create_allocation_key(AllocationKeyCreate(property_id=estate["property"].id, name="Fläche",
                                                          key_type="area_sqm"))
    assert owner.post(f"{API}/invoices/{invoice['id']}/review/cost-transfer",
                      json={"billing_period_id": period.id, "allocation_key_id": key.id}).status_code == 409
    assert _decide(owner, invoice["id"]).status_code == 409                                 # decided is decided
    other_case, other_order = _order(owner, estate)
    assert owner.post(f"{API}/maintenance/{other_case['id']}/orders/{other_order['id']}/invoices",
                      json={"invoice_id": invoice["id"]}).status_code == 409
    assert _history(owner, invoice["id"]) == ["received", "query", "rejected"]


def test_rejected_service_contract_bill_is_not_transferred(owner, estate):
    provider = store.create_contact(ContactCreate(contact_type="supplier", company_name="Stadtwerke"))
    contract = _contract(owner, estate, provider)
    good = _bill(owner, contract, 600, "SW-1", "2026-01-01", "2026-06-30")
    bad = _bill(owner, contract, 650, "SW-2", "2026-07-01", "2026-12-31")
    _ok(_receive(owner, bad["invoice_id"]), 201)
    _ok(_decide(owner, bad["invoice_id"], "reject", reason="doppelt"))
    period = store.create_billing_period(BillingPeriodCreate(property_id=estate["property"].id, label="BK 2026",
                                                             start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)))
    key = store.create_allocation_key(AllocationKeyCreate(property_id=estate["property"].id, name="Fläche",
                                                          key_type="area_sqm"))
    result = _ok(owner.post(f"{API}/service-contracts/{contract}/cost-transfers",
                            json={"billing_period_id": period.id, "allocation_key_id": key.id}), 201)
    assert [item["amount"] for item in result["created"]] == [600.0]
    assert result["skipped"] == [{"service_contract_invoice_id": bad["id"], "reason": "rejected"}]
    recon = _ok(owner.get(f"{API}/service-contracts/{contract}/reconciliation",
                          params={"date_from": "2026-01-01", "date_to": "2026-12-31"}))
    assert recon["invoiced"] == 600.0
    bills = {b["invoice_id"]: b for b in _ok(owner.get(f"{API}/service-contracts/{contract}/invoices"))}
    assert bills[bad["invoice_id"]]["review"] == {"status": "rejected", "amount": 0.0}
    assert bills[good["invoice_id"]]["review"] is None                        # legacy: unchanged


# ─── history ─────────────────────────────────────────────────────────────────

def test_history_is_immutable(owner, estate):
    invoice = _invoice(owner, estate)
    _ok(_receive(owner, invoice["id"]), 201)
    _checked(owner, invoice["id"])
    _ok(_decide(owner, invoice["id"]))
    events = _view(owner, invoice["id"])["history"]
    assert [e["seq"] for e in events] == [1, 2, 3, 4]
    assert all(e["actor_name"] == "Owner" and e["actor_role"] == "eigentuemer" for e in events)
    # after the decision: no more changes of the receipt, the checks or the invoice's reviewed facts
    assert owner.patch(f"{API}/invoices/{invoice['id']}/review", json={"cost_category": "x"}).status_code == 409
    assert _check(owner, invoice["id"], "factual").status_code == 409
    assert "geprüft" in _error(owner.patch(f"{API}/invoices/{invoice['id']}", json={"gross_amount": 2380, "net_amount": 2000, "vat_amount": 380}), 409)
    _ok(owner.patch(f"{API}/invoices/{invoice['id']}", json={"notes": "bezahlt per Überweisung"}))
    assert "Prüfverlauf" in _error(owner.delete(f"{API}/invoices/{invoice['id']}"), 409)
    bulk = _ok(owner.post(f"{API}/admin/bulk-delete/invoices", json={"ids": [invoice["id"]]}))
    assert bulk["deleted"] == 0
    if SQL:
        from sqlalchemy import text

        with pytest.raises(Exception, match="immutable"):
            store.db.execute(text("UPDATE invoice_review_events SET reason = 'geändert'"))
        store.db.rollback()
    assert [e["reason"] for e in _view(owner, invoice["id"])["history"]] == [e["reason"] for e in events]


# ─── payment ─────────────────────────────────────────────────────────────────

def test_explicit_service_contract_payments_and_refunds_reach_the_invoice(owner, estate):
    provider = store.create_contact(ContactCreate(contact_type="supplier", company_name="Stadtwerke"))
    contract = _contract(owner, estate, provider)
    bill = _bill(owner, contract, 100, "SW-ZAHLUNG", "2026-01-01", "2026-06-30")
    invoice_id = bill["invoice_id"]
    _ok(_receive(owner, invoice_id), 201)
    _ok(owner.patch(f"{API}/invoices/{invoice_id}", json={"due_date": (TODAY - timedelta(days=1)).isoformat()}))
    _checked(owner, invoice_id)
    _ok(_decide(owner, invoice_id))
    payment = _booking(estate, -100)
    _ok(owner.post(f"{API}/service-contracts/{contract}/payments", json={
        "booking_id": payment.id, "service_contract_invoice_id": bill["id"]}), 201)
    settlement = _view(owner, invoice_id)["settlement"]
    assert (settlement["paid"], settlement["open"], settlement["payment_status"]) == (100, 0, "paid")
    assert not _ok(owner.get(f"{API}/invoice-review/payment-proposals"))["items"]
    assert _ok(owner.get(f"{API}/invoice-review/inbox", params={"due": "overdue"}))["total"] == 0

    refund = _booking(estate, 20)
    _ok(owner.post(f"{API}/service-contracts/{contract}/payments", json={
        "booking_id": refund.id, "service_contract_invoice_id": bill["id"]}), 201)
    settlement = _view(owner, invoice_id)["settlement"]
    assert (settlement["paid"], settlement["open"]) == (80, 20)
    assert _ok(owner.get(f"{API}/invoice-review/payment-proposals"))["items"][0]["proposed_amount"] == 20
    due = _ok(owner.get(f"{API}/invoice-review/inbox", params={"due": "overdue", "limit": 1}))
    assert due["total"] == 1 and due["items"][0]["invoice_id"] == invoice_id


def test_payment_status_with_skonto_and_overpayment(owner, estate):
    invoice = _invoice(owner, estate, gross=1190, net=1000, day=TODAY - timedelta(days=3))
    _ok(_receive(owner, invoice["id"], skonto_percent=2, skonto_days=10, payment_days=30,
                 property_id=estate["property"].id), 201)
    _checked(owner, invoice["id"])
    _ok(_decide(owner, invoice["id"]))
    proposal = _ok(owner.get(f"{API}/invoice-review/payment-proposals"))["items"][0]
    assert (proposal["proposed_amount"], proposal["skonto_amount"]) == (1166.2, 23.8)
    assert proposal["pay_by"] == (TODAY + timedelta(days=7)).isoformat()
    _ok(_pay(owner, invoice["id"], _booking(estate, -1000), 1000), 201)
    assert _view(owner, invoice["id"])["settlement"]["payment_status"] == "partially_paid"
    _ok(_pay(owner, invoice["id"], _booking(estate, -166.2), 166.2), 201)
    settlement = _view(owner, invoice["id"])["settlement"]
    assert (settlement["payment_status"], settlement["skonto_taken"], settlement["flow_amount"]) == (
        "paid", 23.8, 1166.2)
    inbox = _ok(owner.get(f"{API}/invoice-review/inbox", params={"skonto": True}))
    assert inbox["total"] == 0                                                 # nothing left to pay with Skonto

    over = _invoice(owner, estate, gross=119, net=100, number="O-1")
    _ok(_receive(owner, over["id"]), 201)
    _checked(owner, over["id"])
    _ok(_decide(owner, over["id"], "partial", amount=100, reason="Anfahrt nicht vereinbart"))
    _ok(_pay(owner, over["id"], _booking(estate, -119), 119), 201)             # paid in full before the decision
    settlement = _view(owner, over["id"])["settlement"]
    assert settlement["payment_status"] == "overpaid" and "overpaid" in {f["code"] for f in settlement["findings"]}


def test_inbox_due_filter_uses_resolved_credit_and_dispute_balances_before_paging(owner, estate):
    credited = _invoice(owner, estate, gross=100, net=100, number="C-BASE", vat_rate=0,
                        due_date=(TODAY - timedelta(days=2)).isoformat())
    partial = _invoice(owner, estate, gross=100, net=100, number="P-BASE", vat_rate=0,
                       due_date=(TODAY - timedelta(days=1)).isoformat())
    for invoice in (credited, partial):
        _ok(_receive(owner, invoice["id"]), 201)
        _checked(owner, invoice["id"])
    _ok(_decide(owner, credited["id"]))
    _ok(_decide(owner, partial["id"], "partial", amount=50, reason="Teilbetrag"))
    _ok(owner.post(f"{API}/invoices/{partial['id']}/review/dispute", json={
        "outcome": "partial_payment", "amount": 20, "reason": "Nachprüfung"}))
    _ok(_pay(owner, partial["id"], _booking(estate, -50), 50), 201)
    credit = _invoice(owner, estate, gross=100, net=100, number="C-NOTE", vat_rate=0)
    _ok(_receive(owner, credit["id"], kind="credit_note", credit_for_invoice_id=credited["id"]), 201)
    _ok(_check(owner, credit["id"], "arithmetic"))
    _ok(_decide(owner, credit["id"]))
    result = _ok(owner.get(f"{API}/invoice-review/inbox", params={"due": "overdue", "limit": 1}))
    assert result["total"] == 1 and result["has_more"] is False
    assert [(row["invoice_id"], row["settlement"]["open"]) for row in result["items"]] == [(partial["id"], 20)]


def test_inbox_filters_count_before_paging(owner, estate):
    south = _estate("Süd")
    overdue = _invoice(owner, estate, number="I-1", supplier="Alpha", day=TODAY - timedelta(days=60),
                       due_date=(TODAY - timedelta(days=30)).isoformat())
    _invoice(owner, estate, number="I-2", supplier="Beta")                    # legacy, not due
    skonto = _invoice(owner, south, number="I-3", supplier="Gamma")
    _ok(_receive(owner, skonto["id"], skonto_percent=3, skonto_days=14), 201)
    _ok(_receive(owner, overdue["id"]), 201)

    def ids(**params):
        page = _ok(owner.get(f"{API}/invoice-review/inbox", params=params))
        return page["total"], [row["invoice_id"] for row in page["items"]]

    assert ids()[0] == 3
    assert ids(status="legacy")[0] == 1
    assert ids(status="pending")[0] == 2
    assert ids(due="overdue") == (1, [overdue["id"]])
    assert ids(skonto=True) == (1, [skonto["id"]])
    assert ids(property_id=south["property"].id) == (1, [skonto["id"]])
    assert ids(q="alp") == (1, [overdue["id"]])
    first = _ok(owner.get(f"{API}/invoice-review/inbox", params={"limit": 2}))
    second = _ok(owner.get(f"{API}/invoice-review/inbox", params={"limit": 2, "skip": 2}))
    assert first["has_more"] and not second["has_more"] and first["total"] == 3
    assert len({row["invoice_id"] for row in first["items"] + second["items"]}) == 3
    row = next(r for r in first["items"] + second["items"] if r["invoice_id"] == overdue["id"])
    assert row["settlement"]["overdue"] is False                              # not approved: nothing payable yet


# ─── result: utility billing, once ───────────────────────────────────────────

def test_recoverable_approved_invoice_enters_the_utility_billing_once(owner, estate):
    period = store.create_billing_period(BillingPeriodCreate(property_id=estate["property"].id, label="BK 2026",
                                                             start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)))
    key = store.create_allocation_key(AllocationKeyCreate(property_id=estate["property"].id, name="Fläche",
                                                          key_type="area_sqm"))
    invoice = _invoice(owner, estate, gross=595, net=500, number="H-1", supplier="Hauswart Meier")
    _ok(_receive(owner, invoice["id"], cost_category="hauswart"), 201)
    _checked(owner, invoice["id"])
    _ok(_decide(owner, invoice["id"]))
    body = {"billing_period_id": period.id, "allocation_key_id": key.id}
    path = f"{API}/invoices/{invoice['id']}/review/cost-transfer"
    assert "umlagefähig" in _error(owner.post(path, json=body), 409)
    tech = _client(_user("tech", "techniker"))
    assert tech.post(path, json=body).status_code == 403
    # the free assignment is fixed after the decision; a new receipt for a recoverable one
    other = _invoice(owner, estate, gross=595, net=500, number="H-2", supplier="Hauswart Meier")
    _ok(_receive(owner, other["id"], cost_category="hauswart", recoverable=True,
                 property_id=estate["property"].id), 201)
    _checked(owner, other["id"])
    _ok(_decide(owner, other["id"]))
    books = _client(_user("books", "buchhaltung"))
    created = _ok(books.post(f"{API}/invoices/{other['id']}/review/cost-transfer", json=body), 201)
    assert created["cost_item"]["amount"] == 595.0 and created["cost_item"]["net_amount"] == 500.0
    assert created["cost_item"]["cost_category"] == "hauswart"
    assert "nur einmal" in _error(books.post(f"{API}/invoices/{other['id']}/review/cost-transfer", json=body), 409)
    items = [i for i in store.list_cost_items() if i.billing_period_id == period.id]
    assert [i.amount for i in items] == [595.0]
    assert _view(owner, other["id"])["transfer"]["cost_item_id"] == items[0].id
    # the cost item removed: the transfer goes with it and may be repeated
    _ok(owner.delete(f"{API}/billing/cost-items/{items[0].id}"), 204)
    assert _view(owner, other["id"])["transfer"] is None
    _ok(books.post(f"{API}/invoices/{other['id']}/review/cost-transfer", json=body), 201)


# ─── legacy invoices ─────────────────────────────────────────────────────────

def test_legacy_invoices_are_untouched(owner, estate):
    case, order = _order(owner, estate, gross=1190)
    legacy = _invoice(owner, estate, gross=1190, net=1000, number="L-1")
    _link(owner, case, order, legacy)
    listed = _ok(owner.get(f"{API}/invoices"))
    assert [i["id"] for i in listed] == [legacy["id"]] and set(listed[0]) == set(legacy)
    view = _view(owner, legacy["id"])
    assert view["status"] == "legacy" and view["review"] is None and view["history"] == []
    assert view["settlement"]["flow_amount"] is None and view["abilities"]["receive"] is True
    assert _ok(owner.get(f"{API}/maintenance/{case['id']}/costs"))["invoiced"] == 1190.0
    _ok(_pay(owner, legacy["id"], _booking(estate, -1190), 1190), 201)          # payments as before
    _ok(owner.put(f"{API}/invoices/{legacy['id']}", json={**{k: legacy[k] for k in (
        "property_id", "supplier", "invoice_date", "net_amount", "vat_amount", "gross_amount", "vat_rate")},
        "status": "paid"}))
    assert _ok(owner.get(f"{API}/invoice-review/inbox", params={"status": "legacy"}))["total"] == 1
    # reading never created a review
    assert store.list_invoices()[0].status == "paid"
    assert _view(owner, legacy["id"])["review"] is None


# ─── roles and portfolio boundary ────────────────────────────────────────────

def test_readonly_and_restricted_accounts(owner, estate):
    south = _estate("Süd")
    mine = _invoice(owner, estate, number="N-1")
    foreign = _invoice(owner, south, number="S-1", supplier="Süd GmbH")
    _ok(_receive(owner, foreign["id"]), 201)
    reader = _client(_user("reader", "readonly"))
    assert _receive(reader, mine["id"]).status_code == 403
    assert _view(reader, mine["id"])["abilities"]["receive"] is False

    staff = _client(_user("nora", "verwalter", [estate["portfolio"]], "selected"))
    inbox = _ok(staff.get(f"{API}/invoice-review/inbox"))
    assert [row["invoice_id"] for row in inbox["items"]] == [mine["id"]] and inbox["total"] == 1
    for path in ("", ):
        assert staff.get(f"{API}/invoices/{foreign['id']}/review{path}").status_code == 404
    assert _receive(staff, foreign["id"]).status_code == 404
    assert _decide(staff, foreign["id"], "reject", reason="x").status_code == 404
    assert _ok(staff.get(f"{API}/invoice-review/payment-proposals"))["total"] == 0
    dupes = _ok(staff.get(f"{API}/invoice-review/duplicates", params={
        "supplier": "Süd GmbH", "invoice_number": "S-1", "gross_amount": 1190, "invoice_date": TODAY.isoformat()}))
    assert dupes["duplicates"] == []                                          # another portfolio stays hidden
    _ok(_receive(staff, mine["id"]), 201)
    # a free assignment to a property of another portfolio is refused
    assert staff.patch(f"{API}/invoices/{mine['id']}/review",
                       json={"unit_id": south["unit"].id}).status_code in (403, 404)
    assert _ok(staff.get(f"{API}/invoice-review/settings"))["id"] == "default"


# ─── snapshot, DSGVO, migration ──────────────────────────────────────────────

def test_snapshot_round_trip_keeps_reviews_history_and_transfers(owner, estate):
    invoice = _invoice(owner, estate)
    _ok(_receive(owner, invoice["id"], skonto_percent=2, skonto_days=10), 201)
    _checked(owner, invoice["id"])
    _ok(_decide(owner, invoice["id"], "partial", amount=1000, reason="Teil"))
    owner.put(f"{API}/invoice-review/settings", json={"four_eyes_limit": 5000})
    snapshot = export_snapshot(store)
    assert snapshot["format_version"] >= 5
    assert len(snapshot["invoice_review_events"]) == 5
    clear_business_data(store)
    assert _ok(owner.get(f"{API}/invoice-review/inbox"))["total"] == 0
    import_snapshot(store, snapshot, replace=True)
    view = _view(owner, invoice["id"])
    assert view["status"] == "partially_approved" and len(view["history"]) == 5
    assert view["settlement"]["dispute_open"] == 190.0 and view["settings"]["four_eyes_limit"] == 5000.0


def test_dsgvo_export_contains_reviews_of_the_tenants_documents(owner, estate):
    tenant = store.create_tenant(TenantCreate(full_name="Lars Lustig"))
    contract = store.create_contract(ContractCreate(property_id=estate["property"].id, unit_id=estate["unit"].id,
                                                    tenant_id=tenant.id, start_date=date(2025, 1, 1),
                                                    contract_number="V-1"))
    document, _ = _document(estate, contract_id=contract.id)
    invoice = _invoice(owner, estate, number="Schaden-1", supplier="Glaserei")
    _ok(_receive(owner, invoice["id"], document_id=document.id), 201)
    export = _ok(owner.get(f"{API}/admin/dsgvo/tenant/{tenant.id}/export"))
    assert [r["invoice_id"] for r in export["invoice_reviews"]] == [invoice["id"]]
    assert [e["action"] for e in export["invoice_review_events"]] == ["received"]


ROOT = Path(__file__).resolve().parents[2]


def test_migration_up_down_and_refused_downgrade(tmp_path, monkeypatch):
    import sqlite3

    url = f"sqlite:///{tmp_path / 'app.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config()
    config.set_main_option("script_location", str(ROOT / "backend" / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    # Exercise the invoice-review revision at its actual historic boundary.
    # A downgrade from the modern merged head crosses independently retained
    # private sources and must be refused before invoice-review's own guard.
    command.upgrade(config, "c9f4a2e7b1d5")
    with sqlite3.connect(tmp_path / "app.db") as conn:
        conn.executescript("""
            INSERT INTO invoices (id, supplier, invoice_date, net_amount, vat_amount, gross_amount, status, created_at,
                                  updated_at)
                VALUES ('i1', 'Lieferant', '2026-05-01', 100, 19, 119, 'open', '2026-05-01', '2026-05-01');
            INSERT INTO invoice_reviews (id, invoice_id, kind, received_on, status, checklist, vat_lines, recoverable,
                                         created_at, updated_at)
                VALUES ('r1', 'i1', 'invoice', '2026-05-02', 'received', '{}', '[]', 0, '2026-05-02', '2026-05-02');
            INSERT INTO invoice_review_events (id, invoice_id, seq, action, details, created_at)
                VALUES ('e1', 'i1', 1, 'received', '{}', '2026-05-02');
        """)
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("UPDATE invoice_review_events SET reason = 'x'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO invoice_reviews (id, invoice_id, kind, received_on, status, checklist, "
                         "vat_lines, recoverable, created_at, updated_at) VALUES ('r2', 'i1', 'invoice', "
                         "'2026-05-02', 'received', '{}', '[]', 0, '2026-05-02', '2026-05-02')")
    with sqlite3.connect(tmp_path / "app.db") as conn:
        before = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    with pytest.raises(RuntimeError, match="invoice reviews"):
        command.downgrade(config, "5e8b2d4f7a19")
    with sqlite3.connect(tmp_path / "app.db") as conn:     # refused: nothing changed, also not a later revision
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == before
        assert conn.execute("SELECT id FROM invoice_review_events").fetchall() == [("e1",)]
        conn.executescript("DELETE FROM invoice_review_events; DELETE FROM invoice_reviews;")
    command.downgrade(config, "5e8b2d4f7a19")
    with sqlite3.connect(tmp_path / "app.db") as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "invoice_reviews" not in tables and "invoices" in tables
        assert conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 1      # legacy data kept
    command.upgrade(config, "head")
    with sqlite3.connect(tmp_path / "app.db") as conn:
        assert {"invoice_reviews", "invoice_review_events", "invoice_cost_transfers", "invoice_review_settings"} <= {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
