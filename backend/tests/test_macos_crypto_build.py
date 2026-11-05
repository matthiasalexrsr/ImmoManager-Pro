"""Block the actual macOS OpenSSL collision and preserve source-build provenance."""
from __future__ import annotations

import hashlib
import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from scripts import build_macos_openssl, check_macos_crypto
from tools import desktop_bundle


def archive_bytes(*, unsafe: str | None = None) -> bytes:
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        for name, content in (("Configure", b"original build input"), ("LICENSE.txt", b"original license"),
                              ("NOTICE", b"original notice")):
            item = tarfile.TarInfo("openssl-3.5.9/" + name)
            item.size = len(content)
            item.mode = 0o755 if name == "Configure" else 0o644
            archive.addfile(item, io.BytesIO(content))
        if unsafe:
            item = tarfile.TarInfo(unsafe)
            if unsafe.endswith("symlink"):
                item.type = tarfile.SYMTYPE
                item.linkname = "../../outside"
            archive.addfile(item)
    return data.getvalue()


def test_source_hash_and_size_are_both_required(tmp_path):
    archive = tmp_path / "source.tar.gz"
    archive.write_bytes(b"pinned original archive")
    pin = {"source_bytes": archive.stat().st_size,
           "source_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    build_macos_openssl.verify_archive(archive, pin)
    archive.write_bytes(b"tampered original file")
    with pytest.raises(RuntimeError, match="pinned size and SHA"):
        build_macos_openssl.verify_archive(archive, pin)


@pytest.mark.parametrize("unsafe", ["openssl-3.5.9/../../outside", "/outside", "other-root/file",
                                    "openssl-3.5.9/symlink", "openssl-3.5.9/bad\\file"])
def test_invalid_archive_is_rejected_before_any_extraction(tmp_path, unsafe):
    archive = tmp_path / "source.tar.gz"
    archive.write_bytes(archive_bytes(unsafe=unsafe))
    destination = tmp_path / "extracted"
    with pytest.raises(RuntimeError, match="Unsafe member"):
        build_macos_openssl.extract_source(archive, destination, "3.5.9")
    assert not destination.exists()


def test_wrong_native_host_cannot_create_build_output(tmp_path, monkeypatch):
    monkeypatch.setattr(build_macos_openssl.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="native Intel macOS"):
        build_macos_openssl.build(tmp_path / "output")
    assert not (tmp_path / "output").exists()


def source_build_fixture(tmp_path, monkeypatch):
    original = archive_bytes()
    pin = {"schema": "immomanager-static-openssl-source/1", "version": "3.5.9",
           "source_url": "https://upstream.invalid/openssl-3.5.9.tar.gz", "source_bytes": len(original),
           "source_sha256": hashlib.sha256(original).hexdigest(), "deployment_target": "13.0",
           "configure_target": "darwin64-x86_64-cc"}
    manifest = tmp_path / "source-pin.json"
    manifest.write_text(json.dumps(pin))
    monkeypatch.setattr(build_macos_openssl, "MANIFEST", manifest)
    monkeypatch.setattr(build_macos_openssl.sys, "platform", "darwin")
    monkeypatch.setattr(build_macos_openssl.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(build_macos_openssl.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(original))
    output = tmp_path / "private-build"
    prefix = output / "install"
    calls: list[tuple[list[str], dict]] = []
    version = "OpenSSL 3.5.9 29 Sep 2026 (Library: OpenSSL 3.5.9 29 Sep 2026)\n"

    def native_command(command, **kwargs):
        calls.append((command, kwargs))
        if command[-1] == "install_sw":
            for name in ("lib/libssl.a", "lib/libcrypto.a", "bin/openssl"):
                path = prefix / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(("synthetic native build " + name).encode())
        return SimpleNamespace(stdout=version)

    monkeypatch.setattr(build_macos_openssl.subprocess, "run", native_command)
    receipt = build_macos_openssl.build(output)
    return prefix, receipt, calls, manifest


def test_static_source_build_owns_its_output_and_binds_original_notices(tmp_path, monkeypatch):
    prefix, receipt, calls, _manifest = source_build_fixture(tmp_path, monkeypatch)
    assert receipt["schema"] == "immomanager-static-openssl-build/1"
    assert receipt == json.loads((prefix / "build-receipt.json").read_text())
    assert (prefix / "LICENSE.txt").read_bytes() == b"original license"
    assert (prefix / "NOTICE").read_bytes() == b"original notice"
    assert set(receipt["files"]) == {"lib/libssl.a", "lib/libcrypto.a", "bin/openssl", "LICENSE.txt", "NOTICE"}
    for name, identity in receipt["files"].items():
        assert identity == build_macos_openssl.file_identity(prefix / name)
    configure, environment = calls[0]
    assert {"no-shared", "no-module", "--libdir=lib", "darwin64-x86_64-cc"} <= set(configure)
    assert environment["env"]["MACOSX_DEPLOYMENT_TARGET"] == "13.0"
    assert environment["env"]["CFLAGS"].endswith("-mmacosx-version-min=13.0")
    with pytest.raises(FileExistsError):
        build_macos_openssl.build(prefix.parent)


def fake_otool(monkeypatch, *, dependency="/usr/lib/libSystem.B.dylib", minimum="13.0", missing=False):
    def run(command, **kwargs):
        assert command[0] == "/usr/bin/otool" and kwargs["check"] and kwargs["timeout"] == 30
        if command[1] == "-L":
            return SimpleNamespace(stdout="extension.so:\n\t" + dependency + " (compatibility version 1.0.0, current version 1.0.0)\n")
        return SimpleNamespace(stdout="no recognized commands" if missing else
                               "Load command 10\n      cmd LC_BUILD_VERSION\n  cmdsize 32\n platform 1\n    minos "
                               + minimum + "\n      sdk 15.0\n")
    monkeypatch.setattr(desktop_bundle.subprocess, "run", run)


@pytest.mark.parametrize("dependency", ["/usr/local/opt/openssl@3/lib/libssl.3.dylib",
                                       "@rpath/libcrypto.3.dylib"])
def test_actual_macho_linkage_blocks_the_failing_external_openssl_pair(tmp_path, monkeypatch, dependency):
    fake_otool(monkeypatch, dependency=dependency)
    with pytest.raises(RuntimeError, match="statically linked OpenSSL"):
        desktop_bundle.macos_crypto_linkage(tmp_path / "_rust.abi3.so")


@pytest.mark.parametrize("minimum,missing", [("15.0", False), ("13.0", True)])
def test_unproven_or_newer_macos_minimum_cannot_claim_macos_13(tmp_path, monkeypatch, minimum, missing):
    fake_otool(monkeypatch, minimum=minimum, missing=missing)
    with pytest.raises(RuntimeError, match="macOS|load command"):
        desktop_bundle.macos_crypto_linkage(tmp_path / "_rust.abi3.so")


def test_independent_openssl_linkage_preserves_actual_evidence(tmp_path, monkeypatch):
    fake_otool(monkeypatch)
    extension = tmp_path / "_rust.abi3.so"
    extension.write_bytes(b"synthetic Mach-O fixture")
    report = desktop_bundle.macos_crypto_linkage(extension)
    assert report["external_openssl_dependencies"] == []
    assert report["minimum_macos_versions"] == ["13.0"]
    assert report["sha256"] == hashlib.sha256(extension.read_bytes()).hexdigest()


def test_packager_cannot_bypass_macos_abi_preflight(monkeypatch):
    monkeypatch.setattr(desktop_bundle.sys, "platform", "darwin")
    calls = []

    def reject():
        raise RuntimeError("actual ABI violation")

    monkeypatch.setattr(desktop_bundle, "macos_crypto_abi_report", reject)
    with pytest.raises(RuntimeError, match="actual ABI violation"):
        desktop_bundle.isolated_native_analysis(lambda: calls.append("analysis"))
    assert calls == []


def test_failed_native_preflight_emits_a_failed_report_and_nonzero_status(tmp_path, monkeypatch):
    monkeypatch.setattr(check_macos_crypto, "run_probe", lambda: (_ for _ in ()).throw(RuntimeError("actual ABI failure")))
    output = tmp_path / "reports/macos-openssl-abi.json"
    assert check_macos_crypto.main(["--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert report["status"] == "failed" and "actual ABI failure" in report["error"]


@pytest.mark.parametrize("tamper", [None, "library", "version"])
def test_native_preflight_binds_actual_crypto_to_original_static_build(tmp_path, monkeypatch, tamper):
    prefix, _receipt, _calls, manifest = source_build_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(check_macos_crypto, "MANIFEST", manifest)
    monkeypatch.setenv("IMMO_STATIC_OPENSSL_PREFIX", str(prefix))
    monkeypatch.setenv("OPENSSL_DIR", str(prefix))
    monkeypatch.setenv("OPENSSL_STATIC", "1")
    version = "OpenSSL 3.6.5 wrong build" if tamper == "version" else "OpenSSL 3.5.9 original build"
    monkeypatch.setattr(desktop_bundle, "macos_crypto_abi_report", lambda: {"status": "passed", "cryptography_openssl": version})
    if tamper == "library":
        (prefix / "lib/libcrypto.a").write_bytes(b"a different native library")
    if tamper:
        with pytest.raises(RuntimeError, match="provenance has changed|different versions"):
            check_macos_crypto.run_probe()
    else:
        report = check_macos_crypto.run_probe()
        assert report["source_build_openssl"]["directory"] == str(prefix.resolve())
        assert report["source_build_openssl"]["receipt_sha256"] == hashlib.sha256((prefix / "build-receipt.json").read_bytes()).hexdigest()
