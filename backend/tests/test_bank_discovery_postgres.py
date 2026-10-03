"""Real dedicated PostgreSQL only, never a SQLite substitute."""

import hashlib

from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.bank_discovery import prepare_discovery
from backend.tests.test_bank_discovery import records
from backend.tests.test_bank_imports import account, confirm, stage
from backend.tests.test_private_server_concurrency import postgres_database  # noqa: F401


def test_pg_original_discovery_is_exact_after_independent_session_and_confirmation(postgres_database):  # noqa: F811
    engine, factory, _, _ = postgres_database
    from backend.db.bank_import_schema import ensure_bank_import_schema
    with engine.begin() as connection:
        ensure_bank_import_schema(connection)
    text = 'date;amount;text;late\n2026-01-01;1;Ä €;raw provider data\n'
    with factory() as db:
        store = SQLAlchemyStore(db)
        selected = account(store)
        job = stage(store, selected.id, text)
        assert confirm(store, job)['published_count'] == 1
    with factory() as db:
        plan = prepare_discovery(SQLAlchemyStore(db), job['id'])
        try:
            rows = records(plan)
            assert rows[0]['business_state'] == 'committed'
            assert rows[3]['cells'][-1]['value'] == 'raw provider data'
            assert rows[-1]['source_sha256'] == hashlib.sha256(text.encode()).hexdigest()
            assert rows[-1]['parser_complete'] and rows[-1]['original_complete']
        finally:
            plan.close()
