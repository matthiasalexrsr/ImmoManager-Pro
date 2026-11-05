"""Fail the build if its standalone renderer lacks native deployment files."""
from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
import tomllib
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path

VERSION = "6.11.3"
IMPORTS = ["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "PySide6.QtNetwork",
           "PySide6.QtPrintSupport", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"]


@contextmanager
def windows_build_search_path():
    """Do not let unrelated installed toolchains shadow Windows system DLLs.

    In particular, Qt imports the unversioned Windows ICU API. A vendor's ICU78
    with the same filename but version-suffixed exports is not ABI-compatible.
    This modifies only the private build process and restores its original PATH.
    """
    import os
    if sys.platform != "win32":
        yield
        return
    import ctypes
    buffer = ctypes.create_unicode_buffer(32768)
    if not getattr(ctypes, "windll").kernel32.GetSystemDirectoryW(buffer, len(buffer)):
        raise OSError("Cannot determine the native Windows system directory")
    system = Path(buffer.value)
    original = os.environ.get("PATH")
    paths = [system, system.parent, system / "Wbem", Path(sys.executable).parent,
             Path(sys.prefix) / "Scripts", Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs"]
    for package in ("PySide6", "shiboken6"):
        paths.append(Path(str(metadata.distribution(package).locate_file(package))))
    os.environ["PATH"] = os.pathsep.join(dict.fromkeys(str(path) for path in paths))
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = original


def isolated_native_analysis(factory, *args, **kwargs):
    if sys.platform == "darwin":
        macos_crypto_abi_report()
    with windows_build_search_path():
        result = factory(*args, **kwargs)
    if sys.platform == "win32":
        for destination, source, _kind in result.binaries:
            if destination.replace("\\", "/").casefold() in {"icuuc.dll", "icudt78.dll"}:
                raise RuntimeError("A foreign global ICU runtime would shadow Windows ICU: " + str(source))
    return result


def macos_crypto_linkage(extension: Path) -> dict:
    """Reject the source-wheel OpenSSL collision before creating a broken app.

    Cryptography 50 no longer publishes an Intel macOS wheel. Its default
    source build links Homebrew OpenSSL dynamically, which PyInstaller can
    flatten over the differently versioned libssl used by the Python runtime.
    The upstream-supported static build keeps that independent OpenSSL inside
    the extension instead. Inspect the actual Mach-O rather than its wheel tag.
    """
    command = ["/usr/bin/otool", "-L", str(extension)]
    dependencies = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30).stdout
    libraries = [line.strip().split(" (", 1)[0] for line in dependencies.splitlines()[1:]
                 if " (compatibility version " in line]
    if not libraries:
        raise RuntimeError("otool did not identify the actual cryptography Mach-O dependencies")
    external_openssl = [name for name in libraries
                        if re.fullmatch(r"lib(?:ssl|crypto)(?:\.[0-9]+)*\.dylib", name.rsplit("/", 1)[-1])]
    if external_openssl:
        raise RuntimeError("macOS cryptography must use its own statically linked OpenSSL; external dependencies: "
                           + ", ".join(external_openssl))
    load_commands = subprocess.run(["/usr/bin/otool", "-l", str(extension)], capture_output=True,
                                   text=True, check=True, timeout=30).stdout
    minimum_versions = []
    for block in re.split(r"(?m)^Load command [0-9]+\s*$", load_commands):
        if not re.search(r"(?m)^\s*cmd LC_(?:BUILD_VERSION|VERSION_MIN_MACOSX)\s*$", block):
            continue
        match = re.search(r"(?m)^\s*(?:minos|version) ([0-9]+(?:\.[0-9]+){0,2})\s*$", block)
        if not match:
            raise RuntimeError("Cannot determine the cryptography Mach-O minimum macOS version")
        version = match.group(1)
        parts = tuple(int(part) for part in version.split("."))
        if (*parts, *(0 for _ in range(3 - len(parts)))) > (13, 0, 0):
            raise RuntimeError("cryptography requires macOS " + version + "; the desktop package promises macOS 13")
        minimum_versions.append(version)
    if not minimum_versions:
        raise RuntimeError("The cryptography extension has no recognizable minimum macOS load command")
    return {"extension": str(extension), "sha256": hashlib.sha256(extension.read_bytes()).hexdigest(),
            "dynamic_dependencies": libraries, "external_openssl_dependencies": external_openssl,
            "minimum_macos_versions": minimum_versions, "otool_dependencies": dependencies,
            "otool_load_commands": load_commands}


def macos_crypto_abi_report() -> dict:
    """Exercise both actual OpenSSL consumers and require independent linkage."""
    if sys.platform != "darwin":
        raise RuntimeError("The macOS OpenSSL ABI preflight requires a native macOS host")
    import ssl

    from cryptography.fernet import Fernet
    from cryptography.hazmat.backends.openssl.backend import backend as openssl_backend
    from cryptography.hazmat.bindings import _rust

    report = macos_crypto_linkage(Path(_rust.__file__))
    cipher = Fernet(Fernet.generate_key())
    plaintext = b"Synthetic native OpenSSL ABI preflight; contains no application data."
    if cipher.decrypt(cipher.encrypt(plaintext)) != plaintext:
        raise RuntimeError("The native cryptography encryption roundtrip failed")
    context = ssl.create_default_context()
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise RuntimeError("The native Python TLS context lost certificate verification")
    return {"schema": "immomanager-native-macos-openssl-abi/1", "status": "passed", "python": sys.version,
            "machine": platform.machine(), "cryptography": metadata.version("cryptography"),
            "python_openssl": ssl.OPENSSL_VERSION, "cryptography_openssl": openssl_backend.openssl_version_text(),
            "fernet_roundtrip": True, "python_tls_context": True, **report}


def mac_bundle_versions(root):
    from packaging.version import Version
    value = Version(tomllib.loads((Path(root) / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])
    short = ".".join(str(part) for part in (*value.release, 0, 0)[:3])
    build = short
    if value.pre:
        stage, number = value.pre
        if not 1 <= number <= 255:
            raise RuntimeError("Apple prerelease build numbers must be between 1 and 255")
        build += {"a": "a", "b": "b", "rc": "fc"}[stage] + str(number)
    return {"CFBundleShortVersionString": short, "CFBundleVersion": build}


def verify_versions():
    for name in ("PySide6", "PySide6_Addons", "PySide6_Essentials", "shiboken6"):
        if metadata.version(name) != VERSION:
            raise RuntimeError(f"Desktop engine version mismatch: {name}; expected {VERSION}")


def required_groups(target=None):
    target = target or sys.platform
    common = [{"icudtl.dat"}, {"qtwebengine_resources.pak"}, {"qtwebengine_resources_100p.pak"},
              {"qtwebengine_resources_200p.pak"}]
    if target == "win32":
        return [*common, {"QtWebEngineProcess.exe"}, {"Qt6WebEngineCore.dll"},
                {"Qt6WebEngineWidgets.dll"}, {"qwindows.dll"}]
    if target == "darwin":
        return [*common, {"QtWebEngineProcess"}, {"QtWebEngineCore"},
                {"QtWebEngineWidgets"}, {"libqcocoa.dylib"}]
    if target.startswith("linux"):
        return [*common, {"QtWebEngineProcess"}, {"libQt6WebEngineCore.so.6"},
                {"libQt6WebEngineWidgets.so.6"}, {"libqxcb.so", "libqwayland-egl.so", "libqwayland-generic.so"}]
    raise RuntimeError("No tested standalone deployment layout for " + target)


def write_runtime_manifest(bundle, *, target=None, layout="onedir"):
    root = Path(bundle)
    target = target or sys.platform
    if target == "win32" and any((root / "_internal" / name).exists() for name in ("icuuc.dll", "icudt78.dll")):
        raise RuntimeError("The bundle must use Windows ICU, not a conflicting global toolchain DLL")
    paths = sorted(p for p in root.rglob("*") if p.is_file())
    selected = []
    for names in required_groups(target):
        matches = [p for p in paths if p.name in names]
        if not matches:
            raise RuntimeError("Standalone bundle is incomplete; missing " + "/".join(sorted(names)))
        selected.extend(matches)
    locales = [p for p in paths if p.suffix == ".pak" and p.stem in {"de", "en-US"}
               and "qtwebengine_locales" in str(p)]
    if {p.stem for p in locales} != {"de", "en-US"}:
        raise RuntimeError("Standalone renderer is missing German/English locale data")
    selected.extend(locales)
    entries = []
    for path in sorted(set(selected)):
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        entries.append({"file": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": checksum})
    value = {"schema": "immomanager-desktop-runtime/1", "engine": "pyside6-qtwebengine", "version": VERSION,
             "layout": layout,
             "platform": target, "machine": platform.machine(), "launch_modes": ["standalone", "browser"],
             "default_launch_mode": "standalone", "native_required_files": [entry["file"] for entry in entries],
             "workspaces": ["own", "demo-bw"],
             "files": entries}
    marker = root / ("Resources/desktop-runtime.json" if layout == "macos-app" else "_internal/desktop-runtime.json")
    marker.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return value
