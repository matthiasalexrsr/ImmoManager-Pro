"""Actual ordinary writers against retained history and the privacy snapshot."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import Session

from backend import auth
from backend.db.orm_models import UnitORM
from backend.models import AllocationKeyPatch, UnitPatch
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import measurement_history as history
from backend.services import measurement_parent_guards as guards
from backend.services.measurement_history_types import MeasurementCommand
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.tenant_privacy import (
    PrivacyConflict,
    anonymize_tenant_profile,
    export_tenant_metadata,
    preview_tenant_anonymization,
)
from backend.tests.form_draft_api_support import application, migrate
from backend.tests.measurement_history_postgres_support import migrated_postgres
from backend.tests.test_billing_consumption_http import context as context_fixture
from backend.tests.test_measurement_history_http import confirm, fact, fixture_history, span, standard

context = context_fixture


@pytest.fixture(params=["memory", "sqlite", "postgres"])
def draft_http(request, monkeypatch, tmp_path):
    if request.param == "postgres":
        with migrated_postgres(monkeypatch) as (engine, _config), application(monkeypatch, engine) as active:
            yield active
        return
    engine = None
    if request.param == "sqlite":
        url = "sqlite:///" + (tmp_path / "parents.sqlite").as_posix()
        assert migrate(url, monkeypatch) == "h2a2b3c4d5e6"
        engine = create_engine(url, hide_parameters=True, connect_args={"check_same_thread": False})
    try:
        with application(monkeypatch, engine) as active:
            yield active
    finally:
        if engine is not None:
            engine.dispose()


def mutation(context, path, changes=None, method="patch"):
    client = context["active"].client
    opened = client.get("/api/v1" + path, headers=context["headers"])
    assert opened.status_code == 200, opened.text
    return client.request(method, "/api/v1" + path, headers={**context["headers"], "If-Match": opened.headers["etag"]}, json=changes)


def test_http_parent_rebinding_and_deletion_preserve_originals_before_any_cascade(context):
    key, changes, receipts = fixture_history(context)
    home, lease = context["homes"][0], context["leases"][0]
    active = context["active"]
    for path, changeset in (
        (f"/units/{home['id']}", {"property_id": active.properties[1].id}),
        (f"/contracts/{lease['id']}", {"tenant_id": context["leases"][1]["tenant_id"]}),
        (f"/billing/allocation-keys/{key['id']}", {"property_id": active.properties[1].id}),
        (f"/properties/{active.properties[0].id}", {"portfolio_id": active.portfolios[1].id}),
    ):
        rejected = mutation(context, path, changeset)
        assert rejected.status_code == 409, rejected.text
    for path in (f"/units/{home['id']}", f"/properties/{active.properties[0].id}",
                 f"/portfolios/{active.portfolios[0].id}", f"/tenants/{lease['tenant_id']}",
                 f"/contracts/{lease['id']}", f"/billing/allocation-keys/{key['id']}",
                 f"/meters/{changes[0][0]['data']['meter_id']}"):
        rejected = mutation(context, path, method="delete")
        assert rejected.status_code == 409, rejected.text
    assert context["generate"]().status_code == 201
    assert mutation(context, f"/units/{home['id']}", {"label": "Renamed safely"}).status_code == 200
    assert mutation(context, f"/meters/{changes[0][0]['data']['meter_id']}", {"unit_id": context["homes"][1]["id"]}).status_code == 200
    assert context["generate"]().status_code == 201


def test_direct_repository_patch_also_preserves_historical_unit_binding(context):
    fixture_history(context)
    active = context["active"]
    patch = UnitPatch(property_id=active.properties[1].id)
    with scope_context(None):
        if active.engine is None:
            with pytest.raises(HTTPException) as caught:
                active.store._patch_entity("unit", context["homes"][0]["id"], patch)
        else:
            with Session(active.engine) as db:
                with pytest.raises(HTTPException) as caught:
                    SQLAlchemyStore(db).portfolio._units.patch(context["homes"][0]["id"], patch)
                db.rollback()
        assert caught.value.status_code == 409
    assert context["generate"]().status_code == 201


def test_put_rebinding_uses_the_same_historical_guard(context):
    fixture_history(context)
    home = context["homes"][0]
    response = mutation(context, f"/units/{home['id']}",
        {"property_id": context["active"].properties[1].id, "label": home["label"], "unit_type": "Wohnung"}, method="put")
    assert response.status_code == 409, response.text


def test_preexisting_wrong_parent_can_be_repaired_only_back_to_preserved_original(context):
    fixture_history(context)
    active = context["active"]
    home = context["homes"][0]
    # Synthetic legacy corruption bypasses all ordinary writers deliberately.
    if active.engine is None:
        active.store.units[home["id"]] = active.store.units[home["id"]].model_copy(update={"property_id": active.properties[1].id})
    else:
        with active.engine.begin() as connection:
            connection.execute(update(UnitORM).where(UnitORM.id == home["id"]).values(property_id=active.properties[1].id))
    repaired = mutation(context, f"/units/{home['id']}", {"property_id": home["property_id"]})
    assert repaired.status_code == 200, repaired.text
    assert context["generate"]().status_code == 201


def test_native_parent_sqlite_contention_is_retryable_without_partial_write(context):
    active = context["active"]
    if active.engine is None or active.engine.dialect.name != "sqlite":
        pytest.skip("Native SQLite writer-contention gate")
    fixture_history(context)
    identifier = context["homes"][0]["id"]
    with active.engine.connect() as holder:
        holder.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            with Session(active.engine) as db, pytest.raises(HTTPException) as caught:
                SQLAlchemyStore(db).portfolio._units.patch(identifier, UnitPatch(label="After retry"))
            assert caught.value.status_code == 409
        finally:
            holder.rollback()
    result = mutation(context, f"/units/{identifier}", {"label": "After retry"})
    assert result.status_code == 200, result.text


def test_first_confirmation_and_ordinary_key_writer_share_actual_lock(context, monkeypatch):
    active = context["active"]
    key = context["key"]()
    changes = standard(context, context["homes"][0], key, context["leases"][0])
    body = MeasurementCommand(expected_revision=0, idempotency_key="first-concurrent", changes=changes)
    inserted, release, attempted = Event(), Event(), Event()
    original = history._add
    def hold(store, row):
        original(store, row)
        if row.__tablename__ == "measurement_facts" and not inserted.is_set():
            inserted.set()
            assert release.wait(15)
    monkeypatch.setattr(history, "_add", hold)
    def confirm_source():
        if active.engine is None:
            return history.confirm(active.store, context["homes"][0]["id"], body, active.owner.id)
        with Session(active.engine) as db:
            return history.confirm(SQLAlchemyStore(db), context["homes"][0]["id"], body, active.owner.id)
    def ordinary():
        attempted.set()
        patch = AllocationKeyPatch(property_id=active.properties[1].id)
        try:
            if active.engine is None:
                active.store._patch_entity("allocation_key", key["id"], patch)
            else:
                with Session(active.engine) as db:
                    SQLAlchemyStore(db).billing._allocation_keys.patch(key["id"], patch)
                    db.commit()
        except HTTPException as error:
            return error.status_code
        return 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        confirmed = pool.submit(confirm_source)
        assert inserted.wait(15)
        changed = pool.submit(ordinary)
        try:
            assert attempted.wait(5)
            assert not changed.done()
        finally:
            release.set()
        assert confirmed.result(timeout=20)["revision"] == 1
        assert changed.result(timeout=20) == 409


def test_role_loss_before_publication_never_changes_parent(context, monkeypatch):
    fixture_history(context)
    active = context["active"]
    original_user = auth.get_user_by_id
    original_guard = guards.guard_edit
    revoked = []
    def after_guard(*args, **kwargs):
        original_guard(*args, **kwargs)
        revoked.append(True)
    def user(identifier):
        row = original_user(identifier)
        return {**row, "role": "readonly"} if revoked and identifier == active.owner.id else row
    monkeypatch.setattr(guards, "guard_edit", after_guard)
    monkeypatch.setattr(auth, "get_user_by_id", user)
    response = mutation(context, f"/units/{context['homes'][0]['id']}", {"label": "Must not publish"})
    assert response.status_code == 403, response.text
    monkeypatch.setattr(auth, "get_user_by_id", original_user)
    opened = active.client.get("/api/v1/units/" + context["homes"][0]["id"], headers=context["headers"])
    assert opened.json()["label"] != "Must not publish"


def test_native_role_loss_after_sql_update_before_commit_rolls_back(context, monkeypatch):
    active = context["active"]
    if active.engine is None:
        pytest.skip("Native SQL publication gate; Memory uses the account/domain critical section")
    fixture_history(context)
    original_user = auth.get_user_by_id
    updated = []
    def observed(_connection, _cursor, statement, _parameters, _ctx, _many):
        if statement.lstrip().upper().startswith("UPDATE UNITS SET"):
            updated.append(True)
    def user(identifier):
        row = original_user(identifier)
        return {**row, "role": "readonly"} if updated and identifier == active.owner.id else row
    event.listen(active.engine, "after_cursor_execute", observed)
    monkeypatch.setattr(auth, "get_user_by_id", user)
    try:
        response = mutation(context, f"/units/{context['homes'][0]['id']}", {"label": "Must roll back actual DML"})
        assert updated, "No native UPDATE reached the publication gate"
        assert response.status_code == 403, response.text
    finally:
        event.remove(active.engine, "after_cursor_execute", observed)
        monkeypatch.setattr(auth, "get_user_by_id", original_user)
    opened = active.client.get("/api/v1/units/" + context["homes"][0]["id"], headers=context["headers"])
    assert opened.json()["label"] != "Must roll back actual DML"


def test_privacy_export_excludes_successor_command_text_and_anonymization_keeps_originals(context):
    active = context["active"]
    home = context["homes"][0]
    old = context["patch"](f"/contracts/{context['leases'][0]['id']}", {"end_date": "2026-06-30", "status": "terminated"})
    successor = context["post"]("/tenants", {"full_name": "Synthetic successor"})
    new = context["post"]("/contracts", {"property_id": home["property_id"], "unit_id": home["id"],
        "tenant_id": successor["id"], "contract_number": "NEXT-PRIVATE", "start_date": "2026-07-01"})
    rows = [fact("old", "occupancy", **span(valid_until="2026-07-01"), contract_id=old["id"], persons=2),
            fact("next", "occupancy", **span(valid_from="2026-07-01"), contract_id=new["id"], persons=1)]
    rows[1]["reason"] = "PRIVATE SUCCESSOR ONLY"
    receipt = confirm(context, home, rows).json()
    with scope_context(scope_from_user(auth.get_user_by_id(active.owner.id))):
        graph = export_tenant_metadata(active.store, old["tenant_id"])
        assert len(graph["measurement_facts"]) == 1
        assert "PRIVATE SUCCESSOR ONLY" not in json.dumps(graph)
        assert "request" not in graph["measurement_commands"][0]
        plan = preview_tenant_anonymization(active.store, old["tenant_id"])
        assert plan["retained_personal_evidence"]["measurement_facts"]["count"] == 1
    correction = deepcopy(rows[0])
    correction.update(predecessor_id=receipt["fact_ids"][0], reason="Corrected original number")
    correction["data"]["persons"] = 3
    confirm(context, home, [correction], revision=1, command="privacy-correction")
    with scope_context(scope_from_user(auth.get_user_by_id(active.owner.id))):
        with pytest.raises(PrivacyConflict):
            anonymize_tenant_profile(active.store, old["tenant_id"], plan_hash=plan["plan_hash"], confirm_tenant_id=old["tenant_id"])
        plan = preview_tenant_anonymization(active.store, old["tenant_id"])
        result = anonymize_tenant_profile(active.store, old["tenant_id"], plan_hash=plan["plan_hash"], confirm_tenant_id=old["tenant_id"])
        assert result["status"] == "profile_anonymized"
        after = export_tenant_metadata(active.store, old["tenant_id"])
        assert len(after["measurement_facts"]) == 2
        assert after["measurement_facts"][0]["data"]["persons"] == 2
    if active.engine is not None:
        active.store.db.remove()


def test_privacy_confirmation_and_first_measurement_writer_cannot_publish_stale_plan(context, monkeypatch):
    active = context["active"]
    old = context["patch"](f"/contracts/{context['leases'][0]['id']}", {"status": "terminated", "end_date": "2026-12-31"})
    with scope_context(None):
        plan = preview_tenant_anonymization(active.store, old["tenant_id"])
        if active.engine is not None:
            active.store.db.remove()
    inserted, release = Event(), Event()
    original = history._add
    def hold(store, row):
        original(store, row)
        if row.__tablename__ == "measurement_facts":
            inserted.set()
            assert release.wait(15)
    monkeypatch.setattr(history, "_add", hold)
    body = MeasurementCommand(expected_revision=0, idempotency_key="privacy-first-writer",
        changes=[fact("occupancy", "occupancy", **span(), contract_id=old["id"], persons=1)])
    def writer():
        if active.engine is None:
            return history.confirm(active.store, context["homes"][0]["id"], body, active.owner.id)
        with Session(active.engine) as db:
            return history.confirm(SQLAlchemyStore(db), context["homes"][0]["id"], body, active.owner.id)
    with ThreadPoolExecutor(max_workers=1) as pool:
        operation = pool.submit(writer)
        assert inserted.wait(15)
        try:
            with scope_context(None), pytest.raises(PrivacyConflict):
                anonymize_tenant_profile(active.store, old["tenant_id"], plan_hash=plan["plan_hash"], confirm_tenant_id=old["tenant_id"])
        finally:
            release.set()
        assert operation.result(timeout=20)["revision"] == 1
    with scope_context(None):
        assert active.store.get_tenant(old["tenant_id"]).full_name == "Synthetic occupant 0"
        if active.engine is not None:
            active.store.db.remove()
