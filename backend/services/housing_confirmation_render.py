"""Deterministic local PDF renderer for Wohnungsgeberbestätigung facts."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
from threading import Lock
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_FONT_LOCK = Lock()
_REGULAR = "ImmoHousingNoto"
_BOLD = "ImmoHousingNotoBold"
_INK = colors.HexColor("#202124")
_MUTED = colors.HexColor("#666A70")
_RULE = colors.HexColor("#C8CBD0")
_FILL = colors.HexColor("#F2F3F4")


def _fonts() -> tuple[str, str]:
    with _FONT_LOCK:
        if _REGULAR not in pdfmetrics.getRegisteredFontNames():
            # Ship the same licensed Unicode face on Windows and Linux;
            # ReportLab's bundled Vera omits Greek and Cyrillic glyphs.
            font_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
            pdfmetrics.registerFont(TTFont(_REGULAR, str(font_dir / "NotoSans-Regular.ttf")))
            pdfmetrics.registerFont(TTFont(_BOLD, str(font_dir / "NotoSans-Bold.ttf")))
    return _REGULAR, _BOLD


def _styles():
    regular, bold = _fonts()
    return {
        "body": ParagraphStyle(
            "HousingBody",
            fontName=regular,
            fontSize=9.4,
            leading=12.6,
            textColor=_INK,
            spaceAfter=4,
        ),
        "title": ParagraphStyle(
            "HousingTitle",
            fontName=bold,
            fontSize=17,
            leading=20,
            alignment=TA_CENTER,
            textColor=_INK,
            spaceAfter=7,
        ),
        "subtitle": ParagraphStyle(
            "HousingSubtitle",
            fontName=regular,
            fontSize=8,
            leading=10,
            alignment=TA_CENTER,
            textColor=_MUTED,
            spaceAfter=12,
        ),
        "section": ParagraphStyle(
            "HousingSection",
            fontName=bold,
            fontSize=10.5,
            leading=13,
            textColor=_INK,
            spaceAfter=0,
        ),
        "table": ParagraphStyle(
            "HousingTable",
            fontName=regular,
            fontSize=9,
            leading=11.5,
            textColor=_INK,
            alignment=TA_LEFT,
        ),
        "table_bold": ParagraphStyle(
            "HousingTableBold",
            fontName=bold,
            fontSize=8.8,
            leading=11,
            textColor=_INK,
        ),
        "small": ParagraphStyle(
            "HousingSmall",
            fontName=regular,
            fontSize=7.5,
            leading=9.5,
            textColor=_MUTED,
        ),
        "signature": ParagraphStyle(
            "HousingSignature",
            fontName=regular,
            fontSize=8.5,
            leading=11,
            alignment=TA_CENTER,
            textColor=_INK,
        ),
    }


def _p(value: str, style) -> Paragraph:
    return Paragraph(escape(value).replace("\n", "<br/>"), style)


def _section(title: str, styles, width: float) -> Table:
    table = Table([[_p(title, styles["section"])]], colWidths=[width])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _FILL),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, _RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _facts(rows, styles, width: float) -> Table:
    table = Table(
        [
            [_p(label, styles["table_bold"]), _p(value, styles["table"])]
            for label, value in rows
        ],
        colWidths=[52 * mm, width - 52 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.45, _RULE),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, _RULE),
                ("BACKGROUND", (0, 0), (0, -1), _FILL),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def render_pdf(review: dict) -> bytes:
    """Render only reviewed input facts; no signature/delivery claim is added."""
    data = review["data"]
    source = review["source"]
    output = BytesIO()
    styles = _styles()
    width = A4[0] - 36 * mm

    def display_date(value: str) -> str:
        return date.fromisoformat(value).strftime("%d.%m.%Y")

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(_RULE)
        canvas.setLineWidth(0.4)
        canvas.line(doc.leftMargin, 14 * mm, A4[0] - doc.rightMargin, 14 * mm)
        canvas.setFillColor(_MUTED)
        canvas.setFont(_REGULAR, 7.3)
        canvas.drawString(doc.leftMargin, 9.5 * mm, f"Vertrag {source['contract']['contract_number']}")
        canvas.drawRightString(A4[0] - doc.rightMargin, 9.5 * mm, f"Seite {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        invariant=1,
        title="Wohnungsgeberbestätigung",
        author="ImmoManager",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
    )
    story = [
        _p("WOHNUNGSGEBERBESTÄTIGUNG", styles["title"]),
        _p("Lokale Ausfertigung zur manuellen Unterzeichnung", styles["subtitle"]),
        _section("Wohnungsgeber", styles, width),
        Spacer(1, 4),
        _facts(
            [
                ("Name", data["housing_provider_name"]),
                ("Anschrift", data["housing_provider_address"]),
            ],
            styles,
            width,
        ),
        Spacer(1, 9),
        _section("Eigentümer", styles, width),
        Spacer(1, 4),
        _facts(
            [
                (
                    "Eigentümer",
                    "identisch mit Wohnungsgeber"
                    if data["owner_same_as_provider"]
                    else data["owner_name"],
                )
            ],
            styles,
            width,
        ),
        Spacer(1, 9),
        _section("Wohnung und Einzug", styles, width),
        Spacer(1, 4),
        _facts(
            [
                ("Wohnungsanschrift", data["apartment_address"]),
                ("Wohnungsbezeichnung", data["apartment_label"] or "—"),
                ("Tatsächlicher Einzug", display_date(data["move_in_date"])),
            ],
            styles,
            width,
        ),
        Spacer(1, 9),
        _section("Einziehende Personen", styles, width),
        Spacer(1, 4),
    ]

    residents = [
        [_p("Nr.", styles["table_bold"]), _p("Vollständiger Name", styles["table_bold"])]
    ]
    residents.extend(
        [_p(str(index), styles["table"]), _p(name, styles["table"])]
        for index, name in enumerate(data["residents"], 1)
    )
    residents_table = Table(
        residents,
        colWidths=[16 * mm, width - 16 * mm],
        repeatRows=1,
    )
    residents_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _FILL),
                ("BOX", (0, 0), (-1, -1), 0.45, _RULE),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, _RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.extend(
        [
            residents_table,
            Spacer(1, 10),
            KeepTogether(
                [
                    _section("Ausstellung", styles, width),
                    Spacer(1, 4),
                    _facts(
                        [
                            ("Ausstellungsdatum", display_date(data["issue_date"])),
                            ("Ausstellende Person", data["issuer_name"]),
                            (
                                "Rolle",
                                "Wohnungsgeber"
                                if data["issuer_role"] == "housing_provider"
                                else "beauftragte Person",
                            ),
                        ],
                        styles,
                        width,
                    ),
                    Spacer(1, 13),
                    _p(
                        "Ort: ________________________________    "
                        f"Datum: {display_date(data['issue_date'])}",
                        styles["body"],
                    ),
                    Spacer(1, 16),
                    Table(
                        [[Paragraph("________________________________________<br/>Tatsächliche Unterschrift", styles["signature"])]],
                        colWidths=[85 * mm],
                        hAlign="LEFT",
                    ),
                    Spacer(1, 8),
                    _p(
                        "Dieses lokal erzeugte Dokument enthält keine elektronische Unterschrift "
                        "und keine Aussage über eine Übermittlung an eine Meldebehörde.",
                        styles["small"],
                    ),
                ]
            ),
        ]
    )
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output.getvalue()
