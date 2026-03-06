from backend.services.ocr_service import _extract_invoice_fields, extract_text_from_bytes


def test_extract_invoice_fields_parses_values():
    text = "Rechnungsnr: RE-9988\nRechnungsdatum: 01.12.2025\nGesamtbetrag: 1.234,56"
    fields = _extract_invoice_fields(text)
    assert fields["invoice_number"] == "RE-9988"
    assert fields["invoice_date"] == "01.12.2025"
    assert fields["total_amount"] == 1234.56


def test_extract_text_from_bytes_for_unsupported_type_returns_none():
    assert extract_text_from_bytes(b"abc", "docx") is None
