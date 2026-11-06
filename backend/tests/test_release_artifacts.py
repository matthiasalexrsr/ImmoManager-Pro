"""Release promotion boundaries; these tests never call GitHub or native installers."""
import io
import json
import subprocess
import tarfile

import pytest

from scripts import release_artifacts as release

VERSION = "2.0.0-beta.1"
COMMIT = "a" * 40


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def worker_fixture(report):
    """Controlled promotion-contract fixture, never a claim of native execution."""
    pdf, png, docx = "application/pdf", "image/png", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    for stage in ("source-runtime", "frozen-runtime", "qt-demo-ui"):
        packaged = stage != "source-runtime"
        cases = {mime: {"input_sha256": "c"*64, "status": "rendered", "pages_total": 1, "pages_sent": 1,
                       "omissions": [], "pixels": pixels, "image_sha256": "d"*64, "image_bytes": 100}
                 for mime, pixels in ((pdf, [300, 150]), (png, [8, 4]))}
        attachments = {mime: {"status": "ready", "input_sha256": "c"*64, "byte_length": 100,
                             "expected_phrases": phrases, "text_characters": 70 if phrases else 0,
                             "text_truncated": False, "omissions": [] if phrases else ["image-only"], "original_unchanged": True}
                       for mime, phrases in ((pdf, ["LOCAL AI WORKER"]), (png, []),
                           (docx, ["LOCAL DOCX BODY", "LOCAL DOCX TABLE", "LOCAL DOCX HEADER", "LOCAL DOCX FOOTER"]))}
        write(report/stage/"ai-image-worker-smoke.json", {"packaged_runtime": packaged, "action": "render_images",
              "cases": cases, "text_worker": {"status": "extracted", "source": "pdf_text", "complete": True,
              "warning": None, "input_sha256": "c"*64, "original_unchanged": True, "expected_phrase": "LOCAL AI WORKER"},
              "assistant_attachments": attachments})
        write(report/stage/"ai-text-worker-observation.json", {"packaged_runtime": packaged, "complete": True,
              "failed": False, "source": "pdf_text", "warning": None, "text_characters": 16,
              "expected_phrase_found": True, "input_sha256": "c"*64})


def customer_macos_fixture(folder):
    """Synthetic native-signing contract; no real signing/notarization here."""
    for arch in ("x64", "arm64"):
        path = folder/f"ImmoManager-Pro-{VERSION}-macOS-{arch}.dmg"
        receipt = release.read_json(path.with_suffix(".dmg.json"))
        runtime = release.read_json(folder/"native-acceptance.json")["targets"]["macos-"+arch]
        runtime.pop("package")
        runtime["environment"].update(customer_signed_runtime=True, customer_package_sha256=release.digest(path))
        receipt["customer_signing"] = {"schema": "immomanager-macos-customer-signing/1", "source_commit": COMMIT,
            "architecture": arch, "developer_id_verified": True, "hardened_runtime_verified": True,
            "notarization_status": "Accepted", "stapler_validated": True, "gatekeeper_accepted": True,
            "signed_runtime_verified": True, "signed_runtime_package_sha256": release.digest(path),
            "accepted_package_sha256": release.digest(path), "signed_runtime_acceptance": runtime}
        write(path.with_suffix(".dmg.json"), receipt)
    manifest = release.read_json(folder/"release-assets.json")
    manifest["files"] = [release.row(folder/entry["file"]) for entry in manifest["files"]]
    write(folder/"release-assets.json", manifest)
    (folder/"SHA256SUMS.txt").write_text("\n".join(f"{release.digest(p)}  {p.name}"
        for p in sorted(folder.iterdir()) if p.name != "SHA256SUMS.txt")+"\n", encoding="ascii")


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    packages, reports, sources = [tmp_path / name for name in ("packages", "reports", "sources")]
    sources.mkdir()
    for target, (platform, arch, suffix) in release.TARGETS.items():
        folder = packages / f"Desktop-{target}-native-package"
        package = folder / f"ImmoManager-Pro-{VERSION}-{suffix}"
        folder.mkdir(parents=True)
        package.write_bytes(target.encode())
        if target == "windows-x64":
            write(package.with_suffix(".build.json"), {"version": VERSION, "installer_sha256": release.digest(package),
                                                       "desktop_runtime": {"workspaces": ["own", "demo-bw"]}})
            portable = folder / f"ImmoManager-Pro-{VERSION}-Windows.zip"
            portable.write_bytes(b"same native Windows payload fixture")
            release.stamp_windows(folder, version=VERSION, commit=COMMIT, signature="NotSigned")
        else:
            write(package.with_suffix(package.suffix + ".json"), {"source_commit": COMMIT, "version": VERSION,
                "platform": platform, "architecture": arch, "workspaces": ["own", "demo-bw"], **release.row(package)})
        report = reports / f"Desktop-{target}-reports"
        write(report / "native-environment.json", {"source_commit": COMMIT, "platform": platform, "architecture": arch})
        write(report / "frozen-runtime/verification.json", {"status": "passed", "packaged_runtime": True,
            "server_exit_code": 0, "server_port_closed": True,
            "checks": {"normal_window_close_with_explicit_test_confirmation": True}})
        write(report / "real-gui-runtime/verification.json", {"status": "passed", "server_exit_code": 0,
            "server_port_closed_after_cleanup": True, "forced_server_cleanup": False,
            "checks": {"owned_backend_application_shutdown_record": True}})
        write(report / "demo-runtime/verification.json", {"status": "passed", "packaged_runtime": True,
            "protected_production_paths_unchanged": True, "port_closed_after_cleanup": True,
            "checks": {key: True for key in ("real_login_and_persisted_api_edit",
                "actual_seeded_pdf_fetched_through_authenticated_api", "complete_dataset_and_user_edit_survive_restart_without_reseeding",
                "independent_readonly_sql_counts")}})
        write(report / "frozen-gui-demo/verification.json", {"status": "passed", "health": {"demo": True, "demo_ready": True},
            "checks": {"demo_seed_ready_from_real_packaged_gui": True}})
        write(report / "qt-demo-ui/verification.json", {"status": "passed", "packaged_runtime": True,
            "server_exit_code": 0, "server_port_closed": True, "checks": {key: True for key in (
                "demo_login_page_in_embedded_renderer", "demo_seeded_login_through_real_ui", "demo_health_from_embedded_fetch",
                "embedded_pdf_print_output", "normal_window_close_with_explicit_test_confirmation")}})
        worker_fixture(report)
        if target == "windows-x64":
            write(report / "installer/immoqa-owned/verification.json", {"status": "passed", "installer_sha256": release.digest(package)})
    archives = []
    for index in range(11):
        archive = sources / f"qt-{index}.tar.xz"
        archive.write_bytes(str(index).encode())
        archives.append({"filename": archive.name, "sha256": release.digest(archive)})
    manifest = tmp_path / "qt-manifest.json"
    write(manifest, {"version": "6.11.3", "archives": archives})

    def snapshot(path, commit):
        assert commit == COMMIT
        with tarfile.open(path, "w:gz") as archive:
            member = tarfile.TarInfo("ImmoManager-Pro/pyproject.toml")
            content = b'[project]\nversion="2.0.0-beta.1"\n'
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))

    monkeypatch.setattr(release, "source_snapshot", snapshot)
    return {"packages": packages, "reports": reports, "sources": sources, "output": tmp_path / "staged",
            "version": VERSION, "commit": COMMIT, "desktop_run": 123, "ci_run": 456,
            "hardening_run": 789, "qt_manifest": manifest}


def test_complete_five_target_release_has_bound_sources_and_every_final_checksum(inputs):
    value = release.stage_native(**inputs)
    folder = inputs["output"]
    assert value["source_commit"] == COMMIT
    evidence = release.read_json(folder / "native-acceptance.json")
    assert set(evidence["targets"]) == set(release.TARGETS)
    assert len(list(folder.glob("qt-*.tar.xz"))) == 11
    for line in (folder / "SHA256SUMS.txt").read_text().splitlines():
        checksum, name = line.split("  ", 1)
        assert release.digest(folder / name) == checksum


def test_real_nested_upload_artifact_reports_layout_keeps_commit_and_installer_binding(inputs):
    for target in release.TARGETS:
        root = inputs["reports"] / f"Desktop-{target}-reports"
        original = list(root.iterdir())
        nested = root / "artifacts/desktop-reports"
        nested.mkdir(parents=True)
        for path in original:
            path.rename(nested / path.name)
    release.stage_native(**inputs)
    evidence = release.read_json(inputs["output"] / "native-acceptance.json")
    assert set(evidence["targets"]) == set(release.TARGETS)
    windows = evidence["targets"]["windows-x64"]
    assert windows["environment"]["source_commit"] == COMMIT
    assert windows["installer_lifecycle"]["installer_sha256"] == windows["package"]["files"][0]["sha256"]


def test_report_layout_never_searches_an_arbitrary_subdirectory(inputs):
    root = inputs["reports"] / "Desktop-macos-arm64-reports"
    source = root / "native-environment.json"
    other = root / "unapproved/deep"
    other.mkdir(parents=True)
    source.rename(other / source.name)
    with pytest.raises(ValueError, match="Missing or linked release evidence"):
        release.stage_native(**inputs)


def test_malformed_canonical_directory_cannot_fall_back_to_flat_evidence(inputs):
    root = inputs["reports"] / "Desktop-macos-arm64-reports"
    (root / "artifacts").mkdir()
    (root / "artifacts/desktop-reports").write_text("not a report directory")
    with pytest.raises(ValueError, match="canonical native reports directory"):
        release.stage_native(**inputs)


@pytest.mark.parametrize("fault", ["wrong-commit", "changed-package", "failed-gui", "missing-platform", "missing-source", "wrong-installer", "demo-gui", "demo-ui"])
def test_incomplete_or_other_commit_artifacts_never_pass_staging(inputs, fault):
    target = "macos-arm64"
    folder = inputs["packages"] / f"Desktop-{target}-native-package"
    package = folder / f"ImmoManager-Pro-{VERSION}-macOS-arm64.dmg"
    if fault == "wrong-commit":
        receipt = release.read_json(package.with_suffix(".dmg.json"))
        write(package.with_suffix(".dmg.json"), {**receipt, "source_commit": "b" * 40})
    elif fault == "changed-package":
        package.write_bytes(b"changed after native acceptance")
    elif fault == "failed-gui":
        write(inputs["reports"] / f"Desktop-{target}-reports/real-gui-runtime/verification.json", {"status": "failed"})
    elif fault == "missing-platform":
        package.unlink()
    elif fault == "missing-source":
        (inputs["sources"] / "qt-10.tar.xz").unlink()
    elif fault in {"demo-gui", "demo-ui"}:
        name = "frozen-gui-demo" if fault == "demo-gui" else "qt-demo-ui"
        write(inputs["reports"] / f"Desktop-{target}-reports/{name}/verification.json", {"status": "failed"})
    else:
        write(inputs["reports"] / "Desktop-windows-x64-reports/installer/immoqa-owned/verification.json",
              {"status": "passed", "installer_sha256": "f" * 64})
    with pytest.raises(ValueError):
        release.stage_native(**inputs)


@pytest.mark.parametrize("version,publish,tag,unsigned", [
    ("2.0.0", True, "v2.0.0", True), ("2.0.0-rc.1", True, "v2.0.0-rc.1", True),
    (VERSION, False, "", True), (VERSION, True, "v9.0.0", True), (VERSION, False, "v" + VERSION, False),
])
def test_unsigned_or_mismatched_policy_requires_an_explicit_exact_beta(version, publish, tag, unsigned):
    with pytest.raises(ValueError):
        release.check_policy(version, publish=publish, tag=tag, allow_unsigned=unsigned)


def test_only_missing_or_same_commit_tag_is_eligible_and_existing_releases_are_never_overwritten():
    assert release.check_release_target("owner/repo", "v" + VERSION, COMMIT, getter=lambda *_: None) is False
    def getter(_repo, suffix):
        return None if suffix.startswith("releases/") else {"object": {"type": "commit", "sha": COMMIT}}
    assert release.check_release_target("owner/repo", "v" + VERSION, COMMIT, getter=getter) is True
    with pytest.raises(ValueError, match="existing release"):
        release.check_release_target("owner/repo", "v" + VERSION, COMMIT, getter=lambda *_: {"id": 1})
    with pytest.raises(ValueError, match="different commit"):
        release.check_release_target("owner/repo", "v" + VERSION, "b" * 40, getter=getter)


def test_beta_publication_uses_literal_argv_verified_tag_and_exact_staged_assets(inputs, monkeypatch):
    release.stage_native(**inputs)
    calls = []
    monkeypatch.setattr(release, "check_release_target", lambda *a, **k: True)
    def execute(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(release.subprocess, "run", execute)
    release.publish_release(inputs["output"], version=VERSION, commit=COMMIT, tag="v" + VERSION,
                            repository="owner/repo", allow_unsigned=True)
    command = calls[0][0]
    assert command[:4] == ["gh", "release", "create", "v" + VERSION]
    assert "--verify-tag" in command and "--prerelease" in command
    assert "--clobber" not in command and "--force" not in command
    assert len([part for part in command if part.endswith(".dmg")]) == 2
    assert len([part for part in command if part.endswith(".tar.gz")]) == 3


def test_changed_final_checksum_manifest_blocks_publication_before_any_remote_action(inputs, monkeypatch):
    release.stage_native(**inputs)
    (inputs["output"] / "SHA256SUMS.txt").write_text("untrusted replacement")
    monkeypatch.setattr(release, "check_release_target", lambda *a, **k: pytest.fail("No remote access before validation"))
    with pytest.raises(ValueError, match="checksum manifest"):
        release.publish_release(inputs["output"], version=VERSION, commit=COMMIT, tag="v" + VERSION,
                                repository="owner/repo", allow_unsigned=True)


@pytest.mark.parametrize("signature", ["Valid", "NotSigned"])
def test_regular_release_replaces_only_windows_baseline_with_verified_signed_output(inputs, tmp_path, signature):
    release.stage_native(**inputs)
    customer_macos_fixture(inputs["output"])
    signed, metadata, final = [tmp_path / name for name in ("signed", "sbom", "final")]
    signed.mkdir()
    metadata.mkdir()
    setup = signed / f"ImmoManager-Pro-{VERSION}-Setup-x64.exe"
    setup.write_bytes(b"signed current-commit Windows payload fixture")
    write(setup.with_suffix(".build.json"), {"version": VERSION, "signature_status": signature, "installer_sha256": release.digest(setup)})
    setup.with_suffix(".sha256").write_text(release.digest(setup) + "  " + setup.name)
    portable = signed / f"ImmoManager-Pro-{VERSION}-Windows.zip"
    portable.write_bytes(b"signed GUI and CLI portable fixture")
    write(metadata / "sbom-python.cdx.json", {"bomFormat": "CycloneDX"})
    options = dict(staged=inputs["output"], installer=setup, portable=portable, metadata=metadata, output=final,
                   version=VERSION, commit=COMMIT)
    if signature != "Valid":
        with pytest.raises(ValueError, match="verified Authenticode"):
            release.finalize_signed(**options)
        assert not final.exists()
        return
    manifest = release.finalize_signed(**options)
    assert (final / setup.name).read_bytes() == setup.read_bytes()
    assert not (final / f"ImmoManager-Pro-{VERSION}-Windows-native.json").exists()
    assert (final / "native-baseline-acceptance.json").is_file()
    assert len(list(final.glob("*.dmg"))) == 2
    assert len(list(final.glob("*Linux-*.tar.gz"))) == 2
    assert manifest["source_commit"] == COMMIT
    assert "windows_signing" in manifest
