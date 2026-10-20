"""Deterministic PDF of a dunning letter (Zahlungserinnerung / Mahnung) from its reviewed content.

The same content always gives the same bytes (ReportLab invariant mode), so the
preview of a draft and the archived original are byte-identical.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, SimpleDocTemplate, Spacer

from .handover_protocol_render import _table
from .housing_confirmation_render import _RULE, _facts, _fonts, _p, _section, _styles

KIND_LABELS = {"rent": "Miete", "receivable": "Forderung", "fee": "Mahngebühr", "interest": "Verzugszinsen"}

OPENINGS = {
    1: ("sicher ist es Ihrer Aufmerksamkeit entgangen: Auf Ihrem Mietkonto sind die unten aufgeführten Beträge "
        "fällig und noch nicht (vollständig) bei uns eingegangen."),
    2: ("trotz Fälligkeit konnten wir für die unten aufgeführten Forderungen keinen (vollständigen) Zahlungseingang "
        "feststellen. Wir mahnen die offenen Beträge hiermit an."),
    3: ("auf unsere bisherigen Schreiben haben Sie die unten aufgeführten Forderungen nicht beglichen. Wir fordern "
        "Sie erneut zur Zahlung auf."),
    4: ("trotz mehrfacher Aufforderung sind die unten aufgeführten Forderungen weiterhin offen. Dies ist unsere "
        "letzte Mahnung."),
}
CLOSINGS = {
    1: "Sollten Sie die Zahlung inzwischen veranlasst haben, betrachten Sie dieses Schreiben bitte als gegenstandslos.",
    2: ("Sollten Sie die Zahlung inzwischen veranlasst haben, betrachten Sie dieses Schreiben bitte als gegenstandslos. "
        "Bei Fragen oder Einwänden wenden Sie sich bitte unter Angabe des Aktenzeichens an uns."),
    3: ("Bei Fragen oder Einwänden wenden Sie sich bitte unter Angabe des Aktenzeichens umgehend an uns. "
        "Weitere Kosten und Zinsen lassen sich durch fristgerechte Zahlung vermeiden."),
    4: ("Geht der Gesamtbetrag nicht fristgerecht ein, werden wir die Forderung ohne weitere Ankündigung an ein "
        "Inkassounternehmen abgeben oder gerichtlich geltend machen. Die dadurch entstehenden Kosten gehen zu "
        "Ihren Lasten."),
}


def day(value: str | None) -> str:
    return date.fromisoformat(value).strftime("%d.%m.%Y") if value else "—"


def eur(value: Any) -> str:
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    text = f"{amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{text} €"


def subject(content: dict) -> str:
    return f"{content['stage_label']} – Aktenzeichen {content['reference']} – Vertrag {content['contract']['number']}"


def plain_text(content: dict) -> str:
    """The letter as plain text (outbox body, e-mail draft); the PDF stays the original."""
    lines = [f"{content['recipient']['name']}", "", subject(content), "",
             "Sehr geehrte Damen und Herren,", "", OPENINGS[content["stage"]], ""]
    for line in content["lines"]:
        lines.append(f"- {line['description']} (fällig {day(line['due_date'])}): {eur(line['outstanding'])}")
    for line in content["earlier_charges"]:
        lines.append(f"- {line['description']}: {eur(line['outstanding'])}")
    if Decimal(content["fee"]):
        lines.append(f"- Mahngebühr dieses Schreibens: {eur(content['fee'])}")
    if Decimal(content["interest"]):
        lines.append(f"- Verzugszinsen bis {day(content['letter_date'])}: {eur(content['interest'])}")
    lines += ["", f"Gesamtbetrag: {eur(content['total'])}",
              f"Bitte zahlen Sie bis spätestens {day(content['payment_deadline'])} unter Angabe des Aktenzeichens "
              f"{content['reference']}."]
    bank = [line.strip() for line in ((content.get("letterhead") or {}).get("bank") or "").split("\n") if line.strip()]
    if bank:
        lines += ["", "Bankverbindung:", *bank]
    lines += ["", CLOSINGS[content["stage"]], "", "Mit freundlichen Grüßen", content["sender"]["name"]]
    return "\n".join(lines)


def _claims_and_totals(content: dict, styles: dict, width: float) -> list[Any]:
    head, cell = styles["table_bold"], styles["table"]
    rows = [[_p(text, head) for text in ("Forderung", "Fällig", "Betrag", "Gezahlt", "Offen")]]
    for line in [*content["lines"], *content["earlier_charges"]]:
        rows.append([_p(line["description"], cell), _p(day(line["due_date"]), cell), _p(eur(line["amount"]), cell),
                     _p(eur(line["paid"]), cell), _p(eur(line["outstanding"]), cell)])
    totals = [("Offene Hauptforderung", eur(content["principal"]))]
    if Decimal(content["earlier_charges_total"]):
        totals.append(("Gebühren und Zinsen früherer Schreiben", eur(content["earlier_charges_total"])))
    if Decimal(content["fee"]):
        totals.append(("Mahngebühr dieses Schreibens", eur(content["fee"])))
    if Decimal(content["interest"]):
        totals.append((f"Verzugszinsen bis {day(content['letter_date'])}", eur(content["interest"])))
    totals.append(("Gesamtbetrag", eur(content["total"])))
    story: list[Any] = [_section("Offene Forderungen", styles, width), Spacer(1, 4),
                        _table(rows, [width - 112 * mm, 24 * mm, 30 * mm, 28 * mm, 30 * mm], styles),
                        Spacer(1, 8), _facts(totals, styles, width), Spacer(1, 8)]
    if content.get("interest_note"):
        story += [_p(content["interest_note"], styles["small"]), Spacer(1, 6)]
    return story


def _render_with_letterhead(content: dict, logo: bytes | None) -> bytes:
    """Format 2: the shared letterhead frame, with the bank details in the footer."""
    from .letter_layout import TEXT_WIDTH, closing_flowables, letter_styles, render_frame

    head = content["letterhead"]
    styles, letter = _styles(), letter_styles()
    contract = content["contract"]
    place = " · ".join(part for part in (contract.get("property"), contract.get("unit")) if part) or "—"
    account = " auf das Konto in der Fußzeile" if (head.get("bank") or "").strip() else ""
    story: list[Any] = [_p("Sehr geehrte Damen und Herren,", letter["body"]),
                        _p(OPENINGS[content["stage"]], letter["body"]), Spacer(1, 4),
                        *_claims_and_totals(content, styles, TEXT_WIDTH),
                        _p(f"Bitte überweisen Sie den Gesamtbetrag bis spätestens {day(content['payment_deadline'])}"
                           f"{account} unter Angabe des Aktenzeichens {content['reference']}.", letter["body"]),
                        _p(CLOSINGS[content["stage"]], letter["body"]),
                        *closing_flowables("Mit freundlichen Grüßen", head.get("signature") or content["sender"]["name"],
                                           letter),
                        Spacer(1, 6),
                        _p("Dieses Schreiben wurde maschinell erstellt; das archivierte Original ist unveränderlich.",
                           letter["small"])]
    frame = {"recipient_name": content["recipient"]["name"], "recipient_address": content["recipient"].get("address") or "",
             "issue_date": content["letter_date"], "subject": subject(content),
             "info": [["Aktenzeichen", content["reference"]], ["Mietvertrag", contract["number"]], ["Objekt", place],
                      ["Zahlungsziel", day(content["payment_deadline"])]]}
    return render_frame(frame, head, logo, story)


def render_pdf(content: dict, logo: bytes | None = None) -> bytes:
    """Format 1 (no letterhead in the content) as before; format 2 in the shared letterhead frame."""
    if isinstance(content.get("letterhead"), dict):
        return _render_with_letterhead(content, logo)
    styles = _styles()
    regular, _ = _fonts()
    head, cell = styles["table_bold"], styles["table"]
    width = A4[0] - 40 * mm

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(_RULE)
        canvas.setLineWidth(0.4)
        canvas.line(doc.leftMargin, 13 * mm, A4[0] - doc.rightMargin, 13 * mm)
        canvas.setFont(regular, 7.3)
        canvas.setFillColor(colors.HexColor("#666A70"))
        canvas.drawString(doc.leftMargin, 9 * mm, f"{content['stage_label']} · Aktenzeichen {content['reference']}")
        canvas.drawRightString(A4[0] - doc.rightMargin, 9 * mm, f"Seite {doc.page}")
        canvas.restoreState()

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, invariant=1, title=subject(content), author="ImmoManager",
                            leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=20 * mm)
    sender, recipient, contract = content["sender"], content["recipient"], content["contract"]
    story: list[Any] = [
        _p(sender["name"], styles["small"]),
        Spacer(1, 10),
        _p("\n".join(part for part in (recipient["name"], recipient.get("address")) if part), styles["body"]),
        Spacer(1, 16),
        _p(f"{day(content['letter_date'])}", styles["body"]),
        Spacer(1, 6),
        _p(content["stage_label"].upper(), styles["title"]),
        _p(f"Aktenzeichen {content['reference']} · bitte bei Zahlung und Rückfragen angeben", styles["subtitle"]),
        _facts([
            ("Mietvertrag", contract["number"]),
            ("Objekt", " · ".join(part for part in (contract.get("property"), contract.get("unit")) if part) or "—"),
            ("Stand", f"Zahlungseingänge bis {day(content['letter_date'])} berücksichtigt"),
        ], styles, width),
        Spacer(1, 10),
        _p("Sehr geehrte Damen und Herren,", styles["body"]),
        _p(OPENINGS[content["stage"]], styles["body"]),
        Spacer(1, 6),
        _section("Offene Forderungen", styles, width), Spacer(1, 4),
    ]
    rows = [[_p(text, head) for text in ("Forderung", "Fällig", "Betrag", "Gezahlt", "Offen")]]
    for line in content["lines"]:
        rows.append([_p(line["description"], cell), _p(day(line["due_date"]), cell), _p(eur(line["amount"]), cell),
                     _p(eur(line["paid"]), cell), _p(eur(line["outstanding"]), cell)])
    for line in content["earlier_charges"]:
        rows.append([_p(line["description"], cell), _p(day(line["due_date"]), cell), _p(eur(line["amount"]), cell),
                     _p(eur(line["paid"]), cell), _p(eur(line["outstanding"]), cell)])
    story.append(_table(rows, [width - 112 * mm, 24 * mm, 30 * mm, 28 * mm, 30 * mm], styles))
    totals = [("Offene Hauptforderung", eur(content["principal"]))]
    if Decimal(content["earlier_charges_total"]):
        totals.append(("Gebühren und Zinsen früherer Schreiben", eur(content["earlier_charges_total"])))
    if Decimal(content["fee"]):
        totals.append(("Mahngebühr dieses Schreibens", eur(content["fee"])))
    if Decimal(content["interest"]):
        totals.append((f"Verzugszinsen bis {day(content['letter_date'])}", eur(content["interest"])))
    totals.append(("Gesamtbetrag", eur(content["total"])))
    story += [Spacer(1, 8), _facts(totals, styles, width), Spacer(1, 8)]
    if content.get("interest_note"):
        story.append(_p(content["interest_note"], styles["small"]))
        story.append(Spacer(1, 6))
    story += [
        _p(f"Bitte überweisen Sie den Gesamtbetrag bis spätestens {day(content['payment_deadline'])} unter Angabe "
           f"des Aktenzeichens {content['reference']}.", styles["body"]),
        _p(CLOSINGS[content["stage"]], styles["body"]),
        KeepTogether([Spacer(1, 10), _p("Mit freundlichen Grüßen", styles["body"]), Spacer(1, 14),
                      _p(sender["name"], styles["body"])]),
        Spacer(1, 12),
        _p("Dieses Schreiben wurde maschinell erstellt; das archivierte Original ist unveränderlich.",
           styles["small"]),
    ]
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output.getvalue()
