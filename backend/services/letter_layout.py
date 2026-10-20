"""One deterministic letter layout (DIN 5008, Form B) with the shared letterhead.

Page 1: sender and logo at the top, return line and recipient in the address
field of a window envelope (45 mm from the top, 20 mm from the left), the
information block on the right (references and date), fold marks at 105 mm and
210 mm and the punch mark at 148.5 mm. Every page: address, contact and bank
details in three footer columns, the footer line and the page number.

The body is plain text: paragraphs are separated by a blank line, lines starting
with "- " are bullet points, **text** is bold, and a line that is exactly
`{{tabelle.<name>}}` is replaced by the table `blocks[<name>]` the server
calculated. Same input, same bytes (ReportLab invariant mode).
"""
from __future__ import annotations

import re
from datetime import date
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import registerFontFamily, stringWidth
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .housing_confirmation_render import _fonts

INK = colors.HexColor("#202124")
MUTED = colors.HexColor("#5F6368")
RULE = colors.HexColor("#C8CBD0")
FILL = colors.HexColor("#F2F3F4")
WATERMARK = colors.HexColor("#E3E5E8")

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT = 25 * mm                      # text edge (DIN 5008)
RIGHT = 20 * mm
TEXT_WIDTH = PAGE_WIDTH - LEFT - RIGHT
FOOTER_TOP = 34 * mm                # body text ends above the footer
FIRST_BODY_TOP = 98.5 * mm          # subject line of Form B
LATER_BODY_TOP = 27 * mm
ADDRESS_LEFT, ADDRESS_TOP, ADDRESS_WIDTH, ADDRESS_HEIGHT = 20 * mm, 45 * mm, 85 * mm, 45 * mm
INFO_LEFT, INFO_TOP = 125 * mm, 50 * mm
INFO_WIDTH = PAGE_WIDTH - RIGHT - INFO_LEFT
LOGO_BOX = (60 * mm, 22 * mm)
BLOCK_LINE = re.compile(r"^\{\{\s*tabelle\.([a-z_]+)\s*\}\}$")
BULLET = re.compile(r"^[-•]\s+")
BOLD = re.compile(r"\*\*(.+?)\*\*")


def day(value: str | date | None) -> str:
    if not value:
        return ""
    return (value if isinstance(value, date) else date.fromisoformat(value)).strftime("%d.%m.%Y")


def _styles() -> dict[str, ParagraphStyle]:
    regular, bold = _fonts()
    # <b> in a paragraph needs the bold face of the same family
    registerFontFamily(regular, normal=regular, bold=bold, italic=regular, boldItalic=bold)
    base = dict(fontName=regular, textColor=INK, splitLongWords=True)
    return {
        "body": ParagraphStyle("LetterBody", fontSize=10, leading=14.2, spaceAfter=7, **base),
        "bullet": ParagraphStyle("LetterBullet", fontSize=10, leading=14.2, spaceAfter=3, leftIndent=12,
                                 bulletIndent=2, **base),
        "subject": ParagraphStyle("LetterSubject", fontSize=11, leading=15, spaceAfter=10,
                                  **{**base, "fontName": bold}),
        "address": ParagraphStyle("LetterAddress", fontSize=10, leading=12.6, **base),
        "return": ParagraphStyle("LetterReturn", fontSize=6.6, leading=8, **{**base, "textColor": MUTED}),
        "info_label": ParagraphStyle("LetterInfoLabel", fontSize=7.2, leading=8.6, **{**base, "textColor": MUTED}),
        "info_value": ParagraphStyle("LetterInfoValue", fontSize=9, leading=11, spaceAfter=3, **base),
        "footer": ParagraphStyle("LetterFooter", fontSize=6.9, leading=8.4, **{**base, "textColor": MUTED}),
        "footer_head": ParagraphStyle("LetterFooterHead", fontSize=6.9, leading=8.4,
                                      **{**base, "fontName": bold, "textColor": MUTED}),
        "sender": ParagraphStyle("LetterSender", fontSize=13, leading=16, **{**base, "fontName": bold}),
        "sender_line": ParagraphStyle("LetterSenderLine", fontSize=8, leading=10, **{**base, "textColor": MUTED}),
        "cell": ParagraphStyle("LetterCell", fontSize=9, leading=12, **base),
        "cell_head": ParagraphStyle("LetterCellHead", fontSize=8.6, leading=11.5, **{**base, "fontName": bold}),
        "small": ParagraphStyle("LetterSmall", fontSize=8, leading=10.5, spaceAfter=3, **{**base, "textColor": MUTED}),
    }


def _text(value: str) -> str:
    return BOLD.sub(r"<b>\1</b>", escape(value)).replace("\n", "<br/>")


def _lines(value: str | None) -> list[str]:
    return [line.strip() for line in (value or "").replace("\r\n", "\n").split("\n") if line.strip()]


def block_names(body: str) -> list[str]:
    return [match.group(1) for line in body.split("\n") if (match := BLOCK_LINE.match(line.strip()))]


def _table(block: dict, styles: dict, width: float) -> Table:
    rows = block["rows"]
    header = bool(block.get("header", True))
    numeric = set(block.get("numeric", ()))
    fractions = block.get("widths") or [1 / len(rows[0])] * len(rows[0])
    right = ParagraphStyle("LetterCellRight", parent=styles["cell"], alignment=TA_RIGHT)
    right_head = ParagraphStyle("LetterCellHeadRight", parent=styles["cell_head"], alignment=TA_RIGHT)
    cells = []
    for index, row in enumerate(rows):
        head = header and index == 0
        strong = bool(block.get("total")) and index == len(rows) - 1
        cells.append([Paragraph(("<b>%s</b>" if strong else "%s") % escape(str(cell)),
                                (right_head if head else right) if column in numeric
                                else styles["cell_head"] if head else styles["cell"])
                      for column, cell in enumerate(row)])
    table = Table(cells, colWidths=[width * fraction for fraction in fractions], hAlign="LEFT",
                  repeatRows=1 if header else 0)
    commands: list[Any] = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, -1), (-1, -1), .4, RULE),
    ]
    if header:
        commands += [("BACKGROUND", (0, 0), (-1, 0), FILL), ("LINEBELOW", (0, 0), (-1, 0), .5, RULE)]
    if block.get("total"):
        commands.append(("LINEABOVE", (0, -1), (-1, -1), .6, INK))
    table.setStyle(TableStyle(commands))
    return table


def body_flowables(body: str, styles: dict, blocks: dict[str, dict] | None = None) -> list[Any]:
    """Paragraphs, bullet points and calculated tables of a letter text."""
    story: list[Any] = []
    blocks = blocks or {}
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            story.append(Paragraph(_text("\n".join(paragraph)), styles["body"]))
            paragraph.clear()

    for raw in body.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        match = BLOCK_LINE.match(line.strip())
        if match:
            flush()
            name = match.group(1)
            if name not in blocks:
                raise ValueError(f"Unbekannte Tabelle {name}")
            story += [Spacer(1, 1 * mm), _table(blocks[name], styles, TEXT_WIDTH), Spacer(1, 4 * mm)]
        elif not line.strip():
            flush()
        elif BULLET.match(line.strip()):
            flush()
            story.append(Paragraph(_text(BULLET.sub("", line.strip())), styles["bullet"], bulletText="•"))
        else:
            paragraph.append(line)
    flush()
    return story


def _fit(text: str, font: str, size: float, width: float) -> tuple[str, float]:
    while size > 5.4 and stringWidth(text, font, size) > width:
        size -= 0.2
    while text and stringWidth(text, font, size) > width:
        text = text[:-2] + "…"
    return text, size


def _footer_columns(head: dict, styles: dict) -> list[list[Any]]:
    columns = []
    address = [head.get("sender_name", "")] + _lines(head.get("sender_address"))
    for title, lines in (("Anschrift", address), ("Kontakt", _lines(head.get("contact"))),
                         ("Bankverbindung", _lines(head.get("bank")))):
        lines = [line for line in lines if line]
        columns.append([Paragraph(escape(title), styles["footer_head"])]
                       + [Paragraph(escape(line), styles["footer"]) for line in lines[:5]] if lines else [])
    return columns


def letter_styles() -> dict[str, ParagraphStyle]:
    """The paragraph styles of the letter layout, for letters that build their own content."""
    return _styles()


def closing_flowables(closing: str, signature: str, styles: dict) -> list[Any]:
    """Closing and name with room for a handwritten signature, kept on one page."""
    parts: list[Any] = [Spacer(1, 2 * mm)]
    if closing:
        parts.append(Paragraph(_text(closing), styles["body"]))
    parts.append(Spacer(1, 12 * mm))
    if signature:
        parts.append(Paragraph(_text(signature), styles["body"]))
    return [KeepTogether(parts)]


def render_letter(letter: dict, head: dict, logo: bytes | None, *, draft: bool = False,
                  draft_label: str = "ENTWURF", blocks: dict[str, dict] | None = None) -> bytes:
    """The letter as PDF. `letter`: recipient_name, recipient_address, issue_date, subject, info
    ([label, value] rows), salutation, body, closing, signature, optional appendix (after a rule,
    e.g. a declaration to sign) and attachments."""
    styles = _styles()
    story: list[Any] = []
    if letter.get("salutation"):
        story.append(Paragraph(_text(letter["salutation"]), styles["body"]))
    story += body_flowables(letter.get("body") or "", styles, blocks)
    story += closing_flowables(letter.get("closing") or "", letter.get("signature") or "", styles)
    if letter.get("appendix"):
        rule = Table([[""]], colWidths=[TEXT_WIDTH], style=[("LINEABOVE", (0, 0), (-1, -1), .5, RULE)])
        story.append(KeepTogether([Spacer(1, 8 * mm), rule, Spacer(1, 3 * mm),
                                   *body_flowables(letter["appendix"], styles, blocks)]))
    if letter.get("attachments"):
        story += [Spacer(1, 4 * mm), Paragraph("<b>Anlagen</b>", styles["small"])]
        story += [Paragraph(escape(item), styles["small"]) for item in letter["attachments"]]
    return render_frame(letter, head, logo, story, draft=draft, draft_label=draft_label)


def render_frame(letter: dict, head: dict, logo: bytes | None, content: list[Any], *, draft: bool = False,
                 draft_label: str = "ENTWURF") -> bytes:
    """Any letter in the shared frame: letterhead, address field, information block, subject, then
    `content` (flowables), footer and page numbers. `letter`: recipient_name, recipient_address,
    issue_date, subject, info."""
    styles = _styles()
    regular, bold = _fonts()
    sender_lines = _lines(head.get("sender_address"))
    footer_columns = _footer_columns(head, styles)
    footer_note = (head.get("footer") or "").strip()
    picture = ImageReader(BytesIO(logo)) if logo else None

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(.4)
        canvas.line(LEFT, FOOTER_TOP - 3 * mm, PAGE_WIDTH - RIGHT, FOOTER_TOP - 3 * mm)
        width = TEXT_WIDTH / 3
        for index, column in enumerate(footer_columns):
            y = FOOTER_TOP - 5 * mm
            for flowable in column:
                _, height = flowable.wrapOn(canvas, width - 3 * mm, 20 * mm)
                flowable.drawOn(canvas, LEFT + index * width, y - height + 2)
                y -= height
        canvas.setFont(regular, 6.9)
        canvas.setFillColor(MUTED)
        if footer_note:
            text, size = _fit(" · ".join(_lines(footer_note)), regular, 6.9, TEXT_WIDTH - 22 * mm)
            canvas.setFont(regular, size)
            canvas.drawString(LEFT, 8.5 * mm, text)
            canvas.setFont(regular, 6.9)
        canvas.drawRightString(PAGE_WIDTH - RIGHT, 8.5 * mm, f"Seite {doc.page}")
        if draft:
            canvas.setFillColor(WATERMARK)
            canvas.setFont(bold, 92)
            canvas.translate(PAGE_WIDTH / 2, PAGE_HEIGHT / 2)
            canvas.rotate(48)
            canvas.drawCentredString(0, -30, draft_label)
        canvas.restoreState()

    def marks(canvas) -> None:
        canvas.saveState()
        canvas.setStrokeColor(MUTED)
        canvas.setLineWidth(.3)
        for top, length in ((105 * mm, 5 * mm), (148.5 * mm, 8 * mm), (210 * mm, 5 * mm)):
            canvas.line(4 * mm, PAGE_HEIGHT - top, 4 * mm + length, PAGE_HEIGHT - top)
        canvas.restoreState()

    def first_page(canvas, doc) -> None:
        marks(canvas)
        canvas.saveState()
        # letterhead: sender and logo
        if picture is not None:
            width, height = picture.getSize()
            scale = min(LOGO_BOX[0] / width, LOGO_BOX[1] / height)
            canvas.drawImage(picture, PAGE_WIDTH - RIGHT - width * scale, PAGE_HEIGHT - 12 * mm - height * scale,
                             width * scale, height * scale, mask="auto")
        name_width = TEXT_WIDTH - (LOGO_BOX[0] + 6 * mm if picture is not None else 0)
        sender = Paragraph(escape(head.get("sender_name") or ""), styles["sender"])
        _, height = sender.wrapOn(canvas, name_width, 20 * mm)
        sender.drawOn(canvas, LEFT, PAGE_HEIGHT - 14 * mm - height)
        line = " · ".join(sender_lines)
        if line:
            detail = Paragraph(escape(line), styles["sender_line"])
            _, detail_height = detail.wrapOn(canvas, name_width, 12 * mm)
            detail.drawOn(canvas, LEFT, PAGE_HEIGHT - 15.5 * mm - height - detail_height)
        # address field: return line above the recipient
        back = " · ".join(part for part in [head.get("sender_name") or "", *sender_lines] if part)
        if back:
            text, size = _fit(back, regular, 6.6, ADDRESS_WIDTH - 5 * mm)
            canvas.setFont(regular, size)
            canvas.setFillColor(MUTED)
            canvas.drawString(LEFT, PAGE_HEIGHT - ADDRESS_TOP - 15.2 * mm, text)
            canvas.setStrokeColor(RULE)
            canvas.setLineWidth(.3)
            canvas.line(LEFT, PAGE_HEIGHT - ADDRESS_TOP - 16 * mm,
                        LEFT + min(stringWidth(text, regular, size), ADDRESS_WIDTH - 5 * mm),
                        PAGE_HEIGHT - ADDRESS_TOP - 16 * mm)
        recipient = Paragraph(_text("\n".join([letter["recipient_name"], *_lines(letter["recipient_address"])])),
                              styles["address"])
        _, height = recipient.wrapOn(canvas, ADDRESS_WIDTH - 5 * mm, 27 * mm)
        recipient.drawOn(canvas, LEFT, PAGE_HEIGHT - ADDRESS_TOP - 18.5 * mm - height)
        # information block
        y = PAGE_HEIGHT - INFO_TOP
        for label, value in [*letter.get("info", []), ["Datum", day(letter["issue_date"])]]:
            for text, style in ((label, styles["info_label"]), (value, styles["info_value"])):
                item = Paragraph(escape(str(text)), style)
                _, item_height = item.wrapOn(canvas, INFO_WIDTH, 12 * mm)
                item.drawOn(canvas, INFO_LEFT, y - item_height)
                y -= item_height + (style.spaceAfter or 0)
        canvas.restoreState()
        footer(canvas, doc)

    def later_page(canvas, doc) -> None:
        marks(canvas)
        canvas.saveState()
        canvas.setFont(regular, 7.6)
        canvas.setFillColor(MUTED)
        top = " · ".join(part for part in (head.get("sender_name"), letter["subject"], day(letter["issue_date"])) if part)
        text, size = _fit(top, regular, 7.6, TEXT_WIDTH)
        canvas.setFont(regular, size)
        canvas.drawString(LEFT, PAGE_HEIGHT - 16 * mm, text)
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(.4)
        canvas.line(LEFT, PAGE_HEIGHT - 18 * mm, PAGE_WIDTH - RIGHT, PAGE_HEIGHT - 18 * mm)
        canvas.restoreState()
        footer(canvas, doc)

    story: list[Any] = [Paragraph(_text(letter["subject"]), styles["subject"]), *content]

    output = BytesIO()
    frame = dict(leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc = BaseDocTemplate(output, pagesize=A4, invariant=1, title=letter["subject"],
                          author=head.get("sender_name") or "", creator="ImmoManager Pro",
                          leftMargin=LEFT, rightMargin=RIGHT, topMargin=LATER_BODY_TOP, bottomMargin=FOOTER_TOP)
    doc.addPageTemplates([
        PageTemplate(id="first", onPage=first_page, autoNextPageTemplate="later",
                     frames=[Frame(LEFT, FOOTER_TOP, TEXT_WIDTH, PAGE_HEIGHT - FIRST_BODY_TOP - FOOTER_TOP,
                                   id="first-body", **frame)]),
        PageTemplate(id="later", onPage=later_page,
                     frames=[Frame(LEFT, FOOTER_TOP, TEXT_WIDTH, PAGE_HEIGHT - LATER_BODY_TOP - FOOTER_TOP,
                                   id="later-body", **frame)]),
    ])
    doc.build(story)
    return output.getvalue()
