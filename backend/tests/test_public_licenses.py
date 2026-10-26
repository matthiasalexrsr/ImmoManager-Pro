"""Hosted notices are public; the catalog cannot become a customer file route."""
import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import third_party_licenses as legal


@pytest.fixture
def notices(tmp_path, monkeypatch):
    root = tmp_path / 'published'
    root.mkdir()
    raw = b'Unchanged vendor copyright and license text.\n'
    (root / 'vendor.txt').write_bytes(raw)
    identifier = hashlib.sha256(b'vendor.txt').hexdigest()
    value = {'format': 'immomanager-public-notices/1',
             'components': [{'name': '<script>alert(1)</script>', 'version': '1', 'license': 'MIT'}],
             'files': [{'id': identifier, 'path': 'vendor.txt', 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}]}
    def save():
        (root / 'catalog.json').write_text(json.dumps(value), encoding='utf-8')
    save()
    monkeypatch.setattr(legal, 'notice_root', lambda: root)
    app = FastAPI()
    app.include_router(legal.router, prefix='/api/v1')
    with TestClient(app) as client:
        yield root, value, save, client


def test_public_notices_and_original_source_download_without_login(notices):
    root, value, _, client = notices
    page = client.get('/api/v1/legal')
    assert page.status_code == 200
    assert '<script>' not in page.text and '&lt;script&gt;' in page.text
    assert "default-src 'none'" in page.headers['content-security-policy']
    response = client.get('/api/v1/legal/files/' + value['files'][0]['id'])
    assert response.status_code == 200 and response.content == (root / 'vendor.txt').read_bytes()
    assert response.headers['content-disposition'].startswith('attachment;')


def test_changed_package_file_fails_closed(notices):
    root, value, _, client = notices
    (root / 'vendor.txt').write_bytes(b'changed after inventory')
    assert client.get('/api/v1/legal/files/' + value['files'][0]['id']).status_code == 503


@pytest.mark.parametrize('name', ['../customer.txt', '/customer.txt', 'C:/customer.txt', 'sub\\customer.txt'])
def test_unsafe_catalog_does_not_expose_other_files(notices, name):
    root, value, save, client = notices
    (root.parent / 'customer.txt').write_text('private customer contents', encoding='utf-8')
    entry = value['files'][0]
    entry.update(path=name, id=hashlib.sha256(name.encode()).hexdigest())
    save()
    response = client.get('/api/v1/legal/files/' + entry['id'])
    assert response.status_code == 503 and 'private customer contents' not in response.text


def test_unknown_id_duplicate_entry_and_invalid_metadata_fail_closed(notices):
    _, value, save, client = notices
    assert client.get('/api/v1/legal/files/' + '0' * 64).status_code == 404
    value['files'].append(dict(value['files'][0]))
    save()
    assert client.get('/api/v1/legal/files/' + value['files'][0]['id']).status_code == 404
    value['files'][0]['bytes'] = '<script>alert(1)</script>'
    save()
    assert client.get('/api/v1/legal').status_code == 503


def test_file_and_directory_symlinks_are_not_publishable(notices):
    root, value, save, client = notices
    target = root.parent / 'outside'
    target.mkdir()
    (target / 'vendor.txt').write_bytes((root / 'vendor.txt').read_bytes())
    try:
        (root / 'linked').symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip('This Windows account cannot create symlinks')
    entry = value['files'][0]
    entry.update(path='linked/vendor.txt', id=hashlib.sha256(b'linked/vendor.txt').hexdigest())
    save()
    assert client.get('/api/v1/legal/files/' + entry['id']).status_code == 503
