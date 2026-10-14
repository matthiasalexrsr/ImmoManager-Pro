"""HTTP edit tokens reject a concurrent writer on independent PostgreSQL sessions."""

import threading
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from test_document_versions_postgres import postgres  # noqa: F401

from backend import auth, dependencies
from backend.app import app
from backend.db.orm_models import ContactORM
from backend.models import TenantCreate
from backend.repositories import SQLAlchemyStore, base
from backend.routers import tenants
from backend.services import plausibility
from backend.services.record_revisions import expected_revision


@pytest.mark.parametrize("method", ["PUT", "PATCH"])
def test_same_edit_token_serializes_at_write_and_request_context_is_cleared(postgres, monkeypatch, method):  # noqa: F811
    engine, _ = postgres

    @event.listens_for(engine, "connect")
    def berlin_timezone(connection, _):
        with connection.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'Europe/Berlin'")
        connection.commit()

    engine.dispose()  # every request connection uses the explicit non-UTC zone
    sessions = scoped_session(sessionmaker(engine), scopefunc=dependencies._session_scope)
    target = SQLAlchemyStore(cast(Session, sessions))
    monkeypatch.setattr(dependencies, "_scoped_session", sessions)
    monkeypatch.setattr(dependencies, "store", target)
    monkeypatch.setattr(tenants, "store", target)
    original = target.create_tenant(TenantCreate(full_name="Original"))
    sessions.remove()

    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return original.updated_at.replace(tzinfo=timezone.utc) if tz is not None else original.updated_at

    monkeypatch.setattr(base, "datetime", FrozenClock)
    owner = auth.register_user("race-owner", "race-owner@example.test", "Owner", "Secret123", "eigentuemer")
    headers = {"Authorization": f"Bearer {auth.create_access_token(owner.id)}"}
    # Browser clients can round the database's timestamp to milliseconds.
    token = original.updated_at.isoformat(timespec="milliseconds")
    path = f"/api/v1/tenants/{original.id}"
    reached = threading.Barrier(2, timeout=15)
    checked = []
    responses = []
    errors = []
    check = plausibility.check_not_stale

    def after_check(request_method, request_path, body, store):
        expected = check(request_method, request_path, body, store)
        if request_path == path.removeprefix("/api/v1"):
            checked.append((id(sessions()), sessions().connection().exec_driver_sql("SELECT pg_backend_pid()").scalar()))
            # A losing edit must roll back any pending side effects, not flush
            # them before discovering the conflicting revision.
            sessions().add(ContactORM(id=f"side-{body['full_name']}", contact_type="supplier",
                                      company_name=body["full_name"]))
            reached.wait()
        return expected

    monkeypatch.setattr(plausibility, "check_not_stale", after_check)
    with TestClient(app) as client:
        def write(name):
            try:
                response = client.request(method, path, headers=headers,
                                          json={"full_name": name, "updated_at": token})
                responses.append((name, response))
            except BaseException as exc:
                errors.append(exc)

        workers = [threading.Thread(target=write, args=(name,)) for name in ("Writer A", "Writer B")]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(25)
        assert not any(worker.is_alive() for worker in workers)
        assert not errors, errors
        assert len(checked) == 2 and len({record[0] for record in checked}) == 2
        assert len({record[1] for record in checked}) == 2
        assert sorted(response.status_code for _, response in responses) == [200, 409]
        winner, accepted = next((name, response) for name, response in responses if response.status_code == 200)
        assert datetime.fromisoformat(accepted.json()["updated_at"]) == original.updated_at + timedelta(milliseconds=2)
        with Session(engine) as verification:
            assert SQLAlchemyStore(verification).get_tenant(original.id).full_name == winner
            assert list(verification.scalars(select(ContactORM.company_name))) == [winner]

        monkeypatch.setattr(plausibility, "check_not_stale", check)
        # Same connection pool/client: stale token refused; the current token
        # can be retried, and compatibility requests inherit no old expectation.
        assert client.request(method, path, headers=headers, json={"full_name": "Stale", "updated_at": token}).status_code == 409
        retry = client.request(method, path, headers=headers,
                               json={"full_name": "Retry", "updated_at": accepted.json()["updated_at"]})
        assert retry.status_code == 200, retry.text
        for payload in ({"full_name": "No token"}, {"full_name": "Invalid token", "updated_at": "invalid"}):
            compatible = client.request(method, path, headers=headers, json=payload)
            assert compatible.status_code == 200, compatible.text
        assert expected_revision("tenants", original.id) is None
        assert client.get(path, headers=headers).json()["full_name"] == "Invalid token"
