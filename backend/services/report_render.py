"""Readable, complete PDFs from the same finance payload shown by the API."""

from decimal import Decimal
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import CondPageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..domain.clock import local_today
from .housing_confirmation_render import _fonts

REPORT_TITLES = {
    "cash-v2": "Zahlungsübersicht",
    "performance-period-v2": "Periodenergebnis",
    "liquidity-v2": "Liquiditätsplanung",
    "summary": "Bestands- und Finanzübersicht",
    "finance": "Finanzen nach Kategorien",
    "occupancy": "Belegung",
    "cashflow": "Zahlungsübersicht",
    "receivables-aging": "Forderungsalter",
    "period-result": "Periodenergebnis",
}
_LABELS = {
    "as_of": "Stichtag",
    "balance": "Kontostand", "opening_balance": "Anfangssaldo", "closing_balance": "Endsaldo",
    "totals": "Gesamtwerte", "properties": "Immobilien", "units": "Einheiten", "contracts": "Verträge",
    "finance": "Finanzen", "bookingsTotal": "Buchungen gesamt", "invoicesTotal": "Rechnungen gesamt",
    "openReceivables": "Offene Forderungen", "overdueReceivables": "Überfällige Forderungen",
    "openCredits": "Offene Mieterguthaben", "maintenance": "Instandhaltung", "openCases": "Offene Fälle",
    "totalsByCategory": "Kategorien", "categoryName": "Kategorie", "categoryType": "Art",
    "total": "Betrag", "uncategorizedTotal": "Ohne Kategorie", "totalUnits": "Einheiten gesamt",
    "rentedUnits": "Vermietete Einheiten", "occupancyRate": "Belegungsquote",
    "openTotal": "Offene Forderungen gesamt", "buckets": "Fälligkeit",
    "current": "Noch nicht überfällig", "days1to30": "1 bis 30 Tage", "days31to60": "31 bis 60 Tage",
    "days61to90": "61 bis 90 Tage", "days90plus": "Mehr als 90 Tage",
    "incomeTotal": "Einnahmen gesamt", "expenseTotal": "Ausgaben gesamt", "netTotal": "Zahlungssaldo",
    "monthly": "Monatsverlauf", "month": "Monat", "income": "Einnahmen", "expense": "Ausgaben",
    "net": "Saldo", "rent_due": "Sollmiete", "other_income": "Sonstige Erträge", "costs": "Kosten",
    "result": "Ergebnis", "unassigned_income": "Eingänge ohne Zuordnung",
}
_COUNTS = {"properties", "units", "contracts", "openCases", "totalUnits", "rentedUnits"}
_TEXT = {"month", "categoryName", "categoryType"}


def _value(key: str, value: Any, currency: str = "EUR") -> str:
    if value is None:
        return "-"
    if key == "categoryType":
        return {"income": "Einnahme", "expense": "Ausgabe"}.get(str(value), str(value))
    if key == "occupancyRate":
        return f"{Decimal(str(value)) * 100:.1f}".replace(".", ",") + " %"
    if key not in _COUNTS | _TEXT and isinstance(value, (int, float, Decimal)):
        return format(Decimal(str(value)), ",.2f").replace(",", "_").replace(".", ",").replace("_", ".") + " " + currency
    return str(value)


def render_report_pdf(report_name: str, data: dict, *, selection: dict | None = None, currency: str = "EUR") -> bytes:
    regular, bold = _fonts()
    ink, muted, accent = (colors.HexColor(c) for c in ("#182a30", "#586a70", "#176b63"))
    body = ParagraphStyle("ReportBody", fontName=regular, fontSize=9, leading=13, textColor=ink)
    heading = ParagraphStyle("ReportHeading", parent=body, fontName=bold, fontSize=11, spaceBefore=12,
                             spaceAfter=7)
    title = ParagraphStyle("ReportTitle", parent=heading, fontSize=21, leading=26, textColor=accent)
    note = ParagraphStyle("ReportNote", parent=body, fontSize=8, leading=12, textColor=muted, spaceAfter=5)
    width = A4[0] - 88
    flow: list[Any] = []

    def p(text: Any, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)

    def table(rows: list, widths: list[float], *, header: bool = False) -> None:
        if not rows:
            flow.append(p("Keine Einträge im ausgewählten Bestand.", note))
            return
        item = Table([[p(v) for v in row] for row in rows], colWidths=widths,
                     repeatRows=1 if header else 0, hAlign="LEFT", splitInRow=1)
        style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#dce4e0")),
        ]
        if header:
            style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2f1ed")))
        item.setStyle(TableStyle(style))
        flow.append(item)

    flow.extend([p("ImmoManager Pro", note), p(REPORT_TITLES[report_name], title),
                 p(f"Erstellt am {local_today():%d.%m.%Y}", note)])
    flt = data.get("filters", {})
    start, end = flt.get("date_from"), flt.get("date_to")
    if report_name == "occupancy":
        flow.append(p(f"Belegung zum {local_today():%d.%m.%Y}", note))
    else:
        flow.append(p(f"Zeitraum: {start or 'ohne Anfangsgrenze'} bis {end or 'ohne Endgrenze'}", note))
    for key, label in (("portfolio_id", "Portfolio"), ("property_id", "Immobilie"), ("unit_id", "Einheit")):
        if flt.get(key):
            flow.append(p(f"{label}: {(selection or {}).get(key, 'Ausgewählter Bestand')}", note))
    if not any(flt.get(k) for k in ("portfolio_id", "property_id", "unit_id")):
        flow.append(p("Bestand: alle für dieses Benutzerkonto sichtbaren Objekte", note))
    if report_name == "period-result":
        flow.append(p("Ganze Kalendermonate: Sollmiete plus sonstige Erträge abzüglich gebuchter Kosten. "
                      "Kosten nach Buchungsdatum; keine vollständige steuerliche Gewinnermittlung.", note))
    elif report_name == "cashflow":
        flow.append(p("Tatsächliche Buchungen nach Buchungsdatum. Stornos mindern die ursprüngliche Seite.", note))
    flow.append(Spacer(1, 8))

    def section(obj: dict) -> None:
        scalars = [(k, v) for k, v in obj.items() if k not in {"filters", "basis", "categoryId"}
                   and not isinstance(v, (dict, list))]
        if scalars:
            table([[_LABELS.get(k, k), _value(k, v, currency)] for k, v in scalars], [width * .65, width * .35])
        for key, value in obj.items():
            if key in {"filters", "basis"} or not isinstance(value, (dict, list)):
                continue
            flow.extend([CondPageBreak(80), p(_LABELS.get(key, key), heading)])
            if isinstance(value, dict):
                section(value)
            else:
                columns = [k for row in value for k in row if k != "categoryId"]
                columns = list(dict.fromkeys(columns))
                rows = [[_LABELS.get(k, k) for k in columns]] if columns else []
                rows.extend([_value(k, row.get(k), currency) for k in columns] for row in value)
                widths = ([width * .6, width * .2, width * .2] if columns == ["categoryName", "categoryType", "total"]
                          else [width / len(columns)] * len(columns) if columns else [])
                table(rows, widths, header=True)

    section(data)
    buffer = BytesIO()

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(regular, 8)
        canvas.setFillColor(muted)
        canvas.drawString(44, 27, "ImmoManager Pro | " + REPORT_TITLES[report_name])
        canvas.drawRightString(A4[0] - 44, 27, f"Seite {doc.page}")
        canvas.restoreState()

    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=44, rightMargin=44, topMargin=36, bottomMargin=45,
                      title=REPORT_TITLES[report_name], author="ImmoManager Pro").build(
                          flow, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
