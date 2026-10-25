"""Printing and passing on documents: one printable PDF, an e-mail draft with the file attached.

Both read the document's current file (its newest archived version, else the uploaded file) and
never send anything: the PDF goes to the browser's print dialog, the draft (.eml with X-Unsent)
opens in the person's mail program, ready to send from there.

Printable are PDFs (pages as they are), images (one A4 page each, scaled to fit), text files and,
with a local LibreOffice, Word files. Anything else is named as left out.
"""
from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from io import BytesIO
from typing import Any

from fastapi import HTTPException

from . import document_text

MAX_DOCUMENTS = 50
MAX_BYTES = 150 * 1024 * 1024
IMAGES = {"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "webp"}
TEXTS = {"txt", "csv", "md", "log", "json", "xml"}
ADDRESS = re.compile(r"[^\s<>@,;\x00-\x1f\x7f]+@[^\s<>@,;\x00-\x1f\x7f]+\.[^\s<>@,;\x00-\x1f\x7f]+")
STORAGE_PREFIX = re.compile(r"^[0-9a-f]{32}_")


@dataclass
class CurrentFile:
    content: bytes
    filename: str
    media_type: str

    @property
    def extension(self) -> str:
        return self.filename.rsplit(".", 1)[-1].lower() if "." in self.filename else ""


def shown_name(name: str) -> str:
    """The name a person gave the file, without folders and the storage prefix of uploads."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    return STORAGE_PREFIX.sub("", base) or "Dokument"


def current_file(store: Any, document: Any) -> CurrentFile:
    found = document_text.source(store, document)
    if found is None:
        raise HTTPException(404, f"Zum Dokument „{document.title}“ gibt es keine Datei in dieser Installation.")
    _, content, name = found
    filename = shown_name(name)
    media_type = mimetypes.guess_type(filename)[0] or ("application/pdf" if content.startswith(b"%PDF-")
                                                      else "application/octet-stream")
    return CurrentFile(content, filename, media_type)


# ─── Printing ────────────────────────────────────────────────────────────────

def _image_pages(content: bytes, writer) -> None:
    from PIL import Image, ImageSequence
    from pypdf import PdfReader
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    image = Image.open(BytesIO(content))
    buffer = BytesIO()
    pdf = None
    for frame in ImageSequence.Iterator(image):
        page = frame.convert("RGB")
        size = landscape(A4) if page.width > page.height else A4
        if pdf is None:
            pdf = canvas.Canvas(buffer, pagesize=size)
        pdf.setPageSize(size)
        margin = 10 * mm
        # fit the page; a small image is enlarged at most threefold
        scale = min((size[0] - 2 * margin) / page.width, (size[1] - 2 * margin) / page.height, 3.0)
        width, height = page.width * scale, page.height * scale
        pdf.drawImage(ImageReader(page), (size[0] - width) / 2, (size[1] - height) / 2, width, height)
        pdf.showPage()
    if pdf is None:
        raise ValueError("leeres Bild")
    pdf.save()
    writer.append(PdfReader(BytesIO(buffer.getvalue())))


def _text_pages(content: bytes, title: str, writer) -> None:
    from pypdf import PdfReader
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    from .housing_confirmation_render import _fonts

    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    regular, bold = _fonts()
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    left, top, bottom, size, leading = 18 * mm, A4[1] - 18 * mm, 18 * mm, 9.5, 12.5
    width = A4[0] - 2 * left
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\t", "    ").split("\n"):
        line = ""
        for word in raw.split(" "):
            candidate = f"{line} {word}" if line else word
            if stringWidth(candidate, regular, size) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
            while stringWidth(word, regular, size) > width:   # a word longer than the line
                cut = max(1, int(len(word) * width / stringWidth(word, regular, size)))
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        lines.append(line)
    y = top
    pdf.setFont(bold, 11)
    pdf.drawString(left, y, title[:120])
    y -= 2 * leading
    pdf.setFont(regular, size)
    for line in lines:
        if y < bottom:
            pdf.showPage()
            pdf.setFont(regular, size)
            y = top
        pdf.drawString(left, y, line)
        y -= leading
    pdf.save()
    writer.append(PdfReader(BytesIO(buffer.getvalue())))


def _append(writer, file: CurrentFile, title: str) -> None:
    from pypdf import PdfReader

    if file.extension == "pdf" or file.content.startswith(b"%PDF-"):
        reader = PdfReader(BytesIO(file.content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("passwortgeschützt")
        writer.append(reader)
    elif file.extension in IMAGES:
        _image_pages(file.content, writer)
    elif file.extension in TEXTS:
        _text_pages(file.content, title, writer)
    elif file.extension == "docx":
        from .document_conversion import docx_pdf
        writer.append(PdfReader(BytesIO(docx_pdf(file.content))))
    else:
        raise ValueError("Dateiformat ohne Druckansicht")


def print_pdf(store: Any, document_ids: list[str]) -> tuple[bytes, list[dict]]:
    """One PDF with the pages of every printable document, in the given order, and the ones left out."""
    from pypdf import PdfWriter

    ids = list(dict.fromkeys(document_ids))
    if not ids:
        raise HTTPException(422, "Bitte mindestens ein Dokument auswählen.")
    if len(ids) > MAX_DOCUMENTS:
        raise HTTPException(422, f"Höchstens {MAX_DOCUMENTS} Dokumente auf einmal drucken.")
    from ..storage import NotFoundError
    documents = []
    for identifier in ids:
        try:
            documents.append(store.get_document(identifier))
        except NotFoundError as exc:
            raise HTTPException(404, "Dokument nicht gefunden.") from exc
    files, total, skipped = [], 0, []
    for document in documents:
        try:
            file = current_file(store, document)
        except HTTPException:
            skipped.append({"id": document.id, "title": document.title, "reason": "keine Datei"})
            continue
        total += len(file.content)
        if total > MAX_BYTES:
            raise HTTPException(413, "Die ausgewählten Dateien sind zusammen größer als 150 MB. Bitte weniger auswählen.")
        files.append((document, file))
    if len(files) == 1 and not skipped and (files[0][1].extension == "pdf" or files[0][1].content.startswith(b"%PDF-")):
        return files[0][1].content, []          # one PDF prints as it is
    writer = PdfWriter()
    for document, file in files:
        try:
            _append(writer, file, document.title or file.filename)
        except HTTPException as exc:             # no local LibreOffice for a Word file
            skipped.append({"id": document.id, "title": document.title, "reason": str(exc.detail)})
        except Exception as exc:                 # an unreadable file is left out, never a failed print
            reason = str(exc) if isinstance(exc, ValueError) else "Datei nicht lesbar"
            skipped.append({"id": document.id, "title": document.title, "reason": reason})
    if not len(writer.pages):
        names = ", ".join(f"„{item['title']}“ ({item['reason']})" for item in skipped)
        raise HTTPException(422, f"Keines der Dokumente lässt sich drucken: {names}.")
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue(), skipped


# ─── E-mail draft ────────────────────────────────────────────────────────────

def _addresses(values: list[str], label: str) -> list[str]:
    cleaned = [value.strip() for value in values if value and value.strip()]
    wrong = [value for value in cleaned if not value.isascii() or not ADDRESS.fullmatch(value) or len(value) > 254]
    if wrong:
        raise HTTPException(422, f"{label}: keine gültige E-Mail-Adresse: {', '.join(wrong)}")
    return cleaned


def email_draft(store: Any, document: Any, *, to: list[str], cc: list[str], subject: str, body: str) -> tuple[bytes, str]:
    """An unsent e-mail (.eml) with the document's file attached, to open and send in a mail program."""
    recipients, copies = _addresses(to, "An"), _addresses(cc, "Kopie")
    file = current_file(store, document)
    if len(file.content) > 25 * 1024 * 1024:
        raise HTTPException(413, "Die Datei ist größer als 25 MB; die meisten Mailserver nehmen sie nicht an.")
    message = EmailMessage()
    if recipients:
        message["To"] = ", ".join(recipients)
    if copies:
        message["Cc"] = ", ".join(copies)
    message["Subject"] = (subject or document.title or file.filename).replace("\n", " ")[:200]
    message["Date"] = format_datetime(datetime.now(timezone.utc))
    message["X-Unsent"] = "1"
    message.set_content(body or "")
    maintype, _, subtype = file.media_type.partition("/")
    message.add_attachment(file.content, maintype=maintype or "application", subtype=subtype or "octet-stream",
                           filename=file.filename)
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", document.title or "Dokument")[:80].strip() or "Dokument"
    return message.as_bytes(), f"{stem}.eml"
