from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from backend.services.ocr_service import (
    OCRLimits,
    OCRProcessingError,
    extract_image_text_local,
    extract_text_with_details,
)


def image_bytes(format="PNG", *, size=(40, 30), frames=1):
    output = io.BytesIO()
    with Image.new("RGB", size, "white") as image:
        image.save(output, format, **({"save_all": True, "append_images": [image.copy() for _ in range(frames - 1)]} if frames > 1 else {}))
    return output.getvalue()


class ImageRunner:
    def __init__(self, tools_path, *, sizes=None, text="Synthetic invoice", timeout=False):
        self.tool = tools_path
        self.sizes = sizes or [[40, 30]]
        self.text = text
        self.timeout = timeout
        self.calls = []
        self.source = None
        self.directory = None

    def __call__(self, args, timeout):
        self.calls.append(list(args))
        assert timeout > 0
        if self.timeout:
            raise subprocess.TimeoutExpired(args, timeout)
        if "--input" in args:
            source = Path(args[args.index("--input") + 1])
            self.source = source.read_bytes()
            self.directory = source.parent
            if "--frame" in args:
                index = int(args[args.index("--frame") + 1])
                Path(args[args.index("--output") + 1]).write_bytes(image_bytes(size=tuple(self.sizes[index])))
                return subprocess.CompletedProcess(args, 0, b'{"normalized":true}', b"")
            return subprocess.CompletedProcess(args, 0, json.dumps({"sizes": self.sizes}).encode(), b"")
        assert args[0] == str(self.tool)
        assert args[args.index("--tessdata-dir") + 1] == str(self.tool.parent)
        if "--list-langs" in args:
            return subprocess.CompletedProcess(args, 0, b"eng\ndeu\n", b"")
        Path(args[2]).with_suffix(".txt").write_text(self.text, encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, b"", b"")


@pytest.fixture
def configured(tmp_path):
    tool = tmp_path / "tesseract.exe"
    tool.write_bytes(b"stub")
    limits = OCRLimits(tesseract_path=str(tool), tessdata_path=str(tmp_path), timeout_seconds=10)
    return tool, limits


def test_configured_tesseract_tessdata_and_language_override_are_used(configured):
    tool, limits = configured
    runner = ImageRunner(tool)
    original = image_bytes()
    digest = hashlib.sha256(original).hexdigest()
    result = extract_text_with_details(original, ".PNG", limits=limits, languages="eng", runner=runner)
    assert result.text == "Synthetic invoice"
    assert (result.page_count, result.ocr_pages, result.embedded_text_pages) == (1, 1, 0)
    tess_call = next(call for call in runner.calls if "--psm" in call)
    assert tess_call[tess_call.index("-l") + 1] == "eng"
    assert hashlib.sha256(runner.source).hexdigest() == digest
    assert not runner.directory.exists()


def test_multipage_tiff_keeps_all_frames_and_one_shared_deadline(configured):
    tool, limits = configured
    runner = ImageRunner(tool, sizes=[[40, 30], [40, 30]], text="Page")
    result = extract_image_text_local(image_bytes("TIFF", frames=2), limits=limits, runner=runner)
    assert result.text == "Page\n\nPage" and result.page_count == result.ocr_pages == 2
    assert len([call for call in runner.calls if "--frame" in call]) == 2
    assert not runner.directory.exists()


@pytest.mark.parametrize("changes,sizes,code", [
    ({"max_page_pixels": 100}, [[40, 30]], "ocr_pixel_budget"),
    ({"max_total_pixels": 2000}, [[40, 30], [40, 30]], "ocr_pixel_budget"),
    ({"max_pdf_pages": 1}, [[40, 30], [40, 30]], "ocr_page_budget"),
    ({"max_ram_bytes": 20000}, [[40, 30]], "ocr_ram_budget"),
])
def test_preflight_rejects_before_decode_or_tesseract(configured, changes, sizes, code):
    tool, limits = configured
    runner = ImageRunner(tool, sizes=sizes)
    with pytest.raises(OCRProcessingError) as error:
        extract_image_text_local(image_bytes(), limits=replace(limits, **changes), runner=runner)
    assert error.value.code == code
    assert all("--frame" not in call and call[0] != str(tool) for call in runner.calls)
    assert not runner.directory.exists()


@pytest.mark.parametrize("field,code", [("max_temp_bytes", "ocr_temp_budget"), ("max_ram_bytes", "ocr_ram_budget")])
def test_original_byte_budget_before_worker(configured, field, code):
    tool, limits = configured
    runner = ImageRunner(tool)
    with pytest.raises(OCRProcessingError) as error:
        extract_image_text_local(image_bytes(), limits=replace(limits, **{field: 10}), runner=runner)
    assert error.value.code == code and not runner.calls


def test_common_timeout_is_typed(configured):
    tool, limits = configured
    with pytest.raises(OCRProcessingError) as error:
        extract_image_text_local(image_bytes(), limits=limits, runner=ImageRunner(tool, timeout=True))
    assert error.value.code == "ocr_timeout" and error.value.http_status == 504


def test_native_pillow_rejects_invalid_original_before_tesseract(configured):
    _, limits = configured
    with pytest.raises(OCRProcessingError) as error:
        extract_image_text_local(b"invalid JPEG", limits=limits)
    assert error.value.code == "ocr_invalid_image"


def test_native_pillow_large_header_is_rejected_before_decode(configured):
    from backend.services import ocr_service
    _, limits = configured
    # A genuine highly compressed PNG: metadata must reject before raster decode.
    source = image_bytes(size=(1500, 1000))
    with pytest.raises(OCRProcessingError) as error:
        ocr_service.extract_image_text_local(source, limits=replace(limits, max_page_pixels=1000))
    assert error.value.code == "ocr_pixel_budget"


def test_missing_tesseract_after_real_metadata_is_correctable(configured, monkeypatch):
    _, limits = configured
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(OCRProcessingError) as error:
        extract_image_text_local(image_bytes(), limits=replace(limits, tesseract_path=""))
    assert error.value.code == "ocr_tool_missing" and error.value.http_status == 503


@pytest.mark.parametrize("format,frames", [("PNG", 1), ("JPEG", 1), ("TIFF", 2), ("BMP", 1), ("WEBP", 1)])
def test_native_image_ocr_with_real_tesseract_retains_original(format, frames):
    import os
    executable = os.environ.get("OCR_TEST_TESSERACT_PATH") or shutil.which("tesseract")
    if not executable:
        pytest.skip("Real local Tesseract not installed")
    tessdata = os.environ.get("OCR_TEST_TESSDATA_PATH", "")
    import reportlab
    font = ImageFont.truetype(str(Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"), 58)
    with Image.new("RGB", (1600, 360), "white") as image:
        draw = ImageDraw.Draw(image)
        draw.text((40, 40), "SYNTHETIC IMAGE OCR 271828", fill="black", font=font)
        draw.text((40, 150), "Gesamtbetrag: 1.234,56", fill="black", font=font)
        output = io.BytesIO()
        image.save(output, format, **({"save_all": True, "append_images": [image.copy() for _ in range(frames - 1)]} if frames > 1 else {}))
    original = output.getvalue()
    digest = hashlib.sha256(original).hexdigest()
    result = extract_image_text_local(original, limits=OCRLimits(tesseract_path=executable, tessdata_path=tessdata))
    assert "271828" in result.text and "1.234,56" in result.text
    assert result.page_count == result.ocr_pages == frames
    assert hashlib.sha256(original).hexdigest() == digest


def test_frozen_worker_command_does_not_launch_server(configured, monkeypatch):
    from backend.services import ocr_service
    monkeypatch.setattr(ocr_service.sys, "frozen", True, raising=False)
    args = ocr_service._image_worker_args(Path("input"), 80)
    assert args[1] == "--ocr-image-worker" and "-I" not in args


@pytest.mark.parametrize("code,status", [("ocr_pixel_budget", 422), ("ocr_tool_missing", 503), ("ocr_timeout", 504)])
def test_document_import_ocr_failure_retains_persisted_original(monkeypatch, tmp_path, code, status):
    from fastapi.testclient import TestClient

    from backend import auth
    from backend.app import app
    from backend.dependencies import store
    from backend.routers import documents
    from backend.services import file_storage

    store.clear_all()
    auth.clear_users()
    storage = file_storage.LocalStorage(str(tmp_path / "uploads"))
    monkeypatch.setattr(file_storage, "_storage", storage)
    user = auth.register_user("ocr-import-owner", "ocr-import@example.test", "OCR Owner", "Passphrase12!", "eigentuemer")
    headers = {"Authorization": f"Bearer {auth.create_access_token(user.id)}"}
    def failure(*args):
        raise OCRProcessingError(code, "Bild hat 1200 Pixel; Budget ist 100. Auflösung reduzieren.", status)
    monkeypatch.setattr(documents, "_perform_ocr", failure)
    from backend.routers import files
    monkeypatch.setattr(files, "_perform_ocr", failure)
    source = image_bytes()
    with TestClient(app) as client:
        response = client.post("/api/v1/documents/import", headers=headers,
                files={"file": ("scan.png", source, "image/png")}, data={"title": "Retained original"})
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["ocr_status"] == "failed" and data["ocr_error"]["code"] == code
        assert "1200" in data["ocr_error"]["message"] and data["ocr_url"] is None
        persisted = client.get("/api/v1/documents/" + data["id"], headers=headers)
        assert persisted.status_code == 200 and persisted.json()["file_url"] == data["file_url"]
        # Actual storage path and authenticated route both retain original bytes.
        from backend.routers.files import _file_url_to_key
        assert storage.get(_file_url_to_key(data["file_url"])) == source
        download = client.get("/api/v1/files/download", params={"key": _file_url_to_key(data["file_url"])}, headers=headers)
        assert download.status_code == 200 and download.content == source
        analysis = client.post("/api/v1/documents/ocr-analyze", json={"file_url": data["file_url"]}, headers=headers)
        assert analysis.status_code == status
        assert analysis.json()["error"]["code"] == code
        assert analysis.json()["error"]["message"] == data["ocr_error"]["message"]
        assert not list(storage.base_dir.rglob("*_ocr.txt"))
    store.clear_all()
    auth.clear_users()


def test_worker_dispatch_precedes_configuration_or_server_start(tmp_path):
    import os
    import sys
    root = Path(__file__).resolve().parents[2]
    source = tmp_path / "image.png"
    source.write_bytes(image_bytes())
    script = "import runpy,sys;sys.argv=['backend','--ocr-image-worker','--input',sys.argv[1],'--max-pages','80'];runpy.run_module('backend',run_name='__main__')"
    result = subprocess.run([sys.executable, "-c", script, str(source)], cwd=root,
            env={**os.environ, "PYTHONUTF8": "1", "DATABASE_URL": "invalid-must-not-be-read", "JWT_SECRET_KEY": ""},
            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"sizes": [[40, 30]]}
    assert b"Server" not in result.stdout and b"startup" not in result.stdout


def test_genuine_worker_without_site_packages_reports_missing_image_dependency(configured):
    from backend.services.ocr_service import _run_command
    _, limits = configured
    def no_site_runner(args, timeout):
        assert "--input" in args
        command = [args[0], "-S", *args[1:]]
        return _run_command(command, timeout)
    with pytest.raises(OCRProcessingError) as error:
        extract_image_text_local(image_bytes(), limits=limits, runner=no_site_runner)
    assert error.value.code == "ocr_image_dependency_missing" and error.value.http_status == 503
