"""Independent required native gate; the standard no-tools matrix may skip it."""
import hashlib
import io
import os
import shutil
from pathlib import Path

import pytest

from backend.services.ocr_service import OCRLimits, extract_text_with_details

pytestmark = pytest.mark.skipif(os.environ.get("OCR_NATIVE_REQUIRED") != "1",
                              reason="Executed by the required Linux native OCR job")


def test_required_tools_languages_raster_pdf_and_original_sha256(tmp_path):
    import reportlab
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    tools = {name: shutil.which(name) for name in ("pdfinfo", "pdftotext", "pdftoppm", "tesseract")}
    assert all(tools.values()), "Required native OCR tools missing"
    image = Image.new("RGB", (1400, 420), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"), 62)
    draw.text((35, 90), "NATIVE PDF ORIGINAL 161803", fill="black", font=font)
    draw.text((35, 220), "Gesamtbetrag: 1.234,56", fill="black", font=font)
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(700, 210))
    pdf.drawImage(ImageReader(image), 0, 0, width=700, height=210)
    pdf.showPage()
    pdf.save()
    source = output.getvalue()
    original = tmp_path / "original.pdf"
    original.write_bytes(source)
    before = hashlib.sha256(source).hexdigest()
    result = extract_text_with_details(source, "pdf", limits=OCRLimits(
        languages="deu+eng", pdfinfo_path=tools["pdfinfo"], pdftotext_path=tools["pdftotext"],
        pdftoppm_path=tools["pdftoppm"], tesseract_path=tools["tesseract"], timeout_seconds=45))
    assert result.embedded_text_pages == 0 and result.ocr_pages == 1
    assert "161803" in result.text and "1.234,56" in result.text
    assert hashlib.sha256(source).hexdigest() == before
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before
