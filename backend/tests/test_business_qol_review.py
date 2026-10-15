"""Independent release regressions for adoption and concurrent office workflows."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from importlib import import_module
from io import BytesIO
from threading import Event, Lock
from typing import cast
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect, select

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import DocumentCreate, PortfolioCreate, PropertyCreate
from backend.services import business_documents as documents
from backend.services import business_qol as office
from backend.services.file_storage import LocalStorage
from backend.services.workspace_contexts import resolve_context

API = "/api/v1/work-center"


@pytest.fixture(autouse=True)
def isolated_records():
    auth.clear_users()
    store.clear_all()
    yield
    auth.clear_users()
    store.clear_all()


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    user = auth.register_user("review-office", "review-office@example.test", "Review", "Secret123", "eigentuemer")
    client = TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"}, raise_server_exceptions=False)
    portfolio = store.create_portfolio(PortfolioCreate(name="Review"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Reviewhaus", property_type="residential"))
    files = LocalStorage(tmp_path / "uploads")
    files.save("review.pdf", BytesIO(b"synthetic review document"))
    monkeypatch.setattr(documents, "get_file_storage", lambda: files)
    document = store.create_document(DocumentCreate(property_id=prop.id, title="Reviewdatei", file_url="/uploads/review.pdf"))
    return user, client, document


def test_expired_same_key_processing_attempt_cannot_publish_into_new_lease(fixture, monkeypatch):
    user, client, document = fixture
    clock = {"now": office.timestamp()}
    monkeypatch.setattr(office, "timestamp", lambda: clock["now"])
    first_entered, second_entered, finish_first, finish_second = Event(), Event(), Event(), Event()
    counter, counter_lock = {"value": 0}, Lock()

    def analyze(*args, **kwargs):
        with counter_lock:
            counter["value"] += 1
            ordinal = counter["value"]
        if ordinal == 1:
            first_entered.set()
            assert finish_first.wait(15)
            return {"summary": "Veralteter abgelaufener Versuch"}
        second_entered.set()
        assert finish_second.wait(15)
        return {"summary": "Aktueller Versuch"}

    monkeypatch.setattr(documents, "analyze_bytes", analyze)
    body = {"base_revision": resolve_context(store, "document", document.id, user.id)["revision"], "idempotency_key": str(uuid4())}
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(client.post, f"{API}/documents/{document.id}/process", json=body)
        try:
            assert first_entered.wait(15)
            clock["now"] += timedelta(minutes=11)
            second = executor.submit(client.post, f"{API}/documents/{document.id}/process", json=body)
            assert second_entered.wait(15)
            finish_first.set()
            first_response = first.result(timeout=15)
            finish_second.set()
            second_response = second.result(timeout=15)
        finally:
            finish_first.set()
            finish_second.set()
    assert first_response.status_code == 409, first_response.text
    assert second_response.status_code == 200, second_response.text
    assert second_response.json()["intake"]["result"]["summary"] == "Aktueller Versuch"
    assert client.get(f"{API}/documents/{document.id}").json()["intake"]["result"]["summary"] == "Aktueller Versuch"


@pytest.mark.parametrize("amount", ["not-a-number", "Infinity", "NaN"])
def test_invalid_duplicate_invoice_amount_is_a_user_validation_error(fixture, amount):
    _, client, _ = fixture
    result = client.post(API + "/duplicates/check", json={"kind": "invoice", "candidate": {
        "supplier": "Review GmbH", "invoice_date": "2026-10-15", "gross_amount": amount}})
    assert result.status_code == 422, result.text


@pytest.mark.parametrize("changes", [{"title": None}, {"document_type": {"invalid": "object"}}])
def test_invalid_manual_document_review_is_rejected_without_side_effects(fixture, monkeypatch, changes):
    user, client, document = fixture
    monkeypatch.setattr(documents, "analyze_bytes", lambda *args, **kwargs: {"summary": "Reviewvorschlag"})
    processed = client.post(f"{API}/documents/{document.id}/process", json={
        "base_revision": resolve_context(store, "document", document.id, user.id)["revision"], "idempotency_key": str(uuid4())})
    assert processed.status_code == 200, processed.text
    intake = processed.json()["intake"]
    result = client.post(f"{API}/documents/{document.id}/review", json={"base_revision": intake["revision"],
        "document_revision": intake["document_revision"], "changes": changes, "idempotency_key": str(uuid4())})
    assert result.status_code == 422, result.text
    current = client.get(f"{API}/documents/{document.id}").json()
    assert current["document"]["title"] == "Reviewdatei" and current["intake"]["status"] == "review"


def test_business_migration_adopts_partial_schema_preserving_data_and_indexes(tmp_path):
    from backend.db.business_qol_models import ConversationNoteORM

    migration = import_module("backend.db.migrations.versions.b82d5fa03147_business_qol")
    engine = create_engine(f"sqlite:///{tmp_path / 'adopted-business.db'}")
    metadata = MetaData()
    for name in ("properties", "tasks", "documents"):
        Table(name, metadata, Column("id", String(), primary_key=True))
    notes = cast(Table, ConversationNoteORM.__table__).to_metadata(metadata)
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(notes.insert().values(id="note", entity_type="property", entity_id="property",
            body="Dauerhafte Gesprächsnotiz", conversation_kind="phone", occurred_at=datetime(2026, 10, 15),
            actor_id="owner", created_at=datetime(2026, 10, 15), updated_at=datetime(2026, 10, 15)))
        # Simulate a partially adopted installation with one absent index too.
        connection.exec_driver_sql("DROP INDEX ix_business_notes_context")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        assert connection.execute(select(notes.c.body)).scalar_one() == "Dauerhafte Gesprächsnotiz"
        expected = {"business_conversation_notes": {"ix_business_notes_context"},
                    "business_qol_commands": {"ix_business_commands_actor"},
                    "business_document_intake": {"ix_business_intake_hash", "ix_business_intake_status"},
                    "business_duplicate_exceptions": {"ix_business_duplicate_pair"}}
        for table, indexes in expected.items():
            assert indexes.issubset({index["name"] for index in inspect(connection).get_indexes(table)})
        assert inspect(connection).get_unique_constraints("business_document_intake")[0]["column_names"] == ["document_id"]
    engine.dispose()


def test_maintenance_status_history_and_field_timeline_stay_distinct(fixture):
    user, client, document = fixture
    created = client.post("/api/v1/maintenance", json={"property_id": document.property_id, "title": "Dach prüfen"})
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    base = f"/api/v1/maintenance/{case_id}"
    changed = client.patch(base, json={"status": "in_progress", "title": "Dach reparieren"})
    assert changed.status_code == 200, changed.text
    transitioned = client.post(base + "/transition", json={"status": "cancelled", "reason": "Auftrag entfällt"})
    assert transitioned.status_code == 200, transitioned.text
    # Repeating an unchanged field must not add another timeline event.
    assert client.patch(base, json={"title": "Dach reparieren"}).status_code == 200

    project = client.get(base + "/project")
    assert project.status_code == 200, project.text
    history = project.json()["history"]
    assert [(row["field_name"], row["old_value"], row["new_value"], row["reason"]) for row in history] == [
        ("status", "in_progress", "cancelled", "Auftrag entfällt"),
        ("status", "open", "in_progress", "Bearbeitet"),
        ("status", None, "open", "Angelegt")]
    assert all(row["changed_by"] == user.id and row["changed_by_name"] == "Review" for row in history)

    timeline = client.get(API + "/timeline", params={"entity_type": "maintenance", "entity_id": case_id})
    assert timeline.status_code == 200, timeline.text
    changes = [row for row in timeline.json()["items"] if row["kind"] == "change"]
    assert sorted(row["title"] for row in changes) == ["Änderung: status"] * 3 + ["Änderung: title"]
    assert all(row["actor"] == "Review" for row in changes)
    assert next(row for row in changes if row["title"] == "Änderung: title")["body"] == "Feld geändert"
    fields = [row for row in store.list_change_history()
              if row.entity_type == "maintenance" and row.entity_id == case_id and row.field_name == "title"]
    assert [(row.old_value, row.new_value, row.changed_by) for row in fields] == [
        ("Dach prüfen", "Dach reparieren", user.id)]


def test_maintenance_failed_unit_rolls_back_status_and_field_history(fixture, monkeypatch):
    from backend.services.maintenance_rows import Rows

    _, client, document = fixture
    created = client.post("/api/v1/maintenance", json={"property_id": document.property_id, "title": "Dach prüfen"})
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    base = f"/api/v1/maintenance/{case_id}"
    original_update = Rows.update

    def fail_after_update(self, table, key, **changes):
        result = original_update(self, table, key, **changes)
        if table == "maintenance_cases":
            raise RuntimeError("Synthetic failure after field and status history were staged")
        return result

    monkeypatch.setattr(Rows, "update", fail_after_update)
    failed = client.patch(base, json={"status": "in_progress", "title": "Dach reparieren"})
    assert failed.status_code == 500, failed.text
    project = client.get(base + "/project")
    assert project.status_code == 200, project.text
    assert (project.json()["case"]["status"], project.json()["case"]["title"]) == ("open", "Dach prüfen")
    assert [(row["old_value"], row["new_value"]) for row in project.json()["history"]] == [(None, "open")]
    timeline = client.get(API + "/timeline", params={"entity_type": "maintenance", "entity_id": case_id})
    assert timeline.status_code == 200, timeline.text
    assert [row["title"] for row in timeline.json()["items"] if row["kind"] == "change"] == ["Änderung: status"]
