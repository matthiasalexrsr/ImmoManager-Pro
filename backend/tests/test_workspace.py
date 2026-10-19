"""Private state never executes domain operations or escapes its current owner's rights."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from importlib import import_module
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect, select

from backend import auth
from backend.dependencies import store
from backend.models import (
    ContactCreate,
    ContractCreate,
    MeterCreate,
    PortfolioCreate,
    PropertyCreate,
    ReceivableCreate,
    TaskCreate,
    TenantCreate,
    UnitCreate,
)
from backend.routers import auth as auth_router
from backend.routers import workspace as workspace_router

API = "/api/v1/workspace"
app = FastAPI()
app.include_router(workspace_router.router, prefix="/api/v1")
app.include_router(auth_router.router, prefix="/api/v1")


def command(revision=0, **values):
    return {"base_revision": revision, "idempotency_key": str(uuid4()), **values}


def dependency_etags(client, kind, identifier):
    response = client.get(f"{API}/source/{kind}/{identifier}")
    assert response.status_code == 200, response.text
    return response.json()["dependency_etags"]


@pytest.fixture(autouse=True)
def clean():
    auth.clear_users()
    store.clear_all()
    store.__dict__.pop("_personal_workspace", None)
    yield
    auth.clear_users()
    store.clear_all()
    store.__dict__.pop("_personal_workspace", None)


def client(name, role="eigentuemer", **scope):
    user = auth.register_user(name, f"{name}@example.test", name, "Secret123", role, **scope)
    return user, TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})


@pytest.fixture
def estate():
    north = store.create_portfolio(PortfolioCreate(name="Nord"))
    south = store.create_portfolio(PortfolioCreate(name="Süd"))
    prop = store.create_property(PropertyCreate(portfolio_id=north.id, name="Nordhaus", property_type="residential"))
    foreign = store.create_property(PropertyCreate(portfolio_id=south.id, name="Fremdhaus", property_type="residential"))
    return north, south, prop, foreign


def test_drafts_are_durable_owner_private_and_never_save_the_domain(estate):
    _, first = client("first")
    _, second = client("second")
    identifier = str(uuid4())
    body = command(context="properties", values={"name": "Unfertiger Entwurf"}, field_keys=["name"], form_key="property-form")
    saved = first.put(f"{API}/drafts/{identifier}", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    assert second.get(f"{API}/drafts/{identifier}").status_code == 404
    other = second.put(f"{API}/drafts/{identifier}", json=command(context="properties", values={"name": "Anderer Entwurf"}))
    assert other.status_code == 200, other.text
    assert first.get(f"{API}/drafts/{identifier}").json()["values"]["name"] == "Unfertiger Entwurf"
    assert second.get(f"{API}/drafts/{identifier}").json()["values"]["name"] == "Anderer Entwurf"
    assert len(store.list_properties()) == 2
    assert saved.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("fields,title", [
    ({"first_name": " Ada ", "last_name": "Lovelace"}, "Ada Lovelace"),
    ({"first_name": "Ada", "last_name": "Lovelace", "company_name": "Hausverwaltung"}, "Hausverwaltung"),
    ({"email": "contact@example.test"}, "contact@example.test"),
    ({}, "Unbenannter Kontakt"),
])
def test_contact_source_and_favorites_have_identifiable_titles(fields, title):
    _, owner = client("contact-titles")
    contact = store.create_contact(ContactCreate(**fields))
    source = owner.get(f"{API}/source/contact/{contact.id}")
    assert source.status_code == 200, source.text
    assert source.json()["title"] == title
    favorite = owner.put(f"{API}/favorites/contact/{contact.id}", json=command())
    assert favorite.status_code == 200, favorite.text
    assert favorite.json()["title"] == title


def test_cas_retry_and_tombstone_revision_prevent_lost_updates(estate):
    _, owner = client("cas")
    identifier = str(uuid4())
    body = command(context="tasks", values={"title": "A"})
    first = owner.put(f"{API}/drafts/{identifier}", json=body).json()
    assert owner.put(f"{API}/drafts/{identifier}", json=body).json() == first
    changed = {**body, "values": {"title": "Wrong"}}
    assert owner.put(f"{API}/drafts/{identifier}", json=changed).status_code == 409
    second = owner.put(f"{API}/drafts/{identifier}", json=command(1, context="tasks", values={"title": "B"})).json()
    assert second["revision"] == 2
    assert owner.put(f"{API}/drafts/{identifier}", json=command(1, context="tasks", values={"title": "Old"})).status_code == 409
    removed = owner.request("DELETE", f"{API}/drafts/{identifier}", json=command(2)).json()
    assert removed == {"id": identifier, "revision": 3, "deleted": True}
    assert owner.get(f"{API}/drafts/{identifier}").status_code == 404
    restored = owner.put(f"{API}/drafts/{identifier}", json=command(context="tasks", values={"title": "New"})).json()
    assert restored["revision"] == 4
    assert owner.put(f"{API}/drafts/{identifier}", json=command(2, context="tasks", values={"title": "Old"})).status_code == 409


def test_changed_source_preserves_autosave_until_explicit_rebase(estate):
    _, _, prop, _ = estate
    _, owner = client("source")
    identifier = str(uuid4())
    source = {"kind": "property", "id": prop.id, "revision": prop.updated_at.isoformat()}
    body = command(context="properties", mode="edit", source=source, values={"name": "Mein Entwurf"})
    first = owner.put(f"{API}/drafts/{identifier}", json=body)
    assert first.status_code == 200, first.text
    updated = store.update_property(prop.id, PropertyCreate(**{**prop.model_dump(), "name": "Fremde Änderung"}))
    draft = owner.get(f"{API}/drafts/{identifier}").json()
    assert draft["source_state"]["status"] == "changed"
    assert draft["values"]["name"] == "Mein Entwurf"
    autosave = owner.put(f"{API}/drafts/{identifier}", json=command(1, context="properties", mode="edit", source=source,
                                                                  values={"name": "Weiter getippt"}))
    assert autosave.status_code == 200, autosave.text
    assert autosave.json()["source_state"]["status"] == "changed"
    assert store.get_property(prop.id).name == "Fremde Änderung"
    tokens = dependency_etags(owner, "property", prop.id)
    wrong = owner.post(f"{API}/drafts/{identifier}/rebase", json=command(2, source_revision=source["revision"], dependency_etags=tokens, values={"name": "Merge"}))
    assert wrong.status_code == 409
    rebased = owner.post(f"{API}/drafts/{identifier}/rebase", json=command(2, source_revision=updated.updated_at.isoformat(), dependency_etags=tokens, values={"name": "Merge"}))
    assert rebased.status_code == 200, rebased.text
    assert rebased.json()["source_state"]["status"] == "current"
    assert store.get_property(prop.id).name == "Fremde Änderung"


def test_parent_source_changes_are_recoverable_without_replacing_the_revision(estate):
    _, _, prop, _ = estate
    _, owner = client("parent-source")
    task = store.create_task(TaskCreate(property_id=prop.id, title="Aufgabe"))
    identifier = str(uuid4())
    original_revision = task.updated_at.isoformat()
    saved = owner.put(f"{API}/drafts/{identifier}", json=command(context="tasks", mode="edit",
        source={"kind": "task", "id": task.id, "revision": original_revision}, values={"title": "Entwurf"}))
    assert saved.status_code == 200, saved.text
    store.update_property(prop.id, PropertyCreate(**{**prop.model_dump(), "name": "Geänderter Bezug"}))
    recovered = owner.get(f"{API}/drafts/{identifier}").json()
    assert recovered["source"]["revision"] == original_revision
    assert recovered["source_state"]["status"] == "changed" and recovered["source_state"]["dependencies_changed"]
    old_tokens = dependency_etags(owner, "task", task.id)
    store.update_property(prop.id, PropertyCreate(**{**prop.model_dump(), "name": "Erneut nach Vergleich geändert"}))
    stale = owner.post(f"{API}/drafts/{identifier}/rebase", json=command(1, source_revision=original_revision,
        dependency_etags=old_tokens, values={"title": "Veralteter Vergleich"}))
    assert stale.status_code == 409, stale.text
    assert owner.get(f"{API}/drafts/{identifier}").json()["revision"] == 1
    rebased = owner.post(f"{API}/drafts/{identifier}/rebase", json=command(1, source_revision=original_revision,
        dependency_etags=dependency_etags(owner, "task", task.id), values={"title": "Bewusst geprüft"}))
    assert rebased.status_code == 200, rebased.text
    assert rebased.json()["source_state"]["status"] == "current"
    assert store.get_task(task.id).title == "Aufgabe"


def test_revocation_hides_drafts_recents_favorites_and_idempotent_replays(estate):
    north, south, prop, _ = estate
    _, owner = client("grant-owner")
    staff, viewer = client("grant-staff", "verwalter", portfolio_access="selected", portfolio_ids=[north.id])
    identifier = str(uuid4())
    draft_body = command(context="properties", mode="edit",
                         source={"kind": "property", "id": prop.id, "revision": prop.updated_at.isoformat()}, values={"name": "Privat"})
    assert viewer.put(f"{API}/drafts/{identifier}", json=draft_body).status_code == 200
    favorite = command()
    assert viewer.put(f"{API}/favorites/property/{prop.id}", json=favorite).status_code == 200
    recent = {"kind": "property", "entity_id": prop.id, "idempotency_key": str(uuid4())}
    assert viewer.post(f"{API}/recents/events", json=recent).status_code == 200
    changed = owner.patch(f"/api/v1/auth/users/{staff.id}", json={"portfolio_access": "selected", "portfolio_ids": [south.id]})
    assert changed.status_code == 200, changed.text
    for path in (f"drafts/{identifier}", f"favorites/property/{prop.id}", f"recents/property/{prop.id}"):
        assert viewer.get(f"{API}/{path}").status_code == 404
    for collection in ("drafts", "favorites", "recents"):
        listed = viewer.get(f"{API}/{collection}")
        assert listed.status_code == 200, listed.text
        assert listed.json()["items"] == [] and "Nordhaus" not in listed.text
    assert viewer.put(f"{API}/drafts/{identifier}", json=draft_body).status_code == 404
    assert viewer.put(f"{API}/favorites/property/{prop.id}", json=favorite).status_code == 404
    assert viewer.post(f"{API}/recents/events", json=recent).status_code == 404


def test_deleted_source_can_recover_only_with_original_portfolio_authority(estate):
    north, _, prop, _ = estate
    _, staff = client("deleted", "verwalter", portfolio_access="selected", portfolio_ids=[north.id])
    identifier = str(uuid4())
    response = staff.put(f"{API}/drafts/{identifier}", json=command(context="properties", mode="edit",
        source={"kind": "property", "id": prop.id, "revision": prop.updated_at.isoformat()},
        anchor={"kind": "property", "id": prop.id}, values={"name": "Wiederherstellbarer Text"}))
    assert response.status_code == 200, response.text
    store.delete_property(prop.id)
    recovered = staff.get(f"{API}/drafts/{identifier}")
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["source_state"]["status"] == "deleted"
    assert recovered.json()["values"]["name"] == "Wiederherstellbarer Text"


def test_deleted_source_does_not_bypass_other_saved_reference_permissions(estate):
    north, south, prop, _ = estate
    _, owner = client("deleted-ref-owner")
    user, staff = client("deleted-ref-staff", "verwalter", portfolio_access="selected", portfolio_ids=[north.id, south.id])
    identifier = str(uuid4())
    body = command(context="properties", mode="edit",
        source={"kind": "property", "id": prop.id, "revision": prop.updated_at.isoformat()},
        values={"name": "Entwurf", "portfolio_id": south.id})
    assert staff.put(f"{API}/drafts/{identifier}", json=body).status_code == 200
    store.delete_property(prop.id)
    assert staff.get(f"{API}/drafts/{identifier}").status_code == 200
    assert owner.patch(f"/api/v1/auth/users/{user.id}", json={"portfolio_access": "selected", "portfolio_ids": [north.id]}).status_code == 200
    assert staff.get(f"{API}/drafts/{identifier}").status_code == 404
    assert staff.put(f"{API}/drafts/{identifier}", json=body).status_code == 404


def test_credentials_foreign_references_and_role_mismatch_are_rejected(estate):
    north, _, _, foreign = estate
    _, staff = client("secure", "techniker", portfolio_access="selected", portfolio_ids=[north.id])
    assert staff.put(f"{API}/drafts/{uuid4()}", json=command(context="bookings", values={"amount": 123})).status_code == 403
    for values in ({"notes": {"api_token": "never-store"}}, {"password": "never-store"}):
        assert staff.put(f"{API}/drafts/{uuid4()}", json=command(context="tasks", values=values)).status_code == 422
    assert staff.put(f"{API}/drafts/{uuid4()}", json=command(context="tasks", values={"property_id": foreign.id})).status_code == 404
    assert staff.put(f"{API}/drafts/{uuid4()}", json=command(context="integrations", values={})).status_code == 422
    _, readonly = client("reader", "readonly")
    assert readonly.put(f"{API}/views/{uuid4()}", json=command(context="tasks", name="Meine Liste", config={})).status_code == 200
    assert readonly.put(f"{API}/drafts/{uuid4()}", json=command(context="tasks", values={})).status_code == 403


def test_named_views_and_same_area_table_state_keep_distinct_identities(estate):
    _, owner = client("views")
    for suffix, search in (("table-a", "Alpha"), ("table-b", "Beta")):
        path = f"{API}/view-state/tasks%23{suffix}"
        saved = owner.put(path, json=command(state={"search": search, "scroll_top": 400, "sort": {"key": "title", "direction": "asc"}}))
        assert saved.status_code == 200, saved.text
        view = owner.put(f"{API}/views/{uuid4()}", json=command(context=f"tasks#{suffix}", name="Gleichnamig", config={"search": search}))
        assert view.status_code == 200, view.text
    for suffix, search in (("table-a", "Alpha"), ("table-b", "Beta")):
        assert owner.get(f"{API}/view-state/tasks%23{suffix}").json()["state"]["search"] == search
        listed = owner.get(f"{API}/views", params={"context": f"tasks#{suffix}"}).json()["items"]
        assert len(listed) == 1 and listed[0]["config"]["search"] == search


def test_first_visit_view_state_is_null_with_missing_ok_and_404_without(estate):
    _, owner = client("first-visit")
    path = f"{API}/view-state/tasks%23first-visit"
    assert owner.get(path).status_code == 404
    first = owner.get(path, params={"missing_ok": "true"})
    assert first.status_code == 200 and first.json() is None
    assert owner.put(path, json=command(state={"search": "Erstbesuch"})).status_code == 200
    assert owner.get(path, params={"missing_ok": "true"}).json()["state"]["search"] == "Erstbesuch"
    favorite = f"{API}/favorites/property/{estate[2].id}"
    assert owner.get(favorite).status_code == 404
    unmarked = owner.get(favorite, params={"missing_ok": "true"})
    assert unmarked.status_code == 200 and unmarked.json() is None


def test_cursor_lists_continue_through_every_record_without_total_cap(estate):
    _, owner = client("pages")
    for index in range(7):
        response = owner.put(f"{API}/drafts/{uuid4()}", json=command(context="tasks", form_key="same-form", values={"title": str(index)}))
        assert response.status_code == 200, response.text
    found: list[str] = []
    cursor = None
    while True:
        params = {"context": "tasks", "form_key": "same-form", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        response = owner.get(f"{API}/drafts", params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        found.extend(row["values"]["title"] for row in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert set(found) == {str(index) for index in range(7)} and len(found) == 7


def test_recents_hydrate_current_labels_and_deferrals_stay_private(estate):
    north, _, prop, _ = estate
    _, staff = client("personal", "verwalter", portfolio_access="selected", portfolio_ids=[north.id])
    _, other = client("other-personal")
    task = store.create_task(TaskCreate(property_id=prop.id, title="Rückruf", due_date=date(2026, 10, 1)))
    recent = staff.post(f"{API}/recents/events", json={"kind": "property", "entity_id": prop.id, "idempotency_key": str(uuid4())})
    assert recent.status_code == 200, recent.text
    store.update_property(prop.id, PropertyCreate(**{**prop.model_dump(), "name": "Neuer Name"}))
    assert staff.get(f"{API}/recents").json()["items"][0]["title"] == "Neuer Name"
    key = f"task:{task.id}:task_due"
    response = staff.put(f"{API}/deferrals/{key}", json=command(due_on="2026-11-01", reason="Warte auf Rückruf"))
    assert response.status_code == 200, response.text
    assert response.json()["work_item_key"] == key and response.json()["revision"] == 1
    assert other.get(f"{API}/deferrals/{key}").status_code == 404
    assert store.get_task(task.id).due_date == date(2026, 10, 1)


def test_context_registry_contains_real_reading_and_conversation_fields(estate):
    _, owner = client("registry")
    response = owner.get(f"{API}/contexts")
    assert response.status_code == 200, response.text
    contexts = {row["context"]: row for row in response.json()["items"]}
    assert {"reading_date", "value", "recorded_by"}.issubset(contexts["meters"]["field_keys"])
    assert {"conversation_kind", "follow_up_title", "follow_up_due"}.issubset(contexts["conversation-note"]["field_keys"])
    assert "integrations" not in contexts


def test_custom_drafts_recheck_nested_references_and_clear_confirmations(estate):
    north, _, prop, foreign = estate
    _, staff = client("nested", "verwalter", portfolio_access="selected", portfolio_ids=[north.id])
    anchor = {"kind": "property", "id": prop.id}
    forbidden = staff.put(f"{API}/drafts/{uuid4()}", json=command(context="maintenance-protocol", anchor=anchor,
        values={"defects": [{"description": "Ungültiger Bezug", "property_id": foreign.id}]}))
    assert forbidden.status_code == 404, forbidden.text
    housing = staff.put(f"{API}/drafts/{uuid4()}", json=command(context="housing-confirmation", anchor=anchor,
        values={"occupants": [{"key": "local-person", "name": "Mia"}], "confirmed_authority": True,
                "confirmed_actual_move_in": True, "confirmed_residents": True, "correction_of": None}))
    assert housing.status_code == 200, housing.text
    assert housing.json()["values"]["occupants"][0]["name"] == "Mia"
    assert housing.json()["values"]["confirmed_authority"] is False
    source = staff.get(f"{API}/source/property/{prop.id}")
    assert source.status_code == 200 and set(source.json()) == {"kind", "id", "revision", "title", "href", "values", "dependency_etags"}
    assert source.json()["values"]["id"] == prop.id


def test_revoked_row_mark_is_omitted_from_read_and_retry_without_mutating_state(estate):
    north, south, prop, _ = estate
    _, owner = client("mark-owner")
    user, staff = client("mark-staff", "verwalter", portfolio_access="selected", portfolio_ids=[north.id, south.id])
    body = command(state={"search": "Persönliche Suche", "scroll_top": 400, "row_mark": {"kind": "property", "id": prop.id}})
    assert staff.put(f"{API}/view-state/properties%23rows", json=body).status_code == 200
    assert owner.patch(f"/api/v1/auth/users/{user.id}", json={"portfolio_access": "selected", "portfolio_ids": [south.id]}).status_code == 200
    recovered = staff.get(f"{API}/view-state/properties%23rows")
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["state"]["scroll_top"] == 400 and "row_mark" not in recovered.json()["state"]
    replay = staff.put(f"{API}/view-state/properties%23rows", json=body)
    assert replay.status_code == 200, replay.text
    assert "row_mark" not in replay.json()["state"]
    assert owner.patch(f"/api/v1/auth/users/{user.id}", json={"portfolio_access": "selected", "portfolio_ids": [north.id, south.id]}).status_code == 200
    assert staff.get(f"{API}/view-state/properties%23rows").json()["state"]["row_mark"]["id"] == prop.id
    assert owner.patch(f"/api/v1/auth/users/{user.id}", json={"portfolio_access": "selected", "portfolio_ids": [south.id]}).status_code == 200
    # A revoked old mark must not prevent saving a newly authorized position.
    replacement = staff.put(f"{API}/view-state/properties%23rows", json=command(1, state={"scroll_top": 450}))
    assert replacement.status_code == 200, replacement.text
    assert replacement.json()["state"] == {"scroll_top": 450}


def test_simultaneous_retries_create_once_and_competing_updates_conflict(estate, monkeypatch):
    _, owner = client("race")
    postgres_pids: set[int] = set()
    native = hasattr(store, "db") and store.db.get_bind().dialect.name == "postgresql"
    if native:
        from threading import Barrier

        from backend.services import document_versions as archive

        ready = Barrier(2)
        begin = archive.begin_writer

        def begin_independently(db):
            begin(db)
            if len(postgres_pids) < 2:
                connection = db.connection().connection.driver_connection
                postgres_pids.add(connection.get_backend_pid())
                ready.wait(timeout=15)

        monkeypatch.setattr(archive, "begin_writer", begin_independently)
    path = f"{API}/drafts/{uuid4()}"
    body = command(context="tasks", values={"title": "Einmal"})
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: owner.put(path, json=body), range(2)))
    assert [result.status_code for result in results] == [200, 200]
    assert results[0].json() == results[1].json()
    competing = [command(1, context="tasks", values={"title": title}) for title in ("A", "B")]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda value: owner.put(path, json=value), competing))
    assert sorted(result.status_code for result in results) == [200, 409]
    assert owner.get(path).json()["revision"] == 2
    if native:
        assert len(postgres_pids) == 2


def test_context_links_identify_exact_records_and_derive_unambiguous_property(estate):
    from backend.services.workspace_contexts import resolve_context

    _, _, prop, foreign = estate
    user, owner = client("context-links")
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="1", unit_type="apartment"))
    tenant = store.create_tenant(TenantCreate(full_name="Gleicher Name"))
    contract = store.create_contract(ContractCreate(property_id=prop.id, unit_id=unit.id, tenant_id=tenant.id,
        contract_number="V1", start_date=date(2026, 1, 1)))
    receivable = store.create_receivable(ReceivableCreate(contract_id=contract.id, due_date=date(2026, 1, 1), amount_due=10))
    meter = store.create_meter(MeterCreate(unit_id=unit.id, meter_type="cold_water"))
    for kind, identifier in (("property", prop.id), ("unit", unit.id), ("contract", contract.id),
                             ("receivable", receivable.id), ("meter", meter.id), ("tenant", tenant.id)):
        assert resolve_context(store, kind, identifier, user.id)["property_id"] == prop.id
    assert owner.get(f"{API}/source/tenant/{tenant.id}").json()["href"] == f"/tenants?focus_id={tenant.id}"
    assert owner.get(f"{API}/source/contract/{contract.id}").json()["href"] == f"/contracts?focus_id={contract.id}"
    other_unit = store.create_unit(UnitCreate(property_id=foreign.id, label="2", unit_type="apartment"))
    store.create_contract(ContractCreate(property_id=foreign.id, unit_id=other_unit.id, tenant_id=tenant.id,
        contract_number="V2", start_date=date(2026, 1, 1)))
    assert resolve_context(store, "tenant", tenant.id, user.id)["property_id"] is None


def test_workspace_migration_adopts_existing_tables_and_preserves_records(tmp_path):
    migration = import_module("backend.db.migrations.versions.a71c4e9f2036_personal_workspace")
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    metadata = MetaData()
    users = Table("users", metadata, Column("id", String(), primary_key=True))
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(users.insert().values(id="owner"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            table = Table("workspace_drafts", MetaData(), autoload_with=connection)
            connection.execute(table.insert().values(id="draft", owner_user_id="owner", revision=1,
                context="tasks", payload={"values": {"title": "Erhalten"}}, created_at=date(2026, 1, 1), updated_at=date(2026, 1, 1)))
            migration.upgrade()  # create_all/adoption must not replace existing state
            assert connection.execute(select(table.c.payload)).scalar_one()["values"]["title"] == "Erhalten"
            assert inspect(connection).get_pk_constraint("workspace_drafts")["constrained_columns"] == ["id", "owner_user_id"]
            migration.downgrade()
        assert inspect(connection).get_table_names() == ["users"]
        assert connection.execute(select(users.c.id)).scalar_one() == "owner"
    engine.dispose()


def test_contract_wizard_creates_private_nested_draft_without_source_or_anchor(estate):
    north, _, prop, foreign = estate
    _, staff = client("wizard", "verwalter", portfolio_access="selected", portfolio_ids=[north.id])
    identifier = str(uuid4())
    saved = staff.put(f"{API}/drafts/{identifier}", json=command(context="contract-wizard",
        values={"form": {"property_id": prop.id, "tenant": {"name": "Anna"}}}))
    assert saved.status_code == 200, saved.text
    assert saved.json()["source_state"]["status"] == "new"
    assert saved.json()["values"]["form"]["tenant"]["name"] == "Anna"
    denied = staff.put(f"{API}/drafts/{uuid4()}", json=command(context="contract-wizard",
        values={"form": {"property_id": foreign.id}}))
    assert denied.status_code == 404
    credentials = staff.put(f"{API}/drafts/{uuid4()}", json=command(context="contract-wizard",
        values={"form": {"tenant": {"password": "hidden"}}}))
    assert credentials.status_code == 422


def test_anchor_only_create_draft_detects_changes_and_rebases_without_executing_domain(estate):
    _, _, prop, _ = estate
    _, owner = client("anchor-only")
    identifier = str(uuid4())
    body = command(context="conversation-note", anchor={"kind": "property", "id": prop.id},
                   values={"body": "Noch nicht geführtes Gespräch"})
    saved = owner.put(f"{API}/drafts/{identifier}", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["source"] is None
    assert saved.json()["anchor_revision"] == prop.updated_at.isoformat()
    updated = store.update_property(prop.id, PropertyCreate(**{**prop.model_dump(), "name": "Geänderte Akte"}))
    recovered = owner.get(f"{API}/drafts/{identifier}").json()
    assert recovered["source_state"]["status"] == "changed"
    assert recovered["source_state"]["reference"] == "anchor"
    assert recovered["values"]["body"] == "Noch nicht geführtes Gespräch"
    tokens = dependency_etags(owner, "property", prop.id)
    assert owner.post(f"{API}/drafts/{identifier}/rebase", json=command(1, source_revision=updated.updated_at.isoformat(), values=recovered["values"])).status_code == 422
    assert owner.post(f"{API}/drafts/{identifier}/rebase", json=command(1, source_revision=prop.updated_at.isoformat(), dependency_etags=tokens, values=recovered["values"])).status_code == 409
    rebased = owner.post(f"{API}/drafts/{identifier}/rebase", json=command(1, source_revision=updated.updated_at.isoformat(), dependency_etags=tokens, values=recovered["values"]))
    assert rebased.status_code == 200, rebased.text
    assert rebased.json()["source"] is None and rebased.json()["source_state"]["status"] == "current"
    assert rebased.json()["anchor_revision"] == updated.updated_at.isoformat()
    assert not store.list_tasks()
    store.delete_property(prop.id)
    deleted = owner.get(f"{API}/drafts/{identifier}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["source_state"]["status"] == "deleted"
    assert deleted.json()["values"]["body"] == "Noch nicht geführtes Gespräch"
