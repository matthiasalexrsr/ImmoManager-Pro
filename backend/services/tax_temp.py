"""Owned tax spools with an OS lease; reap only proven abandoned workspaces."""
import json
import shutil
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from ..config import settings

FORMAT = "immomanager-tax-spool-v1"


@contextmanager
def _lease(stream):
    locked = False
    try:
        stream.seek(0)
        if sys.platform == "win32":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                locked = True
            except OSError:
                pass
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError:
                pass
        yield locked
    finally:
        if locked:
            stream.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _identity(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("Reparse/spool path cannot be cleaned")
    return [info.st_dev, info.st_ino]


def reap_abandoned(base):
    base = base.resolve(strict=True)
    for path in base.iterdir():
        if not path.name.startswith("tax-"):
            continue
        try:
            identity = _identity(path)
            if not path.is_dir() or path.resolve(strict=True).parent != base:
                continue
            marker = json.loads((path / ".tax-owner.json").read_text(encoding="utf-8"))
            if marker != {"format": FORMAT, "directory": str(path), "identity": identity}:
                continue
            abandoned = False
            with (path / ".tax-owner.lock").open("r+b") as stream, _lease(stream) as locked:
                abandoned = locked
            # Windows cannot remove an open lock file. Recheck the exact owned
            # directory after closing it; a live process never releases its lease
            # until it has finished with all of that directory's source files.
            if abandoned and _identity(path) == identity and path.resolve(strict=True).parent == base:
                shutil.rmtree(path)
        except (OSError, ValueError, TypeError):
            # Unknown, replaced or currently active paths must remain untouched.
            continue


@contextmanager
def tax_workspace(parent=None):
    base = Path(parent) if parent else Path(settings.data_dir) / "tax-work"
    base.mkdir(parents=True, exist_ok=True)
    base = base.resolve(strict=True)
    reap_abandoned(base)
    with tempfile.TemporaryDirectory(prefix="tax-", dir=base) as directory:
        path = Path(directory)
        with (path / ".tax-owner.lock").open("x+b") as stream:
            stream.write(b"\0")
            stream.flush()
            with _lease(stream) as locked:
                if not locked:
                    raise OSError("Tax spool lease could not be acquired")
                (path / ".tax-owner.json").write_text(json.dumps({"format": FORMAT, "directory": str(path),
                    "identity": _identity(path)}), encoding="utf-8")
                yield path
