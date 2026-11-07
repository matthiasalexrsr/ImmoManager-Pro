"""The desktop must own its server, stop it cleanly, and never trust a foreign port."""

import io
import json
import os
import queue
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from urllib.request import urlopen

import pytest

from backend import __main__ as cli
from backend.desktop import DesktopSession
from backend.desktop_control import (
    READY_PREFIX,
    DesktopControl,
    WindowsMutex,
    ensure_standard_streams,
    instance_key,
    ready_message,
)
from tools.windows_version import version_fields

ROOT = Path(__file__).resolve().parents[2]


def test_ready_message_requires_exact_parent_nonce_child_pid_and_url():
    token = "a" * 64
    expected = dict(token=token, pid=1234, url="http://127.0.0.1:18991")

    def matches(line):
        return ready_message(line, token=token, pid=1234, url="http://127.0.0.1:18991")

    assert matches(READY_PREFIX + json.dumps(expected))
    for changed in ({"pid": 9999}, {"token": "b" * 64}, {"url": "http://127.0.0.1:8000"}, {"extra": True}):
        assert not matches(READY_PREFIX + json.dumps({**expected, **changed}))
    for line in ("healthy", READY_PREFIX + "not JSON", READY_PREFIX + "[]", "x" * 5000):
        assert not matches(line)


@pytest.mark.parametrize("command", ["", "STOP " + "a" * 64 + "\n"])
def test_parent_eof_or_authenticated_stop_is_remembered_before_server_exists(command):
    output = io.StringIO()
    control = DesktopControl("a" * 64, io.StringIO(command), output)
    control._read()
    server = SimpleNamespace(should_exit=False, started=False)
    control.attach(server, "http://127.0.0.1:18991")
    assert control.stop_requested.is_set() and server.should_exit
    assert output.getvalue() == ""


def test_foreign_command_does_not_stop_server_until_parent_pipe_closes():
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd, "r", encoding="utf-8") as reader, os.fdopen(write_fd, "w", encoding="utf-8") as writer:
        control = DesktopControl("a" * 64, reader, io.StringIO())
        control.start()
        writer.write("STOP " + "b" * 64 + "\n")
        writer.flush()
        assert not control.stop_requested.wait(0.06)
        writer.close()
        assert control.stop_requested.wait(2)


def test_readiness_is_emitted_only_after_uvicorn_started():
    class ReadyOutput(io.StringIO):
        def write(self, value):
            result = super().write(value)
            written.set()
            return result

    written = threading.Event()
    output = ReadyOutput()
    control = DesktopControl("a" * 64, io.StringIO(), output)
    server = SimpleNamespace(should_exit=False, started=False)
    url = "http://127.0.0.1:18991"
    control.attach(server, url)
    assert not written.wait(0.06)
    server.started = True
    assert written.wait(2)
    assert ready_message(output.getvalue(), token=control.token, pid=os.getpid(), url=url)
    control.request_stop()
    assert server.should_exit


def test_windowed_streams_and_tee_accept_missing_console(monkeypatch):
    with monkeypatch.context() as patch:
        for name in ("stdin", "stdout", "stderr"):
            patch.setattr(sys, name, None)
        ensure_standard_streams()
        streams = [sys.stdin, sys.stdout, sys.stderr]
        assert all(stream is not None for stream in streams)
        sys.stdout.write("windowed diagnostic")
        sys.stderr.flush()
    for stream in streams:
        stream.close()
    output = io.StringIO()
    writer = cli._TeeWriter(None, output)
    writer.write("Überblick →\n")
    writer.flush()
    assert output.getvalue() == "Überblick →\n"


def test_startup_log_is_user_writable_append_and_bounded(tmp_path, monkeypatch):
    bundle, data = tmp_path / "bundle", tmp_path / "Daten mit Ä"
    bundle.mkdir()
    monkeypatch.setattr(cli, "IS_FROZEN", True)
    monkeypatch.setattr(cli, "_exe_dir", lambda: str(bundle))
    monkeypatch.setattr(sys, "argv", ["ImmoManager-Pro-CLI.exe", "--data-dir", str(data)])
    for text in ("Erster Start\n", "Zweiter Start\n"):
        stream = cli._setup_logging_to_file()
        stream.write(text)
        stream.close()
    path = data / "logs" / f"immo_startup-{os.getpid()}.log"
    assert path.read_text(encoding="utf-8") == "Erster Start\nZweiter Start\n"
    assert not (bundle / "immo_startup.log").exists()
    stream = cli._StartupLog(path)
    stream.handler.maxBytes = 80
    for _ in range(12):
        stream.write("Diagnose mit Umlaut Ä\n")
    stream.close()
    assert 1 < len(list(path.parent.glob(path.name + "*"))) <= 4


def test_managed_child_has_only_parent_owned_rotating_startup_log(monkeypatch):
    monkeypatch.setattr(cli, "IS_FROZEN", True)
    monkeypatch.setattr(sys, "argv", ["cli.exe", "--desktop-token", "a" * 64])
    assert cli._setup_logging_to_file() is None


def test_desktop_log_never_contains_private_control_messages(tmp_path):
    session = DesktopSession(SimpleNamespace(host="127.0.0.1", port=18991), tmp_path)
    payload = {"token": session.token, "pid": 1234, "url": session.url}
    output = READY_PREFIX + json.dumps(payload) + "\n" + READY_PREFIX + "malformed-private-message\n" + "Normale Diagnose Ä\n"
    session.process = cast(subprocess.Popen[str], SimpleNamespace(stdout=io.StringIO(output), pid=1234))
    session._read_output()
    session.handler.flush()
    session.handler.close()
    log = session.log_path.read_text(encoding="utf-8")
    assert session.token not in log and READY_PREFIX not in log and "malformed-private-message" not in log
    assert "Anwendung bereit." in log and "Normale Diagnose Ä" in log
    assert session.events.get_nowait() == "ready"


@pytest.mark.parametrize("filename", ["ImmoManager-Pro.exe", "ImmoManager-Pro-CLI.exe"])
def test_version_resource_uses_project_beta_and_executable_name(tmp_path, filename):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "2.1.3-beta.4"\n', encoding="utf-8")
    fields = version_fields(tmp_path, filename, "ImmoManager Pro")
    assert fields["number"] == (2, 1, 3, 0) and fields["prerelease"]
    assert fields["strings"]["ProductVersion"] == "2.1.3-beta.4"
    assert fields["strings"]["FileVersion"] == "2.1.3.0"
    assert fields["strings"]["OriginalFilename"] == filename


@pytest.mark.skipif(os.name != "nt", reason="Native Windows instance mutex")
def test_instance_mutex_blocks_only_the_same_data_directory(tmp_path):
    name = r"Local\ImmoManagerPro.Test." + instance_key(tmp_path)
    first = WindowsMutex(name)
    second = WindowsMutex(name)
    other = WindowsMutex(r"Local\ImmoManagerPro.Test." + instance_key(tmp_path / "other"))
    try:
        assert not first.existed and second.existed and not other.existed
    finally:
        first.close()
        second.close()
        other.close()


def _environment(data: Path, port: int):
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
    environment.update(PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONUNBUFFERED="1", DATA_DIR=str(data),
        DATABASE_URL="sqlite:///" + (data / "app.db").as_posix(), JWT_SECRET_KEY="synthetic-desktop-regression-key-only-48-characters",
        ENVIRONMENT="development", JOB_SCHEDULER_ENABLED="false", BACKUP_SCHEDULE_ENABLED="false",
        CORS_ORIGINS=f"http://127.0.0.1:{port}", LOG_FILE=str(data / "logs/app.log"))
    return environment


@pytest.mark.parametrize("shutdown", ["stop", "parent_eof"])
def test_real_cli_private_ready_and_graceful_shutdown(tmp_path, shutdown):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    token = secrets.token_hex(32)
    lines: queue.Queue[str] = queue.Queue()
    data = tmp_path / "Eigene Daten Ä"
    process = subprocess.Popen([sys.executable, "-m", "backend", "--no-browser", "--no-upgrade", "--port", str(port),
        "--data-dir", str(data), "--desktop-token", token], cwd=tmp_path, env=_environment(data, port),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert process.stdout is not None and process.stdin is not None
    stdout, stdin = process.stdout, process.stdin
    collected: list[str] = []

    def read():
        for line in stdout:
            collected.append(line)
            lines.put(line)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            assert process.poll() is None, "".join(collected)[-4000:]
            try:
                line = lines.get(timeout=0.25)
            except queue.Empty:
                continue
            if ready_message(line, token=token, pid=process.pid, url=f"http://127.0.0.1:{port}", allow_child_pid=True):
                break
        else:
            raise AssertionError("Owned server did not announce readiness: " + "".join(collected)[-4000:])
        with urlopen(f"http://127.0.0.1:{port}/api/v1/auth/registration-status", timeout=5) as response:
            assert response.status == 200
        if shutdown == "stop":
            stdin.write("STOP " + token + "\n")
            stdin.flush()
        stdin.close()
        assert process.wait(timeout=20) == 0
        assert (data / "app.db").is_file()
    finally:
        if process.poll() is None:
            stdin.close()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()  # Only this fixture's own process, after a failed graceful stop.
                process.wait(timeout=5)
        reader.join(timeout=3)
        stdout.close()


def test_foreign_listener_never_causes_desktop_ready(tmp_path):
    token = secrets.token_hex(32)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        data = tmp_path / "unstarted"
        result = subprocess.run([sys.executable, "-m", "backend", "--no-browser", "--no-upgrade", "--port", str(port),
            "--data-dir", str(data), "--desktop-token", token], cwd=tmp_path, env=_environment(data, port),
            input="", capture_output=True, text=True, encoding="utf-8", timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 1
    assert "bereits belegt" in result.stdout
    assert READY_PREFIX not in result.stdout
