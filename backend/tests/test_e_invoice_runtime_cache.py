"""Archive transport/cache integrity; foreign JREs are fixtures, never executed."""

import hashlib
import io
import json
import os
import tarfile
from types import SimpleNamespace

import pytest

from backend.services.e_invoice import asset_bundle, runtime_cache, validator
from tools import prepare_e_invoice


@pytest.fixture
def mac_package(tmp_path):
    root = tmp_path / "signed application.app/Contents/Resources/e-invoice"
    root.mkdir(parents=True)
    archive = root / "pinned-mac-jre.tar.gz"
    with tarfile.open(archive, "w:gz") as target:
        for name, content, mode in [
            ("jdk-21.0.13+9-jre/Contents/Home/bin/java", b"original vendor Mach-O fixture", 0o755),
            ("jdk-21.0.13+9-jre/Contents/Home/legal/java.base/LICENSE", b"official license fixture", 0o644),
        ]:
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(content), mode
            target.addfile(member, io.BytesIO(content))
        link = tarfile.TarInfo("jdk-21.0.13+9-jre/Contents/Home/legal/java.logging/LICENSE")
        link.type, link.linkname = tarfile.SYMTYPE, "../java.base/LICENSE"
        target.addfile(link)
    java = "runtime/jdk-21.0.13+9-jre/Contents/Home/bin/java"
    assets = [{"name": "test-mac-runtime", "filename": archive.name, "extract": "runtime",
               "sha256": asset_bundle.file_sha(archive), "bytes": archive.stat().st_size}]
    jar = root / "validator.jar"
    jar.write_bytes(b"pinned validator fixture")
    assets.append({"name": "test-validator", "filename": jar.name, "sha256": asset_bundle.file_sha(jar)})
    expected = {"format": "fixture-bundle", "platform": "darwin-arm64", "assets": assets, "runtime_mode": "archive-cache"}
    manifest = {**expected, "files": {asset["filename"]: asset["sha256"] for asset in assets}}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert asset_bundle.verify(root, expected)[0] == manifest
    return root, expected, java


@pytest.mark.parametrize("system,machine,compiled,expected", [
    ("Linux", "x86_64", "linux-x86_64", "linux-x64"),
    ("Linux", "aarch64", "linux-aarch64", "linux-arm64"),
    ("Darwin", "arm64", "macosx-13-universal2", "darwin-arm64"),
    ("Darwin", "x86_64", "macosx-13-universal2", "darwin-x64"),
    ("Windows", "AMD64", "win-amd64", "windows-x64"),
    ("Windows", "ARM64", "win-amd64", "windows-x64"),
])
def test_runtime_matches_the_application_architecture(monkeypatch, system, machine, compiled, expected):
    monkeypatch.setattr(asset_bundle.platform, "system", lambda: system)
    monkeypatch.setattr(asset_bundle.platform, "machine", lambda: machine)
    monkeypatch.setattr(asset_bundle.sysconfig, "get_platform", lambda: compiled)
    assert asset_bundle.platform_id() == expected


@pytest.mark.parametrize("system,machine,compiled", [
    ("Windows", "ARM64", "win-arm64"), ("Windows", "x86", "win32"), ("Linux", "riscv64", "linux-riscv64"),
])
def test_unpublished_native_runtime_is_never_invented(monkeypatch, system, machine, compiled):
    monkeypatch.setattr(asset_bundle.platform, "system", lambda: system)
    monkeypatch.setattr(asset_bundle.platform, "machine", lambda: machine)
    monkeypatch.setattr(asset_bundle.sysconfig, "get_platform", lambda: compiled)
    with pytest.raises(ValueError):
        asset_bundle.platform_id()


def test_all_reviewed_targets_have_one_exact_runtime_and_macos_transports_no_macho():
    pins = {
        "linux-arm64": (51266660, "b1734db7ade49c3f6acc6ae06233b8c2dd90e3e2f00f67000ae1c972aaa64d8c"),
        "darwin-arm64": (47935740, "225bab0a09491ef06835488cd942f5d2befa9a0410a2484f0c8bbcf7506ec09a"),
        "darwin-x64": (41902098, "c909674b1c10c261b9a3fb7e9c0efebd303e33f88a4fe84be7135b5e2d711f89"),
    }
    for platform in asset_bundle.SUPPORTED_PLATFORMS:
        configuration = asset_bundle.configuration(target_platform=platform)
        runtime = [asset for asset in configuration["assets"] if asset.get("extract") == "runtime"]
        assert len(runtime) == 1 and runtime[0]["platform"] == platform
        assert (configuration.get("runtime_mode") == "archive-cache") == platform.startswith("darwin-")
        if platform in pins:
            assert (runtime[0]["bytes"], runtime[0]["sha256"]) == pins[platform]


def test_prepare_keeps_original_macos_archive_and_publishes_legal_from_it(mac_package, tmp_path, monkeypatch):
    source, expected, java = mac_package
    monkeypatch.setattr(prepare_e_invoice, "configuration", lambda **kwargs: expected)
    monkeypatch.setattr(prepare_e_invoice, "fetch", lambda asset, cache: source / asset["filename"])
    destination = tmp_path / "distribution"
    prepared = prepare_e_invoice.prepare(destination, target_platform="darwin-arm64")
    assert not (destination / "runtime").exists()
    assert java not in prepared["files"]
    assert asset_bundle.verify(destination, expected)[0] == prepared
    legal = list(asset_bundle.runtime_legal_files(destination, prepared))
    assert len(legal) == 2
    assert {content for _, content, _ in legal} == {b"official license fixture"}
    assert all("Contents/Home/legal/" in name for name, _, _ in legal)


def test_cache_verifies_original_bytes_preserves_executable_and_reuses(mac_package, tmp_path):
    source, expected, java = mac_package
    source_before = {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    cache = tmp_path / "private-data/resource-cache/e-invoice"
    target, manifest, digest = runtime_cache.materialize_runtime_bundle(source, expected, cache_dir=cache)
    assert target.parent == cache.resolve() and len(target.name) == 64
    assert (target / java).read_bytes() == b"original vendor Mach-O fixture"
    assert list((target / "runtime").rglob("java")) == [target / java]
    assert asset_bundle.verify(target, expected, materialized=True) == (manifest, digest)
    assert runtime_cache.materialize_runtime_bundle(source, expected, cache_dir=cache) == (target, manifest, digest)
    assert {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*") if path.is_file()} == source_before
    assert not list(cache.glob(".prepare-*"))
    if os.name != "nt":
        assert target.parent.stat().st_mode & 0o777 == 0o700
        assert (target / java).stat().st_mode & 0o111


def test_rewritten_cache_manifest_cannot_approve_modified_java_and_quarantines_intact(mac_package, tmp_path):
    source, expected, java = mac_package
    cache = tmp_path / "cache"
    target, manifest, _ = runtime_cache.materialize_runtime_bundle(source, expected, cache_dir=cache)
    changed = b"modified executable must not run"
    (target / java).write_bytes(changed)
    manifest["files"][java] = hashlib.sha256(changed).hexdigest()
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (target / "unrecognized-user-note.txt").write_text("preserve me", encoding="utf-8")
    rebuilt, rebuilt_manifest, _ = runtime_cache.materialize_runtime_bundle(source, expected, cache_dir=cache)
    assert rebuilt == target and (rebuilt / java).read_bytes() == b"original vendor Mach-O fixture"
    assert rebuilt_manifest["files"][java] != manifest["files"][java]
    quarantined = list(cache.glob(".invalid-*"))
    assert len(quarantined) == 1
    assert (quarantined[0] / java).read_bytes() == changed
    assert (quarantined[0] / "unrecognized-user-note.txt").read_text(encoding="utf-8") == "preserve me"


def test_changed_source_archive_fails_before_creating_a_cache(mac_package, tmp_path):
    source, expected, _ = mac_package
    (source / expected["assets"][0]["filename"]).write_bytes(b"modified download")
    cache = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="checksum"):
        runtime_cache.materialize_runtime_bundle(source, expected, cache_dir=cache)
    assert not cache.exists()


def _directory_link(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip("This host does not allow directory symlink creation: " + str(error))


@pytest.mark.parametrize("where", ["root", "target"])
def test_cache_links_cannot_read_write_or_quarantine_an_outside_directory(mac_package, tmp_path, where):
    source, expected, _ = mac_package
    outside, cache = tmp_path / "outside", tmp_path / "cache"
    outside.mkdir()
    marker = outside / "preserve.txt"
    marker.write_bytes(b"outside bytes")
    if where == "root":
        _directory_link(cache, outside)
    else:
        cache.mkdir()
        _, digest = asset_bundle.verify(source, expected)
        _directory_link(cache / digest, outside)
    with pytest.raises(ValueError):
        runtime_cache.materialize_runtime_bundle(source, expected, cache_dir=cache)
    assert marker.read_bytes() == b"outside bytes"
    assert list(outside.iterdir()) == [marker]
    assert not list(tmp_path.glob("**/.invalid-*"))


def test_cache_default_uses_selected_personal_data_and_not_the_working_directory(tmp_path, monkeypatch):
    from backend import config, platform_paths

    data, home = tmp_path / "selected-data", tmp_path / "native-home"
    monkeypatch.setattr(config, "settings", SimpleNamespace(data_dir=str(data)))
    assert runtime_cache._default_cache_base() == data / "resource-cache/e-invoice"
    monkeypatch.setattr(config, "settings", SimpleNamespace(data_dir=None))
    monkeypatch.setattr(platform_paths, "default_user_data_dir", lambda: home)
    assert runtime_cache._default_cache_base() == home / "resource-cache/e-invoice"
    assert not data.exists() and not home.exists()


def test_validator_uses_materialized_root_and_reports_corruption_before_execution(mac_package, tmp_path, monkeypatch):
    source, expected, java = mac_package
    monkeypatch.setattr(validator, "settings", SimpleNamespace(e_invoice_bundle=str(source)))
    monkeypatch.setattr(runtime_cache, "configuration", lambda: expected)
    monkeypatch.setattr(runtime_cache, "_default_cache_base", lambda: tmp_path / "cache")
    target, _, _ = validator.bundle()
    assert target != source and (target / java).is_file()
    (source / expected["assets"][0]["filename"]).write_bytes(b"modified")
    with pytest.raises(validator.ValidatorUnavailable, match="Prüfsummen"):
        validator.bundle()


def test_download_size_pin_is_checked_even_when_the_sha_matches(tmp_path, monkeypatch):
    content = b"pinned bytes but incorrect size pin"
    entry = {"filename": "input.tar.gz", "url": "https://example.invalid/not-requested",
             "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content) + 1}
    monkeypatch.setattr(prepare_e_invoice.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(content))
    with pytest.raises(RuntimeError, match="size mismatch"):
        prepare_e_invoice.fetch(entry, tmp_path)
    assert not list(tmp_path.iterdir())


def test_non_deferred_bundle_is_never_copied_to_a_cache(mac_package, tmp_path):
    source, expected, _ = mac_package
    expected = {**expected, "assets": expected["assets"][1:]}
    expected.pop("runtime_mode")
    for path in source.iterdir():
        if path.name.endswith(".tar.gz"):
            path.unlink()
    manifest = {**expected, "files": {asset["filename"]: asset["sha256"] for asset in expected["assets"]}}
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    cache = tmp_path / "unused-cache"
    root, _, _ = runtime_cache.materialize_runtime_bundle(source, expected, cache_dir=cache)
    assert root == source and not cache.exists()
