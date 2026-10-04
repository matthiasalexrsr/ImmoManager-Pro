"""Real SQL authentication and encrypted runtime HTTP composition."""

import pytest
from sqlalchemy import text

from backend import auth
from backend.db.integration_history_models import TABLES
from backend.services.iban_encryption import generate_key
from backend.services.integrations.runtime_factory import configured_runtime_store, initialize_new
from backend.tests.test_integration_private_boundary import private_manager as private_manager
from backend.tests.test_portfolio_access_http import access_http as access_http


@pytest.mark.parametrize("access_http", ["sql"], indirect=True)
def test_real_sql_login_cipher_cas_and_missing_state_refuse_before_provider(access_http, private_manager, tmp_path, monkeypatch):
    client, _, _, _, *_ = access_http
    path = tmp_path / "explicit-native-integrations.json"
    values = {"INTEGRATION_STATE_FILE": str(path), "ENCRYPTION_KEY": generate_key(),
              "ENCRYPTION_INDEX_KEY": generate_key(), "ENCRYPTION_ACTIVE_KEY_ID": "default"}
    initialize_new(values)
    private_manager._store = configured_runtime_store(values)
    private_manager._store.update(lambda state: {**state, "unknown": {"nested": ["SYNTHETIC_UNKNOWN"]}})
    private_manager.update_config("email", {"smtp_password": "SYNTHETIC_NATIVE_CIPHER_SECRET"})

    def login(name):
        response = client.post("/api/v1/auth/login", json={"username": name, "password": "StrongPass123!"})
        assert response.status_code == 200
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    owner, member = login("owner"), login("member")
    endpoint = "/api/v1/integrations/email/connection-state"
    current = client.get(endpoint, headers=owner)
    assert current.status_code == 200
    assert current.json()["config"]["smtp_password"] == "***"
    assert "SYNTHETIC_NATIVE_CIPHER_SECRET" not in current.text
    revision = current.json()["revision"]
    changed = client.patch(endpoint, headers=owner,
        json={"expected_revision": revision, "enabled": True, "config": {"smtp_password": "***"}})
    assert changed.status_code == 200
    assert changed.json()["revision"] != revision
    original = path.read_bytes()
    stale = client.patch(endpoint, headers=owner,
        json={"expected_revision": revision, "config": {"smtp_password": "stale-attempt"}})
    assert stale.status_code == 412
    assert stale.json()["detail"]["code"] == "state_revision_conflict"
    assert stale.json()["error"]["code"] == "state_revision_conflict"
    assert stale.json()["error"]["message"] == stale.json()["detail"]["message"]
    assert stale.json()["error"]["request_id"] != "-"
    assert stale.headers["cache-control"] == "private, no-store"
    assert "authorization" in stale.headers["vary"].lower()
    assert path.read_bytes() == original
    raw = configured_runtime_store(values).load()
    assert raw["config"]["email"]["smtp_password"] == "SYNTHETIC_NATIVE_CIPHER_SECRET"
    assert raw["unknown"] == {"nested": ["SYNTHETIC_UNKNOWN"]}
    assert b"SYNTHETIC_NATIVE_CIPHER_SECRET" not in original
    assert client.get(endpoint, headers=member).status_code == 403
    assert client.patch(endpoint, headers=member,
        json={"expected_revision": changed.json()["revision"], "enabled": False}).status_code == 403
    assert path.read_bytes() == original

    def journal_counts():
        with auth._user_store._session_factory() as session:
            return {table: session.scalar(text(f'SELECT count(*) FROM "{table}"')) for table in TABLES}

    before = journal_counts()
    provider_reached = False
    def forbidden_provider(*_args, **_kwargs):
        nonlocal provider_reached
        provider_reached = True
        raise AssertionError("Missing encrypted state reached a provider")

    monkeypatch.setattr(private_manager._providers["email"], "run", forbidden_provider)
    path.unlink()  # Only this explicitly owned temporary fixture state.
    for method, route, payload in (("GET", endpoint, None),
        ("PATCH", endpoint, {"expected_revision": changed.json()["revision"], "enabled": False}),
        ("POST", "/api/v1/integrations/email/run", {"payload": {}})):
        result = client.request(method, route, headers=owner, **({"json": payload} if payload is not None else {}))
        assert result.status_code == 503
        assert result.json()["detail"]["code"] == "state_missing"
        assert result.json()["error"]["code"] == "state_missing"
        assert result.headers["cache-control"] == "private, no-store"
        assert "authorization" in result.headers["vary"].lower()
        assert "SYNTHETIC_NATIVE_CIPHER_SECRET" not in result.text
        assert not path.exists()
    assert journal_counts() == before
    assert not provider_reached
