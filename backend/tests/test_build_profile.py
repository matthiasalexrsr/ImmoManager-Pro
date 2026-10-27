"""Release profile regression checks: ambient packages and stale assets cannot opt in."""

import json
from pathlib import Path

import pytest

from tools import build_profile as profile


@pytest.fixture(autouse=True)
def clean_profile(monkeypatch):
    for key in ("IMMO_BUILD_DOCUMENT_TOOLS", "IMMO_BUILD_BANK", "IMMO_BUILD_PURPOSE", "IMMO_LICENSE_APPROVAL_FILE"):
        monkeypatch.delenv(key, raising=False)


def test_core_excludes_ambient_optional_packages(monkeypatch):
    monkeypatch.setattr(profile, "find_spec", lambda name: object())
    assert profile.selected_optional_packages() == []
    assert set(profile.DOCUMENT + profile.BANK + profile.AI) <= set(profile.excluded_optional_packages())


@pytest.mark.parametrize("purpose", [None, "", "commercial", "production"])
def test_documents_require_explicit_purpose(monkeypatch, purpose):
    monkeypatch.setenv("IMMO_BUILD_DOCUMENT_TOOLS", "1")
    if purpose is not None:
        monkeypatch.setenv("IMMO_BUILD_PURPOSE", purpose)
    with pytest.raises(RuntimeError):
        profile.document_tools()


@pytest.mark.parametrize("missing", ["PyMuPDF", "superdoc", "@superdoc/docx-engine"])
def test_every_document_component_needs_rights(monkeypatch, tmp_path, missing):
    data = {
        "components": {
            name: {"reference": "synthetic contract test", "distribution": True}
            for name in ("PyMuPDF", "superdoc", "@superdoc/docx-engine")
        }
    }
    del data["components"][missing]
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("IMMO_BUILD_DOCUMENT_TOOLS", "1")
    monkeypatch.setenv("IMMO_BUILD_PURPOSE", "licensed")
    monkeypatch.setenv("IMMO_LICENSE_APPROVAL_FILE", str(approval))
    with pytest.raises(RuntimeError, match="Missing distribution rights"):
        profile.document_tools()


def test_stale_editor_assets_block_core_bundle(tmp_path):
    dist = tmp_path / "frontend/dist"
    (dist / "document-editor").mkdir(parents=True)
    (dist / "product-profile.json").write_text('{"document_tools":false,"purpose":"core"}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="do not match"):
        profile.verify_frontend_profile(tmp_path)


def test_validation_assets_cannot_be_relabelled_for_customers(tmp_path):
    dist = tmp_path / "frontend/dist"
    dist.mkdir(parents=True)
    (dist / "product-profile.json").write_text('{"document_tools":false,"purpose":"validation"}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="validation build"):
        profile.verify_frontend_profile(tmp_path)


def test_required_optional_engine_missing_stops_build(monkeypatch):
    monkeypatch.setenv("IMMO_BUILD_DOCUMENT_TOOLS", "1")
    monkeypatch.setenv("IMMO_BUILD_PURPOSE", "validation")
    monkeypatch.setattr(profile, "find_spec", lambda name: None)
    with pytest.raises(RuntimeError, match="are missing"):
        profile.selected_optional_packages()


def test_core_metadata_has_single_version_source():
    import tomllib

    root = Path(__file__).resolve().parents[2]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert "dependencies" in data["project"]["dynamic"]
    assert data["tool"]["setuptools"]["dynamic"]["dependencies"]["file"] == ["requirements-runtime.txt"]
    assert "-r requirements-runtime.txt" in (root / "requirements.txt").read_text(encoding="utf-8")


def test_mpl_archive_contains_the_installed_covered_sources(tmp_path):
    import tarfile
    from importlib import metadata

    from tools import third_party_notices

    files = third_party_notices.covered_sources(tmp_path)
    archive = next(tmp_path / name for name in files if name.endswith('.tar.gz'))
    dist = metadata.distribution('certifi')
    with tarfile.open(archive) as source:
        for name in ('core.py', '__init__.py', 'cacert.pem'):
            member = source.extractfile(f'certifi-{dist.version}/certifi/{name}')
            assert member is not None
            assert member.read() == Path(str(dist.locate_file('certifi/' + name))).read_bytes()


def test_modified_covered_archive_blocks_distribution(tmp_path, monkeypatch):
    import hashlib

    from tools import third_party_notices

    folder = tmp_path / 'packaging/third-party'
    folder.mkdir(parents=True)
    (folder / 'sample.tar.gz').write_bytes(b'corrupted source archive')
    (folder / 'sources.json').write_text(json.dumps([{'name': 'certifi', 'version': 'test',
        'filename': 'sample.tar.gz', 'sha256': hashlib.sha256(b'original').hexdigest()}]), encoding='utf-8')
    monkeypatch.setattr(third_party_notices, 'ROOT', tmp_path)
    monkeypatch.setattr(third_party_notices.metadata, 'version', lambda name: 'test')
    with pytest.raises(RuntimeError, match='checksum mismatch'):
        third_party_notices.covered_sources(tmp_path)


def test_wizard_assets_match_reviewed_source_and_audited_lock():
    profile.verify_wizard_assets(Path(__file__).resolve().parents[2])


def test_modified_wizard_library_blocks_distribution(tmp_path):
    import shutil

    root = Path(__file__).resolve().parents[2]
    relative = Path('mietvertrag_wizard_fastapi_reportlab_pro/mietvertrag_wizard/static/mietvertrag_wizard/vendor')
    shutil.copytree(root / relative, tmp_path / relative)
    (tmp_path / 'frontend').mkdir()
    shutil.copyfile(root / 'frontend/package-lock.json', tmp_path / 'frontend/package-lock.json')
    (tmp_path / relative / 'pdfmake.min.js').write_bytes(b'altered browser library')
    with pytest.raises(RuntimeError, match='Wizard asset checksum mismatch'):
        profile.verify_wizard_assets(tmp_path)


def test_hosting_notices_skip_removed_packages_and_require_installed_ones(tmp_path, monkeypatch):
    import subprocess

    from tools import hosting_notices

    docs = tmp_path / 'doc'
    (docs / 'curl').mkdir(parents=True)
    (docs / 'curl' / 'copyright').write_text('curl licence', encoding='utf-8')
    listing = ('curl\t7.88\tcurl\t7.88\tinstalled\n'
               'dirmngr\t2.2.40\tgnupg2\t2.2.40\tconfig-files\n')  # left behind by purging gnupg in the image
    monkeypatch.setattr(hosting_notices.subprocess, 'run',
                        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=listing))
    real_path = hosting_notices.Path
    monkeypatch.setattr(hosting_notices, 'Path',
                        lambda value: docs if value == '/usr/share/doc' else real_path(value))
    rows = hosting_notices.generate(tmp_path)
    assert [row['name'] for row in rows] == ['curl']
    listing = 'curl\t7.88\tcurl\t7.88\tinstalled\nlibfoo\t1\tfoo\t1\tinstalled\n'
    with pytest.raises(RuntimeError, match='Missing Debian copyright notice: libfoo'):
        hosting_notices.generate(tmp_path)
