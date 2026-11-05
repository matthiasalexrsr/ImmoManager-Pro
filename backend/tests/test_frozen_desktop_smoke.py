"""Supervisor boundaries; real GUI acceptance is run against the frozen artifact."""

import io
import json
import os
import struct
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import check_frozen_desktop as check


@pytest.mark.parametrize("platform,relative", [
    ("win32", "ImmoManager-Pro.exe"), ("linux", "ImmoManager-Pro"),
    ("darwin", "Contents/MacOS/ImmoManager-Pro"),
])
def test_only_the_actual_native_gui_entry_is_selected(tmp_path, platform, relative):
    root = tmp_path / ("ImmoManager Pro.app" if platform == "darwin" else "distribution")
    gui = root / relative
    gui.parent.mkdir(parents=True)
    if platform == "win32":
        image = bytearray(64 + 94)
        image[:2] = b"MZ"
        struct.pack_into("<I", image, 60, 64)
        image[64:68] = b"PE\0\0"
        struct.pack_into("<H", image, 64 + 92, 2)
        gui.write_bytes(image)
        assert check.gui_executable(root, platform=platform) == gui
        struct.pack_into("<H", image, 64 + 92, 3)
        gui.write_bytes(image)
        with pytest.raises(ValueError, match="windowed"):
            check.gui_executable(root, platform=platform)
    else:
        gui.write_bytes(b"native executable fixture")
        assert check.gui_executable(root, platform=platform) == gui


def test_foreign_app_bundle_cannot_be_claimed_as_a_native_check(tmp_path):
    root = tmp_path / "application.app"
    root.mkdir()
    with pytest.raises(ValueError, match="on macOS"):
        check.gui_executable(root, platform="linux")


def test_sterile_environment_redirects_profiles_temp_and_all_data(tmp_path):
    inherited = {"PATH": "preserve-os-path", "SYSTEMROOT": "C:/Windows", "DISPLAY": ":99",
        "DATA_DIR": "real customer data", "DATABASE_URL": "real customer DB", "QT_PLUGIN_PATH": "foreign plugin",
        "QTWEBENGINE_DISABLE_SANDBOX": "1", "HTTP_PROXY": "foreign proxy", "HOME": "real home",
        "SMTP_PASSWORD": "private", "IMMO_DESKTOP_INSTANCE_FD": "123", "PYTHONPATH": "foreign module"}
    environment = check.isolated_environment(tmp_path, 12345, inherited)
    assert environment["PATH"] == inherited["PATH"]
    assert environment["DATA_DIR"] == str(tmp_path / "data")
    assert environment["DATABASE_URL"] == "sqlite:///" + (tmp_path / "data/synthetic.db").as_posix()
    for name in ("HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "TMPDIR",
                 "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR"):
        assert str(environment[name]).startswith(str(tmp_path))
    assert not set(inherited).intersection(environment).intersection({"QT_PLUGIN_PATH", "QTWEBENGINE_DISABLE_SANDBOX",
        "HTTP_PROXY", "SMTP_PASSWORD", "IMMO_DESKTOP_INSTANCE_FD", "PYTHONPATH"})
    assert environment["IMMO_TESTVERSION"] == "false" and environment["ENVIRONMENT"] == "production"
    assert "--no-sandbox" not in environment["QTWEBENGINE_CHROMIUM_FLAGS"]


def test_renderer_and_server_evidence_cannot_be_quoted_or_ambiguous():
    assert check.loaded("2026-11-05 10:20:30,123 " + check.LOADED + "\n")
    assert not check.loaded("2026-11-05 10:20:30,123 Fehler: '" + check.LOADED + "'\n")
    assert check.server_pid("INFO: Started server process [123]\n") == 123
    with pytest.raises(ValueError, match="Multiple"):
        check.server_pid("Started server process [123]\nStarted server process [456]\n")


def test_backend_shutdown_requires_one_exact_app_json_lifecycle_record():
    record = {"timestamp": "2026-11-05T11:23:02.683965+00:00", "level": "INFO", "logger": "backend.app",
              "message": "ImmoManager Pro shutting down", "request_id": "-", "user_id": "-"}
    line = json.dumps(record)
    assert check.backend_shutdown_record("unrelated startup text\n" + line + "\n") == record
    assert check.backend_shutdown_record(line + "\n" + line) is None
    assert check.backend_shutdown_record(json.dumps({**record, "logger": "another.module"})) is None
    assert check.backend_shutdown_record(json.dumps({**record, "message": "Quoted: 'ImmoManager Pro shutting down'"})) is None
    assert check.backend_shutdown_record(json.dumps({**record, "level": "ERROR"})) is None
    assert check.backend_shutdown_record(json.dumps(line)) is None
    assert check.backend_shutdown_record("INFO: " + line) is None
    assert check.backend_shutdown_record("Application shutdown complete.\nFinished server process [123]\n") is None


def test_no_native_process_handle_can_be_acquired_for_an_unowned_pid(monkeypatch):
    monkeypatch.setattr(check, "_owned_descendant", lambda *args: False)
    monkeypatch.setattr(check.ctypes, "WinDLL", lambda *a, **k: pytest.fail("Must not open a foreign process"), raising=False)
    with pytest.raises(ValueError, match="not an OS-owned descendant"):
        check.ServerWatch(987654, os.getpid())


def test_native_retained_watcher_observes_an_owned_child_exit_zero():
    child = subprocess.Popen([sys.executable, "-c", "import sys; print('ready',flush=True); sys.stdin.read()"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    watch = None
    try:
        assert child.stdout is not None and child.stdin is not None
        assert child.stdout.readline().strip() == "ready"
        watch = check.ServerWatch(child.pid, os.getpid())
        assert watch.poll() is None
        child.stdin.close()
        deadline = time.monotonic() + 10
        while watch.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert watch.poll() == 0
    finally:
        if watch is not None:
            watch.close()
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                stream.close()


@pytest.mark.parametrize("foreign", [False, True])
@pytest.mark.parametrize("demo", [False, True])
def test_run_uses_real_gui_argv_records_deliberate_termination_and_never_kills_foreign_pid(tmp_path, monkeypatch, foreign, demo):
    gui = tmp_path / "actual-gui"
    gui.write_bytes(b"entry fixture")
    output = tmp_path / "new-isolated-run"
    calls: list[Any] = []
    log = output / "data/logs/desktop.log"

    class Child:
        pid = 123
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            calls.append("terminate-own-gui")
            self.returncode = 47
            # The intentionally killed GUI cannot forward any more stdout.
            # The independent backend still writes its own JSON lifecycle log.
            record = {"timestamp": "2026-11-05T11:23:02.683965+00:00", "level": "INFO", "logger": "backend.app",
                      "message": "ImmoManager Pro shutting down", "request_id": "-", "user_id": "-"}
            log.with_name("immomanager.log").write_text(json.dumps(record) + "\n", encoding="utf-8")

        def wait(self, **kwargs):
            return self.returncode

    child = Child()

    def launch(command, **kwargs):
        calls.append((command, kwargs))
        log.parent.mkdir(parents=True)
        log.write_text("2026-11-05 10:20:30,123 INFO: Started server process [456]\n"
                       "2026-11-05 10:20:31,123 " + check.LOADED + "\n", encoding="utf-8")
        return child

    class Watch:
        pid, code, raw_status = 456, None, None

        def __init__(self, pid, gui_pid):
            assert (pid, gui_pid) == (456, 123)
            if foreign:
                raise ValueError("not an OS-owned descendant")

        def poll(self):
            if child.returncode is not None:
                self.code = 0
            return self.code

        def force_kill(self):
            pytest.fail("A graceful or foreign server must not be force-killed")

        def close(self):
            pass

    health = {"status": "ok", "version": "2.0.0-beta.1", "environment": "production", "testversion": False,
              "database_connected": True, "store_backend": "SQLAlchemyStore", "demo": demo, "demo_ready": demo}
    monkeypatch.setattr(check, "gui_executable", lambda _: gui)
    monkeypatch.setattr(check, "enable_exit_collection", lambda: None)
    monkeypatch.setattr(check, "ServerWatch", Watch)
    monkeypatch.setattr(check, "free_port", lambda: 12345)
    monkeypatch.setattr(check, "port_closed", lambda _: True)
    monkeypatch.setattr(check.subprocess, "Popen", launch)
    monkeypatch.setattr(check.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=lambda *a, **k: io.BytesIO(json.dumps(health).encode())))
    args = SimpleNamespace(dist=tmp_path, output=output, startup_timeout=1, shutdown_timeout=1, expected_version="2.0.0-beta.1", demo=demo)
    result = check.run(args)
    assert result["status"] == ("failed" if foreign else "passed")
    command, options = calls[0]
    assert command == [str(gui), "--mode", "standalone", "--software-rendering", "--no-browser",
                       "--host", "127.0.0.1", "--port", "12345", "--data-dir", str(output / "data")] + (["--demo"] if demo else [])
    assert options["cwd"] == output
    assert options["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert calls.count("terminate-own-gui") == 1
    assert result["gui_exit_code"] == 47
    assert result["gui_test_termination_requested"] is True
    assert result["normal_gui_close_exercised"] is False
    assert result["server_port_closed_after_cleanup"] is True
    assert result["forced_server_cleanup"] is False
    assert "Finished server process" not in log.read_text(encoding="utf-8")
    if not foreign:
        assert bool(result["checks"].get("demo_seed_ready_from_real_packaged_gui")) is demo
        assert result["checks"]["owned_backend_application_shutdown_record"] is True
        assert result["backend_shutdown_record"]["logger"] == "backend.app"
        assert "server_graceful_shutdown_log" not in result["checks"]
    assert json.loads((output / "verification.json").read_text()) == result
