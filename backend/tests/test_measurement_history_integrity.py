"""Recovery, corrections, missing boundaries and fresh authority counterexamples."""

from copy import deepcopy
from datetime import date, timedelta
from io import BytesIO

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from backend import auth
from backend.db.measurement_history_models import MeasurementFactORM
from backend.models import DocumentCreate
from backend.services import measurement_history as history
from backend.services.file_storage import LocalStorage
from backend.services.measurement_history_recovery import (
    RESTORE_ORDER,
    iter_measurement_family,
    retained_measurement_subject,
)
from backend.services.measurement_history_validation import (
    MeasurementIntegrityError,
    validate_measurement_snapshot,
)
from backend.services.portfolio_scope import scope_context
from backend.tests.test_measurement_history_http import (
    BASE,
    confirm,
    fact,
    fixture_history,
    source_rows,
    span,
    standard,
)
from backend.tests.test_measurement_history_http import (
    context as context_fixture,
)
from backend.tests.test_measurement_history_http import (
    draft_http as draft_http_fixture,
)

context = context_fixture
draft_http = draft_http_fixture


def original(context, monkeypatch, tmp_path):
    active = context["active"]
    storage = LocalStorage(str(tmp_path / "source"))
    storage.save("documents/approval.txt", BytesIO(b"Synthetic explicit daily proration approval"))
    monkeypatch.setattr("backend.services.contract_attachment.get_file_storage", lambda: storage)
    with scope_context(None):
        document = active.store.create_document(DocumentCreate(property_id=context["period"]["property_id"],
            unit_id=context["homes"][0]["id"], title="Synthetic approval", file_url="/uploads/documents/approval.txt"))
        if active.engine is not None:
            active.store.db.remove()
    prefix = f"/api/v1/documents/{document.id}"
    opened = active.client.get(prefix + "/versions", headers=context["headers"])
    assert opened.status_code == 200, opened.text
    source = active.client.get(prefix + "/version-source", headers=context["headers"])
    assert source.status_code == 200, source.text
    response = active.client.post(prefix + "/versions/archive-original", headers=context["headers"], json={
        "idempotency_key": "proration-original", "expected_document_etag": opened.json()["document_etag"],
        "confirmed": True, "comment": "Reviewed original approval", "expected_sha256": source.json()["sha256"]})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_missing_move_boundary_only_becomes_calculable_after_documented_proration(context, monkeypatch, tmp_path):
    key = context["key"](amount=730)
    home = context["homes"][0]
    old = context["patch"](f"/contracts/{context['leases'][0]['id']}", {"end_date": "2026-06-30"})
    tenant = context["post"]("/tenants", {"full_name": "Synthetic successor"})
    new = context["post"]("/contracts", {"property_id": context["period"]["property_id"], "unit_id": home["id"],
        "tenant_id": tenant["id"], "contract_number": "SUCCESSOR", "start_date": "2026-07-01"})
    rows = standard(context, home, key, old, delta=365)
    rows[3]["data"]["valid_until"] = "2026-07-01"
    rows.append(fact("next", "occupancy", **span(valid_from="2026-07-01"), contract_id=new["id"], persons=1))
    receipt = confirm(context, home, rows).json()
    confirm(context, context["homes"][1], standard(context, context["homes"][1], key, context["leases"][1], delta=365))
    assert context["generate"]().status_code == 400
    version = original(context, monkeypatch, tmp_path)
    approval = fact("approval", "proration", **span(), assignment_key="assignment",
        start_reading_id=receipt["fact_ids"][1], end_reading_id=receipt["fact_ids"][2])
    approval["evidence_version_ids"] = [version]
    confirm(context, home, [approval], revision=1, command="approval")
    response = context["generate"]()
    assert response.status_code == 201, response.text
    assert {row["contract_id"]: row["total_cost"] for row in response.json()} == {
        old["id"]: 181, new["id"]: 184, context["leases"][1]["id"]: 365}


def test_withdrawn_selection_and_date_shift_do_not_restore_stammdaten_fallback(context):
    _key, changes, receipts = fixture_history(context)
    fix = deepcopy(changes[0][4])
    fix.update(predecessor_id=receipts[0]["fact_ids"][4], withdrawn=True, reason="Falsche ursprüngliche Zuordnung")
    confirm(context, context["homes"][0], [fix], revision=1, command="withdraw")
    assert "HISTORICAL_BASIS_INCOMPLETE" in {row["code"] for row in context["preflight"]()["blockers"]}
    assert context["generate"]().status_code == 400


def test_privacy_projection_and_pure_restore_reject_tampered_hash_or_missing_family(context, monkeypatch):
    _key, changes, receipts = fixture_history(context)
    # Correction IDs deliberately sort before originals: restore must respect
    # the predecessor FK, not UUID ordering.
    identifiers = iter(("00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"))
    monkeypatch.setattr(history, "uuid4", lambda: next(identifiers))
    fix = deepcopy(changes[0][2])
    fix.update(predecessor_id=receipts[0]["fact_ids"][2], reason="Originalbeleg korrigiert")
    fix["data"]["value"] = "130"
    confirm(context, context["homes"][0], [fix], revision=1, command="restore-correction")
    active = context["active"]
    with scope_context(None):
        family = {name: list(iter_measurement_family(active.store, name)) for name in RESTORE_ORDER}
        inserted = set()
        for item in family["measurement_facts"]:
            assert item["predecessor_id"] is None or item["predecessor_id"] in inserted
            inserted.add(item["id"])
        parents = {name: {row.id: row.model_dump() for row in getattr(active.store, "list_" + name)()}
            for name in ("units", "properties", "meters", "allocation_keys", "contracts", "tenants")}
        parents["document_versions"] = {}
        validate_measurement_snapshot(family, parents=parents)
        broken = deepcopy(family)
        broken["measurement_facts"][0]["reason"] = "Changed outside correction journal"
        with pytest.raises(MeasurementIntegrityError):
            validate_measurement_snapshot(broken, parents=parents)
        broken = dict(family)
        broken.pop("measurement_evidence")
        with pytest.raises(MeasurementIntegrityError, match="Unvollständige"):
            validate_measurement_snapshot(broken, parents=parents)
        disclosure = retained_measurement_subject(active.store, context["leases"][0]["tenant_id"])
        assert len(disclosure["facts"]) == 1
        assert all(row["tenant_id"] == context["leases"][0]["tenant_id"] for row in disclosure["facts"])
        assert "request" not in disclosure["commands"][0]
        if active.engine is not None:
            active.store.db.remove()


def test_foreign_parent_and_revoked_role_at_publication_never_leave_partial_sources(context, monkeypatch):
    key = context["key"]()
    home = context["homes"][0]
    rows = standard(context, home, key, context["leases"][0])
    foreign_home = context["post"]("/units", {"property_id": context["active"].properties[1].id,
        "label": "Foreign synthetic unit", "unit_type": "Wohnung"})
    foreign_meter = context["meter"](foreign_home)
    wrong = deepcopy(rows)
    wrong[0]["data"]["meter_id"] = foreign_meter["id"]
    confirm(context, home, wrong, status=404)
    assert source_rows(context, home) == {"revision": 0, "facts": []}
    active = context["active"]
    original_add = history._add
    current_get = auth.get_user_by_id
    revoked = []
    def add_and_revoke(store, row):
        original_add(store, row)
        if row.__tablename__ == "measurement_facts":
            revoked.append(True)
    def fresh_user(identifier):
        user = current_get(identifier)
        if revoked and identifier == active.owner.id:
            return {**user, "role": "readonly"}
        return user
    monkeypatch.setattr(history, "_add", add_and_revoke)
    monkeypatch.setattr(auth, "get_user_by_id", fresh_user)
    confirm(context, home, rows, status=403)
    monkeypatch.setattr(auth, "get_user_by_id", current_get)
    assert source_rows(context, home) == {"revision": 0, "facts": []}


def test_dated_physical_meter_reassignment_across_units_preserves_history_and_refuses_overlap(context):
    home, other = context["homes"]
    meter = context["meter"](home)
    first = fact("assignment", "assignment", **span(valid_until="2026-07-01"), meter_id=meter["id"],
        medium="cold_water", measurement_unit="m³", circuit_path=["water"])
    confirm(context, home, [first])
    overlap = deepcopy(first)
    overlap["data"]["valid_until"] = "2027-01-01"
    confirm(context, other, [overlap], status=409)
    assert source_rows(context, other)["revision"] == 0
    second = deepcopy(overlap)
    second["data"]["valid_from"] = "2026-07-01"
    confirm(context, other, [second])
    assert source_rows(context, home)["facts"][0]["data"]["valid_until"] == "2026-07-01"
    assert source_rows(context, other)["facts"][0]["data"]["valid_from"] == "2026-07-01"


def test_anonymous_and_foreign_portfolio_cannot_read_or_confirm_historical_sources(context):
    active = context["active"]
    home = context["post"]("/units", {"property_id": active.properties[1].id,
        "label": "Foreign synthetic unit", "unit_type": "Wohnung"})
    path = BASE + home["id"]
    query = {"start": "2026-01-01", "end": "2027-01-01"}
    assert active.client.get(path, params=query).status_code == 401
    peer = active.headers(active.peer)
    assert active.client.get(path, params=query, headers=peer).status_code == 404
    assert active.client.post(path + "/confirm", headers=peer, json={"expected_revision": 0,
        "idempotency_key": "foreign", "changes": [fact("vacancy", "occupancy", **span(), vacancy=True, persons=0)]}).status_code == 404


def test_period_read_does_not_materialize_thousand_unrelated_historical_readings(context):
    _key, changes, receipts = fixture_history(context)
    start = date(2000, 1, 1)
    old = [fact("old-meter", "assignment", valid_from=start.isoformat(), valid_until="2004-01-01",
        meter_id=changes[0][0]["data"]["meter_id"], medium="cold_water", measurement_unit="m³", circuit_path=["water"])]
    old += [fact(f"old-reading-{index}", "reading", assignment_key="old-meter",
        boundary_date=(start + timedelta(days=index)).isoformat(), value=str(index)) for index in range(1001)]
    confirm(context, context["homes"][0], old, revision=1, command="old-history")
    active = context["active"]
    loaded = []
    def observed(row, _load_context):
        loaded.append(row.id)
    event.listen(MeasurementFactORM, "load", observed)
    try:
        with scope_context(None):
            period = active.store.get_billing_period(context["period"]["id"])
            selected = history.period_sources(active.store, period)
            if active.engine is not None:
                active.store.db.remove()
        expected = set(receipts[0]["fact_ids"] + receipts[1]["fact_ids"])
        assert {row["id"] for row in selected} == expected
        if active.engine is not None:
            assert set(loaded) == expected
            assert len(loaded) == len(expected)
    finally:
        event.remove(MeasurementFactORM, "load", observed)


def test_finalized_original_is_unchanged_after_historical_correction(context):
    _key, changes, receipts = fixture_history(context)
    assert context["generate"]().status_code == 201
    active = context["active"]
    path = f"/api/v1/billing/periods/{context['period']['id']}"
    assert active.client.post(path + "/finalize", headers=context["headers"]).status_code == 200
    before = active.client.get(path, headers=context["headers"]).json()
    statements = active.client.get("/api/v1/billing/statements", headers=context["headers"]).json()
    fix = deepcopy(changes[0][2])
    fix.update(predecessor_id=receipts[0]["fact_ids"][2], reason="Später belegte Korrektur")
    fix["data"]["value"] = "130"
    confirm(context, context["homes"][0], [fix], revision=1, command="late")
    assert active.client.post(path + "/finalize", headers=context["headers"]).json() == before
    assert active.client.get("/api/v1/billing/statements", headers=context["headers"]).json() == statements


def test_native_immutable_sources_reject_direct_update_delete_and_parent_delete(context):
    active = context["active"]
    if active.engine is None:
        pytest.skip("Native DDL guard requires SQLite/PostgreSQL; Memory corrections use append-only commands")
    _key, _changes, receipts = fixture_history(context)
    for statement, parameters in (
        ("UPDATE measurement_facts SET reason='raw overwrite' WHERE id=:id", {"id": receipts[0]["fact_ids"][0]}),
        ("DELETE FROM measurement_facts WHERE id=:id", {"id": receipts[0]["fact_ids"][0]}),
        ("DELETE FROM units WHERE id=:id", {"id": context["homes"][0]["id"]}),
    ):
        with pytest.raises(DBAPIError):
            with active.engine.begin() as connection:
                if active.engine.dialect.name == "sqlite":
                    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.execute(text(statement), parameters)
    assert source_rows(context, context["homes"][0])["revision"] == 1
