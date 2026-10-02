"""Real permission, owner-continuity, validation and independent-session races."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.app import app
from backend.db.access_models import UserAccessORM, UserPortfolioORM
from backend.db.auth_models import AuthSetupORM
from backend.db.orm_models import Base, LoginAttemptORM, PortfolioORM, RevokedTokenORM, UserORM
from backend.db.session_models import AuthRefreshORM, AuthSessionORM


@pytest.fixture(params=["memory", "sqlite"])
def managed_users(request, monkeypatch, tmp_path):
    engine = None
    factory = None
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path / 'users.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine, tables=[UserORM.__table__, AuthSetupORM.__table__, LoginAttemptORM.__table__, RevokedTokenORM.__table__,
                                                PortfolioORM.__table__, UserAccessORM.__table__, UserPortfolioORM.__table__,
                                                AuthSessionORM.__table__, AuthRefreshORM.__table__])
        factory = sessionmaker(bind=engine)
        store = auth.SQLUserStore(factory)
    else:
        store = auth.InMemoryUserStore()
    monkeypatch.setattr(auth, "_user_store", store)
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Strong123", "eigentuemer")
    manager = auth.register_user("manager", "manager@example.com", "Manager", "Strong123", "verwalter")
    reader = auth.register_user("reader", "reader@example.com", "Reader", "Strong123", "readonly")
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield store, client, owner, manager, reader
    if engine:
        engine.dispose()


def headers(user):
    return {"Authorization": "Bearer " + auth.create_access_token(user.id)}


@pytest.mark.parametrize("change", [{"is_active": False}, {"full_name": "Changed"}, {"email": "other@example.com"}])
def test_manager_cannot_change_any_owner_field(managed_users, change):
    store, client, owner, manager, _ = managed_users
    before = store.get_by_id(owner.id)
    response = client.patch(f"/api/v1/auth/users/{owner.id}", headers=headers(manager), json=change)
    assert response.status_code == 403
    assert store.get_by_id(owner.id) == before


def test_manager_cannot_assign_roles_but_can_manage_nonowner_profiles(managed_users):
    store, client, _, manager, reader = managed_users
    assert client.patch(f"/api/v1/auth/users/{reader.id}", headers=headers(manager), json={"role": "eigentuemer"}).status_code == 403
    response = client.patch(f"/api/v1/auth/users/{reader.id}", headers=headers(manager), json={"full_name": "Approved reader", "is_active": False})
    assert response.status_code == 200
    assert store.get_by_id(reader.id)["full_name"] == "Approved reader"
    assert store.get_by_id(reader.id)["is_active"] is False


@pytest.mark.parametrize("change", [{"is_active": False}, {"role": "verwalter"}, {"role": "readonly"}])
def test_owner_cannot_disable_or_downgrade_self_even_with_another_owner(managed_users, change):
    store, client, owner, _, _ = managed_users
    auth.register_user("second", "second@example.com", "Second", "Strong123", "eigentuemer")
    response = client.patch(f"/api/v1/auth/users/{owner.id}", headers=headers(owner), json=change)
    assert response.status_code == 409
    assert store.get_by_id(owner.id)["role"] == "eigentuemer"
    assert store.get_by_id(owner.id)["is_active"] is True
    assert client.patch(f"/api/v1/auth/users/{owner.id}", headers=headers(owner), json={"full_name": "New owner name", "email": "new-owner@example.com"}).status_code == 200


@pytest.mark.parametrize("action", ["disable", "downgrade", "delete"])
def test_last_active_owner_survives_all_destructive_storage_paths(managed_users, action):
    store, _, owner, _, _ = managed_users
    inactive = auth.register_user("inactive", "inactive@example.com", "Inactive Owner", "Strong123", "eigentuemer")
    store.update(inactive.id, {"is_active": False})
    with pytest.raises(HTTPException) as error:
        if action == "delete":
            store.delete(owner.id)
        else:
            store.update(owner.id, {"is_active": False} if action == "disable" else {"role": "readonly"})
    assert error.value.status_code == 409
    assert store.get_by_id(owner.id)["role"] == "eigentuemer"
    assert store.get_by_id(owner.id)["is_active"] is True


@pytest.mark.parametrize("change", [
    {"role": "unsupported"}, {"role": None}, {"email": None}, {"full_name": None}, {"is_active": None},
    {"email": "missing-at"}, {"email": "owner@"}, {"email": "a b@example.com"},
])
def test_invalid_user_patch_is_422_without_mutation(managed_users, change):
    store, client, owner, _, reader = managed_users
    before = store.get_by_id(reader.id)
    assert client.patch(f"/api/v1/auth/users/{reader.id}", headers=headers(owner), json=change).status_code == 422
    assert store.get_by_id(reader.id) == before


def test_duplicate_email_is_a_conflict_and_keeps_existing_profile(managed_users):
    store, client, owner, _, reader = managed_users
    assert client.patch(f"/api/v1/auth/users/{reader.id}", headers=headers(owner), json={"email": owner.email, "full_name": "Should roll back"}).status_code == 409
    assert store.get_by_id(reader.id)["full_name"] == "Reader"
    assert store.get_by_id(reader.id)["email"] == "reader@example.com"


@pytest.mark.parametrize("action", ["disable", "downgrade", "delete"])
def test_parallel_changes_of_final_two_owners_leave_one_active(managed_users, action):
    store, _, first, _, _ = managed_users
    second = auth.register_user("second", "second@example.com", "Second", "Strong123", "eigentuemer")
    barrier = Barrier(2)

    def remove_owner(identity):
        barrier.wait(timeout=10)
        try:
            if action == "delete":
                store.delete(identity)
            else:
                store.update(identity, {"is_active": False} if action == "disable" else {"role": "readonly"})
            return 200
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(remove_owner, [first.id, second.id]))
    assert sorted(results) == [200, 409]
    assert sum(user["role"] == "eigentuemer" and user["is_active"] for user in store.list_all()) == 1


def test_actor_permissions_are_rechecked_inside_the_transaction(managed_users):
    store, _, first, _, reader = managed_users
    second = auth.register_user("second", "second@example.com", "Second", "Strong123", "eigentuemer")
    store.update(second.id, {"is_active": False}, actor_id=first.id)
    with pytest.raises(HTTPException) as error:
        store.update(reader.id, {"full_name": "Stale authenticated actor"}, actor_id=second.id)
    assert error.value.status_code == 403
    assert store.get_by_id(reader.id)["full_name"] == "Reader"


def test_owners_can_manage_another_owner_while_continuity_is_preserved(managed_users):
    store, client, first, _, _ = managed_users
    second = auth.register_user("second", "second@example.com", "Second", "Strong123", "eigentuemer")
    assert client.patch(f"/api/v1/auth/users/{second.id}", headers=headers(first), json={"role": "readonly"}).status_code == 200
    assert store.get_by_id(first.id)["role"] == "eigentuemer"
    assert client.delete(f"/api/v1/auth/users/{second.id}", headers=headers(first)).status_code == 204
    assert store.get_by_id(second.id) is None


def test_parallel_http_owners_cannot_deactivate_each_other_and_leave_no_owner(managed_users):
    store, client, first, _, _ = managed_users
    second = auth.register_user("second", "second@example.com", "Second", "Strong123", "eigentuemer")
    barrier = Barrier(2)
    def deactivate(pair):
        actor, target = pair
        authorization = headers(actor)
        barrier.wait(timeout=10)
        return client.patch(f"/api/v1/auth/users/{target.id}", headers=authorization, json={"is_active": False}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(deactivate, [(first, second), (second, first)]))
    assert statuses.count(200) == 1
    assert all(status in {200, 403, 409} for status in statuses)
    assert sum(user["is_active"] and user["role"] == "eigentuemer" for user in store.list_all()) == 1


def test_production_account_creation_accepts_long_passphrases_and_rejects_short_passwords(managed_users, monkeypatch):
    _, client, owner, _, _ = managed_users
    monkeypatch.setattr(auth.settings, "environment", "production")
    body = {"username": "new", "email": "new@example.com", "full_name": "New User", "password": "Strong123", "role": "readonly"}
    assert client.post("/api/v1/auth/users", headers=headers(owner), json=body).status_code == 400
    body["password"] = "a long private passphrase"
    assert client.post("/api/v1/auth/users", headers=headers(owner), json=body).status_code == 201
    # Existing short legacy passwords still authenticate.
    assert client.post("/api/v1/auth/login", json={"username": "owner", "password": "Strong123"}).status_code == 200


def test_production_local_setup_enforces_twelve_characters_without_weakening_peer_guard(managed_users, monkeypatch):
    store, local, _, _, _ = managed_users
    store.clear()
    monkeypatch.setattr(auth.settings, "environment", "production")
    body = {"username": "new-owner", "email": "new-owner@example.com", "full_name": "Synthetic", "password": "Strong123"}
    assert local.post("/api/v1/auth/setup", json=body).status_code == 400
    body["password"] = "a long local owner passphrase"
    assert local.post("/api/v1/auth/setup", json=body, headers={"Host": "foreign.example"}).status_code == 403
    assert local.post("/api/v1/auth/setup", json=body).status_code == 201
    assert local.post("/api/v1/auth/setup", json=body).status_code == 409
