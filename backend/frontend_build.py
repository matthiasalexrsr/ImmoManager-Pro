"""Content-aware frontend builds with validation and recoverable directory promotion.

This module uses only the standard library so the Windows launcher can invoke it
before importing the application or connecting to the user's database.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

MANIFEST_NAME = ".immomanager-build.json"


class FrontendBuildError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_fingerprint(project_root: Path) -> str:
    root = project_root.resolve()
    frontend = root / "frontend"
    files: set[Path] = set()
    for directory in (frontend / "src", frontend / "public", root / "i18n"):
        if directory.is_dir():
            files.update(path for path in directory.rglob("*") if path.is_file())
    # Include root build configuration and environment inputs, excluding generated
    # output, installed dependencies, e2e screenshots and temporary staging dirs.
    if frontend.is_dir():
        files.update(path for path in frontend.iterdir() if path.is_file() and (
            path.name in {"index.html", "package.json", "package-lock.json", ".npmrc"}
            or path.name.startswith(("vite.config.", "tsconfig", "jsconfig", "postcss.config.", "tailwind.config.", ".env"))
        ))
    digest = hashlib.sha256(b"immomanager-frontend-v1\0")
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(_sha256(path).encode("ascii") + b"\0")
    return digest.hexdigest()


class _AssetReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        reference = values.get("src") if tag == "script" else values.get("href") if tag == "link" else None
        if reference:
            self.references.append(reference)
            if tag == "script":
                self.scripts.append(reference)


def validate_dist(dist: Path) -> None:
    root = dist.resolve()
    index = root / "index.html"
    if not index.is_file() or not index.stat().st_size:
        raise FrontendBuildError("Frontend fehlt oder index.html ist leer. Bitte das Frontend bauen.")
    parser = _AssetReferences()
    parser.feed(index.read_text(encoding="utf-8"))
    local_scripts = 0
    for reference in parser.references:
        url = urlsplit(reference)
        if url.scheme or url.netloc:
            continue
        raw = unquote(url.path).lstrip("/")
        asset = (root / raw).resolve()
        if not raw or not asset.is_relative_to(root) or not asset.is_file() or not asset.stat().st_size:
            raise FrontendBuildError("Frontend enthält eine fehlende oder ungültige Asset-Datei.")
        if reference in parser.scripts:
            local_scripts += 1
    if not local_scripts:
        raise FrontendBuildError("Frontend enthält keinen lokalen JavaScript-Einstiegspunkt.")
    manifest = root / MANIFEST_NAME
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            assets = data["assets"]
            if not isinstance(assets, dict) or "index.html" not in assets:
                raise ValueError("Missing asset checksums")
            for name, checksum in assets.items():
                asset = (root / name).resolve()
                if not asset.is_relative_to(root) or not asset.is_file() or _sha256(asset) != checksum:
                    raise ValueError("Asset checksum mismatch")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise FrontendBuildError("Frontend-Prüfsummen sind ungültig. Bitte das Frontend neu bauen.") from exc


def is_fresh(project_root: Path) -> bool:
    dist = project_root / "frontend" / "dist"
    try:
        validate_dist(dist)
        manifest = json.loads((dist / MANIFEST_NAME).read_text(encoding="utf-8"))
        return manifest.get("source_fingerprint") == source_fingerprint(project_root)
    except (FrontendBuildError, OSError, ValueError, TypeError):
        return False


def _remove_owned(path: Path, frontend: Path) -> None:
    # No deletion of dist/user directories or paths outside this exact parent.
    if path.is_symlink() or path.resolve().parent != frontend.resolve() or not path.name.startswith(
            (".immomanager-build-", ".immomanager-previous-")):
        raise FrontendBuildError("Ungültiger temporärer Frontend-Pfad")
    if path.exists():
        shutil.rmtree(path)


def promote_dist(staged: Path, frontend: Path) -> None:
    frontend = frontend.resolve()
    if staged.is_symlink() or staged.resolve().parent != frontend or not staged.name.startswith(".immomanager-build-"):
        raise FrontendBuildError("Ungültiger Frontend-Build-Pfad")
    validate_dist(staged)
    dist = frontend / "dist"
    if dist.is_symlink():
        raise FrontendBuildError("Frontend-Verzeichnis darf kein symbolischer Link sein")
    previous = frontend / f".immomanager-previous-{uuid4().hex}"
    had_dist = dist.exists()
    if had_dist:
        dist.rename(previous)
    try:
        staged.rename(dist)
    except Exception:
        if had_dist:
            previous.rename(dist)
        raise
    if previous.exists():
        _remove_owned(previous, frontend)


@contextmanager
def _build_lock(frontend: Path):
    lock = frontend / ".immomanager-build.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise FrontendBuildError("Ein Frontend-Build läuft bereits. Bitte den Vorgang abschließen.") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def ensure_frontend(project_root: Path, *, skip_build: bool = False) -> str:
    root = project_root.resolve()
    frontend = root / "frontend"
    dist = frontend / "dist"
    if skip_build:
        validate_dist(dist)
        return "Vorhandenes Frontend geprüft; Build ausdrücklich übersprungen."
    if is_fresh(root):
        return "Frontend ist aktuell; kein Build erforderlich."
    if not (frontend / "package.json").is_file():
        raise FrontendBuildError("frontend/package.json fehlt")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise FrontendBuildError("Frontend ist nicht aktuell; Node.js/npm fehlt. Bitte Node.js installieren oder gültige Assets mit SkipFrontendBuild verwenden.")
    with _build_lock(frontend):
        staged = Path(tempfile.mkdtemp(prefix=".immomanager-build-", dir=frontend))
        try:
            install = [npm, "ci" if (frontend / "package-lock.json").is_file() else "install", "--include=dev", "--no-audit", "--no-fund"]
            _run(install, frontend)
            fingerprint = source_fingerprint(root)
            _run([npm, "run", "build", "--", "--outDir", str(staged), "--emptyOutDir"], frontend)
            validate_dist(staged)
            if fingerprint != source_fingerprint(root):
                raise FrontendBuildError("Frontend-Quellen wurden während des Builds verändert. Bitte erneut starten.")
            assets = {path.relative_to(staged).as_posix(): _sha256(path)
                      for path in staged.rglob("*") if path.is_file()}
            (staged / MANIFEST_NAME).write_text(json.dumps({"source_fingerprint": fingerprint, "assets": assets},
                                                           ensure_ascii=False, indent=2), encoding="utf-8")
            promote_dist(staged, frontend)
            return "Frontend erfolgreich gebaut und geprüft."
        finally:
            if staged.exists():
                _remove_owned(staged, frontend)


def _run(command: list[str], frontend: Path) -> None:
    try:
        completed = subprocess.run(command, cwd=frontend, text=True, capture_output=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FrontendBuildError(f"Frontend-Befehl fehlgeschlagen: {type(exc).__name__}") from exc
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "").strip()[-500:]
        raise FrontendBuildError(f"Frontend-Befehl fehlgeschlagen (Exit {completed.returncode}): {detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    try:
        print(ensure_frontend(args.root, skip_build=args.skip_build))
        return 0
    except (FrontendBuildError, OSError) as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
