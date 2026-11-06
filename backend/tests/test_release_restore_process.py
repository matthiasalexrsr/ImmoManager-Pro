"""A real owned process interruption must not publish a partial restore target."""

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_operations_backup import installation  # noqa: F401

from backend.services import full_backup
from backend.services.filesystem_paths import filesystem_path


def _child_environment() -> dict[str, str]:
    """Own child imports must not depend on pytest's cwd or inherited search path."""
    project = Path(__file__).resolve(strict=True).parents[2]
    if not (project / "backend" / "__init__.py").is_file():
        raise RuntimeError("The process test's absolute project import root is missing")
    return {**os.environ, "PYTHONPATH": str(project)}


def _stop_child(process: subprocess.Popen) -> None:
    """Stop only the child owned by this test, with a bounded kill fallback."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def test_interrupted_restore_is_unpublished_and_can_restart_into_the_new_target(installation, tmp_path):  # noqa: F811
    event = full_backup.create_full_backup(sources=installation.sources)
    source = installation.sources.root / event["archive"]
    original = source.read_bytes()
    target, ready = tmp_path / "fresh-profile", tmp_path / "owned-child-ready"
    command = """from pathlib import Path
import sys,time
from backend.services import full_backup
original=full_backup._extract
def pause(*args,**kwargs):
 result=original(*args,**kwargs)
 Path(sys.argv[3]).write_text('extracted but unpublished')
 time.sleep(60)
 return result
full_backup._extract=pause
full_backup.restore_archive(Path(sys.argv[1]),Path(sys.argv[2]))
"""
    with (tmp_path / "owned-child.log").open("wb") as log:
        process = subprocess.Popen([sys.executable, "-X", "utf8", "-c", command, str(source), str(target), str(ready)],
            cwd=tmp_path, env=_child_environment(), stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 25
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            if not ready.exists():
                _stop_child(process)
                log.flush()
                diagnostic = (tmp_path / "owned-child.log").read_text(encoding="utf-8", errors="replace")[-4000:]
                pytest.fail("Own restore process did not reach the 25-second extraction checkpoint; "
                            f"exit={process.returncode}; child log={diagnostic}")
            assert not target.exists()
            _stop_child(process)
        finally:
            _stop_child(process)
    assert source.read_bytes() == original and not target.exists()
    unpublished = list(tmp_path.glob(".fresh-profile.restore-*"))
    assert len(unpublished) == 1 and not (unpublished[0] / "installation/immo_manager.db").exists()
    if os.name != "nt":
        assert unpublished[0].stat().st_mode & 0o777 == 0o700
    # A fresh invocation ignores the unpublished working directory and verifies
    # the original archive again, then creates the real intended target once.
    restored = full_backup.restore_archive(source, target)
    assert restored["restored_to"] and filesystem_path(target / "immo_manager.db").is_file()
    with sqlite3.connect(filesystem_path(target / "immo_manager.db")) as connection:
        assert connection.execute("SELECT count(*) FROM portfolios").fetchone() == (2,)
    assert source.read_bytes() == original
