"""Static OpenSSL notices must describe the exact source and actual build bytes."""
import hashlib
import json

import pytest

from tools import third_party_notices as notices


@pytest.fixture
def static_build(tmp_path, monkeypatch):
    pinned = json.loads((notices.ROOT / "packaging/third-party/openssl-static-macos.json").read_text(encoding="utf-8"))
    prefix = tmp_path / "private-openssl"
    prefix.mkdir()
    identities = {}
    for name in ("lib/libssl.a", "lib/libcrypto.a", "bin/openssl", "LICENSE.txt"):
        path = prefix / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("Original build fixture " + name + "\n").encode())
        identities[name] = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    receipt = {**pinned, "schema": "immomanager-static-openssl-build/1", "native_platform": "darwin",
               "native_machine": "x86_64", "openssl_version": "OpenSSL " + pinned["version"] + " original fixture\n",
               "compiler_environment": {"MACOSX_DEPLOYMENT_TARGET": pinned["deployment_target"]},
               "configure_argv": [pinned["configure_target"], "no-shared"], "files": identities}

    def save():
        (prefix / "build-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")

    save()
    monkeypatch.setenv("IMMO_STATIC_OPENSSL_PREFIX", str(prefix))
    monkeypatch.setattr(notices.sys, "platform", "darwin")
    monkeypatch.setattr(notices.platform, "machine", lambda: "x86_64")
    return prefix, pinned, receipt, save


def test_other_package_builds_have_no_static_source_side_effect(monkeypatch):
    monkeypatch.delenv("IMMO_STATIC_OPENSSL_PREFIX", raising=False)
    monkeypatch.setattr(notices.sys, "platform", "linux")
    assert notices.static_openssl_license_sources() == []


@pytest.mark.parametrize("platform,machine", [("win32", "AMD64"), ("linux", "x86_64"), ("darwin", "arm64")])
def test_explicit_static_source_cannot_be_mislabelled_on_another_native_target(monkeypatch, platform, machine):
    monkeypatch.setenv("IMMO_STATIC_OPENSSL_PREFIX", "never-open-this-prefix")
    monkeypatch.setattr(notices.sys, "platform", platform)
    monkeypatch.setattr(notices.platform, "machine", lambda: machine)
    with pytest.raises(RuntimeError, match="native Intel macOS"):
        notices.static_openssl_license_sources()


def test_exact_source_original_license_and_build_provenance_are_collected(static_build):
    prefix, pinned, _, _ = static_build
    rows = notices.static_openssl_license_sources()
    assert len(rows) == 1
    name, version, expression, files, upstream = rows[0]
    assert name == "OpenSSL (static cryptography linkage)" and version == pinned["version"]
    assert expression == "Apache-2.0"
    assert files == [prefix / "LICENSE.txt", prefix / "build-receipt.json"]
    assert upstream == {"url": pinned["source_url"], "sha256": pinned["source_sha256"]}
    assert files[0].read_bytes() == b"Original build fixture LICENSE.txt\n"


@pytest.mark.parametrize("field", ["version", "source_url", "source_sha256", "source_bytes", "deployment_target", "configure_target"])
def test_receipt_cannot_substitute_another_source_version_or_deployment_target(static_build, field):
    _, _, receipt, save = static_build
    receipt[field] = "unreviewed"
    save()
    with pytest.raises(RuntimeError, match="exact reviewed source"):
        notices.static_openssl_license_sources()


@pytest.mark.parametrize("name", ["LICENSE.txt", "bin/openssl", "lib/libssl.a", "lib/libcrypto.a"])
def test_changed_license_binary_or_static_archive_blocks_collection(static_build, name):
    prefix, _, _, _ = static_build
    path = prefix / name
    path.write_bytes(b"x" * path.stat().st_size)
    with pytest.raises(RuntimeError, match="Changed static OpenSSL"):
        notices.static_openssl_license_sources()


@pytest.mark.parametrize("name", ["NOTICE", "NOTICE.txt"])
def test_present_original_notice_is_kept_and_hash_verified(static_build, name):
    prefix, _, receipt, save = static_build
    path = prefix / name
    path.write_bytes(b"Original Apache NOTICE fixture.\n")
    receipt["files"][name] = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    save()
    rows = notices.static_openssl_license_sources()
    assert path in rows[0][3]
    path.write_bytes(b"changed notice")
    with pytest.raises(RuntimeError, match="Changed static OpenSSL"):
        notices.static_openssl_license_sources()


def test_existing_notice_without_original_hash_cannot_silently_disappear(static_build):
    prefix, _, _, _ = static_build
    (prefix / "NOTICE").write_bytes(b"An upstream notice that must be retained.\n")
    with pytest.raises(RuntimeError, match="omits or changes original notice"):
        notices.static_openssl_license_sources()


@pytest.mark.parametrize("field,value", [("native_machine", "arm64"), ("native_platform", "linux"),
                                        ("openssl_version", "OpenSSL 3.0.0 wrong runtime"),
                                        ("configure_argv", ["darwin64-x86_64-cc"]),
                                        ("compiler_environment", {"MACOSX_DEPLOYMENT_TARGET": "15.0"})])
def test_wrong_architecture_runtime_or_nonstatic_build_cannot_be_noticed_as_reviewed(static_build, field, value):
    _, _, receipt, save = static_build
    receipt[field] = value
    save()
    with pytest.raises(RuntimeError, match="exact reviewed source"):
        notices.static_openssl_license_sources()
