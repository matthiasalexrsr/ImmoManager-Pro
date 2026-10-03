"""Protected atomic external state and real process-lifetime file ownership."""

import json
import os
import stat
from contextlib import contextmanager
from io import FileIO
from pathlib import Path
from uuid import uuid4

from scripts.private_server_backup import (
    BackupError,
    _protect,
    _safe_path,
    _verify_private,
    _windows_sid,
    protected_new_file,
)

from .plan import BackupOperationError, BackupPlan


def private_directory(directory: Path) -> Path:
    directory = Path(os.path.abspath(directory))
    _safe_path(directory.parent, directory=True)
    sid = _windows_sid() if os.name == "nt" else None
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        _safe_path(directory, directory=True)
        _verify_private(directory, directory, sid)
    else:
        _protect(directory, directory, sid)
    return directory


def read_private(path: Path, *, maximum=1024 * 1024) -> bytes:
    path = _safe_path(path)
    sid = _windows_sid() if os.name == "nt" else None
    _verify_private(path, path.parent, sid, protected=False)
    before = path.stat()
    if before.st_size > maximum:
        raise BackupOperationError("private_metadata_too_large")
    with path.open("rb") as source:
        value = source.read(maximum + 1)
        after = os.fstat(source.fileno())
    if len(value) > maximum or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise BackupOperationError("private_metadata_changed")
    return value


def read_json(path: Path):
    from backend.services.full_recovery import _json
    return _json(read_private(path))


def _sync_directory(path: Path):
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def write_json(path: Path, value, *, new=False):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    temporary = path.with_name("." + path.name + "." + uuid4().hex + ".tmp")
    try:
        with protected_new_file(temporary) as target:
            target.write(raw)
        if new:
            os.link(temporary, path)
        else:
            if path.exists():
                _safe_path(path)
            os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class FileLease:
    """Kernel-owned exclusion; no PID, age or stale-lock deletion heuristic."""
    def __init__(self, path: Path):
        self.path = path
        self.file: FileIO | None = None

    def __enter__(self):
        if self.file is not None:
            return self  # A stop operation may return an already acquired lease.
        if not self.path.exists():
            try:
                with protected_new_file(self.path) as target:
                    target.write(b"L")
            except FileExistsError:
                pass
        _safe_path(self.path)
        descriptor = os.open(self.path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
        self.file = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                getattr(fcntl, "flock")(descriptor, getattr(fcntl, "LOCK_EX") | getattr(fcntl, "LOCK_NB"))
            before, current = os.fstat(descriptor), self.path.lstat()
            if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino) or not stat.S_ISREG(current.st_mode):
                raise BackupOperationError("lock_ownership_changed")
        except Exception as error:
            self.file.close()
            self.file = None
            if isinstance(error, BlockingIOError) or isinstance(error, OSError) and error.errno in {11, 13, 35}:
                raise BackupOperationError("installation_busy") from None
            raise
        return self

    def __exit__(self, *_):
        if self.file is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.file.seek(0)
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    getattr(fcntl, "flock")(self.file.fileno(), getattr(fcntl, "LOCK_UN"))
            finally:
                self.file.close()
                self.file = None


@contextmanager
def plan_lock(directory: Path):
    with FileLease(directory / "runner.lock"):
        yield


def load_plan(directory: Path) -> BackupPlan:
    try:
        return BackupPlan.model_validate(read_json(directory / "plan.json"))
    except (ValueError, OSError, BackupError):
        raise BackupOperationError("backup_plan_invalid_or_unreadable") from None


def save_plan(directory: Path, plan: BackupPlan, *, expected_revision: int | None = None):
    directory = private_directory(directory)
    with plan_lock(directory):
        path = directory / "plan.json"
        if path.exists():
            previous = load_plan(directory)
            if expected_revision != previous.revision or previous.id != plan.id or plan.revision != previous.revision + 1:
                raise BackupOperationError("backup_plan_revision_changed")
            for key, reference in previous.key_files.items():
                if plan.key_files.get(key) != reference:
                    raise BackupOperationError("retained_archive_key_reference_required")
            write_json(path, plan.model_dump(mode="json"))
        else:
            if expected_revision is not None or plan.revision != 1:
                raise BackupOperationError("backup_plan_revision_changed")
            write_json(path, plan.model_dump(mode="json"), new=True)


def passphrase(plan: BackupPlan, key_id: str | None = None) -> str:
    try:
        value = read_private(plan.key_files[key_id or plan.key_id], maximum=64 * 1024).decode("utf-8").rstrip("\r\n")
        if len(value) < 12 or "\x00" in value:
            raise ValueError
        return value
    except (KeyError, ValueError, OSError, BackupError):
        raise BackupOperationError("backup_key_missing_or_unreadable") from None
