"""Optional local PDF tools. Never writes an input file or returns overlay redaction.

PyMuPDF is deliberately not imported at application startup. Its AGPL/commercial
licensing must be resolved by the operator before enabling this optional engine.
"""
import html
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import HTTPException
from PIL import Image

from ..config import settings
from ..document_work_models import Annotation
from .document_formats import decode


def available():
    return importlib.util.find_spec("pymupdf") is not None


def worker_command(folder: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "document-pdf-worker", str(folder)]
    return [sys.executable, "-m", "backend.services.document_pdf_worker", str(folder)]


def isolated(content, action, options=None, extra_contents=(), annotations=()):
    """Bound native PDF work to a disposable child. A native crash cannot kill
    the application, and no live database/configuration is given to the child.
    """
    if not available():
        engine()  # the same explicit missing-component error, without a child
    from ..paths import get_data_dir
    root = Path(get_data_dir()).resolve() / "document-pdf-jobs"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="work-", dir=root) as temporary:
        folder = Path(temporary)
        (folder / "source.pdf").write_bytes(content)
        for index, value in enumerate(extra_contents):
            (folder / f"extra-{index}.pdf").write_bytes(value)
        request = {"action": action, "options": options or {}, "extra_count": len(extra_contents),
                   "annotations": annotations}
        (folder / "input.json").write_text(json.dumps(request, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        environment = {key: value for key, value in os.environ.items() if key.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TESSDATA_PREFIX"}}
        environment.update(PYTHONPATH=str(Path(__file__).resolve().parents[2]), PYTHONUTF8="1",
            DATA_DIR=str(folder), DATABASE_URL="sqlite:///:memory:", JOB_SCHEDULER_ENABLED="false",
            BACKUP_SCHEDULE_ENABLED="false", INTEGRATION_STATE_FILE=str(folder / "integrations.json"),
            SECRET_KEY_FILE=str(folder / "keyring.json"), ENVIRONMENT="development")
        try:
            completed = subprocess.run(worker_command(folder),
                cwd=folder, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=120, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise HTTPException(503, "Das PDF-Werkzeug hat das Zeitlimit erreicht. Der gespeicherte Auftrag kann erneut ausgeführt werden.") from None
        except OSError:
            raise HTTPException(503, "Die lokale PDF-Verarbeitung konnte nicht gestartet werden.") from None
        output = folder / "result.json"
        if completed.returncode or not output.is_file() or output.stat().st_size > 5_000_000:
            raise HTTPException(503, "Die isolierte PDF-Verarbeitung wurde abgebrochen. Original und Auftrag bleiben erhalten.")
        result = json.loads(output.read_text(encoding="utf-8"))
        if "error" in result:
            raise HTTPException(result["status"], result["error"])
        if action in {"inspect", "validate_annotations"}:
            return result["result"]
        outputs = []
        for index, item in enumerate(result["outputs"]):
            file = folder / f"output-{index}.pdf"
            if not file.is_file() or file.stat().st_size > settings.max_upload_size_bytes:
                raise HTTPException(413, "Die PDF-Ausgabe fehlt oder überschreitet die erlaubte Größe.")
            outputs.append((item["filename"], "application/pdf", file.read_bytes()))
        return outputs


def engine():
    if not available():
        raise HTTPException(503, "Die lokale PDF-Werkzeugkomponente ist noch nicht installiert. Original und Auftrag bleiben erhalten.")
    import pymupdf
    return pymupdf


def open_pdf(content):
    fitz = engine()
    try:
        doc = fitz.open(stream=content, filetype="pdf")
        if doc.needs_pass or doc.is_encrypted:
            doc.close()
            raise HTTPException(422, "Geschützte PDFs bitte lokal entsperren und als neue Eingangsdatei übernehmen.")
        if doc.is_repaired or doc.page_count == 0:
            doc.close()
            raise HTTPException(422, "Das PDF ist beschädigt oder enthält keine Seiten. Eine stille Reparatur ist nicht zulässig.")
        return doc
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "Das PDF kann nicht sicher geöffnet werden.") from None


def inspect_pdf(content, *, start_page=0, limit=50):
    fitz = engine()
    with open_pdf(content) as doc:
        if type(start_page) is not int or type(limit) is not int or start_page < 0 or not 1 <= limit <= 100 or start_page >= len(doc):
            raise HTTPException(422, "Ungültige Prüfseite oder Seitengröße.")
        pages, signatures, forms = [], [], []
        end = min(start_page + limit, len(doc))
        for number in range(start_page, end):
            page = doc[number]
            pages.append({"page": page.number, "width": page.cropbox.width, "height": page.cropbox.height,
                          "rotation": page.rotation})
            for widget in page.widgets() or []:
                item = {"page": page.number, "name": widget.field_name, "type": widget.field_type_string,
                        "value": str(widget.field_value or ""), "rect": list(widget.rect), "xref": widget.xref,
                        "read_only": bool(widget.field_flags & fitz.PDF_FIELD_IS_READ_ONLY),
                        "choices": list(widget.choice_values or [])}
                if widget.field_type in {fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON}:
                    item["on_value"] = widget.on_state()
                if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                    signatures.append(item | {"validity": "not_verified"})
                else:
                    forms.append(item)
        return {"pages": pages, "signatures": signatures, "forms": forms,
                "total_pages": len(doc), "next_page": end if end < len(doc) else None,
                "signature_validity": "not_verified", "signature_flags": doc.get_sigflags()}


def rectangle(page, value):
    fitz = engine()
    if not isinstance(value, (list, tuple)) or len(value) != 4 or any(
            isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in value):
        raise HTTPException(422, "Ein Rechteck benötigt vier endliche PDF-Punktkoordinaten.")
    rect = fitz.Rect(value)
    bounds = fitz.Rect(0, 0, page.cropbox.width, page.cropbox.height)
    if rect.is_empty or rect.is_infinite or not bounds.contains(rect):
        raise HTTPException(422, "Die Markierung liegt außerhalb der unrotierten Seite.")
    return rect


def page_at(doc, number):
    if type(number) is not int or not 0 <= number < len(doc):
        raise HTTPException(422, "Ungültige Seitennummer (Seiten beginnen bei 0).")
    return doc[number]


def _validate(doc, items):
    result = []
    for item in items:
        value = item if isinstance(item, Annotation) else Annotation.model_validate({
            key: val for key, val in item.items() if key not in {"author_id", "created_at", "modified_by", "modified_at"}})
        page = page_at(doc, value.page)
        rect = rectangle(page, value.rect)
        if page.rotation != value.rotation:
            raise HTTPException(409, "Die Seitenrotation wurde geändert. Bitte die Anmerkungen vergleichen.")
        if value.kind in {"freehand", "drawn_signature"}:
            if len(value.points) < 2 or any(not all(math.isfinite(x) for x in point)
                    or not rect.contains(engine().Point(*point)) for point in value.points):
                raise HTTPException(422, "Freihandzüge benötigen mindestens zwei Punkte innerhalb der Markierung.")
        if value.kind == "image_signature":
            if not value.image_base64:
                raise HTTPException(422, "Bitte eine Bildunterschrift auswählen.")
            image = decode(value.image_base64)
            try:
                with Image.open(io.BytesIO(image)) as source:
                    if source.format not in {"PNG", "JPEG"}:
                        raise ValueError()
                    source.verify()
            except (OSError, ValueError, Image.DecompressionBombError):
                raise HTTPException(422, "Bildunterschriften benötigen ein gültiges PNG oder JPEG.") from None
        result.append(value)
    return result


def validate_annotations(content, items):
    with open_pdf(content) as doc:
        _validate(doc, items)


def _text(page, rect, value, rotation=0):
    # Escaped text only, no HTML/remote resources accepted from the caller.
    spare, _ = page.insert_htmlbox(rect, "<div>" + html.escape(value).replace("\n", "<br>") + "</div>",
                                  rotate=rotation, scale_low=1)
    if spare < 0:
        raise HTTPException(422, "Der Text passt nicht in das gewählte Rechteck. Bitte das Rechteck vergrößern.")


def _flatten(doc, items):
    fitz = engine()
    for item in _validate(doc, items):
        page = doc[item.page]
        rect = rectangle(page, item.rect)
        if item.kind == "highlight":
            page.draw_rect(rect, color=None, fill=(1, 0.9, 0), fill_opacity=0.3, overlay=True)
        elif item.kind in {"freehand", "drawn_signature"}:
            page.draw_polyline([fitz.Point(*point) for point in item.points], color=(0, 0, 0.6), width=1.5)
        elif item.kind == "image_signature":
            page.insert_image(rect, stream=decode(item.image_base64), rotate=item.rotation)
        else:
            _text(page, rect, item.text, rotation=item.rotation)


def _bytes(doc):
    value = doc.tobytes(garbage=4, deflate=True, clean=True)
    if len(value) > settings.max_upload_size_bytes:
        raise HTTPException(413, "Die erzeugte Ausgabe ist zu groß. Bitte einen kleineren Seitenbereich wählen.")
    return value


def _sanitize_raster(doc):
    """Rebuild only visible post-redaction pixels: no source objects, attachments,
    metadata, forms, layers, comments or hidden/overlapping text survive.

    The result intentionally has no searchable text. This conservative mode is
    explicit in the UI; it is never represented as lossless optimization.
    """
    fitz = engine()
    result = fitz.open()
    try:
        for page in doc:
            if page.rect.width * page.rect.height * 4 > 80_000_000:
                raise HTTPException(413, "Die Seite ist für die sichere Rasterausgabe zu groß.")
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False, annots=False)
            output = result.new_page(width=page.rect.width, height=page.rect.height)
            output.insert_image(output.rect, stream=pixmap.tobytes("png"))
        result.set_metadata({})
        return _bytes(result)
    finally:
        result.close()


def transform(content, operation, options, extra_contents, annotations):
    fitz = engine()
    try:
        with open_pdf(content) as doc:
            if operation == "flatten":
                _flatten(doc, annotations)
            elif operation == "rotate":
                rotation = options.get("degrees")
                if type(rotation) is not int or rotation not in {90, 180, 270}:
                    raise HTTPException(422, "Bitte 90, 180 oder 270 Grad wählen.")
                indexes = options.get("pages")
                if not isinstance(indexes, list) or not indexes or len(set(indexes)) != len(indexes):
                    raise HTTPException(422, "Bitte jede zu drehende Seite genau einmal auswählen.")
                for index in indexes:
                    page = page_at(doc, index)
                    page.set_rotation((page.rotation + rotation) % 360)
            elif operation == "pages":
                indexes = options.get("pages")
                if not isinstance(indexes, list) or not indexes:
                    raise HTTPException(422, "Bitte mindestens eine Seite wählen.")
                for index in indexes:
                    page_at(doc, index)
                doc.select(indexes)
            elif operation in {"insert", "merge"}:
                if not extra_contents:
                    raise HTTPException(422, "Bitte mindestens ein archiviertes Zusatz-PDF auswählen.")
                position = options.get("at", len(doc)) if operation == "insert" else len(doc)
                if type(position) is not int or not 0 <= position <= len(doc):
                    raise HTTPException(422, "Ungültige Einfügeposition.")
                for extra in extra_contents:
                    with open_pdf(extra) as other:
                        doc.insert_pdf(other, start_at=position)
                        position += len(other)
            elif operation == "split":
                groups = options.get("groups")
                if not isinstance(groups, list) or not groups:
                    raise HTTPException(422, "Bitte Seitengruppen angeben.")
                if sorted(index for group in groups for index in group) != list(range(len(doc))):
                    raise HTTPException(422, "Beim Teilen muss jede Quellseite genau einer Ausgabe zugeordnet sein.")
                outputs = []
                for number, group in enumerate(groups):
                    if not group:
                        raise HTTPException(422, "Eine Ausgabe darf nicht leer sein.")
                    with fitz.open() as output:
                        for index in group:
                            page_at(doc, index)
                            output.insert_pdf(doc, from_page=index, to_page=index)
                        outputs.append((f"Teil-{number + 1}.pdf", "application/pdf", _bytes(output)))
                return outputs
            elif operation == "crop":
                for change in options.get("regions", []):
                    page = page_at(doc, change["page"])
                    rect = rectangle(page, change["rect"])
                    # This only changes the view. UI explicitly says crop is not redaction.
                    page.set_cropbox(rect + (page.cropbox_position.x, page.cropbox_position.y,
                                             page.cropbox_position.x, page.cropbox_position.y))
            elif operation == "forms":
                changes = options.get("fields")
                if not isinstance(changes, list) or not changes:
                    raise HTTPException(422, "Bitte mindestens ein bearbeitbares Formularfeld auswählen.")
                for change in changes:
                    page = page_at(doc, change["page"])
                    found = [widget for widget in page.widgets() or [] if widget.field_name == change["name"]
                             and ("xref" not in change or widget.xref == change["xref"])]
                    if len(found) != 1 or found[0].field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                        raise HTTPException(422, "Formularfeld nicht eindeutig oder ein geschütztes Signaturfeld.")
                    widget = found[0]
                    if widget.field_flags & fitz.PDF_FIELD_IS_READ_ONLY:
                        raise HTTPException(422, "Ein schreibgeschütztes Formularfeld darf nicht überschrieben werden.")
                    value = change["value"]
                    if widget.field_type in {fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON}:
                        on_value = widget.on_state()
                        if value is True or value == on_value:
                            value = on_value
                        elif value is False or value == "Off":
                            value = "Off"
                        else:
                            raise HTTPException(422, "Ungültiger Zustand für ein Auswahlfeld.")
                    elif widget.field_type in {fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX}:
                        if not isinstance(value, str) or (value not in (widget.choice_values or [])
                                and not widget.field_flags & fitz.PDF_CH_FIELD_IS_EDIT):
                            raise HTTPException(422, "Bitte einen zulässigen Formularwert wählen.")
                    elif widget.field_type != fitz.PDF_WIDGET_TYPE_TEXT or not isinstance(value, str):
                        raise HTTPException(422, "Dieses Formularfeld kann nicht ausgefüllt werden.")
                    if isinstance(value, str) and widget.text_maxlen and len(value) > widget.text_maxlen:
                        raise HTTPException(422, "Der Formularwert überschreitet die erlaubte Feldlänge.")
                    widget.field_value = value
                    widget.update()
            elif operation in {"redact", "edit_content"}:
                regions = options.get("regions", [])
                if not regions:
                    raise HTTPException(422, "Bitte mindestens einen Inhaltsbereich angeben.")
                if operation == "edit_content" and options.get("explicit_content_mode") is not True:
                    raise HTTPException(422, "Bitte die Inhaltsbearbeitung ausdrücklich bestätigen.")
                for change in regions:
                    page = page_at(doc, change["page"])
                    rect = rectangle(page, change["rect"])
                    page.add_redact_annot(rect, fill=(0, 0, 0) if operation == "redact" else (1, 1, 1))
                    page.apply_redactions(images=2, graphics=2, text=0)
                    if operation == "edit_content":
                        _text(page, rect, str(change.get("text", "")))
                if operation == "redact":
                    return [("Geschwaerzt.pdf", "application/pdf", _sanitize_raster(doc))]
            elif operation == "ocr":
                # Rebuild a searchable PDF from page pixels using local Tesseract;
                # unlike an extracted .txt this actually contains a text layer.
                try:
                    tessdata = fitz.get_tessdata()
                    with fitz.open() as searchable:
                        for page in doc:
                            if page.rect.width * page.rect.height * 4 > 80_000_000:
                                raise HTTPException(413, "Die Seite ist für lokale OCR zu groß.")
                            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                            value = pixmap.pdfocr_tobytes(language="deu+eng", tessdata=tessdata)
                            with open_pdf(value) as recognized:
                                searchable.insert_pdf(recognized)
                        return [("Durchsuchbar.pdf", "application/pdf", _bytes(searchable))]
                except HTTPException:
                    raise
                except Exception:
                    raise HTTPException(503, "Die lokale OCR-Komponente oder ihre Sprachdaten (Deutsch/Englisch) sind noch nicht verfügbar. Der Auftrag bleibt wiederholbar.") from None
            elif operation != "optimize":
                raise HTTPException(422, "Dieses PDF-Werkzeug ist nicht unterstützt.")
            return [("Ausgabe.pdf", "application/pdf", _bytes(doc))]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "Der PDF-Auftrag konnte nicht ausgeführt werden. Bitte Seiten, Felder und Eingabedateien prüfen.") from None
