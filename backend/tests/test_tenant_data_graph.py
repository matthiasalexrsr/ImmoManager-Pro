"""Tests for tenant_data_graph/1. Synthetic records; no network/files.
SQLite uses real repositories but create_all, not migration/HTTP/RBAC gates.
Run: python -m pytest backend/tests/test_tenant_data_graph.py -q
"""
from copy import deepcopy
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from backend import models as m
from backend.db.orm_models import Base, TenantORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import tenant_data_graph as sut
from backend.services.billing_settlement import settlements
from backend.services.payments import Payment, PaymentReversal
from backend.storage import InMemoryStore, NotFoundError

STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOT_COVERED = {
    "contacts", "maintenance_cases", "tasks", "calendar_events",
    "standalone_meter_readings", "shared_billing_periods",
    "property_cost_documents", "notifications", "audit_history",
}
READS = (
    "get_tenant", "list_contracts", "list_documents", "list_deposits",
    "list_receivables", "list_rent_charges", "list_rent_adjustments",
    "list_handover_protocols", "list_utility_statements", "list_message_threads",
    "list_bookings", "list_messages", "list_meter_readings", "list_payments",
)


def records():
    data = {}

    def add(collection, cls, key, **values):
        times = {k: STAMP for k in ("created_at", "updated_at", "sent_at")
                 if k in cls.model_fields}
        row = cls(id=key, **times, **values)
        data.setdefault(collection, []).append(row)
        return row

    add("portfolios", m.Portfolio, "pf", name="Synthetic")
    add("properties", m.Property, "prop", portfolio_id="pf", name="Shared",
        property_type="residential")
    add("units", m.Unit, "unit", property_id="prop", label="Shared",
        unit_type="apartment", area_sqm=50)
    add("accounts", m.Account, "account", portfolio_id="pf", name="Test",
        account_type="checking")
    for who, year in (("a", 2024), ("b", 2025)):
        contract = f"c-{who}"
        start, end = date(year, 1, 1), date(year, 12, 31)
        add("tenants", m.Tenant, who, full_name="Same Name",
            email="same@example.invalid", archived=who == "a")
        add("contracts", m.Contract, contract, tenant_id=who,
            contract_number=contract, property_id="prop", unit_id="unit",
            start_date=start, end_date=end, status="terminated")
        add("bookings", m.Booking, f"b-{who}", account_id="account",
            tenant_id=who, property_id="prop", unit_id="unit",
            booking_date=start, amount=10, receipt_url=f"file://{who}-receipt")
        add("documents", m.Document, f"d-{who}", contract_id=contract,
            property_id="prop", unit_id="unit", title=f"Document {who}",
            file_url=f"file://{who}-document")
        add("deposits", m.Deposit, f"dep-{who}", contract_id=contract, amount=100)
        add("rent_charges", m.RentCharge, f"rc-{who}", contract_id=contract,
            month=f"{year}-01", cold_rent=100, service_charge=20)
        add("rent_adjustments", m.RentAdjustment, f"adj-{who}",
            contract_id=contract, adjustment_type="stepped", effective_date=start,
            previous_rent=90, new_rent=100)
        add("handover_protocols", m.HandoverProtocol, f"h-{who}",
            contract_id=contract, unit_id="unit", protocol_type="move_out",
            protocol_date=end, photos='["file://opaque-photo"]',
            tenant_signature="opaque-tenant", landlord_signature="opaque-landlord")
        add("meter_readings", m.MeterReading, f"mr-{who}", handover_id=f"h-{who}",
            meter_type="water", reading_value=42, photo_url="file://opaque-meter")
        add("message_threads", m.MessageThread, f"th-{who}",
            contract_id=contract, property_id="prop", unit_id="unit",
            subject=f"Thread {who}", participant_ids="unverified-contact")
        add("messages", m.Message, f"msg-{who}", thread_id=f"th-{who}",
            body=f"Own message {who}", attachment_ids=f"d-{who}")
        add("billing_periods", m.BillingPeriod, f"bp-{who}",
            property_id="prop", label=who, start_date=start, end_date=end,
            status="finalized")
        add("utility_statements", m.UtilityStatement, f"s-{who}",
            billing_period_id=f"bp-{who}", contract_id=contract, unit_id="unit",
            total_cost=110, advance_paid=10, balance=100, status="finalized",
            snapshot_hash=f"snapshot-{who}", calculation_hash=f"calculation-{who}",
            line_items=[{"description": "Water", "allocated_amount": 110}])
        add("receivables", m.Receivable, f"r-{who}", contract_id=contract,
            due_date=end, amount_due=100, statement_id=f"s-{who}")
        add("billing_settlements", m.BillingSettlement, f"bs-{who}",
            contract_id=contract, billing_period_id=f"bp-{who}",
            statement_id=f"s-{who}", root_statement_id=f"s-{who}",
            signed_amount=100, kind="debt", status="receivable_created",
            receivable_id=f"r-{who}")

    # Null tenant + shared bank is not authority to export the bank row.
    add("bookings", m.Booking, "bank-global", account_id="account",
        property_id="prop", unit_id="unit", booking_date=date(2024, 1, 3),
        amount=200, payment_text="PRIVATE-BANK-TEXT",
        receipt_url="file://PRIVATE-BANK-FILE")
    for who in ("a", "b"):
        payment_id = f"pay-{who}"
        reversal = PaymentReversal(id=f"rev-{who}", payment_id=payment_id,
            idempotency_key=f"reverse-{who}", amount="60.00",
            reversal_date=date(2026, 1, 1), reason="Correction", created_at=STAMP)
        add("payments", Payment, payment_id, entity_type="rent_charge",
            entity_id=f"rc-{who}", idempotency_key=f"receipt-{who}", amount="60.00",
            payment_date=date(2024 if who == "a" else 2025, 1, 3),
            booking_id="bank-global", reversal=reversal)
    add("payments", Payment, "pay-claim", entity_type="receivable",
        entity_id="r-a", idempotency_key="claim-payment", amount="10.00",
        payment_date=date(2025, 1, 3), booking_id="b-a")
    data["receivables"][0].amount_paid = 10
    data["receivables"][0].status = "partial"
    data["bookings"][0].allocated_amount = 10
    detail = {"rent_charge_id": "rc-a", "receipt_ids": ["pay-a"],
              "receipt_paid_at_cutoff": 60, "advance_paid": 10,
              "excluded_receipts": [], "legacy_undated_paid": 0,
              "reversals_after_cutoff": [{"receipt_id": "pay-a",
                  "reversal_id": "rev-a", "reversal_date": "2026-01-01"}]}
    data["utility_statements"][0].advance_details = [detail]
    data["messages"][0].attachment_ids = "d-a,d-b,d-shared,missing"
    add("documents", m.Document, "d-shared", property_id="prop", unit_id="unit",
        title="PRIVATE-SHARED-DOCUMENT", file_url="file://PRIVATE-SHARED-FILE")
    add("message_threads", m.MessageThread, "th-shared", subject="PRIVATE-SHARED",
        property_id="prop", unit_id="unit")
    add("messages", m.Message, "msg-shared", thread_id="th-shared",
        body="PRIVATE-SHARED-MESSAGE")
    # Two equal names/emails must not establish a contact relationship.
    add("contacts", m.Contact, "contact", first_name="Same", last_name="Name",
        email="same@example.invalid", notes="PRIVATE-CONTACT")
    add("maintenance_cases", m.MaintenanceCase, "maintenance", property_id="prop",
        unit_id="unit", title="Shared issue", reported_by="Same Name")
    add("notifications", m.Notification, "notice", notification_type="general",
        title="Stored notice", content="Related but outside this graph",
        entity_type="contract", entity_id="c-a")
    return data


@pytest.fixture(params=["memory", "sqlite"])
def store(request):
    seed = records()
    if request.param == "memory":
        memory = InMemoryStore()
        for name, rows in seed.items():
            setattr(memory, name, {
                (r.idempotency_key if name == "payments" else r.id): r for r in rows
            })
        yield memory
        return
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    try:
        Base.metadata.create_all(engine)
        values = {name: [r.model_dump() for r in rows] for name, rows in seed.items()}
        values["payment_reversals"] = []
        for row in values["payments"]:
            # Derived from credit_receipts.payment_id; no duplicate DB column.
            assert row.pop("credit_receipt_id") is None
            kind, target = row.pop("entity_type"), row.pop("entity_id")
            row[f"{kind}_id"] = target
            reversal = row.pop("reversal")
            if reversal is not None:
                values["payment_reversals"].append(reversal)
        with engine.begin() as connection:
            for table in Base.metadata.sorted_tables:
                for row in values.get(table.name, []):
                    assert set(row) <= set(table.c.keys()), table.name
                    connection.execute(table.insert().values(**row))
        with Session(engine) as session:
            yield SQLAlchemyStore(session)
    finally:
        engine.dispose()


def state(store):
    if isinstance(store, InMemoryStore):
        # Monkeypatch restores bound methods as instance attributes. They are
        # test instrumentation, not persisted business state.
        return deepcopy({key: value for key, value in vars(store).items() if not callable(value)})
    return {
        t.name: [dict(row) for row in store.db.execute(
            select(t).order_by(*t.primary_key.columns)
        ).mappings()]
        for t in Base.metadata.sorted_tables
    }


def ids(graph, name):
    return {row["id"] for row in graph[name]}


def test_typed_graph_excludes_other_tenant_and_shared_locations(store):
    g = sut.tenant_data_graph(store, "a")
    assert g["tenant"]["archived"] is True
    assert ids(g, "contracts") == {"c-a"}
    for name, key in {
        "documents": "d-a", "deposits": "dep-a", "rent_charges": "rc-a",
        "rent_adjustments": "adj-a", "handover_protocols": "h-a",
        "meter_readings": "mr-a", "message_threads": "th-a", "messages": "msg-a",
        "utility_statements": "s-a", "receivables": "r-a",
        "billing_settlements": "bs-a", "bookings": "b-a",
    }.items():
        assert ids(g, name) == {key}
    assert ids(g, "payments") == {"pay-a", "pay-claim"}


def test_bank_reversal_keeps_receipt_not_other_bank_data(store):
    g = sut.tenant_data_graph(store, "a")
    payment = next(row for row in g["payments"] if row["id"] == "pay-a")
    expected = next(p for p in store.list_payments() if p.id == "pay-a")
    assert payment == expected.model_dump(mode="json")
    assert payment["booking_id"] == "bank-global"
    assert payment["reversal"]["payment_id"] == "pay-a"
    assert "bank-global" not in ids(g, "bookings")
    assert "b-b" not in ids(g, "bookings")
    assert "PRIVATE-BANK" not in str(g)


def test_scope_and_export_only_redactions_are_honest(store):
    g = sut.tenant_data_graph(store, "a")
    assert g["schema_version"] == "tenant-data-graph/1"
    assert NOT_COVERED <= set(g["scope"]["not_covered"])
    assert g["scope"]["file_content"] == "excluded; metadata only"
    assert g["scope"]["selection"] == "explicit_tenant_contract_relationships"
    assert not ((NOT_COVERED | {"billing_periods", "cost_items"}) & g.keys())
    assert g["messages"][0]["attachment_ids"] == "d-a"
    reds = g["scope"]["redactions"]
    assert {"collection": "messages", "id": "msg-a", "field": "attachment_ids",
            "omitted_count": 3} in reds
    for name, fields in (
        ("documents", ["file_url"]), ("bookings", ["receipt_url"]),
        ("meter_readings", ["photo_url"]), ("message_threads", ["participant_ids"]),
        ("handover_protocols", ["photos", "tenant_signature", "landlord_signature"]),
    ):
        for field in fields:
            assert field not in g[name][0]
            assert {"collection": name, "id": g[name][0]["id"], "field": field} in reds


def test_export_is_detached_deterministic_and_never_changes_financial_rows(store):
    before = state(store)
    first = sut.tenant_data_graph(store, "a")
    pristine = deepcopy(first)
    assert first == sut.tenant_data_graph(store, "a")
    for name, reader in (
        ("utility_statements", store.list_utility_statements),
        ("receivables", store.list_receivables),
        ("rent_charges", store.list_rent_charges),
        ("billing_settlements", lambda: settlements(store)),
    ):
        expected = [r.model_dump(mode="json") for r in reader() if r.contract_id == "c-a"]
        assert first[name] == sorted(expected, key=lambda r: r["id"])
    first["utility_statements"][0]["line_items"][0]["allocated_amount"] = 999
    first["payments"][0]["reversal"]["reason"] = "CHANGED-EXPORT"
    first["tenant"]["full_name"] = "CHANGED-EXPORT"
    assert sut.tenant_data_graph(store, "a") == pristine
    assert state(store) == before


def test_missing_tenant_is_distinct_from_broken_store(store, monkeypatch):
    with pytest.raises(sut.TenantNotFoundError):
        sut.tenant_data_graph(store, "unknown")
    def broken():
        raise NotFoundError("broken subordinate query")
    monkeypatch.setattr(store, "list_documents", broken)
    with pytest.raises(sut.TenantExportError):
        sut.tenant_data_graph(store, "a")


@pytest.mark.parametrize("method", READS)
def test_required_read_errors_fail_closed(store, monkeypatch, method):
    before = state(store)
    def broken(*args, **kwargs):
        raise RuntimeError("synthetic database failure")
    with monkeypatch.context() as patch:
        patch.setattr(store, method, broken)
        with pytest.raises(sut.TenantExportError):
            sut.tenant_data_graph(store, "a")
    assert state(store) == before


def test_settlement_query_failure_is_not_an_empty_list(store, monkeypatch):
    def broken(_):
        raise RuntimeError("synthetic settlement failure")
    monkeypatch.setattr(sut, "_settlements", broken)
    with pytest.raises(sut.TenantExportError):
        sut.tenant_data_graph(store, "a")


@pytest.mark.parametrize("bad", [None, {"items": []}, [None]])
def test_incomplete_or_untyped_lists_fail_closed(store, monkeypatch, bad):
    monkeypatch.setattr(store, "list_documents", lambda: bad)
    with pytest.raises(sut.TenantExportError):
        sut.tenant_data_graph(store, "a")


def test_duplicate_ids_and_broken_attachment_ids_fail_closed(store, monkeypatch):
    rows = store.list_documents()
    with monkeypatch.context() as patch:
        patch.setattr(store, "list_documents", lambda: rows + [rows[0]])
        with pytest.raises(sut.TenantExportError):
            sut.tenant_data_graph(store, "a")
    messages = [r.model_copy(deep=True) for r in store.list_messages()]
    next(r for r in messages if r.id == "msg-a").attachment_ids = "d-a,,d-b"
    monkeypatch.setattr(store, "list_messages", lambda: messages)
    with pytest.raises(sut.TenantExportError):
        sut.tenant_data_graph(store, "a")


def test_all_documents_not_only_first_100(store):
    sample = next(r for r in store.list_documents() if r.id == "d-a")
    rows = [sample.model_copy(update={"id": f"extra-{i:03d}"}, deep=True) for i in range(101)]
    if isinstance(store, InMemoryStore):
        store.documents.update({row.id: row for row in rows})
    else:
        table = Base.metadata.tables["documents"]
        for row in rows:
            store.db.execute(table.insert().values(**row.model_dump()))
        store.db.commit()
    assert len(sut.tenant_data_graph(store, "a")["documents"]) == 102


@pytest.mark.parametrize("method,key,changes", [
    ("list_documents", "d-a", {"unit_id": "wrong-unit"}),
    ("list_payments", "pay-a", {"booking_id": "b-b"}),
    ("list_payments", "pay-b", {"booking_id": "b-a"}),
    ("list_utility_statements", "s-a", {"source_statement_id": "s-b"}),
    ("list_utility_statements", "s-a", {"source_statement_id": "s-a"}),
    ("list_receivables", "r-a", {"statement_id": "s-b"}),
    ("list_utility_statements", "s-a", {"advance_details": [
        {"rent_charge_id": "rc-a", "receipt_ids": ["pay-b"]}]}),
])
def test_conflicting_links_fail_without_expanding_to_foreign_data(store, monkeypatch, method, key, changes):
    rows = [r.model_copy(update=changes if r.id == key else {}, deep=True)
            for r in getattr(store, method)()]
    monkeypatch.setattr(store, method, lambda: rows)
    with pytest.raises(sut.TenantExportError):
        sut.tenant_data_graph(store, "a")


def test_typed_payment_key_is_not_entity_id_alone(store, monkeypatch):
    rows = store.list_payments()
    extra = next(p for p in rows if p.id == "pay-a").model_copy(update={
        "id": "wrong-kind", "entity_type": "receivable", "entity_id": "rc-a",
        "booking_id": None, "reversal": None,
    }, deep=True)
    monkeypatch.setattr(store, "list_payments", lambda: rows + [extra])
    assert "wrong-kind" not in ids(sut.tenant_data_graph(store, "a"), "payments")


def test_legacy_credit_reference_is_preserved_without_claiming_payout(store, monkeypatch):
    # Explicit typed response doubles, not a claim to test the legacy migration.
    substitutions = (
        ("list_utility_statements", "s-a", {
            "total_cost": 0, "advance_paid": 20, "balance": -20,
            "advance_details": None, "line_items": []}),
        ("list_receivables", "r-a", {
            "amount_due": -20, "amount_paid": 0, "status": "credit_available"}),
    )
    for method, key, changes in substitutions:
        rows = [r.model_copy(update=changes if r.id == key else {}, deep=True)
                for r in getattr(store, method)()]
        monkeypatch.setattr(store, method, lambda rows=rows: rows)
    rows = [r.model_copy(update={
        "signed_amount": -20, "kind": "credit", "status": "credit_available"
    } if r.id == "bs-a" else {}, deep=True) for r in settlements(store)]
    monkeypatch.setattr(sut, "_settlements", lambda _: rows)
    payments = [p for p in store.list_payments() if p.id != "pay-claim"]
    monkeypatch.setattr(store, "list_payments", lambda: payments)
    graph = sut.tenant_data_graph(store, "a")
    record = graph["billing_settlements"][0]
    assert (record["kind"], record["status"], record["signed_amount"]) == (
        "credit", "credit_available", -20)
    assert record["receivable_id"] == "r-a"
    assert graph["receivables"][0]["amount_due"] == -20


def test_sql_pending_changes_are_not_flushed(store):
    if isinstance(store, InMemoryStore):
        pytest.skip("SQL-specific autoflush guard")
    store.db.get(TenantORM, "a").full_name = "UNCOMMITTED"
    with pytest.raises(sut.TenantExportError, match="clean read session"):
        sut.tenant_data_graph(store, "a")
    store.db.rollback()
    assert store.get_tenant("a").full_name == "Same Name"
