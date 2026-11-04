"""Source revisions stay exact across database clocks, imports and checkpoints."""

from datetime import datetime, timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from test_document_text import _upload, case  # noqa: F401
from test_document_text_progress import commit_checkpoint

from backend.dependencies import store
from backend.models import DocumentCreate
from backend.services import document_text
from backend.services.file_storage import get_file_storage


def set_revision(identifier, revision):
    if hasattr(store, "db"):
        from sqlalchemy import update

        from backend.db.orm_models import DocumentORM

        store.db.execute(update(DocumentORM).where(DocumentORM.id == identifier).values(updated_at=revision))
        store.db.commit()
    else:
        store.documents[identifier] = store.get_document(identifier).model_copy(update={"updated_at": revision})


def finish_bounded(identifier, maximum=4):
    for _ in range(maximum):
        document_text.index_pending(store)
        commit_checkpoint()
        row = document_text.get(store, identifier)
        assert row is not None
        if row.complete:
            return row
    pytest.fail("The same source must finish within its known number of bounded steps")


def test_future_source_revision_survives_committed_continuation(case, monkeypatch):  # noqa: F811
    content = "Anfang mit Suchwort Endefund"
    document = _upload(case, "future.txt", content.encode(), "Import mit späterer Quellzeit")
    revision = datetime(2099, 1, 2, 3, 4, 5, 123456)
    set_revision(document["id"], revision)
    monkeypatch.setattr(document_text, "MAX_CHARACTERS", 16)
    assert document_text.index_pending(store) == (0, "")
    commit_checkpoint()
    first = document_text.get(store, document["id"])
    assert first is not None and not first.complete and first.cursor["offset"] == 16
    assert first.source_updated_at == revision and first.indexed_at < revision
    finished = finish_bounded(document["id"])
    assert finished.text == content and finished.source_updated_at == revision
    assert document_text.pending(store, "", 10) == []
    assert document_text.status(store)["in_progress"] == 0


def test_database_timezone_does_not_restart_the_same_document(case, monkeypatch):  # noqa: F811
    from sqlalchemy import text

    content = "Anfang mit Suchwort Endefund"
    key = f"documents/{uuid4().hex}-database-clock.txt"
    get_file_storage().save(key, BytesIO(content.encode()))
    postgres = hasattr(store, "db") and store.db.get_bind().dialect.name == "postgresql"
    if postgres:
        # This transaction belongs to the test. The setting expires at its
        # commit and never changes the server/other sessions' timezone.
        store.db.execute(text("SET LOCAL TIME ZONE 'Europe/Berlin'"))
    document = store.create_document(DocumentCreate(title="DB-Uhr", property_id=case["property"].id,
                                                    file_url="/uploads/" + key))
    if not postgres:
        set_revision(document.id, document_text.now() + timedelta(hours=1))
        document = store.get_document(document.id)
    revision = document_text._naive(document.updated_at)
    assert revision is not None and revision > document_text.now() + timedelta(minutes=50)
    monkeypatch.setattr(document_text, "MAX_CHARACTERS", 16)
    assert document_text.index_pending(store) == (0, "")
    commit_checkpoint()
    finished = finish_bounded(document.id)
    assert finished.text == content and finished.source_updated_at == document_text._naive(document.updated_at)
    assert document_text.pending(store, "", 10) == []


def test_changed_revision_during_parsing_restarts_even_when_the_new_stamp_is_older(case, monkeypatch):  # noqa: F811
    content = "Anfang mit Suchwort Endefund"
    document = _upload(case, "revision.txt", content.encode(), "Unveränderte Datei mit neuer Revision")
    revision = document_text._naive(store.get_document(document["id"]).updated_at)
    assert revision is not None
    changed_revision = revision - timedelta(microseconds=1)
    monkeypatch.setattr(document_text, "MAX_CHARACTERS", 16)
    original = document_text.extract_part
    cursors = []

    def change_after_read(content, name, cursor=None):
        cursors.append(dict(cursor or {}))
        part = original(content, name, cursor)
        if len(cursors) == 1:
            set_revision(document["id"], changed_revision)
        return part

    monkeypatch.setattr(document_text, "extract_part", change_after_read)
    document_text.index_pending(store)
    commit_checkpoint()
    first = document_text.get(store, document["id"])
    assert first is not None and first.source_updated_at == revision
    assert [row.id for row in document_text.pending(store, "", 10)] == [document["id"]]
    finished = finish_bounded(document["id"])
    assert cursors[:2] == [{}, {}] and cursors[2]["offset"] == 16
    assert finished.text == content and finished.source_updated_at == changed_revision
    assert document_text.pending(store, "", 10) == []


def test_legacy_index_without_a_revision_marker_is_rebuilt(case):  # noqa: F811
    document = _upload(case, "legacy.txt", b"Aktueller Text", "Alter abgeleiteter Index")
    document_text.save(store, document_text.TextRow(document["id"], "file:" + document["file_url"],
        "plain", "Alter Text", "alter text", 10, document_text.now(), complete=True))
    commit_checkpoint()
    assert [row.id for row in document_text.pending(store, "", 10)] == [document["id"]]
    row = finish_bounded(document["id"])
    assert row.text == "Aktueller Text" and row.source_updated_at is not None
    assert document_text.pending(store, "", 10) == []


@pytest.mark.parametrize("stamp", ["2040-01-02 03:04:05", "2040-01-02 03:04:05.1",
                                    "2040-01-02 03:04:05.123456", "2040-01-02 03:04:05.000001"])
def test_sqlite_revision_text_formats_preserve_exact_microseconds(case, stamp):  # noqa: F811
    if not hasattr(store, "db") or store.db.get_bind().dialect.name != "sqlite":
        pytest.skip("SQLite's stored text date/time spellings are tested in the SQLite matrix")
    from sqlalchemy import text

    document = _upload(case, "precision.txt", b"Praeziser Text", "Sekundenformat")
    store.db.execute(text("UPDATE documents SET updated_at=:stamp WHERE id=:id"), {"stamp": stamp, "id": document["id"]})
    store.db.commit()
    row = finish_bounded(document["id"])
    expected = datetime.fromisoformat(stamp)
    assert row.source_updated_at == expected and document_text.pending(store, "", 10) == []
    store.db.execute(text("UPDATE documents SET updated_at=:stamp WHERE id=:id"),
                     {"stamp": (expected + timedelta(microseconds=1)).isoformat(sep=" ", timespec="microseconds"),
                      "id": document["id"]})
    store.db.commit()
    assert [row.id for row in document_text.pending(store, "", 10)] == [document["id"]]
