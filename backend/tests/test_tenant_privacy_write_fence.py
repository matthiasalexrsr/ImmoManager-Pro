"""Confirmation contention proved with native writers/events, never sleep.

PostgreSQL cases own a randomly named schema from the existing workflow fixture.
Only TEST_SERVER_DATABASE_URL enables them; Memory/SQLite stay real stores too.
"""
# ruff: noqa: F811

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timezone
from threading import Event, current_thread

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from backend import auth
from backend.db.auth_models import AuthSetupORM
from backend.db.operational_job_models import JOB_MODELS
from backend.db.operational_models import (
    OperationalDispatchORM,
    OperationalLockORM,
    OperationalOccurrenceORM,
    OperationalScheduleORM,
    OperationalTickORM,
)
from backend.db.orm_models import TenantORM
from backend.db.tenancy_workflow_models import TENANCY_WORKFLOW_MODELS, WorkflowCommandORM
from backend.models import ContractPatch, TaskCreate, TenantCreate, TenantPatch
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import operational_jobs as jobs
from backend.services import tenancy_workflow as workflow
from backend.services import tenant_privacy as privacy
from backend.services.operational_job_types import JobCreate
from backend.services.operational_schedule import _state_lock, ensure_operational_schema
from backend.services.payments import _memory_lock
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.tenancy_workflow_types import UpdateStep
from backend.tests.test_operational_recovery_guards import complete_domain_test_schema
from backend.tests.test_tenancy_workflow_core import box as box
from backend.tests.test_tenancy_workflow_core import preview_and_start, published_template

OPERATIONAL_FAMILY = (OperationalLockORM, OperationalScheduleORM, OperationalOccurrenceORM,
                      OperationalDispatchORM, OperationalTickORM)


def setup_subject(box, monkeypatch, *, sql_auth=False, historical=False):
    if box.engine is not None:
        complete_domain_test_schema(box)
    if sql_auth:
        if box.engine is None:
            pytest.skip("SQL account-lock proof needs a real SQL domain")
        monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(sessionmaker(box.engine)))
        with Session(box.engine) as session:
            if session.get(AuthSetupORM, 1) is None:
                session.add(AuthSetupORM(id=1))
                session.commit()
    else:
        monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", sessionmaker(box.engine) if sql_auth else None)
    # Native account reads/rights rechecks use this test's actual store, rather
    # than the inherited workflow fixture's convenient get_user_by_id stub.
    for identifier, user in box.users.items():
        auth._user_store.create({**user, "username": "fence-" + identifier,
            "email": identifier + "@example.invalid", "hashed_password": "unused-synthetic-auth-hash",
            "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
            "totp_enabled": False, "totp_secret": None})
    monkeypatch.setattr(auth, "get_user_by_id", auth._user_store.get_by_id)
    template = published_template(box)
    _, _, change = preview_and_start(box, template)
    if historical:
        corrected = box.store.create_tenant(TenantCreate(full_name="Current corrected synthetic party"))
        box.store._patch_entity("contract", box.previous.id, ContractPatch(tenant_id=corrected.id))
        assert box.store.get_contract(box.previous.id).tenant_id != box.previous.tenant_id
    plan = privacy.preview_tenant_anonymization(box.store, box.previous.tenant_id)
    return change, plan


def confirm(box, plan):
    return privacy.anonymize_tenant_profile(box.store, box.previous.tenant_id,
        plan_hash=plan["plan_hash"], confirm_tenant_id=box.previous.tenant_id)


def journal(box):
    if box.engine is not None:
        box.db.rollback()
        with box.engine.connect() as connection:
            return tuple(tuple(connection.execute(model.__table__.select().order_by(model.id)))
                         for model in (*TENANCY_WORKFLOW_MODELS, *JOB_MODELS))
    return privacy._memory_state(deepcopy({model.__tablename__: box.store.__dict__.get(model.__tablename__, {})
                                          for model in (*TENANCY_WORKFLOW_MODELS, *JOB_MODELS)}))


@pytest.mark.parametrize("sql_auth", [False, True], ids=["memory-auth", "sql-auth"])
def test_historical_party_confirmation_preserves_every_frozen_fact_and_receipt(box, monkeypatch, sql_auth):
    _, plan = setup_subject(box, monkeypatch, sql_auth=sql_auth, historical=True)
    before = journal(box)
    result = confirm(box, plan)
    assert result["status"] == "profile_anonymized"
    assert box.store.get_tenant(box.previous.tenant_id).archived
    assert journal(box) == before


@contextmanager
def no_profile_dml(box):
    writes = []
    def observe(_connection, _cursor, statement, _params, _context, _many):
        normalized = statement.lower().replace('"', '')
        if "update tenants " in normalized or "delete from tenants" in normalized:
            writes.append(statement)
    event.listen(box.engine, "before_cursor_execute", observe)
    try:
        yield writes
    finally:
        event.remove(box.engine, "before_cursor_execute", observe)


@pytest.mark.parametrize("sql_auth", [False, True], ids=["memory-auth", "sql-auth"])
def test_pg_actual_old_party_step_writer_refuses_profile_before_any_dml(box, monkeypatch, sql_auth):
    if box.engine is None or box.engine.dialect.name != "postgresql":
        pytest.skip("Native independent PostgreSQL sessions required")
    change, plan = setup_subject(box, monkeypatch, sql_auth=sql_auth, historical=True)
    held, release = Event(), Event()
    touch = workflow._touch_step
    def pause_after_native_locks(unit, step):
        touch(unit, step)
        held.set()
        assert release.wait(15), "Controller did not release the actual step writer"
    monkeypatch.setattr(workflow, "_touch_step", pause_after_native_locks)
    item = change["steps"][0]
    def write():
        with Session(box.engine) as session:
            return workflow.update_step(SQLAlchemyStore(session), change["id"], item["id"], UpdateStep(
                idempotency_key="busy-profile-step", expected_revision=item["revision"],
                expected_change_revision=change["revision"], state="in_progress"), "tech")
    with no_profile_dml(box) as writes, ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(write)
        try:
            assert held.wait(10)
            with pytest.raises(privacy.PrivacyConflict, match="erneut versuchen"):
                confirm(box, plan)
            assert writes == []
            assert box.store.get_tenant(box.previous.tenant_id).full_name == "Old synthetic tenant"
        finally:
            release.set()
        assert writer.result(timeout=10)["state"] == "in_progress"
    with box.engine.connect() as connection:
        assert connection.scalar(select(WorkflowCommandORM.id).where(
            WorkflowCommandORM.idempotency_key == "busy-profile-step")) is not None


@pytest.mark.parametrize("sql_auth", [False, True], ids=["memory-auth", "sql-auth"])
def test_pg_actual_job_writer_refuses_profile_before_any_dml(box, monkeypatch, sql_auth):
    if box.engine is None or box.engine.dialect.name != "postgresql":
        pytest.skip("Native independent PostgreSQL sessions required")
    _, plan = setup_subject(box, monkeypatch, sql_auth=sql_auth, historical=True)
    with box.engine.begin() as connection:
        ensure_operational_schema(connection)
    # Global rights are required by the job API, not granted by privacy.
    auth._user_store.update("manager", {"portfolio_access": "all", "portfolio_ids": []})
    held, release = Event(), Event()
    add = jobs.Unit.add
    def pause_actual_publication(unit, row):
        if current_thread().name.startswith("actual-job-writer"):
            held.set()
            assert release.wait(15), "Controller did not release the actual job writer"
        add(unit, row)
    monkeypatch.setattr(jobs.Unit, "add", pause_actual_publication)
    def write():
        with Session(box.engine) as session:
            return jobs.create_job(SQLAlchemyStore(session), JobCreate(
                idempotency_key="busy-profile-job", as_of="2026-11-05"), "manager")
    with no_profile_dml(box) as writes, ThreadPoolExecutor(max_workers=1, thread_name_prefix="actual-job-writer") as pool:
        writer = pool.submit(write)
        try:
            assert held.wait(10)
            with pytest.raises(privacy.PrivacyConflict, match="erneut versuchen"):
                confirm(box, plan)
            assert writes == []
            assert not box.store.get_tenant(box.previous.tenant_id).archived
        finally:
            release.set()
        assert writer.result(timeout=10)["state"] == "queued"


@pytest.mark.parametrize("carrier", ["account", "operational"], ids=["sql-account", "empty-operational"])
def test_pg_fence_held_through_actual_hash_prevents_late_carrier_publication(box, monkeypatch, carrier):
    if box.engine is None or box.engine.dialect.name != "postgresql":
        pytest.skip("Native independent PostgreSQL sessions required")
    _, plan = setup_subject(box, monkeypatch, sql_auth=True, historical=True)
    held, release = Event(), Event()
    original = privacy._plan
    def pause_after_real_hash(graph):
        result = original(graph)
        if current_thread().name.startswith("held-profile"):
            held.set()
            assert release.wait(15)
        return result
    monkeypatch.setattr(privacy, "_plan", pause_after_real_hash)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="held-profile") as pool:
        profile = pool.submit(confirm, box, plan)
        try:
            assert held.wait(10)
            from sqlalchemy.exc import OperationalError
            with Session(box.engine) as session:
                with pytest.raises(OperationalError) as failure:
                    if carrier == "account":
                        session.scalar(select(AuthSetupORM.id).with_for_update(nowait=True))
                    else:
                        # The empty legacy singleton's table is protected too.
                        session.connection().exec_driver_sql("LOCK TABLE operational_lock IN ROW EXCLUSIVE MODE NOWAIT")
                assert getattr(failure.value.orig, "pgcode", None) == "55P03"
        finally:
            release.set()
        assert profile.result(timeout=10)["status"] == "profile_anonymized"
    with box.engine.connect() as connection:
        assert connection.scalar(select(OperationalLockORM.id)) is None  # No seed/repair.


@pytest.mark.parametrize("sql_auth", [False, True], ids=["memory-auth", "sql-auth"])
def test_pg_actual_job_cannot_publish_after_confirmed_hash_barrier(box, monkeypatch, sql_auth):
    if box.engine is None or box.engine.dialect.name != "postgresql":
        pytest.skip("Native independent PostgreSQL sessions required")
    _, plan = setup_subject(box, monkeypatch, sql_auth=sql_auth, historical=True)
    auth._user_store.update("manager", {"portfolio_access": "all", "portfolio_ids": []})
    held, release = Event(), Event()
    observed_account_contention, refreshed_after_commit = Event(), Event()
    original = privacy._plan
    def pause_after_hash(graph):
        result = original(graph)
        if current_thread().name.startswith("profile-hash-barrier"):
            held.set()
            assert release.wait(15)
        return result
    def bounded_native_writer(connection):
        if current_thread().name.startswith("job-after-hash"):
            connection.exec_driver_sql("SET LOCAL lock_timeout='1s'")
    def write():
        with Session(box.engine) as session:
            return jobs.create_job(SQLAlchemyStore(session), JobCreate(
                idempotency_key="late-job-subject-facts", as_of="2026-11-05"), "manager")
    if not sql_auth:
        native_read = auth._user_store.get_by_id
        def observe_native_account_read(identifier):
            first_job_read = current_thread().name.startswith("job-after-hash") and not observed_account_contention.is_set()
            if first_job_read:
                # Actual failed acquisition proves the native reader is fenced;
                # a Future timeout alone would not be evidence of any lock.
                acquired = auth._user_store._lock.acquire(blocking=False)
                if acquired:
                    auth._user_store._lock.release()
                assert not acquired
                observed_account_contention.set()
            value = native_read(identifier)
            if first_job_read:
                with Session(box.engine) as session:
                    assert session.scalar(select(TenantORM.archived).where(TenantORM.id == box.previous.tenant_id))
                refreshed_after_commit.set()
            return value
        monkeypatch.setattr(auth, "get_user_by_id", observe_native_account_read)
    monkeypatch.setattr(privacy, "_plan", pause_after_hash)
    event.listen(box.engine, "begin", bounded_native_writer)
    from sqlalchemy.exc import OperationalError
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="profile-hash-barrier") as profile_pool:
            profile = profile_pool.submit(confirm, box, plan)
            try:
                assert held.wait(10)
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="job-after-hash") as job_pool:
                    writer = job_pool.submit(write)
                    if sql_auth:
                        with pytest.raises(OperationalError) as busy:
                            writer.result(timeout=10)
                        assert getattr(busy.value.orig, "pgcode", None) == "55P03"
                    else:
                        assert observed_account_contention.wait(10)
                        release.set()
                        assert writer.result(timeout=10)["state"] == "queued"
                        assert refreshed_after_commit.is_set()
            finally:
                release.set()
            assert profile.result(timeout=10)["status"] == "profile_anonymized"
    finally:
        release.set()
        event.remove(box.engine, "begin", bounded_native_writer)
    with box.engine.connect() as connection:
        if sql_auth:
            for model in JOB_MODELS:
                assert connection.scalar(select(model.id)) is None
        else:
            assert connection.scalar(select(JOB_MODELS[0].id)) is not None
            assert connection.scalar(select(JOB_MODELS[1].id)) is not None
            assert connection.scalar(select(JOB_MODELS[2].id)) is None
        assert (connection.scalar(select(OperationalLockORM.id)) is None) == sql_auth


@pytest.mark.parametrize("lock_kind", ["account", "operational", "domain"])
def test_memory_busy_fence_is_before_staging_and_leaves_profile_and_journal_untouched(box, monkeypatch, lock_kind):
    if box.engine is not None:
        pytest.skip("Actual Memory locks required")
    _, plan = setup_subject(box, monkeypatch, historical=True)
    before = privacy._memory_state(deepcopy(box.store.__dict__))
    lock = {"account": auth._user_store._lock, "operational": _state_lock, "domain": _memory_lock}[lock_kind]
    held, release = Event(), Event()
    def hold():
        with lock:
            held.set()
            assert release.wait(10)
    monkeypatch.setattr(privacy, "_memory_copy", lambda _: pytest.fail("Busy fence entered staged-copy boundary"))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(hold)
        try:
            assert held.wait(5)
            with pytest.raises(privacy.PrivacyConflict, match="erneut versuchen"):
                confirm(box, plan)
            assert privacy._memory_state(box.store.__dict__) == before
        finally:
            release.set()
        future.result(timeout=5)


@pytest.mark.parametrize("family", [JOB_MODELS, TENANCY_WORKFLOW_MODELS, OPERATIONAL_FAMILY], ids=["jobs", "workflow", "operational"])
def test_partial_family_refuses_before_profile_dml_without_repair(box, monkeypatch, family):
    if box.engine is not None and box.engine.dialect.name != "sqlite":
        pytest.skip("Disposable Memory/SQLite partial-schema fixture")
    _, plan = setup_subject(box, monkeypatch, historical=True)
    if box.engine is None:
        if family in (OPERATIONAL_FAMILY, JOB_MODELS):
            pytest.skip("Memory operational/job collections are lazy data, not SQL table schema")
        # Real Memory writers initialize whole dynamic families.
        for model in family:
            box.store.__dict__.setdefault(model.__tablename__, {})
        del box.store.__dict__[family[-1].__tablename__]
        before = privacy._memory_state(deepcopy(box.store.__dict__))
        with pytest.raises(privacy.PrivacyConflict, match="Unvollständige"):
            confirm(box, plan)
        assert privacy._memory_state(box.store.__dict__) == before
    else:
        box.db.rollback()
        with box.engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.exec_driver_sql('DROP TABLE "' + family[-1].__tablename__ + '"')
        with no_profile_dml(box) as writes:
            with pytest.raises(privacy.PrivacyConflict, match="Unvollständige"):
                confirm(box, plan)
            assert writes == []
        from sqlalchemy import inspect
        assert family[-1].__tablename__ not in inspect(box.engine).get_table_names()


def test_wholly_absent_legacy_families_are_allowed_without_bootstrap(box, monkeypatch):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    families = (*JOB_MODELS, *TENANCY_WORKFLOW_MODELS, *OPERATIONAL_FAMILY)
    if box.engine is not None:
        complete_domain_test_schema(box)
        box.db.rollback()
        with box.engine.begin() as connection:
            for group in (JOB_MODELS, TENANCY_WORKFLOW_MODELS, OPERATIONAL_FAMILY):
                for model in reversed(group):
                    model.__table__.drop(connection)
    else:
        for model in families:
            box.store.__dict__.pop(model.__tablename__, None)
    plan = privacy.preview_tenant_anonymization(box.store, box.previous.tenant_id)
    assert confirm(box, plan)["status"] == "profile_anonymized"
    if box.engine is not None:
        from sqlalchemy import inspect
        names = inspect(box.engine).get_table_names()
    else:
        names = box.store.__dict__
    assert all(model.__tablename__ not in names for model in families)


def test_frozen_subject_in_hidden_portfolio_is_denied_without_mutating_profile(box, monkeypatch):
    _, plan = setup_subject(box, monkeypatch, historical=True)
    # Scope now includes only the unrelated portfolio; the current old tenant
    # contract no longer reveals the frozen party, so the parent check matters.
    actor = dict(box.users["manager"], portfolio_ids=[box.foreign_portfolio.id])
    monkeypatch.setattr(auth, "get_user_by_id", lambda _: actor)
    with scope_context(scope_from_user(actor)), pytest.raises(HTTPException) as failure:
        confirm(box, plan)
    assert failure.value.status_code == 403
    assert not box.store.get_tenant(box.previous.tenant_id).archived


def test_existing_outer_atomic_rollback_publishes_neither_profile_nor_journal_change(box, monkeypatch):
    _, plan = setup_subject(box, monkeypatch, historical=True)
    before = journal(box)
    original = privacy._scoped_graph
    def fail_after_plan_read(store, tenant_id):
        original(store, tenant_id)
        if hasattr(store, "db"):
            assert store.db.in_transaction()
        raise RuntimeError("Synthetic failure within existing atomic transaction")
    monkeypatch.setattr(privacy, "_scoped_graph", fail_after_plan_read)
    with pytest.raises(RuntimeError, match="Synthetic failure"):
        confirm(box, plan)
    assert not box.store.get_tenant(box.previous.tenant_id).archived
    assert journal(box) == before


def test_memory_actual_operational_schedule_is_retained_without_spurious_conflict(box, monkeypatch):
    if box.engine is not None:
        pytest.skip("Real Memory operational state required")
    setup_subject(box, monkeypatch, historical=True)
    from backend.services import operational_schedule as operation
    task = box.store.create_task(TaskCreate(title="Synthetic recurring maintenance", due_date=date(2026, 1, 1)))
    with operation._transaction(box.store) as tx:
        schedule = tx.schedule("task", task.id, date(2026, 1, 1), "FREQ=MONTHLY")
        tx.record(schedule.id, date(2026, 1, 1), "task", task.id)
    before = privacy._memory_state(deepcopy(box.store._operational_state))
    plan = privacy.preview_tenant_anonymization(box.store, box.previous.tenant_id)
    assert confirm(box, plan)["status"] == "profile_anonymized"
    assert privacy._memory_state(box.store._operational_state) == before
    assert box.store.get_task(task.id).title == "Synthetic recurring maintenance"


def test_memory_real_queued_job_with_lazy_work_items_is_retained(box, monkeypatch):
    if box.engine is not None:
        pytest.skip("Real Memory lazy job collections required")
    setup_subject(box, monkeypatch, historical=True)
    auth._user_store.update("manager", {"portfolio_access": "all", "portfolio_ids": []})
    job = jobs.create_job(box.store, JobCreate(idempotency_key="retained-lazy-memory-job", as_of="2026-11-05"), "manager")
    assert JOB_MODELS[-1].__tablename__ not in box.store.__dict__
    before = journal(box)
    plan = privacy.preview_tenant_anonymization(box.store, box.previous.tenant_id)
    assert confirm(box, plan)["status"] == "profile_anonymized"
    assert journal(box) == before
    assert jobs.read_job(box.store, job["id"], "manager")["state"] == "queued"


def test_memory_operational_normalization_still_detects_actual_concurrent_state_change(box, monkeypatch):
    if box.engine is not None:
        pytest.skip("Real Memory operational state required")
    setup_subject(box, monkeypatch, historical=True)
    from backend.services import operational_schedule as operation
    task = box.store.create_task(TaskCreate(title="Synthetic recurring maintenance", due_date=date(2026, 1, 1)))
    with operation._transaction(box.store) as tx:
        schedule = tx.schedule("task", task.id, date(2026, 1, 1), "FREQ=MONTHLY")
    with pytest.raises(privacy.PrivacyConflict, match="während der Anonymisierung geändert"):
        with privacy._privacy_write(box.store) as staged:
            # Real reentrant write to the live store after its staged snapshot:
            # conflict detection must protect that update, not overwrite it.
            with operation._transaction(box.store) as tx:
                tx.schedule("task", task.id, date(2026, 1, 1), "FREQ=WEEKLY")
            staged._patch_entity("tenant", box.previous.tenant_id, TenantPatch(archived=True))
    assert box.store._operational_state["schedules"][schedule.id].recurrence_rule == "FREQ=WEEKLY"
    assert not box.store.get_tenant(box.previous.tenant_id).archived


def test_sqlite_memory_auth_allows_existing_writer_to_finish_before_confirmation(box, monkeypatch):
    if box.engine is None or box.engine.dialect.name != "sqlite":
        pytest.skip("Actual SQLite/Memory-auth transaction ordering required")
    change, plan = setup_subject(box, monkeypatch, historical=True)
    original_tenant = box.store.get_tenant(box.previous.tenant_id).model_dump()
    writer_held, release_writer, profile_begin, account_available = Event(), Event(), Event(), Event()
    original_touch = workflow._touch_step
    def pause_writer(unit, item):
        original_touch(unit, item)
        writer_held.set()
        assert release_writer.wait(10)
        available = auth._user_store._lock.acquire(blocking=False)
        if available:
            auth._user_store._lock.release()
        assert available, "Privacy holds the account mutex while waiting for this SQLite writer"
        account_available.set()
    def observe_begin(_connection, _cursor, statement, _params, _context, _many):
        if current_thread().name.startswith("sqlite-profile") and statement == "BEGIN IMMEDIATE":
            profile_begin.set()
            release_writer.set()
    monkeypatch.setattr(workflow, "_touch_step", pause_writer)
    item = change["steps"][0]
    def write():
        with Session(box.engine) as session:
            return workflow.update_step(SQLAlchemyStore(session), change["id"], item["id"], UpdateStep(
                idempotency_key="sqlite-existing-writer", expected_revision=item["revision"],
                expected_change_revision=change["revision"], state="in_progress"), "tech")
    event.listen(box.engine, "before_cursor_execute", observe_begin)
    try:
        with ThreadPoolExecutor(max_workers=1) as writers, ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite-profile") as profiles:
            writer = writers.submit(write)
            try:
                assert writer_held.wait(10)
                profile = profiles.submit(confirm, box, plan)
                assert profile_begin.wait(10)
                assert writer.result(timeout=10)["state"] == "in_progress"
                assert account_available.is_set()
                # The writer changed retained evidence after the reviewed
                # graph was captured. Account/DB lock ordering permits it to
                # finish; the stale confirmation must then refuse publication.
                with pytest.raises(privacy.PrivacyConflict, match="Datenstand"):
                    profile.result(timeout=10)
                assert box.store.get_tenant(box.previous.tenant_id).model_dump() == original_tenant
                current = workflow.get_change(box.store, change["id"], "tech")
                assert current["steps"][0]["state"] == "in_progress"
            finally:
                release_writer.set()
    finally:
        release_writer.set()
        event.remove(box.engine, "before_cursor_execute", observe_begin)

    fresh = privacy.preview_tenant_anonymization(box.store, box.previous.tenant_id)
    assert fresh["plan_hash"] != plan["plan_hash"]
    assert confirm(box, fresh)["status"] == "profile_anonymized"


def test_sqlite_memory_account_fence_is_held_until_actual_outer_publication(box, monkeypatch):
    if box.engine is None or box.engine.dialect.name != "sqlite":
        pytest.skip("Actual SQLite outer-commit barrier required")
    _, plan = setup_subject(box, monkeypatch)
    held, release, contended, observed_published = Event(), Event(), Event(), Event()
    native_update = auth._user_store.update
    def before_real_commit(_connection):
        if current_thread().name.startswith("profile-outer-commit"):
            held.set()
            assert release.wait(15)
    def management():
        available = auth._user_store._lock.acquire(blocking=False)
        if available:
            auth._user_store._lock.release()
        assert not available, "Account management slipped into the outer SQL commit window"
        contended.set()
        value = native_update("manager", {"is_active": False, "portfolio_access": "all", "portfolio_ids": []})
        with Session(box.engine) as session:
            assert session.scalar(select(TenantORM.archived).where(TenantORM.id == box.previous.tenant_id))
        observed_published.set()
        return value
    captured = scope_from_user(auth._user_store.get_by_id("manager"))
    def profile():
        with scope_context(captured):
            return confirm(box, plan)
    event.listen(box.engine, "commit", before_real_commit)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="profile-outer-commit") as profiles:
            result = profiles.submit(profile)
            try:
                assert held.wait(10)
                with ThreadPoolExecutor(max_workers=1) as managers:
                    update = managers.submit(management)
                    try:
                        assert contended.wait(10)
                    finally:
                        release.set()
                    assert update.result(timeout=10)["is_active"] is False
            finally:
                release.set()
            assert result.result(timeout=10)["status"] == "profile_anonymized"
            assert observed_published.is_set()
    finally:
        release.set()
        event.remove(box.engine, "commit", before_real_commit)
