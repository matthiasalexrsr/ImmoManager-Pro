"""A search hit opens the record it found, not the bare list."""

from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import TenantCreate
from backend.services import global_search as gs
from backend.services.data_snapshot import clear_business_data


def test_every_search_type_links_its_record():
    record = SimpleNamespace(id="a1/b 2")
    for spec in gs.SEARCH_TYPES:
        url = spec.url(record)
        assert url.startswith("/") and quote(record.id, safe="") in url, (spec.entity_type, url)
    assert gs.TYPES_BY_NAME["booking"].url(record) == "/bookings?booking_id=a1%2Fb%202"
    assert gs.TYPES_BY_NAME["deposit"].url(record) == "/deposits?deposit_id=a1%2Fb%202"
    assert gs.TYPES_BY_NAME["maintenance"].url(record) == "/maintenance/a1%2Fb%202"


@pytest.fixture
def client():
    clear_business_data(store)
    auth.clear_users()
    user = auth.register_user("linda.reiser", "linda@example.com", "Linda Reiser", "Secret123", "eigentuemer")
    yield TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})
    clear_business_data(store)
    auth.clear_users()


def test_a_found_tenant_opens_in_the_tenant_list(client):
    tenant = store.create_tenant(TenantCreate(full_name="Mia Muster"))
    hits = client.get("/api/v1/search", params={"q": "Mia Muster", "semantic": False}).json()["results"]
    assert [hit["url"] for hit in hits if hit["entity_type"] == "tenant"] == [f"/tenants?focus_id={tenant.id}"]
