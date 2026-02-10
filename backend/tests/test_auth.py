"""Tests for authentication: registration, login, JWT tokens, RBAC."""

import pytest
from datetime import datetime

from backend.auth import (
    authenticate_user,
    clear_users,
    create_access_token,
    create_refresh_token,
    decode_token,
    delete_user,
    get_user_by_id,
    hash_password,
    list_users,
    register_user,
    update_user,
    verify_password,
)
from backend.models import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserPatch,
    UserRead,
)
from backend.routers.auth import (
    get_me,
    get_users,
    login,
    patch_user,
    register,
    refresh,
    remove_user,
)

from fastapi import HTTPException


@pytest.fixture(autouse=True)
def _clean_users():
    """Clear user store before each test."""
    clear_users()
    yield
    clear_users()


def _register_admin() -> UserRead:
    return register_user("admin", "admin@example.com", "Admin User", "secret123", "eigentuemer")


def _register_viewer() -> UserRead:
    return register_user("viewer", "viewer@example.com", "View User", "pass123", "readonly")


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
            register_user("admin", "other@example.com", "Other", "pass", "readonly")
        assert exc_info.value.status_code == 409

    def test_authenticate_valid(self):
        _register_admin()
        user = authenticate_user("admin", "secret123")
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
        user = authenticate_user("admin", "secret123")
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
        result = register(UserCreate(
            username="test", email="test@example.com",
            full_name="Test User", password="pass123"
        ))
        assert result.username == "test"

    def test_login_endpoint(self):
        _register_admin()
        result = login(LoginRequest(username="admin", password="secret123"))
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
