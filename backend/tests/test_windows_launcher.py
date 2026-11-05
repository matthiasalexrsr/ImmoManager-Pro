import json
import os
import runpy
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from backend import __main__ as launcher
from backend import runtime_origins
from scripts import install_desktop_dependencies as desktop_dependencies


def test_sqlite_url_uses_absolute_forward_slashes(tmp_path):
    db_path = tmp_path / "immo_manager.db"

    url = launcher._sqlite_url(str(db_path))

    assert url.startswith("sqlite:///")
    assert "\\" not in url


def test_configure_runtime_environment_creates_persistent_defaults(tmp_path, monkeypatch):
    for key in [
        "DATA_DIR",
        "UPLOADS_DIR",
        "BACKUP_DIR",
        "DATABASE_URL",
        "LOG_FILE",
        "INTEGRATION_STATE_FILE",
        "ALLOW_INMEMORY_FALLBACK",
        "SQLITE_PERSISTENT_STORE",
        "JWT_SECRET_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(launcher, "IS_FROZEN", False)

    data_dir = launcher._configure_runtime_environment(str(tmp_path))

    assert data_dir == os.path.abspath(str(tmp_path))
    assert (tmp_path / "uploads").is_dir()
    assert (tmp_path / "backups").is_dir()
    assert (tmp_path / "logs").is_dir()
    assert os.environ["DATABASE_URL"].startswith("sqlite:///")
    assert os.environ["JWT_SECRET_KEY"] != "dev-secret-key-change-in-production"
    assert (tmp_path / ".env").is_file()


def test_packageless_frozen_entry_reloads_existing_config_and_keeps_explicit_overrides(tmp_path, monkeypatch):
    # Frozen executables run this source as a script, so importing it as
    # backend.__main__ would miss relative-import failures on the second start.
    namespace = runpy.run_path(str(Path(launcher.__file__)), run_name='frozen_launcher_probe')
    configure = namespace['_configure_runtime_environment']
    assert not configure.__globals__['__package__']
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    monkeypatch.setitem(configure.__globals__, 'IS_FROZEN', True)
    monkeypatch.setitem(configure.__globals__, '_exe_dir', lambda: str(bundle))
    monkeypatch.setattr(runtime_origins, 'ENV_FILE_ORIGINS', {})
    keys = ('DATA_DIR', 'UPLOADS_DIR', 'BACKUP_DIR', 'DATABASE_URL', 'LOG_FILE', 'INTEGRATION_STATE_FILE',
            'ALLOW_INMEMORY_FALLBACK', 'SQLITE_PERSISTENT_STORE', 'JWT_SECRET_KEY', 'CORS_ORIGINS',
            'ENVIRONMENT', 'CONTRACT_WIZARD_REQUIRED')
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('IMMO_TESTVERSION', 'false')
    directory = tmp_path / 'Bestand mit Umlaut Ä'
    configure(str(directory))
    original_key = os.environ['JWT_SECRET_KEY']
    original_database = os.environ['DATABASE_URL']
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    explicit_log = str(tmp_path / 'explicit.log')
    monkeypatch.setenv('LOG_FILE', explicit_log)
    assert configure(str(directory)) == str(directory.resolve())
    assert os.environ['JWT_SECRET_KEY'] == original_key
    assert os.environ['DATABASE_URL'] == original_database
    assert os.environ['LOG_FILE'] == explicit_log
    assert runtime_origins.ENV_FILE_ORIGINS['jwt_secret_key'] == str((directory / '.env').resolve())


def _standalone_cli(tmp_path, *arguments):
    # Execute the actual guard without a parent package. Its project and runtime
    # files belong only to this fixture, even when the caller has a real .env.
    script = tmp_path / 'bundle/backend/__main__.py'
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_bytes(Path(launcher.__file__).read_bytes())
    data = tmp_path / 'data'
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'}}
    environment.update(PYTHONPATH=str(Path(launcher.__file__).resolve().parents[1]),
        DATA_DIR=str(data), DATABASE_URL=f'sqlite:///{(data / "app.db").as_posix()}',
        JWT_SECRET_KEY='synthetic-cli-only-key-not-a-user-secret', ENVIRONMENT='development')
    return subprocess.run([sys.executable, str(script), '--data-dir', str(data), '--no-browser', '--no-upgrade',
                           *arguments], cwd=tmp_path, env=environment, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=30,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def test_standalone_cli_reports_occupied_port_as_failure(tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        result = _standalone_cli(tmp_path, '--port', str(listener.getsockname()[1]))
    assert 'bereits belegt' in result.stdout
    assert result.returncode == 1


def test_standalone_cli_reports_unreadable_configuration_as_failure(tmp_path):
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    (bundle / '.env').write_bytes(b'BROKEN=\xff\xfe')
    result = _standalone_cli(tmp_path)
    assert 'Unerwarteter Fehler' in result.stdout
    assert result.returncode == 1


def test_desktop_versions_require_every_exact_pin_without_importing_qt(tmp_path, monkeypatch):
    requirements = tmp_path / 'requirements-desktop.txt'
    requirements.write_text('# pinned native engine\nPySide6==6.11.3\nshiboken6==6.11.3\n', encoding='utf-8')
    versions = {'PySide6': '6.11.3', 'shiboken6': '6.11.3'}
    monkeypatch.setattr(desktop_dependencies.metadata, 'version', lambda name: versions[name])
    assert desktop_dependencies.versions_current(tmp_path)
    versions['shiboken6'] = '6.12.0'
    assert not desktop_dependencies.versions_current(tmp_path)
    requirements.write_text('PySide6>=6.11.3\n', encoding='utf-8')
    with pytest.raises(ValueError, match='versioniert'):
        desktop_dependencies.pinned_versions(tmp_path)


def test_missing_desktop_distribution_requires_repair(tmp_path, monkeypatch):
    (tmp_path / 'requirements-desktop.txt').write_text('PySide6==6.11.3\n', encoding='utf-8')
    def missing(_):
        raise desktop_dependencies.metadata.PackageNotFoundError('PySide6')
    monkeypatch.setattr(desktop_dependencies.metadata, 'version', missing)
    assert not desktop_dependencies.versions_current(tmp_path)


def test_desktop_install_helper_rejects_a_non_venv_before_creating_any_alias(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'prefix', str(tmp_path))
    with pytest.raises(RuntimeError, match='virtuellen'):
        with desktop_dependencies.pip_python():
            pytest.fail('A global Python must not be selected for desktop installation')
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name != 'nt', reason='Real Windows junction cleanup')
def test_missing_venv_python_cleans_only_its_temporary_alias(tmp_path, monkeypatch):
    venv, home = tmp_path / 'Venv', tmp_path / 'Home'
    venv.mkdir()
    home.mkdir()
    (venv / 'pyvenv.cfg').write_text('synthetic venv without its interpreter\n', encoding='utf-8')
    monkeypatch.setattr(sys, 'prefix', str(venv))
    monkeypatch.setattr(Path, 'home', lambda: home)
    with pytest.raises(FileNotFoundError, match='Python-Starter'):
        with desktop_dependencies.pip_python():
            pytest.fail('A missing interpreter must not be invoked')
    assert list(home.iterdir()) == [] and (venv / 'pyvenv.cfg').is_file()


@pytest.mark.skipif(os.name != 'nt', reason='Real Windows junction cleanup')
@pytest.mark.parametrize('pip_fails', [False, True])
def test_desktop_pip_uses_short_owned_alias_and_preserves_venv_after_success_or_failure(tmp_path, monkeypatch, pip_fails):
    root, home, venv = tmp_path / 'Project Ä', tmp_path / 'Home', tmp_path / 'Actual environment Ä'
    root.mkdir()
    home.mkdir()
    (venv / 'Scripts').mkdir(parents=True)
    (venv / 'pyvenv.cfg').write_text('synthetic isolated venv\n', encoding='utf-8')
    python = venv / 'Scripts/python.exe'
    python.write_bytes(b'synthetic fixture; never executed')
    sentinel = venv / 'preserve-me.txt'
    sentinel.write_text('original venv content\n', encoding='utf-8')
    (root / 'requirements-desktop.txt').write_text('PySide6==6.11.3\n', encoding='utf-8')
    (root / 'constraints.txt').write_text('# isolated requirement fixture\n', encoding='utf-8')
    monkeypatch.setattr(sys, 'prefix', str(venv))
    monkeypatch.setattr(Path, 'home', lambda: home)
    aliases = []
    def run(command, **options):
        short_python = Path(command[0])
        aliases.append(short_python.parent.parent)
        assert short_python.resolve() == python.resolve()
        assert short_python.parent.parent.parent.parent == home
        assert command[1:] == ['-m', 'pip', 'install', '-r', str(root / 'requirements-desktop.txt'), '-c', str(root / 'constraints.txt')]
        assert options == {'check': True, 'stdin': subprocess.DEVNULL,
                           'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}
        if pip_fails:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(desktop_dependencies.subprocess, 'run', run)
    if pip_fails:
        with pytest.raises(subprocess.CalledProcessError):
            desktop_dependencies.install(root)
    else:
        desktop_dependencies.install(root)
    assert aliases and all(not alias.exists() for alias in aliases)
    assert list(home.iterdir()) == []
    assert sentinel.read_text(encoding='utf-8') == 'original venv content\n'
    assert python.read_bytes() == b'synthetic fixture; never executed'


@pytest.mark.skipif(shutil.which('powershell.exe') is None, reason='Native PowerShell launcher contracts')
def test_source_windows_starter_routes_modes_and_refreshes_dependency_stamps_without_starting_ui(tmp_path):
    root = Path(__file__).resolve().parents[2]
    stamp, changed = tmp_path / 'desktop.stamp', tmp_path / 'requirements-desktop.txt'
    script = r'''
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($env:IMMO_START_SOURCE,[ref]$tokens,[ref]$errors)
if($errors){throw ($errors|Out-String)}
$wanted=@('Get-BackendArguments','Test-DesktopDependenciesRequired','Test-DependencyInstallNeeded','Quote-ProcessArgument')
foreach($function in $ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst]},$true)) {
    if($function.Name -in $wanted){Invoke-Expression $function.Extent.Text}
}
# Evaluate only the real parameter declaration and pure helpers. The launcher's
# install/build/start statements are deliberately never executed.
$parameterProbe=[scriptblock]::Create($ast.ParamBlock.Extent.Text + '; $Mode')
$default=& $parameterProbe
$invalidRejected=$false
try { & $parameterProbe -Mode invalid } catch { $invalidRejected=$true }
$cases=@()
foreach($console in @($false,$true)) {
    foreach($mode in @('standalone','browser')) {
        $arguments=@(Get-BackendArguments -Port 9000 -DataDir 'C:\Daten Ä\Ordner mit Leerzeichen\' -Console:$console -Mode $mode -Seed -NoBrowser)
        $cases+=@{console=$console;mode=$mode;arguments=$arguments;needs_qt=(Test-DesktopDependenciesRequired -Console:$console -Mode $mode)}
    }
}
$stamp=$env:IMMO_START_STAMP;$changed=$env:IMMO_START_CHANGED
Set-Content -LiteralPath $changed -Value 'synthetic exact Qt requirements'
$missing=Test-DependencyInstallNeeded -Stamp $stamp -Files @($changed)
Set-Content -LiteralPath $stamp -Value 'successful previous installation'
(Get-Item -LiteralPath $stamp).LastWriteTimeUtc=[datetime]::UtcNow.AddMinutes(1)
$unchanged=Test-DependencyInstallNeeded -Stamp $stamp -Files @($changed)
(Get-Item -LiteralPath $changed).LastWriteTimeUtc=[datetime]::UtcNow.AddMinutes(2)
$updated=Test-DependencyInstallNeeded -Stamp $stamp -Files @($changed)
@{default=$default;invalid_rejected=$invalidRejected;cases=$cases;missing=$missing;unchanged=$unchanged;updated=$updated;
  uppercase_arguments=@(Get-BackendArguments -Port 9000 -DataDir 'C:\Daten Ä' -Mode 'Browser');
  demo_arguments=@(Get-BackendArguments -Port 8766 -DataDir 'C:\Demo Ä' -Mode standalone -Demo);
  demo_console_arguments=@(Get-BackendArguments -Port 8766 -DataDir 'C:\Demo Ä' -Console -Demo);
  quoted=Quote-ProcessArgument 'C:\Daten Ä\Ordner mit Leerzeichen\'} | ConvertTo-Json -Depth 6 -Compress
'''
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                             '[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);' + script],
        env={**os.environ, 'IMMO_START_SOURCE': str(root / 'scripts/start_windows.ps1'),
             'IMMO_START_STAMP': str(stamp), 'IMMO_START_CHANGED': str(changed)},
        capture_output=True, text=True, encoding='utf-8-sig', stdin=subprocess.DEVNULL, timeout=30,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['default'] == 'standalone' and value['invalid_rejected']
    assert value['missing'] and not value['unchanged'] and value['updated']
    for case in value['cases']:
        arguments = case['arguments']
        assert arguments[1] == ('backend' if case['console'] else 'backend.desktop_entry')
        assert case['needs_qt'] == (not case['console'] and case['mode'] == 'standalone')
        assert arguments[arguments.index('--data-dir') + 1] == 'C:\\Daten Ä\\Ordner mit Leerzeichen\\'
        assert arguments[-2:] == ['--seed', '--no-browser']
        if case['console']:
            assert '--mode' not in arguments
        else:
            assert arguments[arguments.index('--mode') + 1] == case['mode']
    assert value['uppercase_arguments'][-2:] == ['--mode', 'browser']
    assert value['demo_arguments'][-3:] == ['--mode', 'standalone', '--demo']
    assert '--demo' in value['demo_console_arguments'] and '--mode' not in value['demo_console_arguments']
    assert value['quoted'] == '"C:\\Daten Ä\\Ordner mit Leerzeichen\\\\"'
