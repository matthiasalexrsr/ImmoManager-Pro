"""Fail the build if its standalone renderer lacks native deployment files."""
from __future__ import annotations

import hashlib
import json
import platform
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
    with windows_build_search_path():
        result = factory(*args, **kwargs)
    if sys.platform == "win32":
        for destination, source, _kind in result.binaries:
            if destination.replace("\\", "/").casefold() in {"icuuc.dll", "icudt78.dll"}:
                raise RuntimeError("A foreign global ICU runtime would shadow Windows ICU: " + str(source))
    return result


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
