"""Packaged acceptance must execute one complete, unmixed native Qt runtime."""
import builtins
import hashlib
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from backend.standalone_policy import LocalOrigin
from scripts import check_desktop_runtime as check
from tools.desktop_bundle import required_groups


class StartupSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, value):
        for callback in self.callbacks:
            callback(value)


@pytest.fixture
def startup_probe(monkeypatch):
    origin = LocalOrigin.from_url("http://127.0.0.1:18791")
    state = SimpleNamespace(time=0.0, url="about:blank", event_queue=[], calls=[], respond=False)
    service_signal, loading_signal = StartupSignal(), StartupSignal()

    def sleep(seconds):
        state.time += seconds

    def pump():
        if state.event_queue:
            state.event_queue.pop(0)()

    def run_script(code, callback):
        state.calls.append((code, state.url, state.time))
        if state.respond:
            callback(True)

    def load(status, reported_url, current_url):
        state.url = current_url
        loading_signal.emit(SimpleNamespace(status=lambda: status,
                                            url=lambda: SimpleNamespace(toString=lambda: reported_url)))

    monkeypatch.setattr(check, "time", SimpleNamespace(monotonic=lambda: state.time, sleep=sleep))
    view = SimpleNamespace(
        url=lambda: SimpleNamespace(toString=lambda: state.url),
        page=lambda: SimpleNamespace(loadingChanged=loading_signal, runJavaScript=run_script),
    )
    app = SimpleNamespace(processEvents=pump)
    window = SimpleNamespace(policy=origin, web_view=view, serviceReady=service_signal)
    return state, app, window, load


@pytest.mark.parametrize("synchronize", [False, True])
def test_startup_does_not_send_setup_script_to_previous_document(startup_probe, synchronize):
    state, app, window, load = startup_probe
    local = window.policy.url
    foreign = "http://127.0.0.1:18792/"
    ready = check.watch_initial_document(window, "success") if synchronize else None

    def complete():
        load("success", local, local)
        state.respond = True

    state.event_queue[:] = [
        lambda: None,
        lambda: window.serviceReady.emit(foreign),
        lambda: load("success", local, local),  # No signal from the owned service yet.
        lambda: load("started", local, local),
        lambda: window.serviceReady.emit(local),
        lambda: load("success", "about:blank", local),
        lambda: load("success", foreign, local),
        lambda: load("failure", local, local),
        lambda: load("success", local, foreign),
        complete,
    ]
    if synchronize:
        assert check.wait_javascript_qt(app, window, "test setup fields", timeout=120, ready=ready) is True
        assert [(code, url) for code, url, _ in state.calls] == [("test setup fields", local)]
        assert not state.event_queue
    else:
        # The old ordering sends once to the blank renderer and times out even
        # though the owned page subsequently loaded.
        with pytest.raises(TimeoutError):
            check.wait_javascript_qt(app, window, "test setup fields", timeout=120)
        assert state.calls == [("test setup fields", "about:blank", 0.0)]
        assert not state.event_queue
        assert 10 <= state.time < 10.03


def test_initial_callback_shares_the_remaining_budget_and_is_not_retried(startup_probe):
    state, app, window, load = startup_probe
    local = window.policy.url
    ready = check.watch_initial_document(window, "success")

    def finish_late():
        state.time = 119.9
        window.serviceReady.emit(local)
        load("success", local, local)

    state.event_queue[:] = [finish_late]
    with pytest.raises(TimeoutError):
        check.wait_javascript_qt(app, window, "test setup fields", timeout=120, ready=ready)
    assert state.calls == [("test setup fields", local, 119.9)]
    assert 120 <= state.time < 120.03


def native_bundle(tmp_path, platform):
    root = tmp_path / ("ImmoManager Pro.app" if platform == "darwin" else "distribution")
    bundle = root / "Contents" if platform == "darwin" else root
    marker_path = bundle / ("Resources/desktop-runtime.json" if platform == "darwin" else "_internal/desktop-runtime.json")
    marker_path.parent.mkdir(parents=True)
    entries = []
    names = [sorted(group)[0] for group in required_groups(platform)] + ["de.pak", "en-US.pak"]
    for name in names:
        path = bundle / "native" / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(("Native component fixture " + name).encode())
        entries.append({"file": path.relative_to(bundle).as_posix(),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    marker = {"schema": "immomanager-desktop-runtime/1", "engine": "pyside6-qtwebengine",
              "version": "6.11.3", "platform": platform, "files": entries}
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    cli = bundle / ("MacOS" if platform == "darwin" else "") / (
        "ImmoManager-Pro-CLI.exe" if platform == "win32" else "ImmoManager-Pro-CLI")
    cli.parent.mkdir(exist_ok=True)
    cli.write_bytes(b"Actual CLI entry fixture")
    return root, bundle, cli, marker_path, marker


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_complete_native_runtime_and_actual_cli_are_verified(tmp_path, platform):
    root, bundle, cli, _, _ = native_bundle(tmp_path, platform)
    assert check.packaged_cli(root, platform=platform) == (cli, bundle)
    next((bundle / "native").iterdir()).write_bytes(b"changed after packaging")
    with pytest.raises(ValueError, match="Changed packaged desktop runtime"):
        check.packaged_cli(root, platform=platform)


@pytest.mark.parametrize("mutation", ["missing-group", "outside", "wrong-version"])
def test_incomplete_foreign_or_changed_inventory_cannot_be_accepted(tmp_path, mutation):
    root, _, _, marker_path, marker = native_bundle(tmp_path, "linux")
    if mutation == "missing-group":
        marker["files"] = marker["files"][1:]
    elif mutation == "outside":
        marker["files"][0]["file"] = "../outside/icudtl.dat"
        outside = tmp_path / "outside/icudtl.dat"
        outside.parent.mkdir()
        outside.write_bytes(b"foreign")
    else:
        marker["version"] = "6.11.2"
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete|outside|Unexpected"):
        check.packaged_cli(root, platform="linux")


@pytest.mark.parametrize("demo", [False, True])
def test_dist_supervisor_never_imports_source_qt_and_uses_fixed_native_command(tmp_path, monkeypatch, demo):
    root, _, cli, _, _ = native_bundle(tmp_path, sys.platform)
    output = tmp_path / "fresh-acceptance"
    monkeypatch.setenv("DATA_DIR", "customer data must not be inherited")
    monkeypatch.setenv("QTWEBENGINEPROCESS_PATH", "source Qt helper must not be inherited")
    imported = builtins.__import__

    def no_host_qt(name, *args, **kwargs):
        assert not name.startswith("PySide6") and name != "backend.standalone"
        return imported(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_host_qt)

    def run(command, **kwargs):
        assert command == [str(cli), "desktop-runtime-check", "--output", str(output)] + (["--demo"] if demo else [])
        assert "--dist" not in command and "-m" not in command
        assert "DATA_DIR" not in kwargs["env"] and "QTWEBENGINEPROCESS_PATH" not in kwargs["env"]
        assert kwargs["env"]["QT_QPA_PLATFORM"] == "offscreen"
        assert "--no-sandbox" not in kwargs["env"]["QTWEBENGINE_CHROMIUM_FLAGS"]
        assert kwargs["cwd"] == cli.parent and not output.exists()
        output.mkdir()
        (output / "verification.json").write_text(json.dumps({"status": "passed", "packaged_runtime": True}))
        return SimpleNamespace(returncode=0, stdout="Actual frozen child output\n")

    monkeypatch.setattr(check.subprocess, "run", run)
    assert check.main(["--dist", str(root), "--output", str(output)] + (["--demo"] if demo else [])) == 0
    receipt = json.loads((output / "frozen-supervisor.json").read_text())
    assert receipt["actual_exit_code"] == 0
    assert receipt["cli_sha256"] == hashlib.sha256(cli.read_bytes()).hexdigest()


def test_child_failure_is_propagated_even_if_a_receipt_claims_success(tmp_path, monkeypatch):
    root, _, _, _, _ = native_bundle(tmp_path, sys.platform)
    output = tmp_path / "failed-child"

    def run(*args, **kwargs):
        output.mkdir()
        (output / "verification.json").write_text(json.dumps({"status": "passed", "packaged_runtime": True}))
        return SimpleNamespace(returncode=23, stdout="Native process failed after UI work\n")

    monkeypatch.setattr(check.subprocess, "run", run)
    assert check.supervise_packaged(root, output, False) == 23
    assert json.loads((output / "frozen-supervisor.json").read_text())["actual_exit_code"] == 23


@pytest.mark.parametrize("receipt", [{"status": "failed", "packaged_runtime": True},
                                    {"status": "passed", "packaged_runtime": False}])
def test_exit_zero_alone_is_insufficient_for_packaged_acceptance(tmp_path, monkeypatch, receipt):
    root, _, _, _, _ = native_bundle(tmp_path, sys.platform)
    output = tmp_path / "incomplete-child"

    def run(*args, **kwargs):
        output.mkdir()
        (output / "verification.json").write_text(json.dumps(receipt))
        return SimpleNamespace(returncode=0, stdout="Incomplete evidence\n")

    monkeypatch.setattr(check.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="passing packaged-runtime evidence"):
        check.supervise_packaged(root, output, False)


def test_existing_output_is_rejected_before_any_native_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(check.subprocess, "run", lambda *a, **kw: pytest.fail("Must not launch a child"))
    with pytest.raises(FileExistsError, match="new output"):
        check.supervise_packaged(tmp_path / "unused", tmp_path, False)


@pytest.mark.parametrize("foreign", [False, True])
@pytest.mark.parametrize("key", ["QT_PLUGIN_PATH", "LD_LIBRARY_PATH"])
def test_frozen_hook_paths_are_preserved_only_within_actual_bundle(tmp_path, monkeypatch, foreign, key):
    _, bundle, cli, _, _ = native_bundle(tmp_path, sys.platform)
    monkeypatch.setattr(check.sys, "executable", str(cli))
    hook_path = tmp_path / "foreign-qt" if foreign else bundle / "native"
    for variable in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH", "QTWEBENGINEPROCESS_PATH",
                     "QTWEBENGINE_RESOURCES_PATH", "QTWEBENGINE_LOCALES_PATH", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(key, str(hook_path))
    if foreign:
        with pytest.raises(ValueError, match="outside its own bundle"):
            check.frozen_hook_environment()
    else:
        environment, actual = check.frozen_hook_environment()
        assert environment[key] == str(hook_path) and actual == bundle


def test_frozen_child_cannot_reenter_supervisor_or_create_output(tmp_path, monkeypatch):
    monkeypatch.setattr(check.sys, "frozen", True, raising=False)
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="external supervisor"):
        check.main(["--dist", str(tmp_path), "--output", str(output)])
    assert not output.exists()


def test_fixed_cli_diagnostic_help_precedes_customer_configuration_and_qt(tmp_path):
    forbidden = tmp_path / "customer-data-must-not-be-created"
    environment = dict(os.environ, DATA_DIR=str(forbidden), UPLOADS_DIR=str(forbidden / "uploads"),
                       DATABASE_URL="sqlite:///" + (forbidden / "customer.db").as_posix())
    completed = subprocess.run([sys.executable, "-m", "backend", "desktop-runtime-check", "--help"],
        cwd=check.ROOT, env=environment, capture_output=True, text=True, encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "--dist" in completed.stdout and "--demo" in completed.stdout
    assert not forbidden.exists()
