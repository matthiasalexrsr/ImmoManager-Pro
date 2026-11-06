"""Inspect chat binary attachments only in the owned document process."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException

MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_TEXT = 64000
MAX_RESPONSE_BYTES = 512 * 1024
TIMEOUT_SECONDS = 30
WORK_BYTES = 128 * 1024 * 1024
IMAGE_FORMATS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP"}
EXTENSIONS = {*IMAGE_FORMATS, "pdf", "docx"}
HINTS = {
    "pdf_limit": "PDF-Auszug auf 100 Seiten / 64.000 Zeichen begrenzt.",
    "pdf_empty": "PDF enthält keinen extrahierbaren Text; keine automatische OCR durchgeführt.",
    "docx_empty": "DOCX enthält keinen extrahierbaren Text.",
    "image_only": "Bild wird nur an bildfähige Modelle übergeben; lokal keine automatische OCR.",
    "text_limit": "Textauszug auf 64.000 Zeichen begrenzt.",
}


class InspectionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _limits(extension, source_limit, upload_limit):
    if (extension not in EXTENSIONS or type(source_limit) is not int or type(upload_limit) is not int
            or not 1 <= upload_limit <= source_limit <= MAX_SOURCE_BYTES):
        raise InspectionError("inspection_unavailable")


def inspect_in_worker(content: bytes, extension: str, source_limit: int, upload_limit: int) -> dict:
    """Worker action only: native parsers never run in the API caller."""
    _limits(extension, source_limit, upload_limit)
    if not content or len(content) > source_limit:
        raise InspectionError("inspection_unavailable")
    from io import BytesIO

    text, pdf_limit = "", False
    try:
        if extension == "pdf":
            from pypdf import PdfReader

            if not content.startswith(b"%PDF-"):
                raise InspectionError("invalid_pdf")
            reader = PdfReader(BytesIO(content))
            if reader.is_encrypted:
                raise InspectionError("encrypted_pdf")
            if len(reader.pages) < 1:
                raise InspectionError("invalid_pdf")
            parts, length = [], 0
            for number, page in enumerate(reader.pages):
                if number >= 100 or length >= MAX_TEXT:
                    pdf_limit = True
                    break
                chunk = page.extract_text() or ""
                parts.append(chunk[:MAX_TEXT + 1 - length])
                length += len(chunk)
            text = "\n".join(parts)
        elif extension == "docx":
            import zipfile

            from ..config import settings
            from . import safe_xml
            from .document_formats import validate_docx

            # Never let this worker's private default settings relax the
            # caller's compressed or uncompressed DOCX upload boundaries.
            if settings.max_upload_size_bytes != upload_limit:
                raise InspectionError("inspection_unavailable")
            validate_docx(content)
            namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            parts, length = [], 0
            with zipfile.ZipFile(BytesIO(content)) as package:
                selected = ["word/document.xml"] + sorted(name for name in package.namelist()
                    if name.startswith(("word/header", "word/footer")) and name.endswith(".xml"))
                for part in selected:
                    root = safe_xml.fromstring(package.read(part))
                    for paragraph in root.iter(namespace + "p"):
                        chunk = "".join(node.text or "" if node.tag == namespace + "t" else
                            "\t" if node.tag == namespace + "tab" else "\n"
                            for node in paragraph.iter() if node.tag in (
                                namespace + "t", namespace + "tab", namespace + "br")) + "\n"
                        parts.append(chunk[:MAX_TEXT + 1 - length])
                        length += len(chunk)
                        if length > MAX_TEXT:
                            break
                    if length > MAX_TEXT:
                        break
            text = "".join(parts)
        else:
            from PIL import Image

            with Image.open(BytesIO(content)) as image:
                if (image.format != IMAGE_FORMATS[extension] or image.width < 1 or image.height < 1
                        or image.width * image.height > 25_000_000):
                    raise InspectionError("invalid_image")
                image.verify()
    except InspectionError:
        raise
    except (ImportError, MemoryError):
        raise
    except Exception as error:
        code = "invalid_image" if extension in IMAGE_FORMATS else "invalid_" + extension
        raise InspectionError(code) from error
    truncated = len(text) > MAX_TEXT
    flags = []
    if pdf_limit:
        flags.append("pdf_limit")
    if extension == "pdf" and not text.strip():
        flags.append("pdf_empty")
    if extension == "docx" and not text.strip():
        flags.append("docx_empty")
    if extension in IMAGE_FORMATS:
        flags.append("image_only")
    if truncated:
        flags.append("text_limit")
    return {"text": text[:MAX_TEXT], "text_truncated": truncated, "flags": flags,
            "source_sha256": hashlib.sha256(content).hexdigest(), "source_bytes": len(content)}


def _checked_result(value, content, extension):
    if (not isinstance(value, dict)
            or set(value) != {"text", "text_truncated", "flags", "source_sha256", "source_bytes"}
            or not isinstance(value["text"], str) or len(value["text"]) > MAX_TEXT
            or type(value["text_truncated"]) is not bool
            or type(value["source_bytes"]) is not int or value["source_bytes"] != len(content)
            or value["source_sha256"] != hashlib.sha256(content).hexdigest()
            or not isinstance(value["flags"], list)
            or any(not isinstance(flag, str) for flag in value["flags"])):
        raise ValueError("Invalid attachment worker result")
    flags = value["flags"]
    if len(set(flags)) != len(flags) or any(flag not in HINTS for flag in flags):
        raise ValueError("Invalid attachment flags")
    expected = []
    if extension == "pdf":
        if "pdf_limit" in flags:
            expected.append("pdf_limit")
        if not value["text"].strip():
            expected.append("pdf_empty")
    elif extension == "docx":
        if not value["text"].strip():
            expected.append("docx_empty")
    else:
        if value["text"] or value["text_truncated"]:
            raise ValueError("Invalid image text")
        expected.append("image_only")
    if value["text_truncated"]:
        if len(value["text"]) != MAX_TEXT:
            raise ValueError("Invalid text truncation")
        expected.append("text_limit")
    if flags != expected:
        raise ValueError("Inconsistent attachment flags")
    return {"text": value["text"], "text_truncated": value["text_truncated"],
            "omissions": [HINTS[flag] for flag in flags]}


def inspect_binary(content: bytes, extension: str, *, source_limit: int, upload_limit: int) -> dict:
    from .document_text_process import worker_command
    from .document_worker_diagnostics import FAILURE_FILE, observation, stage
    from .e_invoice.validator import _protect_windows_directory, _run

    try:
        _limits(extension, source_limit, upload_limit)
        if not isinstance(content, bytes) or not content or len(content) > source_limit:
            raise ValueError("Invalid attachment input")
        with tempfile.TemporaryDirectory(prefix="immo-e-invoice-text-") as directory, observation(
                "attachment", folder=Path(directory), ignore=(HTTPException,)) as diagnostic:
            folder = Path(directory)
            stage("attachment_input")
            if os.name == "nt":
                _protect_windows_directory(folder)
            (folder / "source.bin").write_bytes(content)
            request = {"action": "inspect_attachment", "extension": extension,
                       "source_limit": source_limit, "upload_limit": upload_limit}
            (folder / "input.json").write_text(json.dumps(request), encoding="utf-8")
            environment = {"DOCUMENT_TEXT_READ_DIR": str(folder), "PATH": "",
                "PYTHONPATH": str(Path(__file__).resolve().parents[2]), "PYTHONUTF8": "1",
                "DATA_DIR": str(folder), "DATABASE_URL": "sqlite:///:memory:",
                "SECRET_KEY_FILE": str(folder / "keyring.json"),
                "INTEGRATION_STATE_FILE": str(folder / "integrations.json"),
                "MAX_UPLOAD_SIZE_BYTES": str(upload_limit), "JOB_SCHEDULER_ENABLED": "false",
                "BACKUP_SCHEDULE_ENABLED": "false", "ENVIRONMENT": "development"}
            stage("attachment_process")
            code, _, _ = _run(worker_command(folder), folder, environment=environment,
                timeout_seconds=TIMEOUT_SECONDS, max_processes=2, file_limit_bytes=WORK_BYTES, resource_mode="image")
            diagnostic.exit_code = code
            stage("attachment_result")
            result = folder / "result.json"
            failure = folder / FAILURE_FILE
            if (code or not result.is_file() or result.stat().st_size > MAX_RESPONSE_BYTES
                    or failure.exists() or failure.is_symlink()):
                raise ValueError("Attachment worker did not finish")
            value = json.loads(result.read_text(encoding="utf-8"))
            if isinstance(value, dict) and set(value) == {"error"}:
                stage("attachment_worker_error")
                errors = {
                    "invalid_pdf": (422, "PDF konnte nicht gelesen werden."),
                    "encrypted_pdf": (422, "Passwortgeschützte PDFs können nicht analysiert werden."),
                    "invalid_docx": (422, "Das DOCX ist beschädigt, geschützt oder enthält nicht unterstützte aktive Inhalte."),
                    "invalid_image": (415, "Bildformat ist ungültig oder das Bild ist zu groß."),
                }
                if isinstance(value["error"], str) and value["error"] in errors:
                    status, message = errors[value["error"]]
                    raise HTTPException(status, message)
                raise ValueError("Invalid attachment worker error")
            stage("attachment_schema")
            return _checked_result(value, content, extension)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Die isolierte Anhangprüfung konnte wegen eines Lese-, Zeit- oder Ressourcenlimits nicht abgeschlossen werden. Bitte die Datei erneut prüfen; das Original bleibt erhalten.") from None
