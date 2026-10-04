"""A full native migration must leave a later native bootstrap usable."""

from importlib import import_module
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from backend.db.orm_models import Base


def test_actual_sqlite_upgrade_roundtrip_then_fresh_create_all_keeps_metadata_unique(tmp_path, monkeypatch):
    scheduler = import_module("backend.db.migrations.versions.f2a2b3c4d5e6_durable_scheduler")
    url = "sqlite:///" + (tmp_path / "migrated.sqlite").as_posix()
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    before = {name: sum(index.name == name for index in table.indexes)
              for name, table, _ in scheduler.INDICES}
    command.upgrade(config, "head")
    command.downgrade(config, "e2a2b3c4d5e6")
    command.upgrade(config, "head")
    assert {name: sum(index.name == name for index in table.indexes)
            for name, table, _ in scheduler.INDICES} == before
    migrated = create_engine(url)
    fresh = create_engine("sqlite:///" + (tmp_path / "fresh.sqlite").as_posix())
    try:
        with migrated.connect() as db:
            for name, table, columns in scheduler.INDICES:
                definitions = [index for index in inspect(db).get_indexes(table.name) if index["name"] == name]
                assert len(definitions) == 1 and definitions[0]["column_names"] == list(columns)
        # This actual DDL failed with DuplicateTable after the previous f2
        # implementation had attached two copies to the same ORM metadata.
        Base.metadata.create_all(fresh)
        assert set(inspect(fresh).get_table_names()) >= {table.name for _, table, _ in scheduler.INDICES}
    finally:
        migrated.dispose()
        fresh.dispose()
