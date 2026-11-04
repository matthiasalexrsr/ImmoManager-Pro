"""Chunked search must keep phrases, mixed-page coverage and explicit failure states."""

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from test_document_text import _index, _upload, case  # noqa: F401

from backend.dependencies import store
from backend.services import document_text
from backend.services.document_text_reader import Budget, normalize, normalize_part, read_part


@pytest.mark.parametrize("separator", ["  ", "\t\t", "\r\n", " \r\n ", "\n\n\n"])
def test_plain_chunk_boundary_matches_whole_file_normalization(case, separator):  # noqa: F811
    content = "\n\n" + "x" * (document_text.MAX_CHARACTERS - 3) + separator + "Zielwert\r\n"
    document = _upload(case, "whitespace.txt", content.encode(), "Suchphrase über Abschnittsgrenze")
    _index()
    row = document_text.get(store, document["id"])
    assert row is not None and row.complete and row.warning is None
    assert row.text == normalize(content)
    expected = normalize("x" + separator + "Zielwert")
    assert document_text.search(store, expected)["total"] == 1


def test_stream_normalization_keeps_crlf_and_arbitrary_whitespace_boundaries():
    original = "Start \r\n  Mitte\t\t Ende\r\n\n\nNachher\r"
    for chunk in range(1, 12):
        state: dict = {}
        pieces = []
        for start in range(0, len(original), chunk):
            end = min(len(original), start + chunk)
            part, state = normalize_part(original[start:end], state, end == len(original))
            pieces.append(part)
        assert "".join(pieces) == normalize(original, trim=False)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_bom_text_is_read_without_silent_garbled_characters(case, encoding):  # noqa: F811
    document = _upload(case, "unicode.txt", "Mietkonto Straßenprüfung".encode(encoding), "Unicode")
    _index()
    assert document_text.search(store, "Straßenprüfung")["total"] == 1
    row = document_text.get(store, document["id"])
    assert row is not None and row.complete and row.warning is None


def test_odt_tail_and_styled_word_remain_searchable(case):  # noqa: F811
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "content.xml",
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text><text:p>Grenz<text:span>mark</text:span>ierung und <text:a>Verweis</text:a> Endefund</text:p></office:text></office:body></office:document-content>',
        )
    document = _upload(case, "styled.odt", output.getvalue(), "Formatierter ODT-Text")
    _index()
    row = document_text.get(store, document["id"])
    assert row is not None and row.complete and row.warning is None
    for word in ["Grenzmarkierung", "Verweis Endefund"]:
        assert document_text.search(store, word)["total"] == 1


def mixed_pdf():
    output = BytesIO()
    pdf = canvas.Canvas(output)
    pdf.drawString(50, 750, "Eine normale lesbare Textebene auf Seite eins.")
    pdf.showPage()
    image = Image.new("RGB", (900, 200), "white")
    ImageDraw.Draw(image).text((40, 70), "RASTERFUND", fill="black", font_size=56)
    pdf.drawImage(ImageReader(image), 50, 500, width=450, height=100)
    pdf.showPage()
    pdf.save()
    return output.getvalue()


def test_mixed_pdf_marks_missing_page_ocr_instead_of_claiming_full_text(case, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PATH", str(Path(__file__).parent / "no-ocr-binary"))
    document = _upload(case, "mixed.pdf", mixed_pdf(), "Gemischtes PDF")
    _index()
    row = document_text.get(store, document["id"])
    assert row is not None and row.complete and row.warning and "Texterkennung" in row.warning
    assert "normale lesbare" in row.text and "RASTERFUND" not in row.text
    index = document_text.status(store)
    assert index["partial"] == index["limited"] == 1
    assert document_text.search(store, "RASTERFUND")["index"]["partial"] == 1


def test_zip_expansion_budget_produces_a_visible_read_limit(case, monkeypatch):  # noqa: F811
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "<document><p><t>" + "A" * 10000 + "</t></p></document>")
    assert len(output.getvalue()) < 1024
    monkeypatch.setattr(document_text, "MAX_BYTES", 1024)
    document = _upload(case, "expanded.docx", output.getvalue(), "Komprimierter Inhalt")
    _index()
    row = document_text.get(store, document["id"])
    assert row is not None and row.complete and row.warning
    assert document_text.status(store)["limited"] == 1


def test_invalid_negative_shared_string_reference_is_not_accepted_as_a_real_cell():
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", "<sst><si><t>Falscher Treffer</t></si></sst>")
        archive.writestr("xl/worksheets/sheet1.xml", '<worksheet><c t="s"><v>-1</v></c></worksheet>')
    result = read_part(output.getvalue(), "invalid.xlsx", {}, Budget())
    assert result.warning and "Falscher Treffer" not in result.text
