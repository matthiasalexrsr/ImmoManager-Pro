"""PDF of a maintenance protocol (Abnahme, Begehung, Ortstermin) from its frozen content.

The PDF shows exactly the content that is archived with it (maintenance_projects
_protocol_content) and the photos the protocol names, scaled down; the hash of that
content is printed, so the paper copy names the archived evidence.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

from fastapi import HTTPException
from PIL import Image as PILImage
from PIL import ImageOps, UnidentifiedImageError
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, SimpleDocTemplate, Spacer, Table, TableStyle

from .housing_confirmation_render import _FILL, _MUTED, _RULE, _facts, _fonts, _p, _section, _styles

TITLES = {"acceptance": "Abnahmeprotokoll", "inspection": "Begehungsprotokoll", "site_visit": "Protokoll Ortstermin"}
RESULTS = {"accepted": "Abgenommen", "accepted_with_defects": "Abgenommen mit Mängeln",
           "refused": "Abnahme verweigert"}
SEVERITIES = {"minor": "geringfügig", "major": "erheblich", "critical": "kritisch"}
PHOTO_EDGE = 1400          # pixels: enough to see a defect, small enough for the archive


def _date(value: str | None) -> str:
    return date.fromisoformat(value).strftime("%d.%m.%Y") if value else "—"


def _money(value: float) -> str:
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €"


def _scaled(data: bytes, photo_id: str) -> tuple[BytesIO, int, int]:
    try:
        with PILImage.open(BytesIO(data)) as source:
            picture = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(409, f"Das Foto {photo_id} lässt sich nicht als Bild lesen.") from None
    picture.thumbnail((PHOTO_EDGE, PHOTO_EDGE))
    output = BytesIO()
    picture.save(output, format="JPEG", quality=82, optimize=True)
    output.seek(0)
    return output, picture.width, picture.height


def _photo_cell(photo: dict, data: bytes | None, styles, width: float) -> Any:
    caption = photo.get("caption") or "Foto"
    if data is None:
        return _p(f"{caption} (Datei fehlt)", styles["small"])
    stream, pixel_width, pixel_height = _scaled(data, photo["id"])
    scale = min(width / pixel_width, (70 * mm) / pixel_height)
    return [Image(stream, width=pixel_width * scale, height=pixel_height * scale),
            _p(f"{caption} · SHA-256 {str(photo.get('sha256') or '')[:16]}…", styles["small"])]


def render_protocol_pdf(content: dict, photos: dict[str, bytes], *, draft: bool = False,
                        content_sha256: str | None = None) -> bytes:
    regular, _ = _fonts()
    styles = _styles()
    width = A4[0] - 36 * mm
    fields = content["fields"]
    title = TITLES.get(fields["protocol_type"], "Protokoll")
    output = BytesIO()

    def decorate(canvas, doc):
        canvas.saveState()
        if draft:
            canvas.setFillColor(_RULE)
            canvas.setFont(regular, 64)
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "ENTWURF")
            canvas.rotate(-35)
            canvas.translate(-A4[0] / 2, -A4[1] / 2)
        canvas.setStrokeColor(_RULE)
        canvas.setLineWidth(0.4)
        canvas.line(doc.leftMargin, 14 * mm, A4[0] - doc.rightMargin, 14 * mm)
        canvas.setFillColor(_MUTED)
        canvas.setFont(regular, 7.3)
        canvas.drawString(doc.leftMargin, 9.5 * mm, f"{title} · {content['case']['title']}"[:110])
        canvas.drawRightString(A4[0] - doc.rightMargin, 9.5 * mm, f"Seite {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(output, pagesize=A4, invariant=1, title=title, author="ImmoManager",
                            leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=20 * mm)
    location = content["property"]
    facts = [
        ("Objekt", " · ".join(x for x in (location.get("name"), location.get("address")) if x) or "—"),
        ("Einheit", (content.get("unit") or {}).get("label") or "—"),
        ("Akte", content["case"]["title"]),
        ("Datum", _date(fields["protocol_date"])),
        ("Teilnehmende", fields.get("participants") or "—"),
    ]
    if content.get("work_package"):
        facts.append(("Arbeitspaket", content["work_package"]["title"]))
    if content.get("order"):
        order = content["order"]
        facts.append(("Auftrag", " · ".join(x for x in (
            order.get("order_number"), order.get("supplier_name"), _money(order["gross_amount"])) if x)))
    if fields.get("result"):
        facts.append(("Ergebnis", RESULTS.get(fields["result"], fields["result"])))
    story: list[Any] = [
        _p(title.upper(), styles["title"]),
        _p(fields.get("title") or content["case"]["title"], styles["subtitle"]),
        _section("Angaben", styles, width), Spacer(1, 4), _facts(facts, styles, width), Spacer(1, 9),
    ]
    if fields.get("notes"):
        story += [_section("Bemerkungen", styles, width), Spacer(1, 4), _p(fields["notes"], styles["body"]),
                  Spacer(1, 9)]

    defects = fields.get("defects") or []
    story += [_section(f"Mängel ({len(defects)})", styles, width), Spacer(1, 4)]
    if defects:
        rows = [[_p(text, styles["table_bold"]) for text in ("Nr.", "Mangel", "Ort", "Gewicht", "Frist")]]
        for index, defect in enumerate(defects, 1):
            described = defect["title"] + (f"\n{defect['description']}" if defect.get("description") else "")
            if defect.get("photo_ids"):
                described += f"\nFotos: {len(defect['photo_ids'])}"
            rows.append([_p(str(index), styles["table"]), _p(described, styles["table"]),
                         _p(defect.get("location") or "—", styles["table"]),
                         _p(SEVERITIES.get(defect.get("severity"), "—"), styles["table"]),
                         _p(_date(defect.get("due_date")), styles["table"])])
        table = Table(rows, colWidths=[10 * mm, width - 92 * mm, 32 * mm, 24 * mm, 26 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _FILL), ("BOX", (0, 0), (-1, -1), 0.45, _RULE),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, _RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(table)
    else:
        story.append(_p("Keine Mängel festgestellt.", styles["body"]))
    story.append(Spacer(1, 9))

    if content.get("photos"):
        story += [_section(f"Fotos ({len(content['photos'])})", styles, width), Spacer(1, 4)]
        cell = (width - 6 * mm) / 2
        cells = [_photo_cell(photo, photos.get(photo["id"]), styles, cell) for photo in content["photos"]]
        grid = [cells[index:index + 2] + [""] * (2 - len(cells[index:index + 2])) for index in range(0, len(cells), 2)]
        table = Table(grid, colWidths=[cell + 3 * mm, cell + 3 * mm])
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        story += [table, Spacer(1, 9)]

    closing = []
    if draft:
        closing.append(_p("Entwurf – noch nicht abgeschlossen und nicht archiviert.", styles["small"]))
    else:
        by = (content.get("finalized_by") or {}).get("name") or "—"
        stamp = (content.get("finalized_at") or "")[:16].replace("T", " ")
        closing.append(_p(f"Abgeschlossen am {stamp} UTC von {by}. Das Protokoll ist als unveränderliches "
                          "Original archiviert.", styles["small"]))
        if content_sha256:
            closing.append(_p(f"Prüfsumme des Inhalts (SHA-256): {content_sha256}", styles["small"]))
    closing += [Spacer(1, 16), Table([["", ""], [
        _p("________________________________\nAuftraggeber / Verwaltung", styles["signature"]),
        _p("________________________________\nAuftragnehmer", styles["signature"])]],
        colWidths=[width / 2, width / 2])]
    story.append(KeepTogether(closing))
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output.getvalue()
