"""Deterministic Unicode correspondence and frozen billing annex; no network resources."""
from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, SimpleDocTemplate, Spacer, Table, TableStyle

from .housing_confirmation_render import _fonts, _p


class _BillingTable(Table):
    def split(self, availWidth, availHeight):
        # Prefer complete rows. ReportLab otherwise starts a second fragment
        # (and repeats the header) in the remaining space on the SAME page.
        # An exceptionally tall row may split, but only on a fresh full frame.
        self.splitInRow = int(availHeight >= A4[1] - 47 * mm - 12 - .5)
        return super().split(availWidth, availHeight)


def render_pdf(review):
    regular, bold = _fonts()
    ink, muted, accent = colors.HexColor("#183D3C"), colors.HexColor("#59676A"), colors.HexColor("#126F68")
    styles = {name: ParagraphStyle("BillingLetter" + name, fontName=bold if name in {"title", "head"} else regular,
        fontSize=size, leading=leading, textColor=ink if name != "small" else muted,
        spaceAfter=space, splitLongWords=True) for name, size, leading, space in (
            ("body", 10, 15, 8), ("small", 8, 11, 4), ("title", 17, 23, 14),
            ("head", 9, 13, 0), ("cell", 8.4, 12, 0))}
    styles["amount"] = ParagraphStyle("BillingLetterAmount", parent=styles["cell"], alignment=TA_RIGHT)
    styles["amount_head"] = ParagraphStyle("BillingLetterAmountHead", parent=styles["head"], alignment=TA_RIGHT)
    data, document = review["data"], review["source"]["document"]
    width = A4[0] - 40 * mm
    facts = dict(document["facts"])
    reference = " | ".join(f"{key}: {facts[key]}" for key in ("Abrechnungszeitraum", "Vertrag", "Einheit")
                           if facts.get(key) and facts[key] != "—") or document["title"]
    issue_date = date.fromisoformat(data["issue_date"]).strftime("%d.%m.%Y")
    label = "ENTWURF - NICHT ZUM VERSAND" if review["draft"] else "Abrechnungsschreiben"

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(accent)
        canvas.setLineWidth(1)
        canvas.line(doc.leftMargin, A4[1] - 15 * mm, A4[0] - doc.rightMargin, A4[1] - 15 * mm)
        canvas.setFont(regular, 7.2)
        canvas.setFillColor(muted)
        canvas.drawString(doc.leftMargin, 12 * mm, f"{label} | {issue_date}")
        canvas.drawRightString(A4[0] - doc.rightMargin, 12 * mm, f"Seite {doc.page}")
        if review["draft"]:
            canvas.setFont(bold, 8)
            canvas.setFillColor(accent)
            canvas.drawRightString(A4[0] - doc.rightMargin, A4[1] - 12 * mm, "ENTWURF")
        canvas.restoreState()

    def paragraph(text, kind="body"):
        return _p(str(text or ""), styles[kind])

    def table(rows, widths, header=True, numeric_columns=()):
        cells = [[paragraph(cell, ("amount_head" if header and index == 0 else "amount") if column in numeric_columns
                            else "head" if header and index == 0 else "cell") for column, cell in enumerate(row)]
                 for index, row in enumerate(rows)]
        result = _BillingTable(cells, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT", splitInRow=1)
        result.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LINEBELOW", (0, 0), (-1, 0), .6, accent),
            ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, colors.HexColor("#F3F7F6")]),
        ]))
        return result

    story = [paragraph(data["sender_name"], "head"), paragraph(data["sender_address"], "small"), Spacer(1, 10 * mm),
             paragraph(data["recipient_name"], "head"), paragraph(data["recipient_address"]), Spacer(1, 6 * mm),
             paragraph(issue_date, "small"), paragraph(data["subject"], "title"),
             paragraph(f"Bezug: {reference}", "small"), Spacer(1, 1 * mm),
             paragraph(data["salutation"]), paragraph(data["intro"])]
    story += [Spacer(1, 3 * mm), KeepTogether([table(document["totals"], [width - 45 * mm, 45 * mm],
                  header=False, numeric_columns=(1,))]), Spacer(1, 5 * mm)]
    story += [paragraph("Die beigefügte Einzelabrechnung zeigt den Abrechnungszeitraum, Ihre Kostenanteile und die berücksichtigten Vorauszahlungen.")]
    story += [KeepTogether([Spacer(1, 3 * mm), paragraph(data["closing"]), paragraph(data["signature"])])]
    story += [PageBreak(),
              paragraph(document["title"], "title"), paragraph("Einzelabrechnung und Berechnungsgrundlagen", "small"),
              table(document["facts"], [46 * mm, width - 46 * mm], header=False), Spacer(1, 7 * mm)]
    rows = [["Kostenposition", "Gesamtkosten", "Verteilung und Ihr Anteil", "Ihr Betrag"], *document["rows"]]
    story += [table(rows, [57 * mm, 28 * mm, 56 * mm, width - 141 * mm], numeric_columns=(1, 3)), Spacer(1, 7 * mm)]
    if document.get("advances"):
        story += [paragraph("Vorauszahlungen", "head"), table([["Zeitraum", "Vereinbart", "Betrag"], *document["advances"]],
                   [width - 85 * mm, 50 * mm, 35 * mm], numeric_columns=(1, 2)), Spacer(1, 6 * mm)]
    story += [KeepTogether([paragraph("Abrechnungsergebnis", "head"), Spacer(1, 3 * mm),
        table(document["totals"], [width - 45 * mm, 45 * mm], header=False, numeric_columns=(1,))])]
    output = BytesIO()
    pdf = SimpleDocTemplate(output, pagesize=A4, invariant=1, title=data["subject"], author=data["sender_name"],
                            creator="ImmoManager Pro", leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=24 * mm, bottomMargin=23 * mm)
    pdf.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output.getvalue()
