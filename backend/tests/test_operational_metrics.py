"""Real HTTP/stream/SQL/job observations, without event or input retention."""

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from backend import auth, dependencies
from backend.app import app
from backend.db.orm_models import Base
from backend.logging_config import JSONFormatter
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import operational_metrics as router
from backend.routers import portfolios, tasks
from backend.services import operational_schedule
from backend.services.operational_metrics import OperationalMetrics, OperationalMetricsMiddleware, database_health
from backend.services.portfolio_scope import scope_context
from backend.storage import InMemoryStore

ENDPOINT = "/api/v1/admin/operational-metrics"
PRIVATE = "tenant-private@example.invalid-token-123-12345678-1234-5678-9012-123456789012"


@pytest.fixture(params=["memory", "sqlite"])
def installation(request, monkeypatch, tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "telemetry.db").as_posix(), connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    registry = scoped_session(factory, scopefunc=dependencies.session_scope_key)
    store = SQLAlchemyStore(registry) if request.param == "sqlite" else InMemoryStore()
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory) if request.param == "sqlite" else auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", factory if request.param == "sqlite" else None)
    monkeypatch.setattr(dependencies, "store", store)
    monkeypatch.setattr(portfolios, "store", store)
    monkeypatch.setattr(tasks, "store", store)
    monkeypatch.setattr(dependencies, "_scoped_session", registry if request.param == "sqlite" else None)
    collector = OperationalMetrics()
    monkeypatch.setattr(router, "metrics", collector)
    monkeypatch.setattr(operational_schedule, "metrics", collector)
    with scope_context(None):
        users = {role: auth.register_user(role, role + "@example.invalid", "Synthetic " + role, "SyntheticPass123!", role)
                 for role in ("eigentuemer", "verwalter", "readonly", "buchhaltung")}
        users["selected"] = auth.register_user("selected", "selected@example.invalid", "Synthetic", "SyntheticPass123!", "verwalter", portfolio_access="selected")
    headers = {key: {"Authorization": "Bearer " + auth.create_access_token(user.id)} for key, user in users.items()}
    # The outer collector is private to this installation. Actual application
    # auth, error handlers, RBAC, portfolio and session middleware still run.
    with TestClient(OperationalMetricsMiddleware(app, collector=collector), raise_server_exceptions=False) as client:
        yield SimpleNamespace(client=client, store=store, collector=collector, headers=headers, users=users, engine=engine)
    registry.remove()
    engine.dispose()


def test_full_application_installs_protected_route_and_outer_observation():
    assert any(middleware.cls is OperationalMetricsMiddleware for middleware in app.user_middleware)
    assert any(route.path == ENDPOINT for route in app.routes)


def test_real_auth_and_scoped_admin_access_precede_database_probe(installation, monkeypatch):
    active = installation
    probes = []
    original = router.database_health

    def probe(store):
        probes.append(True)
        return original(store, collector=active.collector)

    monkeypatch.setattr(router, "database_health", probe)
    assert active.client.get(ENDPOINT).status_code == 401
    for role in ("readonly", "buchhaltung", "selected"):
        response = active.client.get(ENDPOINT, headers=active.headers[role])
        assert response.status_code == 403, response.text
        assert "requests" not in response.json()
    assert not probes
    for role in ("eigentuemer", "verwalter"):
        response = active.client.get(ENDPOINT, headers=active.headers[role])
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        data = response.json()
        assert data["scope"] == "process_worker" and data["persistent"] is False
        assert data["database"]["state"] == ("connected" if hasattr(active.store, "db") else "not_configured")
        assert data["database"]["persistent"] == hasattr(active.store, "db")
        assert data["process"]["cpu_seconds"] >= 0 and data["uptime_seconds"] >= 0
        assert PRIVATE not in response.text


def test_true_server_error_is_counted_once_and_next_request_recovers(installation, monkeypatch):
    active = installation

    def fail():
        raise RuntimeError(PRIVATE)

    with monkeypatch.context() as patch:
        patch.setattr(active.store, "list_portfolios", fail)
        response = active.client.get("/api/v1/portfolios?search=" + PRIVATE, headers=active.headers["eigentuemer"])
    assert response.status_code == 500, response.text
    assert active.client.get("/api/v1/portfolios", headers=active.headers["eigentuemer"]).status_code == 200
    rows = active.collector.snapshot()["requests"]["series"]
    assert sum(row["count"] for row in rows if row["outcome"] == "server_error") == 1
    assert sum(row["count"] for row in rows if row["outcome"] == "success") == 1
    assert active.collector.snapshot()["requests"]["inflight"] == 0
    assert PRIVATE not in json.dumps(active.collector.snapshot())


def test_revocation_during_probe_prevents_publication(installation, monkeypatch):
    active = installation

    def revoke(store):
        auth._user_store.update(active.users["verwalter"].id, {"is_active": False}, actor_id=active.users["eigentuemer"].id)
        return {"state": "connected"}

    monkeypatch.setattr(router, "database_health", revoke)
    response = active.client.get(ENDPOINT, headers=active.headers["verwalter"])
    assert response.status_code == 403
    assert "requests" not in response.text and "started_at" not in response.text
    assert active.client.get(ENDPOINT, headers=active.headers["verwalter"]).status_code == 403


def test_missing_database_is_unavailable_and_connection_errors_are_private(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "missing" / (PRIVATE + ".db")).as_posix())
    collector = OperationalMetrics()
    try:
        with sessionmaker(bind=engine)() as session:
            result = database_health(SimpleNamespace(db=session), collector=collector)
        assert result["state"] == "unavailable" and result["persistent"] is True
        assert result["backend"] == "sqlite"
        assert not (tmp_path / "missing").exists()
        assert PRIVATE not in json.dumps({"health": result, "metrics": collector.snapshot()})
        assert collector.snapshot()["database_probes"]["unavailable"]["count"] == 1
    finally:
        engine.dispose()


def test_real_parallel_http_requests_are_observed_without_losing_counts(installation):
    active = installation
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: active.client.get("/api/v1/portfolios", headers=active.headers["eigentuemer"]), range(24)))
    assert all(response.status_code == 200 for response in responses)
    snapshot = active.collector.snapshot()
    assert snapshot["requests"]["completed"] == 24
    assert snapshot["requests"]["inflight"] == 0
    assert snapshot["requests"]["peak_inflight"] > 1
    assert sum(row["count"] for row in snapshot["requests"]["series"] if row["group"] == "property") == 24


def test_direct_router_cannot_bypass_portfolio_guard_without_app_middleware(installation, monkeypatch):
    active = installation
    application = FastAPI()
    application.include_router(router.router, prefix="/api/v1")
    probes = []
    monkeypatch.setattr(router, "database_health", lambda *_: probes.append(True))
    with TestClient(application) as client:
        response = client.get(ENDPOINT, headers=active.headers["selected"])
    assert response.status_code == 403 and not probes


def test_http_database_failure_keeps_sanitized_status_readable(installation, monkeypatch, tmp_path):
    active = installation
    offline = create_engine("sqlite:///" + (tmp_path / "gone" / "private.db").as_posix())
    try:
        with sessionmaker(bind=offline)() as session:
            monkeypatch.setattr(dependencies, "store", SimpleNamespace(db=session))
            response = active.client.get(ENDPOINT, headers=active.headers["eigentuemer"])
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["database"]["state"] == "unavailable"
        assert "gone" not in response.text and str(tmp_path) not in response.text and "OperationalError" not in response.text
        assert response.headers["cache-control"] == "private, no-store"
    finally:
        offline.dispose()


def test_two_thousand_unique_private_urls_never_expand_metric_labels():
    application = FastAPI()
    collector = OperationalMetrics()
    with TestClient(OperationalMetricsMiddleware(application, collector=collector)) as client:
        for index in range(2000):
            assert client.get(f"/unknown/{index}/{PRIVATE}?password={PRIVATE}", headers={"User-Agent": PRIVATE}).status_code == 404
    snapshot = collector.snapshot()
    assert snapshot["requests"]["completed"] == 2000
    assert len(snapshot["requests"]["series"]) == 1
    row, = snapshot["requests"]["series"]
    assert (row["group"], row["method"], row["outcome"]) == ("unmatched", "GET", "client_error")
    assert sum(bucket["count"] for bucket in row["histogram"]) == 2000
    assert PRIVATE not in json.dumps(snapshot) and "/unknown" not in json.dumps(snapshot)


def test_parallel_requests_are_not_lost_and_measure_inflight():
    now = [0.0]
    collector = OperationalMetrics(clock=lambda: now[0])
    from threading import Barrier
    barrier = Barrier(10)

    def request(index):
        started = collector.begin_request()
        barrier.wait(timeout=3)
        now[0] = 0.1
        collector.finish_request(group="finance", method="GET", outcome="success", started=started)

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(request, range(10)))
    snapshot = collector.snapshot()
    assert snapshot["requests"]["peak_inflight"] == 10
    assert snapshot["requests"]["inflight"] == 0 and snapshot["requests"]["completed"] == 10
    row, = snapshot["requests"]["series"]
    assert row["mean_ms"] == row["max_ms"] == 100
    assert next(bucket["count"] for bucket in row["histogram"] if bucket["upper_ms"] == 100) == 10


@pytest.mark.parametrize("failure", ["disconnect", "cancel", "none"])
def test_duration_includes_final_stream_body_and_abort_is_not_success(failure):
    now = [0.0]
    collector = OperationalMetrics(clock=lambda: now[0])

    async def application(scope, receive, send):
        scope["route"] = SimpleNamespace(path="/api/v1/files/download")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        now[0] = 0.05
        await send({"type": "http.response.body", "body": b"part", "more_body": True})
        now[0] = 2.0
        if failure == "cancel":
            raise asyncio.CancelledError()
        await send({"type": "http.response.body", "body": b"last"})

    async def send(message):
        if failure == "disconnect" and message.get("body") == b"last":
            raise OSError(PRIVATE)

    async def receive():
        return {"type": "http.disconnect"}

    call = OperationalMetricsMiddleware(application, collector=collector)({"type": "http", "method": "GET"}, receive, send)
    if failure != "none":
        with pytest.raises(OSError if failure == "disconnect" else asyncio.CancelledError):
            asyncio.run(call)
    else:
        asyncio.run(call)
    snapshot = collector.snapshot()
    row, = snapshot["requests"]["series"]
    assert row["total_ms"] == 2000 and row["outcome"] == ("success" if failure == "none" else "aborted")
    assert snapshot["requests"]["inflight"] == 0
    assert snapshot["requests"]["aborted"] == (0 if failure == "none" else 1)
    assert PRIVATE not in json.dumps(snapshot)


def test_aborted_error_body_counts_both_http_server_error_and_abort():
    collector = OperationalMetrics()

    async def application(scope, receive, send):
        await send({"type": "http.response.start", "status": 503, "headers": []})
        await send({"type": "http.response.body", "body": b"error", "more_body": True})
        raise OSError(PRIVATE)

    async def send(message):
        pass

    with pytest.raises(OSError):
        asyncio.run(OperationalMetricsMiddleware(application, collector=collector)({"type": "http", "method": "GET"}, None, send))
    snapshot = collector.snapshot()
    row, = snapshot["requests"]["series"]
    assert row["outcome"] == "server_error" and row["count"] == 1
    assert snapshot["requests"]["aborted"] == 1 and snapshot["requests"]["inflight"] == 0


def test_disconnect_while_sending_headers_is_an_abort_not_an_invented_500():
    collector = OperationalMetrics()

    async def application(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def send(message):
        raise OSError("Synthetic disconnected client")

    with pytest.raises(OSError, match="Synthetic disconnected client"):
        asyncio.run(OperationalMetricsMiddleware(application, collector=collector)({"type": "http", "method": "GET"}, None, send))
    snapshot = collector.snapshot()
    row, = snapshot["requests"]["series"]
    assert row["outcome"] == "aborted"
    assert snapshot["requests"]["aborted"] == 1 and snapshot["requests"]["inflight"] == 0


def test_error_after_response_is_visible_without_falsifying_success_status():
    collector = OperationalMetrics()

    async def application(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
        raise RuntimeError(PRIVATE)

    async def send(message):
        pass

    with pytest.raises(RuntimeError):
        asyncio.run(OperationalMetricsMiddleware(application, collector=collector)({"type": "http", "method": "GET"}, None, send))
    snapshot = collector.snapshot()
    row, = snapshot["requests"]["series"]
    assert row["outcome"] == "success" and snapshot["requests"]["exceptions"] == 1
    assert snapshot["requests"]["aborted"] == 0
    assert PRIVATE not in json.dumps(snapshot)


def test_actual_ticks_report_committed_success_and_rollback_failure(installation, monkeypatch):
    active = installation
    operational_schedule.operational_tick(active.store)
    # Failure after entering the real job preserves the original exception and
    # never emits a committed/successful tick journal.
    with monkeypatch.context() as patch:
        patch.setattr(operational_schedule, "_recurring", lambda *_args: (_ for _ in ()).throw(RuntimeError(PRIVATE)))
        with pytest.raises(RuntimeError, match=PRIVATE):
            operational_schedule.operational_tick(active.store)
    assert len(operational_schedule.recent_ticks(active.store)) == 1
    snapshot = active.collector.snapshot()
    assert snapshot["jobs"]["operational_tick"]["success"]["count"] == 1
    assert snapshot["jobs"]["operational_tick"]["error"]["count"] == 1
    assert PRIVATE not in json.dumps(snapshot)


def test_manual_tick_log_correlates_with_actual_request_without_journal_ids(installation, caplog):
    active = installation
    with caplog.at_level(logging.INFO, logger="backend.services.operational_metrics"):
        response = active.client.post("/api/v1/tasks/operational-tick", headers=active.headers["eigentuemer"], json={})
    assert response.status_code == 200, response.text
    records = [record for record in caplog.records if record.name == "backend.services.operational_metrics"]
    assert len(records) == 1
    output = json.loads(JSONFormatter().format(records[0]))
    assert output["request_id"] == response.headers["x-request-id"]
    assert output["duration_ms"] >= 0 and output["message"] == "Local operational tick success"
    assert PRIVATE not in json.dumps(output)
    assert active.collector.snapshot()["jobs"]["operational_tick"]["success"]["count"] == 1


def test_manual_tick_keeps_request_context_without_root_handler_filters(installation, monkeypatch):
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            if record.name == "backend.services.operational_metrics":
                records.append(record)

    # Alembic or an embedding application can replace root handlers. The
    # operational event still needs its real request context at creation.
    monkeypatch.setattr(logging.getLogger(), "handlers", [Capture()])
    # Alembic can leave root at WARNING. Explicitly enable the event under test
    # without depending on the levels left by earlier migration tests.
    monkeypatch.setattr(logging.getLogger(), "level", logging.WARNING)
    monkeypatch.setattr(logging.getLogger("backend.services.operational_metrics"), "level", logging.INFO)
    response = installation.client.post("/api/v1/tasks/operational-tick",
                                       headers=installation.headers["eigentuemer"], json={})
    assert response.status_code == 200, response.text
    assert len(records) == 1
    output = json.loads(JSONFormatter().format(records[0]))
    assert output["request_id"] == response.headers["x-request-id"]
    assert output["request_id"] != "-"
    assert output["message"] == "Local operational tick success"
    assert PRIVATE not in json.dumps(output)


def test_worker_restart_has_independent_empty_counters():
    collector = OperationalMetrics()
    started = collector.begin_request()
    collector.finish_request(group="other", method="GET", outcome="success", started=started)
    restarted = OperationalMetrics()
    assert collector.snapshot()["requests"]["completed"] == 1
    assert restarted.snapshot()["requests"]["completed"] == 0
    assert restarted.snapshot()["requests"]["series"] == []


def test_failed_telemetry_log_cannot_replace_job_result_or_original_error(monkeypatch):
    from backend.services import operational_metrics
    collector = OperationalMetrics()
    monkeypatch.setattr(operational_metrics.logger, "info", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("Log handler failed")))
    with collector.operational_tick():
        result = "committed"
    assert result == "committed"
    with pytest.raises(ValueError, match="Original job failure"):
        with collector.operational_tick():
            raise ValueError("Original job failure")
    assert collector.snapshot()["jobs"]["operational_tick"]["success"]["count"] == 1
    assert collector.snapshot()["jobs"]["operational_tick"]["error"]["count"] == 1
