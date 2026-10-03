"""Persist runtime defaults atomically before they can encrypt business data.

This module deliberately imports no application settings during launcher setup.
"""
import errno
import importlib
import io
import os
import re
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

_guard = threading.Lock()
_locks: dict[str, Any] = {}
_VALUE_MARKER = " # immomanager-runtime-value:v1"


class RuntimeConfigurationError(RuntimeError):
    pass


def runtime_value(raw):
    """Decode marked dotenv values; retain literal legacy simply quoted paths."""
    value = raw.strip()
    if value.endswith(_VALUE_MARKER):
        from dotenv import dotenv_values

        decoded = dotenv_values(stream=io.StringIO("VALUE=" + value), interpolate=False).get("VALUE")
        if not isinstance(decoded, str):
            raise RuntimeConfigurationError("Ungültige kodierte Runtime-Konfiguration.")
        return decoded
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _serialized_value(value):
    if value != value.strip() or any(char in value for char in "'\"\\#$") or any(ord(char) < 32 for char in value):
        escapes = {"\\": "\\\\", '"': '\\"', "\a": "\\a", "\b": "\\b", "\f": "\\f",
                   "\n": "\\n", "\r": "\\r", "\t": "\\t", "\v": "\\v"}
        return '"' + "".join(escapes.get(char, char) for char in value) + '"' + _VALUE_MARKER
    return value


def _physical_records(content):
    lines = content.split("\n")
    if lines[-1] == "":
        lines.pop()  # Final newline sentinel is not a new blank record.
    return lines


def _regular(path, missing_ok=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return None
        raise
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or getattr(info, "st_file_attributes", 0) & 0x400):
        raise RuntimeConfigurationError("Unsichere Runtime-Datei. Pfad und Dateityp lokal prüfen.")
    return info


@contextmanager
def _locked(path):
    lock_path = path.with_name(path.name + ".lock")
    with _guard:
        lock = _locks.setdefault(os.path.normcase(str(path)), threading.RLock())
    with lock:
        _regular(lock_path, missing_ok=True)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            named, opened = _regular(lock_path), os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
                raise RuntimeConfigurationError("Runtime-Sperrdatei wurde verändert. Erneut starten.")
            if opened.st_size == 0:
                os.write(fd, b"\0")
            deadline = time.monotonic() + 10
            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    if os.name == "nt":
                        msvcrt = importlib.import_module("msvcrt")
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl = importlib.import_module("fcntl")
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EINTR}:
                        raise
                    if time.monotonic() >= deadline:
                        raise RuntimeConfigurationError("Runtime-Konfiguration ist belegt. Anderen Start abschließen und erneut starten.") from None
                    time.sleep(0.02)
            yield
        finally:
            os.close(fd)


def persist_default(config_file, key, proposed, *, persist_existing=False):
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or any(c in proposed for c in "\0\r\n"):
        raise RuntimeConfigurationError("Ungültiger Runtime-Konfigurationswert.")
    current = os.environ.get(key)
    if current and current != "dev-secret-key-change-in-production":
        if not persist_existing:
            return current
        proposed = current
    path = Path(config_file).absolute()
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with _locked(path):
            info = _regular(path, missing_ok=True)
            existing = path.read_text(encoding="utf-8") if info else ""
            matches = [runtime_value(line.partition("=")[2])
                       for line in _physical_records(existing) if line.partition("=")[0].strip().upper() == key]
            if len(matches) > 1:
                raise RuntimeConfigurationError("Doppelte Runtime-Schlüssel. Konfigurationsdatei lokal bereinigen.")
            if matches and matches[0] == proposed:
                os.environ[key] = proposed
                return proposed
            if matches and matches[0] and matches[0] != "dev-secret-key-change-in-production" and (not persist_existing or not current):
                os.environ[key] = matches[0]
                return matches[0]
            lines = [line for line in _physical_records(existing) if line.partition("=")[0].strip().upper() != key]
            lines.append(key + "=" + _serialized_value(proposed))
            # The exclusive file has a verified private ACL before secret bytes.
            from scripts.private_server_backup import protected_new_file
            with protected_new_file(temporary) as output:
                output.write(("\n".join(lines) + "\n").encode("utf-8"))
            if info:
                current_info = _regular(path)
                if (current_info.st_dev, current_info.st_ino, current_info.st_mtime_ns, current_info.st_size) != (
                        info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size):
                    raise RuntimeConfigurationError("Runtime-Konfiguration wurde verändert. Erneut starten.")
            elif os.path.lexists(path):
                raise RuntimeConfigurationError("Runtime-Konfiguration wurde parallel angelegt. Erneut starten.")
            os.replace(temporary, path)
            os.environ[key] = proposed
            return proposed
    except (OSError, ValueError) as exc:
        raise RuntimeConfigurationError("Runtime-Konfiguration konnte nicht dauerhaft gespeichert werden. Freien Speicher und Dateirechte prüfen, dann erneut starten.") from exc
    finally:
        temporary.unlink(missing_ok=True)


def persist_selected_values(config_file, values):
    """Atomically retain an explicit key bundle; refuse rotation/conflicting keys."""
    if not isinstance(values, dict) or not values:
        raise RuntimeConfigurationError("Keine ausdrückliche Schlüsselkonfiguration ausgewählt.")
    for key, value in values.items():
        if (not isinstance(key, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key)
                or not isinstance(value, str) or any(char in value for char in "\0\r\n")):
            raise RuntimeConfigurationError("Ungültige ausgewählte Schlüsselkonfiguration.")
    path = Path(config_file).absolute()
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with _locked(path):
            info = _regular(path, missing_ok=True)
            existing = path.read_text(encoding="utf-8") if info else ""
            lines = _physical_records(existing)
            missing = []
            # Prove the whole bundle before creating a temporary secret file.
            for key, value in values.items():
                matches = [runtime_value(line.partition("=")[2])
                           for line in lines if line.partition("=")[0].strip().upper() == key]
                if len(matches) > 1 or (matches and matches[0] != value):
                    raise RuntimeConfigurationError(
                        "Ausgewählte und gespeicherte Schlüssel unterscheiden sich. "
                        "Konfiguration lokal prüfen; Erstinitialisierung ersetzt keine bestehenden Schlüssel."
                    )
                if not matches:
                    missing.append(key + "=" + _serialized_value(value))
            if not missing:
                return
            from scripts.private_server_backup import protected_new_file
            with protected_new_file(temporary) as output:
                output.write(("\n".join([*lines, *missing]) + "\n").encode("utf-8"))
            if info:
                current_info = _regular(path)
                if (current_info.st_dev, current_info.st_ino, current_info.st_mtime_ns, current_info.st_size) != (
                        info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size):
                    raise RuntimeConfigurationError("Runtime-Konfiguration wurde verändert. Erneut prüfen.")
            elif os.path.lexists(path):
                raise RuntimeConfigurationError("Runtime-Konfiguration wurde parallel angelegt. Erneut prüfen.")
            os.replace(temporary, path)
    except (OSError, ValueError):
        raise RuntimeConfigurationError(
            "Schlüsselkonfiguration konnte nicht dauerhaft gespeichert werden. "
            "Freien Speicher und Dateirechte prüfen; keine Integrationsdatei anlegen."
        ) from None
    finally:
        temporary.unlink(missing_ok=True)

