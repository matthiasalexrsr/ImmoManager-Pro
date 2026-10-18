"""Additive, nondestructive migration of existing billing objection originals."""

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

import backend.models  # noqa: F401 (register the complete SQL schema)
from backend.db.orm_models import Base
from backend.db.schema_state import alembic_config, head_revision

PARENT = "f016a1b2c001"
HEAD = head_revision()


def test_prior_issued_objections_survive_upgrade_and_decision_keys_are_unique(tmp_path):
    url = "sqlite:///" + (tmp_path / "retained-period.sqlite").as_posix()
    cfg = alembic_config(url)
    command.upgrade(cfg, PARENT)
    eng = create_engine(url)
    try:
        with eng.begin() as db:
            db.exec_driver_sql(
                "INSERT INTO portfolios(id,name,currency,timezone,status,created_at,updated_at) "
                "VALUES ('pf','synthetic','EUR','Europe/Berlin','active','2025-01-01','2025-01-01')")
            db.exec_driver_sql(
                "INSERT INTO properties(id,portfolio_id,name,property_type,status,created_at,updated_at) "
                "VALUES ('p','pf','synthetic','residential','active','2025-01-01','2025-01-01')")
            db.exec_driver_sql(
                "INSERT INTO billing_periods(id,property_id,label,start_date,end_date,status,revision,created_at,updated_at) "
                "VALUES ('b','p','2025','2025-01-01','2025-12-31','disputed',1,'2025-01-01','2025-01-01')")
            for i in (1, 2):
                db.exec_driver_sql(
                    "INSERT INTO billing_objections(id,billing_period_id,received_on,reason,status,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (f"synthetic-{i}", "b", "2026-05-01", f"Unchanged tenant reason {i}",
                     "open", "2026-05-01", "2026-05-01"))
        command.upgrade(cfg, "head")
        assert head_revision() == HEAD
        with eng.connect() as db:
            names = {column["name"] for column in inspect(db).get_columns("billing_objections")}
            assert {"decision_revision", "decision_reason", "decision_key", "decision_actor_id",
                    "decision_source_sha256", "decided_at", "source_period_status"} <= names
            rows = db.execute(text(
                "SELECT id,reason,status,decision_revision,decision_key "
                "FROM billing_objections ORDER BY id")).all()
            assert rows == [
                ("synthetic-1", "Unchanged tenant reason 1", "open", 0, None),
                ("synthetic-2", "Unchanged tenant reason 2", "open", 0, None),
            ]
        # An old, undecided objection contains no evidence in the new fields.
        # Its original reason must also survive a safe round trip.
        command.downgrade(cfg, PARENT)
        with eng.connect() as db:
            assert db.execute(text(
                "SELECT id,reason,status FROM billing_objections ORDER BY id")).all() == [
                ("synthetic-1", "Unchanged tenant reason 1", "open"),
                ("synthetic-2", "Unchanged tenant reason 2", "open"),
            ]
        command.upgrade(cfg, "head")
        with eng.begin() as db:
            db.execute(text("UPDATE billing_objections SET decision_key='synthetic-key' WHERE id='synthetic-1'"))
        with pytest.raises(IntegrityError):
            with eng.begin() as db:
                db.execute(text("UPDATE billing_objections SET decision_key='synthetic-key' WHERE id='synthetic-2'"))
        with eng.connect() as db:
            assert db.scalar(text("SELECT decision_key FROM billing_objections WHERE id='synthetic-2'")) is None
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        with pytest.raises(RuntimeError, match="must not be discarded"):
            command.downgrade(cfg, PARENT)
        with eng.connect() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
    finally:
        eng.dispose()


def test_complete_unversioned_orm_decision_family_is_adopted_without_rewrite(tmp_path):
    url = "sqlite:///" + (tmp_path / "already-orm.sqlite").as_posix()
    engine = create_engine(url)
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as db:
            db.exec_driver_sql(
                "INSERT INTO billing_objections(id,billing_period_id,received_on,reason,status,"
                "decision_revision,decision_key,decision_reason,created_at,updated_at) "
                "VALUES ('already','legacy','2025-04-01','preserve','rejected',1,'test-original','confirmed',"
                "'2026-01-01','2026-01-01')")
        cfg = alembic_config(url)
        command.stamp(cfg, PARENT)
        command.upgrade(cfg, "head")
        with engine.connect() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
            assert db.scalar(text("SELECT decision_reason FROM billing_objections WHERE id='already'")) == "confirmed"
    finally:
        engine.dispose()


@pytest.mark.parametrize("field,value", [
    ("decision_revision", 1),
    ("decision_reason", "Retain original decision rationale"),
    ("decision_actor_id", "actor"),
    ("decision_key", "command-key"),
    ("decided_at", "2026-10-18 12:00:00"),
    ("decision_source_sha256", "a" * 64),
    ("source_period_status", "delivered"),
])
def test_each_piece_of_decision_or_prior_status_evidence_blocks_downgrade(tmp_path, field, value):
    url = "sqlite:///" + (tmp_path / "evidence.sqlite").as_posix()
    engine = create_engine(url)
    try:
        Base.metadata.create_all(engine)
        cfg = alembic_config(url)
        command.stamp(cfg, HEAD)
        with engine.begin() as db:
            db.execute(text(
                "INSERT INTO billing_objections(id,billing_period_id,received_on,reason,status,"
                "created_at,updated_at) VALUES ('retained','legacy','2026-01-01','original','open',"
                "'2026-01-01','2026-01-01')"))
            db.execute(text(f"UPDATE billing_objections SET {field}=:value WHERE id='retained'"),
                       {"value": value})
        with pytest.raises(RuntimeError, match="must not be discarded"):
            command.downgrade(cfg, PARENT)
        with engine.connect() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
            assert db.scalar(text(f"SELECT {field} FROM billing_objections WHERE id='retained'")) == value
    finally:
        engine.dispose()


def test_empty_database_can_downgrade_and_upgrade_the_decision_schema(tmp_path):
    url = "sqlite:///" + (tmp_path / "empty.sqlite").as_posix()
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, PARENT)
    engine = create_engine(url)
    try:
        assert "decision_key" not in {col["name"] for col in inspect(engine).get_columns("billing_objections")}
        command.upgrade(cfg, "head")
        assert "decision_key" in {col["name"] for col in inspect(engine).get_columns("billing_objections")}
    finally:
        engine.dispose()


def test_partial_existing_decision_columns_refuse_adoption_without_altering_original(tmp_path):
    url = "sqlite:///" + (tmp_path / "partial.sqlite").as_posix()
    cfg = alembic_config(url)
    command.upgrade(cfg, PARENT)
    engine = create_engine(url)
    try:
        with engine.begin() as db:
            db.exec_driver_sql("ALTER TABLE billing_objections ADD COLUMN decision_key VARCHAR(120)")
        with pytest.raises(RuntimeError, match="Partial objection decision schema"):
            command.upgrade(cfg, "head")
        with engine.connect() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == PARENT
            names = {column["name"] for column in inspect(db).get_columns("billing_objections")}
            assert "decision_key" in names and "decided_at" not in names
    finally:
        engine.dispose()
