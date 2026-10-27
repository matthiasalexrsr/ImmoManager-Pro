"""Render bounded plain-text preview blocks without interpreting user markup."""

from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate


def build_preview_pdf(blocks: object) -> bytes:
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= 1000:
        raise ValueError("Die Vertragsvorschau enthält keine gültigen Textblöcke.")
    total = 0
    for block in blocks:
        if not isinstance(block, dict) or block.get("kind") not in ("title", "heading", "paragraph"):
            raise ValueError("Ungültiger Typ in der Vertragsvorschau.")
        text = block.get("text")
        if not isinstance(text, str) or len(text) > 10000:
            raise ValueError("Ein Textblock ist ungültig oder zu lang.")
        total += len(text)
    if total > 200000:
        raise ValueError("Die Vertragsvorschau ist zu lang.")
    try:
        from backend.services.housing_confirmation_render import _fonts
        regular, bold = _fonts()
    except ImportError:
        regular, bold = "Helvetica", "Helvetica-Bold"
    styles = {
        "paragraph": ParagraphStyle("PreviewBody", fontName=regular, fontSize=10, leading=14, spaceAfter=7),
        "heading": ParagraphStyle("PreviewHeading", fontName=bold, fontSize=12, leading=16,
                                  spaceBefore=10, spaceAfter=7, keepWithNext=True),
        "title": ParagraphStyle("PreviewTitle", fontName=bold, fontSize=18, leading=22, spaceAfter=14),
    }
    stream = BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=A4, leftMargin=50, rightMargin=50, topMargin=50, bottomMargin=50)
    story = [Paragraph(escape(block["text"]).replace("\n", "<br/>"), styles[block["kind"]]) for block in blocks]
    doc.build(story)
    return stream.getvalue()
