"""Real composed authenticated API; only synthetic records and owned databases."""

from copy import deepcopy

import pytest
from sqlalchemy import create_engine

from backend.tests.form_draft_api_support import application, migrate
from backend.tests.test_billing_consumption_http import context as context_fixture

context = context_fixture

BASE = "/api/v1/billing/measurement-history/units/"


@pytest.fixture(params=["memory", "sqlite", "postgres"])
def draft_http(request, monkeypatch, tmp_path):
    if request.param == "postgres":
        from backend.tests.measurement_history_postgres_support import migrated_postgres
        with migrated_postgres(monkeypatch) as (native_engine, _config), application(monkeypatch, native_engine) as active:
            yield active
        return
    engine = None
    if request.param == "sqlite":
        url = "sqlite:///" + (tmp_path / "measurement-api.sqlite").as_posix()
        assert migrate(url, monkeypatch) == "g2a2b3c4d5e6"
        engine = create_engine(url, hide_parameters=True, connect_args={"check_same_thread": False})
    try:
        with application(monkeypatch, engine) as active:
            yield active
    finally:
        if engine is not None:
            engine.dispose()


def fact(source, kind, **data):
    return {"source_key": source, "reason": "Synthetisches Original geprüft", "data": {"kind": kind, **data}}


def span(**values):
    return {"valid_from": "2026-01-01", "valid_until": "2027-01-01", **values}


def confirm(context, home, changes, revision=0, command="first", status=200):
    response = context["active"].client.post(BASE + home["id"] + "/confirm", headers=context["headers"],
        json={"expected_revision": revision, "idempotency_key": home["id"] + command, "changes": changes})
    assert response.status_code == status, response.text
    return response


def source_rows(context, home):
    response = context["active"].client.get(BASE + home["id"], headers=context["headers"],
        params={"start": "2026-01-01", "end": "2027-01-01"})
    assert response.status_code == 200, response.text
    return response.json()


def standard(context, home, key, contract, delta=10):
    meter = context["meter"](home)
    return [
        fact("assignment", "assignment", **span(), meter_id=meter["id"], medium="cold_water", measurement_unit="m³", circuit_path=["water"]),
        fact("start", "reading", assignment_key="assignment", boundary_date="2026-01-01", value="100"),
        fact("end", "reading", assignment_key="assignment", boundary_date="2027-01-01", value=str(100 + delta)),
        fact("occupancy", "occupancy", **span(), contract_id=contract["id"], persons=2),
        fact("selection", "selection", **span(), allocation_key_id=key["id"], basis="consumption", circuits=[["water"]], confirmed_disjoint=True),
    ]


def fixture_history(context):
    key = context["key"]()
    changes = []
    responses = []
    for home, contract in zip(context["homes"], context["leases"], strict=True):
        items = standard(context, home, key, contract)
        changes.append(items)
        responses.append(confirm(context, home, items).json())
    return key, changes, responses


def test_confirmed_boundary_sources_generate_water_only_and_retry_exactly(context):
    key, changes, responses = fixture_history(context)
    context["meter"](context["homes"][0], 1000, medium="electricity", measurement="kWh")
    assert confirm(context, context["homes"][0], changes[0]).json() == responses[0]
    response = context["generate"]()
    assert response.status_code == 201, response.text
    assert {row["total_cost"] for row in response.json()} == {50}
    altered = deepcopy(changes[0])
    altered[0]["reason"] = "Changed request"
    confirm(context, context["homes"][0], altered, status=409)
    confirm(context, context["homes"][0], altered, command="distinct", status=409)
    assert source_rows(context, context["homes"][0])["revision"] == 1


def test_historical_selection_on_only_one_unit_never_falls_back_to_current_metadata(context):
    key = context["key"]()
    confirm(context, context["homes"][0], standard(context, context["homes"][0], key, context["leases"][0]))
    context["meter"](context["homes"][1])
    review = context["preflight"]()
    assert "HISTORICAL_BASIS_INCOMPLETE" in {item["code"] for item in review["blockers"]}
    assert context["generate"]().status_code == 400


def test_corrected_reading_retains_original_and_invalidates_generated_draft(context):
    _key, changes, responses = fixture_history(context)
    assert context["generate"]().status_code == 201
    fix = deepcopy(changes[0][2])
    fix.update(predecessor_id=responses[0]["fact_ids"][2], reason="Originalbeleg: 130 statt 110")
    fix["data"]["value"] = "130"
    confirm(context, context["homes"][0], [fix], revision=1, command="correct")
    final = context["active"].client.post(f"/api/v1/billing/periods/{context['period']['id']}/finalize", headers=context["headers"])
    assert final.status_code == 409, final.text
    response = context["generate"]()
    assert response.status_code == 201, response.text
    assert {row["total_cost"] for row in response.json()} == {75, 25}
    journal = context["active"].client.get(BASE + context["homes"][0]["id"] + "/journal", headers=context["headers"], params={"page_size": 1}).json()
    assert journal["next_after"] == 1
    assert journal["items"][0]["request"]["changes"][2]["data"]["value"] == "110"
    original = context["active"].client.get(BASE + context["homes"][0]["id"] + "/facts/" + responses[0]["fact_ids"][2], headers=context["headers"])
    assert original.status_code == 200, original.text
    assert original.json()["data"]["value"] == "110"
    assert original.headers["cache-control"] == "private, no-store"


def test_real_tenant_change_and_vacancy_use_boundary_consumption_without_day_estimate(context):
    key = context["key"]()
    home = context["homes"][0]
    old = context["patch"](f"/contracts/{context['leases'][0]['id']}", {"end_date": "2026-06-30"})
    tenant = context["post"]("/tenants", {"full_name": "Synthetic successor"})
    new = context["post"]("/contracts", {"property_id": context["period"]["property_id"], "unit_id": home["id"],
        "tenant_id": tenant["id"], "contract_number": "NEXT", "start_date": "2026-08-01"})
    rows = standard(context, home, key, old, delta=100)
    rows[3]["data"]["valid_until"] = "2026-07-01"
    rows += [fact("vacancy", "occupancy", **span(valid_from="2026-07-01", valid_until="2026-08-01"), vacancy=True, persons=0),
        fact("next", "occupancy", **span(valid_from="2026-08-01"), contract_id=new["id"], persons=1),
        fact("out", "reading", assignment_key="assignment", boundary_date="2026-07-01", value="120"),
        fact("in", "reading", assignment_key="assignment", boundary_date="2026-08-01", value="130")]
    confirm(context, home, rows)
    confirm(context, context["homes"][1], standard(context, context["homes"][1], key, context["leases"][1], delta=100))
    response = context["generate"]()
    assert response.status_code == 201, response.text
    assert {row["contract_id"]: row["total_cost"] for row in response.json()} == {old["id"]: 10, new["id"]: 35, context["leases"][1]["id"]: 50}
    period = context["active"].client.get(f"/api/v1/billing/periods/{context['period']['id']}", headers=context["headers"]).json()
    assert period["owner_cost_share"]["recoverable_vacancy_amount"] == 5


def test_meter_replacement_uses_each_original_boundary_pair(context):
    key = context["key"]()
    home = context["homes"][0]
    rows = standard(context, home, key, context["leases"][0], delta=10)
    rows[0]["data"]["valid_until"] = "2026-07-01"
    rows[2]["data"]["boundary_date"] = "2026-07-01"
    second = context["meter"](home)
    rows += [fact("replacement", "assignment", **span(valid_from="2026-07-01"), meter_id=second["id"], medium="cold_water", measurement_unit="m³", circuit_path=["water"]),
        fact("replacement-start", "reading", assignment_key="replacement", boundary_date="2026-07-01", value="0"),
        fact("replacement-end", "reading", assignment_key="replacement", boundary_date="2027-01-01", value="20")]
    confirm(context, home, rows)
    confirm(context, context["homes"][1], standard(context, context["homes"][1], key, context["leases"][1], delta=10))
    response = context["generate"]()
    assert response.status_code == 201, response.text
    assert {row["total_cost"] for row in response.json()} == {75, 25}


def test_person_days_follow_dated_residents_instead_of_rooms(context):
    key = context["key"](amount=1095)
    context["patch"](f"/billing/allocation-keys/{key['id']}", {"key_type": "person_count"})
    for index, home in enumerate(context["homes"]):
        rows = [fact("selection", "selection", **span(), allocation_key_id=key["id"], basis="person_count"),
            fact("occupancy", "occupancy", **span(valid_until="2026-07-01" if index == 0 else "2027-01-01"), contract_id=context["leases"][index]["id"], persons=1)]
        if index == 0:
            rows += [fact("resident-change", "occupancy", **span(valid_from="2026-07-01"), contract_id=context["leases"][index]["id"], persons=3)]
        confirm(context, home, rows)
    response = context["generate"]()
    assert response.status_code == 201, response.text
    # 181 + 184*3 =733 vs365 person-days, not current 3 rooms per unit.
    amounts = {row["unit_id"]: row["total_cost"] for row in response.json()}
    assert amounts[context["homes"][0]["id"]] == 731.0
    assert amounts[context["homes"][1]["id"]] == 364.0
    assert sum(amounts.values()) == 1095


def test_fully_vacant_period_keeps_all_costs_with_owner_and_finalizes_only_proven_basis(context):
    key = context["key"]()
    for home, lease in zip(context["homes"], context["leases"], strict=True):
        context["patch"](f"/contracts/{lease['id']}", {"status": "draft"})
        items = standard(context, home, key, lease)
        items[3] = fact("occupancy", "occupancy", **span(), vacancy=True, persons=0)
        confirm(context, home, items)
    response = context["generate"]()
    assert response.status_code == 201 and response.json() == [], response.text
    active = context["active"]
    path = f"/api/v1/billing/periods/{context['period']['id']}"
    before = active.client.get(path, headers=context["headers"]).json()
    assert before["owner_cost_share"]["total_amount"] == 100
    assert before["owner_cost_share"]["tenant_cost_total"] == 0
    finalized = active.client.post(path + "/finalize", headers=context["headers"])
    assert finalized.status_code == 200, finalized.text
    stored = active.client.get(path, headers=context["headers"]).json()
    assert active.client.post(path + "/finalize", headers=context["headers"]).json() == stored
