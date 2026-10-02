"""Print-oriented visual system for the residential contract PDF.

The design uses common German legal-form conventions: dense typography, restrained
rules, clear section numbering, warm yellow accents, and explicit signature areas.
It intentionally contains no third-party branding, logos, or contract wording.
"""

from __future__ import annotations

from html import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

INK = colors.HexColor("#202020")
MUTED = colors.HexColor("#626262")
RULE = colors.HexColor("#8A8A82")
RULE_LIGHT = colors.HexColor("#C9C7BC")
ACCENT = colors.HexColor("#E4CF69")
ACCENT_LIGHT = colors.HexColor("#F5EDBE")
ACCENT_PALE = colors.HexColor("#FBF8E8")
PAPER = colors.white

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = 17.5 * mm
RIGHT_MARGIN = 17.5 * mm
TOP_MARGIN = 23 * mm
BOTTOM_MARGIN = 17 * mm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN


def contract_styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    base = ParagraphStyle(
        "contract_base",
        parent=sample["Normal"],
        fontName="Helvetica",
        fontSize=9.25,
        leading=12.2,
        textColor=INK,
        spaceAfter=3.5,
        allowWidows=0,
        allowOrphans=0,
    )
    return {
        "base": base,
        "body": ParagraphStyle(
            "contract_body", parent=base, alignment=TA_JUSTIFY,
        ),
        "small": ParagraphStyle(
            "contract_small", parent=base, fontSize=7.7, leading=9.5,
            textColor=MUTED, spaceAfter=2,
        ),
        "label": ParagraphStyle(
            "contract_label", parent=base, fontName="Helvetica-Bold",
            fontSize=8, leading=9.5, textColor=MUTED, spaceAfter=1,
        ),
        "title": ParagraphStyle(
            "contract_title", parent=base, fontName="Helvetica-Bold",
            fontSize=18, leading=20, alignment=TA_LEFT, spaceAfter=0,
        ),
        "subtitle": ParagraphStyle(
            "contract_subtitle", parent=base, fontName="Helvetica-Bold",
            fontSize=8.3, leading=10, textColor=MUTED, alignment=TA_LEFT,
            spaceAfter=0,
        ),
        "section": ParagraphStyle(
            "contract_section", parent=base, fontName="Helvetica-Bold",
            fontSize=10.4, leading=12.2, alignment=TA_LEFT, spaceAfter=0,
        ),
        "table_header": ParagraphStyle(
            "contract_table_header", parent=base, fontName="Helvetica-Bold",
            fontSize=8.4, leading=10, spaceAfter=0,
        ),
        "signature": ParagraphStyle(
            "contract_signature", parent=base, fontSize=8.3, leading=10.5,
            alignment=TA_CENTER, spaceAfter=0,
        ),
    }


def title_block(styles: dict[str, ParagraphStyle], width: float = CONTENT_WIDTH,
                *, title: str = "WOHNRAUM-MIETVERTRAG", subtitle: str = "VERTRAGSDOKUMENT") -> Table:
    """Compact legal-form masthead with a warm accent, no external branding."""
    table = Table(
        [[
            Paragraph(escape(title, quote=False), styles["title"]),
            Paragraph(escape(subtitle, quote=False), styles["subtitle"]),
        ]],
        colWidths=[width - 41 * mm, 41 * mm],
    )
    table.keepWithNext = True
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ACCENT_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.8, INK),
        ("LINEBEFORE", (1, 0), (1, 0), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (0, 0), 9),
        ("RIGHTPADDING", (0, 0), (0, 0), 8),
        ("LEFTPADDING", (1, 0), (1, 0), 7),
        ("RIGHTPADDING", (1, 0), (1, 0), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def section_heading(
    label: str,
    styles: dict[str, ParagraphStyle],
    width: float = CONTENT_WIDTH,
) -> Table:
    """Section bar emphasizing the paragraph number without a heavy grey box."""
    table = Table(
        [[Paragraph(escape(label, quote=False), styles["section"])]],
        colWidths=[width],
    )
    table.keepWithNext = True
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ACCENT_PALE),
        ("LINEBEFORE", (0, 0), (0, 0), 4.2, ACCENT),
        ("LINEBELOW", (0, 0), (-1, -1), 0.35, RULE_LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ]))
    return table


def party_table_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.65, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, RULE_LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6.5),
        ("TOPPADDING", (0, 0), (-1, -1), 5.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ])


def data_table_style(last_row: int | None = None) -> TableStyle:
    commands: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT_LIGHT),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.6, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, RULE_LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5.5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if last_row is not None and last_row > 0:
        commands.extend([
            ("LINEABOVE", (0, last_row), (-1, last_row), 0.7, INK),
            ("FONTNAME", (0, last_row), (-1, last_row), "Helvetica-Bold"),
            ("BACKGROUND", (0, last_row), (-1, last_row), ACCENT_PALE),
        ])
    return TableStyle(commands)


def signature_table_style() -> TableStyle:
    return TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.55, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, RULE_LIGHT),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ])


def decorate_page(canvas, doc_obj, *, title: str = "WOHNRAUM-MIETVERTRAG",
                  footer_left: str = "ImmoManager Pro · Vertragsdokument",
                  footer_right: str = "Ausfertigung für die Vertragsparteien") -> None:
    """Quiet header/footer: form identity, accent rule, page number."""
    canvas.saveState()
    left = doc_obj.leftMargin
    right = PAGE_WIDTH - doc_obj.rightMargin

    canvas.setFillColor(ACCENT)
    canvas.rect(left, PAGE_HEIGHT - 15.2 * mm, 20 * mm, 1.9 * mm, fill=1, stroke=0)
    canvas.setStrokeColor(RULE_LIGHT)
    canvas.setLineWidth(0.45)
    canvas.line(left + 22 * mm, PAGE_HEIGHT - 14.3 * mm, right, PAGE_HEIGHT - 14.3 * mm)

    canvas.setFillColor(INK)
    canvas.setFont("Helvetica-Bold", 7.8)
    canvas.drawString(left, PAGE_HEIGHT - 11.2 * mm, title)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawRightString(right, PAGE_HEIGHT - 11.2 * mm, f"Seite {doc_obj.page}")

    canvas.setStrokeColor(RULE_LIGHT)
    canvas.line(left, 12.5 * mm, right, 12.5 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 6.8)
    canvas.drawString(left, 8.8 * mm, footer_left)
    canvas.drawRightString(right, 8.8 * mm, footer_right)
    canvas.restoreState()
