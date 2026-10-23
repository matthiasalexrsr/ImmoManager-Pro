"""Validate native packages without rebuilding them or executing embedded content."""
import base64
import binascii
import io
import posixpath
import zipfile
from pathlib import PurePosixPath
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from fastapi import HTTPException
from PIL import Image

from ..config import settings

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def decode(value: str) -> bytes:
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "Ungültige Dateikodierung.") from None
    if not result or len(result) > settings.max_upload_size_bytes:
        raise HTTPException(413, "Die Datei ist leer oder überschreitet die erlaubte Größe.")
    return result


def validate_docx(content: bytes) -> dict:
    """Read all members (also CRCs), reject bombs, macros, embedded active objects and unsafe paths.

    The input bytes are returned/stored as supplied, never serialized by ElementTree.
    External hyperlinks are retained; external images/templates and OLE are refused.
    """
    if not content or len(content) > settings.max_upload_size_bytes:
        raise HTTPException(422, "Das DOCX ist leer oder überschreitet die erlaubte Dokumentgröße.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            entries = package.infolist()
            names = [item.filename for item in entries]
            if len(entries) > 10000 or len(names) != len(set(names)):
                raise ValueError()
            if not {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= set(names):
                raise ValueError()
            if sum(item.file_size for item in entries) > settings.max_upload_size_bytes * 10:
                raise ValueError()
            for item in entries:
                path = PurePosixPath(item.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in item.filename or ":" in item.filename:
                    raise ValueError()
                if item.flag_bits & 1 or item.file_size > settings.max_upload_size_bytes * 4:
                    raise ValueError()
                if any(part in item.filename.lower() for part in ("vbaproject", "embeddings/", "activex/")):
                    raise ValueError()
                data = package.read(item)
                if item.filename.endswith((".xml", ".rels")):
                    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                        raise ValueError()
                    xml = ET.fromstring(data)
                    if item.filename == "[Content_Types].xml" and any(any(marker in node.get("ContentType", "").lower()
                            for marker in ("macroenabled", "vbaproject", "activex", "oleobject")) for node in xml):
                        raise ValueError()
                    if item.filename == "word/document.xml" and any(node.tag.rsplit("}", 1)[-1] in {
                            "altChunk", "object", "control"} for node in xml.iter()):
                        raise ValueError()
                    if item.filename.endswith(".rels"):
                        for relation in xml:
                            if relation.get("Type", "").rsplit("/", 1)[-1].lower() in {
                                    "vbaproject", "oleobject", "control", "afchunk", "attachedtemplate"}:
                                raise ValueError()
                            if relation.get("TargetMode") == "External" and not (
                                relation.get("Type", "").endswith("/hyperlink")
                                and relation.get("Target", "").split(":", 1)[0].lower() in {"https", "http", "mailto"}
                            ):
                                raise ValueError()
                            if relation.get("TargetMode") != "External":
                                target = unquote(relation.get("Target", "")).split("#", 1)[0]
                                base = posixpath.dirname(posixpath.dirname(item.filename))
                                resolved = posixpath.normpath(posixpath.join(base, target))
                                if not target or target.startswith("/") or ":" in target or "\\" in target or (
                                        resolved.startswith("../") or resolved not in names):
                                    raise ValueError()
            main = ET.fromstring(package.read("word/document.xml"))
            if main.tag != "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document":
                raise ValueError()
            return {"format": "docx", "parts": len(entries), "native_ooxml": True,
                    "signature_parts": sum(name.startswith("_xmlsignatures/") for name in names),
                    "signature_validity": "not_verified"}
    except (zipfile.BadZipFile, KeyError, ValueError, ET.ParseError, RuntimeError, NotImplementedError):
        raise HTTPException(422, "Das DOCX ist beschädigt, geschützt oder enthält nicht unterstützte aktive Inhalte.") from None


def inspect_file(content: bytes, filename: str) -> dict:
    extension = filename.rsplit(".", 1)[-1].lower()
    if (not content and extension != "txt") or len(content) > settings.max_upload_size_bytes:
        raise HTTPException(413, "Die Datei ist leer oder zu groß.")
    if extension == "docx":
        return validate_docx(content) | {"media_type": DOCX}
    if extension == "pdf":
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-4096:]:
            raise HTTPException(422, "Das PDF ist unvollständig oder beschädigt.")
        # Full structural validation is provided by the optional local PDF engine.
        return {"format": "pdf", "media_type": "application/pdf", "structural_validation": "pending_engine"}
    if extension in {"png", "jpg", "jpeg", "tif", "tiff", "webp", "bmp"}:
        try:
            with Image.open(io.BytesIO(content)) as image:
                media = Image.MIME.get(image.format or "", "application/octet-stream")
                image.verify()
        except (OSError, ValueError, Image.DecompressionBombError):
            raise HTTPException(422, "Die Bilddatei ist beschädigt oder zu groß.") from None
        return {"format": "image", "media_type": media}
    if extension == "txt":
        try:
            content.decode("utf-8")
        except UnicodeError:
            raise HTTPException(422, "Textdateien müssen UTF-8 verwenden.") from None
        return {"format": "text", "media_type": "text/plain"}
    raise HTTPException(415, "Als Original sind PDF, DOCX, Bilder und UTF-8-Text unterstützt.")
