"""Protected publisher pipeline; preparation tests never constitute Apple acceptance.

Only build() reads the publisher's step-scoped environment. Actual application
checks run later, after cleanup, in a new allowlisted synthetic environment.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import plistlib
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.release_artifacts import acceptance, check_identity, read_json, row  # noqa: E402
from tools.desktop_bundle import macos_signing_options  # noqa: E402

SECRET_NAMES = ("MACOS_SIGNING_P12_BASE64", "MACOS_SIGNING_PASSWORD", "APPLE_NOTARY_KEY_BASE64",
                "APPLE_NOTARY_KEY_ID", "APPLE_NOTARY_ISSUER_ID")
PUBLIC_NAMES = ("MACOS_SIGNING_IDENTITY", "MACOS_TEAM_ID")
STATE_NAME = "immo-customer-signing"


def native(architecture):
    if (sys.platform != "darwin" or architecture not in {"x64", "arm64"}
            or {"x86_64": "x64", "arm64": "arm64"}.get(platform.machine()) != architecture):
        raise ValueError("Customer signing and runtime verification require the actual matching native Mac")


def configuration(environment):
    missing = [name for name in (*SECRET_NAMES, *PUBLIC_NAMES) if not environment.get(name)]
    if missing:
        raise ValueError("Missing protected publisher configuration: " + ", ".join(missing))
    if (not re.fullmatch(r"[A-Z0-9]{10}", environment["APPLE_NOTARY_KEY_ID"])
            or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", environment["APPLE_NOTARY_ISSUER_ID"])):
        raise ValueError("Invalid APPLE_NOTARY_KEY_ID or APPLE_NOTARY_ISSUER_ID")
    macos_signing_options(ROOT, environment={**environment, "IMMO_MACOS_CUSTOMER_SIGNING": "1"}, target="darwin")
    decoded = {}
    for name in ("MACOS_SIGNING_P12_BASE64", "APPLE_NOTARY_KEY_BASE64"):
        try:
            value = base64.b64decode(environment[name], validate=True)
        except (ValueError, TypeError):
            raise ValueError("Invalid base64 publisher configuration: " + name) from None
        if not 1 <= len(value) <= 2 * 1024 * 1024:
            raise ValueError("Invalid size of publisher configuration: " + name)
        decoded[name] = value
    if (b"-----BEGIN PRIVATE KEY-----" not in decoded["APPLE_NOTARY_KEY_BASE64"]
            or b"-----END PRIVATE KEY-----" not in decoded["APPLE_NOTARY_KEY_BASE64"]):
        raise ValueError("APPLE_NOTARY_KEY_BASE64 must contain a private .p8 key")
    return decoded


def checked(command, *, environment=None, timeout=180):
    # Do not print argv/stdout/stderr here: security import/partition arguments
    # contain temporary passwords and notarytool can echo credential details.
    try:
        result = subprocess.run(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Publisher tool failed or timed out: " + Path(command[0]).name) from None
    if result.returncode != 0:
        raise RuntimeError("Publisher tool rejected the operation: " + Path(command[0]).name)
    return result


def state_path(path):
    root = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    if path.is_symlink() or path.name != STATE_NAME or path.resolve().parent != root:
        raise ValueError("Publisher state must be its owned directory directly under RUNNER_TEMP")
    return root / STATE_NAME


def private_file(path, value):
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(value)


def cleanup(state):
    state = state_path(state)
    if not state.exists():
        return
    if not state.is_dir():
        raise ValueError("Invalid publisher state directory")
    previous_file = state / "previous-keychains.json"
    error = None
    try:
        if previous_file.exists():
            if previous_file.is_symlink():
                raise ValueError("Linked publisher keychain state")
            previous = json.loads(previous_file.read_text())
            if not isinstance(previous, list) or not all(isinstance(p, str) and p.startswith("/") for p in previous):
                raise ValueError("Invalid previous keychain list")
            checked(["/usr/bin/security", "list-keychains", "-d", "user", "-s", *previous])
        keychain = state / "publisher.keychain-db"
        if keychain.exists():
            checked(["/usr/bin/security", "delete-keychain", str(keychain)])
    except (OSError, ValueError, RuntimeError) as exc:
        error = exc
    finally:
        # A deterministic, verified owned RUNNER_TEMP child only; never touch
        # an existing user's keychain, other process or application profile.
        shutil.rmtree(state)
    if error:
        raise RuntimeError("Publisher cleanup failed; customer promotion is blocked") from None


def notary(package, key, environment):
    result = checked(["/usr/bin/xcrun", "notarytool", "submit", str(package), "--key", str(key),
                      "--key-id", environment["APPLE_NOTARY_KEY_ID"], "--issuer", environment["APPLE_NOTARY_ISSUER_ID"],
                      "--wait", "--timeout", "30m", "--output-format", "json"], timeout=1900)
    try:
        value = json.loads(result.stdout)
        identifier = value["id"]
        if value.get("status") != "Accepted" or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", identifier):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("Apple notarization did not return an Accepted submission") from None
    return {"submission_id": identifier, "status": "Accepted"}


def build(state, output, *, version, commit, architecture, desktop_run):
    native(architecture)
    check_identity(version, commit)
    if desktop_run <= 0 or output.exists():
        raise ValueError("A positive accepted desktop run and a new output directory are required")
    environment = dict(os.environ)
    decoded = configuration(environment)  # Fail before creating/importing any secret file.
    state = state_path(state)
    state.mkdir(mode=0o700)
    try:
        keychain = state / "publisher.keychain-db"
        p12, key = state / "publisher.p12", state / "AuthKey.p8"
        private_file(p12, decoded["MACOS_SIGNING_P12_BASE64"])
        private_file(key, decoded["APPLE_NOTARY_KEY_BASE64"])
        previous = shlex.split(checked(["/usr/bin/security", "list-keychains", "-d", "user"]).stdout.decode())
        private_file(state / "previous-keychains.json", json.dumps(previous).encode())
        password = secrets.token_urlsafe(40)
        checked(["/usr/bin/security", "create-keychain", "-p", password, str(keychain)])
        checked(["/usr/bin/security", "set-keychain-settings", "-lut", "7200", str(keychain)])
        checked(["/usr/bin/security", "unlock-keychain", "-p", password, str(keychain)])
        checked(["/usr/bin/security", "import", str(p12), "-k", str(keychain), "-P",
                 environment["MACOS_SIGNING_PASSWORD"], "-T", "/usr/bin/codesign", "-T", "/usr/bin/security"])
        p12.unlink()
        checked(["/usr/bin/security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:",
                 "-s", "-k", password, str(keychain)])
        checked(["/usr/bin/security", "list-keychains", "-d", "user", "-s", str(keychain)])
        identities = checked(["/usr/bin/security", "find-identity", "-v", "-p", "codesigning", str(keychain)]).stdout.decode()
        if ('"' + environment["MACOS_SIGNING_IDENTITY"] + '"') not in identities:
            raise ValueError("MACOS_SIGNING_IDENTITY is absent from the imported signing keychain")
        build_env = {k: v for k, v in environment.items() if k not in SECRET_NAMES
                     and k not in {"GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN"}}
        build_env["IMMO_MACOS_CUSTOMER_SIGNING"] = "1"
        checked([sys.executable, "-m", "PyInstaller", "immomanager.spec", "--noconfirm", "--clean"],
                environment=build_env, timeout=3000)
        app = ROOT / "dist/ImmoManager Pro.app"
        checked(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)])
        archive = state / "application.zip"
        checked(["/usr/bin/ditto", "-c", "-k", "--keepParent", str(app), str(archive)])
        app_notary = notary(archive, key, environment)
        checked(["/usr/bin/xcrun", "stapler", "staple", str(app)])
        checked(["/usr/bin/xcrun", "stapler", "validate", str(app)])
        checked([sys.executable, "scripts/package_native_desktop.py", "--dist", "dist", "--output", str(output)],
                environment=build_env, timeout=300)
        package = output / f"ImmoManager-Pro-{version}-macOS-{architecture}.dmg"
        original = read_json(package.with_suffix(".dmg.json"))
        if original.get("source_commit") != commit or original.get("architecture") != architecture:
            raise ValueError("The built package is not from the selected source and native architecture")
        checked(["/usr/bin/codesign", "--force", "--sign", environment["MACOS_SIGNING_IDENTITY"],
                 "--timestamp", str(package)])
        image_notary = notary(package, key, environment)
        checked(["/usr/bin/xcrun", "stapler", "staple", str(package)])
        checked(["/usr/bin/xcrun", "stapler", "validate", str(package)])
        value = {**original, **row(package), "pre_sign_package_sha256": original["sha256"],
                 "customer_build": {"schema": "immomanager-macos-publisher-build/1",
                                    "desktop_workflow_run": desktop_run,
                                    "application_notarization": app_notary, "image_notarization": image_notary}}
        package.with_suffix(".dmg.json").write_text(json.dumps(value, indent=2) + "\n")
        package.with_suffix(".dmg.sha256").write_text(value["sha256"] + "  " + package.name + "\n", encoding="ascii")
        return {"file": package.name, "sha256": value["sha256"], "status": "awaiting_actual_signed_runtime_verification"}
    finally:
        cleanup(state)


def signed_runtime(package, reports, *, version, commit, architecture, desktop_run):
    """Exercise the exact read-only mounted image after publisher cleanup."""
    from scripts.check_frozen_desktop import isolated_environment

    native(architecture)
    check_identity(version, commit)
    if desktop_run <= 0 or reports.exists():
        raise ValueError("A positive accepted desktop run and new reports directory are required")
    if any(os.environ.get(name) for name in SECRET_NAMES):
        raise ValueError("Publisher credentials must be absent before application runtime checks")
    if state_path(Path(os.environ["RUNNER_TEMP"]) / STATE_NAME).exists():
        raise ValueError("Publisher private state must be removed before application runtime checks")
    before = row(package)
    reports.mkdir(parents=True)
    environment = {"platform": "darwin", "architecture": architecture, "machine": platform.machine(),
                   "python": sys.version, "source_commit": commit, "desktop_workflow_run": desktop_run,
                   "customer_signed_runtime": False}
    marker = reports / "native-environment.json"
    marker.write_text(json.dumps(environment, indent=2) + "\n")
    temp = Path(tempfile.mkdtemp(prefix="immo-signed-runtime-"))
    mount = temp / "image"
    mount.mkdir()
    attach_attempted = False
    original_failure: BaseException | None = None
    try:
        attach_attempted = True
        mounted = checked(["/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-noautoopen", "-plist",
                           "-mountpoint", str(mount), str(package.resolve())])
        points = [item["mount-point"] for item in plistlib.loads(mounted.stdout).get("system-entities", []) if item.get("mount-point")]
        if len(points) != 1 or Path(points[0]).resolve() != mount.resolve():
            raise ValueError("The signed image was not mounted at its own read-only path")
        app = mount / "ImmoManager Pro.app"
        wrapper = temp / "environment"
        wrapper.mkdir()
        clean = isolated_environment(wrapper, 18875)
        # Each existing harness creates its own independent profile again.
        # The publisher keychain and step-scoped credentials were removed first.
        stages = [
            ("source-runtime", "check_desktop_runtime.py", []),
            ("frozen-runtime", "check_desktop_runtime.py", ["--dist", str(app)]),
            ("real-gui-runtime", "check_frozen_desktop.py", ["--dist", str(app)]),
            ("demo-runtime", "check_demo_runtime.py", ["--dist", str(app)]),
            ("frozen-gui-demo", "check_frozen_desktop.py", ["--dist", str(app), "--demo"]),
            ("qt-demo-ui", "check_desktop_runtime.py", ["--dist", str(app), "--demo"]),
        ]
        for stage, script, arguments in stages:
            checked([sys.executable, str(ROOT / "scripts" / script), *arguments, "--output", str(reports / stage)],
                    environment=clean, timeout=900)
        acceptance(reports, "macos-" + architecture, commit)
    except BaseException as failure:
        original_failure = failure
        raise
    finally:
        errors: list[Exception] = []
        if attach_attempted:
            try:
                checked(["/usr/bin/hdiutil", "detach", str(mount)])
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as failure:
                errors.append(failure)
        try:
            mount.rmdir()  # Empty only; never recursively walk a mounted image.
        except FileNotFoundError:
            pass
        except OSError as failure:
            errors.append(failure)
        if not mount.exists():
            wrapper = temp / "environment"
            if wrapper.is_dir():
                shutil.rmtree(wrapper)  # Only our separate synthetic profile envelope.
            try:
                temp.rmdir()
            except OSError as failure:
                errors.append(failure)
        if errors:
            if original_failure is None:
                raise RuntimeError("Signed runtime mount cleanup failed; customer promotion is blocked") from errors[0]
            original_failure.add_note("Owned signed-runtime mount cleanup did not complete.")
    if row(package) != before:
        raise ValueError("The signed image changed during its runtime acceptance")
    environment.update(customer_signed_runtime=True, customer_package_sha256=before["sha256"])
    marker.write_text(json.dumps(environment, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--state", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    runtime = sub.add_parser("runtime")
    runtime.add_argument("--package", type=Path, required=True)
    runtime.add_argument("--reports", type=Path, required=True)
    for item in (build_parser, runtime):
        item.add_argument("--version", required=True)
        item.add_argument("--commit", required=True)
        item.add_argument("--architecture", choices=("x64", "arm64"), required=True)
        item.add_argument("--desktop-run", type=int, required=True)
    clean = sub.add_parser("cleanup")
    clean.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "cleanup":
        cleanup(args.state)
    elif args.command == "build":
        print(json.dumps(build(args.state, args.output, version=args.version, commit=args.commit,
                              architecture=args.architecture, desktop_run=args.desktop_run)))
    else:
        signed_runtime(args.package, args.reports, version=args.version, commit=args.commit,
                       architecture=args.architecture, desktop_run=args.desktop_run)


if __name__ == "__main__":
    main()
