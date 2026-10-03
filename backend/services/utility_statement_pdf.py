"""Deterministic checked PDF derivation; this renderer archives and sends nothing."""

import hashlib
import json
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from threading import Lock
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .utility_statement_original_source import PROFILE, UNPROVED, UtilityOriginalIntegrityError, validate_source

_FONT_LOCK = Lock()
REGULAR, BOLD = "ImmoUtilityNoto", "ImmoUtilityNotoBold"
INK, MUTED, FILL = (colors.HexColor(value) for value in ("#202124", "#62676D", "#F0F2F4"))
WIDTH = A4[0] - 36 * mm


def _fonts():
    with _FONT_LOCK:
        if REGULAR not in pdfmetrics.getRegisteredFontNames():
            root = Path(__file__).resolve().parent.parent / "assets" / "fonts"
            pdfmetrics.registerFont(TTFont(REGULAR, str(root / "NotoSans-Regular.ttf")))
            pdfmetrics.registerFont(TTFont(BOLD, str(root / "NotoSans-Bold.ttf")))


def _p(value, style):
    return Paragraph(escape(str(value)).replace("\n", "<br/>"), style)


def _money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
            raise ValueError("nonfinite or noncent money")
    except (ValueError, TypeError, InvalidOperation) as error:
        raise UtilityOriginalIntegrityError("Der Originalbetrag ist nicht endlich und centgenau.") from error
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _table(rows, widths, *, repeat=0, header=False):
    table = Table(rows, colWidths=widths, repeatRows=repeat, hAlign="LEFT")
    commands = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#D7DBDF"))]
    if header:
        commands += [("BACKGROUND", (0, 0), (-1, 0), FILL), ("LINEBELOW", (0, 0), (-1, 0), 0.6, MUTED)]
    table.setStyle(TableStyle(commands))
    return table


def render_pdf(value):
    source = validate_source(value)
    _fonts()
    body = ParagraphStyle("UtilityBody", fontName=REGULAR, fontSize=9, leading=12, textColor=INK, spaceAfter=5)
    title = ParagraphStyle("UtilityTitle", parent=body, fontName=BOLD, fontSize=18, leading=23, spaceAfter=9)
    heading = ParagraphStyle("UtilityHeading", parent=body, fontName=BOLD, fontSize=11, leading=14, spaceBefore=13, spaceAfter=7)
    small = ParagraphStyle("UtilitySmall", parent=body, fontSize=7.4, leading=10, textColor=MUTED)
    amount_style = ParagraphStyle("UtilityAmount", parent=body, alignment=2)
    statement, period = source.statement_original, source.period_context
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=20*mm,
        bottomMargin=23*mm, title="Geprüfte Betriebskostenabrechnung - PDF-Vorschau", author="ImmoManager Pro", invariant=1)
    story = [_p("Betriebskostenabrechnung", title), _p("Geprüfte PDF-Vorschau", heading),
        _p("Diese Ableitung wurde anhand der gespeicherten Abrechnungsquellen geprüft. Archivierung und Versand sind gesonderte Vorgänge.", small)]
    if source.party_binding == UNPROVED:
        story += [_p("Historische Mietpartei nicht belegt", heading),
            _p("Die damalige Mietpartei und ihre postalische Identität wurden in dieser älteren Abrechnungsfassung nicht eingefroren.", body)]
    else:
        identity = source.original_party.identity
        address = [identity.full_name, identity.address_line, " ".join(item for item in (identity.postal_code, identity.city) if item), identity.country]
        story += [_p("Belegte ursprüngliche Mietpartei", heading), _p("\n".join(item for item in address if item), body)]
    story += [_p("Abrechnungsfassung", heading), _table([
        [_p("Zeitraum", body), _p(f"{period.start_date:%d.%m.%Y} bis {period.end_date:%d.%m.%Y}", body)],
        [_p("Fassung", body), _p(statement["revision"], body)],
        [_p("Einheitenreferenz", body), _p(statement["unit_id"], small)],
        [_p("Vertragsreferenz", body), _p(statement["contract_id"], small)],
    ], [43*mm, WIDTH-43*mm]), _p("Ursprüngliche Kostenpositionen", heading)]
    rows = [[_p("Kostenart", body), _p("Anteil", amount_style)]]
    for item in statement.get("line_items") or []:
        rows.append([_p(item.get("description") or "Kostenposition", body), _p(_money(item.get("allocated_amount")), amount_style)])
    if len(rows) == 1:
        rows.append([_p("Keine umgelegten Einzelpositionen im Original", body), _p(_money(0), amount_style)])
    story += [_table(rows, [WIDTH-37*mm, 37*mm], repeat=1, header=True), Spacer(1, 9), _table([
        [_p("Gesamtkosten", body), _p(_money(statement["total_cost"]), amount_style)],
        [_p("Bezahlte Vorauszahlungen", body), _p(_money(statement["advance_paid"]), amount_style)],
        [_p("Saldo", ParagraphStyle("UtilityTotal", parent=body, fontName=BOLD)), _p(_money(statement["balance"]), amount_style)],
    ], [WIDTH-47*mm, 47*mm])]
    if statement.get("advance_details"):
        story.append(_p("Gespeicherte Vorauszahlungsbelege", heading))
        advance_rows = [[_p("Belegreferenz", body), _p("Betrag", amount_style)]]
        for item in statement["advance_details"]:
            advance_rows.append([_p(item.get("rent_charge_id") or item.get("month") or "Gespeicherter Zahlungsbeleg", small),
                _p(_money(item["advance_paid"]) if "advance_paid" in item else "Betrag im Original nicht belegt", amount_style)])
        story.append(_table(advance_rows, [WIDTH-37*mm, 37*mm], repeat=1, header=True))
    if source.source_chain:
        story.append(_p("Belegte Korrekturquellen", heading))
        for link in source.source_chain:
            suffix = "Historische Partei unbelegt" if link.party_binding == UNPROVED else "Ursprüngliche Partei belegt"
            story.append(_p(f"Fassung {link.revision}: {link.statement_id}. {suffix}.", small))
    story += [_p("Quellnachweis", heading), _p("Abrechnungsreferenz: " + statement["id"], small),
        _p("Originalhash der vollständigen Periode: " + statement["snapshot_hash"], small),
        _p("Hash der ausgewählten Quellenfassung: " + source.source_digest, small), _p("Rendererprofil: " + PROFILE, small)]
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(REGULAR, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(18*mm, 12*mm, "Geprüfte PDF-Vorschau")
        canvas.drawRightString(A4[0]-18*mm, 12*mm, f"Seite {doc.page}")
        canvas.restoreState()
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def prepare_pdf_preview(store, identifier, actor_id):
    from .billing_disputes import work
    from .utility_statement_original_source import _Reader
    with work(store, actor_id) as (active, _case, _period, _add):
        source = _Reader(active).source(identifier)
        return render_pdf(source), source


def prepare_period_zip(store, identifier, actor_id):
    from .billing_disputes import work
    from .utility_statement_original_source import _Reader
    with work(store, actor_id, period_id=identifier) as (active, _case, _period, _add):
        reader = _Reader(active)
        reader.period(identifier)
        buffer, count = BytesIO(), 0
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            for statement in reader.rows(identifier):
                source = reader.source(statement.id)
                content = render_pdf(source)
                for suffix, data in (("pdf", content), ("source.json", json.dumps(source.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))):
                    metadata = ZipInfo(f"statement_{statement.id}.{suffix}", date_time=(1980, 1, 1, 0, 0, 0))
                    metadata.compress_type = ZIP_DEFLATED
                    archive.writestr(metadata, data)
                count += 1
        if count == 0:
            raise UtilityOriginalIntegrityError("Keine finalisierten Einzelabrechnungen für die geprüfte Vorschau vorhanden.")
        return buffer.getvalue()


def content_digest(content):
    return hashlib.sha256(content).hexdigest()
