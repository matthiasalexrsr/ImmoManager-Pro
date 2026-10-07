"""Regression tests for fixture ownership, process cleanup and failure evidence."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.xstress import core, run, saveload


def test_fixture_environment_overrides_inherited_state(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    for name in ("DATA_DIR", "UPLOADS_DIR", "BACKUP_DIR", "INTEGRATION_STATE_FILE", "AI_CACHE_DIR", "LOG_FILE"):
        monkeypatch.setenv(name, str(outside / name))
    monkeypatch.setenv("PLUGIN_DIRS", '["external-plugin"]')
    monkeypatch.setenv("AI_ENABLED", "true")
    monkeypatch.setenv("SQLITE_PERSISTENT_STORE", "false")
    monkeypatch.setenv("IMMO_TESTVERSION", "true")
    monkeypatch.setenv("TASK_QUEUE_BACKEND", "celery")
    server = core.Server(tmp_path / "owned")
    env = server.env()
    for name in ("DATA_DIR", "UPLOADS_DIR", "BACKUP_DIR", "INTEGRATION_STATE_FILE", "AI_CACHE_DIR", "LOG_FILE"):
        assert Path(env[name]).resolve().is_relative_to(server.dir.resolve()), name
    assert env["PLUGIN_DIRS"] == "[]"
    assert env["AI_ENABLED"] == "false"
    assert env["SQLITE_PERSISTENT_STORE"] == "true"
    assert env["ALLOW_INMEMORY_FALLBACK"] == "false"
    assert env["IMMO_TESTVERSION"] == "false"
    assert env["TASK_QUEUE_BACKEND"] == "sync"
    if os.name == "nt":
        assert {key.upper(): value for key, value in env.items()}["SYSTEMROOT"] == os.environ["SystemRoot"]
    assert env["JWT_SECRET_KEY"] == server.env()["JWT_SECRET_KEY"]
    assert env["JWT_SECRET_KEY"] != core.Server(tmp_path / "other").env()["JWT_SECRET_KEY"]
    assert env["JWT_SECRET_KEY"] == server.clone("copy").env()["JWT_SECRET_KEY"]


def test_fresh_server_and_clone_preserve_existing_directories(tmp_path):
    existing = tmp_path / "main"
    existing.mkdir()
    (existing / "user-file").write_text("preserve", encoding="utf-8")
    server = core.Server(tmp_path)
    assert server.dir != existing
    (server.dir / "synthetic").write_text("fixture", encoding="utf-8")
    copy_dir = tmp_path / "copy"
    copy_dir.mkdir()
    (copy_dir / "user-file").write_text("preserve", encoding="utf-8")
    clone = server.clone("copy")
    assert clone.dir != copy_dir
    assert (clone.dir / "synthetic").read_text() == "fixture"
    assert (copy_dir / "user-file").read_text() == "preserve"
    assert (existing / "user-file").read_text() == "preserve"


@pytest.mark.parametrize("name", ["..", "../escape", "a/b", "a\\b", "C:\\escape"])
def test_fixture_names_cannot_escape_workdir(tmp_path, name):
    with pytest.raises(ValueError):
        core.Server(tmp_path, name)


def test_start_timeout_reaps_owned_process(tmp_path, monkeypatch):
    server = core.Server(tmp_path)
    original_popen = subprocess.Popen
    started = []
    def launch(args, **kwargs):
        proc = original_popen([sys.executable, "-c", "import time; time.sleep(120)"], **kwargs)
        started.append(proc)
        return proc
    monkeypatch.setattr(core.subprocess, "Popen", launch)
    monkeypatch.setattr(core.httpx, "get", lambda *a, **kw: (_ for _ in ()).throw(core.httpx.ConnectError("wait")))
    try:
        with pytest.raises(RuntimeError, match="did not start"):
            server.start(timeout=0.1)
        assert server.proc is None
    finally:
        for proc in started:
            if proc.poll() is None:
                original_popen(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).wait() if os.name == "nt" else proc.kill()
    # The parent log handle must be closed too (Windows refuses rename otherwise).
    server.log.rename(server.log.with_suffix(".closed"))


@pytest.mark.parametrize("hard", [False, True])
def test_stop_reaps_python_launcher_and_child(tmp_path, monkeypatch, hard):
    server = core.Server(tmp_path)
    pid_file = server.dir / "child.pid"
    original_popen = subprocess.Popen
    child_code = "import time; time.sleep(120)"
    launcher_code = (
        "import subprocess,sys,time,pathlib; "
        f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid)); "
        "p.wait()"
    )

    def launch(args, **kwargs):
        if "uvicorn" in args:
            args = [sys.executable, "-c", launcher_code]
        return original_popen(args, **kwargs)

    monkeypatch.setattr(core.subprocess, "Popen", launch)
    monkeypatch.setattr(core.httpx, "get", lambda *a, **kw: type("Ready", (), {"status_code": 200})())
    server.start()
    proc = server.proc
    deadline = time.monotonic() + 10
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pid_file.exists()
    child_pid = int(pid_file.read_text())
    try:
        server.stop(hard=hard)
        assert proc.poll() is not None
        if os.name == "nt":
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x100000, False, child_pid)
            if handle:
                try:
                    assert ctypes.windll.kernel32.WaitForSingleObject(handle, 5000) == 0
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
        else:
            # An orphan can remain a zombie until the OS reaps it; it must not run.
            stat = Path(f"/proc/{child_pid}/stat")
            assert not stat.exists() or stat.read_text().split()[2] == "Z"
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else proc.kill()
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(child_pid), "/T", "/F"], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)


@pytest.mark.parametrize("failure", ["startup", "simulation", "finding", "none"])
def test_run_preserves_reports_and_returns_failure_status(tmp_path, monkeypatch, failure):
    out = tmp_path / "runs"
    old = out / "server" / "main"
    old.mkdir(parents=True)
    (old / "user-file").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["xstress", "--quick", "--out", str(out), "--skip", "ui", "saveload", "rechte", "fehldaten"])

    def start(self, **kwargs):
        if failure == "startup":
            raise RuntimeError("synthetic startup failure")

    def simulate(self, callback):
        if failure == "simulation":
            raise RuntimeError("synthetic simulation failure")

    monkeypatch.setattr(core.Server, "start", start)
    monkeypatch.setattr(run, "setup_users", lambda *a: {})
    monkeypatch.setattr(run.Simulation, "run", simulate)
    monkeypatch.setattr(run, "run_checks", lambda sim, date: sim.f.add("FALSCH", "test", "failed check") if failure == "finding" else None)
    code = run.main()
    reports = list(out.glob("run-*/report.md"))
    assert len(reports) == 1
    assert (old / "user-file").read_text() == "keep"
    assert code == (0 if failure == "none" else 1)
    findings = json.loads(reports[0].with_name("findings.json").read_text(encoding="utf-8"))
    if failure != "none":
        assert any(f["severity"] != "HINWEIS" for f in findings)


def test_sql_test_configuration_never_deletes_external_database(tmp_path):
    sentinel = tmp_path / "immo_test.db"
    sentinel.write_bytes(b"outside database must survive")
    env = {**os.environ, "TEST_STORE_BACKEND": "sql", "DATABASE_URL": "sqlite:///external.db"}
    code = f"import tempfile,runpy; tempfile.tempdir={str(tmp_path)!r}; runpy.run_path('backend/tests/conftest.py')"
    result = subprocess.run([sys.executable, "-c", code], cwd=core.REPO, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert sentinel.read_bytes() == b"outside database must survive"


def test_sql_test_configuration_allocates_unique_default_databases(tmp_path):
    env = {**os.environ, "TEST_STORE_BACKEND": "sql"}
    env.pop("DATABASE_URL", None)
    code = f"import tempfile,runpy,os; tempfile.tempdir={str(tmp_path)!r}; runpy.run_path('backend/tests/conftest.py'); print(os.environ['DATABASE_URL'])"
    results = [subprocess.run([sys.executable, "-c", code], cwd=core.REPO, env=env, capture_output=True, text=True) for _ in range(2)]
    assert all(result.returncode == 0 for result in results)
    assert results[0].stdout != results[1].stdout


def test_crash_phase_cleanup_survives_setup_failure(tmp_path, monkeypatch):
    original_popen = subprocess.Popen
    processes = []

    def launch(args, **kwargs):
        proc = original_popen([sys.executable, "-c", "import time; time.sleep(120)"], **kwargs)
        processes.append(proc)
        return proc

    monkeypatch.setattr(core.subprocess, "Popen", launch)
    monkeypatch.setattr(core.httpx, "get", lambda *a, **kw: type("Ready", (), {"status_code": 200})())
    monkeypatch.setattr(saveload, "setup_users", lambda *a: (_ for _ in ()).throw(RuntimeError("setup failed")))
    server = core.Server(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="setup failed"):
            saveload.hard_kill(server, {}, core.Findings(), "account-1")
        assert len(processes) == 2
        assert processes[1].poll() is not None
    finally:
        server.stop(hard=True)
        if len(processes) > 1 and processes[1].poll() is None:
            processes[1].kill()
            processes[1].wait(timeout=10)
