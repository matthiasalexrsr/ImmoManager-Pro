"""Toolsetup guards, process ownership and runtime tamper refusal.

Real locked package installation/PNG/PDF checks are separately executed by the
explicit administration CLI; these tests do not substitute mocks for that gate.
"""
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts import windows_ocr_tools as tools


@pytest.fixture
def portable_setup(monkeypatch):
    monkeypatch.setattr(tools, "_windows", lambda: None)
    if os.name != "nt":
        monkeypatch.setattr(tools, "_windows_sid", lambda: None)


def small_lock(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    content = b"reviewed package bytes"
    artifact = {"fn": "tesseract-test.conda", "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest()}
    (cache / artifact["fn"]).write_bytes(content)
    bootstrap = {"fn": "bootstrap.tar.bz2", "size": len(content), "sha256": artifact["sha256"]}
    (cache / bootstrap["fn"]).write_bytes(content)
    lock = {"packages": [artifact], "bootstrap": bootstrap}
    monkeypatch.setattr(tools, "load_lock", lambda: lock)
    return cache, lock


def test_committed_lock_has_full_pinned_sources_licenses_and_native_languages():
    lock = tools.load_lock()
    assert len(lock["packages"]) == 52
    packages = {p["name"]: p for p in lock["packages"]}
    assert packages["tesseract"]["version"] == "5.5.3"
    assert packages["poppler"]["version"] == "26.09.0"
    assert packages["poppler"]["license"] == "GPL-2.0-or-later"
    assert "Microsoft" in packages["vc14_runtime"]["license"]
    assert packages["tesseract"]["license_files"]
    assert packages["poppler"]["license_files"]
    assert set(lock["critical_files"]) == {
        "Library/bin/pdfinfo.exe", "Library/bin/pdftotext.exe", "Library/bin/pdftoppm.exe",
        "Library/bin/tesseract.exe", "share/tessdata/deu.traineddata", "share/tessdata/eng.traineddata"}


def test_failed_hash_preflight_has_no_target_or_cache_writes(tmp_path, monkeypatch, portable_setup):
    cache, lock = small_lock(tmp_path, monkeypatch)
    damaged = cache / lock["packages"][0]["fn"]
    damaged.write_bytes(b"tampered package bytes")
    before = {p.name: p.read_bytes() for p in cache.iterdir()}
    target = tmp_path / "new tools"
    with pytest.raises(tools.ToolSetupError, match="SHA-256"):
        tools.install(cache, target)
    assert not target.exists()
    assert {p.name: p.read_bytes() for p in cache.iterdir()} == before


def test_missing_input_refused_before_target_creation(tmp_path, monkeypatch, portable_setup):
    cache, lock = small_lock(tmp_path, monkeypatch)
    (cache / lock["packages"][0]["fn"]).unlink()
    target = tmp_path / "new tools"
    with pytest.raises(tools.ToolSetupError) as exc:
        tools.install(cache, target)
    assert exc.value.code == "package_missing"
    assert not target.exists()


def test_existing_target_and_permissions_remain_unchanged(tmp_path, monkeypatch, portable_setup):
    cache, _ = small_lock(tmp_path, monkeypatch)
    target = tmp_path / "existing"
    target.mkdir()
    original = target / "existing-tool.exe"
    original.write_bytes(b"do not replace")
    before = target.stat().st_mode
    with pytest.raises((ValueError, FileExistsError)):
        tools.install(cache, target)
    assert original.read_bytes() == b"do not replace"
    assert target.stat().st_mode == before
    assert list(target.iterdir()) == [original]


def test_source_cache_cannot_be_used_as_install_target(tmp_path, monkeypatch, portable_setup):
    cache, _ = small_lock(tmp_path, monkeypatch)
    target = cache / "never write here"
    with pytest.raises(tools.ToolSetupError) as exc:
        tools.install(cache, target)
    assert exc.value.code == "target_in_source_cache"
    assert not target.exists()


def test_unicode_final_target_requires_only_an_explicit_ascii_stage(tmp_path, portable_setup):
    cache = tmp_path / "cache"
    cache.mkdir()
    target = tmp_path / "frei gewähltes Werkzeugziel"
    with pytest.raises(tools.ToolSetupError) as exc:
        tools._install_paths(cache, target, None)
    assert exc.value.code == "staging_required"
    assert not target.exists()
    resolved, stage = tools._install_paths(cache, target, tmp_path)
    assert resolved == target and stage == tmp_path
    assert not target.exists()


def test_staged_publish_moves_only_owned_new_directories_and_keeps_other_inputs(tmp_path, portable_setup):
    workspace = tools._new_target(tmp_path / "stage")
    target = tools._new_target(tmp_path / "endgültiges Ziel")
    for directory in ("env", "licenses", "bootstrap"):
        (workspace / directory).mkdir()
        (workspace / directory / "file.txt").write_bytes(b"verified content")
    (workspace / "archives").mkdir()
    archive = workspace / "archives/input.conda"
    archive.write_bytes(b"retained source")
    tools._publish_new_prefix(workspace, target)
    assert all((target / directory / "file.txt").read_bytes() == b"verified content"
               for directory in ("env", "licenses", "bootstrap"))
    assert archive.read_bytes() == b"retained source"


def test_staged_publish_refuses_any_existing_destination_before_moving(tmp_path, portable_setup):
    workspace = tools._new_target(tmp_path / "stage")
    target = tools._new_target(tmp_path / "target")
    for directory in ("env", "licenses", "bootstrap"):
        (workspace / directory).mkdir()
    (target / "licenses").mkdir()
    original = target / "licenses/original.txt"
    original.write_bytes(b"existing")
    with pytest.raises(tools.ToolSetupError) as exc:
        tools._publish_new_prefix(workspace, target)
    assert exc.value.code == "target_changed"
    assert (workspace / "env").is_dir()
    assert not (target / "env").exists()
    assert original.read_bytes() == b"existing"


def test_staged_publish_rejects_replaced_target_identity(tmp_path, portable_setup):
    workspace = tools._new_target(tmp_path / "stage")
    target = tools._new_target(tmp_path / "target")
    identity = target.stat().st_dev, target.stat().st_ino + 1
    with pytest.raises(tools.ToolSetupError) as exc:
        tools._publish_new_prefix(workspace, target, target_identity=identity)
    assert exc.value.code == "target_changed"
    assert not list(target.iterdir())


def sidecar_inputs(tmp_path):
    target = tmp_path / "tools"
    (target / "env/share/tessdata").mkdir(parents=True)
    (target / "licenses/tesseract/tesseract").mkdir(parents=True)
    (target / "licenses/tesseract/tesseract/LICENSE").write_bytes(b"synthetic license fixture")
    lock = {"critical_files": {}, "packages": [{"name": "tesseract", "license": "Apache-2.0"}]}
    for language in ("deu", "eng"):
        content = ("synthetic language fixture " + language).encode()
        (target / f"env/share/tessdata/{language}.traineddata").write_bytes(content)
        lock["critical_files"][f"share/tessdata/{language}.traineddata"] = {
            "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    return target, lock


def test_explicit_persistent_sidecar_keeps_original_models_and_unrelated_parent_data(tmp_path, portable_setup):
    target, lock = sidecar_inputs(tmp_path)
    parent = tmp_path / "persistent"
    parent.mkdir()
    sentinel = parent / "existing-language-data"
    sentinel.write_bytes(b"never touch")
    record = tools._tessdata_sidecar(target, parent, lock)
    path = tools._verify_sidecar(target, record)
    assert path.parent == parent and path != parent
    for language in ("deu", "eng"):
        assert (path / f"{language}.traineddata").read_bytes() == (target / f"env/share/tessdata/{language}.traineddata").read_bytes()
    assert sentinel.read_bytes() == b"never touch"
    assert set(record["files"]) == {"deu.traineddata", "eng.traineddata", "TESSERACT_LICENSE"}


def test_tampered_sidecar_is_refused_before_native_execution(tmp_path, portable_setup):
    target, lock = sidecar_inputs(tmp_path)
    record = tools._tessdata_sidecar(target, tmp_path, lock)
    (Path(record["path"]) / "eng.traineddata").write_bytes(b"corrupt replacement")
    with pytest.raises(tools.ToolSetupError) as exc:
        tools._verify_sidecar(target, record)
    assert exc.value.code == "tessdata_changed"


def test_failed_sidecar_copy_keeps_original_data_and_no_verified_marker(tmp_path, portable_setup):
    target, lock = sidecar_inputs(tmp_path)
    (target / "env/share/tessdata/eng.traineddata").write_bytes(b"corrupt source")
    parent = tmp_path / "persistent"
    parent.mkdir()
    sentinel = parent / "original.txt"
    sentinel.write_bytes(b"existing data")
    with pytest.raises(tools.ToolSetupError) as exc:
        tools._tessdata_sidecar(target, parent, lock)
    assert exc.value.code == "artifact_mismatch"
    assert sentinel.read_bytes() == b"existing data"
    stages = list(parent.glob("ocr-data-*"))
    assert len(stages) == 1
    assert not (stages[0] / "tessdata-source.json").exists()
    assert (target / "env/share/tessdata/deu.traineddata").exists()


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows ANSI native path/8.3 API")
def test_missing_short_alias_is_correctable_with_explicit_persistent_sidecar(tmp_path, monkeypatch, portable_setup):
    target, lock = sidecar_inputs(tmp_path)
    exotic = tmp_path / "日本"
    exotic.mkdir()
    monkeypatch.setattr(tools, "_windows_short_path", lambda path: None)
    with pytest.raises(tools.ToolSetupError) as exc:
        tools._native_tessdata_path(exotic)
    assert exc.value.code == "native_path_unrepresentable"
    assert "--tessdata-parent" in str(exc.value)
    sidecar = tools._tessdata_sidecar(target, tmp_path, lock)
    assert tools._native_tessdata_path(Path(sidecar["path"])) == sidecar["path"]


def test_exclusive_target_creation_has_single_winner(tmp_path, portable_setup):
    target = tmp_path / "same target"

    def create(_):
        try:
            tools._new_target(target)
            return True
        except (ValueError, FileExistsError):
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(create, range(2))) == [False, True]
    assert target.is_dir()


def test_changed_source_during_copy_is_rejected(tmp_path):
    source = tmp_path / "input.conda"
    source.write_bytes(b"untrusted replacement")
    expected = {"size": 4, "sha256": hashlib.sha256(b"good").hexdigest()}
    with pytest.raises(tools.ToolSetupError) as exc:
        tools._copy_verified(source, tmp_path / "owned-copy.conda", expected)
    assert exc.value.code == "artifact_mismatch"


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), True])
def test_invalid_time_budget(value):
    with pytest.raises(tools.ToolSetupError) as exc:
        tools._seconds(value)
    assert exc.value.code == "invalid_timeout"


def test_larger_positive_budget_is_not_arbitrarily_rejected():
    assert tools._seconds(86400) == 86400
    assert tools._memory(16384) == 16384 * 1024 * 1024


@pytest.mark.parametrize("relative", ["../outside", "/absolute", "C:/windows", "x\\y", "x\nnext"])
def test_manifest_paths_cannot_escape_target(relative):
    with pytest.raises(tools.ToolSetupError):
        tools._relative(relative)


def test_environment_contains_no_app_secrets_or_inherited_conda_config(tmp_path, monkeypatch):
    for name in ("DATABASE_URL", "JWT_SECRET_KEY", "ENCRYPTION_KEY", "CONDA_PREFIX", "HTTP_PROXY", "TESSDATA_PREFIX"):
        monkeypatch.setenv(name, "synthetic secret sentinel")
    env = tools._environment(tmp_path)
    assert "synthetic secret sentinel" not in json.dumps(env)
    assert all(name not in env for name in ("DATABASE_URL", "JWT_SECRET_KEY", "ENCRYPTION_KEY", "CONDA_PREFIX", "HTTP_PROXY", "TESSDATA_PREFIX"))
    assert env["TEMP"] == str(tmp_path / "temp")


def test_setup_import_does_not_load_application_configuration():
    result = subprocess.run([sys.executable, "-c", "import scripts.windows_ocr_tools,sys; assert 'backend.config' not in sys.modules"],
                            cwd=tools.ROOT, capture_output=True, timeout=15)
    assert result.returncode == 0


def test_redirect_cannot_change_pinned_download_origin():
    with pytest.raises(tools.ToolSetupError) as exc:
        tools._NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.example/payload")
    assert exc.value.code == "download_redirect"


@pytest.mark.parametrize("change", ["modify", "add", "remove"])
def test_verify_refuses_runtime_tamper_before_executing_any_native_tool(tmp_path, monkeypatch, portable_setup, change):
    target = tools._new_target(tmp_path / "tools")
    for directory in ("env", "licenses", "bootstrap"):
        (target / directory).mkdir()
    binary = target / "env/original.dll"
    binary.write_bytes(b"verified content")
    manifest = {"state": "verified", "lock_sha256": tools._hash(tools.LOCK_PATH),
                "configuration": tools._settings(target), "files": tools._seal_files(target)}
    tools._write(target / "ocr-toolchain.json", manifest)
    if change == "modify":
        binary.write_bytes(b"modified content")
    elif change == "add":
        (target / "env/injected.dll").write_bytes(b"extra content")
    else:
        binary.unlink()
    monkeypatch.setattr(tools, "_native_check", lambda *args: pytest.fail("must not execute changed tools"))
    with pytest.raises(tools.ToolSetupError) as exc:
        tools.verify(target)
    assert exc.value.code == "runtime_changed"


def test_failed_install_never_creates_success_marker(tmp_path, monkeypatch, portable_setup):
    cache, _ = small_lock(tmp_path, monkeypatch)
    monkeypatch.setattr(tools, "_bootstrap", lambda *args: (_ for _ in ()).throw(ValueError("synthetic failure")))
    target = tmp_path / "new install"
    with pytest.raises(ValueError, match="synthetic"):
        tools.install(cache, target)
    assert target.is_dir()
    assert not (target / "ocr-toolchain.json").exists()
    assert not (target / "env").exists()


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows job-owned setup subprocess")
def test_native_command_timeout_kills_process_and_cleans_own_diagnostic(tmp_path, monkeypatch):
    (tmp_path / "temp").mkdir()
    (tmp_path / "home").mkdir()
    marker = tmp_path / "started.txt"
    processes = []
    original_popen = tools.subprocess.Popen

    def capture_real_process(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(tools.subprocess, "Popen", capture_real_process)
    command = [sys.executable, "-c", f"from pathlib import Path;import time;Path({str(marker)!r}).write_text('started');time.sleep(60)"]
    with pytest.raises(tools.ToolSetupError) as exc:
        tools._command(command, tmp_path, 0.5)
    assert exc.value.code == "command_timeout"
    # Under a busy build host Python can still be starting at the deadline.
    # Observe the actual OS process exit, not an unrelated startup timing race.
    assert len(processes) == 1 and processes[0].poll() is not None
    assert not list(tmp_path.glob("command-output-*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows sanitized native process environment")
def test_native_command_receives_only_sanitized_environment(tmp_path, monkeypatch):
    (tmp_path / "temp").mkdir()
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("JWT_SECRET_KEY", "synthetic-secret-that-must-not-pass")
    output = tools._command([sys.executable, "-c", "import os;print(os.environ.get('JWT_SECRET_KEY','absent'))"], tmp_path, 10)
    assert output.strip() == "absent"
    assert not list(tmp_path.glob("command-output-*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows job-owned native command collision")
def test_existing_diagnostic_collision_never_deletes_or_overwrites_original(tmp_path, monkeypatch):
    class FixedUUID:
        hex = "fixed"

    original = tmp_path / "command-output-fixed.tmp"
    original.write_bytes(b"other running command or existing user data")
    monkeypatch.setattr(tools, "uuid4", FixedUUID)
    with pytest.raises(FileExistsError):
        tools._command([sys.executable, "-c", "print('never started')"], tmp_path, 10)
    assert original.read_bytes() == b"other running command or existing user data"


@pytest.mark.skipif(os.name != "nt", reason="Actual independent Windows native process jobs")
def test_parallel_native_commands_keep_independent_diagnostics(tmp_path):
    for directory in ("temp", "home"):
        (tmp_path / directory).mkdir()

    def run(index):
        return tools._command([sys.executable, "-c", f"print('worker-{index}')"], tmp_path, 15).strip()

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(run, range(2))) == ["worker-0", "worker-1"]
    assert not list(tmp_path.glob("command-output-*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows refusal to replace existing diagnostic data")
def test_legacy_fixed_diagnostic_name_is_preserved_during_native_command(tmp_path):
    for directory in ("temp", "home"):
        (tmp_path / directory).mkdir()
    original = tmp_path / "command-output.tmp"
    original.write_bytes(b"existing diagnosis must survive")
    output = tools._command([sys.executable, "-c", "print('independent new diagnostic')"], tmp_path, 15)
    assert output.strip() == "independent new diagnostic"
    assert original.read_bytes() == b"existing diagnosis must survive"
