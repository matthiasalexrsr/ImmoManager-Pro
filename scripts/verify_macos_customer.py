"""Verify an already signed/notarized DMG on its native Mac; never invent a signing identity.

This tool does not sign, remove quarantine, install, launch the application or submit
anything to a notary service. It creates a new verified copy only after Apple tools
accept both the image and its application. Existing output is never overwritten.
"""
from __future__ import annotations

import argparse
import json
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.release_artifacts import (  # noqa: E402 -- explicit repository root for CLI
    acceptance,
    check_identity,
    read_json,
    row,
)


def checked(command: list[str]) -> Any:
    result = subprocess.run(command, check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=120)
    if len(result.stdout) + len(result.stderr) > 1024 * 1024:
        raise ValueError("Unexpectedly large Apple verification response")
    return result


def native_checks(app: Path, package: Path, *, version: str, team_id: str,
                  runner: Callable[..., Any] = checked) -> dict:
    if not re.fullmatch(r"[A-Z0-9]{10}", team_id):
        raise ValueError("An explicit ten-character Apple developer team is required")
    info_path = app / "Contents/Info.plist"
    if app.is_symlink() or info_path.is_symlink() or not info_path.is_file() or info_path.stat().st_size > 1024 * 1024:
        raise ValueError("Missing or linked native application metadata")
    info = plistlib.loads(info_path.read_bytes())
    parsed = Version(version)
    short = ".".join(str(part) for part in parsed.release)
    build = short
    if parsed.pre:
        stage, number = parsed.pre
        build += {"a": "a", "b": "b", "rc": "fc"}[stage] + str(number)
    if (info.get("CFBundleIdentifier") != "de.immomanagerpro.desktop"
            or info.get("CFBundleShortVersionString") != short or info.get("CFBundleVersion") != build):
        raise ValueError("The mounted application has a different identity/version")
    observations = []

    def run(command):
        result = runner(command)
        if result.returncode != 0:
            raise ValueError("Apple verification command did not succeed")
        text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        observations.append({"tool": command[0], "arguments": command[1:], "output": text})
        return text

    for target in (app, package):
        run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(target)])
        details = run(["/usr/bin/codesign", "--display", "--verbose=4", str(target)])
        if (not re.search(r"(?m)^Authority=Developer ID Application:", details)
                or f"TeamIdentifier={team_id}" not in details.splitlines()
                or not re.search(r"(?m)^Timestamp=.+", details)):
            raise ValueError("Developer ID, expected team or secure timestamp is unverified")
        if target == app and not re.search(r"flags=.*\bruntime\b", details):
            raise ValueError("The application hardened runtime is unverified")
        run(["/usr/bin/xcrun", "stapler", "validate", str(target)])
        arguments = (["--type", "execute"] if target == app else
                     ["--type", "open", "--context", "context:primary-signature"])
        assessment = run(["/usr/sbin/spctl", "--assess", *arguments, "--verbose=4", str(target)])
        if "source=Notarized Developer ID" not in assessment.splitlines():
            raise ValueError("Gatekeeper did not confirm a notarized Developer ID")
    return {"developer_id_verified": True, "hardened_runtime_verified": True,
            "notarization_status": "Accepted", "stapler_validated": True, "gatekeeper_accepted": True,
            "team_id": team_id, "notarization_evidence": "Valid app/image stapled tickets and both Gatekeeper assessments",
            "checks": observations}


def verify(package: Path, *, receipt: Path, output: Path, version: str, commit: str,
           architecture: str, team_id: str, reports: Path) -> dict:
    check_identity(version, commit)
    native_arch = {"x86_64": "x64", "arm64": "arm64"}.get(platform.machine())
    if sys.platform != "darwin" or architecture not in {"x64", "arm64"} or native_arch != architecture:
        raise ValueError("Customer Mac verification requires the matching native macOS architecture")
    expected_name = f"ImmoManager-Pro-{version}-macOS-{architecture}.dmg"
    if package.name != expected_name or package.is_symlink() or not package.is_file():
        raise ValueError("Unexpected or linked native package")
    provenance = read_json(receipt)
    if (provenance.get("source_commit"), provenance.get("version"), provenance.get("platform"),
            provenance.get("architecture")) != (commit, version, "darwin", architecture):
        raise ValueError("The native build provenance belongs to another source/version/target")
    if (provenance.get("file") != package.name or provenance.get("workspaces") != ["own", "demo-bw"]
            or not isinstance(provenance.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", provenance["sha256"])
            or type(provenance.get("bytes")) is not int or provenance["bytes"] <= 0):
        raise ValueError("Incomplete original native package provenance")
    before = row(package)
    if output.exists():
        raise FileExistsError(output)
    temp = Path(tempfile.mkdtemp(prefix="immo-customer-mac-"))
    mount = temp / "image"
    mount.mkdir()
    attach_attempted = False
    original_failure: BaseException | None = None
    try:
        # hdiutil can mount successfully and then time out before returning its
        # receipt. Cleanup must also cover that uncertain partial-attach path.
        attach_attempted = True
        mounted = checked(["/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-noautoopen",
                           "-plist", "-mountpoint", str(mount), str(package.resolve())])
        entities = plistlib.loads(mounted.stdout).get("system-entities", [])
        points = [item.get("mount-point") for item in entities if item.get("mount-point")]
        if len(points) != 1 or Path(points[0]).resolve() != mount.resolve():
            raise ValueError("Disk image did not mount at its owned verification path")
        app = mount / "ImmoManager Pro.app"
        proof = native_checks(app, package.resolve(), version=version, team_id=team_id)
        runtime = acceptance(reports, "macos-" + architecture, commit)
        environment = runtime["environment"]
        if (environment.get("customer_signed_runtime") is not True
                or environment.get("customer_package_sha256") != before["sha256"]):
            raise ValueError("Actual signed runtime acceptance is not bound to this customer image")
    except BaseException as failure:
        original_failure = failure
        raise
    finally:
        cleanup_errors: list[Exception] = []
        if attach_attempted:
            try:
                # Only this exact private mountpoint is eligible, never a
                # guessed device, another mount, forced detach or recursive rm.
                checked(["/usr/bin/hdiutil", "detach", str(mount)])
            except (OSError, subprocess.SubprocessError, ValueError) as failure:
                cleanup_errors.append(failure)
        for directory in (mount, temp):
            try:
                directory.rmdir()  # Empty directories only, including after a failed detach.
            except FileNotFoundError:
                pass
            except OSError as failure:
                cleanup_errors.append(failure)
        if cleanup_errors:
            if original_failure is None:
                raise ValueError("The owned macOS verification mount cleanup did not complete") from cleanup_errors[0]
            original_failure.add_note("Owned macOS verification cleanup did not complete; inspect its private mountpoint.")
    if row(package) != before:
        raise ValueError("The package changed during native verification")
    output.mkdir(parents=True, exist_ok=False)
    destination = output / package.name
    shutil.copyfile(package, destination)
    if row(destination) != before:
        raise ValueError("The verified package changed while copying")
    proof.update(schema="immomanager-macos-customer-signing/1", source_commit=commit, architecture=architecture,
                 accepted_package_sha256=before["sha256"], verified_at=datetime.now(timezone.utc).isoformat(),
                 signed_runtime_verified=True, signed_runtime_package_sha256=before["sha256"],
                 signed_runtime_acceptance=runtime)
    result = {**provenance, **before, "customer_signing": proof,
              "pre_customer_package_sha256": provenance.get("sha256")}
    destination.with_suffix(".dmg.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    destination.with_suffix(".dmg.sha256").write_text(before["sha256"] + "  " + package.name + "\n", encoding="ascii")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--architecture", choices=("x64", "arm64"), required=True)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--reports", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.package, receipt=args.receipt, output=args.output, version=args.version,
                    commit=args.commit, architecture=args.architecture, team_id=args.team_id, reports=args.reports)
    print(json.dumps({"file": result["file"], "sha256": result["sha256"], "status": "verified"}))


if __name__ == "__main__":
    main()
