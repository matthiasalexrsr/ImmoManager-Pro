"""Build the Windows installer from a completed, private-data-free frozen bundle.

The compiler is an explicit local prerequisite. This helper never downloads or
installs software, requests elevation, or changes the user's installation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "FE5C3565-4782-59C1-9EAC-E3FE6641E286"
COMPILER_VERSION = "6.7.4"
COMPILER_DOWNLOAD = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe"
COMPILER_DOWNLOAD_SHA256 = "a549929319f9120716677c685535ca4671e4b937b5fdc87e2585f32d8eb30e8c"
EXES = ("ImmoManager-Pro.exe", "ImmoManager-Pro-CLI.exe")
LAUNCH_MODES = ("standalone", "browser")
MAX_DESTINATION_UTF16 = 240
DESTINATION_TEMP_RESERVE_UTF16 = 19


def native(path: Path) -> Path:
    """Long-path-safe I/O without changing the public/canonical path strings."""
    text = str(path.absolute())
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return Path(text)
    return Path("\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text)


def digest(path: Path) -> str:
    with native(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def version_info(version: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?", version)
    if not match or any(int(part) > 65535 for part in match.groups()):
        raise ValueError("Ungültige Windows-Paketversion: " + version)
    return ".".join(str(int(part)) for part in match.groups()) + ".0"


def utf16_length(value: str | Path) -> int:
    return len(str(value).encode("utf-16-le")) // 2


def installation_path_limits(payload_directory: str, files: list[dict]) -> dict:
    # Inno's final rename and some bundled native tools use legacy Win32 paths.
    # Reserve 19 code units below the 259-character non-NUL path maximum.
    installed = [payload_directory + "/" + row["path"] for row in files]
    installed += ["installation.json", ".immomanager-installation-id", "Installationshinweise.txt", "unins000.exe"]
    longest = max(map(utf16_length, installed))
    maximum = MAX_DESTINATION_UTF16 - 1 - longest
    if maximum < 4:
        raise ValueError("Interne Paketpfade lassen keinen sicheren Windows-Installationsordner zu.")
    return {"max_install_directory_utf16": maximum,
            "max_destination_path_utf16": MAX_DESTINATION_UTF16,
            "destination_temporary_reserve_utf16": DESTINATION_TEMP_RESERVE_UTF16,
            "longest_installed_relative_path_utf16": longest}


def desktop_runtime(bundle: Path, files: list[dict]) -> dict:
    marker_path = bundle / "_internal/desktop-runtime.json"
    marker = json.loads(native(marker_path).read_text(encoding="utf-8-sig"))
    if marker.get("engine") != "pyside6-qtwebengine" or not re.fullmatch(r"\d+\.\d+\.\d+", marker.get("version", "")):
        raise ValueError("Das Paket enthält keinen geprüften eigenständigen Desktop-Runtime-Marker.")
    if marker.get("workspaces") != ["own", "demo-bw"]:
        raise ValueError("Das Paket muss die eigene Verwaltung und den Demo-Bestand unterstützen.")
    required = marker.get("native_required_files")
    if not isinstance(required, list) or not required or not all(isinstance(path, str) for path in required):
        raise ValueError("Der Desktop-Runtime-Marker enthält keine gültigen nativen Paketpfade.")
    available = {row["path"]: row for row in files}
    if len(set(required)) != len(required):
        raise ValueError("Doppelte Desktop-Runtime-Pfade im Paketmarker.")
    for relative in required:
        path = PurePosixPath(relative)
        if path.is_absolute() or "\\" in relative or ":" in relative or any(part in {".", "..", ""} for part in relative.split("/")):
            raise ValueError("Desktop-Runtime-Pfad verlässt das Paket.")
        if relative not in available or available[relative]["bytes"] == 0:
            raise ValueError("Erforderliche Desktop-Runtime-Datei fehlt: " + relative)
    names = {PurePosixPath(path).name.casefold() for path in required}
    essential = {"qtwebengineprocess.exe", "qt6webenginecore.dll", "qt6webenginewidgets.dll",
                 "qwindows.dll", "icudtl.dat", "qtwebengine_resources.pak"}
    if not essential <= names or not any("qtwebengine_locales" in PurePosixPath(path).parts and path.endswith(".pak") for path in required):
        raise ValueError("Die eigenständige Desktop-Runtime ist unvollständig.")
    return {"engine": marker["engine"], "version": marker["version"], "workspaces": marker["workspaces"],
            "native_required_files": required, "marker_sha256": digest(marker_path)}


def inventory(bundle: Path, version: str) -> dict:
    bundle = bundle.resolve(strict=True)
    for name in EXES:
        with native(bundle / name).open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError("Windows-Programm fehlt oder ist ungültig: " + name)
    bundled_project = native(bundle / "_internal" / "pyproject.toml")
    if tomllib.loads(bundled_project.read_text(encoding="utf-8-sig"))["project"]["version"] != version:
        raise ValueError("Das Windows-Bundle und die Quellversion stimmen nicht überein.")
    profile = json.loads(native(bundle / "_internal/frontend/dist/product-profile.json").read_text(encoding="utf-8"))
    if profile.get("purpose") not in {"core", "licensed"}:
        raise ValueError("Nur ein Core- oder freigegebenes Lizenzprofil darf als Benutzer-Installer ausgegeben werden.")
    if not isinstance(profile.get("document_tools"), bool) or (profile["document_tools"] and profile["purpose"] != "licensed"):
        raise ValueError("Ungültiges Dokumentenprofil im Installationspaket.")
    files = []
    for folder, dirs, names in os.walk(native(bundle), followlinks=False):
        parent = Path(folder)
        relative_parent = parent.relative_to(native(bundle))
        for name in [*dirs, *names]:
            path = parent / name
            attributes = path.lstat()
            if stat.S_ISLNK(attributes.st_mode) or getattr(attributes, "st_file_attributes", 0) & 0x400:
                raise ValueError("Verknüpfungen sind im Installationspaket nicht erlaubt: " + str(path))
        if relative_parent == Path(".") and {name.casefold() for name in dirs} & {"data", "uploads", "backups", "secrets", "logs"}:
            raise ValueError("Das Bundle enthält einen privaten Datenordner.")
        for name in names:
            path = parent / name
            relative = path.relative_to(native(bundle)).as_posix()
            lower = name.casefold()
            if lower.startswith(".env") or Path(lower).suffix in {".db", ".sqlite", ".sqlite3"} or any(suffix in lower for suffix in (".db-", ".sqlite-", ".sqlite3-")):
                raise ValueError("Private Konfiguration oder Datenbank im Bundle: " + relative)
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("Nicht reguläre Paketdatei: " + relative)
            if any(character in relative for character in ('\n', '\r', '"')):
                raise ValueError("Ungültiger Paketpfad: " + relative)
            files.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)})
    files.sort(key=lambda item: item["path"])
    payload_sha = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    payload_id = version + "-" + payload_sha[:12]
    runtime = desktop_runtime(bundle, files)
    return {"schema": "immomanager-windows-installation/1", "app_id": APP_ID, "version": version,
            "payload_id": payload_id, "payload_sha256": payload_sha, "payload_directory": "app/" + payload_id,
            "gui_executable": "app/" + payload_id + "/" + EXES[0],
            "cli_executable": "app/" + payload_id + "/" + EXES[1],
            "data_directory": "%LOCALAPPDATA%/ImmoManagerPro", "files": files,
            "launch_modes": list(LAUNCH_MODES), "default_launch_mode": "standalone", "desktop_runtime": runtime,
            **installation_path_limits("app/" + payload_id, files)}


@contextmanager
def compiler_source(bundle: Path, staging: Path, files: list[dict]):
    """Give ISCC a short source name; its compressor does not accept NT prefixes.

    The original source was already inventoried and rejected reparse points.
    This one owned, temporary junction only shortens the compiler's read path.
    rmdir removes the junction itself, never recursively visits its target.
    """
    longest = max((utf16_length(bundle / row["path"]) for row in files), default=0)
    if os.name != "nt" or longest < 240:
        yield bundle
        return
    import _winapi

    alias = staging / "payload"
    _winapi.CreateJunction(str(bundle), str(alias))
    try:
        if max((utf16_length(alias / row["path"]) for row in files), default=0) >= 260:
            raise RuntimeError("Die Paketpfade sind auch im temporären Quellordner zu lang. Einen kürzeren TEMP-Ordner wählen.")
        yield alias
    finally:
        os.rmdir(alias)


def build(bundle: Path, output: Path, compiler: Path, *, root: Path = ROOT) -> Path:
    bundle = bundle.resolve(strict=True)
    output = output.resolve()
    if output == bundle or output.is_relative_to(bundle):
        raise ValueError("Der Installer-Ausgabeordner darf nicht im Bundle liegen.")
    compiler = compiler.resolve(strict=True)
    with (root / "pyproject.toml").open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    numeric_version = version_info(version)
    manifest = inventory(bundle, version)
    output.mkdir(parents=True, exist_ok=True)
    name = "ImmoManager-Pro-" + version + "-Setup-x64"
    installer = output / (name + ".exe")
    if installer.exists():
        raise FileExistsError("Ein vorhandener Installer wird nicht überschrieben: " + str(installer))
    with tempfile.TemporaryDirectory(prefix="immo-installer-") as temporary:
        staging = Path(temporary)
        (staging / "installation.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / ".immomanager-installation-id").write_text(APP_ID + "\n", encoding="ascii")
        with compiler_source(bundle, staging, manifest["files"]) as compiler_bundle:
            used_short_source = compiler_bundle != bundle
            command = [str(compiler), "/Qp", "/DBundleDir=" + str(compiler_bundle), "/DMetadataDir=" + str(staging),
                       "/DAppVersion=" + version, "/DAppFileVersion=" + numeric_version,
                       "/DPayloadId=" + manifest["payload_id"],
                       "/DMaxInstallDirUtf16=" + str(manifest["max_install_directory_utf16"]),
                       "/O" + str(output), "/F" + name,
                       str(root / "packaging/installer/ImmoManager-Pro.iss")]
            # A windowless compiler must use explicit standard handles. Retain
            # compiler diagnostics even if Python itself is redirected.
            compiler_log = installer.with_suffix(".compiler.log")
            try:
                completed = subprocess.run(command, cwd=root, check=True, capture_output=True,
                                           text=True, encoding="utf-8", errors="replace",
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except subprocess.CalledProcessError as failure:
                diagnostics = (failure.stdout or "") + (failure.stderr or "")
                compiler_log.write_text(diagnostics, encoding="utf-8")
                if diagnostics:
                    print(diagnostics[-8000:], file=sys.stderr)
                raise
            else:
                compiler_log.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if not installer.is_file():
        raise RuntimeError("Der Compiler hat keinen Installer erzeugt.")
    receipt = {"schema": "immomanager-installer-build/1", "version": version, "app_id": APP_ID,
               "compiler_version_required": COMPILER_VERSION, "compiler_path": str(compiler),
               "compiler_sha256": digest(compiler), "bundle": str(bundle),
               "compiler_log": compiler_log.name, "compiler_log_sha256": digest(compiler_log),
               "compiler_used_short_source_alias": used_short_source,
               "installation_path_limits": {key: manifest[key] for key in (
                   "max_install_directory_utf16", "max_destination_path_utf16",
                   "destination_temporary_reserve_utf16", "longest_installed_relative_path_utf16")},
               "payload_sha256": manifest["payload_sha256"], "payload_id": manifest["payload_id"],
               "launch_modes": manifest["launch_modes"], "default_launch_mode": manifest["default_launch_mode"],
               "desktop_runtime": manifest["desktop_runtime"],
               "payload_files": len(manifest["files"]), "gui_executable": manifest["gui_executable"],
               "cli_executable": manifest["cli_executable"], "installer": installer.name,
               "installer_bytes": installer.stat().st_size, "installer_sha256": digest(installer)}
    installer.with_suffix(".build.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    installer.with_suffix(".sha256").write_text(receipt["installer_sha256"] + "  " + installer.name + "\n", encoding="ascii")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return installer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist/ImmoManager-Pro")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/installers")
    parser.add_argument("--iscc", type=Path, help="Pfad zum bereits verifizierten Inno Setup 6.7.4 ISCC.exe")
    options = parser.parse_args()
    compiler = options.iscc or (Path(value) if (value := shutil.which("ISCC.exe")) else None)
    if compiler is None:
        parser.error("Inno Setup 6.7.4 fehlt. Einen verifizierten Compiler mit --iscc angeben; siehe packaging/installer/README.md.")
    build(options.dist, options.output, compiler)


if __name__ == "__main__":
    main()
