"""Install pinned desktop wheels through a short, temporary Windows venv alias.

The alias avoids legacy MAX_PATH failures inside upstream Qt wheel paths. Only
our junction and its empty temporary parent are removed; the venv is preserved.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pinned_versions(root=ROOT):
    result = {}
    for raw in (root / "requirements-desktop.txt").read_text(encoding="utf-8").splitlines():
        line = raw.partition("#")[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==(\d+\.\d+\.\d+)", line)
        if not match:
            raise ValueError("Desktop-Abhängigkeiten müssen ausdrücklich versioniert sein: " + line)
        result[match[1]] = match[2]
    if not result:
        raise ValueError("Keine versionierten Desktop-Abhängigkeiten gefunden.")
    return result


def versions_current(root=ROOT):
    for name, expected in pinned_versions(root).items():
        try:
            if metadata.version(name) != expected:
                return False
        except metadata.PackageNotFoundError:
            return False
    return True


@contextmanager
def pip_python():
    prefix = Path(sys.prefix)
    if not (prefix / "pyvenv.cfg").is_file():
        raise RuntimeError("Desktop-Abhängigkeiten aus der virtuellen Projektumgebung installieren.")
    if os.name != "nt":
        yield Path(sys.executable)
        return
    import _winapi

    owner = Path(tempfile.mkdtemp(prefix="iq-", dir=Path.home()))
    alias = owner / "v"
    linked = False
    try:
        _winapi.CreateJunction(str(prefix), str(alias))
        linked = True
        # Do not resolve this path: resolving would restore the long venv name.
        python = alias / "Scripts/python.exe"
        if not python.is_file():
            raise FileNotFoundError("Der Python-Starter der Projektumgebung fehlt.")
        yield python
    finally:
        if linked:
            os.rmdir(alias)
        os.rmdir(owner)


def install(root=ROOT):
    pinned_versions(root)
    with pip_python() as python:
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(root / "requirements-desktop.txt"),
                        "-c", str(root / "constraints.txt")], check=True, stdin=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Nur die installierten Versionsmetadaten prüfen.")
    args = parser.parse_args()
    if args.check:
        return 0 if versions_current() else 1
    install()
    if not versions_current():
        raise RuntimeError("Die installierten Desktop-Abhängigkeiten entsprechen nicht den festgelegten Versionen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
