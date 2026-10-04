"""Encrypted full-image roundtrip of retained measured originals and evidence."""

import sqlite3
from copy import deepcopy

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend import auth
from backend.models import AllocationKeyCreate, DocumentCreate, MeterCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import document_versions, measurement_history
from backend.services.full_recovery import _database_info, create_full_backup, restore_full_backup
from backend.services.measurement_history_database import validate_measurement_database
from backend.services.measurement_history_types import MeasurementCommand
from backend.services.portfolio_scope import scope_context
from backend.services.recovery_archive import RecoveryError
from backend.tests.test_full_recovery import PASSPHRASE
from backend.tests.test_full_recovery import plan as plan
from backend.tests.test_full_recovery import runtime_template as runtime_template
from backend.tests.test_measurement_history_http import fact, span


def original_rows(path):
    with sqlite3.connect(path) as db:
        return tuple(tuple(db.execute("SELECT * FROM " + name + " ORDER BY id")) for name in
            ("measurement_ledgers", "measurement_commands", "measurement_facts", "measurement_evidence"))


def populated(plan, monkeypatch):
    engine = create_engine("sqlite:///" + plan.database.as_posix())
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    try:
        with engine.connect() as db:
            actor_id = db.execute(text("SELECT id FROM users WHERE username='recovery-owner'")).scalar_one()
        with Session(engine) as db, scope_context(None):
            store = SQLAlchemyStore(db)
            lease = store.list_contracts()[0]
            meter = store.create_meter(MeterCreate(unit_id=lease.unit_id, meter_type="cold_water", measurement_unit="m³"))
            key = store.create_allocation_key(AllocationKeyCreate(property_id=lease.property_id,
                name="Synthetic exact water", key_type="consumption", consumption_medium="cold_water", consumption_unit="m³"))
            changes = [fact("assignment", "assignment", **span(), meter_id=meter.id, medium="cold_water", measurement_unit="m³", circuit_path=["water"]),
                fact("start", "reading", assignment_key="assignment", boundary_date="2026-01-01", value="100"),
                fact("end", "reading", assignment_key="assignment", boundary_date="2027-01-01", value="120"),
                fact("occupancy", "occupancy", **span(), contract_id=lease.id, persons=2),
                fact("selection", "selection", **span(), allocation_key_id=key.id, basis="consumption", circuits=[["water"]], confirmed_disjoint=True)]
            receipt = measurement_history.confirm(store, lease.unit_id, MeasurementCommand.model_validate({
                "expected_revision": 0, "idempotency_key": "recovered-sources", "changes": changes}), actor_id)
            document = store.create_document(DocumentCreate(property_id=lease.property_id, unit_id=lease.unit_id,
                title="Synthetic signed measurement basis", file_url="/uploads/proof.bin"))
            with document_versions.work(store, actor_id, write=True) as (active, actual_db, _):
                actual, binding = document_versions._document(active, actual_db, document.id, lock=True)
                version = document_versions.publish_generated_original(active, actual_db, actual, binding, actor_id,
                    b"%PDF-1.4\nSynthetic measurement approval\n%%EOF", "b" * 64)
            approval = fact("approval", "proration", **span(), assignment_key="assignment",
                start_reading_id=receipt["fact_ids"][1], end_reading_id=receipt["fact_ids"][2])
            approval["evidence_version_ids"] = [version.id]
            measurement_history.confirm(store, lease.unit_id, MeasurementCommand.model_validate({
                "expected_revision": 1, "idempotency_key": "recovered-approval", "changes": [approval]}), actor_id)
            correction = deepcopy(changes[3])
            correction.update(predecessor_id=receipt["fact_ids"][3], reason="Belegter Bewohnerwechsel")
            correction["data"]["persons"] = 3
            measurement_history.confirm(store, lease.unit_id, MeasurementCommand.model_validate({
                "expected_revision": 2, "idempotency_key": "recovered-correction", "changes": [correction]}), actor_id)
            assert validate_measurement_database(db.connection())
    finally:
        engine.dispose()


def test_full_encrypted_restore_preserves_every_source_correction_and_original_evidence(plan, monkeypatch, tmp_path):
    populated(plan, monkeypatch)
    before = original_rows(plan.database)
    backup, target = tmp_path / "measurement.immobak", tmp_path / "restored-measurement"
    create_full_backup(plan, backup, PASSPHRASE, offline=True)
    restored = restore_full_backup(backup, target, PASSPHRASE)
    assert restored["signing_key_rotated"]
    assert original_rows(target / "database.sqlite3") == before == original_rows(plan.database)
    assert len(before[1]) == 3 and len(before[2]) == 7 and len(before[3]) == 1
    with sqlite3.connect(target / "database.sqlite3") as db:
        assert validate_measurement_database(db)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE measurement_facts SET reason='overwrite after restore'")


def test_damaged_native_original_is_refused_before_backup_publication(plan, monkeypatch, tmp_path):
    populated(plan, monkeypatch)
    with sqlite3.connect(plan.database) as db:
        db.execute("DROP TRIGGER preserve_measurement_facts_update")
        db.execute("UPDATE measurement_facts SET reason='modified original'")
    with pytest.raises(RecoveryError, match="Historische Abrechnungsquellen"):
        _database_info(plan.database)
    target = tmp_path / "never-published.immobak"
    with pytest.raises(RecoveryError, match="Historische Abrechnungsquellen"):
        create_full_backup(plan, target, PASSPHRASE, offline=True)
    assert not target.exists()
