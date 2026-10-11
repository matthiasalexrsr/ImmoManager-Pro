"""Deterministic PDF of a deposit settlement (Kautionsabrechnung) from its reviewed facts.

The same facts always give the same bytes (ReportLab invariant mode), so the
reviewed preview and the archived original are byte-identical.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, SimpleDocTemplate, Spacer, Table, TableStyle

from .housing_confirmation_render import _RULE, _facts, _fonts, _p, _section, _styles

FORMS = {"cash": "Barkaution (bar übergeben)", "transfer": "Barkaution (Überweisung auf separates Konto)",
         "deposit_account": "Kautionskonto", "guarantee": "Bürgschaft", "pledged_savings": "Verpfändetes Sparbuch"}
ITEM_KINDS = {"defect": "Mangel laut Übergabeprotokoll", "other": "Sonstiger Anspruch",
              "receivable": "Verrechnung offene Forderung", "rent_arrears": "Verrechnung Mietrückstand",
              "retention": "Einbehalt (offene Nebenkostenabrechnung)"}
KINDS = {"final": "Kautionsabrechnung", "retention_release": "Freigabe des Einbehalts"}


def day(value: str | None) -> str:
    return date.fromisoformat(value).strftime("%d.%m.%Y") if value else "—"


def euro(value: str | Decimal) -> str:
    amount = Decimal(str(value))
    sign = "−" if amount < 0 else ""
    text = f"{abs(amount):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{sign}{text} €"


def _table(rows: list[list[Any]], widths: list[float]) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F3F4")),
        ("BOX", (0, 0), (-1, -1), 0.45, _RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def render_pdf(review: dict) -> bytes:
    styles = _styles()
    regular, _ = _fonts()
    head, cell = styles["table_bold"], styles["table"]
    width = A4[0] - 32 * mm
    settlement, deposit, source = review["settlement"], review["deposit"], review["source"]
    outcome, interest = review["outcome"], review["interest"]
    kind = KINDS[settlement["kind"]]
    contract, tenant, prop, unit = source["contract"], source["tenant"], source["property"], source["unit"]

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(_RULE)
        canvas.setLineWidth(0.4)
        canvas.line(doc.leftMargin, 13 * mm, A4[0] - doc.rightMargin, 13 * mm)
        canvas.setFont(regular, 7.3)
        canvas.setFillColor(colors.HexColor("#666A70"))
        canvas.drawString(doc.leftMargin, 9 * mm, f"{kind} · Vertrag {contract['contract_number']}")
        canvas.drawRightString(A4[0] - doc.rightMargin, 9 * mm, f"Seite {doc.page}")
        canvas.restoreState()

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, invariant=1, title=kind, author="ImmoManager",
                            leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=19 * mm)
    address = "\n".join(part for part in (prop.get("address_line"),
                                          " ".join(v for v in (prop.get("postal_code"), prop.get("city")) if v))
                        if part)
    story: list[Any] = [
        _p(kind.upper(), styles["title"]),
        _p(f"Stichtag {day(settlement['settlement_date'])} · Mietsicherheit nach § 551 BGB", styles["subtitle"]),
        _section("Mietverhältnis", styles, width), Spacer(1, 4),
        _facts([
            ("Objekt", "\n".join(part for part in (prop.get("name"), address) if part)),
            ("Einheit", unit.get("label") or "—"),
            ("Mietvertrag", f"{contract['contract_number']} · Beginn {day(contract.get('start_date'))}"
                            + (f" · Ende {day(contract.get('end_date'))}" if contract.get("end_date") else "")),
            ("Mieter", tenant.get("full_name") or "—"),
            ("Vermieter / Eigentümer", source["portfolio"].get("owner_name") or source["portfolio"].get("name") or "—"),
        ], styles, width),
        Spacer(1, 9), _section("Kautionsvereinbarung", styles, width), Spacer(1, 4),
    ]
    agreement = [("Vereinbarte Kaution", euro(deposit["amount"])), ("Form", FORMS.get(deposit["form"], deposit["form"]))]
    if deposit.get("instalments"):
        agreement.append(("Raten", "\n".join(f"{i['number']}. Rate {euro(i['amount'])}, fällig {day(i['due_date'])}"
                                             for i in deposit["instalments"])))
    held = " · ".join(v for v in (deposit.get("institution"), deposit.get("account_reference"),
                                  deposit.get("account_holder")) if v)
    if held:
        agreement.append(("Angelegt bei", held))
    if deposit.get("cap_reason"):
        agreement.append(("Begründung Höhe", deposit["cap_reason"]))
    story.append(_facts(agreement, styles, width))

    previous = review["previous"]
    if previous is not None:
        story += [Spacer(1, 6), _facts([("Bezug", f"Kautionsabrechnung vom {day(previous.get('settlement_date'))}, "
                                                  f"Einbehalt {euro(previous.get('retention', '0'))} (Original-PDF "
                                                  f"SHA-256 {previous.get('pdf_sha256', '')[:16]}…)")],
                                        styles, width)]

    story += [Spacer(1, 9), _section("Eingänge der Kaution" if previous is None else "Einbehaltener Betrag", styles,
                                     width), Spacer(1, 4)]
    if review["receipts"]:
        rows = [[_p(text, head) for text in ("Datum", "Vorgang", "Betrag")]]
        rows += [[_p(day(r["booking_date"]), cell), _p(r.get("label") or "Zahlungseingang", cell),
                  _p(euro(r["amount"]), cell)] for r in review["receipts"]]
        story.append(_table(rows, [30 * mm, width - 70 * mm, 40 * mm]))
    else:
        story.append(_p("Keine Eingänge erfasst.", styles["body"]))

    story += [Spacer(1, 9), _section("Zinsen", styles, width), Spacer(1, 4)]
    rates = "; ".join(f"ab {day(r['valid_from'])} {r['rate_percent'].replace('.', ',')} % p. a."
                      for r in interest["rates"]) or "kein Zinssatz erfasst"
    facts = [("Zinssätze", rates),
             ("Berechnung", "Zinstage vom Eingang bis zum Stichtag (ausschließlich), tatsächliche Tage je "
                            "Kalenderjahr; je Jahr kaufmännisch auf Cent gerundet und zum 31.12. gutgeschrieben."),
             ("Berechnete Zinsen", euro(interest["computed"]))]
    if interest.get("override") is not None:
        facts.append(("Angesetzte Zinsen", f"{euro(interest['override'])} – {interest.get('reason') or ''}"))
    story.append(_facts(facts, styles, width))
    if interest["years"]:
        rows = [[_p(text, head) for text in ("Jahr", "Zeitraum", "Guthaben zu Beginn", "Zinsen")]]
        rows += [[_p(str(y["year"]), cell), _p(f"{day(y['start'])} – {day(y['end_inclusive'])}", cell),
                  _p(euro(y["principal_start"]), cell), _p(euro(y["interest"]), cell)] for y in interest["years"]]
        story += [Spacer(1, 4), _table(rows, [18 * mm, width - 98 * mm, 40 * mm, 40 * mm])]

    story += [Spacer(1, 9), _section("Ansprüche, Verrechnungen und Einbehalt", styles, width), Spacer(1, 4)]
    if review["items"]:
        rows = [[_p(text, head) for text in ("Nr.", "Art", "Beschreibung / Begründung", "Betrag")]]
        for index, item in enumerate(review["items"], 1):
            text = item["description"] + (f"\n{item['reason']}" if item.get("reason") else "")
            rows.append([_p(str(index), cell), _p(ITEM_KINDS.get(item["kind"], item["kind"]), cell), _p(text, cell),
                         _p(euro(item["amount"]), cell)])
        story.append(_table(rows, [10 * mm, 44 * mm, width - 94 * mm, 40 * mm]))
    else:
        story.append(_p("Keine Ansprüche geltend gemacht.", styles["body"]))

    result = Decimal(outcome["result"])
    summary = [
        ("Kaution (Eingänge)" if previous is None else "Einbehaltener Betrag", euro(outcome["principal"])),
        ("+ Zinsen", euro(outcome["interest"])),
        ("= Guthaben des Mieters", euro(outcome["credit"])),
        ("− Ansprüche und Verrechnungen", euro(outcome["claims"])),
    ]
    if Decimal(outcome["retention"]):
        summary.append(("− Einbehalt bis zur Nebenkostenabrechnung", euro(outcome["retention"])))
    if result > 0:
        summary.append(("Auszahlung an den Mieter", euro(outcome["payout"])))
    elif result < 0:
        summary.append(("Restforderung gegen den Mieter", euro(outcome["remaining_claim"])))
    else:
        summary.append(("Ergebnis", "ausgeglichen"))
    story += [Spacer(1, 9), KeepTogether([_section("Ergebnis", styles, width), Spacer(1, 4),
                                          _facts(summary, styles, width)])]
    if settlement.get("notes"):
        story += [Spacer(1, 9), _section("Bemerkungen", styles, width), Spacer(1, 4),
                  _p(settlement["notes"], styles["body"])]
    story += [Spacer(1, 12), _p("Abgeschlossene Abrechnungen bleiben unverändert im Dokumentarchiv. Die Auszahlung "
                                "bzw. Restforderung ist als Buchung bzw. Forderung erfasst; ein Versand an den "
                                "Mieter erfolgt nicht automatisch.", styles["small"])]
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output.getvalue()
