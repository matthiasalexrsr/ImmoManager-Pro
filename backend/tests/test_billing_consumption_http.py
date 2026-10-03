"""Real authenticated HTTP, Memory and fully migrated SQLite; synthetic data."""

from datetime import date

import pytest

from backend.models import StandaloneMeterReadingCreate
from backend.routers import billing, contracts, meters_standalone, tenants, units
from backend.services.portfolio_scope import scope_context
from backend.tests.test_form_drafts_http import draft_http  # noqa: F401


@pytest.fixture
def context(draft_http, monkeypatch):  # noqa: F811
    active = draft_http
    for router in (billing, contracts, meters_standalone, tenants, units):
        monkeypatch.setattr(router, "store", active.store)
    headers = active.headers(active.owner)

    def post(path, payload):
        response = active.client.post("/api/v1" + path, json=payload, headers=headers)
        assert response.status_code in {200, 201}, response.text
        return response.json()

    def patch(path, payload):
        opened = active.client.get("/api/v1" + path, headers=headers)
        assert opened.status_code == 200, opened.text
        response = active.client.patch("/api/v1" + path, json=payload,
            headers={**headers, "If-Match": opened.headers["etag"]})
        assert response.status_code == 200, response.text
        return response.json()

    property_id = active.properties[0].id
    homes, leases = [], []
    for number in range(2):
        home = post("/units", {"property_id": property_id, "label": f"Synthetic {number}",
            "unit_type": "Wohnung", "area_sqm": 50, "rooms": 3})
        tenant = post("/tenants", {"full_name": f"Synthetic occupant {number}"})
        lease = post("/contracts", {"property_id": property_id, "unit_id": home["id"],
            "tenant_id": tenant["id"], "contract_number": f"TEST-{number}", "start_date": "2026-01-01"})
        homes.append(home)
        leases.append(lease)
    period = post("/billing/periods", {"property_id": property_id, "label": "Synthetic 2026",
        "start_date": "2026-01-01", "end_date": "2026-12-31"})

    def key(medium="cold_water", measurement="m³", amount=100):
        row = post("/billing/allocation-keys", {"property_id": property_id, "name": "Explicit basis",
            "key_type": "consumption", "consumption_medium": medium, "consumption_unit": measurement})
        post("/billing/cost-items", {"billing_period_id": period["id"], "description": "Synthetic cost",
            "amount": amount, "allocation_key_id": row["id"]})
        return row

    def meter(home, delta=10, *, medium="cold_water", measurement="m³", active_now=True,
              start="2026-01-01", end="2026-12-31"):
        row = post("/meters", {"unit_id": home["id"], "meter_type": medium,
            "measurement_unit": measurement, "is_active": active_now})
        for day, value in ((start, 100), (end, 100 + delta)):
            post(f"/meters/{row['id']}/readings", {"meter_id": row["id"], "reading_date": day, "value": value})
        return row

    def preflight():
        response = active.client.get(f"/api/v1/billing/periods/{period['id']}/preflight", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    def generate():
        return active.client.post(f"/api/v1/billing/periods/{period['id']}/generate", headers=headers)

    yield dict(active=active, headers=headers, post=post, patch=patch, homes=homes,
        leases=leases, period=period, key=key, meter=meter, preflight=preflight, generate=generate)
    active.assert_connections_returned()


def assert_blocked(context, code):
    review = context["preflight"]()
    assert review["has_blockers"]
    assert code in {issue["code"] for issue in review["blockers"]}, review
    assert context["generate"]().status_code == 400
    response = context["active"].client.get("/api/v1/billing/statements", headers=context["headers"])
    assert response.status_code == 200 and response.json() == []


def test_water_distribution_does_not_include_electricity_and_each_key_keeps_its_basis(context):
    context["key"]()
    for home in context["homes"]:
        context["meter"](home, 10)
    context["meter"](context["homes"][0], 1000, medium="electricity", measurement="kWh")
    context["meter"](context["homes"][1], 0, medium="electricity", measurement="kWh")
    assert not context["preflight"]()["has_blockers"]
    response = context["generate"]()
    assert response.status_code == 201, response.text
    assert {row["total_cost"] for row in response.json()} == {50}
    context["key"]("electricity", "kWh", 200)
    response = context["generate"]()
    assert response.status_code == 201, response.text
    assert {row["unit_id"]: row["total_cost"] for row in response.json()} == {
        context["homes"][0]["id"]: 250, context["homes"][1]["id"]: 50,
    }


def test_unknown_binding_is_saved_and_can_be_repaired_without_guessing_names(context):
    key = context["key"](None, None)
    for home in context["homes"]:
        context["meter"](home)
    assert_blocked(context, "MISSING_CONSUMPTION_BINDING")
    corrected = context["patch"](f"/billing/allocation-keys/{key['id']}",
        {"consumption_medium": "cold_water", "consumption_unit": "m³"})
    assert corrected["consumption_medium"] == "cold_water" and corrected["consumption_unit"] == "m³"
    assert context["generate"]().status_code == 201


@pytest.mark.parametrize("measurement,code", [(None, "MISSING_METER_UNIT"), ("litre", "CONSUMPTION_UNIT_MISMATCH")])
def test_missing_or_mixed_measurement_units_block_and_are_editable(context, measurement, code):
    context["key"]()
    context["meter"](context["homes"][0])
    wrong = context["meter"](context["homes"][1], measurement=measurement)
    assert_blocked(context, code)
    context["patch"](f"/meters/{wrong['id']}", {"measurement_unit": "m³"})
    assert context["generate"]().status_code == 201


def test_no_medium_is_inferred_from_key_name_or_cost_description(context):
    context["key"]("water", "m³")
    for home in context["homes"]:
        context["meter"](home, medium="cold_water")
    assert_blocked(context, "MISSING_CONSUMPTION_METER")


def test_individual_zero_consumption_is_valid(context):
    context["key"]()
    first = context["meter"](context["homes"][0], 0)
    context["meter"](context["homes"][1], 20)
    response = context["generate"]()
    assert response.status_code == 201, response.text
    assert {row["unit_id"]: row["total_cost"] for row in response.json()} == {
        first["unit_id"]: 0, context["homes"][1]["id"]: 100,
    }


def test_all_zero_requires_an_explicit_alternative_allocation(context):
    context["key"]()
    for home in context["homes"]:
        context["meter"](home, 0)
    assert_blocked(context, "ZERO_CONSUMPTION_TOTAL")


def test_historical_inactive_meter_with_complete_boundaries_remains_included(context):
    context["key"]()
    context["meter"](context["homes"][0], 10, active_now=False)
    context["meter"](context["homes"][1], 10)
    response = context["generate"]()
    assert response.status_code == 201, response.text
    assert {row["total_cost"] for row in response.json()} == {50}


def test_incomplete_boundaries_and_negative_deltas_are_explicit(context):
    context["key"]()
    context["meter"](context["homes"][0], -10)
    context["meter"](context["homes"][1], 10, start="2026-02-01")
    assert_blocked(context, "CONSUMPTION_READING_DECREASE")
    assert "MISSING_CONSUMPTION_BOUNDARY" in {issue["code"] for issue in context["preflight"]()["blockers"]}


def test_ambiguous_same_day_readings_do_not_pick_an_arbitrary_record(context):
    context["key"]()
    first = context["meter"](context["homes"][0])
    context["meter"](context["homes"][1])
    context["post"](f"/meters/{first['id']}/readings", {"meter_id": first["id"],
        "reading_date": "2026-12-31", "value": 999})
    assert_blocked(context, "AMBIGUOUS_CONSUMPTION_READING")


def test_nonfinite_legacy_reading_is_an_explained_blocker(context):
    context["key"]()
    first = context["meter"](context["homes"][0])
    context["meter"](context["homes"][1])
    active = context["active"]
    with scope_context(None):
        active.store.create_standalone_meter_reading(StandaloneMeterReadingCreate(
            meter_id=first["id"], reading_date=date(2026, 6, 1), value=float("inf")))
        if active.engine is not None:
            active.store.db.remove()
    assert_blocked(context, "INVALID_CONSUMPTION_READING")


def test_rooms_never_replace_the_actual_resident_count(context):
    key = context["key"]()
    context["patch"](f"/billing/allocation-keys/{key['id']}", {"key_type": "person_count"})
    assert_blocked(context, "MISSING_PERSON_COUNT")
    for home, people in zip(context["homes"], (1, 3), strict=True):
        context["patch"](f"/units/{home['id']}", {"person_count": people})
    response = context["generate"]()
    assert response.status_code == 201, response.text
    assert {row["unit_id"]: row["total_cost"] for row in response.json()} == {
        context["homes"][0]["id"]: 25, context["homes"][1]["id"]: 75,
    }


def test_changed_measurement_unit_invalidates_draft_and_finalized_originals_stay_unchanged(context):
    context["key"]()
    meters = [context["meter"](home) for home in context["homes"]]
    assert context["generate"]().status_code == 201
    context["patch"](f"/meters/{meters[0]['id']}", {"measurement_unit": "litre"})
    active = context["active"]
    final_path = f"/api/v1/billing/periods/{context['period']['id']}/finalize"
    assert active.client.post(final_path, headers=context["headers"]).status_code == 400
    context["patch"](f"/meters/{meters[0]['id']}", {"measurement_unit": "m³"})
    # Even a repaired declaration is a new source revision and needs regeneration.
    assert active.client.post(final_path, headers=context["headers"]).status_code == 409
    assert context["generate"]().status_code == 201
    finalized = active.client.post(final_path, headers=context["headers"])
    assert finalized.status_code == 200, finalized.text
    persisted = active.client.get(final_path.removesuffix("/finalize"), headers=context["headers"])
    assert persisted.status_code == 200, persisted.text
    before = active.client.get("/api/v1/billing/statements", headers=context["headers"]).json()
    context["patch"](f"/meters/{meters[0]['id']}", {"measurement_unit": "litre"})
    assert active.client.get("/api/v1/billing/statements", headers=context["headers"]).json() == before
    assert active.client.post(final_path, headers=context["headers"]).json() == persisted.json()


def test_under_year_installation_requires_its_own_evidence_basis(context):
    context["key"]()
    first = context["meter"](context["homes"][0])
    context["meter"](context["homes"][1])
    context["patch"](f"/meters/{first['id']}", {"installation_date": "2026-02-01"})
    assert_blocked(context, "CONSUMPTION_METER_CHANGE_BASIS_MISSING")


def test_foreign_scope_cannot_read_another_objects_binding(context):
    key = context["key"]()
    active = context["active"]
    assert active.client.get(f"/api/v1/billing/periods/{context['period']['id']}/preflight").status_code == 401
    # The peer is deliberately restricted to the first portfolio. A source in
    # the second portfolio must stay outside its visible/readable graph.
    foreign = context["post"]("/billing/allocation-keys", {"property_id": active.properties[1].id,
        "name": "Private foreign key", "key_type": "consumption"})
    response = active.client.get(f"/api/v1/billing/allocation-keys/{foreign['id']}", headers=active.headers(active.peer))
    assert response.status_code == 404
    own = active.client.get(f"/api/v1/billing/allocation-keys/{key['id']}", headers=context["headers"])
    assert own.status_code == 200


def test_tenant_turnover_cannot_silently_split_yearly_consumption_by_days(context):
    context["key"]()
    for home in context["homes"]:
        context["meter"](home)
    first = context["leases"][0]
    context["patch"](f"/contracts/{first['id']}", {"end_date": "2026-06-30"})
    new_tenant = context["post"]("/tenants", {"full_name": "Synthetic successor"})
    context["post"]("/contracts", {"property_id": first["property_id"], "unit_id": first["unit_id"],
        "tenant_id": new_tenant["id"], "contract_number": "TEST-successor", "start_date": "2026-07-01"})
    assert_blocked(context, "CONSUMPTION_TENANCY_BASIS_MISSING")
