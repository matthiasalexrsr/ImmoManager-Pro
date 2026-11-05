"""A browser-only or partially collected Qt build must never become an installer."""
import json
from pathlib import Path

import pytest

from tools.desktop_bundle import mac_bundle_versions, required_groups, write_runtime_manifest
from tools.qt_sources import is_notice


def test_conflicting_global_vendor_icu_cannot_be_packaged(tmp_path):
    root = fake_native_payload(tmp_path, "win32")
    (root / "_internal/icuuc.dll").write_bytes(b"Synthetic incompatible vendor ICU")
    with pytest.raises(RuntimeError, match="Windows ICU"):
        write_runtime_manifest(root, target="win32")


def test_windows_analysis_has_a_private_search_path_and_restores_it(monkeypatch):
    import os
    import sys
    from types import SimpleNamespace

    from tools.desktop_bundle import isolated_native_analysis
    if sys.platform != "win32":
        pytest.skip("Native Windows dependency search check")
    monkeypatch.setattr("tools.desktop_bundle.metadata.distribution",
                        lambda name: SimpleNamespace(locate_file=lambda package: Path.cwd() / "synthetic-wheel" / package))
    original = os.environ["PATH"]
    polluted = original + os.pathsep + r"C:\synthetic-unrelated-poppler\bin"
    monkeypatch.setenv("PATH", polluted)
    observed = []
    def fake_factory():
        observed.append(os.environ["PATH"])
        return SimpleNamespace(binaries=[])
    isolated_native_analysis(fake_factory)
    assert observed and "synthetic-unrelated-poppler" not in observed[0]
    assert os.environ["PATH"] == polluted
    def failing_factory():
        raise RuntimeError("Isolated build fixture")
    with pytest.raises(RuntimeError, match="fixture"):
        isolated_native_analysis(failing_factory)
    assert os.environ["PATH"] == polluted


def fake_native_payload(tmp_path, target):
    root = tmp_path / "application"
    (root / "_internal").mkdir(parents=True)
    for group in required_groups(target):
        (root / "_internal" / sorted(group)[0]).write_bytes(b"isolated deployment fixture")
    locale = root / "_internal/PySide6/qtwebengine_locales"
    locale.mkdir(parents=True)
    for language in ("de", "en-US"):
        (locale / (language + ".pak")).write_bytes(language.encode())
    return root


@pytest.mark.parametrize("target", ["win32", "darwin", "linux"])
def test_deployment_manifest_requires_every_native_component_and_locales(tmp_path, target):
    root = fake_native_payload(tmp_path, target)
    value = write_runtime_manifest(root, target=target)
    assert value["launch_modes"] == ["standalone", "browser"]
    assert value["workspaces"] == ["own", "demo-bw"]
    assert value["native_required_files"]
    assert value == json.loads((root / "_internal/desktop-runtime.json").read_text())
    resource = root / "_internal/qtwebengine_resources.pak"
    resource.unlink()
    with pytest.raises(RuntimeError, match="incomplete"):
        write_runtime_manifest(root, target=target)


def test_deployment_without_german_locale_is_not_accepted(tmp_path):
    root = fake_native_payload(tmp_path, "win32")
    (root / "_internal/PySide6/qtwebengine_locales/de.pak").unlink()
    with pytest.raises(RuntimeError, match="locale"):
        write_runtime_manifest(root, target="win32")


def test_unknown_deployment_platform_is_rejected():
    with pytest.raises(RuntimeError, match="layout"):
        required_groups("android")


@pytest.mark.parametrize("version,build", [("2.0.0-beta.1", "2.0.0b1"), ("2.1.0-rc.2", "2.1.0fc2"), ("2.1.0", "2.1.0")])
def test_mac_bundle_uses_valid_apple_versions_from_project(tmp_path, version, build):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion="' + version + '"\n')
    value = mac_bundle_versions(tmp_path)
    assert value["CFBundleVersion"] == build
    assert all(part.isdecimal() for part in value["CFBundleShortVersionString"].split('.'))


@pytest.mark.parametrize("name,expected", [
    ("qtbase/LICENSES/LGPL-3.0-only.txt", True),
    ("qtwebengine/src/3rdparty/chromium/third_party/icu/LICENSE", True),
    ("qtwebengine/qt_attribution.json", True),
    ("qtbase/src/gui/license.cpp", False),
    ("qtbase/tests/foo.cpp", False),
])
def test_qt_original_legal_texts_are_collected_without_source_code(name, expected):
    assert is_notice(name) == expected
