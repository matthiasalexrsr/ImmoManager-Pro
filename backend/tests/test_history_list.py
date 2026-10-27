"""The history page reads which record changed, where it opens and who changed it."""

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.services.data_snapshot import clear_business_data

API = "/api/v1"


@pytest.fixture(autouse=True)
def _clean():
    clear_business_data(store)
    auth.clear_users()
    yield
    clear_business_data(store)
    auth.clear_users()


@pytest.fixture
def client():
    user = auth.register_user("linda.reiser", "linda@example.com", "Linda Reiser", "Secret123", "eigentuemer")
    return TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})


@pytest.mark.parametrize("endpoint", ["/history?limit=50", "/history/page?limit=50"])
def test_a_change_names_its_record_page_and_author(client, endpoint):
    kept = client.post(f"{API}/contacts", json={"contact_type": "supplier", "company_name": "Dachdeckerei Kunze"}).json()
    gone = client.post(f"{API}/contacts", json={"contact_type": "supplier", "company_name": "Maler Weiß"}).json()
    assert client.patch(f"{API}/contacts/{kept['id']}", json={"notes": "Gewerk: Dach"}).status_code == 200
    assert client.patch(f"{API}/contacts/{gone['id']}", json={"notes": "Gewerk: Maler"}).status_code == 200
    assert client.delete(f"{API}/contacts/{gone['id']}").status_code in (200, 204)

    rows = client.get(f"{API}{endpoint}")
    assert rows.status_code == 200, rows.text
    items = rows.json()["items"] if "/page?" in endpoint else rows.json()
    by_record = {row["entity_id"]: row for row in items if row["field_name"] == "notes"}
    shown = by_record[kept["id"]]
    assert shown["entity_title"] == "Dachdeckerei Kunze"
    assert shown["entity_href"].startswith("/contacts") and kept["id"] in shown["entity_href"]
    assert shown["changed_by_name"] == "Linda Reiser"
    assert (shown["old_value"], shown["new_value"]) == (None, "Gewerk: Dach")
    # a deleted record keeps its change, without a page to open
    assert by_record[gone["id"]]["entity_title"] is None and by_record[gone["id"]]["entity_href"] is None


def test_the_history_pages_newest_first_and_filters(client):
    contact = client.post(f"{API}/contacts", json={"contact_type": "supplier", "company_name": "Kunze"}).json()
    for note in ("eins", "zwei", "drei"):
        assert client.patch(f"{API}/contacts/{contact['id']}", json={"notes": note}).status_code == 200
    first = client.get(f"{API}/history?entity_type=contact&entity_id={contact['id']}&limit=2").json()
    second = client.get(f"{API}/history?entity_type=contact&entity_id={contact['id']}&skip=2&limit=2").json()
    notes = [row["new_value"] for row in first + second if row["field_name"] == "notes"]
    assert notes == ["drei", "zwei", "eins"]
    assert client.get(f"{API}/history?entity_type=unit").json() == []
