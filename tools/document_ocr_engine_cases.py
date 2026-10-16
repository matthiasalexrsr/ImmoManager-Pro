"""Explicit local OCR gate. Requires configured German/English traineddata.

No skip: missing local language data is a failed optional-component proof.
"""
import hashlib

from backend.services.document_pdf import engine, isolated


def test_pixel_only_scan_gets_a_real_searchable_text_layer_in_isolated_worker():
    fitz = engine()
    with fitz.open() as rendered:
        page = rendered.new_page(width=595, height=300)
        page.insert_text((35, 85), "MIETVERWALTUNG", fontsize=28)
        page.insert_text((35, 140), "RECHNUNG 119,00 EURO", fontsize=24)
        pixels = page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
        with fitz.open() as scan:
            page = scan.new_page(width=595, height=300)
            page.insert_image(page.rect, stream=pixels)
            original = scan.tobytes()
    digest = hashlib.sha256(original).hexdigest()
    with fitz.open(stream=original, filetype="pdf") as source:
        assert source[0].get_text() == ""
    output = isolated(original, "ocr")[0][2]
    with fitz.open(stream=output, filetype="pdf") as result:
        text = result[0].get_text()
        assert "MIETVERWALTUNG" in text and "119,00" in text and "EURO" in text
    assert hashlib.sha256(original).hexdigest() == digest
