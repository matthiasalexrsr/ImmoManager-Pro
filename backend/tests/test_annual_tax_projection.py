"""Real Memory/SQLite cash sources, explicit splits and immutable source evidence."""

import csv
import io
import json
from datetime import date
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.orm import Session

from backend.db.credit_models import CreditReceiptORM  # noqa: F401 complete native finance metadata
from backend.db.orm_models import Base, BookingORM
from backend.db.tax_models import AnnualTaxProjectionORM, AnnualTaxSourceORM
from backend.models import AccountCreate, BookingCreate, CategoryCreate, PortfolioCreate, PropertyCreate
from backend.services import annual_tax_storage as service
from backend.services.annual_tax_export import prepare_download
from backend.storage import InMemoryStore
from backend.tax_models import AnnualTaxPreflightCreate, AnnualTaxProfileCreate, AnnualTaxProjectionCreate


@pytest.fixture(params=["memory", "sql"])
def tax_store(request, tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "tax.db").as_posix(), connect_args={"check_same_thread": False, "timeout": 20})
    @event.listens_for(engine, "connect")
    def sqlite(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(engine)
    db = Session(engine)
    from backend.repositories.sql_store import SQLAlchemyStore
    store = SQLAlchemyStore(db) if request.param == "sql" else InMemoryStore()
    from backend import dependencies
    monkeypatch.setattr(dependencies, "store", store)
    portfolio = store.create_portfolio(PortfolioCreate(name="Synthetic EUR"))
    properties = [store.create_property(PropertyCreate(portfolio_id=portfolio.id, name=f"Property {i}", property_type="residential")) for i in range(2)]
    accounts = [store.create_account(AccountCreate(portfolio_id=portfolio.id, name=f"Account {i}", account_type="bank")) for i in range(2)]
    categories = [store.create_category(CategoryCreate(portfolio_id=portfolio.id, name=name, category_type=kind)) for name, kind in (("Rent", "income"), ("Repairs", "expense"), ("Transfer", "expense"))]
    yield store, engine, portfolio, properties, accounts, categories
    db.close()
    engine.dispose()


def profile_command(fixture, **changes):
    _, _, portfolio, _, accounts, categories = fixture
    values = dict(portfolio_id=portfolio.id, tax_year=2024, name="User reviewed 2024", reviewed_by="Synthetic accountant",
        review_confirmed=True, idempotency_key="profile", rules=[dict(account_id=accounts[0].id, category_id=categories[0].id,
        treatment="income", form_line="User form income", reason="Reviewed rental cash"),
        dict(account_id=accounts[0].id, category_id=categories[1].id, treatment="expense", form_line="User form costs", reason="Reviewed paid costs")])
    values.update(changes)
    return AnnualTaxProfileCreate(**values)


def booking(fixture, amount, *, category=0, prop=0, account=0, day=date(2024, 6, 1), **changes):
    store, _, _, properties, accounts, categories = fixture
    values = dict(account_id=accounts[account].id, category_id=categories[category].id, property_id=properties[prop].id if prop is not None else None,
        booking_date=day, amount=amount, status="confirmed", payment_text="Synthetic bank source")
    values.update(changes)
    return store.create_booking(BookingCreate(**values))


def preflight_command(version, **changes):
    return AnnualTaxPreflightCreate(profile_version_id=version["id"], as_of=date(2024, 12, 31), **changes)


def save_command(command, preview, **changes):
    return AnnualTaxProjectionCreate(**command.model_dump(), preview_hash=preview["preview_hash"], idempotency_key=changes.pop("idempotency_key", "projection"), **changes)


def test_signed_income_and_expense_refunds_are_exact_and_snapshots_survive_live_edits(tax_store, tmp_path):
    store, _, _, properties, _, _ = tax_store
    original = booking(tax_store, 100.01)
    booking(tax_store, -0.01)
    expense = booking(tax_store, -30.10, category=1)
    refund = booking(tax_store, 10.01, category=1, day=date(2024, 7, 1))
    version = service.create_profile(store, profile_command(tax_store), "actor")
    assert service.create_profile(store, profile_command(tax_store), "actor") == version
    command = preflight_command(version, overrides=[dict(booking_id=refund.id, reason="Partial supplier reimbursement",
        correction_of_booking_id=expense.id, parts=[dict(amount_cents="1001", property_id=properties[0].id, treatment="expense", form_line="User form costs", reason="Supplier credit reduces paid expense")])])
    checked = service.preflight(store, command)
    assert checked["ready"] and checked["cash_reconciled"]
    assert checked["totals"] == dict(cash_cents="7991", income_cents="10000", expense_cents="2009", excluded_cash_cents="0", unclassified_cash_cents="0")
    assert checked["confirmed_cash_rows"] == 4
    saved = service.create_projection(store, save_command(command, checked), "actor")
    assert service.create_projection(store, save_command(command, checked), "actor") == saved
    from backend.models import BookingPatch, PropertyPatch
    store._patch_entity("booking", original.id, BookingPatch(amount=999, payment_text="Later corrected cash"))
    store._patch_entity("property", properties[0].id, PropertyPatch(name="Later label"))
    evidence = list(service.saved_sources(store, saved["id"]))
    assert next(item for item in evidence if item["booking"]["id"] == original.id)["booking"]["amount_cents"] == "10001"
    assert any(item["evidence"].get("correction_of", {}).get("id") == expense.id for item in evidence)
    assert service.read_projection(service.projection_row(store, saved["id"]))["groups"][0]["property_name"] == properties[0].name
    download = prepare_download(store, saved["id"], parent=tmp_path)
    try:
        with ZipFile(download.path) as archive:
            assert set(archive.namelist()) == {"manifest.json", "sources.jsonl", "tax-lines.csv", "cash-evidence.csv"}
            assert json.loads(archive.read("manifest.json"))["totals"] == checked["totals"]
            lines = list(csv.reader(io.StringIO(archive.read("cash-evidence.csv").decode("utf-8-sig")), delimiter=";"))
            assert any(row[6] == "-3010" and row[14] == "3010" for row in lines[1:])
            assert b'"amount_cents":"10001"' in archive.read("sources.jsonl")
    finally:
        folder = download.path.parent
        download.close()
    assert not folder.exists()


def test_explicit_property_and_nontransferable_share_preserve_all_cash(tax_store):
    store, _, _, properties, _, _ = tax_store
    source = booking(tax_store, -100, category=1, prop=None)
    version = service.create_profile(store, profile_command(tax_store), "actor")
    missing = service.preflight(store, preflight_command(version))
    assert not missing["ready"] and missing["blocking_issue_counts"] == {"property_assignment_required": 1}
    command = preflight_command(version, overrides=[dict(booking_id=source.id, reason="Reviewed object/private division",
        parts=[dict(amount_cents="-3000", property_id=properties[0].id, treatment="expense", form_line="Paid costs", reason="Invoice share property A"),
            dict(amount_cents="-2000", property_id=properties[1].id, treatment="expense", form_line="Paid costs", reason="Invoice share property B"),
            dict(amount_cents="-5000", treatment="excluded", exclusion_kind="personal", reason="Private part; not transferred to tax")])])
    checked = service.preflight(store, command)
    assert checked["ready"] and checked["totals"] == dict(cash_cents="-10000", income_cents="0", expense_cents="5000", excluded_cash_cents="-5000", unclassified_cash_cents="0")
    assert sum(int(group["amount_cents"]) for group in checked["groups"]) == 5000
    payload = command.model_dump()
    payload["overrides"][0]["parts"][0]["amount_cents"] = "-3001"
    invalid = service.preflight(store, AnnualTaxPreflightCreate(**payload))
    assert invalid["blocking_issue_counts"] == {"allocation_sum_differs_from_cash": 1}
    with pytest.raises(HTTPException) as error:
        service.create_projection(store, save_command(AnnualTaxPreflightCreate(**payload), invalid), "actor")
    assert error.value.status_code == 422
    assert service.list_projections(store, version["portfolio_id"])["total"] == 0


def test_internal_bank_transfers_need_real_opposite_evidence_on_both_sides(tax_store):
    store, _, _, _, accounts, categories = tax_store
    first = booking(tax_store, -250.01, category=2)
    second = booking(tax_store, 250.01, category=2, account=1)
    rules = [dict(account_id=account.id, category_id=categories[2].id, treatment="excluded", exclusion_kind="internal_transfer", reason="Reviewed own bank transfer") for account in accounts]
    version = service.create_profile(store, profile_command(tax_store, rules=rules), "actor")
    missing = service.preflight(store, preflight_command(version))
    assert missing["blocking_issue_counts"] == {"internal_transfer_counter_evidence_required": 2}
    command = preflight_command(version, overrides=[dict(booking_id=first.id, transfer_counter_booking_id=second.id, reason="Matching bank counterleg",
        parts=[dict(amount_cents="-25001", treatment="excluded", exclusion_kind="internal_transfer", reason="Own transfer; no rental income or costs")])])
    checked = service.preflight(store, command)
    assert checked["ready"] and checked["excluded_rows"] == 2
    assert set(checked["totals"].values()) == {"0"}
    assert len([record for record in checked["source_samples"] if record["evidence"].get("internal_transfer_counter")]) == 2


def test_pending_cutoff_and_missing_mappings_are_explicit(tax_store):
    store, _, _, _, _, _ = tax_store
    booking(tax_store, 100)
    booking(tax_store, 25, status="open")
    booking(tax_store, 10, day=date(2024, 12, 1))
    version = service.create_profile(store, profile_command(tax_store), "actor")
    command = AnnualTaxPreflightCreate(profile_version_id=version["id"], as_of=date(2024, 8, 1))
    checked = service.preflight(store, command)
    assert not checked["ready"] and checked["pending_rows"] == 1 and checked["after_cutoff_rows"] == 1
    assert checked["totals"]["cash_cents"] == "10000" and not checked["full_year"]
    reviewed = AnnualTaxPreflightCreate(**command.model_dump() | {"pending_review_reason": "Unconfirmed imported item still under review; omitted explicitly"})
    checked = service.preflight(store, reviewed)
    assert checked["ready"] and checked["source_rows"] == 3
    saved = service.create_projection(store, save_command(reviewed, checked), "actor")
    assert len(list(service.saved_sources(store, saved["id"]))) == 3


def test_preview_changes_require_recheck_and_revisions_replace_retained_original(tax_store):
    store, _, _, _, _, _ = tax_store
    booking(tax_store, 100)
    version = service.create_profile(store, profile_command(tax_store), "actor")
    command = preflight_command(version)
    first_check = service.preflight(store, command)
    first = service.create_projection(store, save_command(command, first_check), "actor")
    booking(tax_store, -20, day=date(2024, 7, 1))
    with pytest.raises(HTTPException) as error:
        service.create_projection(store, save_command(command, first_check, idempotency_key="stale", previous_projection_id=first["id"], revision_reason="Rent refund"), "actor")
    assert error.value.status_code == 409
    current = service.preflight(store, command)
    revised = service.create_projection(store, save_command(command, current, idempotency_key="revision", previous_projection_id=first["id"], revision_reason="Confirmed rent refund"), "actor")
    assert revised["revision_number"] == 2 and revised["revision_delta_cents"]["income_cents"] == "-2000"
    assert service.read_projection(service.projection_row(store, first["id"]))["totals"]["income_cents"] == "10000"
    with pytest.raises(HTTPException) as error:
        service.create_projection(store, save_command(command, current, idempotency_key="fork", previous_projection_id=first["id"], revision_reason="Another refund"), "actor")
    assert error.value.status_code == 409
    with pytest.raises(HTTPException):
        service.create_projection(store, save_command(command, current, idempotency_key="another-root"), "actor")
    assert service.list_projections(store, version["portfolio_id"])["total"] == 2


def test_retained_evidence_corruption_is_fail_closed(tax_store, tmp_path):
    store, _, _, _, _, _ = tax_store
    booking(tax_store, 100)
    version = service.create_profile(store, profile_command(tax_store), "actor")
    command = preflight_command(version)
    saved = service.create_projection(store, save_command(command, service.preflight(store, command)), "actor")
    if hasattr(store, "db"):
        store.db.execute(update(AnnualTaxSourceORM).where(AnnualTaxSourceORM.projection_id == saved["id"]).values(source_json="{}"))
        store.db.commit()
    else:
        service.memory_state(store).sources[saved["id"]][0].source_json = "{}"
    with pytest.raises(HTTPException) as error:
        prepare_download(store, saved["id"], parent=tmp_path)
    assert error.value.status_code == 503
    assert not any(item.name.startswith("immomanager") for item in tmp_path.iterdir())


def test_original_review_request_is_retained_and_corruption_cannot_change_revision_drafts(tax_store):
    store, _, _, properties, *_ = tax_store
    source = booking(tax_store, -40.01, category=1)
    version = service.create_profile(store, profile_command(tax_store), "actor")
    command = preflight_command(version, overrides=[dict(booking_id=source.id, reason="Original review",
        parts=[dict(property_id=properties[0].id, amount_cents="-4001", treatment="expense", form_line="Reviewed line", reason="Original source proof")])])
    saved = service.create_projection(store, save_command(command, service.preflight(store, command)), "actor")
    assert saved["review_request"] == command.model_dump(mode="json")
    from backend.db.tax_models import AnnualTaxProjectionORM
    if hasattr(store, "db"):
        store.db.execute(update(AnnualTaxProjectionORM).where(AnnualTaxProjectionORM.id == saved["id"]).values(request_json="{}"))
        store.db.commit()
    else:
        service.memory_state(store).projections[saved["id"]].request_json = "{}"
    with pytest.raises(HTTPException) as error:
        service.read_projection(service.projection_row(store, saved["id"]))
    assert error.value.status_code == 503


def test_empty_year_needs_review_and_can_replace_a_corrected_previous_snapshot(tax_store):
    store, _, _, _, _, _ = tax_store
    source = booking(tax_store, 100)
    version = service.create_profile(store, profile_command(tax_store), "actor")
    command = preflight_command(version)
    saved = service.create_projection(store, save_command(command, service.preflight(store, command)), "actor")
    store.delete_booking(source.id)
    blocked = service.preflight(store, command)
    assert blocked["blocking_issue_counts"] == {"no_confirmed_cash_sources": 1}
    reviewed = preflight_command(version, empty_cash_review_reason="Erroneous test cash removed; prior copied evidence retained")
    checked = service.preflight(store, reviewed)
    assert checked["ready"] and checked["source_rows"] == 0
    revised = service.create_projection(store, save_command(reviewed, checked, idempotency_key="zero-revision",
        previous_projection_id=saved["id"], revision_reason="Remove erroneous cash entry"), "actor")
    assert revised["revision_delta_cents"]["income_cents"] == "-10000"
    assert list(service.saved_sources(store, revised["id"])) == []
    assert len(list(service.saved_sources(store, saved["id"]))) == 1


def test_payments_rent_obligations_and_invoices_are_not_added_as_cash_again(tax_store):
    from backend.models import ContractCreate, InvoiceCreate, RentChargeCreate, TenantCreate, UnitCreate
    from backend.services.payments import PaymentCreate
    store, _, _, properties, _, _ = tax_store
    unit = store.create_unit(UnitCreate(property_id=properties[0].id, label="Synthetic unit", unit_type="apartment"))
    tenant = store.create_tenant(TenantCreate(full_name="Synthetic tenant"))
    contract = store.create_contract(ContractCreate(property_id=properties[0].id, unit_id=unit.id, tenant_id=tenant.id, contract_number="Tax-2024", start_date=date(2024, 1, 1)))
    charge = store.create_rent_charge(RentChargeCreate(contract_id=contract.id, month="2024-06", cold_rent=80, service_charge=20))
    cash = booking(tax_store, 100)
    store.record_payment("rent_charge", charge.id, PaymentCreate(idempotency_key="cash-receipt", amount="100.00", payment_date=date(2024, 6, 1), booking_id=cash.id))
    store.create_invoice(InvoiceCreate(property_id=properties[0].id, supplier="Synthetic", invoice_date=date(2024, 6, 1), net_amount=100, gross_amount=100, vat_amount=0, vat_rate=0, status="paid"))
    version = service.create_profile(store, profile_command(tax_store), "actor")
    checked = service.preflight(store, preflight_command(version))
    assert checked["confirmed_cash_rows"] == 1 and checked["totals"]["income_cents"] == "10000"
    assert checked["totals"]["expense_cents"] == "0"
    assert store.get_rent_charge(charge.id).amount_paid == 100


@pytest.mark.parametrize("changes", [dict(tax_year=True), dict(review_confirmed=False), dict(tax_year=10000), dict(rules=[dict(account_id="a", treatment="income", reason="x")])])
def test_profiles_reject_ambiguous_or_unreviewed_inputs(tax_store, changes):
    with pytest.raises(ValidationError):
        profile_command(tax_store, **changes)


def test_sql_source_buffers_and_complete_atomic_persistence(tax_store, monkeypatch):
    store, engine, portfolio, properties, accounts, categories = tax_store
    if not hasattr(store, "db"):
        pytest.skip("SQL transfer/persistence test; Memory semantics covered separately")
    with engine.begin() as db:
        db.execute(BookingORM.__table__.insert(), [dict(id=f"bulk-{i:05}", account_id=accounts[0].id, category_id=categories[0].id,
            property_id=properties[0].id, amount=0.01, booking_date=date(2024, 6, 1), status="confirmed") for i in range(1005)])
    version = service.create_profile(store, profile_command(tax_store), "actor")
    command = preflight_command(version)
    checked = service.preflight(store, command)
    assert checked["confirmed_cash_rows"] == 1005 and checked["totals"]["income_cents"] == "1005"
    assert len(checked["source_samples"]) == 20
    original = store.db.execute
    counter = {"inserts": 0}
    def failure(statement, *args, **kwargs):
        if getattr(getattr(statement, "table", None), "name", None) == "annual_tax_sources":
            counter["inserts"] += 1
            if counter["inserts"] == 2:
                raise RuntimeError("Synthetic second source chunk failure")
        return original(statement, *args, **kwargs)
    monkeypatch.setattr(store.db, "execute", failure)
    with pytest.raises(RuntimeError, match="second source chunk"):
        service.create_projection(store, save_command(command, checked), "actor")
    monkeypatch.setattr(store.db, "execute", original)
    assert store.db.scalar(select(AnnualTaxProjectionORM.id)) is None
    assert store.db.scalar(select(AnnualTaxSourceORM.id)) is None
    saved = service.create_projection(store, save_command(command, checked), "actor")
    assert len(list(service.saved_sources(store, saved["id"]))) == 1005
    assert engine.pool.checkedout() <= 1
