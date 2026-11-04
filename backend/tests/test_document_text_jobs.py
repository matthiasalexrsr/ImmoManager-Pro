"""A stopped index job commits its file cursor and resumes with another worker."""
from io import BytesIO
from uuid import uuid4

from test_durable_jobs import backend  # noqa: F401

from backend.models import DocumentCreate, PortfolioCreate, PropertyCreate
from backend.services import document_text, file_storage
from backend.services.jobs.core import JobRunner
from backend.services.jobs.document_text_index import make_handler


def test_file_cursor_and_text_survive_worker_restart(backend, monkeypatch, tmp_path):  # noqa: F811
    storage = file_storage.LocalStorage(tmp_path / "uploads")
    monkeypatch.setattr(file_storage, "_storage", storage)
    content = "a" * (document_text.MAX_CHARACTERS + 50) + " Neustartfund"
    key = f"documents/{uuid4().hex}.txt"
    storage.save(key, BytesIO(content.encode()))
    target = backend.store()
    try:
        portfolio = target.create_portfolio(PortfolioCreate(name="Index Neustart"))
        prop = target.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
        document = target.create_document(DocumentCreate(title="Großes Dokument", property_id=prop.id, file_url="/uploads/" + key))
    finally:
        if backend.kind == "sql":
            target.db.close()
    run = backend.jobs.enqueue(document_text.KIND, "file-restart", {})
    first = JobRunner(backend.jobs, {document_text.KIND: make_handler()}, owner="first-worker").run_one(max_chunks=1)
    assert first is not None
    assert first.id == run.id and first.status == "running"
    target = backend.store()
    try:
        part = document_text.get(target, document.id)
        assert part is not None
        assert not part.complete and part.cursor["offset"] == document_text.MAX_CHARACTERS
    finally:
        if backend.kind == "sql":
            target.db.close()
    backend.clock.advance(seconds=backend.jobs.lease_seconds + 1)
    resumed = JobRunner(backend.jobs, {document_text.KIND: make_handler()}, owner="replacement-worker").run_one()
    assert resumed is not None and resumed.progress is not None
    assert resumed.id == run.id and resumed.status == "succeeded" and resumed.attempts == 2
    assert resumed.progress["documents"] == 1
    target = backend.store()
    try:
        row = document_text.get(target, document.id)
        assert row is not None
        assert row.complete and row.text == content
        assert document_text.search(target, "Neustartfund")["total"] == 1
    finally:
        if backend.kind == "sql":
            target.db.close()
