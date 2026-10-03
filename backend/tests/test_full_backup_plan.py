"""Native protected plan files, kernel ownership, restart and DST contracts."""

import multiprocessing
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.backup_operations.plan import BackupOperationError, BackupPlan, Installation, due_period
from backend.backup_operations.state import FileLease, load_plan, passphrase, private_directory, save_plan
from scripts.private_server_backup import protected_new_file


def configured(tmp_path):
    directory = private_directory(tmp_path / "plans")
    key = directory / "backup-key.txt"
    with protected_new_file(key) as output:
        output.write(b"Synthetic private full-backup passphrase\n")
    plan = BackupPlan(installation=Installation(backend="sqlite", app_root=tmp_path, python=Path(sys.executable), data_dir=tmp_path),
                      destination=tmp_path / "archives", key_files={"initial": key})
    return directory, plan


def test_native_private_plan_revision_and_secret_reference(tmp_path):
    directory, plan = configured(tmp_path)
    save_plan(directory, plan)
    assert load_plan(directory) == plan and passphrase(plan) == "Synthetic private full-backup passphrase"
    assert b"Synthetic private full-backup passphrase" not in (directory / "plan.json").read_bytes()
    revised = plan.model_copy(update={"revision": 2, "retention_days": 3650})
    save_plan(directory, revised, expected_revision=1)
    with pytest.raises(BackupOperationError, match="revision_changed"):
        save_plan(directory, revised, expected_revision=1)
    assert load_plan(directory) == revised
    plan.key_files["initial"].unlink()
    with pytest.raises(BackupOperationError, match="backup_key_missing"):
        passphrase(plan)


def _locked_child(path, pipe):
    with FileLease(Path(path)):
        pipe.send("owned")
        pipe.recv()
        os._exit(19)


def test_real_killed_worker_releases_kernel_lease_without_stale_file_deletion(tmp_path):
    directory = private_directory(tmp_path / "owned")
    path = directory / "runner.lock"
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_locked_child, args=(str(path), child))
    process.start()
    try:
        assert parent.poll(30) and parent.recv() == "owned"
        identity = (path.stat().st_dev, path.stat().st_ino)
        with pytest.raises(BackupOperationError, match="installation_busy"):
            with FileLease(path):
                pytest.fail("Another process already owns this installation")
        parent.send("crash")
        process.join(timeout=15)
        assert process.exitcode == 19
        with FileLease(path):
            assert (path.stat().st_dev, path.stat().st_ino) == identity
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)
        parent.close()
        child.close()


def test_schedule_dst_gap_fold_and_missed_month_run_once(tmp_path):
    _, plan = configured(tmp_path)
    # Berlin's 02:15 does not exist on the 2026 spring transition.
    before = datetime(2026, 3, 29, 0, 59, tzinfo=timezone.utc)
    after = datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc)
    assert due_period(plan, "backup", before, None) is None
    assert due_period(plan, "backup", after, None) == "2026-03-29"
    first = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
    second = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)
    assert due_period(plan, "backup", first, None) == "2026-10-25"
    assert due_period(plan, "backup", second, "2026-10-25") is None
    missed = datetime(2026, 12, 18, 10, 0, tzinfo=timezone.utc)
    assert due_period(plan, "backup", missed, "2026-10-25") == "2026-12-18"
    assert due_period(plan, "probe", missed, "2026-10") == "2026-12"
