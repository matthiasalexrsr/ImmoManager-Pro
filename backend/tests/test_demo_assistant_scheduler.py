"""Real HTTP/lifespan dispatch for the demo's local-only assistant worker."""
import importlib
import threading
import time
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend import auth, demo
from backend.assistant_models import RunCreate
from backend.config import settings
from backend.dependencies import store
from backend.services import assistant, assistant_providers
from backend.services import assistant_storage as db
from backend.services.jobs import scheduler
from backend.services.jobs.core import JobStore, MemoryJobStore, SqlJobStore
from backend.tests.test_assistant_workspace import clean as clean  # noqa: F401
from backend.tests.test_assistant_workspace import command, conversation

app_module = importlib.import_module("backend.app")


@pytest.fixture
def worker_client(monkeypatch):
    from backend import dependencies

    for name, rows in store.__dict__.get("_integration_connections", {}).items():
        if name.startswith("assistant_"):
            rows.clear()
    jobs: JobStore
    if dependencies._scoped_session is None:
        jobs = MemoryJobStore()
    else:
        from backend.db.session import engine
        jobs = SqlJobStore(engine)
    monkeypatch.setattr(scheduler, "get_job_store", lambda: jobs)
    monkeypatch.setattr(settings, "immo_demo", True)
    monkeypatch.setattr(settings, "job_scheduler_enabled", False)
    monkeypatch.setattr(settings, "job_scheduler_interval_seconds", 3600)
    # The independent demo workspace suite verifies the irreversible process
    # network hook and seeding. This suite owns only isolated fixtures and the
    # production lifecycle/HTTP worker, without changing the test process hook.
    monkeypatch.setattr(demo, "install_backend_guards", lambda: None)
    monkeypatch.setattr(demo, "seed_demo", lambda app: False)
    monkeypatch.setattr(app_module, "ensure_runtime_dirs", lambda: None)
    monkeypatch.setattr(app_module, "_validate_startup_config", lambda: None)

    def forbidden(*args, **kwargs):
        pytest.fail("The demo assistant worker must not dispatch general jobs or cloud adapters")

    monkeypatch.setattr(scheduler, "enqueue_due", forbidden)
    monkeypatch.setattr(assistant_providers, "executable", forbidden)
    monkeypatch.setattr(assistant_providers, "_adapter", forbidden)
    actor = auth.register_user("worker-demo", "worker-demo@example.test", "Lokaler Demotest", "Secret123", "readonly")
    outer = FastAPI(lifespan=app_module.lifespan)

    @outer.middleware("http")
    async def outbound_guard(request, call_next):
        if demo.blocked_action(request.method, request.url.path):
            return JSONResponse(status_code=409, content={"code": "DEMO_EXTERNAL_ACTION_DISABLED"})
        return await call_next(request)

    outer.mount("/", app_module.app)
    yield actor, jobs, TestClient(outer, headers={"Authorization": "Bearer " + auth.create_access_token(actor.id)})
    assert not scheduler._wakeups, "The demo worker must unregister its shutdown callback"
    for name, rows in store.__dict__.get("_integration_connections", {}).items():
        if name.startswith("assistant_"):
            rows.clear()


def status_until(client, identifier, state, timeout=5):
    deadline = time.monotonic() + timeout
    while True:
        result = client.get('/api/v1/assistant/runs/' + identifier)
        assert result.status_code == 200, result.text
        data = result.json()
        if data["state"] == state:
            return data
        assert time.monotonic() < deadline, data
        time.sleep(0.02)


def test_demo_lifespan_wakes_http_submit_cancel_retry_without_general_scheduler(worker_client, monkeypatch):
    actor, jobs, client = worker_client
    chat = conversation(actor)
    entered, release = threading.Event(), threading.Event()
    original = assistant_providers._local_answer
    calls = []

    def held_local_answer(request):
        calls.append(request["run_id"])
        entered.set()
        assert release.wait(5), "Test must release the local analysis"
        return original(request)

    monkeypatch.setattr(assistant_providers, "_local_answer", held_local_answer)
    with client:
        try:
            result = client.post(f'/api/v1/assistant/conversations/{chat["id"]}/runs',
                json=command(expected_revision=chat["revision"], content="Lokal prüfen"))
            assert result.status_code == 200, result.text
            first = result.json()
            assert entered.wait(3), "The demo must wake the local worker without waiting an hour"
            current = status_until(client, first["id"], "running")
            cancelled = client.post(f'/api/v1/assistant/runs/{first["id"]}/cancel',
                json=command(expected_revision=current["revision"]))
            assert cancelled.status_code == 200, cancelled.text
            release.set()
            retry = client.post(f'/api/v1/assistant/runs/{first["id"]}/retry',
                json=command(expected_revision=cancelled.json()["revision"]))
            assert retry.status_code == 200, retry.text
            final = status_until(client, retry.json()["id"], "completed")
            assert final["response"] and final["provider"] == "local"
            assert calls == [first["id"], retry.json()["id"]]
            assert all(job.kind == "assistant.run" for job in jobs.list_runs())
        finally:
            release.set()
    assert not scheduler._wakeups


@pytest.mark.parametrize("legacy", ["local", "run-external", "conversation-external"])
def test_demo_lifespan_recovers_local_queue_and_blocks_persisted_external_provider(worker_client, monkeypatch, legacy):
    actor, jobs, client = worker_client
    chat = conversation(actor)
    # Model an interrupted prior process whose queued assistant row committed
    # before the best-effort durable-job wakeup. No direct runner call is used.
    with monkeypatch.context() as preparing:
        preparing.setattr(assistant, "wake", lambda *args: None)
        run = assistant.submit(store, actor.id, chat["id"], RunCreate(**command(
            expected_revision=chat["revision"], content="Nach Neustart lokal prüfen")))
    with db.work(store, actor.id, write=True) as unit:
        row = db.owned_child(unit, assistant.Run, run["id"], lock=True)
        data = db.payload(row)
        data.pop("provider", None)  # Older local rows use their stored conversation fallback.
        if legacy == "run-external":
            data["provider"] = "claude"
        elif legacy == "conversation-external":
            parent = db.conversation(unit, chat["id"], lock=True)
            parent_data = db.payload(parent)
            parent_data["provider"] = "codex"
            db.put(unit, assistant.Conversation, parent_data, row=parent)
        db.put(unit, assistant.Run, data, row=row)
    unrelated = jobs.enqueue("communication.dispatch", "unrelated-demo-job")
    expired = jobs.enqueue("communication.dispatch", "expired-unrelated-demo-job", max_attempts=1)
    claimed = [jobs.claim("old-worker", ("communication.dispatch",)) for _ in range(2)]
    assert all(row is not None for row in claimed)
    assert {row.id for row in claimed if row is not None} == {unrelated.id, expired.id}
    expired_claim = next(row for row in claimed if row is not None and row.id == expired.id)
    assert expired_claim.lease_expires_at is not None
    expired_at = expired_claim.lease_expires_at + timedelta(seconds=1)
    jobs.clock = lambda: expired_at
    assert jobs.find("assistant:" + run["id"]) is None
    with client:
        final = status_until(client, run["id"], "completed" if legacy == "local" else "blocked")
        if legacy == "local":
            assert final["response"] and final["provider"] == "local"
        assert jobs.get(unrelated.id).status == "running"
        assert jobs.get(expired.id).status == "running", "An assistant-only claim must not expire unrelated jobs"
        assert all(job.kind in {"assistant.run", "communication.dispatch"} for job in jobs.list_runs())
    assert not scheduler._wakeups
