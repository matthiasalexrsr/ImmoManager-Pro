"""Publisher preparation contracts, never a substitute for real Apple signing."""

import base64
import copy
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.tests.test_release_artifacts import COMMIT, VERSION, write
from backend.tests.test_release_artifacts import inputs as inputs
from scripts import release_artifacts as release
from scripts import sign_macos_customer as signing
from tools import desktop_bundle


def configuration():
    return {
        "MACOS_SIGNING_P12_BASE64": base64.b64encode(b"synthetic certificate fixture").decode(),
        "MACOS_SIGNING_PASSWORD": "synthetic-test-password",
        "APPLE_NOTARY_KEY_BASE64": base64.b64encode(
            b"-----BEGIN PRIVATE KEY-----\nsynthetic\n-----END PRIVATE KEY-----"
        ).decode(),
        "APPLE_NOTARY_KEY_ID": "TESTKEY001",
        "APPLE_NOTARY_ISSUER_ID": "12345678-1234-1234-1234-123456789012",
        "MACOS_SIGNING_IDENTITY": "Developer ID Application: Synthetic Publisher (TESTTEAM01)",
        "MACOS_TEAM_ID": "TESTTEAM01",
    }


@pytest.mark.parametrize("missing", [*signing.SECRET_NAMES, *signing.PUBLIC_NAMES])
def test_missing_configuration_reports_only_the_name_without_secret_values(missing):
    environment = configuration()
    environment.pop(missing)
    with pytest.raises(ValueError, match=missing) as error:
        signing.configuration(environment)
    assert "synthetic-test-password" not in str(error.value)


@pytest.mark.parametrize(
    "name,value",
    [
        ("MACOS_SIGNING_P12_BASE64", "not base64"),
        ("APPLE_NOTARY_KEY_BASE64", base64.b64encode(b"not a p8 key").decode()),
        ("APPLE_NOTARY_KEY_ID", "wrong"),
        ("APPLE_NOTARY_ISSUER_ID", "wrong"),
        ("MACOS_TEAM_ID", "OTHERTEAM1"),
        ("MACOS_SIGNING_IDENTITY", "-"),
    ],
)
def test_invalid_configuration_has_no_ad_hoc_customer_fallback(name, value):
    with pytest.raises(ValueError):
        signing.configuration({**configuration(), name: value})


def test_internal_build_is_ad_hoc_but_customer_build_uses_only_reviewed_entitlements():
    assert desktop_bundle.macos_signing_options(signing.ROOT, environment={}) == {}
    options = desktop_bundle.macos_signing_options(
        signing.ROOT, environment={**configuration(), "IMMO_MACOS_CUSTOMER_SIGNING": "1"}, target="darwin"
    )
    assert options["codesign_identity"] == configuration()["MACOS_SIGNING_IDENTITY"]
    import plistlib

    assert plistlib.loads(Path(options["entitlements_file"]).read_bytes()) == {
        "com.apple.security.cs.allow-jit": True,
        "com.apple.security.cs.disable-library-validation": True,
    }
    with pytest.raises(ValueError, match="native macOS"):
        desktop_bundle.macos_signing_options(
            signing.ROOT, environment={**configuration(), "IMMO_MACOS_CUSTOMER_SIGNING": "1"}, target="win32"
        )


def test_seal_refreshes_inventory_before_outer_sign_and_does_not_resign_nested_code(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(desktop_bundle, "write_runtime_manifest", lambda *a, **kw: calls.append("manifest"))
    options = {"codesign_identity": configuration()["MACOS_SIGNING_IDENTITY"], "entitlements_file": "reviewed.plist"}
    desktop_bundle.seal_macos_bundle(
        tmp_path, signing_options=options, runner=lambda command, **kwargs: calls.append(command)
    )
    assert calls[0] == "manifest"
    assert "--deep" not in calls[1] and "--timestamp" in calls[1]
    assert "runtime" in calls[1] and "--entitlements" in calls[1]
    assert "--verify" in calls[2] and "--deep" in calls[2]


@pytest.mark.parametrize("status", ["Invalid", "In Progress", None])
def test_notary_must_actually_return_accepted(status, monkeypatch, tmp_path):
    monkeypatch.setattr(
        signing,
        "checked",
        lambda *a, **kw: SimpleNamespace(
            stdout=json.dumps({"id": "12345678-1234-1234-1234-123456789012", "status": status}).encode()
        ),
    )
    with pytest.raises(RuntimeError, match="Accepted"):
        signing.notary(tmp_path / "test.dmg", tmp_path / "key.p8", configuration())


def test_tool_error_does_not_echo_secret_arguments_or_output(monkeypatch):
    monkeypatch.setattr(
        signing.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a[0], 1, stdout=b"private-key-data", stderr=b"synthetic-test-password"
        ),
    )
    with pytest.raises(RuntimeError) as error:
        signing.checked(["/usr/bin/security", "-P", "synthetic-test-password"])
    assert "synthetic-test-password" not in str(error.value) and "private-key-data" not in str(error.value)


@pytest.mark.parametrize("failure", [None, "build", "notary"])
def test_publisher_cleanup_and_secret_free_build_environment(tmp_path, monkeypatch, failure):
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    state = runner_temp / signing.STATE_NAME
    output = tmp_path / "packages"
    values = {**configuration(), "RUNNER_TEMP": str(runner_temp), "GH_TOKEN": "synthetic-token"}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(signing, "native", lambda architecture: None)
    commands = []

    def checked(command, *, environment=None, timeout=180):
        commands.append(command)
        if "create-keychain" in command:
            Path(command[-1]).write_bytes(b"owned keychain fixture")
        if "find-identity" in command:
            return SimpleNamespace(stdout=('"' + values["MACOS_SIGNING_IDENTITY"] + '"').encode())
        if "list-keychains" in command and "-s" not in command:
            return SimpleNamespace(stdout=b'"/Users/synthetic/login.keychain-db"\n')
        if "PyInstaller" in command:
            assert environment is not None
            assert not set(signing.SECRET_NAMES) & set(environment)
            assert "GH_TOKEN" not in environment and environment["IMMO_MACOS_CUSTOMER_SIGNING"] == "1"
            if failure == "build":
                raise RuntimeError("controlled build failure")
        if "package_native_desktop.py" in " ".join(command):
            output.mkdir()
            package = output / f"ImmoManager-Pro-{VERSION}-macOS-x64.dmg"
            package.write_bytes(b"synthetic image; not a real signing proof")
            write(
                package.with_suffix(".dmg.json"),
                {"source_commit": COMMIT, "architecture": "x64", **release.row(package)},
            )
        if "notarytool" in command:
            if failure == "notary":
                raise RuntimeError("controlled notary failure")
            return SimpleNamespace(
                stdout=json.dumps({"id": "12345678-1234-1234-1234-123456789012", "status": "Accepted"}).encode()
            )
        return SimpleNamespace(stdout=b"")

    monkeypatch.setattr(signing, "checked", checked)
    if failure:
        with pytest.raises(RuntimeError, match="controlled"):
            signing.build(state, output, version=VERSION, commit=COMMIT, architecture="x64", desktop_run=123)
    else:
        result = signing.build(state, output, version=VERSION, commit=COMMIT, architecture="x64", desktop_run=123)
        assert result["status"] == "awaiting_actual_signed_runtime_verification"
    assert not state.exists()
    assert any("delete-keychain" in command for command in commands)
    restore = [c for c in commands if "list-keychains" in c and "-s" in c][-1]
    assert restore[-1] == "/Users/synthetic/login.keychain-db"


def customer_inputs(inputs, tmp_path):
    release.stage_native(**inputs)
    packages, reports = tmp_path / "signed-packages", tmp_path / "signed-reports"
    for arch in ("x64", "arm64"):
        folder = packages / f"Customer-macos-{arch}-verified"
        folder.mkdir(parents=True)
        package = folder / f"ImmoManager-Pro-{VERSION}-macOS-{arch}.dmg"
        package.write_bytes(("signed synthetic " + arch).encode())
        report = reports / f"Customer-macos-{arch}-reports"
        shutil.copytree(inputs["reports"] / f"Desktop-macos-{arch}-reports", report)
        environment = release.read_json(report / "native-environment.json")
        environment.update(
            customer_signed_runtime=True, customer_package_sha256=release.digest(package), desktop_workflow_run=123
        )
        write(report / "native-environment.json", environment)
        runtime = release.acceptance(report, "macos-" + arch, COMMIT)
        signing_proof = {
            "schema": "immomanager-macos-customer-signing/1",
            "source_commit": COMMIT,
            "architecture": arch,
            "developer_id_verified": True,
            "hardened_runtime_verified": True,
            "notarization_status": "Accepted",
            "stapler_validated": True,
            "gatekeeper_accepted": True,
            "signed_runtime_verified": True,
            "signed_runtime_package_sha256": release.digest(package),
            "accepted_package_sha256": release.digest(package),
            "signed_runtime_acceptance": runtime,
        }
        write(
            package.with_suffix(".dmg.json"),
            {
                "source_commit": COMMIT,
                "version": VERSION,
                "platform": "darwin",
                "architecture": arch,
                "workspaces": ["own", "demo-bw"],
                **release.row(package),
                "customer_build": {"desktop_workflow_run": 123},
                "customer_signing": signing_proof,
            },
        )
        package.with_suffix(".dmg.sha256").write_text(
            release.digest(package) + "  " + package.name + "\n", encoding="ascii"
        )
    return dict(
        staged=inputs["output"],
        packages=packages,
        reports=reports,
        output=tmp_path / "overlaid",
        version=VERSION,
        commit=COMMIT,
    )


def test_complete_signed_overlay_preserves_all_five_targets_sources_and_three_run_ids(inputs, tmp_path):
    options = customer_inputs(inputs, tmp_path)
    before = {p.name: release.digest(p) for p in options["staged"].iterdir()}
    value = release.overlay_customer_macos(**options)
    release.validate_required_assets(options["output"], value, version=VERSION, commit=COMMIT)
    release.customer_macos_acceptance(options["output"], version=VERSION, commit=COMMIT)
    proof = release.read_json(options["output"] / "native-acceptance.json")
    assert set(proof["targets"]) == set(release.TARGETS)
    assert [proof[k] for k in ("desktop_workflow_run", "ci_workflow_run", "hardening_workflow_run")] == [123, 456, 789]
    assert {p.name: release.digest(p) for p in options["staged"].iterdir()} == before
    assert len(list(options["output"].glob("qt-*.tar.xz"))) == 11
    assert (options["output"] / "customer-macos-acceptance.json").is_file()


@pytest.mark.parametrize("fault", ["missing", "partial", "target", "commit", "stage", "package", "text", "docx"])
def test_boolean_signing_flags_cannot_replace_complete_signed_runtime(inputs, tmp_path, fault):
    options = customer_inputs(inputs, tmp_path)
    package = options["packages"] / "Customer-macos-x64-verified" / f"ImmoManager-Pro-{VERSION}-macOS-x64.dmg"
    receipt = release.read_json(package.with_suffix(".dmg.json"))
    proof = receipt["customer_signing"]
    runtime = copy.deepcopy(proof["signed_runtime_acceptance"])
    if fault == "missing":
        proof.pop("signed_runtime_acceptance")
    elif fault == "partial":
        proof["signed_runtime_acceptance"] = {"status": "passed"}
    else:
        if fault == "target":
            runtime["environment"]["architecture"] = "arm64"
        elif fault == "commit":
            runtime["environment"]["source_commit"] = "b" * 40
        elif fault == "stage":
            runtime["ai_workers"].pop("source-runtime")
        elif fault == "package":
            runtime["environment"]["customer_package_sha256"] = "c" * 64
        elif fault == "text":
            runtime["ai_workers"]["frozen-runtime"]["text_observation"]["failed"] = True
        elif fault == "docx":
            runtime["ai_workers"]["qt-demo-ui"]["worker"]["assistant_attachments"].pop(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        proof["signed_runtime_acceptance"] = runtime
    # Test the final publication gate directly, without overlay's equality guard.
    destination = options["packages"] / "Customer-macos-arm64-verified" / f"ImmoManager-Pro-{VERSION}-macOS-arm64.dmg"
    flat = tmp_path / "flat"
    flat.mkdir()
    shutil.copyfile(package, flat / package.name)
    write(flat / (package.name + ".json"), receipt)
    shutil.copyfile(destination, flat / destination.name)
    shutil.copyfile(destination.with_suffix(".dmg.json"), flat / (destination.name + ".json"))
    with pytest.raises(ValueError):
        release.customer_macos_acceptance(flat, version=VERSION, commit=COMMIT)


@pytest.mark.parametrize("fault", ["missing-arch", "extra-file", "checksum", "run", "reports", "baseline"])
def test_partial_or_mismatched_overlay_cannot_mutate_baseline_or_create_output(inputs, tmp_path, fault):
    options = customer_inputs(inputs, tmp_path)
    folder = options["packages"] / "Customer-macos-x64-verified"
    if fault == "missing-arch":
        shutil.rmtree(options["packages"] / "Customer-macos-arm64-verified")
    elif fault == "extra-file":
        (folder / "unapproved.log").write_text("not eligible")
    elif fault == "checksum":
        next(folder.glob("*.sha256")).write_text("wrong")
    elif fault == "run":
        receipt = next(folder.glob("*.json"))
        value = release.read_json(receipt)
        value["customer_build"]["desktop_workflow_run"] = 999
        write(receipt, value)
    elif fault == "reports":
        (options["reports"] / "Customer-macos-arm64-reports/frozen-runtime/ai-text-worker-observation.json").unlink()
    else:
        (options["staged"] / "SHA256SUMS.txt").write_text("changed")
    before = {p.name: release.digest(p) for p in options["staged"].iterdir()}
    with pytest.raises(ValueError):
        release.overlay_customer_macos(**options)
    assert not options["output"].exists()
    assert {p.name: release.digest(p) for p in options["staged"].iterdir()} == before


def test_copy_failure_leaves_no_partial_customer_inventory(inputs, tmp_path, monkeypatch):
    options = customer_inputs(inputs, tmp_path)
    original = shutil.copyfile
    calls = []

    def copy_file(source, destination):
        calls.append(source)
        if len(calls) == 3:
            raise OSError("controlled copy failure")
        return original(source, destination)

    monkeypatch.setattr(release.shutil, "copyfile", copy_file)
    with pytest.raises(OSError, match="controlled"):
        release.overlay_customer_macos(**options)
    assert not options["output"].exists() and not list(tmp_path.glob(".customer-mac-overlay-*"))


@pytest.mark.parametrize("changed", ["qt-0.tar.xz", f"ImmoManager-Pro-{VERSION}-macOS-x64.dmg.sha256"])
def test_changed_copy_cannot_be_rehashed_into_a_new_customer_inventory(inputs, tmp_path, monkeypatch, changed):
    options = customer_inputs(inputs, tmp_path)
    before = {p.name: release.digest(p) for p in options["staged"].iterdir()}
    original = shutil.copyfile

    def corrupted_copy(source, destination):
        result = original(source, destination)
        if Path(destination).name == changed:
            Path(destination).write_bytes(b"changed in transit after source validation")
        return result

    monkeypatch.setattr(release.shutil, "copyfile", corrupted_copy)
    with pytest.raises(ValueError, match="changed while copying"):
        release.overlay_customer_macos(**options)
    assert {p.name: release.digest(p) for p in options["staged"].iterdir()} == before
    assert not options["output"].exists() and not list(tmp_path.glob(".customer-mac-overlay-*"))


@pytest.mark.parametrize("fault", [None, "alias", "other-mount", "stage", "attach", "detach"])
def test_runtime_mounts_final_image_and_only_marks_success_after_all_six_clean_stages(tmp_path, monkeypatch, fault):
    for name in signing.SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("SYNTHETIC_UNRELATED_SECRET", "must-not-enter-application")
    monkeypatch.setattr(signing, "native", lambda architecture: None)
    package = tmp_path / "final.dmg"
    package.write_bytes(b"synthetic final image")
    reports = tmp_path / "reports"
    own_temp = tmp_path / "owned-mount-envelope"
    own_temp.mkdir()
    monkeypatch.setattr(signing.tempfile, "mkdtemp", lambda **kwargs: str(own_temp))
    calls = []
    stages = []
    sentinel = own_temp / "image" / "mounted-sentinel"

    def checked(command, *, environment=None, timeout=180):
        calls.append(command)
        if "attach" in command:
            if fault == "attach":
                sentinel.write_bytes(b"must never be recursively removed")
                raise subprocess.TimeoutExpired(command[0], timeout)
            point = command[command.index("-mountpoint") + 1]
            if fault == "alias":
                # Equivalent canonical path spelling, as /var and /private/var
                # on a native Mac. Do not mutate pathlib/sys globally.
                point = str(Path(point).parent / "image" / ".." / "image")
            elif fault == "other-mount":
                point = str(tmp_path / "not-our-mount")
            import plistlib

            return SimpleNamespace(stdout=plistlib.dumps({"system-entities": [{"mount-point": point}]}))
        if "detach" in command:
            if fault in {"attach", "detach"}:
                sentinel.write_bytes(b"must never be recursively removed")
                raise RuntimeError("controlled detach failure")
        if any(str(value).endswith(".py") for value in command):
            stages.append(command)
            assert environment is not None
            assert not set(signing.SECRET_NAMES) & set(environment)
            assert "SYNTHETIC_UNRELATED_SECRET" not in environment
            assert environment["QT_QPA_PLATFORM"] == "offscreen"
            assert "--no-sandbox" not in environment["QTWEBENGINE_CHROMIUM_FLAGS"]
            assert release.read_json(reports / "native-environment.json")["customer_signed_runtime"] is False
            if fault == "stage":
                raise RuntimeError("controlled stage failure")
        return SimpleNamespace(stdout=b"")

    monkeypatch.setattr(signing, "checked", checked)

    def acceptance(*args):
        assert len(stages) == 6
        return {}

    monkeypatch.setattr(signing, "acceptance", acceptance)
    options = dict(version=VERSION, commit=COMMIT, architecture="x64", desktop_run=123)
    if fault not in {None, "alias"}:
        with pytest.raises((ValueError, RuntimeError, subprocess.TimeoutExpired)) as error:
            signing.signed_runtime(package, reports, **options)
        assert release.read_json(reports / "native-environment.json")["customer_signed_runtime"] is False
        if fault == "attach":
            assert isinstance(error.value, subprocess.TimeoutExpired)
            assert error.value.__notes__
            assert sentinel.read_bytes() == b"must never be recursively removed"
        if fault == "detach":
            assert sentinel.is_file()
    else:
        signing.signed_runtime(package, reports, **options)
        value = release.read_json(reports / "native-environment.json")
        assert value["customer_signed_runtime"] is True and value["customer_package_sha256"] == release.digest(package)
        assert len(stages) == 6 and not own_temp.exists()
        assert "--dist" not in stages[0]
        assert all(str(own_temp / "image" / "ImmoManager Pro.app") in command for command in stages[1:])
    detach = [command for command in calls if "detach" in command]
    assert len(detach) == 1 and detach[0][-1] == str(own_temp / "image") and "-force" not in detach[0]


@pytest.mark.parametrize("remaining", ["credential", "keychain-state"])
def test_runtime_refuses_remaining_publisher_credentials_or_state_before_mount(tmp_path, monkeypatch, remaining):
    monkeypatch.setattr(signing, "native", lambda architecture: None)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    for name in signing.SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    if remaining == "credential":
        monkeypatch.setenv("APPLE_NOTARY_KEY_ID", "TESTKEY001")
    else:
        (tmp_path / signing.STATE_NAME).mkdir()
    monkeypatch.setattr(signing, "checked", lambda *args, **kwargs: pytest.fail("No tool before cleanup"))
    with pytest.raises(ValueError, match="Publisher"):
        signing.signed_runtime(
            tmp_path / "final.dmg",
            tmp_path / "reports",
            version=VERSION,
            commit=COMMIT,
            architecture="x64",
            desktop_run=123,
        )
    assert not (tmp_path / "reports").exists()


def test_cleanup_never_deletes_a_path_outside_the_owned_runner_temp_child(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    foreign = tmp_path / "other"
    foreign.mkdir()
    sentinel = foreign / "sentinel"
    sentinel.write_text("keep")
    monkeypatch.setattr(signing, "checked", lambda *args, **kwargs: pytest.fail("No tool on foreign state"))
    with pytest.raises(ValueError, match="owned"):
        signing.cleanup(foreign)
    assert sentinel.read_text() == "keep"
