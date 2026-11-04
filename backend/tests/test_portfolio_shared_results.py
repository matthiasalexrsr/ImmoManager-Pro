"""Only pure review/summary responses may share equal current portfolio boundaries."""

import pytest
from test_read_cache_concurrency import cache  # noqa: F401
from test_stress_findings import client, world  # noqa: F401

from backend.auth import create_access_token
from backend.dependencies import store


@pytest.mark.parametrize("endpoint", ["review", "reports/summary"])
def test_pure_results_keep_actor_permissions_and_invalidate_after_writes(client, world, cache, monkeypatch, endpoint):  # noqa: F811
    if not hasattr(store, "db"):
        pytest.skip("Shared results require tracked SQL sessions")
    from backend.routers import reports, review

    owner = world["owner"]
    south = client.post("/api/v1/portfolios", headers=owner, json={"name": "South"}).json()
    south_account = client.post("/api/v1/accounts", headers=owner, json={
        "name": "South account", "account_type": "bank", "portfolio_id": south["id"]}).json()
    north_booking = client.post("/api/v1/bookings", headers=owner, json={
        "account_id": world["account"]["id"], "booking_date": "2025-01-01", "amount": 123}).json()
    south_booking = client.post("/api/v1/bookings", headers=owner, json={
        "account_id": south_account["id"], "booking_date": "2025-01-01", "amount": 987}).json()
    users = []
    for name, portfolio, role in [("north_a", world["pf"], "readonly"),
                                  ("north_b", world["pf"], "readonly"),
                                  ("south", south, "readonly"),
                                  ("north_admin", world["pf"], "verwalter")]:
        created = client.post("/api/v1/auth/users", headers=owner, json={
            "username": name, "email": f"{name}@stress.test", "full_name": name,
            "password": "Secret123!", "role": role, "portfolio_access": "selected",
            "portfolio_ids": [portfolio["id"]]})
        assert created.status_code == 201, created.text
        user_id = created.json()["id"]
        users.append((user_id, {"Authorization": f"Bearer {create_access_token(user_id)}"}))

    module, function = (review, "review_items") if endpoint == "review" else (reports.report_service, "compute_summary")
    original = getattr(module, function)
    calls = []

    def count(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, function, count)

    def read(index):
        response = client.get(f"/api/v1/{endpoint}", headers=users[index][1])
        assert response.status_code == 200, response.text
        return response.json()

    first = read(0)
    assert read(1) == first and len(calls) == 1
    other = read(2)
    assert other != first and len(calls) == 2
    if endpoint == "review":
        assert north_booking["id"] in {item["entity_id"] for item in first["items"]}
        assert south_booking["id"] not in {item["entity_id"] for item in first["items"]}
        assert north_booking["id"] not in {item["entity_id"] for item in other["items"]}
    else:
        assert first["finance"]["bookingsTotal"] == 123
        assert other["finance"]["bookingsTotal"] == 987
    assert read(3) == first and len(calls) == 3, "A different role has a separate result"

    created = client.post("/api/v1/bookings", headers=owner, json={
        "account_id": world["account"]["id"], "booking_date": "2025-01-02", "amount": 7})
    assert created.status_code == 201, created.text
    changed = read(1)
    assert changed != first and len(calls) == 4
    reassigned = client.patch(f"/api/v1/auth/users/{users[1][0]}", headers=owner,
                              json={"portfolio_access": "selected", "portfolio_ids": [south["id"]]})
    assert reassigned.status_code == 200, reassigned.text
    assert read(1) == other and len(calls) == 5, "An existing token uses its new assignment immediately"


@pytest.mark.parametrize("endpoint", ["account", "current-rents"])
def test_rent_results_share_only_the_same_visible_contracts(client, world, cache, monkeypatch, endpoint):  # noqa: F811
    if not hasattr(store, "db"):
        pytest.skip("Shared results require tracked SQL sessions")
    from backend.routers import contracts, tenants

    owner = world["owner"]
    south = client.post("/api/v1/portfolios", headers=owner, json={"name": "South"}).json()
    prop = client.post("/api/v1/properties", headers=owner, json={
        "name": "South house", "property_type": "residential", "portfolio_id": south["id"]}).json()
    unit = client.post("/api/v1/units", headers=owner, json={
        "property_id": prop["id"], "label": "South unit", "unit_type": "Wohnung", "cold_rent": 333}).json()
    south_contract = client.post("/api/v1/contracts", headers=owner, json={
        "contract_number": "S-1", "property_id": prop["id"], "unit_id": unit["id"],
        "tenant_id": world["tenant"]["id"], "start_date": "2024-01-01"}).json()
    assert "id" in south_contract, south_contract
    users = []
    for name, portfolio in [("north_a", world["pf"]), ("north_b", world["pf"]), ("south", south)]:
        created = client.post("/api/v1/auth/users", headers=owner, json={
            "username": name, "email": f"{name}@stress.test", "full_name": name,
            "password": "Secret123!", "role": "readonly", "portfolio_access": "selected",
            "portfolio_ids": [portfolio["id"]]})
        assert created.status_code == 201, created.text
        identifier = created.json()["id"]
        users.append((identifier, {"Authorization": f"Bearer {create_access_token(identifier)}"}))
    module, function = (tenants, "tenant_account") if endpoint == "account" else (contracts, "charge_for")
    original = getattr(module, function)
    calls = []

    def count(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, function, count)
    path = f"/tenants/{world['tenant']['id']}/account" if endpoint == "account" else "/contracts/current-rents"

    def read(index):
        response = client.get(f"/api/v1{path}?as_of=2026-06-30", headers=users[index][1])
        assert response.status_code == 200, response.text
        return response.json()

    def contract_ids(value):
        return {row["contract_id"] for row in value["contracts"]} if endpoint == "account" else set(value)

    first = read(0)
    assert contract_ids(first) == {world["contract"]["id"]}
    assert read(1) == first and len(calls) == 1
    other = read(2)
    assert contract_ids(other) == {south_contract["id"]} and len(calls) == 2
    new_unit = client.post("/api/v1/units", headers=owner, json={
        "property_id": world["other"]["id"], "label": "Second north unit", "unit_type": "Wohnung",
        "cold_rent": 800}).json()
    new_contract = client.post("/api/v1/contracts", headers=owner, json={
        "contract_number": "N-2", "property_id": world["other"]["id"], "unit_id": new_unit["id"],
        "tenant_id": world["tenant"]["id"], "start_date": "2024-01-01"}).json()
    assert "id" in new_contract, new_contract
    assert contract_ids(read(1)) == {world["contract"]["id"], new_contract["id"]}
    reassigned = client.patch(f"/api/v1/auth/users/{users[1][0]}", headers=owner,
                              json={"portfolio_access": "selected", "portfolio_ids": [south["id"]]})
    assert reassigned.status_code == 200, reassigned.text
    assert read(1) == other


def test_summary_owner_filters_remain_part_of_shared_arguments(client, world, cache):  # noqa: F811
    owner = world["owner"]
    contacts = []
    for name, percentage in [("Alpha", 20), ("Beta", 80)]:
        contact = client.post("/api/v1/contacts", headers=owner, json={
            "contact_type": "owner", "last_name": name}).json()
        share = client.post("/api/v1/ownership-shares", headers=owner, json={
            "property_id": world["prop"]["id"], "owner_contact_id": contact["id"],
            "share_percent": percentage, "valid_from": "2024-01-01"})
        assert share.status_code == 201, share.text
        contacts.append(contact)
    booked = client.post("/api/v1/bookings", headers=owner, json={
        "account_id": world["account"]["id"], "property_id": world["prop"]["id"],
        "booking_date": "2025-01-01", "amount": 100})
    assert booked.status_code == 201, booked.text
    second = client.post("/api/v1/auth/users", headers=owner, json={
        "username": "second_owner", "email": "second_owner@stress.test", "full_name": "Second owner",
        "password": "Secret123!", "role": "eigentuemer", "portfolio_access": "all"})
    assert second.status_code == 201, second.text
    second_headers = {"Authorization": f"Bearer {create_access_token(second.json()['id'])}"}
    for headers, contact, expected in [(owner, contacts[0], 20), (second_headers, contacts[1], 80),
                                       (second_headers, contacts[0], 20)]:
        response = client.get(f"/api/v1/reports/summary?owner_contact_id={contact['id']}&as_of=2026-06-30",
                              headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["finance"]["bookingsTotal"] == expected
