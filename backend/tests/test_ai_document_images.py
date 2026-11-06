"""Synthetic scan fixtures prove the protected image-worker contract."""
import base64
import importlib.util
import json
import sys
import time
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image

from backend.services import ai_document_images as images
from backend.services import document_text_process, document_text_worker
from backend.services.e_invoice import validator


def photo(kind="PNG"):
    output = BytesIO()
    Image.new("RGB", (20, 20), "teal").save(output, format=kind)
    return output.getvalue()


def pdf(pages=3, *, width=100, height=100):
    fitz = pytest.importorskip("fitz")
    with fitz.open() as document:
        for index in range(pages):
            document.new_page(width=width, height=height).insert_text((15, 25), f"Testseite {index + 1}")
        return document.tobytes()


def standard_pdf(pages=1, *, width=144, height=72):
    from reportlab.pdfgen.canvas import Canvas
    output = BytesIO()
    canvas = Canvas(output, pagesize=(width, height), invariant=1)
    for number in range(pages):
        canvas.drawString(8, 36, "LOCAL PAGE " + str(number + 1))
        canvas.showPage()
    canvas.save()
    return output.getvalue()


def qt_worker(monkeypatch):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("Qt PDF belongs to the desktop runtime; real smoke is mandatory there")
    # Require this engine even when a development environment also has fitz.
    # The real worker main and the same owned process limits remain in use.
    def command(folder):
        script = ("import sys;sys.modules['fitz']=None;"
                  "from backend.services.document_text_worker import main;main(sys.argv[1])")
        return [sys.executable, "-c", script, str(folder)]
    monkeypatch.setattr(document_text_process, "worker_command", command)


def test_qt_fallback_renders_real_pages_only_in_child_and_keeps_limits(monkeypatch):
    qt_worker(monkeypatch)
    content = standard_pdf(3)
    before = set(sys.modules)
    monkeypatch.setenv("QT_QPA_PLATFORM", "invalid-operator-platform")
    monkeypatch.setenv("QT_PLUGIN_PATH", "untrusted-operator-plugins")
    owned = []
    factory = validator.CliProcess

    def capture(*args, **kwargs):
        assert kwargs["env"]["PATH"] == ""
        assert "QT_QPA_PLATFORM" not in kwargs["env"] and "QT_PLUGIN_PATH" not in kwargs["env"]
        assert kwargs["memory_limit_bytes"] == 768 * 1024 * 1024
        process = factory(*args, **kwargs)
        owned.append(process)
        return process
    monkeypatch.setattr(validator, "CliProcess", capture)
    result = images.render_page_images(content, "application/pdf", "qt.pdf", max_pages=1)
    assert content == standard_pdf(3)
    assert result["pages_total"] == 3 and result["pages_sent"] == 1 and result["omissions"]
    assert owned and all(child.process.poll() is not None for child in owned)
    assert not any(key.startswith("PySide6.Qt") for key in set(sys.modules) - before)
    with Image.open(BytesIO(base64.b64decode(result["images"][0]["data_base64"]))) as page:
        assert page.size == (300, 150) and page.convert("RGB").getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("kind", ["malformed", "encrypted", "extreme"])
def test_qt_pdf_errors_and_geometry_limits_are_controlled(monkeypatch, kind):
    qt_worker(monkeypatch)
    if kind == "malformed":
        content = b"%PDF-1.7\ntruncated"
    elif kind == "extreme":
        content = standard_pdf(width=10000, height=10000)
    else:
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()
        writer.add_page(PdfReader(BytesIO(standard_pdf())).pages[0])
        writer.encrypt("SYNTHETIC-UNKNOWN-PASSWORD")
        output = BytesIO()
        writer.write(output)
        content = output.getvalue()
    with pytest.raises(HTTPException) as rejected:
        images.render_page_images(content, "application/pdf", "qt-invalid.pdf", 1)
    assert rejected.value.status_code == 422
    assert not isinstance(rejected.value, images.ImageRendererUnavailable)


def test_qt_application_cannot_be_started_outside_the_owned_document_worker(monkeypatch):
    monkeypatch.delenv("DOCUMENT_TEXT_READ_DIR", raising=False)
    with pytest.raises(images.ImageRenderError) as rejected:
        images._qt_pdf(b"pdf", "not-a-worker.pdf", 1, lambda *args: True)
    assert rejected.value.code == "renderer_unavailable"


def test_desktop_smoke_requires_real_pdf_and_png_worker_replies(tmp_path, monkeypatch):
    qt_worker(monkeypatch)
    from scripts.check_desktop_runtime import verify_ai_image_worker
    result = verify_ai_image_worker(tmp_path)
    assert result["action"] == "render_images"
    assert set(result["cases"]) == {"image/png", "application/pdf"}
    assert all(item["status"] == "rendered" and item["pages_total"] == item["pages_sent"] == 1
               for item in result["cases"].values())
    assert (tmp_path / "ai-image-worker-smoke.json").is_file()


@pytest.mark.parametrize("error", [images.ImageRendererUnavailable(), HTTPException(503, "owned worker failed")])
def test_desktop_smoke_never_accepts_missing_pdf_renderer_or_worker_failure(tmp_path, monkeypatch, error):
    from scripts.check_desktop_runtime import verify_ai_image_worker
    render = images.render_page_images

    def fake(content, mime, *args):
        if mime == "application/pdf":
            raise error
        return render(content, mime, *args)
    monkeypatch.setattr(images, "render_page_images", fake)
    with pytest.raises(HTTPException):
        verify_ai_image_worker(tmp_path)
    assert not (tmp_path / "ai-image-worker-smoke.json").exists()


def test_real_pdf_is_rendered_only_in_owned_child_with_private_environment(monkeypatch):
    content = pdf()
    before = bytes(content)
    fitz = sys.modules["fitz"]
    monkeypatch.setattr(fitz, "open", lambda *args, **kwargs: pytest.fail("Native PDF parse in API process"))
    monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC-DO-NOT-INHERIT")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "SYNTHETIC-DO-NOT-INHERIT")
    owned = []
    factory = validator.CliProcess

    def capture(*args, **kwargs):
        assert "OPENAI_API_KEY" not in kwargs["env"] and "ANTHROPIC_API_KEY" not in kwargs["env"]
        assert kwargs["memory_limit_bytes"] == 768 * 1024 * 1024
        process = factory(*args, **kwargs)
        owned.append(process)
        return process

    monkeypatch.setattr(validator, "CliProcess", capture)
    result = images.render_page_images(content, "application/pdf", "Abrechnung.pdf", max_pages=2)
    assert content == before and owned and all(process.process.poll() is not None for process in owned)
    assert result["pages_total"] == 3 and result["pages_sent"] == 2
    assert len(result["images"]) == 2 and "2 der 3" in result["omissions"][0]
    assert [item["name"] for item in result["images"]] == ["Abrechnung.pdf Seite 1.png", "Abrechnung.pdf Seite 2.png"]
    assert all(base64.b64decode(item["data_base64"]).startswith(b"\x89PNG\r\n\x1a\n") for item in result["images"])


@pytest.mark.parametrize("kind,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")])
def test_real_photos_keep_exact_original_bytes_and_format(kind, mime):
    content = photo(kind)
    result = images.render_page_images(content, mime, "Foto", max_pages=1)
    assert result["pages_total"] == result["pages_sent"] == 1 and result["omissions"] == []
    assert result["images"][0]["mime"] == mime
    assert base64.b64decode(result["images"][0]["data_base64"]) == content


@pytest.mark.parametrize("content", [b"not a PDF", b"%PDF-1.7\ntruncated"])
def test_malformed_pdf_is_controlled_and_original_is_preserved(content):
    pytest.importorskip("fitz")
    with pytest.raises(HTTPException) as rejected:
        images.render_page_images(content, "application/pdf", "broken.pdf")
    assert rejected.value.status_code == 422 and "Original" in rejected.value.detail


def test_real_extreme_pdf_geometry_is_rejected_before_large_raster_allocation():
    with pytest.raises(HTTPException) as rejected:
        images.render_page_images(pdf(1, width=10000, height=10000), "application/pdf", "large.pdf")
    assert rejected.value.status_code == 422


def test_pixel_limit_is_checked_before_get_pixmap(monkeypatch):
    called = []
    page = SimpleNamespace(rect=SimpleNamespace(width=10000, height=10000),
        get_pixmap=lambda **kwargs: called.append(kwargs))

    class Document:
        page_count, is_encrypted = 1, False
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def load_page(self, index): return page

    monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(open=lambda **kwargs: Document(), csRGB="RGB"))
    with pytest.raises(images.ImageRenderError) as rejected:
        images.render_in_worker(b"synthetic", "application/pdf", "document.pdf", 1)
    assert rejected.value.code == "image_limit" and called == []


def test_missing_optional_renderer_is_a_known_worker_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "fitz", None)
    with pytest.raises(images.ImageRenderError) as rejected:
        images.render_in_worker(b"synthetic", "application/pdf", "document.pdf", 1)
    assert rejected.value.code == "renderer_unavailable"


def test_total_budget_is_checked_before_allocating_additional_base64(monkeypatch):
    content = b"\x89PNG\r\n\x1a\n" + b"fixture"
    encoded = 4 * ((len(content) + 2) // 3)
    monkeypatch.setattr(images, "MAX_ENCODED_BYTES", encoded)
    calls = []
    encode = base64.b64encode
    def record_encode(data):
        calls.append(len(data))
        return encode(data)
    monkeypatch.setattr(images.base64, "b64encode", record_encode)
    page = SimpleNamespace(rect=SimpleNamespace(width=100, height=100), get_pixmap=lambda **kwargs:
        SimpleNamespace(width=210, height=210, tobytes=lambda kind: content))

    class Document:
        page_count, is_encrypted = 3, False
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def load_page(self, index): return page

    monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(open=lambda **kwargs: Document(), csRGB="RGB"))
    result = images.render_in_worker(b"synthetic", "application/pdf", "document.pdf", 3)
    assert result["pages_total"] == 3 and result["pages_sent"] == 1
    assert len(calls) == 1 and "1 der 3" in result["omissions"][0]


@pytest.mark.parametrize("max_pages", [0, 21, True, "4", None])
def test_invalid_page_budget_never_starts_worker(monkeypatch, max_pages):
    monkeypatch.setattr(validator, "_run", lambda *args, **kwargs: pytest.fail("Invalid request submitted"))
    with pytest.raises(HTTPException) as rejected:
        images.render_page_images(b"synthetic", "application/pdf", "document.pdf", max_pages)
    assert rejected.value.status_code == 422


def test_oversized_source_is_rejected_before_worker_or_temp_copy(monkeypatch):
    monkeypatch.setattr(images, "MAX_SOURCE_BYTES", 10)
    monkeypatch.setattr(validator, "_run", lambda *args, **kwargs: pytest.fail("Oversized request submitted"))
    with pytest.raises(HTTPException) as rejected:
        images.render_page_images(b"x" * 11, "application/pdf", "document.pdf")
    assert rejected.value.status_code == 422


@pytest.mark.parametrize("value", [{"pages_sent": 1}, {"error": "unexpected-and-private"},
    {"images": [], "pages_total": 2, "pages_sent": True, "omissions": []}])
def test_malformed_worker_result_is_never_accepted(monkeypatch, value):
    def run(argv, folder, **kwargs):
        (folder / "result.json").write_text(json.dumps(value), encoding="utf-8")
        return 0, "private diagnostics", "private diagnostics"
    monkeypatch.setattr(validator, "_run", run)
    with pytest.raises(HTTPException) as rejected:
        images.render_page_images(b"synthetic", "application/pdf", "document.pdf")
    assert rejected.value.status_code == 503 and "private diagnostics" not in rejected.value.detail


def test_known_missing_renderer_returns_service_unavailable(monkeypatch):
    def run(argv, folder, **kwargs):
        (folder / "result.json").write_text('{"error":"renderer_unavailable"}', encoding="utf-8")
        return 0, "", ""
    monkeypatch.setattr(validator, "_run", run)
    with pytest.raises(images.ImageRendererUnavailable) as rejected:
        images.render_page_images(b"synthetic", "application/pdf", "document.pdf")
    assert rejected.value.status_code == 503 and rejected.value.code == "renderer_unavailable"
    assert "Dokumentwerkzeuge" in rejected.value.detail


@pytest.mark.parametrize("failure", ["invalid_document", "image_limit", "crash"])
def test_document_and_resource_failures_never_allow_missing_renderer_fallback(monkeypatch, failure):
    def run(argv, folder, **kwargs):
        if failure == "crash":
            raise RuntimeError("synthetic resource failure")
        (folder / "result.json").write_text(json.dumps({"error": failure}), encoding="utf-8")
        return 0, "", ""
    monkeypatch.setattr(validator, "_run", run)
    with pytest.raises(HTTPException) as rejected:
        images.render_page_images(b"synthetic", "application/pdf", "document.pdf")
    assert not isinstance(rejected.value, images.ImageRendererUnavailable)
    assert rejected.value.status_code == (503 if failure == "crash" else 422)


@pytest.mark.parametrize("failure", ["timeout", "memory", "output"])
def test_real_worker_failures_are_bounded_and_owned_processes_are_reaped(monkeypatch, failure):
    owned = []
    factory = validator.CliProcess
    def capture(*args, **kwargs):
        process = factory(*args, **kwargs)
        owned.append(process)
        return process
    code = {"timeout": "import time;time.sleep(60)", "memory": "x=bytearray(2*1024**3)",
            "output": "import sys;sys.stdout.write('x'*2000002);sys.stdout.flush()"}[failure]
    monkeypatch.setattr(validator, "CliProcess", capture)
    monkeypatch.setattr(images, "TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(document_text_process, "worker_command", lambda folder: [sys.executable, "-c", code])
    started = time.monotonic()
    with pytest.raises(HTTPException) as rejected:
        images.render_page_images(photo(), "image/png", "owned.png")
    assert rejected.value.status_code == 503 and time.monotonic() - started < 12
    assert owned and all(process.process.poll() is not None for process in owned)


@pytest.mark.parametrize("payload", [{"action": "unexpected"}, {"action": "render_images", "command": "unapproved"}])
def test_worker_only_accepts_known_strict_actions(tmp_path, monkeypatch, payload):
    folder = tmp_path / "immo-e-invoice-text-test"
    folder.mkdir()
    (folder / "input.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("DOCUMENT_TEXT_READ_DIR", str(folder))
    with pytest.raises(RuntimeError):
        document_text_worker.main(str(folder))
