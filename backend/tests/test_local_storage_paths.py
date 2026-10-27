"""Real local original round-trips beyond legacy Windows MAX_PATH."""
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services.file_storage import LocalStorage
from backend.services.upload_policy import UploadStaticFiles


def test_windows_paths_cover_drives_unc_and_already_extended_paths():
    from backend.services.filesystem_paths import windows_extended_path

    assert windows_extended_path('C:/vault/file.pdf') == '\\\\?\\C:\\vault\\file.pdf'
    assert windows_extended_path('\\\\server\\share\\vault\\file.pdf') == '\\\\?\\UNC\\server\\share\\vault\\file.pdf'
    assert windows_extended_path('\\\\?\\C:\\vault\\file.pdf') == '\\\\?\\C:\\vault\\file.pdf'
    assert windows_extended_path('\\\\?\\UNC\\server\\share\\file.pdf') == '\\\\?\\UNC\\server\\share\\file.pdf'


def long_key():
    return 'documents/' + '/'.join('nested-' + str(index) + '-' + 'x' * 52 for index in range(4)) + '/original.pdf'


def test_long_original_is_atomic_immutable_readable_and_deletable(tmp_path):
    storage = LocalStorage(tmp_path / 'vault')
    key = long_key()
    assert len(str(storage.base_dir / key)) > 260
    data = b'%PDF-1.4\x00synthetic original\xff'
    assert storage.save(key, BytesIO(data)) == str(storage._path(key))
    assert storage.exists(key) and storage.get(key) == data
    storage.save(key, BytesIO(data))
    with pytest.raises(ValueError, match='Originalbytes'):
        storage.save(key, BytesIO(b'changed'))
    assert storage.get(key) == data
    ocr = key.removesuffix('.pdf') + '_ocr.txt'
    storage.save(ocr, BytesIO(b'first'))
    storage.save(ocr, BytesIO(b'corrected'))
    assert storage.get(ocr) == b'corrected'
    assert storage.get_url(key) == '/uploads/' + key
    assert storage.delete(key) and not storage.exists(key)
    assert storage.get(key) is None and not storage.delete(key)
    for escaped in ('../outside.pdf', 'a/../outside.pdf', 'C:/outside.pdf', 'a\\outside.pdf'):
        with pytest.raises(ValueError):
            storage.get(escaped)


def test_long_private_original_supports_download_head_and_ranges(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from backend.services import document_work, file_storage, upload_policy

    storage = LocalStorage(tmp_path / 'vault')
    key, data = long_key(), b'%PDF-1.4 synthetic range original'
    storage.save(key, BytesIO(data))
    accessed = []
    # Transport fixture only; real role/scope/revocation gates have their own
    # tests. Retain the exact unprefixed key crossing the authorization check.
    monkeypatch.setattr(upload_policy, 'require_upload_access', lambda request: SimpleNamespace(id='synthetic-reader'))
    monkeypatch.setattr(upload_policy, 'require_file_access', lambda value: accessed.append(value))
    monkeypatch.setattr(document_work, 'archived_upload', lambda *args: None)
    monkeypatch.setattr(file_storage, 'get_file_storage', lambda: storage)
    app = FastAPI()
    app.mount('/uploads', UploadStaticFiles(directory=storage.base_dir))
    with TestClient(app) as client:
        response = client.get('/uploads/' + key)
        assert response.status_code == 200 and response.content == data
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['x-content-type-options'] == 'nosniff'
        head = client.head('/uploads/' + key)
        assert head.status_code == 200 and not head.content
        partial = client.get('/uploads/' + key, headers={'Range': 'bytes=3-8'})
        assert partial.status_code == 206 and partial.content == data[3:9]
        assert partial.headers['content-range'] == f'bytes 3-8/{len(data)}'
    assert accessed == [key, key, key]
