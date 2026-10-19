"""Exposé of a re-letting project as a local PDF: the offer, its texts, the energy certificate and photos."""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, KeepTogether, SimpleDocTemplate, Spacer, Table, TableStyle

from .housing_confirmation_render import _RULE, _facts, _fonts, _p, _section, _styles
from .portfolio_scope import require_file_access

logger = logging.getLogger(__name__)
MAX_PHOTOS = 6


def _photo_bytes(file_url: str) -> bytes | None:
    """A photo the reader may see, as JPEG or PNG bytes; anything else is left out of the exposé."""
    from ..routers.files import _file_url_to_key
    from .file_storage import get_file_storage

    try:
        require_file_access(file_url)
        content = get_file_storage().get(_file_url_to_key(file_url))
    except Exception:  # noqa: BLE001 - a missing or foreign file does not stop the exposé
        logger.info("Exposé: photo %s left out", file_url)
        return None
    if not content or not (content.startswith(b"\xff\xd8") or content.startswith(b"\x89PNG")):
        return None
    return content


def _photos(photos: list[Any], width: float) -> list[Any]:
    ordered = sorted(photos, key=lambda p: (not getattr(p, "is_primary", False), getattr(p, "sort_order", 0), p.id))
    cells: list[Any] = []
    for photo in ordered:
        if len(cells) >= MAX_PHOTOS:
            break
        content = _photo_bytes(photo.file_url)
        if content is None:
            continue
        try:
            reader = ImageReader(BytesIO(content))
            w, h = reader.getSize()
        except Exception:  # noqa: BLE001 - an unreadable image is left out
            continue
        box = (width - 6 * mm) / 2
        ratio = min(box / w, 62 * mm / h)
        cells.append(Image(BytesIO(content), width=w * ratio, height=h * ratio))
    if not cells:
        return []
    rows = [cells[i:i + 2] + [""] * (2 - len(cells[i:i + 2])) for i in range(0, len(cells), 2)]
    table = Table(rows, colWidths=[width / 2, width / 2])
    table.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return [table]


def render_expose(offer: dict, photos: list[Any]) -> bytes:
    styles = _styles()
    regular, _ = _fonts()
    project, apartment, building = offer["project"], offer["unit"], offer["property"]
    width = A4[0] - 32 * mm
    title = project.headline or apartment.label or "Exposé"
    address = ", ".join(part for part in (building.address_line, " ".join(
        v for v in (building.postal_code, building.city) if v)) if part)

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(_RULE)
        canvas.setLineWidth(0.4)
        canvas.line(doc.leftMargin, 13 * mm, A4[0] - doc.rightMargin, 13 * mm)
        canvas.setFont(regular, 7.3)
        canvas.setFillColor(colors.HexColor("#666A70"))
        canvas.drawString(doc.leftMargin, 9 * mm, f"Exposé · {address or building.name}")
        canvas.drawRightString(A4[0] - doc.rightMargin, 9 * mm, f"Seite {doc.page}")
        canvas.restoreState()

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, invariant=1, title=title, author="ImmoManager",
                            leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=19 * mm)
    story: list[Any] = [_p(title, styles["title"]), _p(address or building.name or "", styles["subtitle"])]
    story += _photos(photos, width)
    story += [Spacer(1, 4), _section("Eckdaten und Kosten", styles, width), Spacer(1, 4),
              _facts(offer["facts"] or [("Angaben", "noch offen")], styles, width)]
    for heading, text in (("Objektbeschreibung", project.description), ("Ausstattung", project.features_text),
                          ("Lage", project.location_text)):
        if text:
            story += [Spacer(1, 9), KeepTogether([_section(heading, styles, width), Spacer(1, 4),
                                                  _p(text, styles["body"])])]
    if offer["energy"]:
        story += [Spacer(1, 9), KeepTogether([_section("Energieausweis", styles, width), Spacer(1, 4),
                                              _facts(offer["energy"], styles, width)])]
    contact = [(label, value) for label, value in (("Ansprechpartner", project.contact_name),
                                                   ("Telefon", project.contact_phone),
                                                   ("E-Mail", project.contact_email)) if value]
    if contact:
        story += [Spacer(1, 9), KeepTogether([_section("Kontakt", styles, width), Spacer(1, 4),
                                              _facts(contact, styles, width)])]
    story += [Spacer(1, 10), _p("Alle Angaben ohne Gewähr. Dieses Exposé ist kein Vertragsangebot.", styles["small"])]
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output.getvalue()
