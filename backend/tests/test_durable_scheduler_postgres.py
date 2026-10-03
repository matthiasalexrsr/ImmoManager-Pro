"""Native PostgreSQL scheduler crashes and independent-worker coordination."""
# ruff: noqa: F811

import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier

import pytest
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.db.operational_job_models import OperationalJobORM
from backend.db.operational_models import OperationalOccurrenceORM
from backend.db.operational_scheduler_models import OperationalSchedulerORM
from backend.models import TaskCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import operational_jobs as jobs
from backend.services import operational_scheduler as scheduler
from backend.services.operational_job_types import FAMILIES, JobCreate
from backend.services.operational_job_validation import validate_job_journal
from backend.services.operational_scheduler_validation import reset_scheduler_claims, validate_scheduler
from backend.tests.test_private_server_concurrency import postgres_database as postgres_database

PARAMETERS = {"max_items": 7, "lookback_days": 30000, "interval_seconds": 300, "full_catch_up": True}


@pytest.fixture
def installed(postgres_database, monkeypatch):
    engine, factory, source, schema = postgres_database
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    actor = auth.register_user("scheduler-owner", "scheduler@example.invalid", "Synthetic scheduler",
                               "Synthetic Scheduler Passphrase 2026", "eigentuemer")
    with factory() as db:
        task = SQLAlchemyStore(db).create_task(TaskCreate(title="Persistent source", due_date=date(2026, 1, 1),
                                                        recurrence_rule="FREQ=DAILY;COUNT=25"))
    return engine, factory, source, schema, actor.id, task.id


def _crash_worker(source, schema, actor_id, phase):
    engine = create_engine(source, connect_args={"options": "-csearch_path=" + schema}, hide_parameters=True)
    factory = sessionmaker(bind=engine)
    auth._user_store, auth._auth_session_factory = auth.SQLUserStore(factory), factory
    with factory() as db:
        store = SQLAlchemyStore(db)
        claim = scheduler.reserve(store, actor_id, PARAMETERS)
        if phase == "reserved":
            os._exit(17)
        created = jobs.create_job(store, JobCreate(idempotency_key="automatic:" + claim.generation_key,
            as_of=claim.as_of, families=FAMILIES, lookback_days=30000, full_catch_up=True), actor_id)
        if phase == "created":
            os._exit(17)
        scheduler.attach(store, claim, created["id"])
        from backend.services.operational_job_types import JobContinue
        for _ in range(12):
            jobs.continue_job(store, created["id"], JobContinue(max_items=7), actor_id)
            if db.scalar(select(func.count()).select_from(OperationalOccurrenceORM)) > 0:
                os._exit(17)
        os._exit(18)


@pytest.mark.parametrize("phase", ["reserved", "created", "packet"])
def test_postgres_killed_process_recovers_reserved_job_and_committed_packets(installed, phase):
    engine, factory, source, schema, actor_id, task_id = installed
    process = multiprocessing.get_context("spawn").Process(target=_crash_worker, args=(source, schema, actor_id, phase))
    process.start()
    process.join(timeout=45)
    if process.is_alive():
        process.terminate()
        process.join(timeout=10)
        pytest.fail("Owned crash worker did not reach the planned crash")
    assert process.exitcode == 17
    with factory() as db:
        before = db.get(OperationalSchedulerORM, "automatic")
        generation, key = before.generation, before.generation_key
        created = db.scalar(select(OperationalJobORM.id))
        if phase == "packet":
            assert db.scalar(select(func.count()).select_from(OperationalOccurrenceORM)) > 0
    with engine.begin() as connection:
        connection.execute(update(OperationalSchedulerORM).values(lease_expires_at=jobs._clock() - timedelta(seconds=1)))
    with factory() as db:
        store = SQLAlchemyStore(db)
        for _ in range(30):
            result = scheduler.advance(store, actor_id, PARAMETERS)
            if result["state"] == "completed":
                break
        assert result["state"] == "completed"
        state = db.get(OperationalSchedulerORM, "automatic")
        assert (state.generation, state.generation_key) == (generation, key)
        if created:
            assert result["job_id"] == created
        assert db.scalar(select(func.count()).select_from(OperationalJobORM)) == 1
        assert db.scalar(select(func.count()).select_from(OperationalOccurrenceORM).where(
            OperationalOccurrenceORM.schedule_id == "task:" + task_id)) == 25
    with engine.connect() as connection:
        assert validate_job_journal(connection) and validate_scheduler(connection)


def test_postgres_parallel_workers_finish_once_and_offline_reset_rolls_back(installed):
    engine, factory, _, _, actor_id, task_id = installed
    barrier = Barrier(2)
    def worker(index):
        with factory() as db:
            store = SQLAlchemyStore(db)
            barrier.wait(timeout=10)
            for _ in range(40):
                result = scheduler.advance(store, actor_id, PARAMETERS, worker_id="scheduler-" + str(index))
                if result["state"] == "completed":
                    return
            pytest.fail("Parallel scheduler failed to finish")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, range(2)))
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(OperationalJobORM)) == 1
        assert db.scalar(select(func.count()).select_from(OperationalOccurrenceORM).where(
            OperationalOccurrenceORM.schedule_id == "task:" + task_id)) == 25
        before = db.get(OperationalSchedulerORM, "automatic").fence
    with engine.connect() as connection:
        transaction = connection.begin()
        assert reset_scheduler_claims(connection) == 1
        transaction.rollback()
    with factory() as db:
        assert db.get(OperationalSchedulerORM, "automatic").fence == before
