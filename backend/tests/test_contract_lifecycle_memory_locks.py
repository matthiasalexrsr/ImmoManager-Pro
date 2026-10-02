"""Real account locks and real memory commands cannot invert privacy ordering."""

import multiprocessing
from datetime import date, timedelta
from queue import Empty
from threading import Event, Thread, current_thread
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend import auth, dependencies
from backend.models import ContractCreate, PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.services import contract_lifecycle as lifecycle
from backend.services.contract_lifecycle_types import Confirmation, DraftCreate, RevisionCommand
from backend.services.tenant_privacy import _memory_copy, _memory_privacy_lock
from backend.storage import InMemoryStore, NotFoundError

PASSWORD = "Synthetic-lock-review-passphrase-123!"


def real_memory_state():
    auth._user_store = auth.InMemoryUserStore()
    auth._auth_session_factory = None
    owner = auth.register_user("lock-owner", "lock-owner@example.test", "Synthetic owner", PASSWORD,
        "eigentuemer", portfolio_access="all")
    reader = auth.register_user("lock-reader", "lock-reader@example.test", "Synthetic reader", PASSWORD,
        "readonly", portfolio_access="all", actor_id=owner.id)
    store = InMemoryStore()
    # Auth grant validation reads the real configured domain store. Bind the
    # same owned synthetic installation, rather than bypassing grant checks.
    dependencies.store = store
    portfolio = store.create_portfolio(PortfolioCreate(name="Synthetic portfolio"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Synthetic property", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="A", unit_type="apartment"))
    tenant = store.create_tenant(TenantCreate(full_name="Synthetic tenant"))
    contract = store.create_contract(ContractCreate(contract_number="Synthetic parent", property_id=prop.id,
        unit_id=unit.id, tenant_id=tenant.id, start_date=date.today() - timedelta(days=90),
        end_date=date.today() + timedelta(days=90)))
    actor = auth.register_user("lock-manager", "lock-manager@example.test", "Synthetic manager", PASSWORD,
        "verwalter", portfolio_access="selected", portfolio_ids=[portfolio.id], actor_id=owner.id)
    payload = DraftCreate(idempotency_key="create", expected_contract_etag=lifecycle.contract_etag(contract),
        data={"operation": "termination", "reason": "Explicit synthetic review",
              "termination_end_date": date.today() + timedelta(days=30)})
    return SimpleNamespace(store=store, owner=owner, actor=actor, reader=reader, contract=contract, payload=payload)


def reviewed(box):
    created = lifecycle.create_draft(box.store, box.contract.id, box.payload, box.actor.id)
    payload = RevisionCommand(idempotency_key="review", expected_revision=created["revision"],
        expected_contract_etag=created["source_contract_etag"])
    return lifecycle.review_draft(box.store, box.contract.id, created["id"], payload, box.actor.id)


def concurrent_privacy_probe(operation, output):
    """Child process keeps a red deadlock from poisoning pytest's global locks.

    The observation wrapper delegates to the actual InMemoryUserStore RLock;
    authentication, commands, snapshots and scope refresh are unmocked.
    """
    box = real_memory_state()
    selected = reviewed(box) if operation == "confirm" else None
    confirmation = Confirmation(idempotency_key="confirm", expected_revision=selected["revision"],
        expected_contract_etag=selected["source_contract_etag"], reviewed_hash=selected["review_hash"],
        confirmed=True) if selected else None
    recorded, privacy_attempted, privacy_account, published, copied = [Event() for _ in range(5)]
    actual_lock = auth._user_store._lock
    original_record = lifecycle._record
    failures, results = [], []

    class ObserveAccountLock:
        def __enter__(self):
            if current_thread().name == "synthetic-privacy":
                privacy_attempted.set()
            actual_lock.acquire()
            if current_thread().name == "synthetic-privacy":
                privacy_account.set()
            return self

        def __exit__(self, *_):
            actual_lock.release()

    auth._user_store._lock = ObserveAccountLock()

    def hold_after_record(*args, **kwargs):
        result = original_record(*args, **kwargs)
        if current_thread().name == "synthetic-publisher":
            recorded.set()
            if not privacy_attempted.wait(3):
                raise AssertionError("Privacy thread never attempted the account lock")
            # Old code lets privacy own account while publisher owns domain.
            # Correct ordering keeps privacy outside account until this command
            # finishes; this event is an observation, never an injected release.
            privacy_account.wait(.25)
        return result

    lifecycle._record = hold_after_record

    def publish():
        try:
            result = lifecycle.confirm_draft(box.store, box.contract.id, selected["id"], confirmation, box.actor.id) if selected else (
                lifecycle.create_draft(box.store, box.contract.id, box.payload, box.actor.id))
            results.append(result)
            published.set()
        except BaseException as error:
            failures.append(type(error).__name__)

    def privacy():
        try:
            if not recorded.wait(3):
                raise AssertionError("No command was recorded")
            with _memory_privacy_lock():
                snapshot = _memory_copy(box.store)
                assert len(snapshot.contract_lifecycle_commands) == (3 if selected else 1)
            copied.set()
        except BaseException as error:
            failures.append(type(error).__name__)

    publisher = Thread(target=publish, name="synthetic-publisher", daemon=True)
    reader = Thread(target=privacy, name="synthetic-privacy", daemon=True)
    publisher.start()
    reader.start()
    publisher.join(4)
    reader.join(.5)
    replay_equal = False
    if published.is_set() and copied.is_set():
        lifecycle._record = original_record
        replay = lifecycle.confirm_draft(box.store, box.contract.id, selected["id"], confirmation, box.actor.id) if selected else (
            lifecycle.create_draft(box.store, box.contract.id, box.payload, box.actor.id))
        replay_equal = replay == results[0]
    output.put({"published": published.is_set(), "copied": copied.is_set(), "replay_equal": replay_equal,
                "failures": failures, "commands": len(box.store.contract_lifecycle_commands)})


@pytest.mark.parametrize("operation", ["create", "confirm"])
def test_real_auth_lifecycle_and_privacy_finish_without_account_domain_deadlock(monkeypatch, operation):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("TEST_STORE_BACKEND", "memory")
    monkeypatch.setenv("SQLITE_PERSISTENT_STORE", "false")
    monkeypatch.setenv("ALLOW_INMEMORY_FALLBACK", "true")
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    process = context.Process(target=concurrent_privacy_probe, args=(operation, output))
    try:
        process.start()
        process.join(12)
        assert not process.is_alive(), "Owned memory lock probe exceeded its process deadline"
        assert process.exitcode == 0
        try:
            result = output.get(timeout=2)
        except Empty:
            pytest.fail("Owned probe returned no lock evidence")
        assert result == {"published": True, "copied": True, "replay_equal": True,
                          "failures": [], "commands": 3 if operation == "confirm" else 1}
    finally:
        if process.is_alive():
            process.terminate()
            process.join(3)
        output.close()
        output.join_thread()


@pytest.fixture
def real_auth(monkeypatch):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    monkeypatch.setattr(dependencies, "store", dependencies.store)
    return real_memory_state()


def test_real_current_role_denial_preserves_private_journal_and_releases_both_locks(real_auth):
    box = real_auth
    row = lifecycle.create_draft(box.store, box.contract.id, box.payload, box.actor.id)
    with pytest.raises(HTTPException) as failure:
        lifecycle.get_draft(box.store, box.contract.id, row["id"], box.reader.id)
    assert failure.value.status_code == 404
    with pytest.raises(HTTPException) as failure:
        lifecycle.create_draft(box.store, box.contract.id, box.payload, box.reader.id)
    assert failure.value.status_code == 403
    auth._user_store.update(box.actor.id, {"portfolio_access": "selected", "portfolio_ids": []}, actor_id=box.owner.id)
    with pytest.raises(NotFoundError):
        lifecycle.get_draft(box.store, box.contract.id, row["id"], box.actor.id)
    assert len(box.store.contract_lifecycle_commands) == 1
    with _memory_privacy_lock():
        assert _memory_copy(box.store).contract_lifecycle_drafts[row["id"]].actor_id == box.actor.id


def test_real_auth_exception_rolls_back_touched_rows_before_privacy_can_snapshot(real_auth, monkeypatch):
    box = real_auth
    row = reviewed(box)
    original_record = lifecycle._record

    def fail_after_record(*args, **kwargs):
        original_record(*args, **kwargs)
        raise RuntimeError("Synthetic failure after actual command insert")

    monkeypatch.setattr(lifecycle, "_record", fail_after_record)
    payload = Confirmation(idempotency_key="confirm-failure", expected_revision=row["revision"],
        expected_contract_etag=row["source_contract_etag"], reviewed_hash=row["review_hash"], confirmed=True)
    with pytest.raises(RuntimeError, match="Synthetic failure"):
        lifecycle.confirm_draft(box.store, box.contract.id, row["id"], payload, box.actor.id)
    assert box.store.get_contract(box.contract.id).end_date == box.contract.end_date
    with _memory_privacy_lock():
        snapshot = _memory_copy(box.store)
        assert snapshot.contract_lifecycle_drafts[row["id"]].state == "reviewed"
        assert len(snapshot.contract_lifecycle_commands) == 2
