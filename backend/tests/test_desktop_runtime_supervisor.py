"""Packaged acceptance must execute one complete, unmixed native Qt runtime."""
import builtins
import hashlib
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import check_desktop_runtime as check
from tools.desktop_bundle import required_groups


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
