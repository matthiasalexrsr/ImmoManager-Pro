"""Every install path must ship the packages security features rely on."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# cryptography: without it IBANs are silently stored in plain text.
REQUIRED = {"cryptography", "pyjwt"}


def _name(spec: str) -> str:
    return re.split(r"[<>=!~\[; ]", spec.strip(), maxsplit=1)[0].lower()


def _requirements(path: Path) -> set[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return {_name(line) for line in lines if line.strip() and not line.startswith(("#", "-"))}


def test_pyproject_declares_security_dependencies():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    names = {_name(dep) for dep in data["project"]["dependencies"]}
    assert REQUIRED <= names


def test_requirements_files_declare_security_dependencies():
    for path in (ROOT / "requirements.txt", ROOT / "backend" / "requirements.txt"):
        assert REQUIRED <= _requirements(path), path
