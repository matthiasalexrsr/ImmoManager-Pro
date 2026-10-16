"""Explicit package hooks; no discovery/import of arbitrary archive-provided code.

Hooks receive only an owned database snapshot and extraction/staging root. Registration
must happen in application/CLI source before backup/restore, never from an archive.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class BackupExtension:
    name: str
    version: int
    references: Callable[[Path], set[str]]
    validate: Callable[[Path, Path], None]


_extensions: dict[str, BackupExtension] = {}


def register(extension: BackupExtension) -> None:
    if not extension.name.isidentifier() or extension.version < 1 or extension.name in _extensions:
        raise ValueError("Ungültige oder doppelte Backup-Erweiterung")
    _extensions[extension.name] = extension


def extensions() -> tuple[BackupExtension, ...]:
    return tuple(_extensions[name] for name in sorted(_extensions))
