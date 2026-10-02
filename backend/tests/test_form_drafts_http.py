"""Full API acceptance: private drafts retain the original business CAS token."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine, update

from backend import auth
from backend.db.orm_models import PropertyORM
from backend.services import form_draft_crypto
from backend.services.concurrency import parse_revision
from backend.tests.form_draft_api_support import (
    ENDPOINT,
    application,
    assert_migrated,
    draft_body,
    draft_query,
    migrate,
)


@pytest.fixture(params=["memory", "sqlite"])
def draft_http(request, monkeypatch, tmp_path):
    engine = None
    if request.param == "sqlite":
        url = "sqlite:///" + (tmp_path / "full-api-drafts.sqlite").as_posix()
        head = migrate(url, monkeypatch)
        engine = create_engine(url, hide_parameters=True, connect_args={"check_same_thread": False})
        assert_migrated(engine, head)
    try:
        with application(monkeypatch, engine) as active:
            yield active
    finally:
        if engine is not None:
            engine.dispose()


def business_revision_flow(active):
    """A restored draft must not inherit a later list/GET revision implicitly."""
    user, row = active.member, active.properties[0]
    original_stamp = datetime(2026, 1, 2, 3, 4, 5, 123456)
    if active.engine is None:
        active.store.properties[row.id].updated_at = original_stamp
    else:
        with active.engine.begin() as connection:
            connection.execute(update(PropertyORM).where(PropertyORM.id == row.id).values(updated_at=original_stamp))
    headers = active.headers(user)
    path = "/api/v1/properties/" + row.id
    opened = active.client.get(path, headers=headers)
    assert opened.status_code == 200, opened.text
    token = opened.headers["etag"]
    assert parse_revision(token).updated_at.microsecond == 123456
    edit = {"collection": "properties", "id": row.id, "updatedAt": opened.json()["updated_at"], "etag": token, "path": "/properties/" + row.id}
    body = draft_body(user, row, business_revision=edit)
    saved = active.client.put(ENDPOINT, headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    before = active.snapshot()
    # A separately authenticated tab performs a real conditional business write.
    other_tab = active.headers(user)
    changed = active.client.patch(path, headers={**other_tab, "If-Match": token}, json={"name": "Saved in another tab"})
    assert changed.status_code == 200, changed.text
    assert changed.headers["etag"] != token
    assert active.client.get(path, headers=headers).json()["name"] == "Saved in another tab"
    listed = active.client.get("/api/v1/properties", headers=headers)
    assert listed.status_code == 200 and listed.json()[0]["updated_at"] == changed.json()["updated_at"]
    restored = active.client.get(ENDPOINT, headers=headers, params=draft_query(user, row))
    assert restored.status_code == 200, restored.text
    draft = restored.json()["draft"]
    assert draft["edit_revision"] == edit
    assert draft["original_values"]["name"] == row.name
    assert draft["values"]["name"] == body["values"]["name"]
    stale = active.client.patch(path, headers={**headers, "If-Match": draft["edit_revision"]["etag"]}, json=draft["values"])
    assert stale.status_code == 412, stale.text
    assert active.client.get(path, headers=headers).json() == changed.json()
    assert active.snapshot() == before
    # Explicit reconciliation can use the current revision; saving a draft never
    # performs this action or changes its original snapshot on the user's behalf.
    reconciled = active.client.patch(path, headers={**headers, "If-Match": changed.headers["etag"]}, json={"name": "Explicitly reconciled"})
    assert reconciled.status_code == 200, reconciled.text
    assert active.snapshot() == before
    active.assert_connections_returned()


def test_full_api_preserves_microseconds_and_rejects_stale_restored_business_write(draft_http):
    business_revision_flow(draft_http)


def private_user_flow(active):
    user, peer, row = active.member, active.peer, active.properties[0]
    headers, peer_headers = active.headers(user), active.headers(peer)
    assert active.client.put(ENDPOINT, json=draft_body(user, row)).status_code in {401, 403}
    saved = active.client.put(ENDPOINT, headers=headers, json=draft_body(user, row))
    assert saved.status_code == 200, saved.text
    before = active.snapshot()
    own = active.client.get(ENDPOINT, headers=headers, params=draft_query(user, row))
    assert own.status_code == 200 and own.headers["cache-control"] == "no-store"
    assert active.client.get(ENDPOINT, headers=peer_headers, params=draft_query(peer, row)).json() == {"draft": None}
    for method in ("get", "put", "delete"):
        if method == "put":
            response = active.client.put(ENDPOINT, headers=peer_headers, json=draft_body(user, row, revision=saved.json()["revision"]))
        else:
            params = draft_query(user, row)
            if method == "delete":
                params["expected_revision"] = saved.json()["revision"]
            response = getattr(active.client, method)(ENDPOINT, headers=peer_headers, params=params)
        assert response.status_code == 403, response.text
        assert "Private synthetic draft" not in response.text
        assert response.headers["cache-control"] == "no-store"
    # The exact own-route exception must never open neighboring auth administration.
    assert active.client.get("/api/v1/auth/users", headers=headers).status_code == 403
    assert active.client.get(ENDPOINT + "/other", headers=headers).status_code == 403
    assert active.snapshot() == before
    peer_saved = active.client.put(ENDPOINT, headers=peer_headers, json=draft_body(peer, row, name="Peer's independent draft"))
    assert peer_saved.status_code == 200, peer_saved.text
    assert len(active.snapshot()) == 2
    assert active.client.get(ENDPOINT, headers=headers, params=draft_query(user, row)).json() == own.json()
    assert active.client.get("/api/v1/properties/" + row.id, headers=headers).json()["name"] == row.name
    active.assert_connections_returned()


def test_full_api_exact_own_route_keeps_same_resource_drafts_private(draft_http):
    private_user_flow(draft_http)


@pytest.mark.parametrize("change", ["portfolio", "role", "inactive"])
def test_full_api_existing_session_observes_revocation_before_decrypt_or_write(draft_http, change, monkeypatch):
    active = draft_http
    user, row = active.member, active.properties[0]
    headers = active.headers(user)
    saved = active.client.put(ENDPOINT, headers=headers, json=draft_body(user, row))
    assert saved.status_code == 200, saved.text
    before = active.snapshot()
    updates = {"portfolio_access": "selected", "portfolio_ids": []} if change == "portfolio" else {"role": "readonly"} if change == "role" else {"is_active": False}
    auth.update_user(user.id, updates, actor_id=active.owner.id)
    calls = []
    def refused(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Revoked access must be rejected before draft encryption/decryption")
    monkeypatch.setattr(form_draft_crypto, "encrypt", refused)
    monkeypatch.setattr(form_draft_crypto, "decrypt", refused)
    for method in ("get", "put", "delete"):
        if method == "put":
            response = active.client.put(ENDPOINT, headers=headers, json=draft_body(user, row, revision=saved.json()["revision"], name="Forbidden overwrite"))
        else:
            params = draft_query(user, row)
            if method == "delete":
                params["expected_revision"] = saved.json()["revision"]
            response = getattr(active.client, method)(ENDPOINT, headers=headers, params=params)
        assert response.status_code in ({401, 403} if change == "inactive" else {403}), response.text
        assert "Private synthetic draft" not in response.text
    assert calls == []
    assert active.snapshot() == before
    owner_headers = active.headers(active.owner)
    assert active.client.get("/api/v1/properties/" + row.id, headers=owner_headers).json()["name"] == row.name
    active.assert_connections_returned()
