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


def _project_dependency_names():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    if 'dependencies' in data['project'].get('dynamic', []):
        files = data['tool']['setuptools']['dynamic']['dependencies']['file']
        assert files, 'Dynamic runtime dependencies need an explicit source'
        return set().union(*(_requirements(ROOT / name) for name in files))
    return {_name(dep) for dep in data['project']['dependencies']}


def test_pyproject_declares_security_dependencies():
    names = _project_dependency_names()
    assert REQUIRED <= names


def test_requirements_files_declare_security_dependencies():
    for path in (ROOT / "requirements.txt", ROOT / "backend" / "requirements.txt"):
        assert REQUIRED <= _requirements(path), path


def test_pyproject_declares_every_runtime_dependency_of_requirements():
    """Regression: pypdf (full-text search of PDFs) was missing; build.bat/build.sh install the project
    from pyproject.toml and built a package without it."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = _project_dependency_names() | {_name(dep) for dep in data["optional-dependencies"]["postgres"]}
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


def test_every_build_installs_with_the_pinned_pip():
    """CI, release builds and the image first install the pip of requirements-pip.txt, never the latest."""
    assert re.search(r"^pip==\d+(\.\d+)+$", (ROOT / "requirements-pip.txt").read_text(encoding="utf-8"), re.M)
    sources = {path.name: path.read_text(encoding="utf-8")
               for path in [*(ROOT / ".github" / "workflows").glob("*.yml"), ROOT / "Dockerfile"]}
    for name, text in sources.items():
        if "pip install" not in text:
            continue
        assert "--upgrade pip" not in text and "-U pip" not in text, name
        first = text.index("pip install")
        assert text.startswith("pip install --no-cache-dir -r requirements-pip.txt", first) or \
            text.startswith("pip install -r requirements-pip.txt", first), name
        # every job installs it before anything else
        assert text.count("-r requirements-pip.txt") >= text.count("actions/setup-python"), name
