"""Real POSIX kernel-lock checks; Windows explicitly skips these native cases."""

import os
import selectors
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from backend.desktop_control import (
    INSTANCE_FD_ENV,
    INSTANCE_LOCK_FILE,
    InstanceLock,
    _posix_process_parent,
    adopt_instance_guard,
)

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Native POSIX flock/descriptor checks require Linux or macOS")
ROOT = Path(__file__).resolve().parents[2]


def _spawn(program, *arguments, **options):
    environment = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1")
    environment.pop(INSTANCE_FD_ENV, None)
    environment.update(options.pop("env", {}))
    return subprocess.Popen([sys.executable, "-c", program, *map(str, arguments)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", env=environment, **options)


def _ready(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(timeout=10), "The owned lock child did not announce readiness"
        assert process.stdout.readline().strip() == "ready"


def _stop(process):
    if process.poll() is None:
        process.kill()
    process.communicate(timeout=5)


def test_kernel_guard_conflicts_per_folder_and_preserves_stale_file(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    marker = data / INSTANCE_LOCK_FILE
    marker.write_text("old PID text is not a lock", encoding="ascii")
    first = InstanceLock(data)
    second = InstanceLock(data)
    other = InstanceLock(tmp_path / "other")
    try:
        assert not first.existed and second.existed and not other.existed
        assert stat.S_IMODE(marker.stat().st_mode) == 0o600
        assert marker.read_text(encoding="ascii") == "old PID text is not a lock"
        fd = first.child_process_options()["pass_fds"][0]
        assert not os.get_inheritable(fd)
        second.close()
        first.close()
        again = InstanceLock(data)
        assert not again.existed
        again.close()
        assert marker.is_file(), "Releasing a lock must never unlink a possibly reused inode"
    finally:
        first.close()
        second.close()
        other.close()


def test_sigkill_releases_a_real_child_lock_without_deleting_any_file(tmp_path):
    program = (
        "import sys,time; from pathlib import Path; from backend.desktop_control import InstanceLock; "
        "guard=InstanceLock(Path(sys.argv[1])); assert not guard.existed; "
        "print('ready',flush=True); time.sleep(60)"
    )
    child = _spawn(program, tmp_path)
    try:
        _ready(child)
        competing = InstanceLock(tmp_path)
        assert competing.existed
        competing.close()
        child.kill()
        child.wait(timeout=5)
        recovered = InstanceLock(tmp_path)
        assert not recovered.existed
        recovered.close()
        assert (tmp_path / INSTANCE_LOCK_FILE).is_file()
    finally:
        _stop(child)


def test_server_descriptor_keeps_lock_until_child_exit_after_parent_release(tmp_path):
    guard = InstanceLock(tmp_path)
    program = (
        "import os,sys; from pathlib import Path; "
        "from backend.desktop_control import adopt_instance_guard; "
        "adopt_instance_guard(Path(sys.argv[1])); print('ready',flush=True); sys.stdin.read()"
    )
    child = _spawn(program, tmp_path, env=guard.child_environment(), **guard.child_process_options())
    try:
        _ready(child)
        guard.close()
        competing = InstanceLock(tmp_path)
        assert competing.existed, "A lost GUI parent must not unlock a still-running server"
        competing.close()
        child.stdin.close()
        child.stdin = None
        assert child.wait(timeout=5) == 0
        recovered = InstanceLock(tmp_path)
        assert not recovered.existed
        recovered.close()
    finally:
        guard.close()
        _stop(child)


def test_guard_refuses_symlink_without_modifying_the_target(tmp_path):
    data, foreign = tmp_path / "data", tmp_path / "foreign"
    data.mkdir()
    foreign.write_bytes(b"do not modify")
    (data / INSTANCE_LOCK_FILE).symlink_to(foreign)
    with pytest.raises(OSError):
        InstanceLock(data)
    assert foreign.read_bytes() == b"do not modify"


def test_guard_refuses_hard_link_without_modifying_the_target(tmp_path):
    data, foreign = tmp_path / "data", tmp_path / "foreign"
    data.mkdir()
    foreign.write_bytes(b"do not modify")
    os.link(foreign, data / INSTANCE_LOCK_FILE)
    with pytest.raises(PermissionError):
        InstanceLock(data)
    assert foreign.read_bytes() == b"do not modify"


def test_inherited_descriptor_from_another_folder_is_not_trusted(tmp_path, monkeypatch):
    guard = InstanceLock(tmp_path / "data")
    foreign = tmp_path / "foreign"
    foreign.write_bytes(b"do not modify")
    fd = os.open(foreign, os.O_RDWR)
    try:
        monkeypatch.setenv(INSTANCE_FD_ENV, str(fd))
        with pytest.raises(RuntimeError, match="nicht zu diesem Datenordner"):
            adopt_instance_guard(tmp_path / "data")
        assert foreign.read_bytes() == b"do not modify"
    finally:
        os.close(fd)
        guard.close()


def test_native_posix_parent_information_is_owned_and_correct():
    assert _posix_process_parent(os.getpid()) == os.getppid()
