# ruff: noqa: F811 -- imported pytest fixture
import os

import pytest
from test_operations_backup import installation  # noqa: F401

from backend.services import full_backup


@pytest.mark.skipif(os.name != "nt", reason="Windows path regression")
def test_full_backup_handles_long_windows_archive_name(installation, tmp_path):
    installation.sources.passphrase = "Synthetic-audit-passphrase-2026!"
    short = full_backup.create_full_backup(sources=installation.sources)
    assert short["ok"], short
    root = tmp_path / "long"
    while len(str(root)) < 220:
        gap = 220 - len(str(root)) - 1
        root = root / ("a" * min(gap, 40))
    assert len(str(root)) == 220
    installation.sources.root = root
    long = full_backup.create_full_backup(sources=installation.sources)
    assert long["ok"], long


@pytest.mark.skipif(os.name != "nt", reason="Windows path regression")
def test_long_upload_paths_support_streaming_checksums(tmp_path, monkeypatch):
    import hashlib
    from io import BytesIO

    from backend.services import business_documents, file_storage
    from backend.services.filesystem_paths import filesystem_path

    root = tmp_path
    while len(str(root)) < 260:
        root /= "nested-data-folder"
    filesystem_path(root).mkdir(parents=True, exist_ok=True)
    storage = file_storage.LocalStorage(root)
    monkeypatch.setattr(file_storage, "_storage", storage)
    content = b"%PDF-1.4\nLong path checksum fixture\n%%EOF"
    key = "documents/receipt.pdf"
    storage.save(key, BytesIO(content), content_type="application/pdf")
    assert business_documents.file_hash("/uploads/" + key) == hashlib.sha256(content).hexdigest()


@pytest.mark.skipif(os.name != "nt", reason="Windows path regression")
def test_pdf_worker_uses_long_owned_directory(tmp_path, monkeypatch):
    from io import BytesIO

    from reportlab.pdfgen.canvas import Canvas

    from backend import paths
    from backend.services import document_pdf

    if not document_pdf.available():
        pytest.skip("Optional native PDF engine not installed")
    root = tmp_path
    while len(str(root)) < 260:
        root /= "nested-data-folder"
    monkeypatch.setattr(paths, "get_data_dir", lambda: root)
    buffer = BytesIO()
    pdf = Canvas(buffer, invariant=1)
    pdf.drawString(20, 20, "Long path PDF worker")
    pdf.save()
    result = document_pdf.isolated(buffer.getvalue(), "inspect")
    assert result["total_pages"] == 1


@pytest.mark.skipif(os.name != 'nt', reason='Windows path regression')
def test_secret_keyring_can_be_reopened_and_rotated_in_long_path(tmp_path):
    from backend.services.secret_box import SecretBox
    root = tmp_path
    while len(str(root)) < 260:
        root /= 'nested-keyring-folder'
    path = root / 'keyring.json'
    first = SecretBox(path)
    sealed = first.seal('Synthetic secret', 'audit-context')
    reopened = SecretBox(path)
    assert reopened.open(sealed, 'audit-context') == 'Synthetic secret'
    reopened.rotate()
    assert SecretBox(path).open(sealed, 'audit-context') == 'Synthetic secret'
    assert SecretBox(path).keyring_file_bytes() is not None


@pytest.mark.skipif(os.name != 'nt', reason='Windows path regression')
def test_encrypted_assistant_vault_is_readable_in_long_upload_path(tmp_path, monkeypatch):
    import base64
    import json

    from backend.services import assistant_provider_vault as vault
    from backend.services.secret_box import SecretBox, write_private_file
    root = tmp_path
    while len(str(root)) < 260:
        root /= 'nested-uploads-folder'
    monkeypatch.setattr(vault, 'get_uploads_dir', lambda: root)
    box = SecretBox(tmp_path / 'short-keyring.json')
    monkeypatch.setattr(vault, 'default_secret_box', lambda: box)
    content = {'version': 1, 'files': {'auth.json': base64.b64encode(b'Synthetic token').decode()},
               'public': {'connected': True}}
    sealed = box.seal(json.dumps(content), vault._context('audit-actor', 'codex'))
    write_private_file(vault._vault_path('audit-actor', 'codex'), json.dumps({'sealed': sealed}).encode())
    loaded = vault.load('audit-actor', 'codex')
    assert loaded['files']['auth.json'] == b'Synthetic token'
    assert loaded['public']['connected'] is True


@pytest.mark.skipif(os.name != 'nt', reason='Windows path regression')
def test_contract_wizard_serves_templates_and_assets_from_long_bundle_path(tmp_path, monkeypatch):
    import importlib

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.services.filesystem_paths import filesystem_path

    application = importlib.import_module('backend.app')
    root = tmp_path
    while len(str(root)) < 260:
        root /= 'nested-bundle-folder'
    template = filesystem_path(root / 'templates/mietvertrag_wizard/index.html')
    template.parent.mkdir(parents=True)
    template.write_text('<h1>Long path contract wizard</h1>', encoding='utf-8')
    asset = filesystem_path(root / 'static/style.css')
    asset.parent.mkdir(parents=True)
    asset.write_text('h1 { color: blue; }', encoding='utf-8')
    assert application._wizard_assets_ready(root)
    monkeypatch.setattr(application, '_load_contract_wizard_mount', lambda: (lambda payload: b'%PDF-', root))
    local = FastAPI()
    assert application._mount_contract_wizard_if_available(local)
    with TestClient(local) as client:
        page = client.get('/mietvertrag/')
        assert page.status_code == 200 and 'Long path contract wizard' in page.text
        style = client.get('/mietvertrag/static/style.css')
        assert style.status_code == 200 and 'color: blue' in style.text


def test_native_template_loader_rejects_parent_traversal(tmp_path):
    from jinja2 import Environment, TemplateNotFound

    from backend.services.template_loader import NativeTemplateLoader
    (tmp_path / 'outside.html').write_text('private content', encoding='utf-8')
    inside = tmp_path / 'templates'
    inside.mkdir()
    environment = Environment(loader=NativeTemplateLoader(inside))
    with pytest.raises(TemplateNotFound):
        environment.get_template('../outside.html')


@pytest.mark.skipif(os.name != 'nt', reason='Windows path regression')
def test_datev_stream_and_owned_spool_support_long_data_paths(tmp_path):
    import hashlib

    from test_datev_streaming import batch, entry, profile

    from backend.services.datev_streaming import prepare_download
    from backend.services.filesystem_paths import filesystem_path
    from backend.services.tax_temp import tax_workspace

    root = tmp_path
    while len(str(root)) < 260:
        root /= 'nested-tax-data-folder'
    with tax_workspace(root) as workspace:
        with prepare_download([entry()], profile(), batch(), spool_dir=workspace) as prepared:
            content = prepared.path.read_bytes()
            assert b'EXTF' in content[:30]
            assert prepared.rows == 1
            assert hashlib.sha256(content).hexdigest() == prepared.sha256
        assert not prepared.path.exists()
    assert not list(filesystem_path(root).iterdir())
