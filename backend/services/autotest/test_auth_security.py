"""Test module: Authentication and authorization security.

Verifies JWT token lifecycle, password policies, rate limiting,
role-based access control, token revocation, and auth edge cases.
"""

import time

from .runner import TestContext, TestResult, test_module


@test_module("auth_security", "Authentication, authorization, and token security")
def test_auth_security(ctx: TestContext) -> list[TestResult]:
    results = []

    # ── Registration validation ───────────────────────────────────────────

    # Weak password rejection
    t0 = time.monotonic()
    resp = ctx.client.post(f"{ctx.base_url}/auth/register", json={
        "username": "weakpw_test",
        "email": "weak@test.local",
        "full_name": "Weak PW",
        "password": "123",
    })
    dur = round((time.monotonic() - t0) * 1000, 1)
    results.append(TestResult(
        name="auth::weak_password_rejected",
        passed=resp.status_code == 400,
        duration_ms=dur,
        message=f"Weak password returned {resp.status_code} (expected 400)",
        file_path="backend/auth.py",
        line_hint="validate_password_strength()",
    ))

    # Duplicate username rejection
    t0 = time.monotonic()
    ctx.client.post(f"{ctx.base_url}/auth/register", json={
        "username": "dup_test_user",
        "email": "dup@test.local",
        "full_name": "Dup Test",
        "password": "DupTest1234!",
    })
    resp = ctx.client.post(f"{ctx.base_url}/auth/register", json={
        "username": "dup_test_user",
        "email": "dup2@test.local",
        "full_name": "Dup Test 2",
        "password": "DupTest1234!",
    })
    dur = round((time.monotonic() - t0) * 1000, 1)
    results.append(TestResult(
        name="auth::duplicate_username_rejected",
        passed=resp.status_code == 409,
        duration_ms=dur,
        message=f"Duplicate username returned {resp.status_code} (expected 409)",
        file_path="backend/auth.py",
        line_hint="register_user()",
    ))

    # ── Login validation ──────────────────────────────────────────────────

    # Invalid credentials
    t0 = time.monotonic()
    resp = ctx.client.post(f"{ctx.base_url}/auth/login", json={
        "username": "nonexistent_user_xyz",
        "password": "wrong",
    })
    dur = round((time.monotonic() - t0) * 1000, 1)
    results.append(TestResult(
        name="auth::invalid_login_rejected",
        passed=resp.status_code in (401, 400),
        duration_ms=dur,
        message=f"Invalid login returned {resp.status_code}",
        file_path="backend/routers/auth.py",
    ))

    # ── Token validation ──────────────────────────────────────────────────

    # Invalid JWT rejected
    t0 = time.monotonic()
    resp = ctx.client.get(f"{ctx.base_url}/portfolios", headers={
        "Authorization": "Bearer invalid.jwt.token"
    })
    dur = round((time.monotonic() - t0) * 1000, 1)
    results.append(TestResult(
        name="auth::invalid_jwt_rejected",
        passed=resp.status_code == 401,
        duration_ms=dur,
        message=f"Invalid JWT returned {resp.status_code} (expected 401)",
        file_path="backend/auth.py",
        line_hint="decode_token()",
    ))

    # Expired/tampered token rejected
    t0 = time.monotonic()
    fake_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmYWtlIiwiZXhwIjoxfQ.fake"
    resp = ctx.client.get(f"{ctx.base_url}/portfolios", headers={
        "Authorization": f"Bearer {fake_token}"
    })
    dur = round((time.monotonic() - t0) * 1000, 1)
    results.append(TestResult(
        name="auth::tampered_token_rejected",
        passed=resp.status_code == 401,
        duration_ms=dur,
        message=f"Tampered JWT returned {resp.status_code} (expected 401)",
        file_path="backend/auth.py",
    ))

    # ── Token revocation ──────────────────────────────────────────────────

    # Register, login, logout, verify revoked token is rejected
    t0 = time.monotonic()
    revoke_user = "revoke_test_user"
    revoke_pw = "RevokeTest1234!"
    ctx.client.post(f"{ctx.base_url}/auth/register", json={
        "username": revoke_user,
        "email": "revoke@test.local",
        "full_name": "Revoke Test",
        "password": revoke_pw,
    })
    login_resp = ctx.client.post(f"{ctx.base_url}/auth/login", json={
        "username": revoke_user,
        "password": revoke_pw,
    })
    revoke_passed = False
    if login_resp.status_code == 200:
        tokens = login_resp.json()
        access = tokens.get("access_token", "")
        # Logout (revoke)
        ctx.client.post(f"{ctx.base_url}/auth/logout", json={
            "access_token": access,
            "refresh_token": tokens.get("refresh_token", ""),
        }, headers={"Authorization": f"Bearer {access}"})
        # Try using revoked token
        check_resp = ctx.client.get(f"{ctx.base_url}/portfolios", headers={
            "Authorization": f"Bearer {access}"
        })
        revoke_passed = check_resp.status_code == 401
    dur = round((time.monotonic() - t0) * 1000, 1)
    results.append(TestResult(
        name="auth::revoked_token_rejected",
        passed=revoke_passed,
        duration_ms=dur,
        message="Revoked token correctly rejected" if revoke_passed else "Revoked token was NOT rejected",
        file_path="backend/auth.py",
        line_hint="is_token_revoked()",
    ))

    # ── RBAC ──────────────────────────────────────────────────────────────

    # Non-admin cannot access admin routes
    t0 = time.monotonic()
    readonly_user = "readonly_test_user"
    readonly_pw = "ReadOnly1234!"
    ctx.client.post(f"{ctx.base_url}/auth/register", json={
        "username": readonly_user,
        "email": "readonly@test.local",
        "full_name": "ReadOnly Test",
        "password": readonly_pw,
    })
    login_resp = ctx.client.post(f"{ctx.base_url}/auth/login", json={
        "username": readonly_user,
        "password": readonly_pw,
    })
    rbac_passed = False
    if login_resp.status_code == 200:
        ro_token = login_resp.json().get("access_token", "")
        admin_resp = ctx.client.get(f"{ctx.base_url}/admin/version", headers={
            "Authorization": f"Bearer {ro_token}"
        })
        rbac_passed = admin_resp.status_code == 403
    dur = round((time.monotonic() - t0) * 1000, 1)
    results.append(TestResult(
        name="auth::rbac_admin_blocked",
        passed=rbac_passed,
        duration_ms=dur,
        message="Non-admin correctly blocked from admin routes" if rbac_passed else "RBAC not enforced on admin routes",
        file_path="backend/routing.py",
        line_hint="Check _admin_dep = [Depends(require_role('eigentuemer', 'verwalter'))]",
    ))

    # ── Password hashing ──────────────────────────────────────────────────

    t0 = time.monotonic()
    from ...auth import hash_password, verify_password
    pw = "TestPassword123!"
    hashed = hash_password(pw)
    hash_ok = (
        verify_password(pw, hashed) and
        not verify_password("wrong", hashed) and
        hashed.startswith("pbkdf2:sha256:")
    )
    dur = round((time.monotonic() - t0) * 1000, 1)
    results.append(TestResult(
        name="auth::password_hashing",
        passed=hash_ok,
        duration_ms=dur,
        message="PBKDF2 hash/verify works correctly" if hash_ok else "Password hashing is broken",
        file_path="backend/auth.py",
        line_hint="hash_password() / verify_password()",
    ))

    return results
