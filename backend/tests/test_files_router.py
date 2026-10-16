from backend.routers.files import (
    _file_url_to_key,
    _normalize_storage_key,
    _ocr_key_from_file_key,
    _safe_extension,
)


def test_file_url_to_key_variants(monkeypatch):
    from backend.services.file_storage import S3Storage

    # No network client is constructed: the storage bucket identity is the
    # source of truth for a private S3 object URL, not the bucket supplied by
    # an untrusted URL.
    owned = S3Storage(bucket="synthetic-owned", endpoint_url="http://127.0.0.1:1",
                      client=object())
    monkeypatch.setattr("backend.routers.files.get_file_storage", lambda: owned)
    assert _file_url_to_key('/uploads/documents/x.pdf') == 'documents/x.pdf'
    assert _file_url_to_key('https://example.com/uploads/documents/x.pdf') == 'documents/x.pdf'
    assert _file_url_to_key('https://example.com/uploads/documents/x.pdf?token=abc') == 'documents/x.pdf'
    assert _file_url_to_key('s3://synthetic-owned/documents/x.pdf') == 'documents/x.pdf'
    assert _file_url_to_key('s3://other-bucket/documents/x.pdf') == ''


def test_ocr_key_from_file_key():
    assert _ocr_key_from_file_key('documents/x.pdf') == 'documents/x_ocr.txt'
    assert _ocr_key_from_file_key('/documents/y.image.png') == 'documents/y.image_ocr.txt'


def test_normalize_storage_key_blocks_traversal():
    assert _normalize_storage_key('../etc/passwd') == ''
    assert _normalize_storage_key('documents/../x.pdf') == 'x.pdf'
    assert _normalize_storage_key('') == ''


def test_safe_extension_defaults_for_invalid_names():
    assert _safe_extension('scan.PDF') == 'pdf'
    assert _safe_extension('noext') == 'bin'
    assert _safe_extension('image.') == 'bin'
    assert _safe_extension('evil.$$$') == 'bin'


def test_file_url_to_key_rejects_non_upload_http_or_unknown_schemes():
    assert _file_url_to_key('https://example.com/documents/x.pdf') == ''
    assert _file_url_to_key('ftp://example.com/uploads/documents/x.pdf') == ''


def test_ocr_key_empty_for_invalid_input():
    assert _ocr_key_from_file_key('../etc/passwd') == ''
