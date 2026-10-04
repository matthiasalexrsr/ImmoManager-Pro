"""Atomic JSON; private local filesystem, cooperating writers, stable sidecar lock."""
from __future__ import annotations

import errno
import hashlib
import hmac
import json
import math
import os
import stat
import tempfile
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from threading import Lock, RLock

_LIMIT = 1024 * 1024
_JSON_DEPTH = 64
_REGISTRY_GUARD = Lock()
_LOCKS: dict[str, RLock] = {}

class ConfigStoreError(RuntimeError):
    """published: False=old file intact; True=new file visible; None=uncertain."""

    def __init__(self, code: str, *, published: bool | None = False):
        super().__init__(code)
        self.code = code
        self.published = published

def _checked_state(value: dict, max_depth: int = _JSON_DEPTH) -> dict:
    if type(max_depth) is not int or max_depth < 1:
        raise ConfigStoreError("invalid_json_depth")
    if not isinstance(value, dict):
        raise ConfigStoreError("invalid_state")
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > max_depth:
            raise ConfigStoreError("state_too_deep")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ConfigStoreError("invalid_state")
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            pending.extend((v, depth + 1) for v in item)
        elif item is None or type(item) in (str, bool, int):
            continue
        elif type(item) is not float or not math.isfinite(item):
            raise ConfigStoreError("invalid_state")
    enabled, configs = value.get("enabled", {}), value.get("config", {})
    if (not isinstance(enabled, dict) or not isinstance(configs, dict)
            or any(type(v) is not bool for v in enabled.values())
            or any(not isinstance(v, dict) for v in configs.values())):
        raise ConfigStoreError("invalid_integration_state")
    return value

def _decode(raw: bytes, max_depth: int = _JSON_DEPTH) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError

    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique,
                           parse_constant=reject_constant)
        return _checked_state(value, max_depth)
    except (ValueError, UnicodeError, RecursionError):
        raise ConfigStoreError("invalid_json") from None

def _encode(value: dict, maximum: int, max_depth: int = _JSON_DEPTH) -> bytes:
    if type(maximum) is not int or maximum < 1:
        raise ConfigStoreError("invalid_store_limit")
    _checked_state(value, max_depth)
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False,
                         indent=2, sort_keys=True).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ConfigStoreError("invalid_state") from None
    if len(raw) > maximum:
        raise ConfigStoreError("state_too_large")
    return raw

def _regular(path: Path, *, missing_ok=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return None
        raise ConfigStoreError("state_missing") from None
    except OSError:
        raise ConfigStoreError("state_unreadable") from None
    if (not stat.S_ISREG(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
            or info.st_nlink != 1):
        raise ConfigStoreError("unsafe_state_file")
    return info

def _verify_handle(path: Path, descriptor: int):
    named = _regular(path)
    opened = os.fstat(descriptor)
    if (named is None or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
        raise ConfigStoreError("state_file_changed")
    return opened

class IntegrationConfigStore(ABC):
    @abstractmethod
    def load(self) -> dict:
        ...

    @abstractmethod
    def save(self, state: dict) -> None:
        ...

    @abstractmethod
    def update(self, mutate: Callable[[dict], dict]) -> dict:
        """Callback runs under lock; no I/O or nested store calls."""
        ...

class InMemoryIntegrationConfigStore(IntegrationConfigStore):
    def __init__(self, *, max_bytes=_LIMIT, max_json_depth=_JSON_DEPTH):
        if type(max_bytes) is not int or max_bytes < 1:
            raise ConfigStoreError("invalid_store_limit")
        if type(max_json_depth) is not int or max_json_depth < 1:
            raise ConfigStoreError("invalid_json_depth")
        self._state: dict = {}
        self._lock = RLock()
        self._maximum = max_bytes
        self._max_depth = max_json_depth

    def _raw(self) -> bytes:
        return _encode(self._state, self._maximum, self._max_depth)

    def load(self) -> dict:
        with self._lock:
            return deepcopy(self._state)

    def load_with_revision(self) -> tuple[dict, str]:
        with self._lock:
            raw = self._raw()
            return deepcopy(self._state), hashlib.sha256(raw).hexdigest()

    def save(self, state: dict) -> None:
        with self._lock:
            self._state = _decode(_encode(state, self._maximum, self._max_depth), self._max_depth)

    def update(self, mutate: Callable[[dict], dict]) -> dict:
        with self._lock:
            candidate = mutate(deepcopy(self._state))
            self._state = _decode(_encode(candidate, self._maximum, self._max_depth), self._max_depth)
            return deepcopy(self._state)

    def update_if_revision(self, expected_revision: str, mutate: Callable[[dict], dict]) -> tuple[dict, str]:
        with self._lock:
            current = self._raw()
            if not isinstance(expected_revision, str) or not expected_revision or not hmac.compare_digest(
                hashlib.sha256(current).hexdigest(), expected_revision
            ):
                raise ConfigStoreError("state_revision_conflict")
            candidate = mutate(deepcopy(self._state))
            raw = _encode(candidate, self._maximum, self._max_depth)
            self._state = _decode(raw, self._max_depth)
            return deepcopy(self._state), hashlib.sha256(raw).hexdigest()

class JsonFileIntegrationConfigStore(IntegrationConfigStore):
    def __init__(self, file_path: str, *, max_bytes=_LIMIT, lock_timeout=5.0, max_json_depth=_JSON_DEPTH):
        if type(max_bytes) is not int or max_bytes < 1:
            raise ConfigStoreError("invalid_store_limit")
        if (isinstance(lock_timeout, bool)
                or not isinstance(lock_timeout, (int, float))
                or not math.isfinite(lock_timeout) or lock_timeout <= 0):
            raise ConfigStoreError("invalid_lock_timeout")
        if type(max_json_depth) is not int or max_json_depth < 1:
            raise ConfigStoreError("invalid_json_depth")
        try:
            requested = Path(file_path).expanduser().absolute()
            if not requested.name:
                raise ValueError
            self._path = requested.parent.resolve() / requested.name
        except (OSError, ValueError, RuntimeError):
            raise ConfigStoreError("invalid_store_path") from None
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._maximum = max_bytes
        self._timeout = float(lock_timeout)
        self._max_depth = max_json_depth
        with _REGISTRY_GUARD:
            self._thread_lock = _LOCKS.setdefault(
                os.path.normcase(str(self._path)), RLock())

    @contextmanager
    def _locked(self):
        deadline = time.monotonic() + self._timeout
        if not self._thread_lock.acquire(timeout=self._timeout):
            raise ConfigStoreError("state_busy")
        descriptor = None
        failed = False
        try:
            _regular(self._lock_path, missing_ok=True)
            flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(
                self._lock_path, flags | getattr(os, "O_BINARY", 0), 0o600)
            if _verify_handle(self._lock_path, descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            while True:
                if time.monotonic() >= deadline:
                    raise ConfigStoreError("state_busy")
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        getattr(fcntl, "flock")(descriptor, getattr(fcntl, "LOCK_EX") | getattr(fcntl, "LOCK_NB"))
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EINTR}:
                        raise
                    time.sleep(min(0.02, max(0, deadline - time.monotonic())))
            yield
        except OSError:
            failed = True
            raise ConfigStoreError("state_io_failed", published=None) from None
        except BaseException:
            failed = True
            raise
        finally:
            try:
                if descriptor is not None:
                    os.close(descriptor)
            except OSError:
                if not failed:
                    raise ConfigStoreError("lock_close_failed", published=None) from None
            finally:
                self._thread_lock.release()

    def _read_raw_locked(self) -> bytes:
        _regular(self._path)
        descriptor = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self._path, flags | getattr(os, "O_BINARY", 0))
            size = _verify_handle(self._path, descriptor).st_size
            if size > self._maximum:
                raise ConfigStoreError("state_too_large")
            source = os.fdopen(descriptor, "rb")
            descriptor = None
            with source:
                raw = source.read(size + 1)
        except OSError:
            raise ConfigStoreError("state_unreadable") from None
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    raise ConfigStoreError("state_read_close_failed") from None
        if len(raw) > self._maximum:
            raise ConfigStoreError("state_too_large")
        return raw

    def _load_locked(self) -> dict:
        return _decode(self._read_raw_locked(), self._max_depth)

    def load(self) -> dict:
        with self._locked():
            return self._load_locked()

    def load_with_revision(self) -> tuple[dict, str]:
        with self._locked():
            raw = self._read_raw_locked()
            return _decode(raw, self._max_depth), hashlib.sha256(raw).hexdigest()

    def initialize(self, state: dict | None = None) -> dict:
        """Bootstrap only; never overwrite damaged state."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise ConfigStoreError("state_io_failed") from None
        with self._locked():
            if _regular(self._path, missing_ok=True) is not None:
                return self._load_locked()
            raw = _encode({} if state is None else state, self._maximum, self._max_depth)
            self._write_locked(raw)
            return _decode(raw, self._max_depth)

    def _write_locked(self, raw: bytes) -> None:
        temporary = None
        directory_fd = descriptor = None
        published = False
        failure = None
        try:
            _regular(self._path, missing_ok=True)
            if os.name == "posix":
                directory_fd = os.open(
                    self._path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            descriptor, filename = tempfile.mkstemp(
                prefix=f".{self._path.name}.tmp-", dir=self._path.parent)
            temporary = Path(filename)
            output = os.fdopen(descriptor, "wb")
            descriptor = None
            with output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            _regular(self._path, missing_ok=True)
            os.replace(temporary, self._path)
            published = True
            if directory_fd is not None:
                os.fsync(directory_fd)
        except ConfigStoreError as exc:
            failure = exc
        except OSError:
            failure = ConfigStoreError(
                "durability_unconfirmed" if published else "state_write_failed",
                published=published)
        finally:
            cleanup_failed = False
            for opened in (descriptor, directory_fd):
                if opened is not None:
                    try:
                        os.close(opened)
                    except OSError:
                        cleanup_failed = True
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    cleanup_failed = True
            if cleanup_failed and failure is None:
                failure = ConfigStoreError("state_cleanup_failed", published=published)
        if failure is not None:
            raise failure from None

    def save(self, state: dict) -> None:
        """Whole-state replacement, not concurrent partial editing."""
        raw = _encode(state, self._maximum, self._max_depth)
        with self._locked():
            self._load_locked()
            self._write_locked(raw)

    def update(self, mutate: Callable[[dict], dict]) -> dict:
        with self._locked():
            raw = _encode(mutate(deepcopy(self._load_locked())), self._maximum, self._max_depth)
            self._write_locked(raw)
            return _decode(raw, self._max_depth)

    def update_if_revision(self, expected_revision: str, mutate: Callable[[dict], dict]) -> tuple[dict, str]:
        with self._locked():
            current_raw = self._read_raw_locked()
            current_revision = hashlib.sha256(current_raw).hexdigest()
            if not isinstance(expected_revision, str) or not expected_revision or not hmac.compare_digest(
                current_revision, expected_revision
            ):
                raise ConfigStoreError("state_revision_conflict")
            current = _decode(current_raw, self._max_depth)
            raw = _encode(mutate(deepcopy(current)), self._maximum, self._max_depth)
            self._write_locked(raw)
            return _decode(raw, self._max_depth), hashlib.sha256(raw).hexdigest()
