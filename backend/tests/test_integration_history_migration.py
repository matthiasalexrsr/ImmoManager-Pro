"""Real complete Alembic chain on fresh SQLite and random PostgreSQL schemas."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import sessionmaker

from backend.db.integration_history_models import TABLES
from backend.db.integration_history_schema import ensure_history_schema
from backend.services.iban_encryption import IBANKeyring, generate_key
from backend.services.integrations.history_store import CLEAR, SQLIntegrationHistoryStore
from backend.tests.test_integration_history_core import ACTOR, completed, journal_engine


@pytest.mark.parametrize("dialect", ["sqlite", pytest.param("pg", id="postgres")])
def test_actual_full_chain_empty_down_up_and_retained_refusal(tmp_path, monkeypatch, dialect):
    with journal_engine(tmp_path, dialect, create_family=False) as engine:
        url = engine.url
        if dialect == "pg":
            with engine.connect() as db:
                url = url.update_query_dict({"options": "-csearch_path=" + db.scalar(text("SELECT current_schema()"))})
        monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
        configuration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        command.upgrade(configuration, "d2a2b3c4d5e6")
        with engine.connect() as db:
            assert ensure_history_schema(db)
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "d2a2b3c4d5e6"
        command.downgrade(configuration, "c2a2b3c4d5e6")
        with engine.connect() as db:
            assert ensure_history_schema(db) is False
        command.upgrade(configuration, "d2a2b3c4d5e6")
        ring = IBANKeyring("synthetic", {"synthetic": generate_key()})
        store = SQLIntegrationHistoryStore(sessionmaker(engine), keyring=ring)
        ticket = completed(store)
        before = store.detail("contract-wizard", ticket.run_id, ACTOR)
        with engine.connect() as db:
            tables = set(inspect(db).get_table_names())
            constraints = {name: inspect(db).get_foreign_keys(name) for name in TABLES}
        with pytest.raises(RuntimeError, match="erase retained integration observations"):
            command.downgrade(configuration, "c2a2b3c4d5e6")
        assert store.detail("contract-wizard", ticket.run_id, ACTOR) == before
        with engine.connect() as db:
            assert set(inspect(db).get_table_names()) == tables
            assert {name: inspect(db).get_foreign_keys(name) for name in TABLES} == constraints
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "d2a2b3c4d5e6"
        assert store.clear("contract-wizard", ACTOR)["cleared"] == 1
        with pytest.raises(RuntimeError, match="erase retained integration observations"):
            command.downgrade(configuration, "c2a2b3c4d5e6")
        with engine.connect() as db:
            assert db.execute(select(CLEAR)).first() is not None
