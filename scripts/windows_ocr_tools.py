"""Explicit Windows OCR tool provisioning; never changes app settings or PATH.

Only the committed, previously exercised win-64 lock is accepted. Installation
copies verified local archives into a NEW private prefix and runs micromamba
offline, without configuration files, shell initialization or link scripts.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import io
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.ocr_process_tree import ProcessTree  # noqa: E402
from backend.services.ocr_service import OCRProcessingError  # noqa: E402
from scripts.private_server_backup import (  # noqa: E402
    BackupError,
    _protect,
    _safe_path,
    _verify_private,
    _windows_sid,
)

LOCK_PATH = Path(__file__).with_name("windows_ocr_tools.lock.json")
CHUNK = 1024 * 1024


class ToolSetupError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _fail(code: str, message: str) -> NoReturn:
    raise ToolSetupError(code, message)


def _relative(value: str) -> Path:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or ".." in path.parts or "\\" in value
            or ":" in value or any(c in value for c in "\0\r\n")):
        _fail("invalid_manifest", "Ungültiger relativer Werkzeugpfad.")
    return Path(*path.parts)


def _json(path: Path) -> dict[str, Any]:
    _safe_path(path)
    if path.stat().st_size > 4 * CHUNK:
        _fail("invalid_manifest", "Werkzeugmanifest ist zu groß oder beschädigt.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        _fail("invalid_manifest", "Werkzeugmanifest ist beschädigt.")
    if not isinstance(value, dict):
        _fail("invalid_manifest", "Werkzeugmanifest ist beschädigt.")
    return value


def load_lock() -> dict[str, Any]:
    lock = _json(LOCK_PATH)
    if lock.get("format_version") != 1 or lock.get("platform") != "win-64":
        _fail("invalid_lock", "Unbekanntes Werkzeug-Lockformat.")
    seen = set()
    for package in [lock["bootstrap"], *lock["packages"]]:
        filename = package["fn"]
        if (Path(filename).name != filename or not re.fullmatch(r"[a-zA-Z0-9_.-]+", filename)
                or filename in seen or not re.fullmatch(r"[0-9a-f]{64}", package["sha256"])
                or type(package["size"]) is not int or package["size"] <= 0
                or not package["url"].startswith("https://conda.anaconda.org/conda-forge/")
                or package["url"].rsplit("/", 1)[-1] != filename or not package["license"]):
            _fail("invalid_lock", "Werkzeug-Lock enthält eine ungültige Paketquelle.")
        seen.add(filename)
        for name in package["license_files"]:
            _relative(name)
    return lock


def _hash(path: Path) -> str:
    _safe_path(path)
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _verified(path: Path, expected: dict[str, Any]) -> None:
    if path.stat().st_size != expected["size"] or _hash(path) != expected["sha256"]:
        _fail("artifact_mismatch", "Paket fehlt oder SHA-256 stimmt nicht: " + path.name)


def _windows() -> None:
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        _fail("unsupported_platform", "Dieses Werkzeugsetup benötigt Windows x64.")


def _seconds(value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        _fail("invalid_timeout", "Zeitbudget muss positiv und endlich sein.")
    return value


def _memory(value: int) -> int:
    if type(value) is not int or value <= 0 or value * CHUNK > (1 << (8 * ctypes.sizeof(ctypes.c_size_t))) - 1:
        _fail("invalid_memory_budget", "RAM-Budget in MiB muss positiv und als Windows SIZE_T darstellbar sein.")
    return value * CHUNK


def _write(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _new_target(target: Path) -> Path:
    target = _safe_path(target, existing=False)
    target.mkdir(mode=0o700)  # Exclusive creation; never change an existing ACL.
    identity = target.stat().st_dev, target.stat().st_ino
    _protect(target, target, _windows_sid())
    _owned_directory(target, identity)
    return target


def preflight(cache: Path, bootstrap: Path | None = None) -> tuple[dict[str, Any], list[Path], Path]:
    """Read-only: authenticate every local input before creating any target."""
    _windows()
    lock = load_lock()
    cache = _safe_path(cache, directory=True)
    paths = []
    for package in lock["packages"]:
        candidates = sorted(cache.rglob(package["fn"]))
        if not candidates:
            _fail("package_missing", "Geprüftes Paket fehlt im Cache: " + package["fn"])
        path = _safe_path(candidates[0])
        _verified(path, package)
        paths.append(path)
    bootstrap = _safe_path(bootstrap or cache / lock["bootstrap"]["fn"])
    _verified(bootstrap, lock["bootstrap"])
    return lock, paths, bootstrap


def _environment(target: Path) -> dict[str, str]:
    """No inherited app/database/proxy/Conda secrets or user configuration."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return {"SystemRoot": root, "WINDIR": root, "COMSPEC": str(Path(root) / "System32/cmd.exe"),
            "PATH": str(Path(root) / "System32"), "TEMP": str(target / "temp"),
            "TMP": str(target / "temp"), "USERPROFILE": str(target / "home"),
            "APPDATA": str(target / "home"), "LOCALAPPDATA": str(target / "home"),
            "PYTHONUTF8": "1"}


def _command(argv: list[str], target: Path, seconds: float, *, memory_mib: int = 1024) -> str:
    """Finite, job-owned command; bounded diagnostics are never echoed."""
    tree = ProcessTree(_memory(memory_mib))
    process = None
    output = target / ("command-output-" + uuid4().hex + ".tmp")
    owned_output: tuple[int, int] | None = None
    try:
        with output.open("xb") as stream:
            info = os.fstat(stream.fileno())
            owned_output = info.st_dev, info.st_ino
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                                       cwd=target, env=_environment(target), shell=False,
                                       **tree.creation_options)
            tree.attach(process)
            end = time.monotonic() + seconds
            while process.poll() is None:
                if time.monotonic() >= end:
                    _fail("command_timeout", "Werkzeugsetup überschritt sein Zeitbudget; neues Ziel für einen neuen Versuch wählen.")
                if output.stat().st_size > CHUNK:
                    _fail("command_output_budget", "Werkzeugdiagnose überschritt ihr Budget.")
                time.sleep(0.02)
            if process.returncode:
                stream.flush()
                with output.open("rb") as diagnostic:
                    with (target / ("diagnostic-" + uuid4().hex + ".txt")).open("xb") as retained:
                        retained.write(diagnostic.read(CHUNK))
                _fail("command_failed", "Werkzeugaufruf fehlgeschlagen; begrenzte Diagnose im neuen Ziel, Voraussetzungen und freien Speicher prüfen.")
        if output.stat().st_size > CHUNK:
            _fail("command_output_budget", "Werkzeugdiagnose überschritt ihr Budget.")
        return output.read_text(encoding="utf-8", errors="replace")
    finally:
        tree.close(process)
        if process is not None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        # Windows job termination and descendant handle release can complete a
        # moment after the leader's wait. Preserve cleanup within a finite bound.
        if owned_output is not None:
            cleanup_end = time.monotonic() + 2
            while os.path.lexists(output):
                _safe_path(output)
                info = output.lstat()
                if (info.st_dev, info.st_ino) != owned_output:
                    _fail("diagnostic_changed", "Eigene Werkzeugdiagnose wurde ersetzt; automatische Löschung verweigert.")
                try:
                    output.unlink()
                    break
                except PermissionError:
                    if time.monotonic() >= cleanup_end:
                        _fail("command_cleanup_failed", "Werkzeugdiagnose blieb nach Prozessende gesperrt; neuen Arbeitslauf wählen und die alte Diagnose lokal prüfen.")
                    time.sleep(0.02)


def _copy_verified(source: Path, destination: Path, expected: dict[str, Any]) -> None:
    # The second hash checks copied bytes against a concurrent cache change.
    _safe_path(source)
    with source.open("rb") as input_stream, destination.open("xb") as output:
        shutil.copyfileobj(input_stream, output, CHUNK)
    _verified(destination, expected)


def _bootstrap(archive: Path, target: Path, lock: dict[str, Any]) -> Path:
    names = ["Library/bin/micromamba.exe", *lock["bootstrap"]["license_files"]]
    with tarfile.open(archive) as package:
        for name in names:
            member = package.getmember(name)
            if not member.isfile():
                _fail("invalid_bootstrap", "Bootstrap enthält unerwartete Dateitypen.")
            destination = target / "bootstrap" / _relative(name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = package.extractfile(member)
            if source is None:
                _fail("invalid_bootstrap", "Bootstrap-Datei fehlt.")
            with source, destination.open("xb") as output:
                shutil.copyfileobj(source, output, CHUNK)
    executable = target / "bootstrap/Library/bin/micromamba.exe"
    if _hash(executable) != lock["bootstrap"]["exe_sha256"]:
        _fail("invalid_bootstrap", "Micromamba-Binärdatei stimmt nicht mit der geprüften Version überein.")
    return executable


def _licenses(target: Path, lock: dict[str, Any]) -> list[dict[str, Any]]:
    inventory = []
    for package in lock["packages"]:
        record = _json(target / "env/conda-meta" / f"{package['name']}-{package['version']}-{package['build']}.json")
        if any(record.get(key) != package[key] for key in ("name", "version", "build", "license")):
            _fail("package_metadata_mismatch", "Installierte Paketidentität stimmt nicht mit dem Lock überein.")
        # Mamba's freshly extracted cache belongs to THIS new target only.
        extracted = _safe_path(Path(record["extracted_package_dir"]), directory=True)
        if not extracted.is_relative_to(target / "mamba-root"):
            _fail("package_metadata_mismatch", "Paketcache liegt außerhalb des neuen Werkzeugverzeichnisses.")
        files = []
        for name in package["license_files"]:
            source = _safe_path(extracted / _relative(name))
            destination = target / "licenses" / package["name"] / _relative(name).relative_to("info/licenses")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as input_stream, destination.open("xb") as output:
                shutil.copyfileobj(input_stream, output, CHUNK)
            files.append(destination.relative_to(target).as_posix())
        inventory.append({"name": package["name"], "version": package["version"], "build": package["build"],
                          "license": package["license"], "url": package["url"], "sha256": package["sha256"],
                          "license_files": files, "license_text_in_package": bool(files)})
    return inventory


def _settings(target: Path, *, tessdata: Path | None = None) -> dict[str, str]:
    binary = target / "env/Library/bin"
    return {"OCR_LANGUAGES": "deu+eng", "OCR_PDFINFO_PATH": str(binary / "pdfinfo.exe"),
            "OCR_PDFTOTEXT_PATH": str(binary / "pdftotext.exe"), "OCR_PDFTOPPM_PATH": str(binary / "pdftoppm.exe"),
            "OCR_TESSERACT_PATH": str(binary / "tesseract.exe"),
            "OCR_TESSDATA_PATH": _native_tessdata_path(tessdata or target / "env/share/tessdata")}


def _native_tessdata_path(path: Path) -> str:
    """Use a read-only OS alias only when native ANSI argv cannot carry the path.

    Tesseract's Windows std::filesystem language listing uses the active ANSI
    code page. A short alias still names the SAME final directory; no junction,
    moved language data, locale change or global 8.3 setting is introduced.
    """
    if os.name != "nt":
        return str(path)
    try:
        str(path).encode("mbcs", errors="strict")
        return str(path)
    except UnicodeEncodeError:
        pass
    _safe_path(path, directory=True)
    alias = _windows_short_path(path)
    if alias is None:
        _fail("native_path_unrepresentable", "Tesseract kann diesen Sprachdatenpfad nicht darstellen und Windows stellt keinen kurzen Alias bereit. --tessdata-parent auf ein vorhandenes ASCII-Verzeichnis setzen; der endgültige Werkzeugpfad darf Unicode enthalten.")
    try:
        alias.encode("mbcs", errors="strict")
    except UnicodeEncodeError:
        _fail("native_path_unrepresentable", "Windows stellt für diesen Tesseract-Sprachdatenpfad keinen passenden kurzen Alias bereit. --tessdata-parent auf ein vorhandenes ASCII-Verzeichnis setzen; die Systemkonfiguration wird nicht verändert.")
    if not os.path.samefile(path, _safe_path(Path(alias), directory=True)):
        _fail("native_path_unrepresentable", "Windows-Sprachdatenalias konnte nicht eindeutig geprüft werden.")
    return alias


def _windows_short_path(path: Path) -> str | None:
    kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    function = kernel.GetShortPathNameW
    function.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    function.restype = ctypes.c_uint
    length = function(str(path), None, 0)
    if not length:
        return None
    buffer = ctypes.create_unicode_buffer(length)
    count = function(str(path), buffer, length)
    return buffer.value if count and count < length else None


def _probe(target: Path, seconds: float, *, tessdata: Path | None = None, memory_mib: int = 1024) -> dict[str, Any]:
    import reportlab
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    from backend.services.ocr_service import OCRLimits, extract_text_with_details

    settings = _settings(target, tessdata=tessdata)
    image = Image.new("RGB", (1400, 420), "white")
    font = ImageFont.truetype(str(Path(reportlab.__file__).parent / "fonts/Vera.ttf"), 62)
    draw = ImageDraw.Draw(image)
    draw.text((35, 90), "WINDOWS OCR ORIGINAL 161803", fill="black", font=font)
    draw.text((35, 220), "Gesamtbetrag: 1.234,56", fill="black", font=font)
    png = io.BytesIO()
    image.save(png, format="PNG")
    pdf = io.BytesIO()
    document = canvas.Canvas(pdf, pagesize=(700, 210))
    document.drawImage(ImageReader(image), 0, 0, width=700, height=210)
    document.showPage()
    document.save()
    limits = OCRLimits(languages=settings["OCR_LANGUAGES"], pdfinfo_path=settings["OCR_PDFINFO_PATH"],
                       pdftotext_path=settings["OCR_PDFTOTEXT_PATH"], pdftoppm_path=settings["OCR_PDFTOPPM_PATH"],
                       tesseract_path=settings["OCR_TESSERACT_PATH"], tessdata_path=settings["OCR_TESSDATA_PATH"],
                       timeout_seconds=seconds, max_ram_bytes=_memory(memory_mib))
    results = {}
    for extension, source in (("png", png.getvalue()), ("pdf", pdf.getvalue())):
        before = hashlib.sha256(source).hexdigest()
        result = extract_text_with_details(source, extension, limits=limits)
        if (not result.text or "161803" not in result.text or "1.234,56" not in result.text
                or result.ocr_pages != 1 or result.embedded_text_pages != 0
                or hashlib.sha256(source).hexdigest() != before):
            _fail("recognition_probe_failed", "Die echte PNG-/Raster-PDF-Erkennungsprobe wurde nicht bestanden.")
        results[extension] = {"original_sha256": before, "bytes": len(source), "ocr_pages": result.ocr_pages,
                              "embedded_text_pages": result.embedded_text_pages,
                              "recognized_marker": "161803", "recognized_amount": "1.234,56"}
    return results


def _native_check(target: Path, lock: dict[str, Any], seconds: float, *, tessdata: Path | None = None,
                  memory_mib: int = 1024) -> dict[str, Any]:
    for relative, expected in lock["critical_files"].items():
        _verified(_safe_path(target / "env" / _relative(relative)), expected)
    versions = {}
    for name in ("pdfinfo", "pdftotext", "pdftoppm", "tesseract"):
        flag = "--version" if name == "tesseract" else "-v"
        output = _command([str(target / f"env/Library/bin/{name}.exe"), flag], target, seconds, memory_mib=memory_mib)
        expected = "5.5.3" if name == "tesseract" else "26.09.0"
        if not re.search(r"\b" + re.escape(expected) + r"\b", output):
            _fail("tool_version_mismatch", "Werkzeugversion stimmt nicht mit dem geprüften Lock überein.")
        versions[name] = expected
    languages = _command([str(target / "env/Library/bin/tesseract.exe"), "--tessdata-dir",
                          _settings(target, tessdata=tessdata)["OCR_TESSDATA_PATH"], "--list-langs"], target, seconds,
                         memory_mib=memory_mib).splitlines()
    if not {"deu", "eng"}.issubset({line.strip() for line in languages}):
        _fail("language_missing", "Die geprüften Sprachdaten deu und eng sind nicht verfügbar.")
    return {"versions": versions, "languages": ["deu", "eng"],
            "recognition": _probe(target, seconds, tessdata=tessdata, memory_mib=memory_mib)}


def _tessdata_sidecar(target: Path, parent: Path, lock: dict[str, Any]) -> dict[str, Any]:
    """Explicit new persistent ASCII language dir for volumes without 8.3 aliases."""
    parent = _safe_path(parent, directory=True)
    if not str(parent).isascii():
        _fail("invalid_tessdata_parent", "Für --tessdata-parent ein vorhandenes ASCII-Verzeichnis wählen.")
    sidecar = _new_target(parent / ("ocr-data-" + uuid4().hex[:12]))
    files = {}
    for language in ("deu", "eng"):
        relative = f"share/tessdata/{language}.traineddata"
        expected = lock["critical_files"][relative]
        source = target / "env" / relative
        _verified(source, expected)
        destination = sidecar / f"{language}.traineddata"
        _copy_verified(source, destination, expected)
        files[destination.name] = expected["sha256"]
    source_license = target / "licenses/tesseract/tesseract/LICENSE"
    with _safe_path(source_license).open("rb") as input_stream, (sidecar / "TESSERACT_LICENSE").open("xb") as output:
        shutil.copyfileobj(input_stream, output, CHUNK)
    files["TESSERACT_LICENSE"] = _hash(sidecar / "TESSERACT_LICENSE")
    manifest = {"format_version": 1, "state": "verified", "tool_target": str(target),
                "lock_sha256": _hash(LOCK_PATH), "license": "Apache-2.0", "license_source": str(source_license),
                "source_package": next(package for package in lock["packages"] if package["name"] == "tesseract"),
                "original_sha256": {language: files[f"{language}.traineddata"] for language in ("deu", "eng")},
                "files": files}
    _write(sidecar / "tessdata-source.json", manifest)
    return {"path": str(sidecar), "manifest_sha256": _hash(sidecar / "tessdata-source.json"), "files": files}


def _verify_sidecar(target: Path, record: dict[str, Any]) -> Path:
    path = _safe_path(Path(record["path"]), directory=True)
    _verify_private(path, path, _windows_sid())
    manifest_path = path / "tessdata-source.json"
    if _hash(manifest_path) != record["manifest_sha256"]:
        _fail("tessdata_changed", "Sprachdatenmanifest wurde verändert; neues geprüftes Werkzeugziel wählen.")
    manifest = _json(manifest_path)
    files = {child.name: _hash(child) for child in path.iterdir() if child.name != "tessdata-source.json"}
    if (files != record["files"] or manifest.get("files") != files
            or manifest.get("lock_sha256") != _hash(LOCK_PATH) or manifest.get("tool_target") != str(target)):
        _fail("tessdata_changed", "Private Sprachdaten stimmen nicht mit dem geprüften Werkzeugziel überein.")
    return path


def _seal_files(target: Path) -> dict[str, str]:
    # Includes DLLs, all traineddata, package metadata, licenses and bootstrap.
    return {path.relative_to(target).as_posix(): _hash(path)
            for directory in ("env", "licenses", "bootstrap")
            for path in sorted((target / directory).rglob("*")) if path.is_file()}


def _install_paths(cache: Path, target: Path, staging_parent: Path | None) -> tuple[Path, Path | None]:
    target = _safe_path(target, existing=False)
    cache = _safe_path(cache, directory=True)
    if target.is_relative_to(cache):
        _fail("target_in_source_cache", "Das neue Werkzeugziel muss außerhalb des Quellcaches liegen.")
    if staging_parent is None:
        if not str(target).isascii():
            _fail("staging_required", "Micromamba benötigt zum Entpacken einen ASCII-Arbeitspfad. --staging-parent auf ein vorhandenes ASCII-Verzeichnis setzen; das endgültige Werkzeugziel darf Unicode enthalten.")
        return target, None
    staging_parent = _safe_path(staging_parent, directory=True)
    if not str(staging_parent).isascii() or staging_parent.is_relative_to(cache):
        _fail("invalid_staging_parent", "ASCII-Arbeitsverzeichnis außerhalb des Quellcaches wählen.")
    return target, staging_parent


def _owned_directory(path: Path, expected: tuple[int, int]) -> None:
    _safe_path(path, directory=True)
    info = path.stat()
    if (info.st_dev, info.st_ino) != expected:
        _fail("target_changed", "Neu angelegtes Werkzeugverzeichnis wurde ersetzt; Veröffentlichung verweigert.")


def _publish_new_prefix(workspace: Path, target: Path, *, workspace_identity: tuple[int, int] | None = None,
                        target_identity: tuple[int, int] | None = None) -> None:
    """Move only our own new runtime dirs; existing destinations are forbidden."""
    workspace_identity = workspace_identity or (workspace.stat().st_dev, workspace.stat().st_ino)
    target_identity = target_identity or (target.stat().st_dev, target.stat().st_ino)
    _owned_directory(workspace, workspace_identity)
    _owned_directory(target, target_identity)
    # Validate every source before any move; no recursive shell operations.
    for directory in ("env", "licenses", "bootstrap"):
        source = _safe_path(workspace / directory, directory=True)
        for child in source.rglob("*"):
            _safe_path(child, directory=child.is_dir())
        if (target / directory).exists():
            _fail("target_changed", "Das neue Ziel wurde verändert; keine vorhandenen Dateien ersetzen.")
    for directory in ("env", "licenses", "bootstrap"):
        source, destination = workspace / directory, target / directory
        _owned_directory(workspace, workspace_identity)
        _owned_directory(target, target_identity)
        _safe_path(destination, existing=False)
        try:
            source.rename(destination)
        except OSError as exc:
            if exc.errno != errno.EXDEV and getattr(exc, "winerror", None) != 17:
                raise
            # Cross-volume: copy into a NEW dir, retain the private stage.
            shutil.copytree(source, destination)
    _owned_directory(target, target_identity)


def install(cache: Path, target: Path, bootstrap: Path | None = None, *, seconds: float = 900,
            staging_parent: Path | None = None, tessdata_parent: Path | None = None, memory_mib: int = 1024) -> dict[str, Any]:
    seconds = _seconds(seconds)
    _memory(memory_mib)
    lock, sources, bootstrap_source = preflight(cache, bootstrap)
    target, staging_parent = _install_paths(cache, target, staging_parent)
    if tessdata_parent is not None:
        tessdata_parent = _safe_path(tessdata_parent, directory=True)
        if not str(tessdata_parent).isascii() or tessdata_parent.is_relative_to(_safe_path(cache, directory=True)):
            _fail("invalid_tessdata_parent", "Für --tessdata-parent ein vorhandenes ASCII-Verzeichnis außerhalb des Quellcaches wählen.")
    target = _new_target(target)
    target_identity = target.stat().st_dev, target.stat().st_ino
    # Keep native cache paths short. Windows archive libraries still encounter
    # MAX_PATH for deeply nested package documentation in a long work prefix.
    workspace = _new_target(staging_parent / ("ocr-" + uuid4().hex[:12])) if staging_parent else target
    workspace_identity = workspace.stat().st_dev, workspace.stat().st_ino
    try:
        for name in ("archives", "temp", "home"):
            (workspace / name).mkdir()
        copied_bootstrap = workspace / "archives" / lock["bootstrap"]["fn"]
        _copy_verified(bootstrap_source, copied_bootstrap, lock["bootstrap"])
        executable = _bootstrap(copied_bootstrap, workspace, lock)
        spec = ["@EXPLICIT"]
        for source, package in zip(sources, lock["packages"], strict=True):
            url = urlsplit(package["url"])
            # Use the exact reviewed HTTPS cache layout. Micromamba 2.9.0's
            # file:// extraction mishandles percent-encoded Windows paths.
            # No network solve/download: every HTTPS artifact is already here.
            copied = workspace / "mamba-root/pkgs" / url.scheme / url.netloc / _relative(url.path.lstrip("/"))
            copied.parent.mkdir(parents=True, exist_ok=True)
            _copy_verified(source, copied, package)
            # SHA-256 was checked above; MD5 syntax is the documented explicit format.
            spec.append(package["url"] + "#" + package["md5"])
        specification = workspace / "explicit.txt"
        specification.write_text("\n".join(spec) + "\n", encoding="utf-8")
        _command([str(executable), "create", "--no-rc", "--no-env", "--offline", "--yes",
                  "--root-prefix", str(workspace / "mamba-root"), "--prefix", str(workspace / "env"),
                  "--relocate-prefix", str(target / "env"),
                  "--file", str(specification), "--always-copy", "--no-shortcuts", "--skip-run-link-scripts"],
                 workspace, seconds, memory_mib=memory_mib)
        inventory = _licenses(workspace, lock)
        if workspace != target:
            _publish_new_prefix(workspace, target, workspace_identity=workspace_identity, target_identity=target_identity)
            for name in ("temp", "home"):
                (target / name).mkdir()
        sidecar = _tessdata_sidecar(target, tessdata_parent, lock) if tessdata_parent else None
        tessdata = Path(sidecar["path"]) if sidecar else None
        native = _native_check(target, lock, seconds, tessdata=tessdata, memory_mib=memory_mib)
        manifest = {"format_version": 1, "state": "verified", "lock_sha256": _hash(LOCK_PATH),
                    "platform": "win-64", "configuration": _settings(target, tessdata=tessdata), "bootstrap": lock["bootstrap"],
                    "packages": inventory, "native": native, "files": _seal_files(target),
                    "staging_workspace": str(workspace) if workspace != target else None, "tessdata_sidecar": sidecar}
        _write(target / "ocr-toolchain.json", manifest)
        return {"state": "verified", "package_count": len(inventory), "configuration": _settings(target, tessdata=tessdata),
                "native": native, "manifest": str(target / "ocr-toolchain.json"),
                "staging_workspace": manifest["staging_workspace"], "tessdata_sidecar": sidecar}
    except BaseException:
        # No success marker, no existing-target cleanup, and no app activation.
        raise


def verify(target: Path, *, seconds: float = 90, memory_mib: int = 1024) -> dict[str, Any]:
    _windows()
    seconds = _seconds(seconds)
    _memory(memory_mib)
    target = _safe_path(target, directory=True)
    _verify_private(target, target, _windows_sid())
    manifest = _json(target / "ocr-toolchain.json")
    if manifest.get("state") != "verified" or manifest.get("lock_sha256") != _hash(LOCK_PATH):
        _fail("manifest_mismatch", "Unvollständige oder abweichende Werkzeuginstallation; neues Ziel wählen.")
    tessdata = _verify_sidecar(target, manifest["tessdata_sidecar"]) if manifest.get("tessdata_sidecar") else None
    if manifest.get("configuration") != _settings(target, tessdata=tessdata):
        _fail("prefix_moved", "Werkzeugpräfix wurde verschoben; am neuen Ziel frisch installieren.")
    files = _seal_files(target)
    if files != manifest.get("files"):
        _fail("runtime_changed", "Werkzeugdateien wurden verändert; geprüftes neues Ziel installieren.")
    # Verification's temporary diagnostic file is new and removed by _command.
    return {"state": "verified", "configuration": _settings(target, tessdata=tessdata),
            "native": _native_check(target, load_lock(), seconds, tessdata=tessdata, memory_mib=memory_mib)}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _fail("download_redirect", "Paketquelle wurde umgeleitet; Lockquelle ausdrücklich neu prüfen.")


def fetch(target: Path, *, seconds: float = 900) -> dict[str, Any]:
    """Opt-in HTTPS download of ONLY the exact reviewed artifacts to a NEW cache."""
    _windows()
    seconds = _seconds(seconds)
    lock = load_lock()
    target = _new_target(target)
    # Never silently inherit proxy credentials or execute downloaded code.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    end = time.monotonic() + seconds
    for package in [lock["bootstrap"], *lock["packages"]]:
        remaining = end - time.monotonic()
        if remaining <= 0:
            _fail("download_timeout", "Downloadzeitbudget überschritten; neues Cacheziel für erneuten Versuch wählen.")
        destination = target / package["fn"]
        with opener.open(package["url"], timeout=min(30, remaining)) as response, destination.open("xb") as output:
            if response.status != 200:
                _fail("download_failed", "Die festgelegte Paketquelle ist nicht verfügbar.")
            total = 0
            while chunk := response.read(CHUNK):
                total += len(chunk)
                if total > package["size"] or time.monotonic() >= end:
                    _fail("download_budget", "Paketdownload überschritt die festgelegte Größe oder Zeit.")
                output.write(chunk)
        _verified(destination, package)
    _write(target / "cache-verified.json", {"lock_sha256": _hash(LOCK_PATH), "artifacts": len(lock["packages"]) + 1})
    return {"state": "verified_cache", "artifacts": len(lock["packages"]) + 1, "cache": str(target)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicit private Windows OCR tool setup; no application activation.")
    sub = parser.add_subparsers(dest="operation", required=True)
    for name in ("preflight", "install"):
        child = sub.add_parser(name)
        child.add_argument("--package-cache", required=True, type=Path)
        child.add_argument("--bootstrap-archive", type=Path)
        if name == "install":
            child.add_argument("--target", required=True, type=Path)
            child.add_argument("--timeout", type=float, default=900)
            child.add_argument("--staging-parent", type=Path)
            child.add_argument("--tessdata-parent", type=Path)
            child.add_argument("--memory-mib", type=int, default=1024)
    for name in ("verify", "fetch"):
        child = sub.add_parser(name)
        child.add_argument("--target", required=True, type=Path)
        child.add_argument("--timeout", type=float, default=90 if name == "verify" else 900)
        if name == "verify":
            child.add_argument("--memory-mib", type=int, default=1024)
    args = parser.parse_args(argv)
    try:
        if args.operation == "preflight":
            lock, _, _ = preflight(args.package_cache, args.bootstrap_archive)
            result = {"state": "verified_inputs", "package_count": len(lock["packages"]), "writes": 0}
        elif args.operation == "install":
            result = install(args.package_cache, args.target, args.bootstrap_archive, seconds=args.timeout,
                             staging_parent=args.staging_parent, tessdata_parent=args.tessdata_parent, memory_mib=args.memory_mib)
        elif args.operation == "verify":
            result = verify(args.target, seconds=args.timeout, memory_mib=args.memory_mib)
        else:
            result = fetch(args.target, seconds=args.timeout)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except ToolSetupError as exc:
        print(json.dumps({"code": exc.code, "message": str(exc)}, ensure_ascii=True), file=sys.stderr)
    except OCRProcessingError as exc:
        print(json.dumps({"code": exc.code, "message": exc.message}, ensure_ascii=True), file=sys.stderr)
    except (OSError, BackupError, ValueError, ImportError, KeyError, TypeError, tarfile.TarError):
        # Paths/URLs and inherited configuration may contain secrets: no raw exception output.
        print(json.dumps({"code": "setup_failed", "message": "Werkzeugsetup nicht abgeschlossen. Voraussetzungen, Cache, freien Speicher und Rechte prüfen; ein neues Ziel wählen."}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
