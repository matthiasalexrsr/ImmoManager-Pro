"""Offline retained-family proof against real images and ordinary reset paths."""
# ruff: noqa: F811

import json
import sqlite3
import time
from contextlib import closing
from importlib import import_module
from threading import Event, Thread, get_ident

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from backend import auth
from backend.db.operational_job_models import JOB_MODELS
from backend.db.tenancy_workflow_models import TENANCY_WORKFLOW_MODELS
from backend.services import recovery_sessions
from backend.services.data_transfer import TransferError, export_store_data, import_store_data
from backend.services.operational_job_validation import FIELDS as JOB_FIELDS
from backend.services.operational_job_validation import JobIntegrityError, validate_job_journal
from backend.services.recovery_retained import guard_operational_history
from backend.services.tenancy_workflow_validation import (
    TABLES as WORKFLOW_TABLES,
)
from backend.services.tenancy_workflow_validation import WorkflowIntegrityError, validate_workflow_journal
from backend.services.tenant_privacy import _memory_state, _privacy_write
from backend.tests import test_tenancy_workflow_core as core
from backend.tests.test_tenancy_workflow_core import box as box
from backend.tests.test_tenancy_workflow_core import preview_and_start, published_template


def complete_domain_test_schema(box):
    """Fixture-only production families in this test's disposable SQL image."""
    for module in ("access_models", "auth_models", "bank_import_models", "contract_correspondence_models",
                   "contract_lifecycle_models", "contract_wizard_models", "credit_models", "datev_models",
                   "form_draft_models", "operational_models", "outbox_models", "rent_batch_models", "session_models", "tax_models"):
        import_module("backend.db." + module)
    core.Base.metadata.create_all(box.engine)


@pytest.mark.parametrize("exercise", [
    core.test_template_dag_versioning_and_frozen_started_snapshot,
    core.test_finalized_handover_and_meter_are_immutable_and_valid_evidence,
    core.test_document_original_link_uses_exact_version_identity_without_path_in_response,
    core.test_reanchor_binds_source_etags_preserves_completed_original_and_updates_open_task,
    core.test_required_evidence_and_explicit_not_applicable,
])
def test_real_workflow_history_is_valid_without_live_auth(box, exercise, monkeypatch):
    if box.engine is None:
        pytest.skip("Offline connection proof requires an actual SQL image")
    exercise(box)
    monkeypatch.setattr(auth, "get_user_by_id", lambda _: pytest.fail("offline validator reached live auth"))
    with box.engine.connect() as connection:
        before = connection.exec_driver_sql("SELECT COUNT(*) FROM tenancy_workflow_commands").scalar_one()
        assert validate_workflow_journal(connection, deadline=time.monotonic() + 30)
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM tenancy_workflow_commands").scalar_one() == before


@pytest.mark.parametrize("family", [WORKFLOW_TABLES, set(JOB_FIELDS)])
def test_complete_old_and_partial_table_families_are_distinguished(tmp_path, family):
    image = tmp_path / "older-image.sqlite"
    with closing(sqlite3.connect(image)) as db:
        assert not validate_workflow_journal(db)
        assert not validate_job_journal(db)
        first = sorted(family)[0]
        db.execute('CREATE TABLE "' + first + '" (id TEXT PRIMARY KEY)')
        db.commit()
        validator, error = ((validate_workflow_journal, WorkflowIntegrityError)
                            if family == WORKFLOW_TABLES else (validate_job_journal, JobIntegrityError))
        before = image.read_bytes()
        with pytest.raises(error, match="schema_incomplete"):
            validator(db)
        assert image.read_bytes() == before


@pytest.mark.parametrize("family", [WORKFLOW_TABLES, set(JOB_FIELDS)])
def test_complete_but_empty_wrong_columns_are_rejected_before_any_dml(tmp_path, family):
    image = tmp_path / "bad-ddl.sqlite"
    with closing(sqlite3.connect(image)) as db:
        for name in sorted(family):
            db.execute('CREATE TABLE "' + name + '" (id TEXT PRIMARY KEY)')
        db.commit()
        validator, error = ((validate_workflow_journal, WorkflowIntegrityError)
                            if family == WORKFLOW_TABLES else (validate_job_journal, JobIntegrityError))
        before = image.read_bytes()
        with pytest.raises(error, match="columns_incomplete"):
            validator(db)
        assert image.read_bytes() == before


@pytest.mark.parametrize("damage", ["snapshot_hash", "snapshot_and_hash", "parent", "original_due", "task_title", "command_subject",
                                    "response_mode", "response_creator", "response_title", "response_direction", "response_requirement", "response_due", "response_actor"])
def test_manipulated_actual_sqlite_history_rejects_before_security_dml(box, tmp_path, monkeypatch, damage):
    if box.engine is None or box.engine.dialect.name != "sqlite":
        pytest.skip("This case alters a disposable copied native SQLite image")
    template = published_template(box)
    _, _, change = preview_and_start(box, template)
    if damage == "task_title":
        item = change["steps"][0]
        core.workflow.create_step_task(box.store, change["id"], item["id"], core.CreateStepTask(
            idempotency_key="projection", expected_revision=item["revision"], expected_change_revision=change["revision"]), "tech")
    image = tmp_path / "staged-invalid.sqlite"
    source_path = box.engine.url.database
    box.db.rollback()
    with closing(sqlite3.connect(source_path)) as source, closing(sqlite3.connect(image)) as db:
        source.backup(db)
        for (name,) in tuple(db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")):
            db.execute('DROP TRIGGER "' + name + '"')
        if damage == "snapshot_hash":
            db.execute("UPDATE tenancy_changes SET snapshot_sha256=?", ("0" * 64,))
        elif damage == "snapshot_and_hash":
            raw = json.loads(db.execute("SELECT snapshot FROM tenancy_changes").fetchone()[0])
            raw["templates"][0]["steps"][0]["title"] = "Tampered frozen title"
            db.execute("UPDATE tenancy_changes SET snapshot=?,snapshot_sha256=?", (json.dumps(raw), core.workflow.digest(raw)))
        elif damage == "parent":
            db.execute("UPDATE tenancy_changes SET portfolio_id=?", (box.foreign_portfolio.id,))
        elif damage == "original_due":
            db.execute("UPDATE tenancy_workflow_step_instances SET original_due_date='2000-01-01'")
        elif damage == "task_title":
            db.execute("UPDATE tasks SET title='Changed projection'")
        elif damage == "command_subject":
            db.execute("UPDATE tenancy_workflow_commands SET subject_id=? WHERE operation='start_tenancy_change'", (template["id"],))
        elif damage == "response_actor":
            db.execute("UPDATE tenancy_workflow_commands SET actor_id='different-actor' WHERE operation='start_tenancy_change'")
        else:
            raw = json.loads(db.execute("SELECT response FROM tenancy_workflow_commands WHERE operation='start_tenancy_change'").fetchone()[0])
            if damage == "response_mode":
                raw["mode"] = "turnover"
            elif damage == "response_creator":
                raw["created_by"] = "different-actor"
            else:
                field, value = {"response_title": ("title_snapshot", "Wrong immutable title"),
                                "response_direction": ("direction", "move_in"),
                                "response_requirement": ("requirement", "optional"),
                                "response_due": ("due_date", "2000-01-01")}[damage]
                raw["steps"][0][field] = value
            db.execute("UPDATE tenancy_workflow_commands SET response=? WHERE operation='start_tenancy_change'", (json.dumps(raw),))
        db.commit()
    before = image.read_bytes()
    monkeypatch.setattr(auth, "get_user_by_id", lambda _: pytest.fail("offline path reached live auth"))
    with pytest.raises(recovery_sessions.SessionRestoreError, match="restore_tenancy_workflow_invalid"):
        recovery_sessions.secure_sqlite_restore(image, {"JWT_SECRET_KEY": "synthetic-offline-key"}, deadline=time.monotonic() + 30)
    assert image.read_bytes() == before


def create_job(box):
    from backend.db.operational_job_models import ensure_operational_job_schema
    from backend.services import operational_jobs as jobs
    from backend.services.operational_job_types import JobCreate
    from backend.services.operational_schedule import ensure_operational_schema
    box.users["manager"]["portfolio_access"] = "all"
    if box.engine is not None:
        with box.engine.begin() as connection:
            ensure_operational_schema(connection)
            ensure_operational_job_schema(connection)
    return jobs.create_job(box.store, JobCreate(idempotency_key="retained-job", as_of="2026-11-05"), "manager")


@pytest.mark.parametrize("family", ["workflow", "job"])
def test_reset_export_and_subset_import_retain_real_workflow_facts(box, family):
    if family == "workflow":
        published_template(box)
    else:
        create_job(box)
    if box.db is None:
        before = _memory_state(box.store.__dict__)
    else:
        box.db.rollback()
        with box.engine.connect() as connection:
            before = tuple(tuple(connection.exec_driver_sql('SELECT * FROM "' + model.__tablename__ + '" ORDER BY id'))
                           for model in (*TENANCY_WORKFLOW_MODELS, *JOB_MODELS))
    with pytest.raises(ValueError, match="Mieterwechsel"):
        box.store.clear_all()
    with pytest.raises(TransferError, match="Mieterwechsel"):
        export_store_data(box.store, "synthetic-test")
    with pytest.raises(TransferError, match="Mieterwechsel"):
        import_store_data(box.store, {}, replace_existing=True)
    with pytest.raises(TransferError, match="Mieterwechsel"):
        import_store_data(box.store, {}, replace_existing=False)
    if box.db is None:
        assert _memory_state(box.store.__dict__) == before
    else:
        box.db.rollback()
        with box.engine.connect() as connection:
            assert tuple(tuple(connection.exec_driver_sql('SELECT * FROM "' + model.__tablename__ + '" ORDER BY id'))
                         for model in (*TENANCY_WORKFLOW_MODELS, *JOB_MODELS)) == before


@pytest.mark.parametrize("damage", ["evidence_hash", "evidence_parent", "evidence_shape", "original_bytes", "terminal_fact"])
def test_manipulated_links_originals_and_terminal_facts_are_rejected(box, tmp_path, damage):
    if box.engine is None or box.engine.dialect.name != "sqlite":
        pytest.skip("Disposable native SQLite corruption proof")
    if damage == "original_bytes":
        core.test_document_original_link_uses_exact_version_identity_without_path_in_response(box)
    else:
        core.test_finalized_handover_and_meter_are_immutable_and_valid_evidence(box)
    image = tmp_path / "bad-evidence.sqlite"
    box.db.rollback()
    with closing(sqlite3.connect(box.engine.url.database)) as source, closing(sqlite3.connect(image)) as db:
        source.backup(db)
        db.execute("PRAGMA ignore_check_constraints=ON")
        for (name,) in tuple(db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")):
            db.execute('DROP TRIGGER "' + name + '"')
        if damage == "evidence_hash":
            db.execute("UPDATE tenancy_workflow_evidence_links SET snapshot_sha256=?", ("0" * 64,))
        elif damage == "evidence_parent":
            db.execute("UPDATE tenancy_workflow_evidence_links SET step_id='different-original-step'")
        elif damage == "evidence_shape":
            db.execute("UPDATE tenancy_workflow_evidence_links SET kind='handover_protocol', handover_protocol_id=(SELECT id FROM handover_protocols LIMIT 1)")
        elif damage == "original_bytes":
            db.execute("UPDATE document_version_chunks SET data=?", (b"corrupt archived original",))
        else:
            db.execute("UPDATE tenancy_workflow_step_instances SET completed_by='different-actor' WHERE state='completed'")
        db.commit()
        before = image.read_bytes()
        with pytest.raises(WorkflowIntegrityError):
            validate_workflow_journal(db)
        assert image.read_bytes() == before


@pytest.mark.parametrize("family", ["workflow", "job"])
def test_memory_privacy_staging_preserves_new_orm_facts_and_detects_real_change(box, family):
    if box.engine is not None:
        pytest.skip("Memory ORM staging parity")
    if family == "workflow":
        published_template(box)
        collection = TENANCY_WORKFLOW_MODELS[1].__tablename__
    else:
        create_job(box)
        collection = JOB_MODELS[0].__tablename__
    before = _memory_state(box.store.__dict__)
    with _privacy_write(box.store):
        pass
    assert _memory_state(box.store.__dict__) == before
    from backend.services.tenant_privacy import PrivacyConflict
    with pytest.raises(PrivacyConflict):
        with _privacy_write(box.store):
            next(iter(box.store.__dict__[collection].values())).revision = "changed"


def test_offline_workflow_validator_keeps_caller_transaction_uncommitted(box):
    if box.engine is None:
        pytest.skip("Actual SQL caller-transaction proof")
    template = published_template(box)
    _, _, change = preview_and_start(box, template)
    item = change["steps"][0]
    projected = core.workflow.create_step_task(box.store, change["id"], item["id"], core.CreateStepTask(
        idempotency_key="projected", expected_revision=item["revision"], expected_change_revision=change["revision"]), "tech")
    with box.engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text("UPDATE tasks SET priority='high' WHERE id=:id"), {"id": projected["task_id"]})
        assert validate_workflow_journal(connection)
        assert connection.in_transaction()
        transaction.rollback()
    with box.engine.connect() as connection:
        assert connection.execute(text("SELECT priority FROM tasks WHERE id=:id"), {"id": projected["task_id"]}).scalar_one() == "medium"


def test_later_supported_contract_party_correction_does_not_rewrite_or_invalidate_start(box):
    if box.engine is None:
        pytest.skip("Offline SQL proof")
    complete_domain_test_schema(box)
    template = published_template(box)
    _, _, change = preview_and_start(box, template)
    from backend.models import ContractPatch, TenantCreate
    corrected = box.store.create_tenant(TenantCreate(full_name="Corrected later party"))
    box.store._patch_entity("contract", box.previous.id, ContractPatch(tenant_id=corrected.id))
    assert core.workflow.get_change(box.store, change["id"], "manager")["snapshot_sha256"] == change["snapshot_sha256"]
    with box.engine.connect() as connection:
        assert validate_workflow_journal(connection)


def test_postgres_reset_refuses_paused_memory_auth_writer_without_parent_child_deadlock(box, monkeypatch):
    if box.engine is None or box.engine.dialect.name != "postgresql":
        pytest.skip("Native PostgreSQL lock ordering requires the disposable PostgreSQL service")
    from backend.repositories.sql_store import SQLAlchemyStore
    from backend.services.tenancy_workflow_types import CreateTemplate, TemplateStepInput
    complete_domain_test_schema(box)
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    reached, release = Event(), Event()
    outcomes = []
    original = core.workflow.Work.add

    def paused_add(unit, row):
        if row.__tablename__ == "tenancy_workflow_templates":
            reached.set()
            if not release.wait(10):
                raise AssertionError("Test did not release the paused writer")
        original(unit, row)

    monkeypatch.setattr(core.workflow.Work, "add", paused_add)
    reset_thread = get_ident()
    reset_dml = []

    def capture_reset_dml(connection, cursor, statement, parameters, context, executemany):
        if get_ident() == reset_thread and statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            reset_dml.append(statement)

    event.listen(box.engine, "before_cursor_execute", capture_reset_dml)

    def writer():
        try:
            with Session(box.engine) as session:
                result = core.workflow.create_template(SQLAlchemyStore(session), CreateTemplate(
                    idempotency_key="concurrent-first-template", expected_revision="new", property_id=box.property.id, direction="move_out",
                    steps=[TemplateStepInput(stable_key="first", position=1, title="First retained step",
                                             default_requirement="required", offset_days=0,
                                             assignee_role="techniker", anchor="previous_contract_end")]), "manager")
                outcomes.append(result)
        except BaseException as error:
            outcomes.append(error)

    thread = Thread(target=writer, daemon=True)
    thread.start()
    try:
        assert reached.wait(10), outcomes
        with Session(box.engine) as session:
            session.execute(text("SET LOCAL lock_timeout='2s'"))
            before = session.execute(text("SELECT COUNT(*) FROM properties")).scalar_one()
            with pytest.raises(ValueError, match="laufender Schreibvorgang"):
                SQLAlchemyStore(session).clear_all()
            # Busy child/parent barriers roll back only their savepoint and never
            # poison or commit this caller-owned transaction.
            assert session.in_transaction()
            assert session.execute(text("SELECT COUNT(*) FROM properties")).scalar_one() == before
            session.rollback()
    finally:
        release.set()
        thread.join(10)
        event.remove(box.engine, "before_cursor_execute", capture_reset_dml)
    assert not thread.is_alive()
    assert reset_dml == []
    assert len(outcomes) == 1 and isinstance(outcomes[0], dict), outcomes
    with Session(box.engine) as session:
        with pytest.raises(ValueError, match="Mieterwechsel"):
            SQLAlchemyStore(session).clear_all()
    with box.engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM tenancy_workflow_templates").scalar_one() == 1
        assert validate_workflow_journal(connection)


def test_sql_empty_families_validate_and_offline_failure_rolls_back_claim_reset(box, monkeypatch):
    if box.engine is None:
        pytest.skip("Actual SQL transaction gate")
    from backend.db.operational_job_models import ensure_operational_job_schema
    from backend.db.session_models import ensure_session_schema
    from backend.services import operational_jobs as jobs
    from backend.services.operational_job_types import JobCreate
    from backend.services.operational_schedule import ensure_operational_schema
    box.users["manager"]["portfolio_access"] = "all"
    with box.engine.begin() as connection:
        ensure_operational_schema(connection)
        ensure_operational_job_schema(connection)
        ensure_session_schema(connection)
    job = jobs.create_job(box.store, JobCreate(idempotency_key="restorable", as_of="2026-11-05"), "manager")
    claim = jobs.claim_lane(box.store, job["id"], "offline-old-worker", actor_id="manager")
    with box.engine.connect() as connection:
        assert validate_workflow_journal(connection)
        assert validate_job_journal(connection)
        before = tuple(connection.exec_driver_sql("SELECT * FROM operational_job_lanes ORDER BY id"))
    from backend.db import session_models
    configuration = {"JWT_SECRET_KEY": "synthetic-offline-signing-key"}
    monkeypatch.setattr(session_models, "invalidate_restored_sessions", lambda _: (_ for _ in ()).throw(RuntimeError("later security failure")))
    with box.engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(RuntimeError, match="later security"):
            recovery_sessions.invalidate_and_inspect(connection, configuration, deadline=time.monotonic() + 30)
        transaction.rollback()
    with box.engine.connect() as connection:
        assert tuple(connection.exec_driver_sql("SELECT * FROM operational_job_lanes ORDER BY id")) == before
    monkeypatch.undo()
    with box.engine.begin() as connection:
        recovery_sessions.invalidate_and_inspect(connection, configuration, deadline=time.monotonic() + 30)
    with box.engine.connect() as connection:
        lane = connection.execute(text("SELECT fence,lease_token FROM operational_job_lanes WHERE id=:id"), {"id": claim.lane_id}).one()
        assert lane.fence > claim.fence and lane.lease_token is None


def test_every_retained_family_is_guarded_without_live_auth(tmp_path, monkeypatch):
    from backend.storage import InMemoryStore
    for model in (*TENANCY_WORKFLOW_MODELS, *JOB_MODELS):
        store = InMemoryStore()
        store.__dict__[model.__tablename__] = {"retained": model()}
        monkeypatch.setattr(auth, "get_user_by_id", lambda _: pytest.fail("retention guard reached live auth"))
        with pytest.raises(ValueError, match="Mieterwechsel"):
            guard_operational_history(store)
