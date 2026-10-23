"""Explicit coordinator gate after installing requirements-documents-optional.txt.

Run via scripts/run_pro_matrix.py with this file explicitly selected. Missing
PyMuPDF is a collection failure, not a skipped proof. This file is outside the
default backend test collection because the engine is an optional component.
"""
import base64
import hashlib
import io

import pytest
from fastapi import HTTPException
from PIL import Image

from backend.document_work_models import Annotation
from backend.services.document_pdf import engine, inspect_pdf, isolated, transform, validate_annotations
from scripts.document_qa_fixtures import pdf_fixture

fitz = engine()


def test_rotate_reorder_extract_merge_and_split_have_independent_page_oracles():
    source = pdf_fixture()
    before = hashlib.sha256(source).hexdigest()
    rotated = transform(source, "rotate", {"pages": [0, 2], "degrees": 90}, [], [])[0][2]
    with fitz.open(stream=rotated, filetype="pdf") as pdf:
        assert [page.rotation for page in pdf] == [90, 90, 90, 0]
    reordered = transform(source, "pages", {"pages": [3, 0, 2]}, [], [])[0][2]
    with fitz.open(stream=reordered, filetype="pdf") as pdf:
        assert len(pdf) == 3
        assert [f"SEITE_{index}_ORAKEL" in pdf[number].get_text() for number, index in enumerate([4, 1, 3])] == [True] * 3
    merged = transform(source, "merge", {}, [source], [])[0][2]
    with fitz.open(stream=merged, filetype="pdf") as pdf:
        assert len(pdf) == 8 and "SEITE_1_ORAKEL" in pdf[4].get_text()
    split = transform(source, "split", {"groups": [[0, 2], [1, 3]]}, [], [])
    assert len(split) == 2
    for output, expected in zip(split, [[1, 3], [2, 4]], strict=True):
        with fitz.open(stream=output[2], filetype="pdf") as pdf:
            assert len(pdf) == 2 and all(f"SEITE_{number}_ORAKEL" in pdf[index].get_text() for index, number in enumerate(expected))
    assert hashlib.sha256(source).hexdigest() == before


def test_all_annotation_tools_flatten_to_new_bytes_without_changing_original():
    source = pdf_fixture()
    image = io.BytesIO()
    Image.new("RGB", (40, 15), (30, 40, 50)).save(image, "PNG")
    items = [Annotation(kind=kind, page=0, rect=(20, 30 + index * 40, 350, 65 + index * 40), text=f"Prüfung {kind} – Wärme €",
        points=[(30, 40 + index * 40), (90, 55 + index * 40)] if kind in {"freehand", "drawn_signature"} else [],
        image_base64=base64.b64encode(image.getvalue()).decode() if kind == "image_signature" else None)
        for index, kind in enumerate(["highlight", "comment", "text", "freehand", "stamp", "drawn_signature", "image_signature"])]
    validate_annotations(source, items)
    output = transform(source, "flatten", {}, [], [item.model_dump() for item in items])[0][2]
    assert output != source
    with fitz.open(stream=output, filetype="pdf") as pdf:
        assert "Prüfung text" in pdf[0].get_text() and "Prüfung stamp" in pdf[0].get_text()
        assert len(pdf[0].get_images()) >= 1
    assert inspect_pdf(source)["signature_validity"] == "not_verified"


def test_true_redaction_removes_text_objects_xml_metadata_attachments_and_forms():
    with fitz.open(stream=pdf_fixture(), filetype="pdf") as pdf:
        pdf.set_xml_metadata('<secret>UNZULAESSIGE_METADATEN_4711</secret>')
        pdf.embfile_add("geheim.txt", b"UNZULAESSIGE_ANLAGE_4711")
        original = pdf.tobytes()
    output = transform(original, "redact", {"regions": [{"page": 0, "rect": [20, 90, 350, 130]}]}, [], [])[0][2]
    with fitz.open(stream=output, filetype="pdf") as pdf:
        assert len(pdf) == 4 and pdf.embfile_count() == 0 and pdf.get_xml_metadata() == ""
        assert not any(value for key, value in pdf.metadata.items() if key not in {"format", "encryption"})
        assert all(page.get_text() == "" and list(page.widgets() or []) == [] for page in pdf)
        objects = '\n'.join(pdf.xref_object(index) for index in range(1, pdf.xref_length()))
        assert "4711" not in objects and "VERTRAULICH" not in objects
        pixel = pdf[0].get_pixmap().pixel(100, 110)
        assert all(channel < 10 for channel in pixel[:3])
    with fitz.open(stream=original, filetype="pdf") as pdf:
        assert "VERTRAULICH_4711" in pdf[0].get_text() and pdf.embfile_count() == 1


def test_crop_is_only_view_change_forms_keep_values_and_optimize_keeps_page_text():
    source = pdf_fixture()
    filled = transform(source, "forms", {"fields": [{"page": 0, "name": "Vermerk", "value": "Geprüft"}]}, [], [])[0][2]
    assert inspect_pdf(filled)["forms"][0]["value"] == "Geprüft"
    cropped = transform(source, "crop", {"regions": [{"page": 0, "rect": [10, 10, 500, 800]}]}, [], [])[0][2]
    with fitz.open(stream=cropped, filetype="pdf") as pdf:
        assert pdf[0].cropbox.width == 490 and pdf[0].cropbox.height == 790
    optimized = transform(source, "optimize", {}, [], [])[0][2]
    with fitz.open(stream=source, filetype="pdf") as first, fitz.open(stream=optimized, filetype="pdf") as second:
        assert [page.get_text() for page in first] == [page.get_text() for page in second]


def test_signature_detection_does_not_claim_cryptographic_validity_and_refuses_signature_form_edit():
    with fitz.open(stream=pdf_fixture(), filetype="pdf") as pdf:
        widget = fitz.Widget()
        widget.field_name = "Digitale Unterschrift"
        widget.field_type = fitz.PDF_WIDGET_TYPE_SIGNATURE
        widget.rect = fitz.Rect(20, 400, 300, 450)
        pdf[0].add_widget(widget)
        source = pdf.tobytes()
    inspection = inspect_pdf(source)
    assert len(inspection["signatures"]) == 1 and inspection["signatures"][0]["validity"] == "not_verified"
    with pytest.raises(HTTPException, match="Signaturfeld"):
        transform(source, "forms", {"fields": [{"page": 0, "name": "Digitale Unterschrift", "value": "fake"}]}, [], [])


def test_protected_corrupt_rotation_and_out_of_bounds_inputs_fail_without_output():
    with fitz.open(stream=pdf_fixture(), filetype="pdf") as pdf:
        protected = pdf.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="synthetic-owner", user_pw="synthetic-user")
    for content in (protected, b"%PDF-incomplete\n%%EOF"):
        with pytest.raises(HTTPException):
            inspect_pdf(content)
    with pytest.raises(HTTPException):
        validate_annotations(pdf_fixture(), [Annotation(kind="text", page=0, rect=(-1, 0, 50, 50))])
    with pytest.raises(HTTPException):
        validate_annotations(pdf_fixture(), [Annotation(kind="text", page=1, rect=(10, 10, 50, 50), rotation=0)])


def test_explicit_content_edit_removes_old_text_and_inserts_unicode_replacement():
    source = pdf_fixture()
    change = {"regions": [{"page": 0, "rect": [20, 90, 450, 140], "text": "Geprüfte Wärme 119,00 €"}], "explicit_content_mode": True}
    output = transform(source, "edit_content", change, [], [])[0][2]
    with fitz.open(stream=output, filetype="pdf") as pdf:
        text = pdf[0].get_text()
        assert "VERTRAULICH_4711" not in text and "Geprüfte Wärme 119,00 €" in text
    with pytest.raises(HTTPException):
        transform(source, "edit_content", change | {"explicit_content_mode": False}, [], [])


def test_isolated_worker_returns_real_inspection_and_edited_bytes():
    source = pdf_fixture()
    assert isolated(source, "inspect")["total_pages"] == 4
    output = isolated(source, "rotate", {"pages": [1], "degrees": 90})[0][2]
    with fitz.open(stream=output, filetype="pdf") as pdf:
        assert pdf[1].rotation == 180 and "SEITE_2_ORAKEL" in pdf[1].get_text()


def test_form_choice_checkbox_and_read_only_states_use_native_widget_contract():
    with fitz.open(stream=pdf_fixture(), filetype="pdf") as pdf:
        page = pdf[0]
        for number, (name, kind) in enumerate([
                ("Bestaetigt", fitz.PDF_WIDGET_TYPE_CHECKBOX),
                ("Auswahl", fitz.PDF_WIDGET_TYPE_COMBOBOX),
                ("Fest", fitz.PDF_WIDGET_TYPE_TEXT)]):
            widget = fitz.Widget()
            widget.field_name, widget.field_type = name, kind
            widget.rect = fitz.Rect(20, 400 + number * 40, 220, 425 + number * 40)
            if name == "Auswahl":
                widget.choice_values = ["A", "B"]
                widget.field_value = "A"
            if name == "Fest":
                widget.field_flags = fitz.PDF_FIELD_IS_READ_ONLY
                widget.field_value = "Unveraendert"
            page.add_widget(widget)
        original = pdf.tobytes()
    inspection = inspect_pdf(original)
    assert next(item for item in inspection["forms"] if item["name"] == "Fest")["read_only"]
    output = transform(original, "forms", {"fields": [
        {"page": 0, "name": "Bestaetigt", "value": True},
        {"page": 0, "name": "Auswahl", "value": "B"}]}, [], [])[0][2]
    forms = {item["name"]: item for item in inspect_pdf(output)["forms"]}
    assert forms["Bestaetigt"]["value"] != "Off" and forms["Auswahl"]["value"] == "B"
    assert forms["Fest"]["value"] == "Unveraendert"
    for name, value in [("Fest", "Manipuliert"), ("Auswahl", "Kein Auswahlwert"), ("Bestaetigt", "falsch")]:
        with pytest.raises(HTTPException):
            transform(original, "forms", {"fields": [{"page": 0, "name": name, "value": value}]}, [], [])


@pytest.mark.parametrize("pages", [[], [0, 0], [True], [99]])
def test_rotation_rejects_empty_duplicate_boolean_and_missing_pages(pages):
    with pytest.raises(HTTPException):
        transform(pdf_fixture(), "rotate", {"pages": pages, "degrees": 90}, [], [])
