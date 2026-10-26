"""Regression tests for independently reproduced access and second-factor defects."""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally injected by name
import base64
import hashlib
import hmac
import struct
import time
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_ai_reading import INVOICE, _pdf, _upload, case  # noqa: F401

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import DocumentCreate


def otp(secret):
    digest = hmac.new(base64.b32decode(secret), struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return str((struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1000000).zfill(6)


def test_unknown_reading_surface_is_client_error(case):
    with TestClient(app, raise_server_exceptions=False, headers=case["clients"]["eigentuemer"].headers) as client:
        response = client.get("/api/v1/ai/readings/options?surface=does-not-exist")
    assert response.status_code == 404, (response.status_code, response.text)


@pytest.mark.parametrize("operation", ["read", "start-replay", "message", "decision", "finish"])
def test_revoked_portfolio_also_revokes_stored_reading(case, operation):
    actor = case["users"]["buchhaltung"]
    client = case["clients"]["buchhaltung"]
    document = store.create_document(
        DocumentCreate(
            title="Private Audit Invoice",
            document_type="invoice",
            property_id=case["property"].id,
            file_url=_upload(_pdf(INVOICE)),
        )
    )
    start_command = {
        "surface": "invoice",
        "document_id": document.id,
        "reader": "local",
        "params": {"property_id": case["property"].id},
        "idempotency_key": uuid4().hex,
    }
    response = client.post("/api/v1/ai/readings", json=start_command)
    assert response.status_code == 201, response.text
    reading = response.json()
    assert reading["values"]["iban"]["value"] == "DE89370400440532013000"
    auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
    denied = client.get(f"/api/v1/documents/{document.id}")
    assert denied.status_code in (403, 404), denied.text
    path = f"/api/v1/ai/readings/{reading['id']}"
    command = {"expected_revision": reading["revision"], "idempotency_key": uuid4().hex}
    if operation == "read":
        leaked = client.get(path)
    elif operation == "start-replay":
        leaked = client.post("/api/v1/ai/readings", json=start_command)
    elif operation == "message":
        leaked = client.post(path + "/messages", json={**command, "text": "Einlesen"})
    elif operation == "decision":
        leaked = client.post(path + "/decision", json={**command, "action": "create_new"})
    else:
        leaked = client.post(path + "/finish", json={**command, "outcome": "cancelled"})
    assert leaked.status_code in (403, 404), (leaked.status_code, leaked.json().get("values"))


def test_enabled_totp_cannot_be_replaced_without_current_factor(case):
    client = case["clients"]["eigentuemer"]
    setup = client.post("/api/v1/auth/2fa/setup", json={})
    assert setup.status_code == 200, setup.text
    original = setup.json()["secret"]
    enabled = client.post("/api/v1/auth/2fa/verify", json={"code": otp(original)})
    assert enabled.status_code == 200, enabled.text
    replacement = client.post("/api/v1/auth/2fa/setup", json={})
    bypassed = (
        client.post("/api/v1/auth/2fa/disable", json={"code": otp(replacement.json()["secret"])})
        if replacement.status_code == 200
        else None
    )
    assert replacement.status_code in (400, 403, 409), (
        replacement.status_code,
        "old factor silently replaced",
        "disable using replacement",
        None if bypassed is None else (bypassed.status_code, bypassed.json()),
    )


def test_totp_login_supported_by_browser_client(case):
    client = case["clients"]["eigentuemer"]
    setup = client.post("/api/v1/auth/2fa/setup", json={}).json()
    assert client.post("/api/v1/auth/2fa/verify", json={"code": otp(setup["secret"])}).status_code == 200
    payload = {"username": case["users"]["eigentuemer"].username, "password": "Secret123"}
    with TestClient(app) as public:
        rejected = public.post("/api/v1/auth/login", json=payload)
        assert rejected.status_code == 401 and "Zwei-Faktor" in rejected.text, rejected.text
        accepted = public.post("/api/v1/auth/login", json={**payload, "totp_code": otp(setup["secret"])})
        assert accepted.status_code == 200, accepted.text


def test_required_totp_signal_survives_error_handler(case):
    client = case["clients"]["eigentuemer"]
    setup = client.post("/api/v1/auth/2fa/setup", json={}).json()
    assert client.post("/api/v1/auth/2fa/verify", json={"code": otp(setup["secret"])}).status_code == 200
    with TestClient(app) as public:
        response = public.post(
            "/api/v1/auth/login", json={"username": case["users"]["eigentuemer"].username, "password": "Secret123"}
        )
    assert response.status_code == 401 and "Zwei-Faktor" in response.text
    assert response.headers.get("x-2fa-required") == "true", "HTTPException.headers is discarded"


def test_totp_disable_clears_secret_and_rejects_stale_factor_updates(case):
    client = case["clients"]["eigentuemer"]
    user_id = case["users"]["eigentuemer"].id
    secret = client.post("/api/v1/auth/2fa/setup").json()["secret"]
    assert client.post("/api/v1/auth/2fa/verify", json={"code": otp(secret)}).status_code == 200
    with pytest.raises(HTTPException) as rejected:
        auth.update_totp(
            user_id, expected_secret=secret, expected_enabled=False, secret=auth.generate_totp_secret(), enabled=False
        )
    assert rejected.value.status_code == 409
    account = auth.get_user_by_id(user_id)
    assert account is not None and account["totp_secret"] == secret
    assert client.post("/api/v1/auth/2fa/disable", json={"code": otp(secret)}).status_code == 200
    account = auth.get_user_by_id(user_id)
    assert account is not None and account["totp_secret"] is None and account["totp_enabled"] is False
    with pytest.raises(HTTPException) as rejected:
        auth.update_totp(user_id, expected_secret=secret, expected_enabled=True, secret=secret, enabled=True)
    assert rejected.value.status_code == 409


def test_revocation_during_reader_call_prevents_new_reading_response(case, monkeypatch):
    from backend.services import ai_reading

    actor = case["users"]["buchhaltung"]
    client = case["clients"]["buchhaltung"]
    document = store.create_document(
        DocumentCreate(
            title="Revoked while reading",
            document_type="invoice",
            property_id=case["property"].id,
            file_url=_upload(_pdf(INVOICE)),
        )
    )
    original = ai_reading._read

    def revoke_after_read(*args, **kwargs):
        result = original(*args, **kwargs)
        auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
        return result

    monkeypatch.setattr(ai_reading, "_read", revoke_after_read)
    response = client.post(
        "/api/v1/ai/readings",
        json={"surface": "invoice", "document_id": document.id, "reader": "local", "idempotency_key": uuid4().hex},
    )
    assert response.status_code in (403, 404), response.text


def test_scope_change_invalidates_cached_context_even_if_source_stays_visible(case):
    actor = case["users"]["buchhaltung"]
    client = case["clients"]["buchhaltung"]
    document = store.create_document(
        DocumentCreate(
            title="Still visible source",
            document_type="invoice",
            property_id=case["property"].id,
            file_url=_upload(_pdf(INVOICE)),
        )
    )
    response = client.post(
        "/api/v1/ai/readings",
        json={"surface": "invoice", "document_id": document.id, "reader": "local", "idempotency_key": uuid4().hex},
    )
    assert response.status_code == 201, response.text
    reading = response.json()
    auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": [case["property"].portfolio_id]})
    assert client.get(f"/api/v1/documents/{document.id}").status_code == 200
    assert client.get(f"/api/v1/ai/readings/{reading['id']}").status_code == 404
