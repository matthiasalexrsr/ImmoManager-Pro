"""Reserved k2 native DDL, stable metadata and real latest/keyset access plans."""

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from backend.db.orm_models import Base, StandaloneMeterReadingORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.tests.measurement_history_postgres_support import migrated_postgres
from backend.tests.test_meter_inventory import meters, readings

INDEX = "ix_meter_readings_latest"


@pytest.fixture(params=["sqlite", "postgres"])
def native(request, monkeypatch, tmp_path):
    if request.param == "postgres":
        with migrated_postgres(monkeypatch) as pair:
            yield pair
        return
    url = "sqlite:///" + (tmp_path / "meter-index.sqlite").as_posix()
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    engine = create_engine(url, hide_parameters=True)
    try:
        command.upgrade(config, "head")
        yield engine, config
    finally:
        engine.dispose()


def originals(engine):
    with engine.connect() as connection:
        return list(connection.execute(text("SELECT id,meter_id,reading_date,value,notes FROM standalone_meter_readings ORDER BY id")))


def test_k2_reupgrade_preserves_originals_and_does_not_register_global_indices(native):
    engine, config = native
    before = {(table.name, index.name) for table in Base.metadata.tables.values() for index in table.indexes}
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        meters(store, 1)
        readings(store, 3)
    snapshot = originals(engine)
    for _ in range(2):
        command.downgrade(config, "j2a2b3c4d5e6")
        with engine.connect() as connection:
            assert INDEX not in {index["name"] for index in inspect(connection).get_indexes("standalone_meter_readings")}
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "k2a2b3c4d5e6"
            assert INDEX in {index["name"] for index in inspect(connection).get_indexes("standalone_meter_readings")}
        assert originals(engine) == snapshot
        assert {(table.name, index.name) for table in Base.metadata.tables.values() for index in table.indexes} == before
        assert not any(index.name == INDEX for index in StandaloneMeterReadingORM.__table__.indexes)


def test_native_latest_and_history_keysets_use_actual_k2_index(native):
    engine, _config = native
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        meters(store, 1)
        readings(store, 10003)
    collation = '"BINARY"' if engine.dialect.name == "sqlite" else '"C"'
    base = f"SELECT id FROM standalone_meter_readings WHERE meter_id=:meter ORDER BY reading_date DESC,id COLLATE {collation} DESC LIMIT 26"
    later = f"SELECT id FROM standalone_meter_readings WHERE meter_id=:meter AND reading_date < '2013-01-01' ORDER BY reading_date DESC,id COLLATE {collation} DESC LIMIT 26"
    with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            entries = list(connection.exec_driver_sql(f'PRAGMA index_xinfo("{INDEX}")'))
            assert [(row[2], row[3], row[4]) for row in entries if row[5]] == [
                ("meter_id", 0, "BINARY"), ("reading_date", 1, "BINARY"), ("id", 1, "BINARY")]
            for query in (base, later):
                plan = " ".join(str(row[-1]) for row in connection.execute(text("EXPLAIN QUERY PLAN " + query), {"meter": "meter-000000"}))
                assert INDEX in plan and "SEARCH" in plan.upper()
                assert "TEMP B-TREE" not in plan.upper()
        else:
            connection.execute(text("ANALYZE standalone_meter_readings"))
            for query in (base, later):
                plan = connection.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query), {"meter": "meter-000000"}).scalar_one()
                assert INDEX in json.dumps(plan)
                assert '"Actual Rows": 26' in json.dumps(plan)
