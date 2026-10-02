import pytest
from fastapi import HTTPException

from backend.routers import files as files_router
from backend.routers.files import (
    _file_url_to_key,
    _normalize_storage_key,
    _ocr_key_from_file_key,
    _safe_extension,
)


def test_file_url_to_key_variants():
    assert _file_url_to_key('/uploads/documents/x.pdf') == 'documents/x.pdf'
    assert _file_url_to_key('https://example.com/uploads/documents/x.pdf') == 'documents/x.pdf'
    assert _file_url_to_key('https://example.com/uploads/documents/x.pdf?token=abc') == 'documents/x.pdf'
    assert _file_url_to_key('s3://bucket/documents/x.pdf') == 'documents/x.pdf'


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


def test_process_ocr_exposes_correctable_local_tool_error(monkeypatch):
    class Storage:
        def get(self, key):
            return b"%PDF-1.7\nscan"

    monkeypatch.setattr(files_router, "require_file_access", lambda _value: None)
    monkeypatch.setattr(files_router, "get_file_storage", lambda: Storage())

    def fail(_storage, _key, _ext):
        from backend.services.ocr_service import OCRProcessingError
        raise OCRProcessingError(
            "ocr_tool_missing",
            "Tesseract ist lokal nicht installiert oder nicht im PATH verfügbar.",
            503,
        )

    monkeypatch.setattr(files_router, "_perform_ocr", fail)
    with pytest.raises(HTTPException) as exc:
        files_router.process_ocr("/uploads/documents/scan.pdf")
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "ocr_tool_missing"
    assert "Tesseract" in exc.value.detail["message"]
