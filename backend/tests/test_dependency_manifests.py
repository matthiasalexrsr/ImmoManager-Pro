"""Every install path must ship the packages security features rely on."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# cryptography seals integration secrets and the full backup; PyJWT signs the sessions.
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


def test_pyproject_declares_every_runtime_dependency_of_requirements():
    """Regression: pypdf (full-text search of PDFs) was missing; build.bat/build.sh install the project
    from pyproject.toml and built a package without it."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = {_name(dep) for dep in data["dependencies"] + data["optional-dependencies"]["postgres"]}
    # pytest belongs to the checks, not to the program
    assert _requirements(ROOT / "requirements.txt") - {"pytest"} <= declared


def test_release_builds_use_the_pinned_build_tools():
    """The Windows packages are built with the PyInstaller of requirements-build.txt, not any 6.x."""
    build = (ROOT / "requirements-build.txt").read_text(encoding="utf-8")
    match = re.search(r"^PyInstaller==(\S+)$", build, re.M)
    assert match, "requirements-build.txt pins PyInstaller"
    pin = match.group(1)
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert f"pyinstaller=={pin}" in data["project"]["optional-dependencies"]["build"]
    for workflow in ("release.yml", "testversion.yml"):
        text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        assert "-r requirements-build.txt" in text and "pyinstaller>=" not in text.lower(), workflow
