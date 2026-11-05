"""Installer boundaries: private data and mutable upgrades never enter a payload."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from scripts import build_installer as installer
from scripts import check_windows_installer as installer_check

VERSION = "2.0.0-beta.1"


@pytest.fixture
def bundle(tmp_path):
    directory = tmp_path / "bundle"
    directory.mkdir()
    for name in installer.EXES:
        (directory / name).write_bytes(b"MZ" + name.encode())
    internal = directory / "_internal"
    (internal / "frontend/dist").mkdir(parents=True)
    (internal / "pyproject.toml").write_text('[project]\nversion="' + VERSION + '"\n', encoding="utf-8")
    (internal / "frontend/dist/product-profile.json").write_text('{"purpose":"core","document_tools":false}', encoding="utf-8")
    native_files = ["PySide6/QtWebEngineProcess.exe", "PySide6/Qt6WebEngineCore.dll", "PySide6/Qt6WebEngineWidgets.dll",
                    "PySide6/plugins/platforms/qwindows.dll", "PySide6/resources/icudtl.dat",
                    "PySide6/resources/qtwebengine_resources.pak", "PySide6/translations/qtwebengine_locales/de.pak"]
    for name in native_files:
        path = internal / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic inventory test resource")
    (internal / "desktop-runtime.json").write_text(json.dumps({"engine": "pyside6-qtwebengine", "version": "6.11.3", "workspaces": ["own", "demo-bw"],
                                                              "native_required_files": ["_internal/" + name for name in native_files]}), encoding="utf-8")
    return directory


def test_different_bundle_bytes_get_separate_payload_directories(bundle):
    first = installer.inventory(bundle, VERSION)
    assert installer.inventory(bundle, VERSION) == first
    (bundle / "_internal/new-library.pyd").write_bytes(b"new compiled module")
    second = installer.inventory(bundle, VERSION)
    assert first["payload_directory"] != second["payload_directory"]
    assert second["gui_executable"].startswith(second["payload_directory"] + "/")
    assert second["cli_executable"].endswith("ImmoManager-Pro-CLI.exe")
    assert all(".." not in Path(row["path"]).parts for row in second["files"])
    assert second["launch_modes"] == ["standalone", "browser"] and second["default_launch_mode"] == "standalone"


@pytest.mark.parametrize("fault", ["missing-marker", "missing-resource", "missing-native-proof", "escaping-path", "old-browser-only", "old-no-demo"])
def test_incomplete_standalone_runtime_cannot_be_packaged_as_both_modes(bundle, fault):
    marker_path = bundle / "_internal/desktop-runtime.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if fault == "missing-marker":
        marker_path.unlink()
    elif fault == "missing-resource":
        (bundle / marker["native_required_files"][0]).unlink()
    elif fault == "missing-native-proof":
        marker["native_required_files"] = []
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
    elif fault == "escaping-path":
        marker["native_required_files"].append("../outside.dll")
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
    elif fault == "old-no-demo":
        marker.pop("workspaces")
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
    else:
        marker["engine"] = "browser-only"
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises((ValueError, FileNotFoundError)):
        installer.inventory(bundle, VERSION)


def test_destination_budget_includes_payload_directory_and_utf16_code_units():
    directory = "app/2.0.0-beta.1-0123456789ab"
    relative = "_internal/legal/" + "\U0001f3e0" * 12 + "/ADDITIONAL_LICENSE_INFO"
    limits = installer.installation_path_limits(directory, [{"path": relative}])
    longest = len((directory + "/" + relative).encode("utf-16-le")) // 2
    assert limits["longest_installed_relative_path_utf16"] == longest
    assert limits["max_install_directory_utf16"] + 1 + longest == 240
    assert limits["max_destination_path_utf16"] + limits["destination_temporary_reserve_utf16"] == 259
    assert installer.utf16_length("C:/Users/Test/App") <= limits["max_install_directory_utf16"]


def test_uninstallable_internal_paths_fail_before_compilation():
    with pytest.raises(ValueError, match="Interne Paketpfade"):
        installer.installation_path_limits("app/" + "x" * 235, [{"path": "program.exe"}])


@pytest.mark.parametrize("private", [".env", ".ENV", ".env.from-backup", "customer.db", "state.sqlite3", "state.sqlite3-wal"])
def test_private_files_are_rejected_even_below_internal(bundle, private):
    (bundle / "_internal" / private).write_bytes(b"private data must not be packaged")
    with pytest.raises(ValueError, match="Private Konfiguration"):
        installer.inventory(bundle, VERSION)


@pytest.mark.parametrize("private", ["data", "Uploads", "Backups", "SECRETS", "logs"])
def test_private_root_directories_are_rejected_case_insensitively(bundle, private):
    (bundle / private).mkdir()
    with pytest.raises(ValueError, match="privaten Datenordner"):
        installer.inventory(bundle, VERSION)


def test_missing_cli_or_wrong_source_version_cannot_be_installed(bundle):
    with pytest.raises(ValueError, match="Quellversion"):
        installer.inventory(bundle, "9.0.0")
    (bundle / installer.EXES[1]).unlink()
    with pytest.raises(FileNotFoundError):
        installer.inventory(bundle, VERSION)


@pytest.mark.parametrize("profile", [
    {"purpose": "validation", "document_tools": True},
    {"purpose": "unknown", "document_tools": False},
    {"purpose": "core", "document_tools": True},
    {"purpose": "core", "document_tools": "false"},
])
def test_validation_or_inconsistent_profiles_are_not_user_installers(bundle, profile):
    (bundle / "_internal/frontend/dist/product-profile.json").write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(ValueError, match="profil"):
        installer.inventory(bundle, VERSION)


def test_output_may_not_be_written_into_the_bundle(bundle, tmp_path):
    with pytest.raises(ValueError, match="Ausgabeordner"):
        installer.build(bundle, bundle / "installers", tmp_path / "missing-compiler")


@pytest.mark.parametrize("mode", ["standalone", "browser"])
def test_shortcut_verification_checks_both_alternatives_and_the_selected_desktop_mode(tmp_path, monkeypatch, mode):
    group, desktop, gui = tmp_path / "Startmenü", tmp_path / "Desktop/ImmoManager Pro.lnk", tmp_path / "App Ä/ImmoManager-Pro.exe"
    expected = {group / "ImmoManager Pro.lnk": mode,
                group / "Startmöglichkeiten/Eigenständige Desktop-Anwendung.lnk": "standalone",
                group / "Startmöglichkeiten/Im Webbrowser verwenden.lnk": "browser",
                desktop: mode}
    demo = {group / "Demo/Baden-Württemberg – Desktop.lnk": "standalone",
            group / "Demo/Baden-Württemberg – Webbrowser.lnk": "browser"}
    monkeypatch.setattr(installer_check, "shortcut_info", lambda path: {"target": str(gui), "arguments": "--mode " + (demo[path] + " --demo" if path in demo else expected[path]),
                                                                       "working_directory": str(gui.parent)})
    checked = installer_check.verify_mode_shortcuts(group, desktop, gui, mode, desktop_owned=True)
    assert {Path(item["path"]) for item in checked} == set(expected) | set(demo)
    assert sum(item["demo"] for item in checked) == 2


@pytest.mark.parametrize("fault", ["target", "arguments", "working_directory"])
def test_shortcut_verification_rejects_an_incorrect_launch_contract(tmp_path, monkeypatch, fault):
    gui = tmp_path / "App/ImmoManager-Pro.exe"
    values = {"target": str(gui), "arguments": "--mode browser", "working_directory": str(gui.parent)}
    values[fault] = str(tmp_path / "other") if fault != "arguments" else "--mode standalone"
    monkeypatch.setattr(installer_check, "shortcut_info", lambda _: values)
    with pytest.raises(AssertionError):
        installer_check.verify_mode_shortcuts(tmp_path / "Startmenü", tmp_path / "unused.lnk", gui, "browser", desktop_owned=False)


@pytest.mark.parametrize("existing", ["ImmoManager Pro", "Isolated QA"])
def test_installer_qa_refuses_existing_start_menu_folders_before_installation(tmp_path, existing):
    folder = tmp_path / existing
    folder.mkdir()
    sentinel = folder / "existing-user-shortcut.lnk"
    sentinel.write_bytes(b"user-owned shortcut; preserve unchanged")
    with pytest.raises(SystemExit, match="no installation started"):
        installer_check.require_shortcut_isolation(tmp_path, tmp_path / "Isolated QA")
    assert sentinel.read_bytes() == b"user-owned shortcut; preserve unchanged"


def test_installer_qa_accepts_only_fresh_start_menu_targets(tmp_path):
    installer_check.require_shortcut_isolation(tmp_path, tmp_path / "Isolated QA")
    assert list(tmp_path.iterdir()) == []


def test_compilation_is_explicit_and_failure_never_claims_an_installer(bundle, tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nversion="' + VERSION + '"\n', encoding="utf-8")
    compiler = tmp_path / "ISCC.exe"
    compiler.write_bytes(b"not executed by this contract test")
    output = tmp_path / "build"
    def fail(command, **options):
        assert command[0] == str(compiler)
        assert "/DBundleDir=" + str(bundle) in command
        assert options["check"] is True
        assert options["capture_output"] is True
        assert any(value.startswith("/DMaxInstallDirUtf16=") for value in command)
        raise subprocess.CalledProcessError(2, command, output="Compiler source diagnostic\n", stderr="Compiler error\n")
    monkeypatch.setattr(installer.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        installer.build(bundle, output, compiler, root=root)
    assert not list(output.glob("*.build.json"))
    assert not list(output.glob("*.sha256"))
    assert next(output.glob("*.compiler.log")).read_text(encoding="utf-8") == "Compiler source diagnostic\nCompiler error\n"


def test_template_uses_separate_payload_and_never_removes_user_data():
    source = (installer.ROOT / "packaging/installer/ImmoManager-Pro.iss").read_text(encoding="utf-8")
    assert 'DestDir: "{app}\\{#PayloadSubdir}"' in source
    assert '[UninstallDelete]' not in source and '[InstallDelete]' not in source
    assert 'AppMutex=Local\\ImmoManagerPro.Desktop' in source
    assert 'PrivilegesRequired=lowest' in source
    assert 'CloseApplications=no' in source and 'RestartApplications=no' in source
    assert 'postinstall skipifsilent' in source
    assert 'DisableProgramGroupPage=no' in source
    assert 'Result := PageID = wpSelectProgramGroup;' in source


@pytest.mark.skipif(os.name != "nt", reason="Real Inno silent-validation event requires Windows")
def test_silent_directory_rejection_exits_without_a_modal_dialog(tmp_path):
    compiler = os.environ.get("IMMO_TEST_ISCC")
    if not compiler:
        pytest.skip("Supply an explicitly verified Inno compiler through IMMO_TEST_ISCC")
    from ctypes import WinDLL, c_void_p

    from backend.services.assistant_provider_process import _windows_job

    source = (installer.ROOT / "packaging/installer/ImmoManager-Pro.iss").read_text(encoding="utf-8")
    # Exercise the actual event, without installing product files, shortcuts or
    # an uninstall entry. An always-invalid fixture covers its error branch.
    event = "function NextButtonClick(" + source.split("function NextButtonClick(", 1)[1].split("function ShouldSkipPage", 1)[0]
    script = tmp_path / "silent-validation.iss"
    script.write_text("[Setup]\nAppId=ImmoSilentQA-" + uuid4().hex + "\nAppName=Isolated silent validation QA\n"
                      "AppVersion=0.0.0-qa\nDefaultDirName={tmp}\\NeverCreatedSilentQA\n"
                      "PrivilegesRequired=lowest\nCreateAppDir=yes\nUninstallable=no\nDisableDirPage=no\n"
                      "DisableWelcomePage=yes\nOutputBaseFilename=ONLY-SILENT-VALIDATION-QA\n"
                      "[Code]\nfunction ValidateDirectory(const Value: String): String;\nbegin\n"
                      "Result := 'synthetic silent guard probe';\nend;\n" + event, encoding="utf-8")
    compiled = subprocess.run([compiler, "/O" + str(tmp_path), str(script)], capture_output=True,
                              stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
    assert compiled.returncode == 0, (compiled.stdout + compiled.stderr).decode(errors="replace")
    log, target = tmp_path / "silent.log", tmp_path / "rejected-target"
    command = [str(tmp_path / "ONLY-SILENT-VALIDATION-QA.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES",
               "/NORESTART", "/SP-", "/DIR=" + str(target), "/LOG=" + str(log)]
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               creationflags=subprocess.CREATE_NO_WINDOW | 0x4)  # CREATE_SUSPENDED
    job = None
    try:
        # A broken future guard must not leave a modal installer child behind.
        # Only descendants of this suspended Popen enter the owned kill-on-close job.
        job = _windows_job(process)
        output, _ = process.communicate(timeout=20)
        assert process.returncode != 0, output.decode(errors="replace")
        assert "synthetic silent guard probe" in log.read_text(encoding="utf-8-sig")
        assert not target.exists()
    finally:
        if job is not None:
            kernel = WinDLL("kernel32")
            kernel.CloseHandle.argtypes = [c_void_p]
            kernel.CloseHandle(job)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


@pytest.mark.parametrize("version", ["1.2", "2.0.0/other", "1.2.65536", "2.0.0\nignored"])
def test_invalid_versions_cannot_enter_paths_or_compiler_defines(version):
    with pytest.raises(ValueError):
        installer.version_info(version)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction and legacy compiler source path")
def test_long_compiler_sources_get_an_owned_short_alias_that_is_removed(tmp_path):
    relative = Path("legal") / ("x" * 85) / "ADDITIONAL_LICENSE_INFO"
    bundle = tmp_path / ("bundle-" + "x" * 95)
    original = bundle / relative
    installer.native(original.parent).mkdir(parents=True)
    installer.native(original).write_bytes(b"preserved upstream notice")
    alias = None
    with tempfile.TemporaryDirectory(prefix="immo-source-test-") as folder:
        with installer.compiler_source(bundle, Path(folder), [{"path": relative.as_posix()}]) as source:
            alias = source
            assert source != bundle and (source / relative).read_bytes() == b"preserved upstream notice"
            assert len(str(source / relative).encode("utf-16-le")) // 2 < 260
        assert not alias.exists()
    assert installer.native(original).read_bytes() == b"preserved upstream notice"
