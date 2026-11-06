"""Promote only complete native acceptance artifacts from one reviewed commit.

This is a build/release tool. It never changes application data or replaces an
existing tag/release. Publishing is an explicit workflow operation; an unsigned
publication exception is restricted to an explicitly selected beta prerelease.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"windows-x64": ("win32", "x64", "Setup-x64.exe"),
           "macos-x64": ("darwin", "x64", "macOS-x64.dmg"),
           "macos-arm64": ("darwin", "arm64", "macOS-arm64.dmg"),
           "linux-x64": ("linux", "x64", "Linux-x64.tar.gz"),
           "linux-arm64": ("linux", "arm64", "Linux-arm64.tar.gz")}


def read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or linked release evidence: " + str(path))
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Invalid release evidence: " + str(path))
    return value


def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Release assets must be regular files: " + str(path))
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def row(path: Path) -> dict:
    checksum = digest(path)
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": checksum}


def check_identity(version: str, commit: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", version) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid release version/commit")


def check_policy(version: str, *, publish: bool, tag: str, allow_unsigned: bool) -> None:
    if tag != ("v" + version if publish else ""):
        raise ValueError("Release tag must match the exact project version; artifacts-only runs have no tag")
    if allow_unsigned and (not publish or not re.fullmatch(r"\d+\.\d+\.\d+-beta\.\d+", version)):
        raise ValueError("Unsigned publication requires explicit publication of a beta.N prerelease")


def stamp_windows(folder: Path, *, version: str, commit: str, signature: str) -> Path:
    check_identity(version, commit)
    setup = folder / f"ImmoManager-Pro-{version}-Setup-x64.exe"
    portable = folder / f"ImmoManager-Pro-{version}-Windows.zip"
    receipt = read_json(setup.with_suffix(".build.json"))
    if (receipt.get("version") != version or receipt.get("installer_sha256") != digest(setup)
            or receipt.get("desktop_runtime", {}).get("workspaces") != ["own", "demo-bw"]):
        raise ValueError("The Windows setup differs from its build receipt")
    value = {"schema": "immomanager-native-package/1", "version": version, "platform": "win32",
             "architecture": "x64", "source_commit": commit, "authenticode_status": signature,
             "workspaces": ["own", "demo-bw"],
             "files": [row(setup), row(portable)]}
    path = folder / f"ImmoManager-Pro-{version}-Windows-native.json"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def report_base(report: Path) -> Path:
    # Multiple upload-artifact paths use their repository-root common ancestor.
    # Support that exact documented artifact layout as well as flat fixtures;
    # never pick an arbitrary recursively found report or follow an outside link.
    nested = report / "artifacts/desktop-reports"
    if nested.exists():
        if not nested.is_dir() or nested.is_symlink() or not nested.resolve().is_relative_to(report.resolve()):
            raise ValueError("The canonical native reports directory is invalid")
        return nested
    return report


def ai_worker_acceptance(report: Path) -> dict:
    """Promote only the three actual source/frozen/demo parser smoke stages."""
    stages = {}
    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    for stage in ("source-runtime", "frozen-runtime", "qt-demo-ui"):
        try:
            worker = read_json(report / stage / "ai-image-worker-smoke.json")
            text = read_json(report / stage / "ai-text-worker-observation.json")
        except (OSError, ValueError) as error:
            raise ValueError("Missing or invalid AI worker acceptance: " + stage) from error
        packaged = stage != "source-runtime"
        cases, attachments = worker.get("cases", {}), worker.get("assistant_attachments", {})
        pdf_hash = cases.get("application/pdf", {}).get("input_sha256")
        valid = (worker.get("packaged_runtime") is packaged and worker.get("action") == "render_images"
                 and set(cases) == {"application/pdf", "image/png"}
                 and set(attachments) == {"application/pdf", "image/png", docx}
                 and text.get("packaged_runtime") is packaged and text.get("complete") is True
                 and text.get("failed") is False and text.get("source") == "pdf_text"
                 and text.get("warning") is None and text.get("expected_phrase_found") is True
                 and type(text.get("text_characters")) is int and text["text_characters"] > 0
                 and isinstance(pdf_hash, str) and re.fullmatch(r"[0-9a-f]{64}", pdf_hash)
                 and text.get("input_sha256") == pdf_hash)
        extracted = worker.get("text_worker", {})
        valid = valid and (extracted.get("status") == "extracted" and extracted.get("complete") is True
                          and extracted.get("source") == "pdf_text" and extracted.get("warning") is None
                          and extracted.get("original_unchanged") is True
                          and extracted.get("input_sha256") == pdf_hash
                          and extracted.get("expected_phrase") == "LOCAL AI WORKER")
        for mime, pixels in (("application/pdf", [300, 150]), ("image/png", [8, 4])):
            case = cases.get(mime, {})
            valid = valid and (case.get("status") == "rendered" and case.get("pages_total") == 1
                               and case.get("pages_sent") == 1 and case.get("omissions") == []
                               and case.get("pixels") == pixels
                               and type(case.get("image_bytes")) is int and case["image_bytes"] > 0
                               and isinstance(case.get("image_sha256"), str)
                               and re.fullmatch(r"[0-9a-f]{64}", case["image_sha256"]))
        for mime, phrases in (("application/pdf", ["LOCAL AI WORKER"]), ("image/png", []),
                              (docx, ["LOCAL DOCX BODY", "LOCAL DOCX TABLE", "LOCAL DOCX HEADER", "LOCAL DOCX FOOTER"])):
            item = attachments.get(mime, {})
            valid = valid and (item.get("status") == "ready" and item.get("original_unchanged") is True
                               and item.get("text_truncated") is False and item.get("expected_phrases") == phrases
                               and type(item.get("byte_length")) is int and item["byte_length"] > 0
                               and type(item.get("text_characters")) is int
                               and (item["text_characters"] > 0 if phrases else item["text_characters"] == 0)
                               and (item.get("omissions") == [] if phrases else bool(item.get("omissions"))))
        if not valid:
            raise ValueError("Incomplete AI document/image/attachment worker acceptance: " + stage)
        stages[stage] = {"worker": worker, "text_observation": text}
    return stages


def acceptance(report: Path, target: str, commit: str) -> dict:
    report = report_base(report)
    platform, arch, _ = TARGETS[target]
    environment = read_json(report / "native-environment.json")
    if (environment.get("source_commit"), environment.get("platform"), environment.get("architecture")) != (commit, platform, arch):
        raise ValueError("Native environment is not bound to this release commit/target: " + target)
    normal = read_json(report / "frozen-runtime/verification.json")
    crash = read_json(report / "real-gui-runtime/verification.json")
    demo = read_json(report / "demo-runtime/verification.json")
    demo_gui = read_json(report / "frozen-gui-demo/verification.json")
    demo_ui = read_json(report / "qt-demo-ui/verification.json")
    if (normal.get("status") != "passed" or normal.get("packaged_runtime") is not True
            or normal.get("server_exit_code") != 0 or normal.get("server_port_closed") is not True
            or normal.get("checks", {}).get("normal_window_close_with_explicit_test_confirmation") is not True):
        raise ValueError("Native normal-close/renderer acceptance is incomplete: " + target)
    if (crash.get("status") != "passed" or crash.get("server_exit_code") != 0
            or crash.get("server_port_closed_after_cleanup") is not True
            or crash.get("forced_server_cleanup") is not False
            or crash.get("checks", {}).get("owned_backend_application_shutdown_record") is not True):
        raise ValueError("Native real-GUI/EOF acceptance is incomplete: " + target)
    demo_checks = {"real_login_and_persisted_api_edit", "actual_seeded_pdf_fetched_through_authenticated_api",
                   "complete_dataset_and_user_edit_survive_restart_without_reseeding", "independent_readonly_sql_counts"}
    if (demo.get("status") != "passed" or demo.get("packaged_runtime") is not True
            or demo.get("protected_production_paths_unchanged") is not True or demo.get("port_closed_after_cleanup") is not True
            or any(demo.get("checks", {}).get(name) is not True for name in demo_checks)):
        raise ValueError("Native complete-demo seed/persistence/isolation acceptance is incomplete: " + target)
    if (demo_gui.get("status") != "passed" or demo_gui.get("health", {}).get("demo") is not True
            or demo_gui.get("health", {}).get("demo_ready") is not True
            or demo_gui.get("checks", {}).get("demo_seed_ready_from_real_packaged_gui") is not True):
        raise ValueError("The actual native demo GUI was not accepted: " + target)
    ui_checks = {"demo_login_page_in_embedded_renderer", "demo_seeded_login_through_real_ui", "demo_health_from_embedded_fetch",
                 "embedded_pdf_print_output", "normal_window_close_with_explicit_test_confirmation"}
    if (demo_ui.get("status") != "passed" or demo_ui.get("packaged_runtime") is not True
            or demo_ui.get("server_exit_code") != 0 or demo_ui.get("server_port_closed") is not True
            or any(demo_ui.get("checks", {}).get(name) is not True for name in ui_checks)):
        raise ValueError("Native embedded demo login/PDF/normal-close acceptance is incomplete: " + target)
    workers = ai_worker_acceptance(report)
    return {"environment": environment, "normal_close": normal, "gui_loss_eof_recovery": crash,
            "ai_workers": workers,
            "complete_demo": demo, "demo_gui": demo_gui, "demo_embedded_ui": demo_ui}


def source_snapshot(path: Path, commit: str) -> None:
    subprocess.run(["git", "archive", "--format=tar.gz", "--prefix=ImmoManager-Pro/", "--output=" + str(path), commit],
                   cwd=ROOT, check=True, stdin=subprocess.DEVNULL)


def stage_native(packages: Path, reports: Path, sources: Path, output: Path, *, version: str, commit: str,
                 desktop_run: int, ci_run: int, hardening_run: int,
                 qt_manifest: Path = ROOT / "packaging/third-party/qt-sources.json") -> dict:
    check_identity(version, commit)
    if min(desktop_run, ci_run, hardening_run) <= 0 or len({desktop_run, ci_run, hardening_run}) != 3:
        raise ValueError("Three distinct successful CI/native/hardening workflow run IDs are required")
    output.mkdir(parents=True, exist_ok=False)
    evidence: dict[str, Any] = {"schema": "immomanager-native-acceptance/1", "version": version, "source_commit": commit,
                "desktop_workflow_run": desktop_run, "ci_workflow_run": ci_run,
                "hardening_workflow_run": hardening_run, "targets": {}}

    def copy(path):
        destination = output / path.name
        if destination.exists():
            raise ValueError("Ambiguous release asset basename: " + path.name)
        digest(path)
        shutil.copyfile(path, destination)

    for target, (platform, arch, suffix) in TARGETS.items():
        folder = packages / f"Desktop-{target}-native-package"
        proof = acceptance(reports / f"Desktop-{target}-reports", target, commit)
        package = folder / f"ImmoManager-Pro-{version}-{suffix}"
        if target == "windows-x64":
            receipt = read_json(folder / f"ImmoManager-Pro-{version}-Windows-native.json")
            if (receipt.get("source_commit"), receipt.get("version"), receipt.get("platform"), receipt.get("architecture")) != (commit, version, platform, arch):
                raise ValueError("Windows native package commit/version mismatch")
            expected = {package.name, f"ImmoManager-Pro-{version}-Windows.zip"}
            if {entry["file"] for entry in receipt["files"]} != expected:
                raise ValueError("Windows setup and portable package are both required")
            for entry in receipt["files"]:
                if row(folder / entry["file"]) != entry:
                    raise ValueError("Changed Windows native package")
            installer_folder = report_base(reports / f"Desktop-{target}-reports") / "installer"
            installer_proofs = [read_json(path) for path in installer_folder.glob("*/verification.json")]
            if not any(item.get("status") == "passed" and item.get("installer_sha256") == digest(package) for item in installer_proofs):
                raise ValueError("The exact native Windows setup has no passed installer lifecycle")
            proof["installer_lifecycle"] = next(item for item in installer_proofs if item.get("status") == "passed" and item.get("installer_sha256") == digest(package))
        else:
            receipt = read_json(package.with_suffix(package.suffix + ".json"))
            if (receipt.get("source_commit"), receipt.get("version"), receipt.get("platform"), receipt.get("architecture")) != (commit, version, platform, arch):
                raise ValueError("Native package commit/version/architecture mismatch: " + target)
            if any(receipt.get(key) != value for key, value in row(package).items()):
                raise ValueError("Native package bytes differ from acceptance receipt: " + target)
        if receipt.get("workspaces") != ["own", "demo-bw"]:
            raise ValueError("A native release must contain the own-data and prepared-demo workspaces: " + target)
        proof["package"] = receipt
        evidence["targets"][target] = proof
        for file in sorted(folder.iterdir()):
            if not file.is_file():
                raise ValueError("Native package artifact contains an unexpected directory/link")
            copy(file)
    pinned = read_json(qt_manifest)
    if pinned.get("version") != "6.11.3" or len(pinned.get("archives", [])) != 11:
        raise ValueError("Exactly 11 complete pinned Qt source archives are required")
    for entry in pinned["archives"]:
        name = entry["filename"]
        if Path(name).name != name or digest(sources / name) != entry["sha256"]:
            raise ValueError("Missing or changed complete Qt source archive")
        copy(sources / name)
    (output / "qt-source-manifest.json").write_text(json.dumps(pinned, indent=2) + "\n", encoding="utf-8")
    (output / "native-acceptance.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    source = output / f"ImmoManager-Pro-{version}-Source.tar.gz"
    source_snapshot(source, commit)
    with tarfile.open(source) as archive:
        if not any(member.name == "ImmoManager-Pro/pyproject.toml" for member in archive):
            raise ValueError("Incomplete project source snapshot")
    manifest = {"schema": "immomanager-release-assets/1", "version": version, "source_commit": commit,
                "files": [row(path) for path in sorted(output.iterdir())]}
    (output / "release-assets.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    sums = [f"{digest(path)}  {path.name}" for path in sorted(output.iterdir())]
    (output / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="ascii")
    return manifest


def finalize_signed(staged: Path, installer: Path, portable: Path, metadata: Path, output: Path,
                    *, version: str, commit: str) -> dict:
    """Keep native Mac/Linux bytes, replacing the CI Windows baseline with signed output."""
    check_identity(version, commit)
    source = read_json(staged / "release-assets.json")
    if (source.get("source_commit"), source.get("version")) != (commit, version):
        raise ValueError("The native assets do not belong to this exact signed release")
    receipt = read_json(installer.with_suffix(".build.json"))
    if (receipt.get("signature_status") != "Valid" or receipt.get("version") != version
            or receipt.get("installer_sha256") != digest(installer)):
        raise ValueError("A signed release requires the exact verified Authenticode installer")
    customer_macos_acceptance(staged, version=version, commit=commit)
    output.mkdir(parents=True, exist_ok=False)
    for entry in source["files"]:
        path = staged / entry["file"]
        if Path(entry["file"]).name != entry["file"] or row(path) != entry:
            raise ValueError("Native release artifact changed before signing promotion")
        if path.name.startswith((f"ImmoManager-Pro-{version}-Windows", f"ImmoManager-Pro-{version}-Setup-x64")):
            continue
        name = "native-baseline-acceptance.json" if path.name == "native-acceptance.json" else path.name
        shutil.copyfile(path, output / name)
    for path in (installer, installer.with_suffix(".build.json"), installer.with_suffix(".sha256"), portable,
                 *sorted(metadata.glob("*.json"))):
        digest(path)
        if (output / path.name).exists():
            raise ValueError("Duplicate signed release asset name")
        shutil.copyfile(path, output / path.name)
    manifest = {"schema": "immomanager-release-assets/1", "version": version, "source_commit": commit,
                "windows_signing": "Valid Authenticode installer; release build and certificate verification recorded separately",
                "files": [row(path) for path in sorted(output.iterdir())]}
    (output / "release-assets.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "SHA256SUMS.txt").write_text("\n".join(f"{digest(path)}  {path.name}" for path in sorted(output.iterdir())) + "\n", encoding="ascii")
    return manifest


def embedded_macos_runtime(value: dict, *, architecture: str, commit: str, package_sha256: str) -> dict:
    """Recheck the complete canonical contract, not self-asserted success flags."""
    required = {"environment", "normal_close", "gui_loss_eof_recovery", "ai_workers",
                "complete_demo", "demo_gui", "demo_embedded_ui"}
    if not isinstance(value, dict) or set(value) != required or not all(isinstance(v, dict) for v in value.values()):
        raise ValueError("Missing complete signed native runtime acceptance")
    environment = value["environment"]
    if (environment.get("customer_signed_runtime") is not True
            or environment.get("customer_package_sha256") != package_sha256):
        raise ValueError("Signed runtime is not bound to the final customer image")
    workers = value["ai_workers"]
    if set(workers) != {"source-runtime", "frozen-runtime", "qt-demo-ui"}:
        raise ValueError("Missing complete signed AI worker stages")
    # These files contain only the supplied bounded report dictionaries. Reuse
    # the single promotion validator so a new check cannot be omitted here.
    with tempfile.TemporaryDirectory(prefix="immo-signed-evidence-") as directory:
        root = Path(directory)
        entries = {"native-environment.json": environment,
                   "frozen-runtime/verification.json": value["normal_close"],
                   "real-gui-runtime/verification.json": value["gui_loss_eof_recovery"],
                   "demo-runtime/verification.json": value["complete_demo"],
                   "frozen-gui-demo/verification.json": value["demo_gui"],
                   "qt-demo-ui/verification.json": value["demo_embedded_ui"]}
        for stage, pair in workers.items():
            if not isinstance(pair, dict) or set(pair) != {"worker", "text_observation"}:
                raise ValueError("Missing signed AI worker/text observation")
            entries[stage + "/ai-image-worker-smoke.json"] = pair["worker"]
            entries[stage + "/ai-text-worker-observation.json"] = pair["text_observation"]
        for name, payload in entries.items():
            path = root / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
        return acceptance(root, "macos-" + architecture, commit)


def customer_macos_acceptance(folder: Path, *, version: str, commit: str) -> dict:
    """Unsigned/ad-hoc validation packages cannot become customer Mac releases."""
    accepted = {}
    for arch in ("x64", "arm64"):
        package = folder / f"ImmoManager-Pro-{version}-macOS-{arch}.dmg"
        receipt = read_json(package.with_suffix(".dmg.json"))
        proof = receipt.get("customer_signing", {})
        if (receipt.get("source_commit") != commit or receipt.get("version") != version
                or receipt.get("architecture") != arch or receipt.get("platform") != "darwin"
                or any(receipt.get(key) != value for key, value in row(package).items())
                or proof.get("schema") != "immomanager-macos-customer-signing/1"
                or proof.get("source_commit") != commit or proof.get("architecture") != arch
                or proof.get("developer_id_verified") is not True or proof.get("hardened_runtime_verified") is not True
                or proof.get("notarization_status") != "Accepted" or proof.get("stapler_validated") is not True
                or proof.get("gatekeeper_accepted") is not True
                or proof.get("signed_runtime_verified") is not True
                or proof.get("signed_runtime_package_sha256") != digest(package)
                or proof.get("accepted_package_sha256") != digest(package)):
            raise ValueError("Customer release requires verified Developer ID and notarization for macOS " + arch)
        embedded_macos_runtime(proof.get("signed_runtime_acceptance"), architecture=arch, commit=commit,
                               package_sha256=digest(package))
        accepted[arch] = proof
    return accepted


def overlay_customer_macos(staged: Path, packages: Path, reports: Path, output: Path,
                          *, version: str, commit: str) -> dict:
    """Create a new complete inventory; never partially overwrite accepted bytes."""
    check_identity(version, commit)
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    original = read_json(staged / "release-assets.json")
    if (original.get("source_commit"), original.get("version")) != (commit, version):
        raise ValueError("The baseline assets do not belong to this exact customer release")
    validate_required_assets(staged, original, version=version, commit=commit)
    inventory = {entry["file"]: entry for entry in original["files"]}
    if {p.name for p in staged.iterdir()} != set(inventory) | {"release-assets.json", "SHA256SUMS.txt"}:
        raise ValueError("Unexpected baseline release inventory")
    for name, entry in inventory.items():
        if Path(name).name != name or row(staged / name) != entry:
            raise ValueError("The baseline inventory changed before customer promotion")
    expected_sums = "\n".join(f"{digest(p)}  {p.name}" for p in sorted(staged.iterdir())
                               if p.name != "SHA256SUMS.txt") + "\n"
    if (staged / "SHA256SUMS.txt").read_text(encoding="ascii") != expected_sums:
        raise ValueError("The baseline checksum inventory changed")
    baseline = read_json(staged / "native-acceptance.json")
    accepted_run = baseline["desktop_workflow_run"]
    replacement = {}
    proofs = {}
    for arch in ("x64", "arm64"):
        folder = packages / f"Customer-macos-{arch}-verified"
        name = f"ImmoManager-Pro-{version}-macOS-{arch}.dmg"
        expected = {name, name + ".json", name + ".sha256"}
        if not folder.is_dir() or folder.is_symlink() or {p.name for p in folder.iterdir()} != expected:
            raise ValueError("Only the canonical verified Mac image, receipt and checksum are accepted")
        package = folder / name
        receipt = read_json(folder / (name + ".json"))
        proof = receipt.get("customer_signing", {})
        runtime = acceptance(reports / f"Customer-macos-{arch}-reports", "macos-" + arch, commit)
        if (receipt.get("customer_build", {}).get("desktop_workflow_run") != accepted_run
                or runtime["environment"].get("desktop_workflow_run") != accepted_run
                or proof.get("signed_runtime_acceptance") != runtime):
            raise ValueError("Signed runtime/image is not bound to the accepted desktop run and actual reports")
        if (folder / (name + ".sha256")).read_text(encoding="ascii") != digest(package) + "  " + name + "\n":
            raise ValueError("Signed Mac checksum does not match its final package")
        replacement.update({p.name: p for p in folder.iterdir()})
        proofs[arch] = runtime
    # Validate both architectures together before any output can be published.
    expected_rows = {**inventory, **{name: row(path) for name, path in replacement.items()}}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".customer-mac-overlay-", dir=output.parent))
    try:
        for name in sorted(set(inventory) | set(replacement)):
            shutil.copyfile(replacement.get(name, staged / name), temporary / name)
            if row(temporary / name) != expected_rows[name]:
                raise ValueError("A release asset changed while copying the customer inventory")
        customer_macos_acceptance(temporary, version=version, commit=commit)
        proof_file = temporary / "customer-macos-acceptance.json"
        proof_file.write_text(json.dumps({"schema": "immomanager-signed-macos-acceptance/1", "source_commit": commit,
            "version": version, "desktop_workflow_run": accepted_run, "targets": proofs}, indent=2) + "\n", encoding="utf-8")
        manifest = {**original, "customer_macos_signing": "Developer ID and notarized final images with actual signed runtime acceptance",
                    "files": [row(p) for p in sorted(temporary.iterdir())]}
        (temporary / "release-assets.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (temporary / "SHA256SUMS.txt").write_text("\n".join(f"{digest(p)}  {p.name}" for p in sorted(temporary.iterdir())
            if p.name != "SHA256SUMS.txt") + "\n", encoding="ascii")
        validate_required_assets(temporary, manifest, version=version, commit=commit)
        if output.exists():
            raise FileExistsError(output)
        os.rename(temporary, output)
        return manifest
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def validate_required_assets(folder: Path, manifest: dict, *, version: str, commit: str) -> None:
    """A self-consistent smaller inventory is not a complete native release."""
    entries = manifest.get("files")
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError("Missing complete release inventory")
    names = [entry.get("file") for entry in entries]
    required = {f"ImmoManager-Pro-{version}-{suffix}" for _, _, suffix in TARGETS.values()}
    required |= {f"ImmoManager-Pro-{version}-Windows.zip", f"ImmoManager-Pro-{version}-Source.tar.gz",
                 "qt-source-manifest.json"}
    if len(names) != len(set(names)) or not required.issubset(names):
        raise ValueError("Missing required native release assets or duplicate inventory entries")
    evidence_name = "native-baseline-acceptance.json" if "native-baseline-acceptance.json" in names else "native-acceptance.json"
    evidence = read_json(folder / evidence_name)
    if (evidence_name not in names or evidence.get("source_commit") != commit or evidence.get("version") != version
            or set(evidence.get("targets", {})) != set(TARGETS)):
        raise ValueError("Missing complete exact-commit native acceptance")
    runs = [evidence.get(key) for key in ("desktop_workflow_run", "ci_workflow_run", "hardening_workflow_run")]
    if not all(type(value) is int and value > 0 for value in runs) or len(set(runs)) != 3:
        raise ValueError("Missing complete distinct CI/native/hardening run binding")
    pinned = read_json(folder / "qt-source-manifest.json")
    archives = pinned.get("archives", [])
    if pinned.get("version") != "6.11.3" or len(archives) != 11:
        raise ValueError("Missing complete pinned Qt source inventory")
    for entry in archives:
        name = entry.get("filename")
        if not isinstance(name, str) or Path(name).name != name or name not in names or digest(folder / name) != entry.get("sha256"):
            raise ValueError("Missing or changed required Qt source archive")


def github_get(repository: str, suffix: str) -> dict | None:
    endpoint = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    request = urllib.request.Request(endpoint + "/repos/" + repository + "/" + suffix,
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def check_release_target(repository: str, tag: str, commit: str, *, getter=github_get) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid GitHub repository")
    encoded = urllib.parse.quote(tag, safe="")
    if getter(repository, "releases/tags/" + encoded) is not None:
        raise ValueError("An existing release will never be overwritten")
    reference = getter(repository, "git/ref/tags/" + encoded)
    if reference is None:
        return False
    target = reference["object"]
    for _ in range(5):
        if target.get("type") == "commit":
            if target.get("sha") != commit:
                raise ValueError("Existing release tag points to a different commit; refusing to move it")
            return True
        if target.get("type") != "tag" or not re.fullmatch(r"[0-9a-f]{40}", target.get("sha", "")):
            break
        annotated = getter(repository, "git/tags/" + target["sha"])
        if annotated is None:
            break
        target = annotated["object"]
    raise ValueError("Unrecognized or cyclic annotated release tag")


def publish_release(folder: Path, *, version: str, commit: str, tag: str, repository: str, allow_unsigned: bool) -> None:
    check_identity(version, commit)
    check_policy(version, publish=True, tag=tag, allow_unsigned=allow_unsigned)
    manifest = read_json(folder / "release-assets.json")
    if (manifest.get("source_commit"), manifest.get("version")) != (commit, version):
        raise ValueError("The staged assets are not from this exact release commit")
    validate_required_assets(folder, manifest, version=version, commit=commit)
    for entry in manifest["files"]:
        if Path(entry["file"]).name != entry["file"] or row(folder / entry["file"]) != entry:
            raise ValueError("The staged release assets changed after native acceptance")
    expected_names = {entry["file"] for entry in manifest["files"]} | {"release-assets.json", "SHA256SUMS.txt"}
    if {path.name for path in folder.iterdir()} != expected_names:
        raise ValueError("Unexpected files are not eligible for release publication")
    expected_sums = "\n".join(f"{digest(path)}  {path.name}" for path in sorted(folder.iterdir()) if path.name != "SHA256SUMS.txt") + "\n"
    if (folder / "SHA256SUMS.txt").read_text(encoding="ascii") != expected_sums:
        raise ValueError("The final release checksum manifest does not match the assets")
    if not allow_unsigned:
        signed = read_json(folder / f"ImmoManager-Pro-{version}-Setup-x64.build.json")
        if signed.get("signature_status") != "Valid":
            raise ValueError("A regular release requires verified Authenticode signing")
        customer_macos_acceptance(folder, version=version, commit=commit)
    exists = check_release_target(repository, tag, commit)
    if not exists:
        # Create-if-absent only: never update/force a ref. A concurrent creation
        # is re-read and must still resolve to our exact reviewed commit.
        created = subprocess.run(["gh", "api", "--method", "POST", f"repos/{repository}/git/refs",
            "-f", "ref=refs/tags/" + tag, "-f", "sha=" + commit], capture_output=True, text=True)
        if created.returncode != 0 and not check_release_target(repository, tag, commit):
            raise RuntimeError("Could not create the new exact-commit release tag")
    check_release_target(repository, tag, commit)
    notes = folder / "release-notes.md"
    policy = ("This explicitly selected beta is a test prerelease published without requiring a Windows publisher signature. "
              "The actual Windows signature status is recorded in its Windows-native.json receipt. " if allow_unsigned else
              "The Windows installer has a verified timestamped Authenticode publisher signature. ")
    mac_policy = ("macOS packages are ad-hoc signed for operation, without Developer-ID or notarization. "
                  "Verify SHA256SUMS.txt and the native acceptance evidence; no macOS platform approval is claimed. "
                  if allow_unsigned else "Both macOS packages have verified Developer-ID, hardened runtime, notarization and stapled tickets. ")
    notes.write_text((ROOT / "docs/RELEASE_NOTES.md").read_text(encoding="utf-8") +
        "\n\n## Signing and native acceptance of this release\n\n" + policy +
        mac_policy +
        "All five native packages passed their acceptance workflows on the exact source commit " + commit + ". "
        "Complete Qt source archives and the application source snapshot accompany this release.\n", encoding="utf-8")
    files = sorted(path for path in folder.iterdir() if path.is_file() and path != notes)
    command = ["gh", "release", "create", tag, *map(str, files), "--repo", repository, "--verify-tag",
               "--title", "ImmoManager Pro " + version, "--notes-file", str(notes)]
    if "-" in version:
        command.append("--prerelease")
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    stamp = sub.add_parser("stamp-windows")
    stamp.add_argument("folder", type=Path)
    stamp.add_argument("--signature", required=True)
    stage = sub.add_parser("stage")
    for name in ("packages", "reports", "sources", "output"):
        stage.add_argument("--" + name, type=Path, required=True)
    stage.add_argument("--desktop-run", type=int, required=True)
    stage.add_argument("--ci-run", type=int, required=True)
    stage.add_argument("--hardening-run", type=int, required=True)
    final = sub.add_parser("finalize-signed")
    for name in ("staged", "installer", "portable", "metadata", "output"):
        final.add_argument("--" + name, type=Path, required=True)
    overlay = sub.add_parser("overlay-customer-macos")
    for name in ("staged", "packages", "reports", "output"):
        overlay.add_argument("--" + name, type=Path, required=True)
    publish = sub.add_parser("publish")
    publish.add_argument("folder", type=Path)
    publish.add_argument("--tag", required=True)
    publish.add_argument("--repository", required=True)
    publish.add_argument("--allow-unsigned", action="store_true")
    for command in (stamp, stage, final, overlay, publish):
        command.add_argument("--version", required=True)
        command.add_argument("--commit", required=True)
    args = parser.parse_args()
    check_identity(args.version, args.commit)
    if args.command == "stamp-windows":
        print(stamp_windows(args.folder, version=args.version, commit=args.commit, signature=args.signature))
    elif args.command == "stage":
        print(json.dumps(stage_native(args.packages, args.reports, args.sources, args.output,
            version=args.version, commit=args.commit, desktop_run=args.desktop_run, ci_run=args.ci_run,
            hardening_run=args.hardening_run)))
    elif args.command == "finalize-signed":
        print(json.dumps(finalize_signed(args.staged, args.installer, args.portable, args.metadata, args.output,
            version=args.version, commit=args.commit)))
    elif args.command == "overlay-customer-macos":
        print(json.dumps(overlay_customer_macos(args.staged, args.packages, args.reports, args.output,
            version=args.version, commit=args.commit)))
    else:
        publish_release(args.folder, version=args.version, commit=args.commit, tag=args.tag,
            repository=args.repository, allow_unsigned=args.allow_unsigned)


if __name__ == "__main__":
    main()
