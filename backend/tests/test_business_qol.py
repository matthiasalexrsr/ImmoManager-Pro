"""Shared office commands: scoped sources, complete pages, replay, rollback and review."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.domain.clock import local_today
from backend.models import ContactCreate, DocumentCreate, PortfolioCreate, PropertyCreate, TaskCreate
from backend.services import business_documents as documents
from backend.services import business_qol as office
from backend.services.data_snapshot import export_snapshot, import_snapshot
from backend.services.file_storage import LocalStorage
from backend.services.workspace_contexts import resolve_context

API = "/api/v1/work-center"


@pytest.fixture(autouse=True)
def clean():
    auth.clear_users()
    store.clear_all()
    yield
    auth.clear_users()
    store.clear_all()


@pytest.fixture
def owner():
    user = auth.register_user("office", "office@example.test", "Büro", "Secret123", "eigentuemer")
    client = TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})
    return user, client


@pytest.fixture
def estate(owner):
    portfolio = store.create_portfolio(PortfolioCreate(name="Nord"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
    task = store.create_task(TaskCreate(title="Rückruf", property_id=prop.id, due_date=date(2026, 10, 1)))
    return {"portfolio": portfolio, "property": prop, "task": task}


def revision(owner, kind, identifier):
    return resolve_context(store, kind, identifier, owner[0].id)["revision"]


def note(owner, estate, **changes):
    return {"entity_type": "property", "entity_id": estate["property"].id,
            "base_revision": revision(owner, "property", estate["property"].id),
            "body": "Telefonat über den Reparaturtermin", "conversation_kind": "phone",
            "idempotency_key": str(uuid4()), **changes}


def test_note_and_followup_are_atomic_replayable_shared_history(owner, estate):
    body = note(owner, estate, follow_up={"title": "Handwerker zurückrufen", "due_date": "2026-10-20"})
    response = owner[1].post(API + "/notes", json=body)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["note"]["task_id"] == saved["task"]["id"]
    assert saved["task"]["property_id"] == estate["property"].id
    # omitted occurred_at is assigned once, not re-generated into a conflicting fingerprint
    repeated = owner[1].post(API + "/notes", json=body)
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["replayed"] is True
    assert repeated.json()["note"] == saved["note"]
    assert len(store.list_tasks()) == 2
    timeline = owner[1].get(API + "/timeline", params={"entity_type": "property", "entity_id": estate["property"].id})
    assert timeline.status_code == 200, timeline.text
    assert any(row["id"] == saved["note"]["id"] and row["task_id"] == saved["task"]["id"]
               for row in timeline.json()["items"])
    changed_key = owner[1].post(API + "/notes", json={**body, "body": "Andere Notiz"})
    assert changed_key.status_code == 409


def test_failed_note_receipt_rolls_back_followup_and_note(owner, estate, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic receipt failure")
    monkeypatch.setattr(office, "save_command", fail)
    with pytest.raises(RuntimeError, match="synthetic"):
        owner[1].post(API + "/notes", json=note(owner, estate, follow_up={"title": "Keine verwaiste Aufgabe"}))
    assert len(store.list_tasks()) == 1
    assert not export_snapshot(store)["business_conversation_notes"]


def test_quick_edit_undo_replay_and_intervening_change(owner, estate):
    task = estate["task"]
    body = {"entity_type": "task", "entity_id": task.id, "base_revision": revision(owner, "task", task.id),
            "changes": {"priority": "high", "status": "in_progress"}, "idempotency_key": str(uuid4())}
    response = owner[1].post(API + "/quick-edits", json=body)
    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited["record"]["priority"] == "high"
    assert owner[1].post(API + "/quick-edits", json=body).json()["replayed"] is True
    undo = {"base_revision": edited["revision"], "idempotency_key": str(uuid4())}
    response = owner[1].post(API + f"/quick-edits/{edited['undo_id']}/undo", json=undo)
    assert response.status_code == 200, response.text
    assert response.json()["record"]["priority"] == "medium"
    assert response.json()["record"]["status"] == "open"
    assert owner[1].post(API + f"/quick-edits/{edited['undo_id']}/undo", json=undo).json()["replayed"] is True
    fresh = owner[1].post(API + "/quick-edits", json={**body, "base_revision": response.json()["revision"],
                                                       "changes": {"assignee": "Anna"}, "idempotency_key": str(uuid4())})
    assert fresh.status_code == 200, fresh.text
    owner[1].patch(f"/api/v1/tasks/{task.id}", json={"title": "Zwischenzeitlich geändert"})
    stale = owner[1].post(API + f"/quick-edits/{fresh.json()['undo_id']}/undo", json={
        "base_revision": fresh.json()["revision"], "idempotency_key": str(uuid4())})
    assert stale.status_code == 409
    assert store.get_task(task.id).title == "Zwischenzeitlich geändert"
    assert store.get_task(task.id).assignee == "Anna"


def test_work_center_pages_and_counts_do_not_load_bookings(owner, estate, monkeypatch):
    for number in range(22):
        store.create_task(TaskCreate(title=f"Arbeit {number}", property_id=estate["property"].id,
                                     due_date=date(2026, 10, 1) + timedelta(days=number % 3)))
    store.create_task(TaskCreate(title="Schon erledigt", status="done", property_id=estate["property"].id))
    def no_bookings(*args, **kwargs):
        raise AssertionError("work center must not read whole booking history")
    monkeypatch.setattr(store, "list_bookings", no_bookings)
    ids, cursor = [], None
    while True:
        result = owner[1].get(API + "/items", params={"kind": "task", "limit": 4, **({"cursor": cursor} if cursor else {})})
        assert result.status_code == 200, result.text
        payload = result.json()
        ids += [row["entity_id"] for row in payload["items"]]
        if not payload["has_more"]:
            break
        cursor = payload["next_cursor"]
    assert len(ids) == len(set(ids)) == 23
    result = owner[1].get(API + "/summary")
    assert result.status_code == 200, result.text
    assert result.json()["counts"]["task"] == 23
    assert result.json()["drilldowns"]["task"]["query"]["kind"] == "task"


def test_timeline_continues_without_losing_same_time_rows(owner, estate):
    for number in range(9):
        response = owner[1].post(API + "/notes", json=note(owner, estate, body=f"Notiz {number}",
                                                           occurred_at="2026-10-01T12:00:00Z"))
        assert response.status_code == 201, response.text
    seen, cursor = [], None
    while True:
        result = owner[1].get(API + "/timeline", params={"entity_type": "property", "entity_id": estate["property"].id,
                                                          "limit": 3, **({"cursor": cursor} if cursor else {})})
        assert result.status_code == 200, result.text
        payload = result.json()
        seen += [row["id"] for row in payload["items"]]
        if not payload["has_more"]:
            break
        cursor = payload["next_cursor"]
    assert len(seen) == len(set(seen))
    assert len(seen) >= 10  # includes the related pre-existing task


@pytest.fixture
def file_storage(tmp_path, monkeypatch):
    storage = LocalStorage(tmp_path / "uploads")
    monkeypatch.setattr(documents, "get_file_storage", lambda: storage)
    monkeypatch.setattr(documents, "analyze_bytes", lambda *args, **kwargs: {
        "document_type": "invoice", "summary": "Vorschlag", "supplier": "Handwerk", "total_amount": 119})
    return storage


def make_document(estate, storage, number=1, content=b"synthetic invoice"):
    key = f"documents/qol-{number}.pdf"
    storage.save(key, BytesIO(content))
    return store.create_document(DocumentCreate(property_id=estate["property"].id, title=f"Eingang {number}",
                                                file_url="/uploads/" + key))


def test_document_proposal_requires_explicit_cas_review(owner, estate, file_storage):
    document = make_document(estate, file_storage)
    body = {"base_revision": revision(owner, "document", document.id), "idempotency_key": str(uuid4())}
    result = owner[1].post(API + f"/documents/{document.id}/process", json=body)
    assert result.status_code == 200, result.text
    intake = result.json()["intake"]
    assert intake["status"] == "review" and intake["sha256"]
    assert store.get_document(document.id).document_type is None
    assert store.list_invoices() == []
    assert owner[1].post(API + f"/documents/{document.id}/process", json=body).json()["replayed"] is True
    review = {"base_revision": intake["revision"], "document_revision": intake["document_revision"],
              "changes": {"document_type": "invoice", "title": "Geprüfte Rechnung"}, "idempotency_key": str(uuid4())}
    result = owner[1].post(API + f"/documents/{document.id}/review", json=review)
    assert result.status_code == 200, result.text
    assert result.json()["intake"]["status"] == "done"
    assert store.get_document(document.id).title == "Geprüfte Rechnung"
    assert owner[1].get(API + "/documents", params={"status": "done"}).json()["items"][0]["document_id"] == document.id
    assert owner[1].post(API + f"/documents/{document.id}/review", json=review).json()["replayed"] is True


def test_document_failure_is_durable_and_new_attempt_can_recover(owner, estate, file_storage, monkeypatch):
    document = make_document(estate, file_storage)
    def fail(*args, **kwargs):
        raise ValueError("synthetic OCR failure")
    monkeypatch.setattr(documents, "analyze_bytes", fail)
    body = {"base_revision": revision(owner, "document", document.id), "idempotency_key": str(uuid4())}
    result = owner[1].post(API + f"/documents/{document.id}/process", json=body)
    assert result.status_code == 200, result.text
    assert result.json()["intake"]["status"] == "failed"
    assert result.json()["intake"]["sha256"]  # indexing succeeds even when OCR cannot extract text
    assert owner[1].get(API + f"/documents/{document.id}").json()["intake"]["status"] == "failed"
    indexed = owner[1].post(API + "/duplicates/check", json={"kind": "file", "candidate": {"document_id": document.id},
        "exclude_id": document.id})
    assert indexed.status_code == 200, indexed.text
    assert indexed.json()["coverage"]["complete"] is True
    assert indexed.json()["coverage"]["indexed_count"] == 1
    monkeypatch.setattr(documents, "analyze_bytes", lambda *args, **kwargs: {"summary": "Jetzt lesbar"})
    result = owner[1].post(API + f"/documents/{document.id}/process", json={**body, "idempotency_key": str(uuid4())})
    assert result.status_code == 200, result.text
    assert result.json()["intake"]["status"] == "review"


def test_contact_duplicate_pages_and_justified_exception(owner, estate):
    first = store.create_contact(ContactCreate(first_name="Mia", email="MIA@example.test"))
    other = store.create_contact(ContactCreate(first_name="Mia 2", email="mia@example.test"))
    result = owner[1].post(API + "/duplicates/check", json={"kind": "contact", "candidate": {"email": " mia@example.test "},
                                                            "exclude_id": first.id, "limit": 1})
    assert result.status_code == 200, result.text
    assert result.json()["items"][0]["id"] == other.id
    request = {"kind": "contact", "entity_id": first.id, "duplicate_id": other.id,
               "base_revision": revision(owner, "contact", first.id), "duplicate_revision": revision(owner, "contact", other.id),
               "reason": "Zwei verschiedene Ansprechpartner derselben Firma", "idempotency_key": str(uuid4())}
    saved = owner[1].post(API + "/duplicates/exceptions", json=request)
    assert saved.status_code == 201, saved.text
    assert saved.json()["exception"]["reason"] == request["reason"]
    assert owner[1].post(API + "/duplicates/exceptions", json=request).json()["replayed"] is True
    assert len(store.list_contacts()) == 2
    checked = owner[1].post(API + "/duplicates/check", json={"kind": "contact", "candidate": {"email": first.email},
        "exclude_id": first.id}).json()
    assert checked["items"][0]["exception"]["reason"] == request["reason"]
    reverse = owner[1].post(API + "/duplicates/check", json={"kind": "contact", "candidate": {"email": other.email},
        "exclude_id": other.id}).json()
    assert reverse["items"][0]["exception"]["id"] == saved.json()["exception"]["id"]
    owner[1].patch(f"/api/v1/contacts/{other.id}", json={"first_name": "Veränderter Ansprechpartner"})
    checked = owner[1].post(API + "/duplicates/check", json={"kind": "contact", "candidate": {"email": first.email},
        "exclude_id": first.id}).json()
    assert checked["items"][0]["exception"] is None


def test_hash_duplicates_preserve_both_documents(owner, estate, file_storage):
    first = make_document(estate, file_storage, 1)
    second = make_document(estate, file_storage, 2)
    for document in (first, second):
        result = owner[1].post(API + f"/documents/{document.id}/process", json={
            "base_revision": revision(owner, "document", document.id), "idempotency_key": str(uuid4())})
        assert result.status_code == 200, result.text
    result = owner[1].post(API + "/duplicates/check", json={"kind": "file", "candidate": {"document_id": first.id},
                                                            "exclude_id": first.id})
    assert result.status_code == 200, result.text
    assert [(row["id"], row["confidence"]) for row in result.json()["items"]] == [(second.id, "confirmed")]
    assert len(store.list_documents()) == 2


def test_shared_business_records_survive_snapshot(owner, estate):
    response = owner[1].post(API + "/notes", json=note(owner, estate, follow_up={"title": "Nachfragen"}))
    assert response.status_code == 201, response.text
    snapshot = export_snapshot(store)
    assert snapshot["business_conversation_notes"]
    assert snapshot["business_qol_commands"]
    import_snapshot(store, snapshot, replace=True)
    timeline = owner[1].get(API + "/timeline", params={"entity_type": "property", "entity_id": estate["property"].id})
    assert timeline.status_code == 200, timeline.text
    assert any(row["id"] == response.json()["note"]["id"] for row in timeline.json()["items"])


def test_readonly_duplicate_check_is_readonly_and_business_writes_remain_forbidden(owner, estate):
    user = auth.register_user("viewer", "viewer@example.test", "Leser", "Secret123", "readonly")
    client = TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})
    existing = store.create_contact(ContactCreate(first_name="Mia", email="mia@example.test"))
    before = export_snapshot(store)
    result = client.post(API + "/duplicates/check", json={"kind": "contact", "candidate": {"email": existing.email}})
    assert result.status_code == 200, result.text
    after = export_snapshot(store)
    assert after.get("audit_logs") == before.get("audit_logs")
    assert after["business_qol_commands"] == before["business_qol_commands"]
    assert client.post(API + "/notes", json=note(owner, estate)).status_code == 403
    assert client.post(API + "/quick-edits", json={"entity_id": estate["task"].id,
        "base_revision": revision(owner, "task", estate["task"].id), "changes": {"priority": "high"},
        "idempotency_key": str(uuid4())}).status_code == 403
    assert client.post(API + "/duplicates/exceptions", json={"kind": "contact", "entity_id": existing.id,
        "duplicate_id": existing.id, "base_revision": "0", "duplicate_revision": "0", "reason": "Dauerhafte Ausnahme",
        "idempotency_key": str(uuid4())}).status_code == 403
    assert TestClient(app).post(API + "/duplicates/check", json={"kind": "contact", "candidate": {}}).status_code == 401


def test_completed_alias_is_canonical_and_not_an_open_work_item(owner, estate):
    result = owner[1].post(API + "/quick-edits", json={"entity_id": estate["task"].id,
        "base_revision": revision(owner, "task", estate["task"].id), "changes": {"status": "done"},
        "idempotency_key": str(uuid4())})
    assert result.status_code == 200, result.text
    assert result.json()["record"]["status"] == "completed"
    assert owner[1].get(API + "/items", params={"kind": "task"}).json()["items"] == []


def test_file_check_reports_unindexed_and_partial_candidate(owner, estate, file_storage, monkeypatch):
    first, second = make_document(estate, file_storage, 1), make_document(estate, file_storage, 2)
    result = owner[1].post(API + "/duplicates/check", json={"kind": "file", "candidate": {"document_id": first.id},
                                                           "exclude_id": first.id})
    assert result.status_code == 200, result.text
    assert result.json()["coverage"]["unindexed_count"] == 2
    assert result.json()["coverage"]["complete"] is False
    # Checksum operations must not call the full-buffer storage API.
    monkeypatch.setattr(file_storage, "get", lambda key: pytest.fail("unbounded checksum read"))
    assert documents.file_hash(first.file_url) == documents.file_hash(second.file_url)
    for kind in ("file", "invoice"):
        result = owner[1].post(API + "/duplicates/check", json={"kind": kind, "candidate": {}})
        assert result.status_code == 200, result.text
        assert result.json()["incomplete"] is True


def test_related_timeline_includes_documents_tasks_payments_damage_changes_and_actor(owner, estate, file_storage):
    from backend.models import AccountCreate, BookingCreate, MaintenanceCaseCreate, PortfolioCreate
    document = make_document(estate, file_storage)
    account = store.create_account(AccountCreate(portfolio_id=estate["portfolio"].id, name="Bank", account_type="bank"))
    payment = store.create_booking(BookingCreate(account_id=account.id, property_id=estate["property"].id,
        booking_date=date(2026, 10, 1), amount=100, payment_text="Miete"))
    damage = store.create_maintenance_case(MaintenanceCaseCreate(property_id=estate["property"].id, title="Wasserschaden"))
    posted = owner[1].post(API + "/notes", json=note(owner, estate))
    assert posted.status_code == 201, posted.text
    edited = owner[1].patch(f"/api/v1/tasks/{estate['task'].id}", json={"priority": "urgent"})
    assert edited.status_code == 200, edited.text
    data = owner[1].get(API + "/timeline", params={"entity_type": "property", "entity_id": estate["property"].id}).json()
    entities = {(row["entity"]["type"], row["entity"]["id"]) for row in data["items"]}
    assert {("document", document.id), ("task", estate["task"].id), ("booking", payment.id), ("maintenance", damage.id)} <= entities
    assert any(row["kind"] == "change" and row["entity"]["id"] == estate["task"].id for row in data["items"])
    assert next(row for row in data["items"] if row["id"] == posted.json()["note"]["id"])["actor"] == "Büro"
    # A second portfolio is not included through an unrelated source.
    foreign = store.create_portfolio(PortfolioCreate(name="Fremd"))
    foreign_prop = store.create_property(PropertyCreate(portfolio_id=foreign.id, name="Fremdhaus", property_type="residential"))
    other = store.create_task(TaskCreate(title="Fremd", property_id=foreign_prop.id))
    data = owner[1].get(API + "/timeline", params={"entity_type": "property", "entity_id": estate["property"].id}).json()
    assert all(row["entity"]["id"] != other.id for row in data["items"])


def test_all_work_sources_property_filter_and_real_missing_readings(owner, estate):
    from backend.models import (
        AllocationKeyCreate,
        BillingPeriodCreate,
        ContractCreate,
        CostItemCreate,
        HandoverProtocolCreate,
        MeterCreate,
        StandaloneMeterReadingCreate,
        TenantCreate,
        UnitCreate,
    )
    from backend.services import workspace_work_items as sources
    unit = store.create_unit(UnitCreate(property_id=estate["property"].id, label="Wohnung", unit_type="residential"))
    tenant = store.create_tenant(TenantCreate(full_name="Mieter"))
    contract = store.create_contract(ContractCreate(property_id=estate["property"].id, unit_id=unit.id,
        tenant_id=tenant.id, contract_number="ALT", start_date=date(2020, 1, 1)))
    protocol = store.create_handover_protocol(HandoverProtocolCreate(contract_id=contract.id, unit_id=unit.id,
        protocol_type="move_in", protocol_date=date(2020, 1, 1)))
    meter = store.create_meter(MeterCreate(unit_id=unit.id, meter_type="cold_water", next_inspection=date(2024, 1, 1)))
    period = store.create_billing_period(BillingPeriodCreate(property_id=estate["property"].id, label="2025",
        start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)))
    key = store.create_allocation_key(AllocationKeyCreate(property_id=estate["property"].id, name="Wasser",
        key_type="consumption", meter_type="cold_water"))
    store.create_cost_item(CostItemCreate(billing_period_id=period.id, description="Wasser", amount=100, allocation_key_id=key.id))
    for kind in sources.SOURCES:
        result = owner[1].get(API + "/items", params={"kind": kind, "property_id": estate["property"].id})
        assert result.status_code == 200, (kind, result.text)
    result = owner[1].get(API + "/summary", params={"property_id": estate["property"].id})
    assert result.status_code == 200, result.text
    assert result.json()["counts"]["meter_reading"] == 1
    assert result.json()["counts"]["tenant_change"] == 1  # unresolved even six years later
    assert sources.resolve_work_item(store, f"tenant_change:{protocol.id}:turnover_incomplete", owner[0].id)
    for day in (period.start_date, period.end_date):
        store.create_standalone_meter_reading(StandaloneMeterReadingCreate(meter_id=meter.id, reading_date=day, value=1))
    assert owner[1].get(API + "/items", params={"kind": "meter_reading"}).json()["items"] == []


def test_memory_history_failure_restores_source_and_no_partial_history(owner, estate, monkeypatch):
    if hasattr(store, "db"):
        pytest.skip("memory failure journal")
    from backend.models import TaskPatch
    from backend.services.portfolio_scope import scope_context, scope_from_user
    raw = object.__getattribute__(store, "__dict__")
    class FailSecond(dict):
        writes = 0
        def __setitem__(self, key, value):
            self.writes += 1
            if self.writes == 2:
                raise RuntimeError("synthetic history failure")
            super().__setitem__(key, value)
    history = FailSecond()
    monkeypatch.setitem(raw, "change_history", history)
    original = store.get_task(estate["task"].id).model_dump()
    user = auth.get_user_by_id(owner[0].id)
    assert user is not None
    with scope_context(scope_from_user(user)):
        with pytest.raises(RuntimeError, match="history failure"):
            store._patch_entity("task", estate["task"].id, TaskPatch(title="Changed", priority="high"))
    assert store.get_task(estate["task"].id).model_dump() == original
    assert not history


def test_document_metadata_undo_is_atomic_and_rejects_intervening_change(owner, estate, file_storage):
    document = make_document(estate, file_storage)
    processed = owner[1].post(API + f"/documents/{document.id}/process", json={
        "base_revision": revision(owner, "document", document.id), "idempotency_key": str(uuid4())}).json()["intake"]
    body = {"base_revision": processed["revision"], "document_revision": processed["document_revision"],
            "changes": {"title": "Geprüft", "tags": "verknüpft"}, "idempotency_key": str(uuid4())}
    reviewed = owner[1].post(API + f"/documents/{document.id}/review", json=body)
    assert reviewed.status_code == 200, reviewed.text
    undo = {"base_revision": reviewed.json()["revision"], "idempotency_key": str(uuid4())}
    restored = owner[1].post(API + f"/quick-edits/{reviewed.json()['undo_id']}/undo", json=undo)
    assert restored.status_code == 200, restored.text
    assert restored.json()["document"]["title"] == document.title
    assert restored.json()["document"]["tags"] is None
    assert restored.json()["intake"]["status"] == "review"
    assert owner[1].post(API + f"/quick-edits/{reviewed.json()['undo_id']}/undo", json=undo).json()["replayed"] is True
    state = restored.json()["intake"]
    again = owner[1].post(API + f"/documents/{document.id}/review", json={**body,
        "base_revision": state["revision"], "document_revision": state["document_revision"], "idempotency_key": str(uuid4())})
    assert again.status_code == 200, again.text
    assert owner[1].patch(f"/api/v1/documents/{document.id}", json={"description": "Spätere Bearbeitung"}).status_code == 200
    result = owner[1].post(API + f"/quick-edits/{again.json()['undo_id']}/undo", json={
        "base_revision": again.json()["revision"], "idempotency_key": str(uuid4())})
    assert result.status_code == 409
    assert store.get_document(document.id).description == "Spätere Bearbeitung"


def test_archive_original_is_matched_without_intake_and_blocks_are_verified(owner, estate, file_storage):
    from archive_helpers import purge_originals

    from backend.services import document_versions as archive
    content = b"%PDF-synthetic invoice"
    first = make_document(estate, file_storage, 1, content)
    second = make_document(estate, file_storage, 2, content)
    try:
        with archive.work(store, owner[0].id, write_areas=("/documents",)) as unit:
            _, binding = archive.bind_document(unit, second.id, lock=True)
            archive.publish_generated_original(unit, second, binding, content, "a" * 64,
                                                version_id="qol-original")
        result = owner[1].post(API + "/duplicates/check", json={"kind": "file", "candidate": {"document_id": first.id},
            "exclude_id": first.id})
        assert result.status_code == 200, result.text
        assert result.json()["items"][0]["id"] == second.id
        assert result.json()["items"][0]["reason"] == "archived_content"
        assert result.json()["coverage"]["indexed_count"] == 1
    finally:
        purge_originals(store)


def test_independent_request_writers_serialize_retries_and_reject_lost_updates(owner, estate, monkeypatch):
    # TestClient creates independent request sessions, and archive.work creates
    # an independent writer Session per command (also on native PostgreSQL).
    postgres_pids: set[int] = set()
    native = hasattr(store, "db") and store.db.get_bind().dialect.name == "postgresql"
    if native:
        from threading import Barrier

        from backend.services import document_versions as archive
        ready = Barrier(2)
        begin = archive.begin_writer
        def begin_independently(db):
            begin(db)
            if len(postgres_pids) < 2:
                connection = db.connection().connection.driver_connection
                postgres_pids.add(connection.get_backend_pid())
                ready.wait(timeout=15)
        monkeypatch.setattr(archive, "begin_writer", begin_independently)
    def submit(body):
        client = TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(owner[0].id)}"})
        return client.post(API + "/quick-edits", json=body)
    base = revision(owner, "task", estate["task"].id)
    bodies = [{"entity_id": estate["task"].id, "base_revision": base,
        "changes": {"priority": priority}, "idempotency_key": str(uuid4())} for priority in ("high", "low")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, bodies))
    assert sorted(row.status_code for row in results) == [200, 409], [row.text for row in results]
    if native:
        assert len(postgres_pids) == 2
    body = note(owner, estate, follow_up={"title": "Nur eine Folgeaufgabe"})
    def create(_):
        client = TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(owner[0].id)}"})
        return client.post(API + "/notes", json=body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    assert [row.status_code for row in results] == [201, 201], [row.text for row in results]
    assert sorted(row.json()["replayed"] for row in results) == [False, True]
    assert results[0].json()["note"]["id"] == results[1].json()["note"]["id"]
    assert len(store.list_tasks()) == 2


def test_source_change_during_extraction_is_visible_failure_not_applied_proposal(owner, estate, file_storage, monkeypatch):
    document = make_document(estate, file_storage)
    def analysis(*args, **kwargs):
        assert owner[1].patch(f"/api/v1/documents/{document.id}", json={"title": "Zwischenzeitlich geändert"}).status_code == 200
        return {"summary": "Veralteter Vorschlag"}
    monkeypatch.setattr(documents, "analyze_bytes", analysis)
    result = owner[1].post(API + f"/documents/{document.id}/process", json={
        "base_revision": revision(owner, "document", document.id), "idempotency_key": str(uuid4())})
    assert result.status_code == 200, result.text
    assert result.json()["intake"]["status"] == "failed"
    assert result.json()["intake"]["result"] is None
    assert "geändert" in result.json()["intake"]["error"]
    assert store.get_document(document.id).title == "Zwischenzeitlich geändert"


def test_pending_process_retry_has_same_intake_shape_and_revoked_writer_cannot_publish(owner, estate, file_storage, monkeypatch):
    document = make_document(estate, file_storage)
    body = {"base_revision": revision(owner, "document", document.id), "idempotency_key": str(uuid4())}
    def analysis(*args, **kwargs):
        retried = owner[1].post(API + f"/documents/{document.id}/process", json=body)
        assert retried.status_code == 200, retried.text
        assert retried.json()["intake"]["status"] == "processing"
        assert retried.json()["replayed"] is True
        auth.update_user(owner[0].id, {"role": "readonly"})
        return {"summary": "Nach Rechteentzug nicht übernehmen"}
    monkeypatch.setattr(documents, "analyze_bytes", analysis)
    result = owner[1].post(API + f"/documents/{document.id}/process", json=body)
    assert result.status_code == 403, result.text
    auth.update_user(owner[0].id, {"role": "eigentuemer"})
    detail = owner[1].get(API + f"/documents/{document.id}").json()["intake"]
    assert detail["status"] == "processing" and detail["result"] is None
    assert store.get_document(document.id).document_type is None


def test_scoped_history_queue_counts_and_replayed_commands_recheck_access(owner, estate, file_storage):
    other_portfolio = store.create_portfolio(PortfolioCreate(name="Fremder Bestand"))
    foreign = store.create_property(PropertyCreate(portfolio_id=other_portfolio.id, name="Fremdhaus", property_type="residential"))
    foreign_task = store.create_task(TaskCreate(title="Fremde Aufgabe", property_id=foreign.id))
    staff = auth.register_user("scoped", "scoped@example.test", "Verwaltung", "Secret123", "verwalter",
        portfolio_access="selected", portfolio_ids=[estate["portfolio"].id])
    client = TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(staff.id)}"})
    body = note(owner, estate)
    saved = client.post(API + "/notes", json=body)
    assert saved.status_code == 201, saved.text
    assert client.get(API + "/summary").json()["counts"]["task"] == 1
    assert client.get(API + "/timeline", params={"entity_type": "property", "entity_id": foreign.id}).status_code == 404
    assert client.post(API + "/quick-edits", json={"entity_id": foreign_task.id,
        "base_revision": revision(owner, "task", foreign_task.id), "changes": {"status": "completed"},
        "idempotency_key": str(uuid4())}).status_code == 404
    auth.update_user(staff.id, {"portfolio_access": "selected", "portfolio_ids": [other_portfolio.id]})
    assert client.post(API + "/notes", json=body).status_code == 404
    assert client.get(API + "/timeline", params={"entity_type": "property", "entity_id": estate["property"].id}).status_code == 404


def test_personal_deferral_filters_page_in_sql_without_altering_task_due_date(owner, estate):
    today = documents.office.local_today()
    for number in range(7):
        task = store.create_task(TaskCreate(title=f"Später {number}", property_id=estate["property"].id, due_date=date(2026, 1, 1)))
        response = owner[1].put(f"/api/v1/workspace/deferrals/task:{task.id}:task_due", json={
            "base_revision": 0, "due_on": (today + timedelta(days=7)).isoformat(), "reason": "Warte auf Antwort",
            "idempotency_key": str(uuid4())})
        assert response.status_code == 200, response.text
    reached = owner[1].put(f"/api/v1/workspace/deferrals/task:{estate['task'].id}:task_due", json={
        "base_revision": 0, "due_on": today.isoformat(), "reason": "Heute erneut prüfen", "idempotency_key": str(uuid4())})
    assert reached.status_code == 200, reached.text
    for mode in ("active", "due"):
        result = owner[1].get(API + "/items", params={"kind": "task", "deferred": mode, "limit": 1})
        assert result.status_code == 200, result.text
        assert [row["entity_id"] for row in result.json()["items"]] == [estate["task"].id]
        assert result.json()["items"][0]["due_again"] is True
        assert result.json()["has_more"] is False
        assert owner[1].get(API + "/summary", params={"deferred": mode}).json()["counts"]["task"] == 1
    assert store.get_task(estate["task"].id).due_date == date(2026, 10, 1)


def test_invoice_duplicate_number_normalization_does_not_drop_old_separator_match(owner, estate):
    from backend.models import InvoiceCreate
    invoice = store.create_invoice(InvoiceCreate(property_id=estate["property"].id, supplier="Handwerk GmbH",
        invoice_date=date(2020, 1, 1), net_amount=100, gross_amount=119))
    # invoice_number is supplied by the existing review record extension.
    if hasattr(store, "db"):
        from sqlalchemy import select

        from backend.db.orm_models import InvoiceORM
        row = store.db.scalar(select(InvoiceORM).where(InvoiceORM.id == invoice.id))
        row.invoice_number = "RE1-0"
        store.db.commit()
    else:
        setattr(invoice, "invoice_number", "RE1-0")
    result = owner[1].post(API + "/duplicates/check", json={"kind": "invoice", "candidate": {
        "supplier": "Handwerk", "invoice_number": "RE-0010", "invoice_date": "2026-10-01", "gross_amount": 250}})
    assert result.status_code == 200, result.text
    assert [(row["id"], row["reason"]) for row in result.json()["items"]] == [(invoice.id, "same_number")]
    from backend.services.invoice_review import duplicate_check
    original = duplicate_check(store, supplier="Handwerk", invoice_number="RE-0010",
                               invoice_date=date(2026, 10, 1), gross_amount=250)
    assert [(row["invoice_id"], row["reason"]) for row in original["duplicates"]] == [(invoice.id, "same_number")]


def test_dashboard_escalation_source_exactly_matches_rules_and_pages(owner, estate):
    from backend.models import EscalationRuleCreate, MaintenanceCaseCreate
    from backend.routers.dashboard import _count_maintenance_escalation_candidates
    today = local_today()
    for days in (10, 3, -1):
        store.create_escalation_rule(EscalationRuleCreate(name=f"Regel {days}", entity_type="maintenance",
            condition_field="due_date", days_overdue=days, action="notify"))
    wanted = set()
    for number, status in enumerate(("open", "pending", "review", "in_progress", "done", "closed")):
        row = store.create_maintenance_case(MaintenanceCaseCreate(property_id=estate["property"].id,
            title=f"Fall {number}", status=status, due_date=today - timedelta(days=number)))
        if status in ("open", "pending", "review", "in_progress"):
            wanted.add(row.id)
    store.create_maintenance_case(MaintenanceCaseCreate(property_id=estate["property"].id,
        title="Zukunft", due_date=today + timedelta(days=1)))
    expected = _count_maintenance_escalation_candidates(store.list_maintenance_cases(), store.list_escalation_rules(), today)
    seen: list[str] = []
    for skip in range(0, expected + 2, 2):
        result = owner[1].get("/api/v1/maintenance", params={"workflow_filter": "escalation", "skip": skip, "limit": 2})
        assert result.status_code == 200, result.text
        seen.extend(row["id"] for row in result.json())
    assert set(seen) == wanted and len(seen) == len(set(seen)) == expected


def test_dashboard_billing_blocker_source_matches_exact_summary_not_warnings(owner, estate):
    from backend.models import (
        AllocationKeyCreate,
        BillingPeriodCreate,
        ContractCreate,
        CostItemCreate,
        TenantCreate,
        UnitCreate,
    )
    from backend.routers.dashboard import _billing_preflight_summary
    unit = store.create_unit(UnitCreate(property_id=estate["property"].id, label="Wohnung", unit_type="residential"))
    tenant = store.create_tenant(TenantCreate(full_name="Mieter"))
    store.create_contract(ContractCreate(property_id=estate["property"].id, unit_id=unit.id, tenant_id=tenant.id,
        contract_number="V", start_date=date(2025, 1, 1)))
    key = store.create_allocation_key(AllocationKeyCreate(property_id=estate["property"].id, name="Fläche", key_type="area_sqm"))
    missing = store.create_billing_period(BillingPeriodCreate(property_id=estate["property"].id, label="Keine Kosten",
        start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)))
    warning = store.create_billing_period(BillingPeriodCreate(property_id=estate["property"].id, label="Nur Warnung",
        start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)))
    store.create_cost_item(CostItemCreate(billing_period_id=warning.id, description="Null", amount=0, allocation_key_id=key.id))
    old = store.create_billing_period(BillingPeriodCreate(property_id=estate["property"].id, label="Ohne Vertrag",
        start_date=date(2020, 1, 1), end_date=date(2020, 12, 31)))
    store.create_cost_item(CostItemCreate(billing_period_id=old.id, description="Kosten", amount=10, allocation_key_id=key.id))
    expected = _billing_preflight_summary(store.list_billing_periods(), store.list_contracts(), store.list_cost_items(), store.list_allocation_keys())
    result = owner[1].get("/api/v1/billing/periods", params={"workflow_filter": "preflight_blockers"})
    assert result.status_code == 200, result.text
    assert {row["id"] for row in result.json()} == {missing.id, old.id}
    assert len(result.json()) == expected["blockers"] == 2
    assert expected["warnings"] == 1


def test_dunning_work_deadline_is_final_letter_payment_deadline_not_tenancy_start(owner):
    from archive_helpers import purge_originals
    from test_dunning import _finalize, _lease, _run
    lease = _lease()
    headers = {"Authorization": f"Bearer {auth.create_access_token(owner[0].id)}"}
    try:
        run = _run(owner[1], headers, lease["contract"].id, "2026-07-15")
        letter = run["letters"][0]
        pending = owner[1].get(API + "/items", params={"kind": "dunning"})
        assert pending.status_code == 200, pending.text
        assert pending.json()["items"][0]["due_date"] is None
        result = _finalize(owner[1], headers, letter["id"])
        assert result.status_code == 200, result.text
        final = result.json()
        cards = owner[1].get(API + "/items", params={"kind": "dunning"})
        assert cards.status_code == 200, cards.text
        assert cards.json()["items"][0]["due_date"] == final["payment_deadline"]
        assert cards.json()["items"][0]["due_date"] != lease["contract"].start_date.isoformat()
        before = (date.fromisoformat(final["payment_deadline"]) - timedelta(days=1)).isoformat()
        assert owner[1].get(API + "/items", params={"kind": "dunning", "due_before": before}).json()["items"] == []
        assert owner[1].get(API + "/summary", params={"due_before": before}).json()["counts"]["dunning"] == 0
        old_key = cards.json()["items"][0]["work_item_key"]
        deferred = owner[1].put("/api/v1/workspace/deferrals/" + old_key, json={"base_revision": 0,
            "due_on": (local_today() + timedelta(days=30)).isoformat(), "reason": "Antwort zur alten Akte abwarten",
            "idempotency_key": str(uuid4())})
        assert deferred.status_code == 200, deferred.text
        assert owner[1].get(API + "/items", params={"kind": "dunning", "deferred": "active"}).json()["items"] == []
        closed = owner[1].post(f"/api/v1/dunning/cases/{letter['case_id']}/result", json={"result": "written_off",
            "result_date": "2026-07-30", "reference": "Abschluss alte Akte"})
        assert closed.status_code == 200, closed.text
        # Manual standalone receivables are deliberately excluded by dunning;
        # a later genuine rent month starts a new case for this same tenancy.
        extended = owner[1].patch(f"/api/v1/contracts/{lease['contract'].id}", json={"end_date": "2026-08-31"})
        assert extended.status_code == 200, extended.text
        new_run = _run(owner[1], headers, lease["contract"].id, "2026-08-15")
        assert len(new_run["letters"]) == 1
        fresh = owner[1].get(API + "/items", params={"kind": "dunning", "deferred": "active"})
        assert fresh.status_code == 200, fresh.text
        assert len(fresh.json()["items"]) == 1
        assert fresh.json()["items"][0]["work_item_key"] != old_key
        assert fresh.json()["items"][0]["due_date"] is None  # old case deadline does not leak into new case
        assert owner[1].get("/api/v1/workspace/deferrals/" + old_key).status_code == 404
    finally:
        purge_originals(store)


def test_filed_documents_leave_the_open_intake_but_invoice_receipts_and_started_analyses_stay(owner, estate, file_storage):
    """A classified, assigned document is filed: it counted as an open intake item for ever (92 on the test version)."""
    receipt = make_document(estate, file_storage, 1)                       # assigned, not classified: to be processed
    filed = store.create_document(DocumentCreate(property_id=estate["property"].id, title="Energieausweis",
                                                 document_type="Energieausweis", file_url="/uploads/documents/qol-2.pdf"))
    invoice = store.create_document(DocumentCreate(property_id=estate["property"].id, title="Rechnung Dach",
                                                   document_type="Rechnung", file_url="/uploads/documents/qol-3.pdf"))
    unassigned = store.create_document(DocumentCreate(title="Scan", document_type="Sonstiges",
                                                      file_url="/uploads/documents/qol-4.pdf"))
    def open_ids():
        return {row["document_id"] for row in owner[1].get(API + "/documents").json()["items"]}
    assert open_ids() == {receipt.id, invoice.id, unassigned.id}
    assert owner[1].get(API + "/summary").json()["counts"]["document"] == 3
    # still reachable for an analysis on purpose
    assert filed.id in {row["document_id"] for row in owner[1].get(API + "/documents", params={"status": "pending"}).json()["items"]}
    # an analysis once started stays open until it is reviewed
    file_storage.save("documents/qol-2.pdf", BytesIO(b"synthetic certificate"))
    started = owner[1].post(API + f"/documents/{filed.id}/process",
                            json={"base_revision": revision(owner, "document", filed.id), "idempotency_key": str(uuid4())})
    assert started.status_code == 200, started.text
    assert filed.id in open_ids()
    assert owner[1].get(API + "/summary").json()["counts"]["document"] == 4
