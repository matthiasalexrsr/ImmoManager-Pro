"""Check real PDF text placement, not just the existence of its bytes."""

from datetime import date
from io import BytesIO

import pdfplumber
from reportlab.pdfbase import pdfmetrics

from backend.services.housing_confirmation_render import render_pdf
from backend.services.housing_confirmation_types import CertificateData


def certificate(residents):
    data = CertificateData(
        housing_provider_name="Verwaltung Muster GmbH",
        housing_provider_address="Lange Straße 5\n66111 Saarbrücken",
        owner_same_as_provider=False,
        owner_name="Eigentümerin Élodie Beispiel",
        move_in_date=date(2026, 9, 30),
        issue_date=date(2026, 10, 3),
        apartment_address="Musterstraße 17\n66111 Saarbrücken",
        apartment_label="Wohnung A, 2. Obergeschoss links",
        issuer_name="Beauftragte Person",
        issuer_role="authorized_person",
        residents=residents,
    )
    return render_pdf({"data": data.model_dump(mode="json"),
                       "source": {"contract": {"contract_number": "QA-2026-0001"}}})


def test_names_are_in_name_column_and_signature_has_no_literal_markup():
    names = ["Anna Beispiel", "Zoë Beispiel", "Łukasz Beispiel"]
    with pdfplumber.open(BytesIO(certificate(names))) as pdf:
        assert len(pdf.pages) == 1
        page = pdf.pages[0]
        text = page.extract_text()
        assert "<br/>" not in text
        assert "Tatsächliche Unterschrift" in text
        assert "30.09.2026" in text and "03.10.2026" in text
        assert "Wohnungsbezeichnung" in text
        for name in names:
            assert name in text
        # Names must occupy the wide second column, rather than wrapping
        # vertically inside the narrow ordinal-number cell.
        words = page.extract_words()
        for first_name in ("Anna", "Zoë", "Łukasz"):
            found = [word for word in words if word["text"] == first_name]
            assert len(found) == 1
            assert found[0]["x0"] > 95


def test_long_resident_list_has_readable_repeated_headings_and_complete_names():
    names = [f"Person {index:02d} – Zoë Łukasz Beispiel mit langem Familiennamen"
             for index in range(1, 46)]
    with pdfplumber.open(BytesIO(certificate(names))) as pdf:
        assert 2 <= len(pdf.pages) <= 4
        text = "\n".join(page.extract_text() for page in pdf.pages)
        for name in names:
            assert name in text
        assert "Tatsächliche Unterschrift" in text
        for number, page in enumerate(pdf.pages, 1):
            assert f"Seite {number}" in page.extract_text()
            if any(name in page.extract_text() for name in names):
                assert "Vollständiger Name" in page.extract_text()
            if "Ausstellende Person" in page.extract_text():
                assert "Tatsächliche Unterschrift" in page.extract_text()


def test_greek_cyrillic_and_latin_names_have_real_embedded_glyphs():
    names = ["Иван Петров", "Μαρία Παπαδοπούλου", "Zoë Łukasz Élodie"]
    with pdfplumber.open(BytesIO(certificate(names))) as pdf:
        text = pdf.pages[0].extract_text()
        for name in names:
            assert name in text
        chars = pdf.pages[0].chars
        for char in set("".join(names)) - {" "}:
            occurrences = [value for value in chars if value["text"] == char]
            assert occurrences
            # PDF text extraction alone also succeeds for Vera's invisible
            # .notdef boxes. Require the embedded font to have actual glyphs.
            for value in occurrences:
                assert "NotoSans" in value["fontname"]
                assert pdfmetrics.getFont("ImmoHousingNoto").face.charToGlyph.get(ord(char), 0) > 0
