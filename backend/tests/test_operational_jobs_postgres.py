"""Optional genuine PostgreSQL gate; no PostgreSQL success without a service."""
# ruff: noqa: F811

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier

import pytest
from sqlalchemy import event, text, update
from sqlalchemy.exc import DBAPIError

from backend import auth
from backend.db.operational_job_models import (
    OperationalJobLaneORM,
    OperationalJobORM,
    OperationalWorkItemORM,
    ensure_operational_job_schema,
)
from backend.db.operational_models import OperationalLockORM
from backend.models import RentChargeCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import operational_jobs as service
from backend.services.auth_sessions import login_pair
from backend.services.operational_job_types import JobCommand, JobContinue, JobCreate, PacketPolicy
from backend.services.operational_job_validation import reset_restored_job_claims, validate_job_journal
from backend.services.operational_schedule import ensure_operational_schema
from backend.tests.test_payments import seed
from backend.tests.test_private_server_concurrency import postgres_database as postgres_database


@pytest.fixture
def installation(postgres_database, monkeypatch):
    engine, factory, _, _ = postgres_database
    with engine.begin() as connection:
        ensure_operational_schema(connection)
        ensure_operational_job_schema(connection)
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    actor = auth.register_user("packet-owner", "packet@example.invalid", "Synthetic owner", "Synthetic Packet Passphrase 2026", "eigentuemer")
    with factory() as db:
        store = SQLAlchemyStore(db)
        initial = seed(store, "rent_charge")
        contract = store.get_contract(initial.contract_id)
        for index in range(19):
            store.create_rent_charge(RentChargeCreate(contract_id=contract.id, month=f"{2020 + index // 12}-{index % 12 + 1:02}", cold_rent=100, status="open"))
        job = service.create_job(store, JobCreate(idempotency_key="pg-job" * 1000, as_of=date(2026, 11, 5), families=("overdue_rent_charge",)), actor.id)
    return engine, factory, actor, job


def test_pg_independent_sessions_publish_once_and_stale_fence_is_rejected(installation):
    engine, factory, actor, job = installation
    large = 2 ** 31 + 1
    with engine.begin() as connection:
        connection.execute(update(OperationalJobORM).where(OperationalJobORM.id == job["id"]).values(revision=large, turn=large))
        connection.execute(update(OperationalJobLaneORM).where(OperationalJobLaneORM.job_id == job["id"])
                           .values(fence=large, served=large, scanned=3 * large, created=large, updated=large, skipped=large))
        connection.execute(update(OperationalLockORM).values(generation=2 ** 31 - 1))
    with factory() as db:
        store = SQLAlchemyStore(db)
        old = service.claim_lane(store, job["id"], "old", actor_id=actor.id)
        service.prepare_claim(store, old, JobContinue(max_items=3))
    with engine.begin() as connection:
        connection.execute(update(OperationalWorkItemORM).where(OperationalWorkItemORM.lane_id == old.lane_id).values(revision=large, attempts=large))
    with engine.begin() as connection:
        connection.execute(update(OperationalJobLaneORM).where(OperationalJobLaneORM.id == old.lane_id)
                           .values(lease_expires_at=service._clock() - timedelta(seconds=1)))
    with factory() as db:
        store = SQLAlchemyStore(db)
        replacement = service.claim_lane(store, job["id"], "new", actor_id=actor.id)
        assert replacement.fence > old.fence > large
        with pytest.raises(service.ClaimLost):
            service.run_claim(store, old, JobContinue(max_items=3))
        service.run_claim(store, replacement, JobContinue(max_items=3))
    barrier = Barrier(2)
    def worker(index):
        with factory() as db:
            barrier.wait(timeout=10)
            store = SQLAlchemyStore(db)
            for _ in range(30):
                result = service.continue_job(store, job["id"], JobContinue(max_items=3), actor.id, worker_id=f"worker-{index}")
                if result["state"] == "completed":
                    return
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, range(2)))
    with factory() as db:
        store = SQLAlchemyStore(db)
        assert len(store.list_notifications()) == 20
        done = service.read_job(store, job["id"], actor.id)
        assert done["state"] == "completed" and done["revision"] > large
        assert done["lanes"][0]["created"] == large + 20
        assert max(item["attempts"] for item in service.item_page(store, job["id"], actor_id=actor.id)["items"]) == large + 1
        assert db.get(OperationalLockORM, 1).generation == 2 ** 31 - 1
    with engine.connect() as connection:
        assert validate_job_journal(connection)
    assert engine.pool.checkedout() == 0


def test_pg_offline_claim_reset_is_transactional_and_keeps_pending_items(installation):
    engine, factory, actor, job = installation
    with factory() as db:
        store = SQLAlchemyStore(db)
        claim = service.claim_lane(store, job["id"], "before-restore", actor_id=actor.id)
        service.prepare_claim(store, claim, JobContinue(max_items=7))
    with engine.connect() as connection:
        transaction = connection.begin()
        assert validate_job_journal(connection)
        assert reset_restored_job_claims(connection) == 1
        transaction.rollback()
    with factory() as db:
        store = SQLAlchemyStore(db)
        service.run_claim(store, claim, JobContinue(max_items=7))
        latest = service.read_job(store, job["id"], actor.id)
        command = JobCommand(idempotency_key="pg-command" * 1000, expected_revision=latest["revision"])
        receipt = service.cancel_job(store, job["id"], command, actor.id)
        assert service.cancel_job(store, job["id"], command, actor.id) == receipt
        with pytest.raises(DBAPIError):
            db.execute(update(OperationalWorkItemORM).where(OperationalWorkItemORM.kind == "command").values(result={}))
            db.commit()
        db.rollback()
    with engine.begin() as connection:
        assert validate_job_journal(connection)


def test_pg_finishing_fence_uses_advancing_database_time_inside_long_transaction(installation, monkeypatch):
    engine, factory, actor, job = installation
    def non_utc_transaction(connection):
        connection.exec_driver_sql("SET LOCAL TIME ZONE 'Pacific/Honolulu'")
    event.listen(engine, "begin", non_utc_transaction)
    policy = PacketPolicy(page_size=3, lease_seconds=2, packet_seconds=0.1)
    with factory() as db:
        store = SQLAlchemyStore(db)
        claim = service.claim_lane(store, job["id"], "late-pg-worker", actor_id=actor.id, policy=policy)
        service.prepare_claim(store, claim, JobContinue(max_items=3), policy=policy)
        original = service.Unit.create
        def delay_after_effect(unit, kind, values):
            value = original(unit, kind, values)
            unit.db.execute(text("SELECT pg_sleep(2.1)"))
            return value
        with monkeypatch.context() as patch:
            patch.setattr(service.Unit, "create", delay_after_effect)
            with pytest.raises(service.ClaimLost, match="finishing fence"):
                service.run_claim(store, claim, JobContinue(max_items=3), policy=policy)
        assert store.list_notifications() == []
        assert service.item_page(store, job["id"], actor_id=actor.id)["items"]
        for _ in range(30):
            if service.continue_job(store, job["id"], JobContinue(max_items=3), actor.id)["state"] == "completed":
                break
        assert len(store.list_notifications()) == 20
    assert engine.pool.checkedout() == 0
    event.remove(engine, "begin", non_utc_transaction)


def test_pg_session_revoked_from_independent_transaction_rejects_current_packet(installation, monkeypatch):
    engine, factory, actor, job = installation
    old = login_pair(actor.id).access_token
    original = service.Unit.create
    def revoke_after_effect(unit, kind, values):
        value = original(unit, kind, values)
        auth.revoke_token(old)
        return value
    with factory() as db:
        store = SQLAlchemyStore(db)
        with service.request_token(old), monkeypatch.context() as patch:
            patch.setattr(service.Unit, "create", revoke_after_effect)
            with pytest.raises(service.HTTPException) as rejected:
                service.continue_job(store, job["id"], JobContinue(max_items=3), actor.id)
            assert rejected.value.status_code == 401
        assert store.list_notifications() == []
        fresh = login_pair(actor.id).access_token
        with service.request_token(fresh):
            current = service.read_job(store, job["id"], actor.id)
            assert current["state"] == "attention" and current["lanes"][0]["last_error"] == "actor_changed"
            service.retry_lane(store, job["id"], current["lanes"][0]["id"], JobCommand(idempotency_key="fresh-login",
                expected_revision=current["revision"]), actor.id)
            for _ in range(30):
                if service.continue_job(store, job["id"], JobContinue(max_items=3), actor.id)["state"] == "completed":
                    break
        assert len(store.list_notifications()) == 20
    assert engine.pool.checkedout() == 0
