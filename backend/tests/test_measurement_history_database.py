"""Native offline proof against actual authenticated source commands."""

import sqlite3
import time
from contextlib import contextmanager
from copy import deepcopy

import pytest
from sqlalchemy import create_engine, select, text, update

from backend.db.measurement_history_models import MEASUREMENT_TABLES, MeasurementCommandORM, MeasurementFactORM
from backend.db.measurement_history_schema import install_measurement_guards
from backend.services.measurement_history_database import validate_measurement_database
from backend.services.measurement_history_validation import MeasurementIntegrityError, digest, fact_hash
from backend.services.recovery_retained import guard_operational_history
from backend.services.recovery_sessions import SessionRestoreError, invalidate_and_inspect
from backend.storage import ValidationError
from backend.tests.form_draft_api_support import application, migrate
from backend.tests.measurement_history_postgres_support import migrated_postgres
from backend.tests.test_measurement_history_http import confirm, fixture_history
from backend.tests.test_measurement_history_http import context as context_fixture

context = context_fixture


@pytest.fixture(params=["sqlite", "postgres"])
def draft_http(request, monkeypatch, tmp_path):
    if request.param == "postgres":
        with migrated_postgres(monkeypatch) as (engine, _), application(monkeypatch, engine) as active:
            yield active
        return
    url = "sqlite:///" + (tmp_path / "native-originals.sqlite").as_posix()
    migrate(url, monkeypatch)
    engine = create_engine(url, hide_parameters=True, connect_args={"check_same_thread": False})
    try:
        with application(monkeypatch, engine) as active:
            yield active
    finally:
        engine.dispose()


@contextmanager
def privileged_original_edit(engine):
    """Explicit tamper fixture, only in an owned disposable database."""
    with engine.begin() as db:
        if engine.dialect.name == "sqlite":
            for name in MEASUREMENT_TABLES[1:]:
                for operation in ("update", "delete"):
                    db.exec_driver_sql(f"DROP TRIGGER preserve_{name}_{operation}")
        else:
            for name in MEASUREMENT_TABLES[1:]:
                db.exec_driver_sql(f"ALTER TABLE {name} DISABLE TRIGGER preserve_{name}")
        yield db
        if engine.dialect.name == "sqlite":
            install_measurement_guards(db)
        else:
            for name in MEASUREMENT_TABLES[1:]:
                db.exec_driver_sql(f"ALTER TABLE {name} ENABLE TRIGGER preserve_{name}")


def test_all_native_sources_and_corrections_are_proved_without_loading_whole_parent_stock(context):
    _, changes, receipts = fixture_history(context)
    fix = deepcopy(changes[0][2])
    fix.update(predecessor_id=receipts[0]["fact_ids"][2], reason="Belegter korrigierter Grenzwert")
    fix["data"]["value"] = "120"
    confirm(context, context["homes"][0], [fix], revision=1, command="corrected-original")
    engine = context["active"].engine
    with engine.connect() as db:
        before = db.execute(text("SELECT reason,content_hash FROM measurement_facts ORDER BY id")).all()
        assert validate_measurement_database(db, deadline=time.monotonic() + 30)
        if engine.dialect.name == "sqlite":
            assert validate_measurement_database(db.connection.driver_connection)
        assert db.execute(text("SELECT reason,content_hash FROM measurement_facts ORDER BY id")).all() == before
        with pytest.raises(MeasurementIntegrityError, match="Zeitbudget"):
            validate_measurement_database(db, deadline=time.monotonic() - 1)


def test_corrupt_original_hash_refuses_security_finalization_before_any_claim_or_session_update(context):
    _, _, receipts = fixture_history(context)
    engine = context["active"].engine
    with privileged_original_edit(engine) as db:
        db.execute(update(MeasurementFactORM).where(MeasurementFactORM.id == receipts[0]["fact_ids"][2]).values(reason="changed behind retained original"))
    with engine.begin() as db:
        before = db.execute(text("SELECT id,revoked_at FROM auth_sessions ORDER BY id")).all()
        with pytest.raises(MeasurementIntegrityError):
            validate_measurement_database(db)
        with pytest.raises(SessionRestoreError, match="restore_measurement_history_invalid"):
            invalidate_and_inspect(db, {}, deadline=time.monotonic() + 30)
        assert db.execute(text("SELECT id,revoked_at FROM auth_sessions ORDER BY id")).all() == before


def test_coherent_per_unit_sources_cannot_hide_cross_unit_physical_meter_overlap(context):
    _, changes, receipts = fixture_history(context)
    engine = context["active"].engine
    with privileged_original_edit(engine) as db:
        fact = dict(db.execute(select(MeasurementFactORM.__table__).where(
            MeasurementFactORM.id == receipts[1]["fact_ids"][0])).mappings().one())
        command = dict(db.execute(select(MeasurementCommandORM.__table__).where(
            MeasurementCommandORM.id == fact["command_id"])).mappings().one())
        fact["meter_id"] = changes[0][0]["data"]["meter_id"]
        fact["data"] = {**fact["data"], "meter_id": fact["meter_id"]}
        fact["content_hash"] = fact_hash(fact, [])
        request = deepcopy(command["request"])
        request["changes"][0]["data"]["meter_id"] = fact["meter_id"]
        db.execute(update(MeasurementFactORM).where(MeasurementFactORM.id == fact["id"]).values(
            meter_id=fact["meter_id"], data=fact["data"], content_hash=fact["content_hash"]))
        db.execute(update(MeasurementCommandORM).where(MeasurementCommandORM.id == command["id"]).values(
            request=request, request_hash=digest(request)))
    with engine.connect() as db:
        with pytest.raises(MeasurementIntegrityError, match="zwischen Einheiten"):
            validate_measurement_database(db)


def test_native_protection_body_and_enabled_status_are_required_and_never_repaired(context):
    fixture_history(context)
    engine = context["active"].engine
    with engine.begin() as db:
        if engine.dialect.name == "sqlite":
            db.exec_driver_sql("DROP TRIGGER preserve_measurement_facts_update")
            db.exec_driver_sql("CREATE TRIGGER preserve_measurement_facts_update BEFORE UPDATE ON measurement_facts BEGIN SELECT 1; END")
        else:
            db.exec_driver_sql("ALTER TABLE measurement_facts DISABLE TRIGGER preserve_measurement_facts")
    with engine.connect() as db:
        with pytest.raises(MeasurementIntegrityError, match="Originalschutzregel"):
            validate_measurement_database(db)


def test_retained_source_ledger_refuses_business_subset_before_delete_even_without_other_jobs(context):
    fixture_history(context)
    active = context["active"]
    with pytest.raises(ValidationError, match="Abrechnungshistorie"):
        guard_operational_history(active.store, serialized=True)
    active.store.db.rollback()
    active.store.db.remove()
    with active.engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM measurement_facts")).scalar_one() == 10


def test_wholly_absent_legacy_family_is_supported_and_partial_family_is_rejected(tmp_path):
    with sqlite3.connect(tmp_path / "legacy.sqlite") as db:
        assert not validate_measurement_database(db)
        db.execute("CREATE TABLE measurement_ledgers(id TEXT PRIMARY KEY)")
        with pytest.raises(MeasurementIntegrityError, match="unvollständig"):
            validate_measurement_database(db)
