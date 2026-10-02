"""Actual draft ciphertext, scopes, expiration and independent writer conflicts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from backend import auth, dependencies
from backend.db.form_draft_models import FormDraftORM
from backend.db.orm_models import Base
from backend.form_draft_models import DraftIdentity, DraftWrite
from backend.middleware import RBACWriteGuardMiddleware
from backend.models import ContractCreate, PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import form_drafts as router
from backend.services import form_draft_crypto, form_drafts
from backend.services.iban_encryption import IBANKeyring, generate_key
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.storage import InMemoryStore
from backend.tests.test_private_server_concurrency import postgres_database  # noqa: F401

ENDPOINT = "/api/v1/auth/users/me/form-drafts"


@pytest.fixture(params=["memory", "sql"])
def workspace(request, tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "drafts.sqlite").as_posix(), hide_parameters=True)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    db = Session(engine)
    store = InMemoryStore() if request.param == "memory" else SQLAlchemyStore(db)
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore() if request.param == "memory" else auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", None if request.param == "memory" else factory)
    monkeypatch.setattr(router, "store", store)
    monkeypatch.setattr(dependencies, "store", store)
    with scope_context(None):
        portfolios = [store.create_portfolio(PortfolioCreate(name="Synthetic " + str(i))) for i in range(2)]
        properties = [store.create_property(PropertyCreate(portfolio_id=p.id, name="Synthetic building", property_type="residential")) for p in portfolios]
        owner = auth.register_user("owner", "owner@example.test", "Owner", "Synthetic passphrase123!", "eigentuemer")
        member = auth.register_user("member", "member@example.test", "Member", "Synthetic passphrase123!", "verwalter",
            portfolio_access="selected", portfolio_ids=[portfolios[0].id])
    app = FastAPI()
    app.include_router(router.router, prefix="/api/v1")
    app.add_middleware(RBACWriteGuardMiddleware)
    with TestClient(PortfolioScopeMiddleware(app)) as client:
        yield store, portfolios, properties, owner, member, client, factory
    db.close()
    engine.dispose()


def actor(user):
    return scope_from_user(auth.get_user_by_id(user.id))


def identity(row=None, *, collection="properties"):
    return DraftIdentity(collection=collection, entity_id=row.id if row else None)


def payload(row, *, name="Not yet saved", revision=None, **changes):
    return DraftWrite(collection="properties", entity_id=row.id, schema="name:text|portfolio_id:select", expected_revision=revision,
        values={"name": name, "portfolio_id": row.portfolio_id}, original_values={"name": row.name, "portfolio_id": row.portfolio_id},
        edit_revision={"collection": "properties", "id": row.id, "updatedAt": row.updated_at.isoformat()}, **changes)


def read(store, user, row):
    return form_drafts.form_draft(store, identity(row), actor(user))["draft"]


def write(store, user, row, **values):
    data = payload(row, **values)
    return form_drafts.form_draft(store, data, actor(user), write=data)


def state(store):
    if hasattr(store, "db"):
        return [dict(row) for row in store.db.connection().execute(select(FormDraftORM.__table__)).mappings()]
    return list(object.__getattribute__(store, "__dict__").get("_form_drafts", {}).values())


def test_incomplete_values_are_saved_but_no_business_action_or_cleartext(workspace):
    store, _, properties, owner, *_ = workspace
    row = properties[0]
    saved = write(store, owner, row, name="Private synthetic name €")
    draft = read(store, owner, row)
    assert draft["revision"] == saved["revision"] and draft["values"]["name"] == "Private synthetic name €"
    assert store.get_property(row.id).name == row.name
    raw = state(store)[0]
    assert raw["payload"].startswith("draft:v1:") and "Private synthetic" not in raw["payload"] and row.name not in raw["payload"]
    assert "values" not in raw and saved["expires_at"] > saved["updated_at"]


def test_new_create_draft_never_creates_entity(workspace):
    store, portfolios, _, owner, *_ = workspace
    data = DraftWrite(collection="properties", schema="name:text", values={"name": "", "portfolio_id": portfolios[0].id, "purchase_price": "not a number"})
    before = len(store.list_properties())
    form_drafts.form_draft(store, data, actor(owner), write=data)
    restored = form_drafts.form_draft(store, DraftIdentity(collection="properties"), actor(owner))["draft"]
    assert restored["values"]["purchase_price"] == "not a number" and restored["edit_revision"] is None
    assert len(store.list_properties()) == before


def test_old_business_revision_survives_current_record_change(workspace):
    store, _, properties, owner, *_ = workspace
    row = properties[0]
    write(store, owner, row)
    store.update_property(row.id, PropertyCreate(portfolio_id=row.portfolio_id, name="Another writer", property_type="residential"))
    draft = read(store, owner, row)
    assert draft["edit_revision"]["updatedAt"] == row.updated_at.isoformat()
    assert draft["original_values"]["name"] == row.name and draft["values"]["name"] == "Not yet saved"


def test_user_entity_and_form_variant_are_independent(workspace):
    store, _, properties, owner, member, *_ = workspace
    row = properties[0]
    write(store, owner, row)
    assert read(store, member, row) is None and read(store, owner, properties[1]) is None
    assert form_drafts.form_draft(store, DraftIdentity(collection="properties", entity_id=row.id, form_key="different"), actor(owner))["draft"] is None
    write(store, member, row, name="Only member")
    assert read(store, owner, row)["values"]["name"] == "Not yet saved"


def test_tab_cas_and_discard_do_not_destroy_other_window(workspace):
    store, _, properties, owner, *_ = workspace
    row = properties[0]
    first = write(store, owner, row)
    newer = write(store, owner, row, revision=first["revision"], name="Window A")
    with pytest.raises(form_drafts.DraftError, match="Ein anderes Fenster"):
        write(store, owner, row, revision=first["revision"], name="Window B")
    with pytest.raises(form_drafts.DraftError):
        form_drafts.form_draft(store, identity(row), actor(owner), remove_revision=first["revision"])
    assert read(store, owner, row)["values"]["name"] == "Window A"
    assert form_drafts.form_draft(store, identity(row), actor(owner), remove_revision=newer["revision"]) == {"discarded": True}
    assert read(store, owner, row) is None


def test_direct_foreign_entity_and_reference_bypass_are_denied(workspace):
    store, portfolios, properties, _, member, *_ = workspace
    with pytest.raises(form_drafts.DraftError) as direct:
        write(store, member, properties[1])
    assert direct.value.status_code == 404
    data = payload(properties[0])
    data.values["portfolio_id"] = portfolios[1].id
    with pytest.raises(form_drafts.DraftError) as reference:
        form_drafts.form_draft(store, data, actor(member), write=data)
    assert reference.value.status_code == 403 and state(store) == []


def test_shared_tenant_draft_needs_all_linked_portfolios(workspace):
    store, _, properties, owner, member, *_ = workspace
    with scope_context(actor(owner)):
        tenant = store.create_tenant(TenantCreate(full_name="Synthetic shared tenant"))
        for index, property in enumerate(properties):
            unit = store.create_unit(UnitCreate(property_id=property.id, label="Synthetic", unit_type="apartment"))
            store.create_contract(ContractCreate(contract_number="Synthetic " + str(index), property_id=property.id,
                unit_id=unit.id, tenant_id=tenant.id, start_date=date(2026, 1, 1)))
    data = DraftWrite(collection="tenants", entity_id=tenant.id, schema="full_name:text", values={"full_name": "Private change"},
        original_values={"full_name": tenant.full_name}, edit_revision={"collection": "tenants", "id": tenant.id, "updatedAt": tenant.updated_at.isoformat()})
    with pytest.raises(form_drafts.DraftError) as denied:
        form_drafts.form_draft(store, data, actor(member), write=data)
    assert denied.value.status_code == 403 and state(store) == []


def test_scope_change_never_restores_previous_scope_payload(workspace):
    store, _, properties, owner, member, *_ = workspace
    old_actor = actor(member)
    saved = write(store, member, properties[0])
    auth.update_user(member.id, {"portfolio_access": "selected", "portfolio_ids": []}, actor_id=owner.id)
    with pytest.raises(Exception) as denied:
        form_drafts.form_draft(store, identity(properties[0]), old_actor)
    assert denied.value.status_code == 403
    auth.update_user(member.id, {"portfolio_access": "all", "portfolio_ids": []}, actor_id=owner.id)
    with pytest.raises(form_drafts.DraftError) as changed:
        read(store, member, properties[0])
    assert changed.value.code == "DRAFT_SCOPE_CHANGED" and state(store)[0]["revision"] == saved["revision"]


def test_reparented_current_entity_is_not_accessible(workspace):
    store, portfolios, properties, owner, member, *_ = workspace
    write(store, member, properties[0])
    with scope_context(actor(owner)):
        store.update_property(properties[0].id, PropertyCreate(portfolio_id=portfolios[1].id, name="Moved", property_type="residential"))
    with pytest.raises(form_drafts.DraftError) as unavailable:
        read(store, member, properties[0])
    assert unavailable.value.status_code == 404


@pytest.mark.parametrize("bad", [{"password": "Synthetic secret"}, {"name": {"nested": "no"}}, {"purchase_price": float("nan")}])
def test_secret_complex_and_nonfinite_fields_refused(workspace, bad):
    store, _, properties, owner, *_ = workspace
    data = payload(properties[0])
    data.values.update(bad)
    with pytest.raises(form_drafts.DraftError):
        form_drafts.form_draft(store, data, actor(owner), write=data)
    assert state(store) == []


def test_byte_budget_is_explicit_and_repairable(workspace, monkeypatch):
    store, _, properties, owner, *_ = workspace
    monkeypatch.setenv("FORM_DRAFT_MAX_BYTES", "1024")
    with pytest.raises(form_drafts.DraftError) as over:
        write(store, owner, properties[0], name="ü" * 1000)
    assert over.value.status_code == 413 and state(store) == []
    monkeypatch.setenv("FORM_DRAFT_MAX_BYTES", "8192")
    write(store, owner, properties[0], name="ü" * 1000)
    assert read(store, owner, properties[0])["values"]["name"] == "ü" * 1000


def test_invalid_configuration_never_claims_saved(workspace, monkeypatch):
    store, _, properties, owner, *_ = workspace
    monkeypatch.setenv("FORM_DRAFT_TTL_DAYS", "0")
    with pytest.raises(form_drafts.DraftError) as invalid:
        write(store, owner, properties[0])
    assert invalid.value.code == "DRAFT_CONFIGURATION_INVALID" and state(store) == []


def test_expiration_is_not_replayed_and_new_work_can_start(workspace):
    store, _, properties, owner, *_ = workspace
    write(store, owner, properties[0])
    old = datetime.now() - timedelta(days=1)
    if hasattr(store, "db"):
        store.db.connection().execute(update(FormDraftORM.__table__).values(expires_at=old))
        store.db.commit()
    else:
        state(store)[0]["expires_at"] = old
    assert read(store, owner, properties[0]) is None
    write(store, owner, properties[0], name="New work")
    assert read(store, owner, properties[0])["values"]["name"] == "New work"


def test_wrong_key_fail_closed_and_original_ciphertext_preserved(workspace, monkeypatch):
    store, _, properties, owner, *_ = workspace
    saved = write(store, owner, properties[0])
    before = state(store)[0]["payload"]
    ring = IBANKeyring("default", {"default": generate_key()})
    monkeypatch.setattr(form_draft_crypto, "current_keyring", lambda: ring)
    with pytest.raises(form_drafts.DraftError) as unavailable:
        read(store, owner, properties[0])
    assert unavailable.value.code == "DRAFT_ENCRYPTION_UNAVAILABLE"
    with pytest.raises(form_drafts.DraftError):
        write(store, owner, properties[0], name="Must not overwrite", revision=saved["revision"])
    assert state(store)[0]["payload"] == before


def test_ciphertext_cannot_be_moved_to_another_entity(workspace):
    store, _, properties, owner, *_ = workspace
    write(store, owner, properties[0])
    write(store, owner, properties[1])
    rows = state(store)
    if hasattr(store, "db"):
        store.db.connection().execute(update(FormDraftORM.__table__).where(FormDraftORM.id == rows[1]["id"]).values(payload=rows[0]["payload"]))
        store.db.commit()
    else:
        rows[1]["payload"] = rows[0]["payload"]
    with pytest.raises(form_drafts.DraftError) as corrupted:
        form_drafts.form_draft(store, DraftIdentity(collection=rows[1]["collection"], entity_id=rows[1]["entity_id"]), actor(owner))
    assert corrupted.value.code == "DRAFT_ENCRYPTION_UNAVAILABLE"


def test_actual_http_selected_routes_and_readonly_no_leak(workspace):
    store, _, properties, owner, member, client, *_ = workspace
    headers = {"Authorization": "Bearer " + auth.create_access_token(member.id)}
    data = {**payload(properties[0]).model_dump(by_alias=True), "owner_id": member.id}
    response = client.put(ENDPOINT, headers=headers, json=data)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    result = client.get(ENDPOINT, headers=headers, params={"collection": "properties", "entity_id": properties[0].id, "owner_id": member.id})
    assert result.status_code == 200 and result.json()["draft"]["values"]["name"] == "Not yet saved"
    assert client.get(ENDPOINT + "/other", headers=headers).status_code == 403
    auth.update_user(member.id, {"role": "readonly"}, actor_id=owner.id)
    denied = client.get(ENDPOINT, headers=headers, params={"collection": "properties", "entity_id": properties[0].id, "owner_id": member.id})
    assert denied.status_code == 403 and "Not yet saved" not in denied.text


def test_unsupported_commands_and_revision_identity_are_refused(workspace):
    store, _, properties, owner, *_ = workspace
    data = payload(properties[0])
    data.edit_revision["id"] = properties[1].id
    with pytest.raises(form_drafts.DraftError) as revision:
        form_drafts.form_draft(store, data, actor(owner), write=data)
    assert revision.value.code == "DRAFT_REVISION_INVALID"
    with pytest.raises(form_drafts.DraftError):
        form_drafts.form_draft(store, DraftIdentity(collection="billing/statements"), actor(owner))


def test_real_independent_sql_writers_only_one_wins(workspace):
    store, _, properties, owner, *_, factory = workspace
    if not hasattr(store, "db"):
        pytest.skip("Actual independent SQL sessions")
    saved = write(store, owner, properties[0])
    principal = actor(owner)
    barrier = Barrier(2)
    def worker(name):
        with factory() as db:
            fresh_store = SQLAlchemyStore(db)
            data = payload(properties[0], revision=saved["revision"], name=name)
            barrier.wait(timeout=10)
            try:
                form_drafts.form_draft(fresh_store, data, principal, write=data)
                return 200
            except form_drafts.DraftError as conflict:
                return conflict.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(worker, ["Window A", "Window B"])) == [200, 409]
    assert read(store, owner, properties[0])["values"]["name"] in {"Window A", "Window B"}
    assert store.db.scalar(text("SELECT count(*) FROM form_drafts")) == 1


def test_drafts_guard_reset_without_data_loss(workspace):
    store, _, properties, owner, *_ = workspace
    write(store, owner, properties[0])
    with pytest.raises(ValueError, match="Formularentwürfe"):
        form_drafts.guard_destructive_reset(store)
    assert read(store, owner, properties[0])["values"]["name"] == "Not yet saved" and store.get_property(properties[0].id).name == properties[0].name


def test_late_actual_memory_grant_revocation_keeps_store_unchanged(workspace, monkeypatch):
    store, _, properties, owner, member, *_ = workspace
    if hasattr(store, "db"):
        pytest.skip("Memory uses the actual shared account-management lock")
    original_encrypt = form_draft_crypto.encrypt
    def revoke_then_encrypt(data, identity):
        auth.update_user(member.id, {"portfolio_access": "selected", "portfolio_ids": []}, actor_id=owner.id)
        return original_encrypt(data, identity)
    monkeypatch.setattr(form_draft_crypto, "encrypt", revoke_then_encrypt)
    with pytest.raises(Exception) as revoked:
        write(store, member, properties[0])
    assert revoked.value.status_code == 403 and state(store) == []


def test_sql_denial_after_actual_insert_rolls_back_ciphertext_and_connection(workspace, monkeypatch):
    store, _, properties, _, member, *_ = workspace
    if not hasattr(store, "db"):
        pytest.skip("Actual SQL rollback after insertion")
    original = form_drafts._fresh
    calls = 0
    def deny_after_insert(principal, identity):
        nonlocal calls
        calls += 1
        original(principal, identity)
        if calls == 4:
            raise form_drafts.DraftError(403, "DRAFT_SCOPE_DENIED", "Synthetic late denial")
    monkeypatch.setattr(form_drafts, "_fresh", deny_after_insert)
    with pytest.raises(form_drafts.DraftError):
        write(store, member, properties[0])
    assert state(store) == [] and store.get_property(properties[0].id).name == properties[0].name


def test_raw_sqlite_backup_ciphertext_roundtrip_and_wrong_configuration(workspace, tmp_path):
    import sqlite3
    store, _, properties, owner, *_, factory = workspace
    if not hasattr(store, "db"):
        pytest.skip("Actual persisted encrypted SQLite backup")
    write(store, owner, properties[0])
    backup = tmp_path / "separate-restored.sqlite"
    source_path = factory.kw["bind"].url.database
    with sqlite3.connect(source_path) as source, sqlite3.connect(backup) as destination:
        source.backup(destination)
    ring = form_draft_crypto.current_keyring()
    assert form_draft_crypto.verify_database(backup, ring) == 1
    wrong = IBANKeyring(ring.active_key_id, {ring.active_key_id: generate_key()})
    with pytest.raises(form_draft_crypto.DraftCryptoError):
        form_draft_crypto.verify_database(backup, wrong)
    # Explicit captured keys work despite unrelated runtime-key changes.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(form_draft_crypto, "current_keyring", lambda: wrong)
        assert form_draft_crypto.verify_database(backup, ring) == 1


def test_actual_postgresql_independent_draft_cas_and_raw_ciphertext(postgres_database, monkeypatch):  # noqa: F811
    engine, factory, *_ = postgres_database
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    with factory() as db, scope_context(None):
        store = SQLAlchemyStore(db)
        owner = auth.register_user("draft-owner", "draft-owner@example.test", "Synthetic", "Synthetic passphrase123!", "eigentuemer")
        portfolio = store.create_portfolio(PortfolioCreate(name="Synthetic PG"))
        row = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Synthetic original", property_type="residential"))
        first = write(store, owner, row)
    principal = actor(owner)
    barrier = Barrier(2)
    def worker(name):
        with factory() as db:
            data = payload(row, name=name, revision=first["revision"])
            barrier.wait(timeout=20)
            try:
                form_drafts.form_draft(SQLAlchemyStore(db), data, principal, write=data)
                return 200
            except form_drafts.DraftError as failure:
                return failure.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(worker, ["Synthetic window A", "Synthetic window B"])) == [200, 409]
    with engine.connect() as connection:
        ciphertext = connection.scalar(text("SELECT payload FROM form_drafts"))
        assert ciphertext.startswith("draft:v1:") and "Synthetic" not in ciphertext
