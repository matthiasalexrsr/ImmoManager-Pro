"""Exercise the actual installer in a new owned folder, never an existing install.

Checks default and explicit launch modes, shortcuts, payload identity, repair,
running-app guard, and uninstall.
The caller may provide its isolated GUI smoke-test data to prove preservation.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

APP_ID = '{FE5C3565-4782-59C1-9EAC-E3FE6641E286}_is1'
MUTEX = r'Local\ImmoManagerPro.Desktop'
MODES = ('standalone', 'browser')


def digest(path):
    with native(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def native(path):
    text = str(path.absolute())
    if os.name != 'nt' or text.startswith('\\\\?\\'):
        return Path(text)
    return Path('\\\\?\\UNC\\' + text[2:] if text.startswith('\\\\') else '\\\\?\\' + text)


def inventory(folder):
    root = native(folder)
    return {str((Path(parent) / name).relative_to(root)).replace('\\', '/'): digest(Path(parent) / name)
            for parent, _, names in os.walk(root, followlinks=False) for name in names}


def registered():
    import winreg
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + APP_ID,
                               0, winreg.KEY_READ | view):
                return True
        except FileNotFoundError:
            pass
    return False


def owns_registration(target):
    import winreg
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + APP_ID,
                               0, winreg.KEY_READ | view) as key:
                location, _ = winreg.QueryValueEx(key, 'InstallLocation')
                if Path(location).resolve() == target.resolve():
                    return True
        except FileNotFoundError:
            pass
    return False


def owned_path(root, relative):
    path = (root / relative.replace('\\', '/')).resolve()
    if not path.is_relative_to(root) or path == root:
        raise AssertionError('Installer metadata escapes its installation directory')
    return path


def execute(command, log, *, required=True):
    result = subprocess.run([str(part) for part in command], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=600)
    log.write_bytes(result.stdout)
    if required and result.returncode != 0:
        raise AssertionError(f'Installer operation failed ({result.returncode}); see {log}')
    return result


def powershell_json(script, **environment):
    code = '[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$ErrorActionPreference="Stop";' + script
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code],
                            env={**os.environ, **environment}, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, encoding='utf-8-sig', check=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=30)
    return json.loads(result.stdout)


def known_shortcut_folders():
    values = powershell_json("@{Programs=[Environment]::GetFolderPath('Programs',[Environment+SpecialFolderOption]::DoNotVerify);"
                             "Desktop=[Environment]::GetFolderPath('DesktopDirectory',[Environment+SpecialFolderOption]::DoNotVerify)}|ConvertTo-Json -Compress")
    assert all(value and Path(value).is_absolute() for value in values.values()), 'Windows shortcut folders are unavailable'
    return {name: Path(value).resolve() for name, value in values.items()}


def require_shortcut_isolation(programs, group):
    # Refuse even an unregistered/pre-existing default folder. If an older
    # installer ignores /GROUP, it must never overwrite another user's links.
    for path in (programs / 'ImmoManager Pro', group):
        if os.path.lexists(path):
            raise SystemExit(f'A protected Start menu folder already exists; no installation started: {path}')


def shortcut_info(path):
    assert path.is_file(), f'Expected installer shortcut is missing: {path}'
    # The filename travels as data in an environment variable, never as code.
    return powershell_json('$link=(New-Object -ComObject WScript.Shell).CreateShortcut($env:IMMO_QA_SHORTCUT);'
                           '@{target=$link.TargetPath;arguments=$link.Arguments;working_directory=$link.WorkingDirectory}|ConvertTo-Json -Compress',
                           IMMO_QA_SHORTCUT=str(path))


def stored_launch_mode(target):
    import winreg
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + APP_ID,
                               0, winreg.KEY_READ | view) as key:
                location, _ = winreg.QueryValueEx(key, 'InstallLocation')
                assert Path(location).resolve() == target.resolve(), 'The registry now belongs to another installation'
                values = [winreg.EnumValue(key, index) for index in range(winreg.QueryInfoKey(key)[1])]
                modes = [(name, value) for name, value, _ in values if name.endswith('LaunchMode')]
                assert len(modes) == 1 and modes[0][1] in MODES, 'Installer launch-mode preference is missing or ambiguous'
                demo = [value for name, value, _ in values if name.endswith('FirstLaunchDemo')]
                assert len(demo) == 1 and demo[0] in ('0', '1'), 'Installer demo preference is missing or ambiguous'
                return {'registry_value': modes[0][0], 'mode': modes[0][1], 'demo_first_launch': demo[0] == '1'}
        except FileNotFoundError:
            pass
    raise AssertionError('Installer launch-mode preference is not registered')


def verify_mode_shortcuts(group, desktop, gui, mode, *, desktop_owned):
    expected = [(group / 'ImmoManager Pro.lnk', mode, False),
                (group / 'Startmöglichkeiten/Eigenständige Desktop-Anwendung.lnk', 'standalone', False),
                (group / 'Startmöglichkeiten/Im Webbrowser verwenden.lnk', 'browser', False),
                (group / 'Demo/Baden-Württemberg – Desktop.lnk', 'standalone', True),
                (group / 'Demo/Baden-Württemberg – Webbrowser.lnk', 'browser', True)]
    if desktop_owned:
        expected.append((desktop, mode, False))
    checked = []
    for path, selected, demo in expected:
        values = shortcut_info(path)
        assert Path(values['target']).resolve() == gui.resolve(), f'Wrong shortcut target: {path}'
        assert values['arguments'] == '--mode ' + selected + (' --demo' if demo else ''), f'Wrong shortcut mode: {path}'
        assert Path(values['working_directory']).resolve() == gui.parent.resolve()
        checked.append({'path': str(path), 'mode': selected, 'demo': demo, **values})
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path)
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise SystemExit('This is a native Windows installer test.')
    if registered():
        raise SystemExit('An existing ImmoManager Pro installation is registered; no changes made.')
    installer = args.installer.resolve(strict=True)
    source = args.dist.resolve(strict=True)
    work = args.work.resolve(strict=True)
    run = Path(tempfile.mkdtemp(prefix='immoqa-', dir=work))
    target = run / 'App Ä'
    folders = known_shortcut_folders()
    group_name = f'ImmoManager Pro QA {run.name}'
    group = folders['Programs'] / group_name
    require_shortcut_isolation(folders['Programs'], group)
    data = args.data_dir.resolve(strict=True) if args.data_dir else run / 'Benutzerdaten'
    if not data.is_relative_to(work) or data == work:
        raise SystemExit('Only explicitly isolated test data below the work folder is permitted.')
    data.mkdir(exist_ok=True)
    sentinel = data / 'installer-preservation-fixture.txt'
    sentinel.write_text('Isolated synthetic user data; preserve on repair and uninstall.\n', encoding='utf-8')
    before = inventory(data)
    desktop = folders['Desktop'] / 'ImmoManager Pro.lnk'
    desktop_owned = desktop.parent.is_dir() and not desktop.exists()
    desktop_before = digest(desktop) if desktop.is_file() else None
    result = {'status': 'failed', 'installer_sha256': digest(installer), 'run': str(run),
              'registered_installation_present_before': False, 'checks': {},
              'shortcut_group': str(group), 'desktop_shortcut_tested': desktop_owned,
              'desktop_shortcut_skipped_reason': None if desktop_owned else 'An existing user shortcut or an absent desktop folder is preserved'}
    base = [installer, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
            f'/DIR={target}', '/TASKS=desktopicon' if desktop_owned else '/TASKS=', f'/GROUP={group_name}']
    try:
        invalid = execute([*base, '/MODE=not-a-supported-mode', f'/LOG={run / "invalid-mode.log"}'],
                          run / 'invalid-mode-output.log', required=False)
        assert invalid.returncode != 0 and not target.exists() and not registered()
        assert not group.exists() and inventory(data) == before
        if desktop_before is not None:
            assert digest(desktop) == desktop_before
        elif desktop_owned:
            assert not desktop.exists()
        result['checks']['invalid_mode_rejected_before_writes'] = True
        invalid_demo = execute([*base, '/DEMO=invalid', f'/LOG={run / "invalid-demo.log"}'],
                               run / 'invalid-demo-output.log', required=False)
        assert invalid_demo.returncode != 0 and not target.exists() and not registered() and not group.exists()
        assert inventory(data) == before
        result['checks']['invalid_demo_choice_rejected_before_writes'] = True
        # An overly deep destination must fail before file copies or registration,
        # rather than rolling back halfway through the application's resources.
        long_target = run / ('long-destination-' + 'x' * 120)
        long_command = [arg for arg in base if not str(arg).startswith('/DIR=')]
        rejected = execute([*long_command, f'/DIR={long_target}', f'/LOG={run / "long-target.log"}'],
                           run / 'long-target-output.log', required=False)
        assert rejected.returncode != 0 and not long_target.exists() and not registered()
        result['checks']['long_destination_rejected_before_writes'] = True
        execute([*base, f'/LOG={run / "install.log"}'], run / 'install-output.log')
        manifest = json.loads((target / 'installation.json').read_text(encoding='utf-8-sig'))
        gui = owned_path(target, manifest['gui_executable'])
        cli = owned_path(target, manifest['cli_executable'])
        assert gui.is_file() and cli.is_file()
        assert manifest['launch_modes'] == list(MODES) and manifest['default_launch_mode'] == 'standalone'
        payload = gui.parent
        expected = inventory(source)
        assert len(expected) == len(manifest['files']), 'The complete inventory was not enumerated'
        assert inventory(payload) == expected, 'Installed payload differs from the actual build'
        import pefile
        with pefile.PE(str(gui), fast_load=True) as pe:
            assert pe.OPTIONAL_HEADER.Subsystem == 2, 'Main program is not a windowed executable'
        with pefile.PE(str(cli), fast_load=True) as pe:
            assert pe.OPTIONAL_HEADER.Subsystem == 3, 'Administrative CLI subsystem changed'
        result['checks']['payload_identity_and_subsystems'] = len(expected)
        assert registered(), 'Installed program has no uninstall registration'
        assert stored_launch_mode(target)['mode'] == 'standalone'
        assert stored_launch_mode(target)['demo_first_launch'] is False
        result['checks']['default_standalone_install_shortcuts'] = verify_mode_shortcuts(group, desktop, gui, 'standalone', desktop_owned=desktop_owned)
        unknown = target / 'unrelated-user-file.txt'
        unknown.write_text('Not owned by the installer.\n', encoding='utf-8')
        unknown_hash = digest(unknown)
        execute([*base, '/MODE=standalone', f'/LOG={run / "mode-standalone.log"}'], run / 'mode-standalone-output.log')
        assert stored_launch_mode(target)['mode'] == 'standalone'
        result['checks']['explicit_standalone_install_shortcuts'] = verify_mode_shortcuts(group, desktop, gui, 'standalone', desktop_owned=desktop_owned)
        assert inventory(data) == before and digest(unknown) == unknown_hash
        execute([*base, '/MODE=browser', '/DEMO=1', f'/LOG={run / "mode-browser.log"}'], run / 'mode-browser-output.log')
        assert stored_launch_mode(target)['mode'] == 'browser'
        assert stored_launch_mode(target)['demo_first_launch'] is True
        result['checks']['browser_install_shortcuts'] = verify_mode_shortcuts(group, desktop, gui, 'browser', desktop_owned=desktop_owned)
        assert inventory(data) == before and digest(unknown) == unknown_hash
        invalid_update = execute([*base, '/MODE=invalid', f'/LOG={run / "invalid-update-mode.log"}'],
                                 run / 'invalid-update-mode-output.log', required=False)
        assert invalid_update.returncode != 0 and stored_launch_mode(target)['mode'] == 'browser'
        verify_mode_shortcuts(group, desktop, gui, 'browser', desktop_owned=desktop_owned)
        assert inventory(data) == before
        result['checks']['aborted_mode_update_preserves_selection_and_data'] = True
        execute([*base, f'/LOG={run / "repair.log"}'], run / 'repair-output.log')
        assert stored_launch_mode(target)['mode'] == 'browser'
        assert stored_launch_mode(target)['demo_first_launch'] is True
        result['checks']['mode_preserved_without_command_line_override'] = verify_mode_shortcuts(group, desktop, gui, 'browser', desktop_owned=desktop_owned)
        assert digest(unknown) == unknown_hash and inventory(data) == before
        assert inventory(gui.parent) == expected, 'Repair changed the payload'
        result['checks']['repair_preserves_data_and_unknown_files'] = True
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        ctypes.set_last_error(0)
        handle = kernel.CreateMutexW(None, False, MUTEX)
        if not handle or ctypes.get_last_error() == 183:
            if handle:
                kernel.CloseHandle(handle)
            raise AssertionError('A real desktop app is active; the test will not stop it')
        try:
            blocked = execute([*base, f'/LOG={run / "blocked.log"}'],
                              run / 'blocked-output.log', required=False)
            assert blocked.returncode != 0, 'Installer ignored the running-application mutex'
            assert inventory(data) == before
        finally:
            kernel.CloseHandle(handle)
        result['checks']['running_application_guard'] = True
        help_result = execute([cli, '--data-dir', data, '--help'], run / 'cli-help.log')
        assert b'--data-dir' in help_result.stdout
        result['checks']['hidden_cli_output_and_exit_code'] = True
        # Running an administrative command may append its own startup log.
        # Uninstall must preserve that new, quiescent data state as well.
        before = inventory(data)
        uninstallers = list(target.glob('unins*.exe'))
        assert len(uninstallers) == 1
        execute([uninstallers[0], '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                 f'/LOG={run / "uninstall.log"}'], run / 'uninstall-output.log')
        assert not gui.exists() and not cli.exists() and not registered()
        assert not group.exists(), 'Installer left its isolated shortcut group'
        if desktop_owned:
            assert not desktop.exists(), 'Installer left the desktop shortcut it created'
        elif desktop_before is not None:
            assert digest(desktop) == desktop_before, 'Installer changed an existing user desktop shortcut'
        remaining_owned = [name for name in expected if native(payload / name).exists()]
        assert not remaining_owned, f'Uninstall left owned payload files: {remaining_owned[:5]}'
        assert unknown.is_file() and digest(unknown) == unknown_hash
        assert inventory(data) == before
        result['checks']['all_owned_payload_files_removed'] = len(expected)
        result['checks']['uninstall_preserves_data_and_unknown_files'] = True
        result['status'] = 'passed'
    finally:
        if result['status'] != 'passed' and owns_registration(target):
            # Recover only this new fixture's registered installation. Never
            # delete a tree or invoke another installation's uninstaller.
            try:
                marker = target / '.immomanager-installation-id'
                if marker.read_text(encoding='ascii').strip() == APP_ID.removesuffix('_is1').strip('{}'):
                    cleanup = list(target.glob('unins*.exe'))
                    if len(cleanup) == 1 and cleanup[0].resolve().is_relative_to(target.resolve()):
                        execute([cleanup[0], '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'],
                                run / 'failure-cleanup.log')
                        result['failure_cleanup_completed'] = not registered()
            except (OSError, ValueError, AssertionError, subprocess.SubprocessError) as exc:
                result['failure_cleanup_error'] = str(exc)
        result['registered_installation_present_after'] = registered()
        (run / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
