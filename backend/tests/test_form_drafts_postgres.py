"""Genuine PostgreSQL G40 gates on an Alembic-migrated, disposable UUID schema.

No create_all, SQLite fallback, shared test schemas or real customer databases.
Two distinct engines prove connection independence rather than thread-local
objects masquerading as two browser tabs.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.db.form_draft_models import FormDraftORM
from backend.db.orm_models import PropertyORM
from backend.form_draft_models import DraftWrite
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import form_draft_crypto, form_drafts
from backend.services.portfolio_scope import scope_from_user
from backend.tests.form_draft_api_support import (
    ENDPOINT,
    application,
    assert_connections_returned,
    assert_migrated,
    draft_body,
    draft_query,
    migrate,
)
from backend.tests.test_form_drafts_http import business_revision_flow, private_user_flow


@pytest.fixture
def postgres_drafts(monkeypatch):
    source = os.environ.get("TEST_SERVER_DATABASE_URL")
    if not source:
        pytest.skip("TEST_SERVER_DATABASE_URL disposable PostgreSQL service is not configured; no local fallback")
    url = make_url(source)
    if url.get_backend_name() != "postgresql":
        pytest.fail("TEST_SERVER_DATABASE_URL must reference disposable PostgreSQL")
    schema = "immo_drafts_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True, pool_pre_ping=True)
    isolated = url.update_query_dict({"options": "-csearch_path=" + schema})
    first = second = None
    created = False
    try:
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            created = True
        head = migrate(isolated.render_as_string(hide_password=False), monkeypatch)
        first = create_engine(isolated, hide_parameters=True, pool_pre_ping=True)
        second = create_engine(isolated, hide_parameters=True, pool_pre_ping=True)
        assert first.dialect.name == second.dialect.name == "postgresql"
        assert_migrated(first, head)
        assert {item["name"] for item in inspect(first).get_indexes("form_drafts")} == {"idx_form_drafts_user_expiry"}
        with application(monkeypatch, first) as active:
            yield active, second
        assert_connections_returned(first)
        assert_connections_returned(second)
    finally:
        if first is not None:
            first.dispose()
        if second is not None:
            second.dispose()
        try:
            if created:
                # Only this generated lowercase UUID namespace is ever dropped.
                assert schema.startswith("immo_drafts_") and len(schema) == 44
                assert all(character in "0123456789abcdef" for character in schema[12:])
                with admin.begin() as connection:
                    connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        finally:
            admin.dispose()


def parallel_drafts(active, second, revision=None, *, different_entities=False):
    current_user = auth.get_user_by_id(active.owner.id)
    assert current_user is not None
    actor = scope_from_user(current_user)
    barrier = Barrier(2)
    factories = [active.factory, sessionmaker(bind=second, autoflush=False)]
    def write(index):
        row = active.properties[index if different_entities else 0]
        expected = revision[index] if isinstance(revision, list) else revision
        data = DraftWrite.model_validate(draft_body(active.owner, row, name=f"Independent tab {index}", revision=expected))
        with factories[index]() as db:
            pid = db.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            barrier.wait(timeout=20)
            try:
                response = form_drafts.form_draft(SQLAlchemyStore(db), data, actor, write=data)
                return index, pid, 200, response
            except HTTPException as error:
                return index, pid, error.status_code, getattr(error, "code", None)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, range(2)))
    assert len({result[1] for result in results}) == 2
    active.assert_connections_returned()
    assert_connections_returned(second)
    return results


def test_pg_migrated_two_connections_insert_update_cas_and_independent_entities(postgres_drafts):
    active, second = postgres_drafts
    first = parallel_drafts(active, second)
    assert sorted(result[2] for result in first) == [200, 409]
    winner = next(result for result in first if result[2] == 200)
    assert next(result[3] for result in first if result[2] == 409) == "DRAFT_CONFLICT"
    rows = active.snapshot()
    assert len(rows) == 1 and rows[0]["revision"] == winner[3]["revision"]
    first_payload = rows[0]["payload"]
    plaintext = form_draft_crypto.decrypt(first_payload, rows[0]["id"].encode("ascii")).decode()
    assert f"Independent tab {winner[0]}" in plaintext
    second_round = parallel_drafts(active, second, winner[3]["revision"])
    assert sorted(result[2] for result in second_round) == [200, 409]
    winner = next(result for result in second_round if result[2] == 200)
    rows = active.snapshot()
    assert len(rows) == 1 and rows[0]["revision"] == winner[3]["revision"]
    assert rows[0]["payload"] != first_payload
    assert f"Independent tab {winner[0]}" in form_draft_crypto.decrypt(rows[0]["payload"], rows[0]["id"].encode("ascii")).decode()
    # Distinct private form identities both succeed without a false conflict.
    results = parallel_drafts(active, second, [rows[0]["revision"], None], different_entities=True)
    assert [result[2] for result in results] == [200, 200]
    assert len(active.snapshot()) == 2
    assert all(row["payload"].startswith("draft:v1:") and "Independent tab" not in row["payload"] for row in active.snapshot())


def test_pg_full_api_restored_original_microsecond_revision_still_guards_business_cas(postgres_drafts):
    business_revision_flow(postgres_drafts[0])


def test_pg_same_resource_private_users_have_identity_bound_encrypted_storage(postgres_drafts):
    active, second = postgres_drafts
    private_user_flow(active)
    before = active.snapshot()
    assert len(before) == 2
    assert all(row["payload"].startswith("draft:v1:") for row in before)
    assert all("Private synthetic draft" not in row["payload"] and "Peer's independent draft" not in row["payload"] for row in before)
    owner_headers = active.headers(active.owner)
    row = active.properties[0]
    forbidden = active.client.get(ENDPOINT, headers=owner_headers, params=draft_query(active.member, row))
    assert forbidden.status_code == 403
    assert active.client.get(ENDPOINT, headers=owner_headers, params=draft_query(active.owner, row)).json() == {"draft": None}
    source = next(item for item in before if item["user_id"] == active.member.id)
    target = next(item for item in before if item["user_id"] == active.peer.id)
    # Copy a genuine cipher into a different private user's identity. AES-GCM
    # binding must reject it, even though both users can edit the same property.
    with second.begin() as connection:
        connection.execute(update(FormDraftORM).where(FormDraftORM.id == target["id"]).values(payload=source["payload"]))
    corrupted = active.snapshot()
    peer_headers = active.headers(active.peer)
    response = active.client.get(ENDPOINT, headers=peer_headers, params=draft_query(active.peer, row))
    assert response.status_code == 503 and response.json()["error"]["code"] == "DRAFT_ENCRYPTION_UNAVAILABLE"
    overwrite = active.client.put(ENDPOINT, headers=peer_headers,
        json=draft_body(active.peer, row, revision=target["revision"], name="Never overwrite inaccessible ciphertext"))
    assert overwrite.status_code == 503
    assert active.snapshot() == corrupted
    member_headers = active.headers(active.member)
    assert active.client.get(ENDPOINT, headers=member_headers, params=draft_query(active.member, row)).json()["draft"]["values"]["name"] == "Private synthetic draft €"
    active.assert_connections_returned()


@pytest.mark.parametrize("change", ["portfolio", "role", "inactive"])
def test_pg_fresh_independent_revocation_rejects_cached_actor_and_existing_http_session(postgres_drafts, monkeypatch, change):
    active, second = postgres_drafts
    user, row = active.member, active.properties[0]
    headers = active.headers(user)
    body = draft_body(user, row)
    saved = active.client.put(ENDPOINT, headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    before = active.snapshot()
    current_user = auth.get_user_by_id(user.id)
    assert current_user is not None
    captured = scope_from_user(current_user)
    factory = sessionmaker(bind=second, autoflush=False)
    with factory() as cached:
        cached_row = cached.get(PropertyORM, row.id)
        assert cached_row is not None and cached_row.name == row.name
        updates = {"portfolio_access": "selected", "portfolio_ids": []} if change == "portfolio" else {"role": "readonly"} if change == "role" else {"is_active": False}
        auth.SQLUserStore(factory).update(user.id, updates, actor_id=active.owner.id)
        calls = []
        def refused(*args, **kwargs):
            calls.append(True)
            raise AssertionError("Revoked scope must be rejected before plaintext access")
        monkeypatch.setattr(form_draft_crypto, "encrypt", refused)
        monkeypatch.setattr(form_draft_crypto, "decrypt", refused)
        data = DraftWrite.model_validate({**body, "expected_revision": saved.json()["revision"]})
        with pytest.raises(HTTPException) as denied:
            form_drafts.form_draft(SQLAlchemyStore(cached), data, captured, write=data)
        assert denied.value.status_code == 403
        cached.rollback()
    for method in ("get", "put", "delete"):
        if method == "put":
            response = active.client.put(ENDPOINT, headers=headers, json={**body, "expected_revision": saved.json()["revision"]})
        else:
            params = draft_query(user, row)
            if method == "delete":
                params["expected_revision"] = saved.json()["revision"]
            response = getattr(active.client, method)(ENDPOINT, headers=headers, params=params)
        assert response.status_code in ({401, 403} if change == "inactive" else {403}), response.text
        assert "Private synthetic draft" not in response.text
    assert calls == [] and active.snapshot() == before
    with second.connect() as connection:
        assert connection.scalar(select(PropertyORM.name).where(PropertyORM.id == row.id)) == row.name
    active.assert_connections_returned()


def test_pg_current_domain_portfolio_move_hides_old_draft_without_losing_ciphertext(postgres_drafts):
    active, second = postgres_drafts
    user, row = active.member, active.properties[0]
    headers = active.headers(user)
    saved = active.client.put(ENDPOINT, headers=headers, json=draft_body(user, row))
    assert saved.status_code == 200, saved.text
    before = active.snapshot()
    with second.begin() as connection:
        connection.execute(update(PropertyORM).where(PropertyORM.id == row.id).values(portfolio_id=active.portfolios[1].id))
    assert active.client.get("/api/v1/properties/" + row.id, headers=headers).status_code == 404
    response = active.client.get(ENDPOINT, headers=headers, params=draft_query(user, row))
    assert response.status_code == 404 and response.json()["error"]["code"] == "DRAFT_RESOURCE_UNAVAILABLE"
    overwrite = active.client.put(ENDPOINT, headers=headers, json=draft_body(user, row, revision=saved.json()["revision"], name="Must remain outside scope"))
    assert overwrite.status_code == 404
    assert active.snapshot() == before
    active.assert_connections_returned()


def test_pg_actual_reset_waits_for_inflight_autosave_and_preserves_draft_and_business_rows(postgres_drafts, monkeypatch):
    """The real clear_all entrypoint cannot race a not-yet-committed draft."""
    active, second = postgres_drafts
    current_user = auth.get_user_by_id(active.owner.id)
    assert current_user is not None
    actor = scope_from_user(current_user)
    row = active.properties[0]
    data = DraftWrite.model_validate(draft_body(active.owner, row))
    paused, resume, reset_started, guard_passed = Event(), Event(), Event(), Event()
    pids = {}
    encrypt = form_draft_crypto.encrypt
    guard = form_drafts.guard_destructive_reset
    def paused_encrypt(value, identity):
        paused.set()
        assert resume.wait(timeout=20), "Synthetic autosave must be released within its test budget"
        return encrypt(value, identity)
    def observed_guard(store):
        result = guard(store)
        guard_passed.set()
        return result
    monkeypatch.setattr(form_draft_crypto, "encrypt", paused_encrypt)
    monkeypatch.setattr(form_drafts, "guard_destructive_reset", observed_guard)
    def autosave():
        with active.factory() as db:
            pids["writer"] = db.scalar(text("SELECT pg_backend_pid()"))
            return form_drafts.form_draft(SQLAlchemyStore(db), data, actor, write=data)
    def reset():
        with sessionmaker(bind=second, autoflush=False)() as db:
            pids["reset"] = db.scalar(text("SELECT pg_backend_pid()"))
            reset_started.set()
            try:
                SQLAlchemyStore(db).clear_all()
                return "unexpected business deletion"
            except ValueError as error:
                db.rollback()
                assert "Formularentwürfe" in str(error)
                return "preserved"
    with ThreadPoolExecutor(max_workers=2) as executor:
        writer = executor.submit(autosave)
        maintenance = None
        try:
            assert paused.wait(timeout=15), "Autosave never reached its real locked transaction"
            maintenance = executor.submit(reset)
            assert reset_started.wait(timeout=10)
            assert isinstance(pids["writer"], int) and isinstance(pids["reset"], int)
            assert pids["writer"] != pids["reset"]
            deadline = monotonic() + 10
            blocked = False
            while monotonic() < deadline:
                with active.engine.connect() as connection:
                    blocked = bool(connection.scalar(text("SELECT :writer = ANY(pg_blocking_pids(:reset))"), pids))
                if blocked or maintenance.done():
                    break
                sleep(0.01)
            assert blocked, "PostgreSQL must prove that maintenance waits for the autosave connection"
            assert not guard_passed.is_set(), "The preservation guard must arbitrate before any business reset DML"
            assert not maintenance.done()
        finally:
            resume.set()
        saved = writer.result(timeout=20)
        assert maintenance is not None and maintenance.result(timeout=20) == "preserved"
    rows = active.snapshot()
    assert len(rows) == 1 and rows[0]["revision"] == saved["revision"]
    assert rows[0]["payload"].startswith("draft:v1:")
    with second.connect() as connection:
        assert connection.scalar(select(PropertyORM.name).where(PropertyORM.id == row.id)) == row.name
        assert len(connection.execute(select(PropertyORM.id)).all()) == 2
    active.assert_connections_returned()
    assert_connections_returned(second)
