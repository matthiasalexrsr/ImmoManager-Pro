"""New integration boundaries on an owned native PostgreSQL database.

The imported fixture creates/migrates a fresh database and removes only that
database. These are independent sessions and never substitute SQLite for PG.
"""

import base64
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from archive_helpers import lease_with_document
from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker
from test_document_versions_postgres import postgres  # noqa: F401

from backend import auth
from backend.document_work_models import OpenSession
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import document_work as documents
from backend.services import file_storage
from backend.tests.test_document_work import command, docx_bytes


def test_registration_quota_is_global_under_real_postgres_connection_contention(postgres, monkeypatch):  # noqa: F811
    engine, _ = postgres
    monkeypatch.setattr(auth, '_auth_session_factory', sessionmaker(engine))
    start = Barrier(8)

    def attempt(_):
        start.wait(timeout=10)
        return auth.reserve_registration_attempt('192.0.2.67')

    with ThreadPoolExecutor(max_workers=8) as workers:
        outcomes = list(workers.map(attempt, range(8)))
    assert outcomes.count(False) == 5 and outcomes.count(True) == 3
    assert auth.reserve_registration_attempt('192.0.2.67') is True
    assert auth.reserve_registration_attempt('192.0.2.68') is False


def test_conflicting_docx_publications_keep_original_and_losing_private_recovery(postgres, tmp_path, monkeypatch):  # noqa: F811
    engine, _ = postgres
    storage = file_storage.LocalStorage(tmp_path / 'uploads')
    monkeypatch.setattr(file_storage, '_storage', storage)
    owner = auth.register_user('pg-document', 'pg@example.test', 'PG Prüfung', 'Synthetic123!', 'eigentuemer')
    original = docx_bytes('Original bleibt erhalten', 10)
    storage.save('documents/source.docx', io.BytesIO(original))
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        lease = lease_with_document(store, file_url='/uploads/documents/source.docx')
        identifier = lease['document'].id
        initial = documents.source(store, identifier, owner.id)
        documents.archive_upload(store, identifier, command(initial), owner.id)
        source = documents.source(store, identifier, owner.id)
        sessions = [documents.open_session(store, identifier, command(source, OpenSession, mode='docx'), owner.id)
                    for _ in range(2)]
        contents = [docx_bytes('Fassung A', 11), docx_bytes('Fassung B – nicht verlieren', 12)]
        for session, content in zip(sessions, contents, strict=True):
            documents.save_docx(store, identifier, session['session_id'], command(source), content, 1, owner.id, autosave=True)

    start = Barrier(2)

    def publish(index):
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            start.wait(timeout=10)
            try:
                result = documents.save_docx(store, identifier, sessions[index]['session_id'],
                                             command(source), contents[index], 2, owner.id)
                return index, result
            except HTTPException as error:
                return index, error.status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(publish, range(2)))
    winners = [(index, result) for index, result in outcomes if isinstance(result, dict)]
    losers = [(index, result) for index, result in outcomes if isinstance(result, int)]
    assert len(winners) == 1 and len(losers) == 1 and losers[0][1] == 409
    winner, result = winners[0]
    loser = losers[0][0]
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        recovered = documents.read_session(store, identifier, sessions[loser]['session_id'], owner.id)
        assert base64.b64decode(recovered['draft_base64']) == contents[loser]
        assert documents.download(store, identifier, source['version']['id'], owner.id)[0] == original
        assert documents.download(store, identifier, result['version_id'], owner.id)[0] == contents[winner]
