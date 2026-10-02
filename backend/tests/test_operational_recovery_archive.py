"""Actual encrypted archive with frozen workflow evidence and a live job claim."""

import sqlite3
import time
from contextlib import closing
from datetime import date
from importlib import import_module
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend import auth
from backend.db.operational_job_models import JOB_MODELS, ensure_operational_job_schema
from backend.db.orm_models import Base
from backend.db.tenancy_workflow_models import TENANCY_WORKFLOW_MODELS
from backend.models import (
    ContractPatch,
    DocumentCreate,
    HandoverProtocolCreate,
    MeterReadingCreate,
    RentChargeCreate,
    TenantPatch,
)
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import document_versions, operational_jobs, recovery_sessions, tenancy_workflow
from backend.services.full_recovery import _database_info, create_full_backup, restore_full_backup
from backend.services.operational_job_types import JobContinue, JobCreate
from backend.services.operational_job_validation import validate_job_journal
from backend.services.operational_schedule import ensure_operational_schema
from backend.services.tenancy_workflow_types import (
    AddEvidence,
    CreateTemplateVersion,
    EvidenceInput,
    PublishTemplateVersion,
    ReanchorPreview,
    ReanchorTenancyChange,
    UpdateStep,
)
from backend.services.tenancy_workflow_validation import validate_workflow_journal
from backend.tests.test_full_recovery import PASSPHRASE
from backend.tests.test_full_recovery import plan as plan
from backend.tests.test_full_recovery import runtime_template as runtime_template
from backend.tests.test_tenancy_workflow_core import current_step, preview_and_start, published_template, step


def rows(path, models):
    with closing(sqlite3.connect(path)) as db:
        return tuple(tuple(db.execute('SELECT * FROM "' + model.__tablename__ + '" ORDER BY id')) for model in models)


def seed(plan, monkeypatch):
    engine = create_engine("sqlite:///" + plan.database.as_posix())
    users = {identifier: {"id": identifier, "full_name": identifier, "role": role, "is_active": True, "portfolio_access": "all", "portfolio_ids": []}
             for identifier, role in (("manager", "verwalter"), ("tech", "techniker"))}
    monkeypatch.setattr(auth, "get_user_by_id", users.get)
    try:
        with engine.begin() as connection:
            Base.metadata.create_all(connection)
            import_module("backend.db.migrations.versions.b2a2b3c4d5e6_tenancy_workflows").install_guards(connection)
            ensure_operational_schema(connection)
            ensure_operational_job_schema(connection)
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            previous = store.list_contracts()[0]
            previous = store._patch_entity("contract", previous.id, ContractPatch(end_date=date(2026, 12, 31), status="terminated"))
            prop, unit = store.get_property(previous.property_id), store.get_unit(previous.unit_id)
            box = SimpleNamespace(store=store, db=db, engine=engine, users=users, previous=previous, following=None,
                                  property=prop, unit=unit, portfolio=store.get_portfolio(prop.portfolio_id))
            template = published_template(box, steps=[step("prepare", 0), step("optional", 1, requirement="optional", depends=("prepare",))])
            _, _, change = preview_and_start(box, template)
            change_id = change["id"]
            change, item = current_step(box, change_id, "prepare")
            tenancy_workflow.create_step_task(store, change_id, item["id"], tenancy_workflow.CreateStepTask(
                idempotency_key="original-task", expected_revision=item["revision"], expected_change_revision=change["revision"]), "tech")
            protocol = store.create_handover_protocol(HandoverProtocolCreate(contract_id=previous.id, unit_id=unit.id,
                protocol_type="move_out", protocol_date=date(2026, 12, 30), status="draft"))
            reading = store.create_meter_reading(MeterReadingCreate(handover_id=protocol.id, meter_type="electricity",
                meter_number="SYNTHETIC-METER", reading_value=123.45, unit="kWh"))
            store.update_handover_protocol(protocol.id, HandoverProtocolCreate(
                **{**protocol.model_dump(include=set(HandoverProtocolCreate.model_fields)), "status": "finalized"}))
            document = store.create_document(DocumentCreate(property_id=prop.id, unit_id=unit.id, contract_id=previous.id,
                title="Synthetic retained original", file_url="/uploads/workflow-evidence.pdf"))
            with document_versions.work(store, "manager", write=True) as (active, active_db, _):
                actual, binding = document_versions._document(active, active_db, document.id, lock=True)
                version = document_versions.publish_generated_original(active, active_db, actual, binding, "manager",
                    b"%PDF-1.4\nretained offline original\n%%EOF", "a" * 64)
            for number, evidence in enumerate((EvidenceInput(kind="document_version", document_id=document.id, document_version_id=version.id),
                    EvidenceInput(kind="handover_protocol", handover_protocol_id=protocol.id), EvidenceInput(kind="meter_reading", meter_reading_id=reading.id))):
                change, item = current_step(box, change_id, "prepare")
                tenancy_workflow.add_evidence(store, change_id, item["id"], AddEvidence(idempotency_key="witness-" + str(number),
                    expected_revision=item["revision"], expected_change_revision=change["revision"], evidence=evidence), "tech")
            for number, handover in enumerate((date(2027, 1, 1), date(2027, 1, 5))):
                change = tenancy_workflow.get_change(store, change_id, "manager")
                preview = tenancy_workflow.reanchor_preview(store, change_id, ReanchorPreview(expected_revision=change["revision"], move_out_handover_date=handover), "manager")
                tenancy_workflow.reanchor_change(store, change_id, ReanchorTenancyChange(idempotency_key="reschedule-" + str(number),
                    expected_revision=change["revision"], move_out_handover_date=handover,
                    preview_hash=preview["preview_hash"], source_etags=preview["source_etags"]), "manager")
                if number == 0:
                    for state in ("in_progress", "completed"):
                        change, item = current_step(box, change_id, "prepare")
                        tenancy_workflow.update_step(store, change_id, item["id"], UpdateStep(idempotency_key="terminal-" + state,
                            expected_revision=item["revision"], expected_change_revision=change["revision"], state=state), "tech")
                    change, item = current_step(box, change_id, "optional")
                    tenancy_workflow.create_step_task(store, change_id, item["id"], tenancy_workflow.CreateStepTask(
                        idempotency_key="optional-task", expected_revision=item["revision"], expected_change_revision=change["revision"]), "tech")
            change = tenancy_workflow.get_change(store, change_id, "manager")
            tenancy_workflow.complete_change(store, change_id, tenancy_workflow.CompleteTenancyChange(idempotency_key="completed-change", expected_revision=change["revision"]), "manager")
            draft = tenancy_workflow.create_template_version(store, template["template_id"], CreateTemplateVersion(idempotency_key="replacement-version",
                expected_revision=template["revision"], based_on_version_id=template["id"]), "manager")
            tenancy_workflow.publish_template_version(store, draft["id"], PublishTemplateVersion(idempotency_key="publish-replacement", expected_revision=draft["revision"]), "manager")
            store._patch_entity("tenant", previous.tenant_id, TenantPatch(full_name="Changed current profile"))
            for number in range(8):
                store.create_rent_charge(RentChargeCreate(contract_id=previous.id, month=f"2020-{number + 1:02}", cold_rent=100, status="open"))
            job = operational_jobs.create_job(store, JobCreate(idempotency_key="restored-work", as_of=date(2026, 11, 5), families=("overdue_rent_charge",)), "manager")
            claim = operational_jobs.claim_lane(store, job["id"], "pre-backup-worker", actor_id="manager")
            operational_jobs.prepare_claim(store, claim, JobContinue(max_items=7))
            return job, claim
    finally:
        engine.dispose()


def test_actual_encrypted_source_gone_keeps_all_facts_and_fences_old_claim(plan, tmp_path, monkeypatch):
    job, claim = seed(plan, monkeypatch)
    before = rows(plan.database, TENANCY_WORKFLOW_MODELS)
    before_items = rows(plan.database, (JOB_MODELS[2],))
    with closing(sqlite3.connect(plan.database)) as db:
        assert validate_workflow_journal(db)
        assert validate_job_journal(db)
    archive = tmp_path / "workflow-jobs.immobak"
    create_full_backup(plan, archive, PASSPHRASE, offline=True)
    assert b"retained offline original" not in archive.read_bytes()
    source = plan.database.parent.resolve()
    assert source == (tmp_path / "source").resolve()
    source.rename(tmp_path / "source-offline")
    target = tmp_path / "restored"
    restore_full_backup(archive, target, PASSPHRASE)
    image = target / "database.sqlite3"
    assert rows(image, TENANCY_WORKFLOW_MODELS) == before
    assert rows(image, (JOB_MODELS[2],)) == before_items
    with closing(sqlite3.connect(image)) as db:
        assert validate_workflow_journal(db) and validate_job_journal(db)
        fence, token = db.execute("SELECT fence,lease_token FROM operational_job_lanes WHERE id=?", (claim.lane_id,)).fetchone()
        assert fence > claim.fence and token is None
    engine = create_engine("sqlite:///" + image.as_posix())
    try:
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            with pytest.raises(operational_jobs.ClaimLost):
                operational_jobs.run_claim(store, claim, JobContinue(max_items=7))
            for _ in range(20):
                done = operational_jobs.continue_job(store, job["id"], JobContinue(max_items=7), "manager")
                if done["state"] == "completed":
                    break
            assert done["state"] == "completed" and len(store.list_notifications()) == 8
    finally:
        engine.dispose()


def test_complete_older_sqlite_archive_without_either_family_roundtrips(plan, tmp_path):
    # Core DTO/model imports register current metadata in this test process;
    # the source image intentionally predates both complete optional families.
    with closing(sqlite3.connect(plan.database)) as db:
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not names.intersection(model.__tablename__ for model in (*TENANCY_WORKFLOW_MODELS, *JOB_MODELS))
    before = _database_info(plan.database)
    archive = tmp_path / "complete-older.immobak"
    create_full_backup(plan, archive, PASSPHRASE, offline=True)
    restore_full_backup(archive, tmp_path / "older-restored", PASSPHRASE)
    assert _database_info(tmp_path / "older-restored" / "database.sqlite3") == before


def test_late_signing_configuration_failure_rolls_back_actual_sqlite_claim_reset(plan, monkeypatch):
    seed(plan, monkeypatch)
    before = rows(plan.database, JOB_MODELS)
    monkeypatch.setattr(recovery_sessions, "rotated_configuration", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("late signing failure")))
    with pytest.raises(recovery_sessions.SessionRestoreError, match="restore_session_security_failed"):
        recovery_sessions.secure_sqlite_restore(plan.database, plan.configuration, deadline=time.monotonic() + 30)
    assert rows(plan.database, JOB_MODELS) == before
