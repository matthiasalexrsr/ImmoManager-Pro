"""Worker failure stays visible without endlessly rescheduling the text index."""
from io import BytesIO
from uuid import uuid4

import pytest
from test_durable_jobs import Backend

from backend.models import DocumentCreate, PortfolioCreate, PropertyCreate
from backend.services import document_text, file_storage
from backend.services.document_text_reader import ExtractionPart
from backend.services.jobs.core import JobRunner
from backend.services.jobs.document_text_index import make_handler


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_failed_worker_is_a_terminal_visible_index_warning_until_explicit_retry(kind, monkeypatch, tmp_path):
    backend = Backend(kind, tmp_path)
    storage = file_storage.LocalStorage(tmp_path / "uploads")
    monkeypatch.setattr(file_storage, "_storage", storage)
    content = b"Nach Wiederholung vollstaendig lesbar"
    key = f"documents/{uuid4().hex}.txt"
    storage.save(key, BytesIO(content))
    target = backend.store()
    try:
        portfolio = target.create_portfolio(PortfolioCreate(name="KI Textfehler"))
        prop = target.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
        document = target.create_document(DocumentCreate(title="Lesefehler", property_id=prop.id, file_url="/uploads/" + key))
    finally:
        if kind == "sql":
            target.db.close()
    try:
        with monkeypatch.context() as failure:
            failure.setattr(document_text, "extract_part", lambda *_args, **_kwargs:
                ExtractionPart(complete=True, warning="Synthetischer Workerabbruch", failed=True))
            queued = backend.jobs.enqueue(document_text.KIND, "worker-failed", {})
            finished = JobRunner(backend.jobs, {document_text.KIND: make_handler()}, owner="index-worker").run_one(max_chunks=3)
            assert finished is not None and finished.id == queued.id and finished.status == "succeeded"
            assert finished.progress is not None
            assert finished.progress["documents"] == 1
            target = backend.store()
            try:
                row = document_text.get(target, document.id)
                assert row is not None and row.complete and row.warning == "Synthetischer Workerabbruch" and not row.text
                status = document_text.status(target)
                assert status["partial"] == status["limited"] == 1 and status["in_progress"] == 0
                assert document_text.pending(target, "", 10) == []
                with pytest.raises(ValueError, match="unvollst"):
                    document_text.extract(content, "test.txt")
            finally:
                if kind == "sql":
                    target.db.close()
        queued = backend.jobs.enqueue(document_text.KIND, "explicit-retry", {"retry_limited": True})
        finished = JobRunner(backend.jobs, {document_text.KIND: make_handler()}, owner="retry-worker").run_one(max_chunks=3)
        assert finished is not None and finished.id == queued.id and finished.status == "succeeded"
        target = backend.store()
        try:
            row = document_text.get(target, document.id)
            assert row is not None and row.complete and row.warning is None and row.text == content.decode()
            assert document_text.status(target)["partial"] == 0
        finally:
            if kind == "sql":
                target.db.close()
    finally:
        if kind == "sql":
            backend.engine.dispose()
