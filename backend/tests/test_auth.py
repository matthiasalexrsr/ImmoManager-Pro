"""Tests for authentication: registration, login, JWT tokens, RBAC."""

import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException

from backend.auth import (
    SQLUserStore,
    authenticate_user,
    clear_users,
    create_access_token,
    create_refresh_token,
    decode_token,
    delete_user,
    hash_password,
    is_token_revoked,
    list_users,
    register_user,
    revoke_token,
    update_user,
    verify_password,
)
from backend.models import (
    LoginRequest,
    RefreshRequest,
    UserCreate,
    UserPatch,
    UserRead,
)
from backend.routers.auth import (
    get_me,
    get_my_preferences,
    get_users,
    login,
    logout,
    patch_user,
    refresh,
    register,
    remove_user,
    update_my_preferences,
)


@pytest.fixture(autouse=True)
def _clean_users():
    """Clear user store before each test."""
    clear_users()
    yield
    clear_users()


def _register_admin() -> UserRead:
    return register_user("admin", "admin@example.com", "Admin User", "Secret123", "eigentuemer")


def _register_viewer() -> UserRead:
    return register_user("viewer", "viewer@example.com", "View User", "Pass1234", "readonly")



# === Password Hashing ===

class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = hash_password("mypassword")
        assert hashed != "mypassword"
        assert verify_password("mypassword", hashed)

    def test_wrong_password(self):
        hashed = hash_password("correct")
        assert not verify_password("wrong", hashed)


# === JWT Tokens ===

class TestTokens:
    def test_create_access_token(self):
        token = create_access_token("user-123")
        payload = decode_token(token)
        assert payload.sub == "user-123"
        assert payload.type == "access"

    def test_create_refresh_token(self):
        token = create_refresh_token("user-123")
        payload = decode_token(token)
        assert payload.sub == "user-123"
        assert payload.type == "refresh"

    def test_invalid_token(self):
        with pytest.raises(HTTPException) as exc_info:
            decode_token("invalid.token.here")
        assert exc_info.value.status_code == 401


# === User Management ===

class TestUserManagement:
    def test_register_user(self):
        user = _register_admin()
        assert user.username == "admin"
        assert user.email == "admin@example.com"
        assert user.role == "eigentuemer"
        assert user.id

    def test_duplicate_username(self):
        _register_admin()
        with pytest.raises(HTTPException) as exc_info:
            register_user("admin", "other@example.com", "Other", "Pass1234", "readonly")
        assert exc_info.value.status_code == 409

    def test_authenticate_valid(self):
        _register_admin()
        user = authenticate_user("admin", "Secret123")
        assert user is not None
        assert user["username"] == "admin"

    def test_authenticate_wrong_password(self):
        _register_admin()
        user = authenticate_user("admin", "wrong")
        assert user is None

    def test_authenticate_nonexistent(self):
        user = authenticate_user("nobody", "pass")
        assert user is None

    def test_authenticate_inactive_user(self):
        u = _register_admin()
        update_user(u.id, {"is_active": False})
        user = authenticate_user("admin", "Secret123")
        assert user is None

    def test_list_users(self):
        _register_admin()
        _register_viewer()
        users = list_users()
        assert len(users) == 2

    def test_update_user(self):
        u = _register_admin()
        updated = update_user(u.id, {"full_name": "Updated Name"})
        assert updated.full_name == "Updated Name"

    def test_update_nonexistent(self):
        with pytest.raises(HTTPException) as exc_info:
            update_user("nonexistent", {"full_name": "X"})
        assert exc_info.value.status_code == 404

    def test_delete_user(self):
        u = _register_admin()
        delete_user(u.id)
        assert len(list_users()) == 0

    def test_delete_nonexistent(self):
        with pytest.raises(HTTPException) as exc_info:
            delete_user("nonexistent")
        assert exc_info.value.status_code == 404


# === Auth Router ===

class TestAuthRouter:
    def test_register_endpoint(self):
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        result = register(UserCreate(
            username="test", email="test@example.com",
            full_name="Test User", password="Pass1234"
        ), request=mock_request)
        assert result.username == "test"

    def test_login_endpoint(self):
        _register_admin()
        result = login(LoginRequest(username="admin", password="Secret123"))
        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "bearer"

    def test_login_invalid(self):
        with pytest.raises(HTTPException) as exc_info:
            login(LoginRequest(username="nobody", password="wrong"))
        assert exc_info.value.status_code == 401

    def test_refresh_endpoint(self):
        user = _register_admin()
        refresh_tok = create_refresh_token(user.id)
        result = refresh(RefreshRequest(refresh_token=refresh_tok))
        assert result.access_token
        assert result.refresh_token

    def test_refresh_with_access_token_fails(self):
        user = _register_admin()
        access_tok = create_access_token(user.id)
        with pytest.raises(HTTPException) as exc_info:
            refresh(RefreshRequest(refresh_token=access_tok))
        assert exc_info.value.status_code == 401

    def test_get_me(self):
        user = _register_admin()
        result = get_me(user)
        assert result.username == "admin"

    def test_get_my_preferences_returns_defaults_on_sqlite(self, monkeypatch):
        user = _register_admin()
        monkeypatch.setattr("backend.db.session.DATABASE_URL", "sqlite:///./immo_manager.db")
        prefs = get_my_preferences(user)
        assert prefs["theme"] == "light"
        assert prefs["locale"] == "de-DE"


    def test_update_my_preferences_returns_defaults_merged_on_sqlite(self, monkeypatch):
        user = _register_admin()
        monkeypatch.setattr("backend.db.session.DATABASE_URL", "sqlite:///./immo_manager.db")

        updated = update_my_preferences({"theme": "dark"}, user)
        assert updated["theme"] == "dark"
        assert updated["locale"] == "de-DE"
        assert updated["currency"] == "EUR"

    def test_update_my_preferences_returns_fallback_when_session_init_fails(self, monkeypatch):
        user = _register_admin()

        monkeypatch.setattr("backend.db.session.DATABASE_URL", "postgresql://db/test")

        def _raise_session_error():
            raise RuntimeError("db down")

        monkeypatch.setattr("backend.db.session.SessionLocal", _raise_session_error)

        updated = update_my_preferences({"theme": "dark", "locale": "en-US", "ignored": "x"}, user)
        assert updated["theme"] == "dark"
        assert updated["locale"] == "en-US"
        assert "ignored" not in updated

    def test_update_my_preferences_returns_fallback_when_commit_fails(self, monkeypatch):
        user = _register_admin()

        monkeypatch.setattr("backend.db.session.DATABASE_URL", "postgresql://db/test")

        class _BrokenSession:
            def query(self, _model):
                return self

            def filter(self, *_args, **_kwargs):
                return self

            def first(self):
                return None

            def add(self, _obj):
                return None

            def commit(self):
                raise RuntimeError("commit failed")

            def rollback(self):
                return None

            def close(self):
                return None

        monkeypatch.setattr("backend.db.session.SessionLocal", lambda: _BrokenSession())

        updated = update_my_preferences({"theme": "dark", "currency": "USD"}, user)
        assert updated["theme"] == "dark"
        assert updated["currency"] == "USD"



# === RBAC ===

class TestRBAC:
    def test_get_users_as_admin(self):
        admin = _register_admin()
        _register_viewer()
        result = get_users(skip=0, limit=100, user=admin)
        assert len(result) == 2

    def test_patch_user_as_admin(self):
        admin = _register_admin()
        viewer = _register_viewer()
        result = patch_user(viewer.id, UserPatch(full_name="Updated"), user=admin)
        assert result.full_name == "Updated"

    def test_manager_cannot_promote_self_to_owner(self, monkeypatch):
        manager = UserRead(
            id="manager-1",
            username="manager",
            email="manager@example.com",
            full_name="Manager User",
            role="verwalter",
            is_active=True,
        )

        monkeypatch.setattr("backend.routers.auth.update_user", lambda *_args, **_kwargs: manager)

        with pytest.raises(HTTPException) as exc_info:
            patch_user(manager.id, UserPatch(role="eigentuemer"), user=manager)
        assert exc_info.value.status_code == 403

    def test_delete_user_as_owner(self):
        admin = _register_admin()
        viewer = _register_viewer()
        remove_user(viewer.id, user=admin)
        assert len(list_users()) == 1

    def test_cannot_delete_self(self):
        admin = _register_admin()
        with pytest.raises(HTTPException) as exc_info:
            remove_user(admin.id, user=admin)
        assert exc_info.value.status_code == 400


# === Token Revocation / Logout ===

class TestTokenRevocation:
    def test_revoke_access_token(self):
        token = create_access_token("user-123")
        assert not is_token_revoked(token)
        revoke_token(token)
        assert is_token_revoked(token)
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token)
        assert exc_info.value.status_code == 401

    def test_revoke_refresh_token(self):
        token = create_refresh_token("user-456")
        revoke_token(token)
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token)
        assert exc_info.value.status_code == 401

    def test_revoke_invalid_token_no_error(self):
        revoke_token("totally.invalid.token")
        # Should not raise

    def test_logout_endpoint(self):
        _register_admin()
        result = login(LoginRequest(username="admin", password="Secret123"))
        resp = logout({"access_token": result.access_token, "refresh_token": result.refresh_token})
        assert "abgemeldet" in resp["detail"].lower() or "erfolgreich" in resp["detail"].lower()
        assert is_token_revoked(result.access_token)
        assert is_token_revoked(result.refresh_token)


class TestSQLUserStoreSessionCleanup:
    def test_finalize_session_removes_scoped_session_when_available(self):
        calls: list[str] = []

        class _Session:
            def close(self):
                calls.append("close")

        class _ScopedFactory:
            def __call__(self):
                return _Session()

            def remove(self):
                calls.append("remove")

        store = SQLUserStore(_ScopedFactory())
        store._finalize_session(_Session())

        assert calls == ["close", "remove"]

    def test_finalize_session_closes_non_scoped_sessions(self):
        calls: list[str] = []

        class _Session:
            def close(self):
                calls.append("close")

        class _SessionFactory:
            def __call__(self):
                return _Session()

        store = SQLUserStore(_SessionFactory())
        store._finalize_session(_Session())

        assert calls == ["close"]

    def test_finalize_session_calls_remove_even_if_close_fails(self):
        calls: list[str] = []

        class _Session:
            def close(self):
                calls.append("close")
                raise RuntimeError("close failed")

        class _ScopedFactory:
            def __call__(self):
                return _Session()

            def remove(self):
                calls.append("remove")

        store = SQLUserStore(_ScopedFactory())

        with pytest.raises(RuntimeError, match="close failed"):
            store._finalize_session(_Session())

        assert calls == ["close", "remove"]

