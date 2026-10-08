"""Deterministic PDF of a handover protocol (Übergabeprotokoll) from its reviewed facts.

The same facts and photos always give the same bytes (ReportLab invariant mode,
photos re-encoded deterministically), so the reviewed preview and the archived
original are byte-identical.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

from PIL import Image as PILImage
from PIL import ImageOps
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, KeepTogether, SimpleDocTemplate, Spacer, Table, TableStyle

from .housing_confirmation_render import _RULE, _facts, _fonts, _p, _section, _styles

CONDITIONS = {"good": "gut", "fair": "befriedigend", "poor": "mangelhaft", None: "nicht bewertet"}
RESPONSIBLE = {"tenant": "Mieter", "landlord": "Vermieter", "open": "offen / zu klären"}
KEY_TYPES = {"house_door": "Haustür", "apartment_door": "Wohnungstür", "mailbox": "Briefkasten", "cellar": "Keller",
             "garage": "Garage / Stellplatz", "other": "Sonstiger Schlüssel"}
METER_TYPES = {"cold_water": "Kaltwasser", "hot_water": "Warmwasser", "heating": "Heizung", "electricity": "Strom",
               "gas": "Gas", "water": "Wasser"}
TYPES = {"move_in": "Einzug", "move_out": "Auszug"}
PHOTO_EDGE = 1400        # pixels of the longer side in the PDF
PHOTO_QUALITY = 72


def pdf_photo(content: bytes) -> bytes:
    """A photo as embedded in the PDF: upright, RGB, at most PHOTO_EDGE pixels, JPEG (deterministic)."""
    with PILImage.open(BytesIO(content)) as image:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        image.thumbnail((PHOTO_EDGE, PHOTO_EDGE))
        output = BytesIO()
        image.save(output, format="JPEG", quality=PHOTO_QUALITY, optimize=False, progressive=False)
        return output.getvalue()


def _day(value: str | None) -> str:
    return date.fromisoformat(value).strftime("%d.%m.%Y") if value else "—"


def _number(value: float) -> str:
    text = f"{value:,.3f}".rstrip("0").rstrip(".")
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _table(rows: list[list[Any]], widths: list[float], styles) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F3F4")),
        ("BOX", (0, 0), (-1, -1), 0.45, _RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def render_pdf(review: dict, photos: dict[str, bytes]) -> bytes:
    """Render the reviewed protocol; `photos` maps photo ids to their pdf_photo() bytes."""
    protocol, source = review["protocol"], review["source"]
    styles = _styles()
    regular, _ = _fonts()
    head, cell = styles["table_bold"], styles["table"]
    width = A4[0] - 32 * mm
    kind = TYPES[protocol["protocol_type"]]
    photo_number = {photo["id"]: index for index, photo in enumerate(review["photos"], 1)}
    room_number = {room["id"]: index for index, room in enumerate(review["rooms"], 1)}

    def photos_of(field: str, identifier: str) -> str:
        numbers = [str(photo_number[p["id"]]) for p in review["photos"] if p.get(field) == identifier]
        return ", ".join(numbers) or "—"

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(_RULE)
        canvas.setLineWidth(0.4)
        canvas.line(doc.leftMargin, 13 * mm, A4[0] - doc.rightMargin, 13 * mm)
        canvas.setFont(regular, 7.3)
        canvas.setFillColor(colors.HexColor("#666A70"))
        canvas.drawString(doc.leftMargin, 9 * mm,
                          f"Übergabeprotokoll {kind} · Vertrag {source['contract']['contract_number']}")
        canvas.drawRightString(A4[0] - doc.rightMargin, 9 * mm, f"Seite {doc.page}")
        canvas.restoreState()

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, invariant=1, title=f"Übergabeprotokoll {kind}", author="ImmoManager",
                            leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=19 * mm)
    prop, unit, contract, tenant = source["property"], source["unit"], source["contract"], source["tenant"]
    address = "\n".join(part for part in (prop.get("address_line"),
                                          " ".join(v for v in (prop.get("postal_code"), prop.get("city")) if v))
                        if part)
    story: list[Any] = [
        _p(f"ÜBERGABEPROTOKOLL – {kind.upper()}", styles["title"]),
        _p(f"Wohnungsübergabe am {_day(protocol['protocol_date'])} · Ausfertigung zur Unterzeichnung",
           styles["subtitle"]),
    ]
    correction = review["correction_of"]
    if correction is not None:
        story += [_facts([("Korrektur", f"Diese Fassung korrigiert das Übergabeprotokoll vom "
                                        f"{_day(correction.get('protocol_date'))} (Original-PDF SHA-256 "
                                        f"{correction.get('pdf_sha256', '')[:16]}…). Das frühere Original bleibt "
                                        "unverändert archiviert.")], styles, width), Spacer(1, 8)]
    story += [
        _section("Objekt und Mietverhältnis", styles, width), Spacer(1, 4),
        _facts([
            ("Objekt", "\n".join(part for part in (prop.get("name"), address) if part)),
            ("Einheit", unit.get("label") or "—"),
            ("Mietvertrag", f"{contract['contract_number']} · Beginn {_day(contract.get('start_date'))}"
                            + (f" · Ende {_day(contract.get('end_date'))}" if contract.get("end_date") else "")),
            ("Mieter", tenant.get("full_name") or "—"),
            ("Vermieter / Eigentümer", source["portfolio"].get("owner_name") or source["portfolio"].get("name") or "—"),
            ("Übergabe", f"{kind} am {_day(protocol['protocol_date'])}"),
            ("Anwesend", f"Mieter: {'ja' if protocol['tenant_present'] else 'nein'} · "
                         f"Vermieter / Beauftragte: {'ja' if protocol['landlord_present'] else 'nein'}"),
            ("Gesamtzustand", CONDITIONS.get(protocol.get("overall_condition"), "nicht bewertet")),
        ], styles, width),
        Spacer(1, 9), _section("Räume", styles, width), Spacer(1, 4),
    ]
    if review["rooms"]:
        rows = [[_p(text, head) for text in ("Nr.", "Raum", "Zustand", "Bemerkungen", "Fotos")]]
        rows += [[_p(str(index), cell), _p(room["name"], cell), _p(CONDITIONS.get(room.get("condition"), "—"), cell),
                  _p(room.get("notes") or "—", cell), _p(photos_of("room_id", room["id"]), cell)]
                 for index, room in enumerate(review["rooms"], 1)]
        story.append(_table(rows, [10 * mm, 40 * mm, 26 * mm, width - 96 * mm, 20 * mm], styles))
    else:
        story.append(_p("Keine Räume erfasst.", styles["body"]))

    story += [Spacer(1, 9), _section("Mängel und Vereinbarungen", styles, width), Spacer(1, 4)]
    if review["defects"]:
        rows = [[_p(text, head) for text in ("Nr.", "Raum", "Mangel", "Verantwortlich", "Vereinbarung / Frist",
                                             "Fotos")]]
        for index, defect in enumerate(review["defects"], 1):
            room = room_number.get(defect.get("room_id") or "")
            room_name = next((r["name"] for r in review["rooms"] if r["id"] == defect.get("room_id")), None)
            agreed = defect.get("remedy") or "—"
            if defect.get("due_date"):
                agreed += f"\nbis {_day(defect['due_date'])}"
            rows.append([_p(str(index), cell), _p(f"{room}. {room_name}" if room else "allgemein", cell),
                         _p(defect["description"], cell), _p(RESPONSIBLE.get(defect.get("responsible"), "—"), cell),
                         _p(agreed, cell), _p(photos_of("defect_id", defect["id"]), cell)])
        story.append(_table(rows, [10 * mm, 30 * mm, width - 128 * mm, 26 * mm, 42 * mm, 20 * mm], styles))
    else:
        story.append(_p("Keine Mängel festgestellt.", styles["body"]))

    story += [Spacer(1, 9), _section("Schlüssel", styles, width), Spacer(1, 4)]
    if review["keys"]:
        move_out = protocol["protocol_type"] == "move_out"
        titles = ("Art", "Bezeichnung", "Ausgehändigt", "Zurückgegeben", "Fehlend") if move_out else (
            "Art", "Bezeichnung", "Übergeben", "Bemerkung")
        rows = [[_p(text, head) for text in titles]]
        for key in review["keys"]:
            if move_out:
                returned = key.get("returned")
                missing = "—" if returned is None else str(max(key["handed_over"] - returned, 0))
                rows.append([_p(KEY_TYPES.get(key["key_type"], key["key_type"]), cell), _p(key.get("label") or "—", cell),
                             _p(str(key["handed_over"]), cell), _p("—" if returned is None else str(returned), cell),
                             _p(missing, cell)])
            else:
                rows.append([_p(KEY_TYPES.get(key["key_type"], key["key_type"]), cell), _p(key.get("label") or "—", cell),
                             _p(str(key["handed_over"]), cell), _p(key.get("notes") or "—", cell)])
        widths = ([38 * mm, width - 128 * mm, 30 * mm, 30 * mm, 30 * mm] if move_out
                  else [38 * mm, width - 98 * mm, 25 * mm, 35 * mm])
        story.append(_table(rows, widths, styles))
    else:
        story.append(_p("Keine Schlüssel erfasst.", styles["body"]))

    story += [Spacer(1, 9), _section(f"Zählerstände am {_day(protocol['protocol_date'])}", styles, width),
              Spacer(1, 4)]
    if review["meter_readings"]:
        rows = [[_p(text, head) for text in ("Zähler", "Zählernummer", "Stand", "Einheit", "Bemerkung", "Fotos")]]
        for reading in review["meter_readings"]:
            medium = METER_TYPES.get(reading["meter_type"], reading["meter_type"])
            if not reading.get("meter_id"):
                medium += " (ohne Zählerzuordnung)"
            rows.append([_p(medium, cell), _p(reading.get("meter_number") or "—", cell),
                         _p(_number(reading["reading_value"]), cell), _p(reading.get("unit") or "—", cell),
                         _p(reading.get("notes") or "—", cell), _p(photos_of("meter_reading_id", reading["id"]), cell)])
        story.append(_table(rows, [36 * mm, 32 * mm, 26 * mm, 16 * mm, width - 130 * mm, 20 * mm], styles))
    else:
        story.append(_p("Keine Zählerstände erfasst.", styles["body"]))

    if protocol.get("notes"):
        story += [Spacer(1, 9), _section("Bemerkungen", styles, width), Spacer(1, 4),
                  _p(protocol["notes"], styles["body"])]
    legacy = [(label, protocol["legacy"].get(name)) for name, label in (
        ("key_count", "Schlüsselanzahl"), ("key_details", "Schlüsseldetails"), ("damages", "Schäden (Freitext)"),
        ("photos", "Fotos (Freitext)")) if protocol["legacy"].get(name) not in (None, "")]
    if legacy:
        story += [Spacer(1, 9), _section("Frühere Angaben", styles, width), Spacer(1, 4),
                  _facts([(label, str(value)) for label, value in legacy], styles, width)]

    signer = styles["signature"]
    tenant_line = (f"Mieter: {protocol.get('tenant_signature') or '—'}" if protocol["tenant_present"]
                   else "Mieter: nicht anwesend")
    signatures = Table([
        [_p("________________________________", signer), _p("________________________________", signer)],
        [_p(tenant_line, signer), _p(f"Vermieter / Beauftragte: {protocol.get('landlord_signature') or '—'}", signer)],
    ], colWidths=[width / 2, width / 2])
    signatures.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story.append(KeepTogether([
        Spacer(1, 12), _section("Bestätigung", styles, width), Spacer(1, 5),
        _p("Die Beteiligten haben die Wohnung gemeinsam begangen und bestätigen die vorstehenden Angaben.",
           styles["body"]),
        Spacer(1, 6), _p(f"Ort: ______________________    Datum: {_day(protocol['protocol_date'])}", styles["body"]),
        Spacer(1, 18), signatures, Spacer(1, 8),
        _p("Dieses Dokument enthält keine elektronische Unterschrift. Abgeschlossene Fassungen bleiben unverändert "
           "im Dokumentarchiv; eine Korrektur erhält ein neues Original.", styles["small"]),
    ]))

    if review["photos"]:
        story += [Spacer(1, 12), _section("Fotos", styles, width), Spacer(1, 5)]
        cells = []
        for photo in review["photos"]:
            image = ImageReader(BytesIO(photos[photo["id"]]))
            pixels_wide, pixels_high = image.getSize()
            box_w, box_h = width / 2 - 6 * mm, 62 * mm
            scale = min(box_w / pixels_wide, box_h / pixels_high)
            where = []
            if photo.get("room_id") in room_number:
                where.append(f"Raum {room_number[photo['room_id']]}")
            if photo.get("defect_id"):
                index = next((i for i, d in enumerate(review["defects"], 1) if d["id"] == photo["defect_id"]), None)
                if index:
                    where.append(f"Mangel {index}")
            label = " · ".join([f"Foto {photo_number[photo['id']]}", *where, photo.get("caption") or ""]).strip(" ·")
            cells.append([Image(BytesIO(photos[photo["id"]]), width=pixels_wide * scale, height=pixels_high * scale),
                          _p(f"{label}\nSHA-256 {photo['sha256'][:16]}…", styles["small"])])
        rows = []
        for index in range(0, len(cells), 2):
            pair = cells[index:index + 2] + ([["", ""]] if len(cells[index:index + 2]) == 1 else [])
            rows += [[pair[0][0], pair[1][0]], [pair[0][1], pair[1][1]]]
        grid = Table(rows, colWidths=[width / 2, width / 2])
        grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(grid)
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output.getvalue()
