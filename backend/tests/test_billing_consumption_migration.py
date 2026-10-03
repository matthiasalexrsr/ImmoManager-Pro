"""Actual historical Alembic upgrade/downgrade, preserving rows and triggers."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, inspect, text

from backend.models import AllocationKey, Meter, Portfolio, Property, Unit

ROOT = Path(__file__).resolve().parents[2]
HEAD = "e2a2b3c4d5e6"
PARENT = "d2a2b3c4d5e6"


@pytest.fixture
def migrated(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "own-consumption-migration.sqlite").as_posix()
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/db/migrations"))
    command.upgrade(config, PARENT)
    engine = create_engine(url)
    with engine.begin() as connection:
        rows = (
            ("portfolios", Portfolio(id="p", name="Synthetic")),
            ("properties", Property(id="h", portfolio_id="p", name="Synthetic", property_type="residential")),
            ("units", Unit(id="u", property_id="h", label="Synthetic", unit_type="Wohnung", status="occupied")),
            ("allocation_keys", AllocationKey(id="k", property_id="h", name="Historischer Verbrauch", key_type="consumption")),
            ("meters", Meter(id="m", unit_id="u", meter_type="cold_water", is_active=False)),
        )
        for name, row in rows:
            legacy = Table(name, MetaData(), autoload_with=connection)
            connection.execute(legacy.insert().values(**{key: value for key, value in row.model_dump().items() if key in legacy.c}))
        connection.exec_driver_sql("CREATE TABLE consumption_sentinel (key_id TEXT, old_name TEXT)")
        connection.exec_driver_sql("CREATE TRIGGER keep_key_update AFTER UPDATE ON allocation_keys BEGIN INSERT INTO consumption_sentinel VALUES(OLD.id,OLD.name); END")
        connection.exec_driver_sql("CREATE INDEX keep_meter_index ON meters(serial_number DESC)")
    try:
        yield config, engine
    finally:
        engine.dispose()


def test_upgrade_preserves_legacy_values_custom_guards_and_parent_relationships(migrated):
    config, engine = migrated
    with engine.connect() as connection:
        before_key = dict(connection.execute(text("SELECT * FROM allocation_keys WHERE id='k'")).mappings().one())
        before_meter = dict(connection.execute(text("SELECT * FROM meters WHERE id='m'")).mappings().one())
        before_triggers = connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").all()
        foreign_keys = inspect(connection).get_foreign_keys("meters")
    command.upgrade(config, HEAD)
    with engine.connect() as connection:
        key = dict(connection.execute(text("SELECT * FROM allocation_keys WHERE id='k'")).mappings().one())
        meter = dict(connection.execute(text("SELECT * FROM meters WHERE id='m'")).mappings().one())
        assert key.pop("consumption_medium") is None
        assert key.pop("consumption_unit") is None
        assert meter.pop("measurement_unit") is None
        assert key == before_key and meter == before_meter
        assert connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").all() == before_triggers
        assert inspect(connection).get_foreign_keys("meters") == foreign_keys
        assert "keep_meter_index" in {row["name"] for row in inspect(connection).get_indexes("meters")}
        assert connection.execute(text("SELECT count(*) FROM consumption_sentinel")).scalar_one() == 0
    command.downgrade(config, PARENT)
    command.upgrade(config, HEAD)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT name FROM allocation_keys WHERE id='k'")).scalar_one() == before_key["name"]


@pytest.mark.parametrize("statement", [
    "UPDATE allocation_keys SET consumption_medium='cold_water' WHERE id='k'",
    "UPDATE allocation_keys SET consumption_unit='m³' WHERE id='k'",
    "UPDATE meters SET measurement_unit='m³' WHERE id='m'",
])
def test_downgrade_refuses_to_erase_any_populated_binding_before_ddl(migrated, statement):
    config, engine = migrated
    command.upgrade(config, HEAD)
    with engine.begin() as connection:
        connection.execute(text(statement))
    with engine.connect() as connection:
        before = connection.exec_driver_sql("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").all()
        key = connection.execute(text("SELECT * FROM allocation_keys WHERE id='k'")).one()
        meter = connection.execute(text("SELECT * FROM meters WHERE id='m'")).one()
    with pytest.raises(RuntimeError, match="erase confirmed consumption bindings"):
        command.downgrade(config, PARENT)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").all() == before
        assert connection.execute(text("SELECT * FROM allocation_keys WHERE id='k'")).one() == key
        assert connection.execute(text("SELECT * FROM meters WHERE id='m'")).one() == meter
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == HEAD
