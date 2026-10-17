"""OS-only paths; public keys and stored references keep their canonical form."""
import ntpath
import os
from pathlib import Path


def windows_extended_path(path: str) -> str:
    absolute = ntpath.abspath(path)
    if absolute.startswith('\\\\?\\'):
        return absolute
    if absolute.startswith('\\\\'):
        return '\\\\?\\UNC\\' + absolute[2:]
    return '\\\\?\\' + absolute


def filesystem_path(path: str | os.PathLike[str]) -> Path:
    """Use Win32 extended paths for I/O, after callers validate confinement."""
    value = os.fspath(path)
    return Path(windows_extended_path(value)) if os.name == 'nt' else Path(value)
