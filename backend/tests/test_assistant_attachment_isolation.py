"""Public chat attachment parsing stays in an owned worker, including core PDFs."""
import hashlib
import json
import sys
import zipfile
from io import BytesIO

import pytest
from fastapi import HTTPException
from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from backend.config import settings
from backend.services import assistant, document_text_process, document_text_worker, safe_xml
from backend.services.e_invoice import validator
from backend.tests.test_assistant_workspace import docx_bytes


def pdf(pages=1, text="CORE ATTACHMENT"):
    output = BytesIO()
    canvas = Canvas(output, pagesize=(144, 72), invariant=1)
    for number in range(pages):
        canvas.drawString(8, 36, text + " " + str(number))
        canvas.showPage()
    canvas.save()
    return output.getvalue()


def picture(kind="PNG"):
    output = BytesIO()
    Image.new("RGB", (8, 4), "teal").save(output, kind)
    return output.getvalue()


def test_core_pdf_attachments_do_not_require_optional_fitz(monkeypatch):
    content = pdf()
    monkeypatch.setitem(sys.modules, "fitz", None)
    script = "import sys;sys.modules['fitz']=None;from backend.services.document_text_worker import main;main(sys.argv[1])"
    monkeypatch.setattr(document_text_process, "worker_command",
        lambda folder: [sys.executable, "-c", script, str(folder)])
    result = assistant.inspect_attachment(content, "Kern.pdf")
    assert "CORE ATTACHMENT" in result["text"]
    assert result["status"] == "ready" and not result["text_truncated"] and result["omissions"] == []
    assert result["byte_length"] == len(content) and result["sha256"] == hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize("extension", ["pdf", "png", "docx"])
def test_binary_parsers_are_never_called_in_api_process(monkeypatch, extension):
    content = {"pdf": pdf(), "png": picture(), "docx": docx_bytes()}[extension]

    def forbidden(*args, **kwargs):
        pytest.fail("Binary parser executed inside the API process")

    monkeypatch.setitem(sys.modules, "fitz", None)
    monkeypatch.setattr(Image, "open", forbidden)
    monkeypatch.setattr(zipfile, "ZipFile", forbidden)
    monkeypatch.setattr(PdfReader, "__init__", forbidden)
    monkeypatch.setattr(safe_xml, "fromstring", forbidden)
    result = assistant.inspect_attachment(content, "Datei." + extension)
    assert result["status"] == "ready" and result["sha256"] == hashlib.sha256(content).hexdigest()
    if extension == "pdf":
        assert "CORE ATTACHMENT" in result["text"]
    if extension == "docx":
        assert all(word in result["text"] for word in ("Haupttext", "Tabellenbeleg", "Kopfzeile", "Fußzeile"))
    if extension == "png":
        assert not result["text"] and result["omissions"]


def test_capabilities_never_offer_more_than_the_worker_source_limit(monkeypatch):
    from backend.services import assistant_providers
    monkeypatch.setattr(settings, "assistant_max_attachment_bytes", 100 * 1024 * 1024)
    monkeypatch.setattr(assistant_providers, "capabilities", lambda actor_id: {})
    assert assistant.attachment_limit() == 50 * 1024 * 1024
    assert assistant.capabilities("synthetic-owner")["attachment_max_bytes"] == 50 * 1024 * 1024


def test_docx_uses_current_upload_unpack_limits_in_private_child(monkeypatch):
    content = docx_bytes("A" * 50000)
    assert len(content) < 3000
    monkeypatch.setattr(settings, "max_upload_size_bytes", 3000)
    monkeypatch.setattr(settings, "assistant_max_attachment_bytes", 6000)
    with pytest.raises(HTTPException) as rejected:
        assistant.inspect_attachment(content, "ZuGrossEntpackt.docx")
    assert rejected.value.status_code == 422


@pytest.mark.parametrize("value", [{"text": "forged"}, {"error": "private-unapproved-message"}])
def test_unverifiable_worker_output_is_never_a_ready_attachment(monkeypatch, value):
    def run(argv, folder, **kwargs):
        (folder / "result.json").write_text(json.dumps(value), encoding="utf-8")
        return 0, "private stdout", "private stderr"

    monkeypatch.setattr(validator, "_run", run)
    with pytest.raises(HTTPException) as rejected:
        assistant.inspect_attachment(picture(), "Eigene.png")
    assert rejected.value.status_code == 503 and "private" not in str(rejected.value.detail)


@pytest.mark.parametrize("kind,extension", [("PNG", "png"), ("JPEG", "jpg"), ("WEBP", "webp")])
def test_valid_image_formats_preserve_original_metadata_and_disclose_image_only(kind, extension):
    content = picture(kind)
    result = assistant.inspect_attachment(content, "Original." + extension)
    assert result["mime"] == assistant.MIME[extension] and result["byte_length"] == len(content)
    assert result["sha256"] == hashlib.sha256(content).hexdigest() and not result["text"]
    assert not result["text_truncated"]
    assert result["omissions"] == ["Bild wird nur an bildfähige Modelle übergeben; lokal keine automatische OCR."]


@pytest.mark.parametrize("pages,limited", [(100, False), (101, True)])
def test_pdf_page_limit_keeps_first_hundred_and_discloses_omitted_pages(pages, limited):
    result = assistant.inspect_attachment(pdf(pages, "PAGE"), "Seiten.pdf")
    assert "PAGE 0" in result["text"] and "PAGE 99" in result["text"] and "PAGE 100" not in result["text"]
    assert any("100 Seiten" in note for note in result["omissions"]) is limited


def test_pdf_long_text_is_bounded_and_has_visible_omission():
    result = assistant.inspect_attachment(pdf(text="L" * 65000), "Lang.pdf")
    assert len(result["text"]) == 64000 and result["text_truncated"]
    assert any("64.000" in note for note in result["omissions"])


def test_encrypted_pdf_is_rejected_without_optional_engine():
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_page(PdfReader(BytesIO(pdf())).pages[0])
    writer.encrypt("SYNTHETIC-PASSWORD")
    output = BytesIO()
    writer.write(output)
    with pytest.raises(HTTPException) as rejected:
        assistant.inspect_attachment(output.getvalue(), "Geheim.pdf")
    assert rejected.value.status_code == 422 and "Passwort" in rejected.value.detail
    assert "SYNTHETIC" not in rejected.value.detail


@pytest.mark.parametrize("extension,content,status", [
    ("png", b"PRIVATE-BROKEN-IMAGE", 415), ("pdf", b"%PDF-PRIVATE-BROKEN", 422),
    ("docx", b"PRIVATE-BROKEN-ZIP", 422), ("jpg", b"PRIVATE-PNG-MISMATCH", 415),
])
def test_invalid_binary_errors_keep_public_status_without_source_diagnostics(extension, content, status):
    with pytest.raises(HTTPException) as rejected:
        assistant.inspect_attachment(content, "Defekt." + extension)
    assert rejected.value.status_code == status and "PRIVATE" not in rejected.value.detail


def test_mislabeled_and_over_limit_image_are_rejected_without_large_allocation():
    import zlib
    with pytest.raises(HTTPException) as mismatch:
        assistant.inspect_attachment(picture(), "FalschesFormat.jpg")
    assert mismatch.value.status_code == 415
    content = bytearray(picture())
    content[16:20] = (5001).to_bytes(4, "big")
    content[20:24] = (5000).to_bytes(4, "big")
    content[29:33] = zlib.crc32(content[12:29]).to_bytes(4, "big")
    with pytest.raises(HTTPException) as excessive:
        assistant.inspect_attachment(bytes(content), "Groesse.png")
    assert excessive.value.status_code == 415


def test_owned_process_is_bounded_private_and_reaped_before_temp_removal(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC-MUST-NOT-LEAVE-PARENT")
    monkeypatch.setenv("QT_PLUGIN_PATH", "SYNTHETIC-UNTRUSTED-PLUGIN")
    owned, folders = [], []
    factory = validator.CliProcess

    def capture(argv, folder, **kwargs):
        assert kwargs["env"]["PATH"] == ""
        assert "OPENAI_API_KEY" not in kwargs["env"] and "QT_PLUGIN_PATH" not in kwargs["env"]
        assert kwargs["memory_limit_bytes"] == 768 * 1024 * 1024
        instance = factory(argv, folder, **kwargs)
        owned.append(instance)
        folders.append(folder)
        return instance

    monkeypatch.setattr(validator, "CliProcess", capture)
    assert "CORE ATTACHMENT" in assistant.inspect_attachment(pdf(), "Privat.pdf")["text"]
    assert owned and all(item.process.poll() is not None for item in owned)
    assert all(not folder.exists() for folder in folders)


@pytest.mark.parametrize("failure", ["process", "exception", "wrong-hash", "wrong-bytes", "invalid-flags", "invalid-truncation"])
def test_worker_failures_or_inconsistent_proofs_never_become_ready(monkeypatch, failure):
    content = picture()
    value = {"text": "", "text_truncated": False, "flags": ["image_only"],
             "source_sha256": hashlib.sha256(content).hexdigest(), "source_bytes": len(content)}
    if failure == "wrong-hash":
        value["source_sha256"] = "0" * 64
    elif failure == "wrong-bytes":
        value["source_bytes"] = True
    elif failure == "invalid-flags":
        value["flags"] = ["PRIVATE-INJECTED-HINT"]
    elif failure == "invalid-truncation":
        value["text_truncated"] = "false"

    def run(argv, folder, **kwargs):
        assert kwargs["resource_mode"] == "image" and kwargs["max_processes"] == 2
        assert kwargs["timeout_seconds"] == 30 and kwargs["file_limit_bytes"] == 128 * 1024 * 1024
        if failure == "exception":
            raise RuntimeError("PRIVATE-TRANSPORT-ERROR")
        (folder / "result.json").write_text(json.dumps(value), encoding="utf-8")
        return (1 if failure == "process" else 0), "PRIVATE-STDOUT", "PRIVATE-STDERR"

    monkeypatch.setattr(validator, "_run", run)
    with pytest.raises(HTTPException) as rejected:
        assistant.inspect_attachment(content, "Begrenzt.png")
    assert rejected.value.status_code == 503 and "PRIVATE" not in rejected.value.detail


def test_source_limit_applies_before_temporary_copy_or_worker(monkeypatch):
    from backend.services import assistant_attachment_inspection as inspection
    monkeypatch.setattr(inspection, "MAX_SOURCE_BYTES", 10)
    monkeypatch.setattr(inspection.tempfile, "TemporaryDirectory", lambda *args, **kwargs: pytest.fail("Oversized copy"))
    with pytest.raises(HTTPException) as rejected:
        assistant.inspect_attachment(b"01234567890", "ZuGross.pdf")
    assert rejected.value.status_code == 413 and assistant.attachment_limit() == 10


@pytest.mark.parametrize("payload", [
    {"action": "inspect_attachment", "extension": "pdf", "source_limit": 10, "upload_limit": 10, "command": "untrusted"},
    {"action": "inspect_attachment", "extension": "pdf", "source_limit": True, "upload_limit": 1},
    {"action": "inspect_attachment", "extension": "pdf", "source_limit": 10, "upload_limit": 11},
])
def test_worker_rejects_extra_actions_and_untrusted_budget_values(tmp_path, monkeypatch, payload):
    from backend.services.assistant_attachment_inspection import InspectionError
    folder = tmp_path / "immo-e-invoice-text-contract"
    folder.mkdir()
    (folder / "input.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("DOCUMENT_TEXT_READ_DIR", str(folder))
    with pytest.raises((RuntimeError, InspectionError)):
        document_text_worker.main(str(folder))
