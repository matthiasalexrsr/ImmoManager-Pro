"""Static declared plugin packages; archives never execute their own code during restore."""
import hashlib
import json
from pathlib import Path

from .file_storage import validate_key

DECLARATION = "immomanager-plugin.json"
SUFFIXES = {".py", ".json", ".txt", ".html", ".css", ".js", ".svg", ".png", ".jpg", ".woff2"}


def package(root: Path) -> tuple[dict, list[tuple[str, Path]]]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Pluginpaket muss ein reguläres Verzeichnis sein")
    declaration = json.loads((root / DECLARATION).read_text(encoding="utf-8"))
    if set(declaration) != {"name", "version", "files"} or not isinstance(declaration["files"], dict):
        raise ValueError("Pluginpaket benötigt eine vollständige Dateideklaration")
    import re
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", declaration["name"]):
        raise ValueError("Ungültiger Pluginpaketname")
    if "__init__.py" not in declaration["files"]:
        raise ValueError("Plugin-Einstiegspunkt fehlt in der Dateideklaration")
    files = [(DECLARATION, root / DECLARATION)]
    for name, digest in declaration["files"].items():
        validate_key(name)
        path = root / name
        if (path.suffix.lower() not in SUFFIXES or path.is_symlink()
                or not path.resolve().is_relative_to(root.resolve()) or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise ValueError("Pluginpaket ist unvollständig oder seine Dateiprüfsumme weicht ab")
        files.append((name, path))
    return declaration, files


def inventory(directories: list[str]) -> list[tuple[dict, list[tuple[str, Path]]]]:
    packages, names = [], set()
    for directory in directories:
        root = Path(directory)
        if not root.is_dir() or root.is_symlink():
            raise ValueError("Deklariertes Pluginverzeichnis ist nicht verfügbar")
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name == "__pycache__":
                continue
            value = package(child)
            if value[0]["name"] in names:
                raise ValueError("Doppelter Pluginpaketname")
            names.add(value[0]["name"])
            packages.append(value)
    return packages
