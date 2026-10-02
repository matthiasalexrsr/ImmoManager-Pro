"""Real Alembic chain with conservative data-bearing downgrade rejection."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_full_chain_empty_down_up_and_saved_draft_guard(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    database = tmp_path / "isolated-draft-migration.sqlite"
    url = "sqlite:///" + database.as_posix()
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend/db/migrations"))
    command.upgrade(config, "head")
    engine = create_engine(url, hide_parameters=True)
    assert "form_drafts" in inspect(engine).get_table_names()
    command.downgrade(config, "w1a2b3c4d5e6")
    assert "form_drafts" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO form_drafts (id,user_id,collection,form_key,scope_hash,revision,payload,updated_at,expires_at) VALUES (:id,'synthetic-user','properties','crud',:scope,'synthetic-revision','retained original evidence','2026-01-01','2026-01-08')"), {"id": "0" * 64, "scope": "1" * 64})
    before = inspect(engine).get_table_names()
    with pytest.raises(RuntimeError, match="Formularentwürfe"):
        command.downgrade(config, "w1a2b3c4d5e6")
    assert inspect(engine).get_table_names() == before
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT payload FROM form_drafts")) == "retained original evidence"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "x1a2b3c4d5e6"
    engine.dispose()


def test_head_adopts_additive_runtime_draft_table_without_recreating_or_losing_rows(tmp_path, monkeypatch):
    from backend.db.form_draft_models import ensure_form_draft_schema
    root = Path(__file__).resolve().parents[2]
    url = "sqlite:///" + (tmp_path / "runtime-precreated.sqlite").as_posix()
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend/db/migrations"))
    command.upgrade(config, "w1a2b3c4d5e6")
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.begin() as connection:
            ensure_form_draft_schema(connection)
            connection.exec_driver_sql("INSERT INTO form_drafts(id,user_id,collection,form_key,scope_hash,revision,payload,updated_at,expires_at) "
                "VALUES ('synthetic-precreated', 'synthetic-user', 'properties', 'crud', 'synthetic-scope', 'synthetic-revision', 'retained opaque cipher', '2026-01-01', '2099-01-01')")
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT payload FROM form_drafts")) == "retained opaque cipher"
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "x1a2b3c4d5e6"
    finally:
        engine.dispose()
