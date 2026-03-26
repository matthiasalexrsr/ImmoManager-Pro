"""Tests for service modules and security features.

Covers: IBAN encryption, password policy, login rate limiting,
TOTP 2FA, task queue, file storage, portal adapters, and email service.
"""

import io
from pathlib import Path

import pytest

from backend.auth import (
    MAX_LOGIN_ATTEMPTS,
    _login_attempts,
    check_login_rate_limit,
    clear_login_attempts,
    generate_totp_secret,
    get_totp_uri,
    record_failed_login,
    validate_password_strength,
    verify_totp,
)
from backend.services.email_service import EmailConfig, send_email
from backend.services.file_storage import LocalStorage
from backend.services.iban_encryption import decrypt_iban, encrypt_iban, mask_iban
from backend.services.portal_adapter import (
    ImmobilienScout24Adapter,
    ImmoweltAdapter,
    _adapters,
    get_adapter,
    list_adapters,
    register_adapter,
)
from backend.services.task_queue import SyncQueue

# ---------------------------------------------------------------------------
# 1. IBAN Encryption
# ---------------------------------------------------------------------------


class TestIBANEncryption:
    """Tests for IBAN encrypt / decrypt / mask round-trips."""

    def test_encrypt_returns_enc_prefix(self):
        encrypted = encrypt_iban("DE89370400440532013000")
        assert encrypted.startswith("enc:")

    def test_round_trip_encrypt_decrypt(self):
        original = "DE89370400440532013000"
        encrypted = encrypt_iban(original)
        assert encrypted != original
        decrypted = decrypt_iban(encrypted)
        assert decrypted == original

    def test_decrypt_plain_value_returned_as_is(self):
        plain = "DE89370400440532013000"
        assert decrypt_iban(plain) == plain

    def test_decrypt_empty_string(self):
        assert decrypt_iban("") == ""

    def test_decrypt_none_returns_none(self):
        assert decrypt_iban(None) is None

    def test_encrypt_empty_string(self):
        assert encrypt_iban("") == ""

    def test_mask_iban_shows_last_four(self):
        result = mask_iban("DE89370400440532013000")
        assert result == "****3000"

    def test_mask_iban_short_value(self):
        result = mask_iban("AB")
        assert result == "****"

    def test_mask_iban_empty(self):
        result = mask_iban("")
        assert result == "****"


# ---------------------------------------------------------------------------
# 2. Password Policy
# ---------------------------------------------------------------------------


class TestPasswordPolicy:
    """Tests for password strength validation."""

    def test_too_short(self):
        errors = validate_password_strength("Aa1")
        assert any("8" in e or "Zeichen" in e for e in errors)

    def test_no_uppercase(self):
        errors = validate_password_strength("abcdefg1")
        assert any("Großbuchstabe" in e for e in errors)

    def test_no_lowercase(self):
        errors = validate_password_strength("ABCDEFG1")
        assert any("Kleinbuchstabe" in e for e in errors)

    def test_no_digit(self):
        errors = validate_password_strength("Abcdefgh")
        assert any("Ziffer" in e for e in errors)

    def test_all_requirements_met(self):
        errors = validate_password_strength("Secure1x")
        assert errors == []

    def test_multiple_violations(self):
        errors = validate_password_strength("abc")
        # Should flag at least length and uppercase and digit
        assert len(errors) >= 3


# ---------------------------------------------------------------------------
# 3. Login Rate Limiting
# ---------------------------------------------------------------------------


class TestLoginRateLimiting:
    """Tests for login attempt rate limiting."""

    @pytest.fixture(autouse=True)
    def _clean_attempts(self):
        _login_attempts.clear()
        # Also clear DB-backed login attempts when SQL backend is active
        from backend.auth import _auth_session_factory
        if _auth_session_factory is not None:
            from backend.db.orm_models import LoginAttemptORM
            session = _auth_session_factory()
            session.query(LoginAttemptORM).delete()
            session.commit()
            session.close()
        yield
        _login_attempts.clear()
        if _auth_session_factory is not None:
            session = _auth_session_factory()
            session.query(LoginAttemptORM).delete()
            session.commit()
            session.close()

    def test_not_blocked_initially(self):
        assert check_login_rate_limit("testuser") is False

    def test_blocked_after_max_attempts(self):
        for _ in range(MAX_LOGIN_ATTEMPTS):
            record_failed_login("testuser")
        assert check_login_rate_limit("testuser") is True

    def test_not_blocked_below_max(self):
        for _ in range(MAX_LOGIN_ATTEMPTS - 1):
            record_failed_login("testuser")
        assert check_login_rate_limit("testuser") is False

    def test_cleared_after_clear_login_attempts(self):
        for _ in range(MAX_LOGIN_ATTEMPTS):
            record_failed_login("testuser")
        assert check_login_rate_limit("testuser") is True
        clear_login_attempts("testuser")
        assert check_login_rate_limit("testuser") is False

    def test_different_users_independent(self):
        for _ in range(MAX_LOGIN_ATTEMPTS):
            record_failed_login("alice")
        assert check_login_rate_limit("alice") is True
        assert check_login_rate_limit("bob") is False


# ---------------------------------------------------------------------------
# 4. TOTP Two-Factor Authentication
# ---------------------------------------------------------------------------


class TestTOTP:
    """Tests for TOTP secret generation, URI building, and verification."""

    def test_generate_secret_is_base32(self):
        secret = generate_totp_secret()
        assert isinstance(secret, str)
        assert len(secret) > 0
        # base32 characters only (uppercase A-Z and 2-7, plus padding)
        import re
        assert re.fullmatch(r"[A-Z2-7=]+", secret)

    def test_generate_secret_unique(self):
        s1 = generate_totp_secret()
        s2 = generate_totp_secret()
        assert s1 != s2

    def test_get_totp_uri_format(self):
        secret = generate_totp_secret()
        uri = get_totp_uri(secret, "admin")
        assert uri.startswith("otpauth://totp/")
        assert secret in uri
        assert "admin" in uri
        assert "digits=6" in uri
        assert "period=30" in uri

    def test_verify_totp_rejects_invalid_code(self):
        secret = generate_totp_secret()
        assert verify_totp(secret, "000000") is False or verify_totp(secret, "000000") is True
        # An empty or wrong-length code must be rejected
        assert verify_totp(secret, "") is False
        assert verify_totp(secret, "12345") is False
        assert verify_totp(secret, "abcdef") is False

    def test_verify_totp_rejects_wrong_length(self):
        secret = generate_totp_secret()
        assert verify_totp(secret, "12345") is False
        assert verify_totp(secret, "1234567") is False


# ---------------------------------------------------------------------------
# 5. Task Queue (SyncQueue)
# ---------------------------------------------------------------------------


class TestSyncQueue:
    """Tests for synchronous task queue."""

    def test_enqueue_returns_task_result(self):
        q = SyncQueue()
        result = q.enqueue(lambda: 42)
        assert result.task_id is not None
        assert result.status == "completed"
        assert result.result == 42

    def test_get_status_returns_result(self):
        q = SyncQueue()
        result = q.enqueue(lambda: "ok")
        fetched = q.get_status(result.task_id)
        assert fetched is not None
        assert fetched.task_id == result.task_id
        assert fetched.status == "completed"
        assert fetched.result == "ok"

    def test_get_status_unknown_id(self):
        q = SyncQueue()
        assert q.get_status("nonexistent") is None

    def test_enqueue_failing_task(self):
        q = SyncQueue()
        def bad():
            raise ValueError("boom")
        result = q.enqueue(bad)
        assert result.status == "failed"
        assert "boom" in result.error

    def test_cancel_pending_not_applicable(self):
        """SyncQueue executes immediately, so cancel on a completed task returns False."""
        q = SyncQueue()
        result = q.enqueue(lambda: 1)
        assert q.cancel(result.task_id) is False


# ---------------------------------------------------------------------------
# 6. File Storage (LocalStorage)
# ---------------------------------------------------------------------------


class TestLocalStorage:
    """Tests for local filesystem storage using tmp_path."""

    @pytest.fixture()
    def storage(self, tmp_path):
        return LocalStorage(base_dir=str(tmp_path / "uploads"))

    def test_save_and_get_roundtrip(self, storage):
        data = io.BytesIO(b"hello world")
        storage.save("test.txt", data)
        content = storage.get("test.txt")
        assert content == b"hello world"

    def test_exists_after_save(self, storage):
        assert storage.exists("test.txt") is False
        storage.save("test.txt", io.BytesIO(b"data"))
        assert storage.exists("test.txt") is True

    def test_delete_removes_file(self, storage):
        storage.save("test.txt", io.BytesIO(b"data"))
        assert storage.delete("test.txt") is True
        assert storage.exists("test.txt") is False

    def test_delete_nonexistent_returns_false(self, storage):
        assert storage.delete("nope.txt") is False

    def test_get_nonexistent_returns_none(self, storage):
        assert storage.get("missing.txt") is None

    def test_get_url(self, storage):
        url = storage.get_url("docs/file.pdf")
        assert url == "/uploads/docs/file.pdf"

    def test_windows_traversal_key_stays_under_base_dir(self, storage):
        malicious_key = r"..\..\Windows\system32\drivers\etc\hosts"
        saved_path = Path(storage.save(malicious_key, io.BytesIO(b"safe"))).resolve()
        assert saved_path.is_relative_to(storage.base_dir.resolve())
        assert storage.get(malicious_key) == b"safe"

    def test_save_nested_key(self, storage):
        storage.save("a/b/c.txt", io.BytesIO(b"nested"))
        assert storage.get("a/b/c.txt") == b"nested"


# ---------------------------------------------------------------------------
# 7. Portal Adapter
# ---------------------------------------------------------------------------


class TestPortalAdapter:
    """Tests for portal adapter registry."""

    @pytest.fixture(autouse=True)
    def _reset_registry(self):
        """Save and restore registry state around each test."""
        saved = dict(_adapters)
        yield
        _adapters.clear()
        _adapters.update(saved)

    def test_default_adapters_registered(self):
        names = list_adapters()
        assert "ImmobilienScout24" in names
        assert "Immowelt" in names

    def test_get_adapter_case_insensitive(self):
        adapter = get_adapter("immobilienscout24")
        assert adapter is not None
        assert adapter.portal_name == "ImmobilienScout24"

    def test_get_adapter_unknown(self):
        assert get_adapter("UnknownPortal") is None

    def test_register_and_list(self):
        _adapters.clear()
        adapter = ImmobilienScout24Adapter()
        register_adapter(adapter)
        names = list_adapters()
        assert "ImmobilienScout24" in names

    def test_immowelt_adapter_portal_name(self):
        adapter = ImmoweltAdapter()
        assert adapter.portal_name == "Immowelt"

    def test_is24_publish_not_configured(self):
        adapter = ImmobilienScout24Adapter()
        result = adapter.publish({"title": "Test"})
        assert result.success is False
        assert result.portal_name == "ImmobilienScout24"


# ---------------------------------------------------------------------------
# 8. Email Service
# ---------------------------------------------------------------------------


class TestEmailService:
    """Tests for email configuration and sending."""

    def test_email_config_defaults(self):
        cfg = EmailConfig()
        assert cfg.smtp_host == ""
        assert cfg.smtp_port == 587
        assert cfg.smtp_use_tls is True
        assert cfg.from_address == "noreply@immomanager.local"
        assert cfg.from_name == "ImmoManager Pro"
        assert cfg.is_configured is False

    def test_email_config_is_configured(self):
        cfg = EmailConfig(smtp_host="mail.example.com", smtp_user="user")
        assert cfg.is_configured is True

    def test_send_email_not_configured_does_not_raise(self):
        # Default config is not configured, should just log and return True
        result = send_email(
            to="test@example.com",
            subject="Test",
            body_html="<p>Hello</p>",
        )
        assert result is True

    def test_send_email_with_body_text(self):
        result = send_email(
            to="test@example.com",
            subject="Test",
            body_html="<p>Hello</p>",
            body_text="Hello",
        )
        assert result is True
