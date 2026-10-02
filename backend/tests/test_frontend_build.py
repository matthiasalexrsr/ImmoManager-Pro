"""Frontend freshness, failure preservation and Windows launcher contracts."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from backend import frontend_build as build


@pytest.fixture
def project(tmp_path):
    frontend = tmp_path / "frontend"
    (frontend / "src").mkdir(parents=True)
    (frontend / "public").mkdir()
    (tmp_path / "i18n").mkdir()
    for path, content in {
        frontend / "src" / "App.jsx": "export default () => <p>Application</p>",
        frontend / "public" / "icon.svg": "<svg></svg>",
        frontend / "index.html": '<script src="/src/main.jsx" type="module"></script>',
        frontend / "package.json": '{"scripts":{"build":"vite build"}}',
        frontend / "package-lock.json": '{"lockfileVersion":3}',
        frontend / "vite.config.js": 'export default {}',
        tmp_path / "i18n" / "de-DE.json": '{"hello":"Hallo"}',
    }.items():
        path.write_text(content, encoding="utf-8")
    return tmp_path


def write_dist(dist, marker="valid UI"):
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    (dist / "assets" / "app.js").write_text(f'console.log({json.dumps(marker)})', encoding="utf-8")
    (dist / "assets" / "app.css").write_text('body { color: black; }', encoding="utf-8")
    (dist / "index.html").write_text('<link rel="stylesheet" href="/assets/app.css"><script type="module" src="/assets/app.js"></script>', encoding="utf-8")


def fake_npm(monkeypatch, *, install_code=0, build_code=0, mutate=None, invalid_output=False):
    calls = []
    monkeypatch.setattr(build.shutil, "which", lambda executable: "npm.cmd" if os.name == "nt" else "npm")
    def run(command, **kwargs):
        calls.append(command)
        if "--outDir" in command:
            staged = Path(command[command.index("--outDir") + 1])
            if not invalid_output:
                write_dist(staged, "new UI")
            if mutate:
                mutate()
            return subprocess.CompletedProcess(command, build_code, stdout="", stderr="build failed" if build_code else "")
        return subprocess.CompletedProcess(command, install_code, stdout="", stderr="npm failed" if install_code else "")
    monkeypatch.setattr(build.subprocess, "run", run)
    return calls


def test_successful_build_is_staged_and_next_offline_restart_needs_no_npm(project, monkeypatch):
    calls = fake_npm(monkeypatch)
    assert "erfolgreich" in build.ensure_frontend(project)
    assert calls[0][1] == "ci" and "--include=dev" in calls[0]
    assert "--outDir" in calls[1] and "--emptyOutDir" in calls[1]
    assert build.is_fresh(project)
    assert list((project / "frontend").glob(".immomanager-*")) == []
    monkeypatch.setattr(build.shutil, "which", lambda executable: None)
    assert "aktuell" in build.ensure_frontend(project)
    assert len(calls) == 2


@pytest.mark.parametrize("path", ["frontend/src/App.jsx", "frontend/public/icon.svg", "frontend/package.json", "frontend/package-lock.json", "frontend/vite.config.js", "i18n/de-DE.json"])
def test_content_changes_trigger_build_despite_unchanged_mtime(project, monkeypatch, path):
    fake_npm(monkeypatch)
    build.ensure_frontend(project)
    changed = project / path
    original_time = changed.stat().st_mtime_ns
    changed.write_text(changed.read_text(encoding="utf-8") + " ", encoding="utf-8")
    os.utime(changed, ns=(original_time, original_time))
    assert not build.is_fresh(project)


def test_new_config_and_deleted_source_are_fingerprinted(project, monkeypatch):
    fake_npm(monkeypatch)
    build.ensure_frontend(project)
    (project / "frontend" / ".env.production").write_text("VITE_LABEL=demo", encoding="utf-8")
    assert not build.is_fresh(project)
    build.ensure_frontend(project)
    (project / "frontend" / "src" / "App.jsx").unlink()
    assert not build.is_fresh(project)


@pytest.mark.parametrize("step", ["install", "build", "invalid output", "changed source"])
def test_failed_build_preserves_previous_assets_and_cleans_owned_staging(project, monkeypatch, step):
    dist = project / "frontend" / "dist"
    write_dist(dist, "previous UI")
    previous = {path.relative_to(dist): path.read_bytes() for path in dist.rglob("*") if path.is_file()}
    fake_npm(monkeypatch, install_code=1 if step == "install" else 0, build_code=1 if step == "build" else 0,
             invalid_output=step == "invalid output",
             mutate=(lambda: (project / "frontend" / "src" / "App.jsx").write_text("changed", encoding="utf-8")) if step == "changed source" else None)
    with pytest.raises(build.FrontendBuildError):
        build.ensure_frontend(project)
    assert {path.relative_to(dist): path.read_bytes() for path in dist.rglob("*") if path.is_file()} == previous
    assert list((project / "frontend").glob(".immomanager-*")) == []


def test_missing_npm_is_a_failure_for_stale_assets(project, monkeypatch):
    write_dist(project / "frontend" / "dist")
    monkeypatch.setattr(build.shutil, "which", lambda executable: None)
    with pytest.raises(build.FrontendBuildError, match="Node.js/npm fehlt"):
        build.ensure_frontend(project)
    assert "geprüft" in build.ensure_frontend(project, skip_build=True)


@pytest.mark.parametrize("invalid", ["missing", "empty index", "missing asset", "empty asset", "traversal", "no script", "checksum"])
def test_skip_build_requires_complete_untampered_prebuilt_assets(project, monkeypatch, invalid):
    dist = project / "frontend" / "dist"
    if invalid != "missing":
        write_dist(dist)
    if invalid == "empty index":
        (dist / "index.html").write_text("")
    elif invalid == "missing asset":
        (dist / "assets" / "app.js").unlink()
    elif invalid == "empty asset":
        (dist / "assets" / "app.js").write_text("")
    elif invalid == "traversal":
        (project / "outside.js").write_text("secret")
        (dist / "index.html").write_text('<script src="../../outside.js"></script>')
    elif invalid == "no script":
        (dist / "index.html").write_text("<h1>placeholder</h1>")
    elif invalid == "checksum":
        fake_npm(monkeypatch)
        build.ensure_frontend(project)
        (dist / "assets" / "app.js").write_text("corrupted")
    with pytest.raises(build.FrontendBuildError):
        build.ensure_frontend(project, skip_build=True)


def test_promotion_failure_restores_previous_dist(project, monkeypatch):
    dist = project / "frontend" / "dist"
    write_dist(dist, "original")
    fake_npm(monkeypatch)
    original_rename = Path.rename
    def rename(source, destination):
        if source.name.startswith(".immomanager-build-"):
            raise OSError("simulated locked directory")
        return original_rename(source, destination)
    monkeypatch.setattr(Path, "rename", rename)
    with pytest.raises(OSError):
        build.ensure_frontend(project)
    assert "original" in (dist / "assets" / "app.js").read_text()
    build.validate_dist(dist)


def test_unsafe_cleanup_path_is_rejected(project):
    external = project / "user-data"
    external.mkdir()
    (external / "keep.txt").write_text("keep")
    with pytest.raises(build.FrontendBuildError):
        build._remove_owned(external, project / "frontend")
    assert (external / "keep.txt").read_text() == "keep"


def test_concurrent_build_lock_cannot_be_stolen(project, monkeypatch):
    fake_npm(monkeypatch)
    lock = project / "frontend" / ".immomanager-build.lock"
    lock.write_text("existing owner")
    with pytest.raises(build.FrontendBuildError, match="läuft bereits"):
        build.ensure_frontend(project)
    assert lock.read_text() == "existing owner"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell launcher runs on Windows")
def test_windows_checked_command_surfaces_first_failed_exit_without_running_next_step(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts" / "start_windows.ps1"
    command = r'''$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($env:TEST_LAUNCHER, [ref]$null, [ref]$errors)
if ($errors.Count) { throw 'Invalid PowerShell syntax' }
$helper = $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-CheckedCommand'}, $true)[0]
Invoke-Expression $helper.Extent.Text
function fail-command { $global:LASTEXITCODE = 19 }
try { Invoke-CheckedCommand 'fail-command' @() 'venv failed'; throw 'Failure was ignored' }
catch { if ($_.Exception.Message -notlike 'venv failed*Exit 19*') { throw }; Write-Output 'failed step surfaced' }
'''
    completed = subprocess.run([shutil.which("powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", command],
                               env={**os.environ, "TEST_LAUNCHER": str(script)}, text=True, capture_output=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert "failed step surfaced" in completed.stdout


@pytest.mark.skipif(os.name != "nt", reason="PowerShell launcher runs on Windows")
def test_windows_dependency_fingerprint_uses_content_and_detects_python_failure(tmp_path):
    for name in ("pyproject.toml", "requirements.txt", "backend/requirements.txt"):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("old")
    script = Path(__file__).resolve().parents[2] / "scripts" / "start_windows.ps1"
    command = r'''$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($env:TEST_LAUNCHER, [ref]$null, [ref]$errors)
$helper = $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-DependencyFingerprint'}, $true)[0]
Invoke-Expression $helper.Extent.Text
$first = Get-DependencyFingerprint $env:TEST_PROJECT $env:TEST_PYTHON
$file = Join-Path $env:TEST_PROJECT 'requirements.txt'
$time = (Get-Item -LiteralPath $file).LastWriteTimeUtc
Set-Content -LiteralPath $file -Value 'new' -Encoding UTF8
(Get-Item -LiteralPath $file).LastWriteTimeUtc = $time
$second = Get-DependencyFingerprint $env:TEST_PROJECT $env:TEST_PYTHON
if ($first -eq $second) { throw 'Content edit ignored' }
function fail-python { $global:LASTEXITCODE = 9 }
try { Get-DependencyFingerprint $env:TEST_PROJECT 'fail-python'; throw 'Python failure was ignored' }
catch { if ($_.Exception.Message -notlike '*Python*geprueft*') { throw } }
Write-Output 'content fingerprint verified'
'''
    completed = subprocess.run([shutil.which("powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", command],
                               env={**os.environ, "TEST_LAUNCHER": str(script), "TEST_PROJECT": str(tmp_path), "TEST_PYTHON": sys.executable},
                               text=True, capture_output=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert "content fingerprint verified" in completed.stdout
