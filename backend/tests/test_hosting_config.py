"""The container refuses an unsafe hosting configuration before it migrates or starts."""

from pathlib import Path

import pytest

from tools import validate_hosting_config as hosting

ROOT = Path(__file__).resolve().parents[2]

SECRET = "s3cr3t-" + "x" * 40
VALID = {
    "ENVIRONMENT": "production",
    "JWT_SECRET_KEY": SECRET,
    "BACKUP_PASSPHRASE": "p" * 40,
    "CORS_ORIGINS": "https://verwaltung.example.de",
    "FORWARDED_ALLOW_IPS": "172.18.0.1",
    "DATABASE_URL": "postgresql://immo:" + SECRET + "@db:5432/immomanager",
    "ALLOW_INMEMORY_FALLBACK": "false",
    "AUTO_SEED_DEMO_DATA": "false",
    "SECURITY_HEADERS_ENABLED": "true",
}


def test_complete_production_profile_passes():
    assert hosting.validate(VALID) == []


def test_development_is_explicit_and_unchecked():
    assert hosting.validate({"ENVIRONMENT": "development"}) == []
    assert hosting.validate({}) == ["ENVIRONMENT must explicitly be production or development."]
    assert hosting.validate({"ENVIRONMENT": "staging"}) == ["ENVIRONMENT must explicitly be production or development."]


@pytest.mark.parametrize(("key", "value", "names"), [
    ("JWT_SECRET_KEY", "short", "JWT_SECRET_KEY"),
    ("BACKUP_PASSPHRASE", "", "BACKUP_PASSPHRASE"),
    ("CORS_ORIGINS", "", "CORS_ORIGINS"),
    ("CORS_ORIGINS", "http://verwaltung.example.de", "CORS_ORIGINS"),
    ("CORS_ORIGINS", "*", "CORS_ORIGINS"),
    ("CORS_ORIGINS", "https://verwaltung.example.de/app", "CORS_ORIGINS"),
    ("CORS_ORIGINS", '["https://a.example.de", "http://b.example.de"]', "CORS_ORIGINS"),
    ("FORWARDED_ALLOW_IPS", "", "FORWARDED_ALLOW_IPS"),
    ("FORWARDED_ALLOW_IPS", "*", "FORWARDED_ALLOW_IPS"),
    ("FORWARDED_ALLOW_IPS", "0.0.0.0/0", "FORWARDED_ALLOW_IPS"),
    ("FORWARDED_ALLOW_IPS", "proxy.local", "FORWARDED_ALLOW_IPS"),
    ("AUTO_SEED_DEMO_DATA", "true", "AUTO_SEED_DEMO_DATA"),
    ("ALLOW_SELF_REGISTRATION", "1", "ALLOW_SELF_REGISTRATION"),
    ("PORTAL_LOCAL_TEST_MODE", "yes", "PORTAL_LOCAL_TEST_MODE"),
    ("SECURITY_HEADERS_ENABLED", "false", "SECURITY_HEADERS_ENABLED"),
    ("DATABASE_URL", "sqlite:///./immo_manager.db", "DATABASE_URL"),
    ("DATABASE_URL", "postgresql://immo@db:5432/immomanager", "DATABASE_URL"),
])
def test_each_unsafe_setting_is_named(key, value, names):
    errors = hosting.validate({**VALID, key: value})
    assert len(errors) == 1 and names in errors[0]


def test_enabled_portal_needs_an_https_address():
    assert hosting.validate({**VALID, "PORTAL_ENABLED": "true", "PORTAL_PUBLIC_URL": "https://portal.example.de"}) == []
    errors = hosting.validate({**VALID, "PORTAL_ENABLED": "true", "PORTAL_PUBLIC_URL": "http://portal.example.de"})
    assert len(errors) == 1 and "PORTAL_PUBLIC_URL" in errors[0]


def test_messages_never_repeat_supplied_values(capsys):
    broken = {**VALID, "JWT_SECRET_KEY": "tiny-secret", "CORS_ORIGINS": "http://leak.example.de",
              "DATABASE_URL": "sqlite:///" + SECRET}
    errors = hosting.validate(broken)
    assert len(errors) == 3
    assert not any(value in error for error in errors for value in ("tiny-secret", "leak.example.de", SECRET))
    assert hosting.main(broken) == 1
    output = capsys.readouterr()
    assert output.out == "" and SECRET not in output.err and "tiny-secret" not in output.err


def test_main_confirms_the_checked_profile(capsys):
    assert hosting.main(VALID) == 0
    assert "Deployment configuration checked (production)." in capsys.readouterr().out


def test_container_files_keep_the_boundary():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    monitoring = (ROOT / "docker-compose.monitoring.yml").read_text(encoding="utf-8")
    development = (ROOT / "docker-compose.development.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "- ENVIRONMENT=production" in compose and "- ENVIRONMENT=development" in development
    assert '"127.0.0.1:${APP_PORT:-8000}:8000"' in compose and "5432:5432" not in compose
    assert '"127.0.0.1:${PROMETHEUS_PORT:-9090}:9090"' in monitoring and '"9090:9090"' not in monitoring
    assert '"127.0.0.1:${GRAFANA_PORT:-3001}:3000"' in monitoring and '"3001:3000"' not in monitoring
    assert "9115:9115" not in monitoring and "GRAFANA_ADMIN_PASSWORD:?" in monitoring
    assert '"--proxy-headers"' in dockerfile and "validate_hosting_config.py" in dockerfile
    assert entrypoint.index("validate_hosting_config.py") < entrypoint.index("backend.upgrade")
