"""Actual historical SQLite/PostgreSQL migrations and immutable DDL guards."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from backend.db.measurement_history_models import MEASUREMENT_MODELS, MEASUREMENT_TABLES
from backend.db.measurement_history_schema import validate_measurement_schema
from backend.tests.measurement_history_postgres_support import migrated_postgres


@pytest.fixture(params=["sqlite", "postgres"])
def native(request, monkeypatch, tmp_path):
    if request.param == "postgres":
        with migrated_postgres(monkeypatch) as pair:
            yield pair
        return
    url = "sqlite:///" + (tmp_path / "history-migration.sqlite").as_posix()
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    engine = create_engine(url)
    try:
        command.upgrade(config, "head")
        yield engine, config
    finally:
        engine.dispose()


def test_full_chain_downgrade_reupgrade_columns_indices_and_no_guessed_history(native):
    engine, config = native
    with engine.connect() as connection:
        assert validate_measurement_schema(connection)
        if engine.dialect.name == "sqlite":
            assert validate_measurement_schema(connection.connection.driver_connection)
        for model in MEASUREMENT_MODELS:
            assert {column.name for column in model.__table__.columns} == {row["name"] for row in inspect(connection).get_columns(model.__tablename__)}
            assert connection.execute(text(f"SELECT count(*) FROM {model.__tablename__}")).scalar_one() == 0
        assert "ix_measurement_fact_period" in {index["name"] for index in inspect(connection).get_indexes("measurement_facts")}
    command.downgrade(config, "f2a2b3c4d5e6")
    with engine.connect() as connection:
        assert not set(MEASUREMENT_TABLES).intersection(inspect(connection).get_table_names())
    command.upgrade(config, "g2a2b3c4d5e6")
    with engine.connect() as connection:
        assert validate_measurement_schema(connection)


def test_downgrade_refuses_retained_sources_before_any_schema_change(native):
    engine, config = native
    # Exercise g2's own retained-source downgrade boundary independently of
    # subsequent additive revisions (h2 and later).
    command.downgrade(config, "g2a2b3c4d5e6")
    from sqlalchemy.orm import Session

    from backend.models import PortfolioCreate, PropertyCreate, UnitCreate
    from backend.repositories.sql_store import SQLAlchemyStore
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        portfolio = store.create_portfolio(PortfolioCreate(name="Synthetic retained"))
        prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Synthetic", property_type="residential"))
        unit = store.create_unit(UnitCreate(property_id=prop.id, label="Synthetic", unit_type="Wohnung"))
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO measurement_ledgers(id, portfolio_id, property_id, revision) VALUES(:id,:portfolio,:property,0)"),
            {"id": unit.id, "portfolio": portfolio.id, "property": prop.id})
    with pytest.raises(RuntimeError, match="erase historical"):
        command.downgrade(config, "f2a2b3c4d5e6")
    with engine.connect() as connection:
        assert validate_measurement_schema(connection)
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "g2a2b3c4d5e6"


def test_native_original_update_delete_guards_and_restrict_fks(native):
    engine, _config = native
    if engine.dialect.name == "sqlite":
        with engine.connect() as connection:
            installed = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))}
        assert {f"preserve_{name}_{op}" for name in MEASUREMENT_TABLES[1:] for op in ("update", "delete")} <= installed
    else:
        with engine.connect() as connection:
            installed = {row[0] for row in connection.execute(text("SELECT trigger_name FROM information_schema.triggers WHERE trigger_schema=current_schema()"))}
        assert {f"preserve_{name}" for name in MEASUREMENT_TABLES[1:]} <= installed
    # A trigger's presence is checked here; actual populated row mutation refusal
    # is exercised through the composed source fixture in the integrity module.
    with engine.connect() as connection:
        for model in MEASUREMENT_MODELS:
            assert all(fk.get("options", {}).get("ondelete", "").upper() == "RESTRICT"
                for fk in inspect(connection).get_foreign_keys(model.__tablename__))
