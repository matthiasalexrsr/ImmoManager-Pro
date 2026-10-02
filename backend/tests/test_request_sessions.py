"""Real worker/ASGI requests must return SQLite connections, including streams."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker

from backend import dependencies
from backend.middleware import DBSessionMiddleware


@pytest.fixture
def scoped_app(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "request-sessions.db").as_posix(),
        connect_args={"check_same_thread": False}, pool_size=2, max_overflow=0, pool_timeout=1)
    sessions = scoped_session(sessionmaker(bind=engine), scopefunc=dependencies.session_scope_key)
    monkeypatch.setattr(dependencies, "_scoped_session", sessions)
    app = FastAPI()
    app.add_middleware(DBSessionMiddleware)

    @app.get("/read")
    def read():
        return {"value": sessions.execute(text("SELECT 1")).scalar_one()}

    @app.get("/fail")
    def fail():
        sessions.execute(text("SELECT 1"))
        raise RuntimeError("synthetic route failure")

    @app.get("/stream")
    def stream():
        selected = sessions()
        selected.execute(text("SELECT 1"))
        def chunks():
            # Cleanup must wait for streaming work and share its worker session.
            assert sessions() is selected
            yield str(sessions.execute(text("SELECT 2")).scalar_one())
        return StreamingResponse(chunks())

    @app.get("/overlap")
    async def overlap():
        selected = sessions()
        selected.execute(text("SELECT 1"))
        await asyncio.sleep(0.03)
        assert sessions() is selected
        return {"session": id(selected)}

    yield app, engine, sessions
    sessions.remove()
    engine.dispose()


def test_worker_connections_are_returned_after_every_request(scoped_app):
    app, engine, sessions = scoped_app
    with TestClient(app) as client:
        for _ in range(35):
            assert client.get("/read").json() == {"value": 1}
            assert engine.pool.checkedout() == 0
            assert not sessions.registry.registry


def test_error_and_streaming_response_release_the_same_request_session(scoped_app):
    app, engine, sessions = scoped_app
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/fail").status_code == 500
        assert engine.pool.checkedout() == 0
        assert not sessions.registry.registry
        assert client.get("/stream").text == "2"
        assert engine.pool.checkedout() == 0
        assert not sessions.registry.registry
        assert client.get("/read").status_code == 200


def test_concurrent_async_requests_have_distinct_sessions(scoped_app):
    app, engine, sessions = scoped_app
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            results = await asyncio.gather(client.get("/overlap"), client.get("/overlap"))
        assert len({response.json()["session"] for response in results}) == 2
    asyncio.run(run())
    assert engine.pool.checkedout() == 0
    assert not sessions.registry.registry


def test_concurrent_worker_requests_do_not_leak_into_thread_registry(scoped_app):
    app, engine, sessions = scoped_app
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=6) as workers:
        responses = list(workers.map(lambda _: client.get("/read"), range(50)))
    assert all(response.status_code == 200 for response in responses)
    assert engine.pool.checkedout() == 0
    assert not sessions.registry.registry
