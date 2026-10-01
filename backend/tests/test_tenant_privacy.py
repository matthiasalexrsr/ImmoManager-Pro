"""Real Memory/SQLite privacy graphs, financial evidence and rollback gates."""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.orm import Session

from backend import models as m
from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.db.orm_models import Base, ContractORM, TenantORM
from backend.dependencies import store
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.payments import PaymentReversalCreate
from backend.services.tenant_data_graph import TenantExportError, TenantNotFoundError
from backend.services.tenant_privacy import (
    PROFILE_FIELDS,
    PrivacyConflict,
    anonymize_tenant_profile,
    export_tenant_metadata,
    preview_tenant_anonymization,
)
from backend.storage import InMemoryStore
from backend.tests.test_payments import payload


@pytest.fixture(params=["memory", "sql"])
def privacy_store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryStore()
        return
    engine = create_engine(f"sqlite:///{tmp_path / 'privacy.db'}")
    @event.listens_for(engine, "connect")
    def setup(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield SQLAlchemyStore(db)
    engine.dispose()


def seed(active_store):
    portfolio = active_store.create_portfolio(m.PortfolioCreate(name="Shared portfolio"))
    prop = active_store.create_property(m.PropertyCreate(portfolio_id=portfolio.id, name="Shared house", property_type="residential"))
    unit = active_store.create_unit(m.UnitCreate(property_id=prop.id, label="Shared unit", unit_type="apartment"))
    own = active_store.create_tenant(m.TenantCreate(full_name="Synthetic own person", email="own@example.com", phone="123456",
        address_line="Synthetic street", postal_code="10115", city="Berlin", country="DE", payment_method="cash",
        sepa_mandate="Own mandate", notes="Own profile note"))
    foreign = active_store.create_tenant(m.TenantCreate(full_name="FOREIGN PERSON MUST NOT LEAK", email="foreign@example.com"))
    contracts = [active_store.create_contract(m.ContractCreate(contract_number=f"Synthetic-{index}", property_id=prop.id,
        unit_id=unit.id, tenant_id=tenant.id, start_date=date(2026, 1, 1), status="terminated"))
        for index, tenant in enumerate((own, foreign))]
    account = active_store.create_account(m.AccountCreate(portfolio_id=portfolio.id, name="Synthetic account", account_type="bank"))
    bank = active_store.create_booking(m.BookingCreate(account_id=account.id, booking_date=date(2026, 9, 5), amount=100,
        status="confirmed", payment_text="UNASSIGNED BANK CONTENT MUST NOT LEAK"))
    own_booking = active_store.create_booking(m.BookingCreate(account_id=account.id, tenant_id=own.id,
        booking_date=date(2026, 9, 6), amount=5, receipt_url="/uploads/own-synthetic.pdf"))
    charge = active_store.create_rent_charge(m.RentChargeCreate(contract_id=contracts[0].id, month="2026-09", cold_rent=100))
    receipt = active_store.record_payment("rent_charge", charge.id, payload().model_copy(update={"booking_id": bank.id}))
    active_store.reverse_payment("rent_charge", charge.id, receipt.id,
        PaymentReversalCreate(idempotency_key="synthetic-reversal", reversal_date=date(2026, 9, 7), reason="Synthetic reversal"))
    docs = [active_store.create_document(m.DocumentCreate(contract_id=contract.id, property_id=prop.id, unit_id=unit.id,
        title=f"Document {index}", file_url=f"/uploads/private-{index}.pdf")) for index, contract in enumerate(contracts)]
    thread = active_store.create_message_thread(m.MessageThreadCreate(subject="Own thread", contract_id=contracts[0].id,
        participant_ids="opaque-shared-contact", property_id=prop.id, unit_id=unit.id))
    message = active_store.create_message(m.MessageCreate(thread_id=thread.id, body="Own message", attachment_ids=f"{docs[0].id},{docs[1].id}"))
    handover = active_store.create_handover_protocol(m.HandoverProtocolCreate(contract_id=contracts[0].id, unit_id=unit.id,
        protocol_type="move_out", protocol_date=date(2026, 9, 8), photos='["/uploads/shared.jpg"]',
        tenant_signature="opaque-tenant-signature", landlord_signature="opaque-landlord-signature"))
    reading = active_store.create_meter_reading(m.MeterReadingCreate(handover_id=handover.id, meter_type="water",
        reading_value=12.5, photo_url="/uploads/shared-meter.jpg"))
    return {"own": own, "foreign": foreign, "contracts": contracts, "charge": charge, "receipt": receipt,
            "bank": bank, "own_booking": own_booking, "docs": docs, "message": message, "reading": reading}


def test_metadata_graph_follows_actual_relationships_without_shared_tenant_or_opaque_files(privacy_store):
    records = seed(privacy_store)
    graph = export_tenant_metadata(privacy_store, records["own"].id)
    encoded = json.dumps(graph)
    assert "FOREIGN PERSON" not in encoded and "foreign@example.com" not in encoded
    assert "UNASSIGNED BANK CONTENT" not in encoded
    assert [row["id"] for row in graph["contracts"]] == [records["contracts"][0].id]
    assert [row["id"] for row in graph["bookings"]] == [records["own_booking"].id]
    assert graph["payments"][0]["booking_id"] == records["bank"].id
    assert graph["payments"][0]["reversal"]["payment_id"] == records["receipt"].id
    assert graph["messages"][0]["attachment_ids"] == records["docs"][0].id
    assert "file_url" not in graph["documents"][0]
    assert "participant_ids" not in graph["message_threads"][0]
    assert "photos" not in graph["handover_protocols"][0]
    assert "photo_url" not in graph["meter_readings"][0]
    assert "notifications" in graph["scope"]["not_covered"]
    assert records["docs"][1].id not in encoded
    # Redacting the export must not mutate the stored records.
    assert privacy_store.get_document(records["docs"][0].id).file_url.endswith("private-0.pdf")
    assert privacy_store.get_message(records["message"].id).attachment_ids.endswith(records["docs"][1].id)


def test_complete_profile_anonymization_preserves_financial_receipts_and_related_records(privacy_store):
    records = seed(privacy_store)
    before = export_tenant_metadata(privacy_store, records["own"].id)
    preview = preview_tenant_anonymization(privacy_store, records["own"].id)
    result = anonymize_tenant_profile(privacy_store, records["own"].id, plan_hash=preview["plan_hash"],
                                     confirm_tenant_id=records["own"].id)
    assert result["status"] == "profile_anonymized" and result["scope"] == "tenant_profile_only"
    current = privacy_store.get_tenant(records["own"].id)
    assert current.full_name == f"Anonymisiert-{records['own'].id}" and current.archived
    for field in PROFILE_FIELDS:
        if field not in {"full_name", "archived"}:
            assert getattr(current, field) is None
    after = export_tenant_metadata(privacy_store, current.id)
    for collection, rows in before.items():
        if isinstance(rows, list):
            assert after[collection] == rows
    assert privacy_store.get_tenant(records["foreign"].id).full_name == "FOREIGN PERSON MUST NOT LEAK"


@pytest.mark.parametrize("condition", ["stale", "active", "wrong_confirmation"])
def test_unreviewed_or_active_profile_changes_are_rejected_without_partial_mutation(privacy_store, condition):
    records = seed(privacy_store)
    own_id = records["own"].id
    plan = preview_tenant_anonymization(privacy_store, own_id)
    if condition == "stale":
        privacy_store._patch_entity("tenant", own_id, m.TenantPatch(notes="Edited meanwhile"))
    elif condition == "active":
        privacy_store._patch_entity("contract", records["contracts"][0].id, m.ContractPatch(status="active"))
        plan = preview_tenant_anonymization(privacy_store, own_id)
        assert not plan["can_anonymize"]
    previous = privacy_store.get_tenant(own_id).model_dump()
    with pytest.raises(PrivacyConflict):
        anonymize_tenant_profile(privacy_store, own_id, plan_hash=plan["plan_hash"],
            confirm_tenant_id=records["foreign"].id if condition == "wrong_confirmation" else own_id)
    assert privacy_store.get_tenant(own_id).model_dump() == previous


def test_repository_failure_rolls_back_even_after_its_inner_commit(privacy_store, monkeypatch):
    records = seed(privacy_store)
    own_id = records["own"].id
    plan = preview_tenant_anonymization(privacy_store, own_id)
    previous = privacy_store.get_tenant(own_id).model_dump()
    original = type(privacy_store)._patch_entity
    def failed(active_store, *args):
        original(active_store, *args)
        raise RuntimeError("Synthetic failure after domain commit")
    monkeypatch.setattr(type(privacy_store), "_patch_entity", failed)
    with pytest.raises(RuntimeError):
        anonymize_tenant_profile(privacy_store, own_id, plan_hash=plan["plan_hash"], confirm_tenant_id=own_id)
    assert privacy_store.get_tenant(own_id).model_dump() == previous


def test_failed_collection_never_returns_partial_export_and_missing_tenant_is_distinct(privacy_store, monkeypatch):
    records = seed(privacy_store)
    with pytest.raises(TenantNotFoundError):
        export_tenant_metadata(privacy_store, "missing-tenant")
    def failed(*_):
        raise RuntimeError("Synthetic store failure")
    if hasattr(privacy_store, "db"):
        from backend.services.tenant_graph_source import TenantGraphSource
        monkeypatch.setattr(TenantGraphSource, "list_messages", failed)
    else:
        monkeypatch.setattr(type(privacy_store), "list_messages", failed)
    with pytest.raises(TenantExportError):
        export_tenant_metadata(privacy_store, records["own"].id)


def test_sql_export_is_one_snapshot_when_another_session_commits(privacy_store, monkeypatch):
    if not hasattr(privacy_store, "db"):
        pytest.skip("SQL snapshot regression")
    records = seed(privacy_store)
    engine = privacy_store.db.get_bind()
    from backend.services.tenant_graph_source import TenantGraphSource
    original = TenantGraphSource.list_contracts
    def changed(active_store):
        with Session(engine) as other:
            other.execute(update(TenantORM).where(TenantORM.id == records["own"].id).values(email="new@example.com"))
            other.execute(update(ContractORM).where(ContractORM.id == records["contracts"][0].id).values(status="expired"))
            other.commit()
        return original(active_store)
    monkeypatch.setattr(TenantGraphSource, "list_contracts", changed)
    graph = export_tenant_metadata(privacy_store, records["own"].id)
    assert graph["tenant"]["email"] == "own@example.com"
    assert graph["contracts"][0]["status"] == "terminated"
    with Session(engine) as db:
        assert db.scalar(select(TenantORM.email).where(TenantORM.id == records["own"].id)) == "new@example.com"


def test_http_export_preview_confirmation_permissions_and_error_statuses():
    store.clear_all()
    clear_users()
    try:
        records = seed(store)
        owner = register_user("privacyowner", "privacyowner@example.com", "Owner", "Strong123", role="eigentuemer")
        reader = register_user("privacyreader", "privacyreader@example.com", "Reader", "Strong123", role="readonly")
        owner_auth = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
        reader_auth = {"Authorization": f"Bearer {create_access_token(reader.id)}"}
        root = f"/api/v1/admin/dsgvo/tenant/{records['own'].id}"
        with TestClient(app) as client:
            assert client.get(root + "/export").status_code == 401
            assert client.get(root + "/export", headers=reader_auth).status_code == 403
            assert client.get("/api/v1/admin/dsgvo/tenant/missing/export", headers=owner_auth).status_code == 404
            exported = client.get(root + "/export", headers=owner_auth)
            assert exported.status_code == 200 and exported.headers["cache-control"] == "private, no-store"
            preview = client.get(root + "/anonymization-preview", headers=owner_auth).json()
            assert client.post(root + "/anonymize", headers=owner_auth).status_code == 422
            body = {"plan_hash": preview["plan_hash"], "confirm_tenant_id": records["own"].id}
            assert client.post(root + "/anonymize", headers=reader_auth, json=body).status_code == 403
            saved = client.post(root + "/anonymize", headers=owner_auth, json=body)
            assert saved.status_code == 200 and saved.json()["status"] == "profile_anonymized"
    finally:
        store.clear_all()
        clear_users()


def test_sql_reads_are_filtered_and_reversals_are_bulk_loaded(privacy_store, monkeypatch):
    if not hasattr(privacy_store, "db"):
        pytest.skip("SQL query shape")
    records = seed(privacy_store)
    def forbidden(*_):
        raise AssertionError("Global store list would load unrelated historical data")
    for name in ("list_contracts", "list_documents", "list_deposits", "list_bookings",
                 "list_receivables", "list_rent_charges", "list_payments", "list_messages"):
        monkeypatch.setattr(SQLAlchemyStore, name, forbidden)
    statements = []
    engine = privacy_store.db.get_bind()
    def observe(_connection, _cursor, sql, _parameters, _context, _many):
        if sql.lstrip().upper().startswith("SELECT"):
            statements.append(sql)
    event.listen(engine, "before_cursor_execute", observe)
    try:
        graph = export_tenant_metadata(privacy_store, records["own"].id)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert len(graph["payments"]) == 1
    assert all("WHERE" in sql.upper() for sql in statements)
    reversal_reads = [sql for sql in statements if "FROM payment_reversals" in sql]
    assert len(reversal_reads) == 1


def test_large_metadata_spills_to_disk_without_a_total_size_cap():
    import hashlib

    from backend.services.tenant_privacy import _graph_hash, metadata_download
    graph = {"large": "x" * (9 * 1024 * 1024), "unicode": "Mieter Ä"}
    output = metadata_download(graph)
    try:
        assert output._rolled
        digest = hashlib.sha256()
        size = 0
        while block := output.read(64 * 1024):
            size += len(block)
            digest.update(block)
        assert size > 8 * 1024 * 1024
        assert digest.hexdigest() == _graph_hash(graph)
    finally:
        output.close()


def test_invalid_serialization_closes_staged_output(monkeypatch):
    import backend.services.tenant_privacy as service
    original = service.SpooledTemporaryFile
    opened = []
    def capture(*args, **kwargs):
        file = original(*args, **kwargs)
        opened.append(file)
        return file
    monkeypatch.setattr(service, "SpooledTemporaryFile", capture)
    with pytest.raises(ValueError):
        service.metadata_download({"invalid": float("nan")})
    assert len(opened) == 1 and opened[0].closed
