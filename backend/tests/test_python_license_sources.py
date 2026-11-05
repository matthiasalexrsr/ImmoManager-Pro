"""Qt wheels without texts must still ship their verified exact upstream licenses."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import qt_sources
from tools import third_party_notices as notices


def distribution(name="PySide6", version="6.11.3", files=()):
    return SimpleNamespace(metadata={"Name": name}, version=version, files=files,
                           locate_file=lambda path: path)


@pytest.fixture
def source_inventory(tmp_path):
    manifest = qt_sources.manifest()
    source = next(row for row in manifest["archives"] if row["module"] == "pyside-setup")
    folder = tmp_path / "qt-6.11.3"
    (folder / "pyside-setup").mkdir(parents=True)
    path = folder / "pyside-setup/fixture.txt"
    path.write_bytes(b"Unchanged upstream license fixture.\n")
    index = {"version": "6.11.3", "sources": manifest["archives"], "files": [
        {"archive": source["filename"], "file": "pyside-setup/fixture.txt",
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    ]}

    def save():
        (folder / "index.json").write_text(json.dumps(index), encoding="utf-8")

    save()
    return tmp_path, source, path, index, save


@pytest.mark.parametrize("name", ["PySide6", "shiboken6", "PySide6_Essentials", "PySide6_Addons"])
def test_qt_wheels_without_license_files_use_exact_verified_source(name, source_inventory):
    output, source, path, _, _ = source_inventory
    files, upstream = notices.python_license_sources(distribution(name), output)
    assert files == [path]
    assert upstream == source
    assert upstream["url"].endswith("pyside-setup-everywhere-src-6.11.3.tar.xz")


def test_wheel_license_text_is_preferred_and_other_packages_get_no_fallback(tmp_path):
    license_path = tmp_path / "LICENSE"
    license_path.write_bytes(b"Wheel's original license.\n")
    assert notices.python_license_sources(distribution(files=[license_path]), tmp_path) == ([license_path], None)
    assert notices.python_license_sources(distribution("unreviewed-package"), tmp_path) == ([], None)


def test_another_qt_version_cannot_reuse_reviewed_release_text(source_inventory):
    output, _, _, _, _ = source_inventory
    with pytest.raises(RuntimeError, match="Missing exact Qt Python license source"):
        notices.python_license_sources(distribution(version="6.11.2"), output)


@pytest.mark.parametrize("field,value", [("version", "6.11.2"), ("sources", [])])
def test_source_inventory_must_match_exact_pinned_archive(field, value, source_inventory):
    output, _, _, index, save = source_inventory
    index[field] = value
    save()
    with pytest.raises(RuntimeError, match="Mismatched Qt Python license source inventory"):
        notices.python_license_sources(distribution(), output)


def test_changed_original_text_blocks_license_collection(source_inventory):
    output, _, path, _, _ = source_inventory
    path.write_bytes(b"Changed after source verification.\n")
    with pytest.raises(RuntimeError, match="Changed Qt Python license source text"):
        notices.python_license_sources(distribution(), output)


@pytest.mark.parametrize("relative", ["../outside.txt", "/outside.txt", "other-module/LICENSE.txt"])
def test_source_notice_paths_cannot_escape_verified_module(relative, source_inventory):
    output, _, _, index, save = source_inventory
    index["files"][0]["file"] = relative
    save()
    with pytest.raises(RuntimeError, match="Invalid Qt Python license source path"):
        notices.python_license_sources(distribution(), output)


def test_inventory_without_original_pyside_texts_still_blocks_release(source_inventory):
    output, _, _, index, save = source_inventory
    index["files"] = []
    save()
    with pytest.raises(RuntimeError, match="Missing Qt Python original license texts"):
        notices.python_license_sources(distribution(), output)


def test_import_path_types_remain_platform_independent():
    assert notices.license_file(Path("package.dist-info/LICENSE.txt"))
    assert not notices.license_file(Path("package/license_check.py"))
