"""Production guards: JWT secret strength and developer tools gating."""

import pytest
from fastapi import HTTPException

from backend import app as app_module
from backend.config import Environment, settings
from backend.routers import dev_notes


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(settings, "environment", Environment.production)
    monkeypatch.setattr(settings, "diagnostics_allow_in_production", False)
    return settings


def _startup_issues(monkeypatch, secret):
    """Run startup validation in development and collect warnings."""
    monkeypatch.setattr(settings, "jwt_secret_key", secret)
    warnings = []
    monkeypatch.setattr(app_module.logger, "warning", lambda fmt, msg: warnings.append(msg))
    app_module._validate_startup_config()
    return [w for w in warnings if "JWT_SECRET_KEY" in w]


def test_short_jwt_secret_is_reported(monkeypatch):
    issues = _startup_issues(monkeypatch, "short-secret")
    assert any("shorter than 32" in issue for issue in issues)


def test_long_random_jwt_secret_is_accepted(monkeypatch):
    assert _startup_issues(monkeypatch, "x" * 48) == []


def test_short_jwt_secret_is_critical_but_not_blocking_in_production(monkeypatch, production):
    # Blocking would force a key rotation, which makes encrypted IBANs unreadable.
    monkeypatch.setattr(settings, "jwt_secret_key", "short-secret")
    criticals = []
    monkeypatch.setattr(app_module.logger, "critical", lambda fmt, msg: criticals.append(msg))
    try:
        app_module._validate_startup_config()
    except RuntimeError as exc:  # other production issues (e.g. in-memory store) may still block
        assert "JWT_SECRET_KEY" not in str(exc)
    assert any("shorter than 32" in c for c in criticals)


def test_default_jwt_secret_blocks_production_startup(monkeypatch, production):
    monkeypatch.setattr(settings, "jwt_secret_key", "dev-secret-key-change-in-production")
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY is using the default"):
        app_module._validate_startup_config()


def test_developer_tools_flag(monkeypatch, production):
    assert settings.developer_tools_enabled is False
    monkeypatch.setattr(settings, "diagnostics_allow_in_production", True)
    assert settings.developer_tools_enabled is True
    monkeypatch.setattr(settings, "environment", Environment.development)
    monkeypatch.setattr(settings, "diagnostics_allow_in_production", False)
    assert settings.developer_tools_enabled is True


def test_dev_notes_blocked_in_production(production):
    with pytest.raises(HTTPException) as exc:
        dev_notes._check_dev_notes_allowed()
    assert exc.value.status_code == 403


def test_dev_notes_log_written_to_runtime_logs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_notes, "get_logs_dir", lambda: tmp_path / "logs")
    dev_notes._write_log_file()
    assert (tmp_path / "logs" / "dev_notes.log").exists()


def test_health_exposes_developer_tools_flag():
    assert "developer_tools_enabled" in app_module.health()
