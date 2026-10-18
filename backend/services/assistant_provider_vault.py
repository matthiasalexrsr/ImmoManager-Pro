"""Encrypted per-application-user CLI credentials; plaintext exists only in private leases.

The encrypted vault is in the protected upload namespace and therefore participates
in full backups. Provider CLIs never read the operator's global account directory.
"""
from __future__ import annotations

import base64
import errno
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from _thread import LockType
from pathlib import Path

from ..paths import get_data_dir, get_uploads_dir
from .assistant_provider_protocol import ProviderError
from .secret_box import SecretError, default_secret_box, write_private_file

AUTH_FILES = {"codex": {"auth.json"}, "claude": {".credentials.json", ".claude.json"}}
_locks: dict[str, LockType] = {}
_guard = threading.Lock()
logger = logging.getLogger(__name__)


def actor_key(actor_id: str) -> str:
    if not isinstance(actor_id, str) or not actor_id:
        raise ProviderError("Die Anmeldung wird noch geprüft.", "authentication_required")
    return hashlib.sha256(actor_id.encode()).hexdigest()


def _vault_path(actor_id: str, provider: str) -> Path:
    if provider not in AUTH_FILES:
        raise ProviderError("Dieser KI-Zugang wird nicht unterstützt.", "unsupported_provider")
    return get_uploads_dir() / "assistant-private" / "_vault" / actor_key(actor_id) / (provider + ".json")


def _context(actor_id: str, provider: str) -> str:
    return "assistant-account:v1:" + actor_key(actor_id) + ":" + provider


def load(actor_id: str, provider: str) -> dict:
    path = _vault_path(actor_id, provider)
    if not path.exists():
        return {"files": {}, "public": {}}
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        body = json.loads(default_secret_box().open(envelope["sealed"], _context(actor_id, provider)))
        if not isinstance(body, dict) or body.get("version") != 1 or not isinstance(body.get("files"), dict) or not isinstance(body.get('public', {}), dict):
            raise ValueError("Invalid credential envelope")
        files = {}
        for name, encoded in body["files"].items():
            if name not in AUTH_FILES[provider] or not isinstance(encoded, str) or len(encoded) > 4_000_000:
                raise ValueError("Invalid credential file")
            files[name] = base64.b64decode(encoded, validate=True)
        return {"files": files, "public": body.get("public", {})}
    except (SecretError, KeyError, ValueError, TypeError, OSError, RecursionError) as error:
        raise ProviderError("Die gespeicherte KI-Anmeldung ist nicht lesbar. Schlüssel oder Sicherung prüfen; alternativ das Konto neu verbinden.", "credentials_unavailable") from error


def public_state(actor_id: str, provider: str) -> dict:
    return load(actor_id, provider)["public"]


def _private_directory(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o700)
        return
    account = (os.environ.get("USERDOMAIN", "") + "\\" + os.environ.get("USERNAME", "")).strip("\\")
    if not account:
        raise ProviderError("Das lokale Benutzerkonto konnte nicht geprüft werden.", "private_directory_unavailable")
    result = subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", account + ":(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise ProviderError("Der geschützte Anmeldeordner konnte nicht eingerichtet werden.", "private_directory_unavailable")


class ProfileLease:
    """Nonblocking OS lease prevents concurrent refreshes from overwriting one account."""
    def __init__(self, actor_id: str, provider: str, *, restore: bool = True):
        self.actor_id, self.provider = actor_id, provider
        _vault_path(actor_id, provider)
        self.root = (get_data_dir() / "assistant-runtime").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path: Path | None = None
        self.handle = None
        self.lock: LockType | None = None
        identity = actor_key(actor_id) + ":" + provider
        with _guard:
            lock = _locks.setdefault(identity, threading.Lock())
        if not lock.acquire(blocking=False):
            raise ProviderError("Dieser Kontozugang wird gerade verwendet. Bitte den laufenden Vorgang abwarten.", "provider_busy")
        self.lock = lock
        try:
            self.handle = (self.root / (actor_key(actor_id) + "-" + provider + ".lock")).open("a+b")
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                # Windows byte-range locks may extend beyond EOF. Reading or
                # initializing the byte would race with another lease holder.
                try:
                    getattr(msvcrt, 'locking')(self.handle.fileno(), getattr(msvcrt, 'LK_NBLCK'), 1)
                except OSError as error:
                    if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise BlockingIOError() from error
                    raise
            else:
                import fcntl
                getattr(fcntl, 'flock')(self.handle.fileno(), getattr(fcntl, 'LOCK_EX') | getattr(fcntl, 'LOCK_NB'))
            prefix = actor_key(actor_id) + "-" + provider + "-"
            # Holding the cross-process lease proves no profile in this exact
            # account namespace is active. Remove only our crash leftovers.
            for previous in self.root.glob(prefix + '*'):
                if previous.is_symlink() or getattr(previous, 'is_junction', lambda: False)():
                    continue
                resolved = previous.resolve()
                if previous.is_dir() and resolved.is_relative_to(self.root) and resolved != self.root:
                    try:
                        shutil.rmtree(resolved)
                    except OSError:
                        logger.warning('Private assistant crash-profile cleanup is incomplete')
            self.path = Path(tempfile.mkdtemp(prefix=prefix, dir=self.root))
            _private_directory(self.path)
            self.state = load(actor_id, provider) if restore else {"files": {}, "public": {}}
            for name, content in self.state["files"].items():
                write_private_file(self.path / name, content)
            (self.path / "work").mkdir()
        except BlockingIOError as error:
            self.close()
            raise ProviderError("Dieser Kontozugang wird in einem anderen Prozess verwendet.", "provider_busy") from error
        except BaseException:
            self.close()
            raise

    def save(self, public: dict | None = None) -> None:
        assert self.path is not None
        files = {}
        for name in AUTH_FILES[self.provider]:
            file = self.path / name
            if file.is_symlink():
                raise ProviderError("Die Anmeldedatei ist kein zulässiges Original.", "credentials_unavailable")
            if file.exists():
                if file.stat().st_size > 3_000_000:
                    raise ProviderError("Die Anmeldedatei ist unerwartet groß.", "credentials_unavailable")
                files[name] = base64.b64encode(file.read_bytes()).decode("ascii")
        body = {"version": 1, "files": files, "public": public if public is not None else self.state["public"]}
        sealed = default_secret_box().seal(json.dumps(body, separators=(",", ":")), _context(self.actor_id, self.provider))
        write_private_file(_vault_path(self.actor_id, self.provider), json.dumps({"version": 1, "sealed": sealed}).encode())

    def close(self) -> None:
        try:
            if self.path is not None:
                original = self.path.absolute()
                if original.parent == self.root and original.name.startswith(actor_key(self.actor_id) + '-' + self.provider + '-'):
                    try:
                        if original.is_symlink():
                            original.unlink()
                        elif getattr(original, 'is_junction', lambda: False)():
                            original.rmdir()
                        elif original.resolve() == original:
                            # Never pass a resolved alias into recursive delete;
                            # rmtree itself does not traverse directory symlinks.
                            shutil.rmtree(original)
                    except FileNotFoundError:
                        pass
                    except OSError:
                        logger.warning("Private assistant runtime cleanup is incomplete; directory remains access-restricted")
                self.path = None
        finally:
            if self.handle is not None:
                self.handle.close()
                self.handle = None
            if self.lock is not None:
                self.lock.release()
                self.lock = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def disconnect(actor_id: str, provider: str) -> None:
    with ProfileLease(actor_id, provider, restore=False):
        _vault_path(actor_id, provider).unlink(missing_ok=True)
