"""Portable bootstrap contracts; foreign-platform boundaries are simulations."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import __main__ as launcher
from backend import desktop_control, paths, platform_paths
from backend.services.runtime_process import frozen_cli_executable


@pytest.mark.parametrize("platform,suffix", [
    ("win32", "AppData/Local/ImmoManagerPro"),
    ("darwin", "Library/Application Support/ImmoManagerPro"),
    ("linux", ".local/share/ImmoManagerPro"),
])
def test_native_defaults_are_home_based_and_test_data_stays_separate(tmp_path, platform, suffix):
    expected = tmp_path.joinpath(*suffix.split("/"))
    assert platform_paths.default_user_data_dir(platform=platform, environ={}, home=tmp_path) == expected
    assert platform_paths.default_user_data_dir(platform=platform, environ={}, home=tmp_path, testversion=True) == expected.with_name("ImmoManagerPro-Testversion")


def test_relative_environment_defaults_do_not_write_below_a_launching_cwd(tmp_path):
    assert platform_paths.default_user_data_dir(platform="linux", environ={"XDG_DATA_HOME": "relative/cache"}, home=tmp_path) == tmp_path / ".local/share/ImmoManagerPro"
    assert platform_paths.default_user_data_dir(platform="win32", environ={"LOCALAPPDATA": "relative"}, home=tmp_path) == tmp_path / "AppData/Local/ImmoManagerPro"
    assert platform_paths.default_user_data_dir(platform="darwin", environ={"XDG_DATA_HOME": "/ignored"}, home=tmp_path) == tmp_path / "Library/Application Support/ImmoManagerPro"
    assert platform_paths.default_user_data_dir(platform="linux", environ={"XDG_DATA_HOME": "/private/data"}, home=tmp_path) == Path("/private/data") / "ImmoManagerPro"
    assert platform_paths.default_user_data_dir(platform="win32", environ={"LOCALAPPDATA": "C:/Local Data"}, home=tmp_path) == Path("C:/Local Data/ImmoManagerPro")


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_cli_and_backend_share_the_same_native_default(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(platform_paths, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(platform_paths.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert Path(launcher._default_data_dir()) == paths._default_user_data_dir()


def test_data_dir_cli_choice_wins_over_process_and_copied_runtime_env(tmp_path):
    chosen, other = tmp_path / "Chosen data Ä", tmp_path / "Other data"
    chosen.mkdir()
    (chosen / ".env").write_text("DATA_DIR=" + str(other) + "\n", encoding="utf-8")
    root = Path(__file__).resolve().parents[2]
    env = {key: value for key, value in os.environ.items() if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"}}
    env.update(DATA_DIR=str(other), PYTHONPATH=str(root), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    program = (
        "from backend.__main__ import _configure_runtime_environment; import sys,json; "
        "selected=_configure_runtime_environment(sys.argv[1]); "
        "from backend.paths import get_data_dir; "
        "print(json.dumps({'selected':selected,'actual':str(get_data_dir())}))"
    )
    result = subprocess.run([sys.executable, "-c", program, str(chosen)], cwd=tmp_path, env=env,
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout.splitlines()[-1])
    assert Path(value["selected"]) == Path(value["actual"]) == chosen.resolve()
    assert not other.exists()
    assert not (tmp_path / "immo_manager.db").exists()


@pytest.mark.parametrize("choice", ["environment", "project-env", "native-default"])
def test_data_dir_remaining_precedence_is_consistent_in_a_fresh_cli(tmp_path, choice):
    project, native, environment, configured = [tmp_path / name for name in ("project", "native", "environment", "configured")]
    project.mkdir()
    if choice != "native-default":
        (project / ".env").write_text("DATA_DIR=" + str(configured) + "\n", encoding="utf-8")
    selected = {"environment": environment, "project-env": configured, "native-default": native}[choice]
    root = Path(__file__).resolve().parents[2]
    env = {key: value for key, value in os.environ.items() if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"}}
    env.update(PYTHONPATH=str(root), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    if choice == "environment":
        env["DATA_DIR"] = str(environment)
    program = (
        "import sys,json; from backend import __main__ as launcher; "
        "launcher._exe_dir=lambda:sys.argv[1]; launcher._default_data_dir=lambda **kwargs:sys.argv[2]; "
        "selected=launcher._configure_runtime_environment(); from backend.paths import get_data_dir; "
        "print(json.dumps({'selected':selected,'actual':str(get_data_dir())}))"
    )
    result = subprocess.run([sys.executable, "-c", program, str(project), str(native)], cwd=tmp_path, env=env,
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout.splitlines()[-1])
    assert Path(value["selected"]) == Path(value["actual"]) == selected.resolve()
    assert (selected / ".env").is_file()
    assert all(not path.exists() for path in (native, environment, configured) if path != selected)


def test_posix_frozen_and_macos_app_cli_host_is_an_exact_companion(tmp_path, monkeypatch):
    folder = tmp_path / "ImmoManager Pro.app/Contents/MacOS"
    folder.mkdir(parents=True)
    gui, cli = folder / "ImmoManager-Pro", folder / "ImmoManager-Pro-CLI"
    gui.touch()
    cli.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(gui))
    assert frozen_cli_executable() == str(cli)
    cli.unlink()
    with pytest.raises(RuntimeError, match="ImmoManager-Pro-CLI fehlt"):
        frozen_cli_executable()


def test_linux_ancestry_is_bounded_and_requires_the_current_user(tmp_path):
    status = tmp_path / "100/status"
    status.parent.mkdir()
    status.write_text("Name:\tworker\nPPid:\t90\nUid:\t1000\t1000\t1000\t1000\n", encoding="ascii")
    assert desktop_control._posix_process_parent(100, platform="linux", proc_root=tmp_path, owner_uid=1000) == 90
    assert desktop_control._posix_process_parent(100, platform="linux", proc_root=tmp_path, owner_uid=1001) is None
    assert desktop_control._posix_process_parent(101, platform="linux", proc_root=tmp_path, owner_uid=1000) is None
    status.write_text("x" * 65537, encoding="ascii")
    assert desktop_control._posix_process_parent(100, platform="linux", proc_root=tmp_path, owner_uid=1000) is None


def test_macos_ancestry_command_and_failure_are_closed(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, " 90 1000\n", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert desktop_control._posix_process_parent(100, platform="darwin", owner_uid=1000) == 90
    assert desktop_control._posix_process_parent(100, platform="darwin", owner_uid=1001) is None
    assert calls[0][0] == ["/bin/ps", "-o", "ppid=", "-o", "uid=", "-p", "100"]
    assert calls[0][1]["stdin"] == subprocess.DEVNULL
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("ps", 2)))
    assert desktop_control._posix_process_parent(100, platform="darwin", owner_uid=1000) is None


def test_posix_ready_rejects_foreign_pid_cycles_and_excessive_depth(monkeypatch):
    monkeypatch.setattr(desktop_control, "_is_windows", lambda: False)
    parents = {30: 20, 20: 10}
    monkeypatch.setattr(desktop_control, "_posix_process_parent", lambda pid: parents.get(pid))
    line = desktop_control.READY_PREFIX + json.dumps({"token": "a" * 64, "pid": 30, "url": "http://127.0.0.1:12345"})
    assert desktop_control.ready_message(line, token="a" * 64, pid=10, url="http://127.0.0.1:12345", allow_child_pid=True)
    assert not desktop_control.ready_message(line, token="b" * 64, pid=10, url="http://127.0.0.1:12345", allow_child_pid=True)
    parents[20] = 30
    assert not desktop_control._owned_descendant(30, 10)
    parents.clear()
    parents.update({pid: pid - 1 for pid in range(11, 31)})
    assert not desktop_control._owned_descendant(30, 10)
