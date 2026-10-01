"""Private deployment configuration and actual Host middleware regression tests."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.configure_private_server import configure, validated_origin


def test_server_configuration_creates_independent_keys_without_replacing_existing_installation(tmp_path):
    target = tmp_path / "server.env"
    configure(target, "https://immo.private.example/", 8181)
    first = target.read_bytes()
    values = dict(line.split("=", 1) for line in first.decode().splitlines())
    assert values["APP_ORIGIN"] == "https://immo.private.example"
    assert values["APP_HOST"] == "immo.private.example"
    assert values["APP_HTTP_PORT"] == "8181"
    assert re.fullmatch(r"[a-f0-9]{64}", values["POSTGRES_PASSWORD"])
    assert re.fullmatch(r"[a-f0-9]{96}", values["JWT_SECRET_KEY"])
    assert values["POSTGRES_PASSWORD"] != values["JWT_SECRET_KEY"]
    with pytest.raises(FileExistsError):
        configure(target, "https://another.private.example")
    assert target.read_bytes() == first
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("origin", ["http://immo.local", "https://u:p@immo.local", "https://*.local", "https://immo.local/path", "https://immo.local?secret=a", "https://immo.local#fragment", "https://immo.local\n", "https://immo.local:70000"])
def test_unsafe_origin_is_rejected_before_creating_configuration(tmp_path, origin):
    target = tmp_path / "server.env"
    with pytest.raises(ValueError):
        configure(target, origin)
    assert not target.exists()


def test_https_origin_preserves_a_custom_tls_port():
    assert validated_origin("https://immo.private.example:8443") == ("https://immo.private.example:8443", "immo.private.example")


def test_configuration_cli_never_prints_generated_keys(tmp_path):
    path = tmp_path / "server.env"
    script = Path(__file__).resolve().parents[2] / "scripts/configure_private_server.py"
    result = subprocess.run([sys.executable, str(script), "--origin", "https://immo.private.example", "--output", str(path)], capture_output=True, text=True, check=True)
    values = dict(line.split("=", 1) for line in path.read_text().splitlines())
    for key in ["POSTGRES_PASSWORD", "JWT_SECRET_KEY"]:
        assert values[key] not in result.stdout + result.stderr


def test_actual_application_restricts_hosts_without_trusting_forwarded_host(tmp_path):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{(tmp_path / 'profile.db').as_posix()}", "SQLITE_PERSISTENT_STORE": "true", "ALLOW_INMEMORY_FALLBACK": "false", "DATA_DIR": str(tmp_path), "UPLOADS_DIR": str(tmp_path / "uploads"), "LOG_FILE": str(tmp_path / "application.log"), "TRUSTED_HOSTS": "immo.private.example,127.0.0.1", "ENVIRONMENT": "development"}
    source = '''
from fastapi.testclient import TestClient
from backend.app import app
client = TestClient(app)
assert client.get('/api/v1/auth/setup-status', headers={'host':'immo.private.example'}).status_code == 200
assert client.get('/api/v1/auth/setup-status', headers={'host':'127.0.0.1:8080'}).status_code == 200
assert client.get('/api/v1/auth/setup-status', headers={'host':'attacker.invalid', 'x-forwarded-host':'immo.private.example'}).status_code == 400
'''
    result = subprocess.run([sys.executable, "-c", source], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
