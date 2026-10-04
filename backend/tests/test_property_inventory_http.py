"""Mounted inventory routes use genuine request registries and native users."""

import csv
import io

from backend.tests.test_portfolio_access_http import access_http as access_http


def test_mounted_property_inventory_uses_actual_request_registry(access_http):
    client, _, owner, member, _, _, properties, *_ = access_http
    params = {"as_of": "2026-10-04", "page_size": 1}
    prefix = "/api/v1/properties/inventory/"
    for operation in ("page", "summary", "export"):
        assert client.get(prefix + operation, params=params).status_code == 401
    response = client.get(prefix + "page", params=params, headers=member)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Authorization"
    assert [row["id"] for row in response.json()["items"]] == [properties[0].id]
    assert response.json()["as_of"] == "2026-10-04"
    assert response.json()["has_more"] is False
    summary = client.get(prefix + "summary", params=params, headers=member)
    assert summary.status_code == 200, summary.text
    assert summary.json()["scope_totals"]["property_count"] == 1
    assert summary.json()["matching_totals"]["property_count"] == 1
    exported = client.get(prefix + "export", params=params, headers=member)
    assert exported.status_code == 200, exported.text
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig")), delimiter=";"))
    assert [row["id"] for row in rows] == [properties[0].id]
    assert properties[1].id not in exported.text
    assert "_rent_cents" not in rows[0]
    owner_summary = client.get(prefix + "summary", params=params, headers=owner)
    assert owner_summary.status_code == 200, owner_summary.text
    assert owner_summary.json()["scope_totals"]["property_count"] == 2
    # Existing CRUD remains reachable beside the additive inventory paths.
    assert client.get(f"/api/v1/properties/{properties[0].id}", headers=member).status_code == 200
    assert isinstance(client.get("/api/v1/properties", headers=member).json(), list)
    for bad in ({}, {**params, "unknown": "value"}, {**params, "sort_by": "not_a_column"}):
        assert client.get(prefix + "page", params=bad, headers=member).status_code == 422
