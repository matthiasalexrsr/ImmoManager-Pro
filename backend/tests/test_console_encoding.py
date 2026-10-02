"""Actual redirected legacy-codepage streams, without altering the user's console."""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.__main__ import _TeeWriter
from backend.console_encoding import prepare_standard_streams, safe_console_stream

MESSAGE = "GET /api/v1/notifications → 200 · Miete € · 房 🏠"


@pytest.mark.parametrize("format_name", ["json", "text"])
def test_direct_asgi_startup_and_logging_with_actual_cp1252_redirect(tmp_path, format_name):
    file_log = tmp_path / "unicode-original.jsonl"
    env = os.environ.copy()
    env.update({
        "PYTHONIOENCODING": "cp1252:strict", "LOG_FORMAT": format_name,
        "LOG_FILE": str(file_log), "ENVIRONMENT": "development", "LOG_LEVEL": "INFO",
        "DATA_DIR": str(tmp_path), "UPLOADS_DIR": str(tmp_path / "uploads"),
        "BACKUP_DIR": str(tmp_path / "backups"),
        "DATABASE_URL": "sqlite:///" + (tmp_path / "isolated.db").as_posix(),
        "ALLOW_INMEMORY_FALLBACK": "false", "SQLITE_PERSISTENT_STORE": "true",
        "AUTH_ENABLED": "true", "TASK_QUEUE_BACKEND": "sync",
    })
    script = """
import logging,sys
assert sys.stdout.encoding.lower() == 'cp1252' and sys.stdout.errors == 'strict'
import backend.app
assert sys.stdout.encoding.lower() == 'cp1252' and sys.stdout.errors == 'backslashreplace'
assert logging.raiseExceptions is True
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.middleware import RequestLoggingMiddleware
probe = FastAPI()
probe.add_middleware(RequestLoggingMiddleware)
@probe.get('/api/console-probe')
def response(): return {'ok':True}
with TestClient(probe) as client:
    for _ in range(2):
        response = client.get('/api/console-probe')
        assert response.status_code == 200 and response.headers['X-Request-ID']
logging.getLogger('console-gate').info(sys.argv[1])
sys.stderr.write(sys.argv[1]+'\\n')
for handler in logging.getLogger().handlers:
    handler.flush()
"""
    result = subprocess.run([sys.executable, "-c", script, MESSAGE], env=env,
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, timeout=35)
    assert result.returncode == 0, result.stderr.decode("cp1252", errors="backslashreplace")
    output = result.stdout.decode("cp1252")
    errors = result.stderr.decode("cp1252")
    assert "\\u2192" in output and "\\u623f" in output
    assert ("\\ud83c\\udfe0" if format_name == "json" else "\\U0001f3e0") in output
    assert "UnicodeEncodeError" not in errors and "--- Logging error ---" not in errors
    # A strict cp1252 console escapes just the unrepresentable characters. The
    # independently formatted UTF-8 JSON file keeps every original Unicode fact.
    raw = file_log.read_bytes()
    assert "→".encode() in raw and "房 🏠".encode() in raw
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    assert next(record["message"] for record in records if record["logger"] == "console-gate") == MESSAGE
    requests = [record for record in records if record.get("path") == "/api/console-probe"]
    assert len(requests) == 2 and all(record["status_code"] == 200 and "→" in record["message"] for record in requests)
    if format_name == "json":
        console_records = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
        # backslashreplace's supplementary-character escape is Python's \U,
        # whereas JSON requires \u escapes. The formatter must remain valid.
        assert next(record["message"] for record in console_records if record["logger"] == "console-gate") == MESSAGE


def test_launcher_prepares_console_before_runtime_loading_and_config_import(tmp_path):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252:strict"
    script = """
import sys
from backend import __main__ as launcher
assert 'backend.config' not in sys.modules
def runtime(_):
    assert 'backend.config' not in sys.modules
    assert sys.stdout.errors == sys.stderr.errors == 'backslashreplace'
    print(fixture)
    return fixture
launcher._configure_runtime_environment = runtime
launcher._port_available = lambda *args: False
fixture = sys.argv[1]
sys.argv = ['immomanager','--no-browser']
try:
    launcher.main()
except SystemExit as error:
    assert error.code == 1
else:
    raise AssertionError('occupied port must still fail')
assert 'backend.config' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", script, MESSAGE], env=env,
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode("cp1252", errors="backslashreplace")
    assert "\\u2192" in result.stdout.decode("cp1252")
    assert not result.stderr


def test_frozen_startup_tee_preserves_original_utf8_bytes(tmp_path):
    buffer = io.BytesIO()
    original = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict")
    log_path = tmp_path / "startup.log"
    with log_path.open("w", encoding="utf-8") as log:
        tee = _TeeWriter(original, log)
        assert tee.write(MESSAGE) == len(MESSAGE)
        tee.flush()
        assert original.encoding == "cp1252" and original.errors == "backslashreplace"
        assert "\\u2192" in buffer.getvalue().decode("cp1252")
    assert log_path.read_bytes() == MESSAGE.encode("utf-8")


def test_custom_console_fallback_preserves_data_and_real_io_failures(tmp_path):
    class LegacyStream:
        encoding = "cp1252"

        def __init__(self):
            self.bytes = b""

        def write(self, text):
            self.bytes += text.encode(self.encoding, errors="strict")
            return len(text)

    legacy = LegacyStream()
    safe_console_stream(legacy).write(MESSAGE)
    assert "\\u2192" in legacy.bytes.decode("cp1252")

    class BrokenStream:
        def write(self, _):
            raise BrokenPipeError("synthetic disconnected output")

    with (tmp_path / "durable-tee.log").open("w", encoding="utf-8") as file:
        with pytest.raises(BrokenPipeError):
            _TeeWriter(BrokenStream(), file).write(MESSAGE)
    assert (tmp_path / "durable-tee.log").read_text(encoding="utf-8") == MESSAGE


def test_existing_utf8_stdout_and_stderr_remain_unicode(monkeypatch):
    output, errors = io.BytesIO(), io.BytesIO()
    stdout = io.TextIOWrapper(output, encoding="utf-8", errors="strict")
    stderr = io.TextIOWrapper(errors, encoding="utf-8", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    prepare_standard_streams()
    sys.stdout.write(MESSAGE)
    sys.stderr.write(MESSAGE)
    sys.stdout.flush()
    sys.stderr.flush()
    assert output.getvalue() == errors.getvalue() == MESSAGE.encode("utf-8")
