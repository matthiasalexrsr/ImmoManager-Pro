"""Host boundary probes run in an independent test account/store."""

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import PortfolioCreate, PropertyCreate


@pytest.fixture(autouse=True)
def clean_accounts_and_records():
    auth.clear_users()
    store.clear_all()
    yield
    auth.clear_users()
    store.clear_all()


def test_untrusted_host_cannot_claim_first_owner():
    with TestClient(app, base_url="http://rebinding.example.invalid") as client:
        response = client.post("/api/v1/auth/register", json={
            "username": "synthetic-claim", "email": "claim@example.invalid",
            "full_name": "Own security fixture", "password": "Birke7Fenster",
        })
    assert response.status_code == 400
    assert not auth.has_users()


@pytest.mark.parametrize("origin", ["https://foreign.example.invalid", "null"])
def test_cross_site_json_without_content_type_cannot_claim_owner(origin):
    # A Blob with an empty MIME type can carry JSON without a CORS preflight.
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/register", headers={"Origin": origin}, content=(
            '{"username":"blind-claim","email":"blind@example.invalid",'
            '"full_name":"Own fixture","password":"Birke7Fenster"}'
        ))
    assert response.status_code == 403
    assert not auth.has_users()


@pytest.mark.parametrize("host", ["testserver?", "testserver/", "testserver/#"])
def test_malformed_host_never_bypasses_read_only_role(host):
    user = auth.register_user("scope-read", "read@example.invalid", "Reader", "Birke7Fenster", "readonly")
    portfolio = store.create_portfolio(PortfolioCreate(name="Own security fixture"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Unchanged", property_type="residential"))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch(f"/api/v1/properties/{prop.id}", json={"name": "Unexpected change"},
                                headers={"Host": host, "Authorization": "Bearer " + auth.create_access_token(user.id)})
    assert response.status_code in (400, 403)
    assert store.get_property(prop.id).name == "Unchanged"
