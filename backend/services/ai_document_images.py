"""Bounded AI page images, parsed only in the existing owned document worker."""
from __future__ import annotations

import base64
import json
import math
import os
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from .document_text_reader import MAX_OCR_PIXELS

MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_PAGES = 20
MAX_PAGE_PIXELS = MAX_OCR_PIXELS
MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_ENCODED_BYTES = MAX_RESPONSE_BYTES - 64 * 1024
TIMEOUT_SECONDS = 30
WORK_BYTES = 128 * 1024 * 1024
IMAGE_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


class ImageRenderError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ImageRendererUnavailable(HTTPException):
    """Only this known absence can permit an explicitly disclosed text-only path."""
    code = "renderer_unavailable"

    def __init__(self):
        super().__init__(503, "Die lokale Bildkonvertierung ist nicht verfügbar. Bitte das Dokument mit Textebene verwenden oder die Dokumentwerkzeuge installieren.")


def _filename(value: str) -> str:
    return "".join(c for c in value.replace("\\", "/").rsplit("/", 1)[-1] if ord(c) >= 32)[:160] or "Dokument"


def _omissions(total: int, sent: int) -> list[str]:
    return ([f"Für die KI wurden Seitenbilder von {sent} der {total} Seiten übertragen. "
             "Die übrigen Seiten sind wegen des gewählten Seiten- oder Bilddatenlimits nicht als Bild enthalten."]
            if sent < total else [])


def _pixels(width: float, height: float) -> None:
    if (not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0
            or math.ceil(width) * math.ceil(height) > MAX_PAGE_PIXELS):
        raise ImageRenderError("image_limit")


def _qt_pdf(content: bytes, filename: str, max_pages: int, add: Callable[[bytes, str, str], bool]) -> int:
    """Use the already bundled Qt PDF engine only inside the owned worker."""
    owned = os.environ.get("DOCUMENT_TEXT_READ_DIR")
    if (not owned or not Path(owned).name.startswith("immo-e-invoice-text-")
            or (Path(owned) / "work").resolve() != Path.cwd().resolve()):
        raise ImageRenderError("renderer_unavailable")
    try:
        # Static imports also let the existing PyInstaller Qt hooks collect
        # QtPdf and its native dependencies, without a new package dependency.
        from PySide6 import QtCore, QtGui, QtPdf  # type: ignore[import-not-found]
    except (ImportError, OSError) as error:
        raise ImageRenderError("renderer_unavailable") from error
    application = QtGui.QGuiApplication.instance()
    if application is None:
        application = QtGui.QGuiApplication(["immomanager-document-images", "-platform", "offscreen"])
    if not isinstance(application, QtGui.QGuiApplication) or application.platformName() != "offscreen":
        raise ImageRenderError("renderer_unavailable")
    document = QtPdf.QPdfDocument()
    source = QtCore.QBuffer(document)
    source.setData(QtCore.QByteArray(content))
    source.open(QtCore.QIODevice.OpenModeFlag.ReadOnly)
    try:
        document.load(source)
        total = document.pageCount()
        if (document.status() != QtPdf.QPdfDocument.Status.Ready or document.error() != QtPdf.QPdfDocument.Error.None_
                or type(total) is not int or total < 1):
            raise ImageRenderError("invalid_document")
        for number in range(min(total, max_pages)):
            points = document.pagePointSize(number)
            width, height = points.width() * 150 / 72, points.height() * 150 / 72
            _pixels(width, height)  # before allocating any native raster
            size = QtCore.QSize(math.ceil(width), math.ceil(height))
            image = document.render(number, size)
            if image.isNull():
                raise ImageRenderError("invalid_document")
            _pixels(image.width(), image.height())
            # QPdfDocument may leave the page background transparent. Match
            # the ordinary white PDF page rather than turning it black in RGB.
            opaque = QtGui.QImage(size, QtGui.QImage.Format.Format_RGB32)
            opaque.fill(QtCore.Qt.GlobalColor.white)
            painter = QtGui.QPainter(opaque)
            try:
                painter.drawImage(0, 0, image)
            finally:
                painter.end()
            encoded = QtCore.QBuffer()
            encoded.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
            try:
                if not opaque.save(encoded, "PNG"):
                    raise ImageRenderError("invalid_document")
                if encoded.size() > MAX_IMAGE_BYTES:
                    raise ImageRenderError("image_limit")
                if not add(bytes(encoded.data()), "image/png", f"{filename} Seite {number + 1}.png"):
                    break
            finally:
                encoded.close()
        return total
    finally:
        document.close()
        source.close()


def render_in_worker(content: bytes, media_type: str, filename: str, max_pages: int) -> dict[str, Any]:
    """Worker-only native parsing. Call render_page_images from the application."""
    if (not isinstance(content, bytes) or not content or len(content) > MAX_SOURCE_BYTES
            or type(max_pages) is not int or not 1 <= max_pages <= MAX_PAGES
            or not isinstance(filename, str) or len(filename) > 200
            or media_type not in {*IMAGE_FORMATS, "application/pdf"}):
        raise ImageRenderError("invalid_document")
    filename = _filename(filename)
    images: list[dict[str, str]] = []
    encoded_total = 0

    def add(data: bytes, mime: str, name: str) -> bool:
        nonlocal encoded_total
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ImageRenderError("image_limit")
        # Check before allocating the base64 string or serializing JSON.
        encoded_length = 4 * ((len(data) + 2) // 3)
        if encoded_total + encoded_length > MAX_ENCODED_BYTES:
            if not images:
                raise ImageRenderError("image_limit")
            return False
        encoded_total += encoded_length
        images.append({"name": name, "mime": mime, "data_base64": base64.b64encode(data).decode("ascii")})
        return True

    try:
        if media_type in IMAGE_FORMATS:
            try:
                from PIL import Image
            except ImportError as error:
                raise ImageRenderError("renderer_unavailable") from error
            with Image.open(BytesIO(content)) as image:
                if image.format != IMAGE_FORMATS[media_type]:
                    raise ImageRenderError("invalid_document")
                _pixels(image.width, image.height)
                image.verify()
            add(content, media_type, filename)
            total = 1
        else:
            try:
                import fitz  # type: ignore[import-not-found,import-untyped]
            except ImportError:
                total = _qt_pdf(content, filename, max_pages, add)
            else:
                with fitz.open(stream=content, filetype="pdf") as document:
                    total = document.page_count
                    if document.is_encrypted or type(total) is not int or total < 1:
                        raise ImageRenderError("invalid_document")
                    for number in range(min(total, max_pages)):
                        page = document.load_page(number)
                        # Validate raster geometry before native pixel allocation.
                        _pixels(page.rect.width * 150 / 72, page.rect.height * 150 / 72)
                        pixmap = page.get_pixmap(dpi=150, colorspace=fitz.csRGB, alpha=False)
                        _pixels(pixmap.width, pixmap.height)
                        if not add(pixmap.tobytes("png"), "image/png", f"{filename} Seite {number + 1}.png"):
                            break
        return {"images": images, "pages_total": total, "pages_sent": len(images),
                "omissions": _omissions(total, len(images))}
    except ImageRenderError:
        raise
    except Exception as error:
        raise ImageRenderError("invalid_document") from error


def _checked_result(value: Any, media_type: str, filename: str, max_pages: int) -> dict[str, Any]:
    if (not isinstance(value, dict) or set(value) != {"images", "pages_total", "pages_sent", "omissions"}
            or type(value["pages_total"]) is not int or type(value["pages_sent"]) is not int
            or not 1 <= value["pages_sent"] <= min(value["pages_total"], max_pages)
            or not isinstance(value["images"], list) or len(value["images"]) != value["pages_sent"]
            or value["omissions"] != _omissions(value["pages_total"], value["pages_sent"])):
        raise ValueError("Invalid image worker response")
    if media_type != "application/pdf" and (value["pages_total"] != 1 or value["pages_sent"] != 1):
        raise ValueError("Invalid image count")
    encoded_total = 0
    for number, image in enumerate(value["images"]):
        expected_name = f"{filename} Seite {number + 1}.png" if media_type == "application/pdf" else filename
        expected_mime = "image/png" if media_type == "application/pdf" else media_type
        if (not isinstance(image, dict) or set(image) != {"name", "mime", "data_base64"}
                or image["name"] != expected_name or image["mime"] != expected_mime
                or not isinstance(image["data_base64"], str)):
            raise ValueError("Invalid image metadata")
        encoded_total += len(image["data_base64"])
        if encoded_total > MAX_ENCODED_BYTES or len(image["data_base64"]) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
            raise ValueError("Image worker response over budget")
        data = base64.b64decode(image["data_base64"], validate=True)
        if not 1 <= len(data) <= MAX_IMAGE_BYTES:
            raise ValueError("Invalid image bytes")
        if ((expected_mime == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n"))
                or (expected_mime == "image/jpeg" and not data.startswith(b"\xff\xd8"))
                or (expected_mime == "image/webp" and not (data.startswith(b"RIFF") and data[8:12] == b"WEBP"))):
            raise ValueError("Invalid image format")
    return value


def render_page_images(content: bytes, media_type: str, filename: str, max_pages: int = 4) -> dict[str, Any]:
    """Render owned, temporary bytes with resource limits; never parse in the API."""
    from .document_text_process import worker_command
    from .e_invoice.validator import _protect_windows_directory, _run

    if type(max_pages) is not int or not 1 <= max_pages <= MAX_PAGES:
        raise HTTPException(422, "Für KI-Seitenbilder sind 1 bis 20 Seiten zulässig.")
    if media_type not in {*IMAGE_FORMATS, "application/pdf"}:
        return {"images": [], "pages_total": 0, "pages_sent": 0, "omissions": []}
    if not isinstance(content, bytes) or not content or len(content) > MAX_SOURCE_BYTES:
        raise HTTPException(422, "Die Bildauswertung benötigt eine nichtleere Datei mit höchstens 50 MiB.")
    if not isinstance(filename, str):
        raise HTTPException(422, "Der Dateiname für die Bildauswertung ist ungültig.")
    filename = _filename(filename)
    try:
        with tempfile.TemporaryDirectory(prefix="immo-e-invoice-text-") as directory:
            folder = Path(directory)
            if os.name == "nt":
                _protect_windows_directory(folder)
            (folder / "source.bin").write_bytes(content)
            request = {"action": "render_images", "media_type": media_type, "filename": filename, "max_pages": max_pages}
            (folder / "input.json").write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            env = {"DOCUMENT_TEXT_READ_DIR": str(folder), "PATH": "", "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
                   "PYTHONUTF8": "1", "DATA_DIR": str(folder), "DATABASE_URL": "sqlite:///:memory:",
                   "SECRET_KEY_FILE": str(folder / "keyring.json"), "INTEGRATION_STATE_FILE": str(folder / "integrations.json"),
                   "JOB_SCHEDULER_ENABLED": "false", "BACKUP_SCHEDULE_ENABLED": "false", "ENVIRONMENT": "development"}
            code, _, _ = _run(worker_command(folder), folder, environment=env, timeout_seconds=TIMEOUT_SECONDS,
                              max_processes=2, file_limit_bytes=WORK_BYTES, resource_mode="image")
            result = folder / "result.json"
            if code or not result.is_file() or result.stat().st_size > MAX_RESPONSE_BYTES:
                raise ValueError("Image worker did not complete")
            value = json.loads(result.read_text(encoding="utf-8"))
            if isinstance(value, dict) and set(value) == {"error"}:
                if value["error"] == "renderer_unavailable":
                    raise ImageRendererUnavailable()
                if value["error"] in {"invalid_document", "image_limit"}:
                    raise HTTPException(422, "Die Datei kann nicht als begrenztes KI-Seitenbild gelesen werden. Bitte eine lesbare oder kleinere Datei verwenden; das Original bleibt erhalten.")
                raise ValueError("Invalid image worker error")
            return _checked_result(value, media_type, filename, max_pages)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Die isolierte Bildauswertung konnte wegen eines Lese-, Zeit- oder Ressourcenlimits nicht abgeschlossen werden. Das Original bleibt erhalten.") from None
