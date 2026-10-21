"""Every install path must ship the packages security features rely on."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# cryptography: without it IBANs are silently stored in plain text.
REQUIRED = {"cryptography", "pyjwt"}


def _name(spec: str) -> str:
    return re.split(r"[<>=!~\[; ]", spec.strip(), maxsplit=1)[0].lower()


def _requirements(path: Path, seen: set[Path] | None = None) -> set[str]:
    """Follow local requirement includes, as pip does; constraints install no packages."""
    path = path.resolve()
    seen = set() if seen is None else seen
    if path in seen:
        return set()
    seen.add(path)
    names = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        include = re.match(r"^(?:-r\s+|--requirement(?:\s+|=))(.+)$", line)
        if include:
            names.update(_requirements(path.parent / include.group(1).strip(), seen))
        elif line and not line.startswith(("#", "-")):
            names.add(_name(line))
    return names


def test_pyproject_declares_security_dependencies():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    names = {_name(dep) for dep in data["project"]["dependencies"]}
    assert REQUIRED <= names


def test_requirements_files_declare_security_dependencies():
    for path in (ROOT / "requirements.txt", ROOT / "backend" / "requirements.txt"):
        assert REQUIRED <= _requirements(path), path
