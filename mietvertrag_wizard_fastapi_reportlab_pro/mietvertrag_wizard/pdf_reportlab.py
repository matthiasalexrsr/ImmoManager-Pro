"""Serverseitige PDF-Erzeugung (ReportLab).

Ziel: robuste, offline-fähige PDF-Erstellung ohne Browser-Abhängigkeiten.

Eingabeformat:
  Das JSON entspricht dem Output des Wizards (collectFormData / exportWizardData).
  Kerndaten werden vor der PDF-Erzeugung validiert; optionale Felder werden unterdrückt.
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal, localcontext
from html import escape
from typing import Any, Dict, List

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (  # type: ignore
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .pdf_theme import (
    BOTTOM_MARGIN,
    CONTENT_WIDTH,
    LEFT_MARGIN,
    RIGHT_MARGIN,
    TOP_MARGIN,
    contract_styles,
    data_table_style,
    decorate_page,
    party_table_style,
    section_heading,
    signature_table_style,
    title_block,
)
from .validation import _has_exact_cents, parse_money_decimal, validate_contract_payload

# -----------------------------
# Hochwertiges Layout / Textbausteine
# -----------------------------

CLAUSE_TEXTS: Dict[str, str] = {
    "schoenheits": "Der Mieter übernimmt die laufenden Schönheitsreparaturen in den Mieträumen im üblichen Umfang, soweit gesetzlich zulässig. Art und Umfang richten sich nach dem Zustand der Räume und dem Grad der Abnutzung.",
    "klein": "Kleinreparaturen an Teilen der Mietsache, die dem häufigen Zugriff des Mieters ausgesetzt sind, trägt der Mieter bis zu den vereinbarten Höchstgrenzen, soweit gesetzlich zulässig.",
    "tierhaltung": "Die Haltung von Kleintieren ist in der Regel gestattet. Die Haltung von Hunden oder Katzen sowie sonstigen Tieren, die typischerweise zu Beeinträchtigungen führen können, bedarf der vorherigen Zustimmung des Vermieters.",
    "untervermietung": "Eine Untervermietung oder sonstige Gebrauchsüberlassung an Dritte bedarf der vorherigen Zustimmung des Vermieters. Gesetzliche Ansprüche des Mieters auf Erteilung der Erlaubnis bleiben unberührt.",
    "besichtigung": "Der Vermieter ist nach rechtzeitiger Ankündigung berechtigt, die Mieträume aus sachlichem Anlass zu besichtigen. Dabei sind berechtigte Interessen des Mieters zu berücksichtigen.",
    "modernisierung": "Der Mieter hat Erhaltungs- und Modernisierungsmaßnahmen nach Maßgabe der gesetzlichen Vorschriften zu dulden. Der Vermieter kündigt Maßnahmen rechtzeitig an und bemüht sich um eine zumutbare Durchführung.",
    "garten": "Soweit eine Garten- oder Außenflächennutzung vereinbart ist, hat der Mieter diese pfleglich zu behandeln. Veränderungen (z. B. bauliche Anlagen, größere Bepflanzungen) bedürfen der Zustimmung des Vermieters.",
    "mehrere": "Sind mehrere Personen Mieter, haften sie für Verpflichtungen aus diesem Vertrag als Gesamtschuldner.",
    "hausordnung": "Der Mieter verpflichtet sich, die Hausordnung einzuhalten, soweit sie wirksam Bestandteil dieses Vertrags ist.",
    "umbauten": "Bauliche Veränderungen und Einbauten bedürfen der vorherigen Zustimmung des Vermieters. Bei Mietende kann der Vermieter die Wiederherstellung des ursprünglichen Zustands verlangen.",
    "haftung": "Schäden an der Mietsache hat der Mieter unverzüglich anzuzeigen. Unterbleibt die Anzeige, haftet der Mieter für daraus entstehende Folgeschäden nach den gesetzlichen Vorschriften.",
    "rauchmelder": "Soweit Rauchwarnmelder in der Mietsache vorhanden sind, ist der Mieter verpflichtet, Störungen unverzüglich mitzuteilen und im Rahmen der gesetzlichen/vertraglichen Regelungen mitzuwirken.",
    "schriftform": "Änderungen und Ergänzungen dieses Vertrags sollen in Textform erfolgen; zwingende gesetzliche Formerfordernisse bleiben unberührt.",
    "ruhezeiten": "Der Mieter hat die üblichen Ruhezeiten einzuhalten und Rücksicht auf Hausbewohner und Nachbarn zu nehmen.",
    "instandhaltung": "Der Mieter verpflichtet sich zu pfleglichem Umgang mit der Mietsache; kleinere, zumutbare Maßnahmen im täglichen Gebrauch (z. B. Leuchtmittel) führt der Mieter selbst aus.",
}


def _fmt_date_de(s: str | None) -> str:
    if not s:
        return ""
    s = str(s).strip()
    # Erwartet TT.MM.JJJJ
    if len(s) == 10 and s[2] == "." and s[5] == ".":
        return s
    # ISO fallback
    try:
        dt = datetime.fromisoformat(s)
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return s


def _parse_money(x: Any) -> Decimal | None:
    try:
        value = parse_money_decimal(x)
    except ValueError:
        return None
    if value is None or not value.is_finite() or not _has_exact_cents(value):
        return None
    return value


def _sum_money(values: tuple[Any, ...]) -> Decimal:
    parsed = [value for value in (_parse_money(item) for item in values) if value is not None]
    if not parsed:
        return Decimal("0")
    integer_digits = max(
        max(len(value.as_tuple().digits) + value.as_tuple().exponent, 1)
        for value in parsed
    )
    fractional_digits = max(max(-value.as_tuple().exponent, 0) for value in parsed)
    with localcontext() as context:
        context.prec = max(28, integer_digits + fractional_digits + 2)
        return sum(parsed, Decimal("0"))


def _fmt_eur(x: Any) -> str:
    value = _parse_money(x)
    if value is None:
        raw = str(x or "").strip()
        return raw + " €" if raw and "€" not in raw else raw
    euros = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return euros + " €"


def _escape_markup(value: Any) -> Any:
    if isinstance(value, str):
        return escape(value, quote=False)
    if isinstance(value, list):
        return [_escape_markup(item) for item in value]
    if isinstance(value, dict):
        return {key: _escape_markup(item) for key, item in value.items()}
    return value


def _join_address(p: Dict[str, Any]) -> str:
    parts = []
    if p.get("strasse"):
        parts.append(str(p["strasse"]))
    plz = str(p.get("plz") or "").strip()
    ort = str(p.get("ort") or "").strip()
    if plz or ort:
        parts.append((plz + " " + ort).strip())
    return "\n".join(parts)


def _party_block(title: str, persons: List[Dict[str, Any]]) -> str:
    if not persons:
        return f"{title}: –"
    lines: List[str] = [f"<b>{title}</b>"]
    for i, p in enumerate(persons, start=1):
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        lines.append(f"{i}. {name}")
        addr = _join_address(p)
        if addr:
            lines.append(addr.replace("\n", "<br/>") )
        tel = str(p.get("telefon") or "").strip()
        email = str(p.get("email") or "").strip()
        extra = ""
        if tel:
            extra += f"Tel.: {tel} "
        if email:
            extra += f"E-Mail: {email}"
        if extra.strip():
            lines.append(extra.strip())
        lines.append("<br/>")
    return "<br/>".join(lines)


def build_contract_pdf(data: Dict[str, Any]) -> bytes:
    """Erzeugt ein validiertes PDF als Bytes."""

    validate_contract_payload(data)
    data = _escape_markup(data)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title="Wohnraum-Mietvertrag",
        author="ImmoManager Pro",
    )

    styles = contract_styles()
    base = styles["base"]
    base_just = styles["body"]
    small = styles["small"]

    story: List[Any] = []

    story.append(title_block(styles, CONTENT_WIDTH))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Zwischen den nachfolgend genannten Parteien wird folgender Mietvertrag geschlossen.", base_just))
    story.append(Spacer(1, 8))

    vermieter = data.get("vermieter") or []
    mieter = data.get("mieter") or []

    parties_table = Table(
        [
            [Paragraph("<b>Vermieter</b>", base), Paragraph("<b>Mieter</b>", base)],
            [Paragraph(_party_block("", vermieter), base), Paragraph(_party_block("", mieter), base)],
        ],
        colWidths=[CONTENT_WIDTH / 2, CONTENT_WIDTH / 2],
    )
    parties_table.setStyle(party_table_style())
    story.append(parties_table)
    story.append(Spacer(1, 8))

    # § 1 Mieträume
    obj = data.get("objekt") or {}
    story.append(section_heading("§ 1 Mieträume", styles, CONTENT_WIDTH))
    story.append(Spacer(1, 4))
    addr = " ".join([str(obj.get("strasse") or "").strip(), str(obj.get("plz") or "").strip(), str(obj.get("ort") or "").strip()]).strip()
    art = str(obj.get("art") or "Wohnung")
    wf = str(obj.get("wohnflaeche") or "").strip()
    geschoss = str(obj.get("geschoss") or "").strip()
    zimmer = str(obj.get("zimmer") or "").strip()
    p1 = f"Vermietet wird eine {art} in {addr}."
    details = []
    if wf:
        details.append(f"Wohnfläche ca. {wf} m²")
    if geschoss:
        details.append(f"Geschoss: {geschoss}")
    if zimmer:
        details.append(f"Zimmer: {zimmer}")
    if details:
        p1 += " (" + ", ".join(details) + ")"
    story.append(Paragraph(p1, base_just))
    nutzung = str(obj.get("nutzung") or "").strip()
    if nutzung:
        story.append(Paragraph(f"Nutzungszweck: {nutzung}", base))

    # Schlüssel
    sch = (obj.get("schluessel") or {})
    if sch:
        line = []
        for key, label in [
            ("haus", "Hausschlüssel"),
            ("wohnung", "Wohnungsschlüssel"),
            ("zimmer", "Zimmerschlüssel"),
            ("boden", "Bodenraumschlüssel"),
            ("keller", "Kellerschlüssel"),
            ("briefkasten", "Briefkastenschlüssel"),
        ]:
            val = str(sch.get(key) or "").strip()
            if val and val != "0":
                line.append(f"{label}: {val}")
        sonst = str(sch.get("sonstige") or "").strip()
        if sonst:
            line.append(f"Sonstige: {sonst}")
        if line:
            story.append(Paragraph("Schlüssel: " + "; ".join(line) + ".", base))

    # § 2 Mietzeit
    mietzeit = data.get("mietzeit") or {}
    story.append(section_heading("§ 2 Mietzeit", styles, CONTENT_WIDTH))
    story.append(Spacer(1, 4))
    beginn = _fmt_date_de(mietzeit.get("beginn"))
    art_m = str(mietzeit.get("art") or "unbefristet")
    ende = _fmt_date_de(mietzeit.get("ende"))
    if art_m == "befristet" and ende:
        story.append(Paragraph(f"Das Mietverhältnis beginnt am {beginn} und endet am {ende}.", base_just))
        grund = str(mietzeit.get("grund") or "").strip()
        if grund:
            story.append(Paragraph(f"Befristungsgrund: {grund}.", base))
    else:
        story.append(Paragraph(f"Das Mietverhältnis beginnt am {beginn} und läuft auf unbestimmte Zeit.", base_just))

    if mietzeit.get("kuendigungAusschluss") and mietzeit.get("kuendigungBis"):
        story.append(Paragraph(f"Die Parteien verzichten wechselseitig auf ihr Recht zur ordentlichen Kündigung bis zum { _fmt_date_de(mietzeit.get('kuendigungBis')) }.", base))

    # § 3 Miete
    miete = data.get("miete") or {}
    story.append(section_heading("§ 3 Miete", styles, CONTENT_WIDTH))
    story.append(Spacer(1, 4))
    grundmiete = miete.get("grund")
    betrieb = miete.get("betrieb")
    heizung = miete.get("heizung")

    rows = [["Position", "Betrag", "Einheit"]]
    if grundmiete:
        rows.append(["Grundmiete", _fmt_eur(grundmiete), "pro Monat"])
    if betrieb:
        rows.append(["Betriebskosten-VZ", _fmt_eur(betrieb), "pro Monat"])
    if heizung:
        rows.append(["Heizkosten-VZ", _fmt_eur(heizung), "pro Monat"])

    total = _sum_money((grundmiete, betrieb, heizung))
    if total > 0:
        euros = f"{total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"
        rows.append(["Gesamt (monatlich)", euros, "pro Monat"])

    if len(rows) > 1:
        t = Table(
            rows,
            colWidths=[CONTENT_WIDTH * 0.52, CONTENT_WIDTH * 0.25, CONTENT_WIDTH * 0.23],
        )
        t.setStyle(data_table_style(last_row=len(rows) - 1))
        t.setStyle(TableStyle([("ALIGN", (1, 1), (1, -1), "RIGHT")]))
        story.append(t)

    if miete.get("kaution"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"Die Mietkaution beträgt {_fmt_eur(miete.get('kaution'))}.", base_just))

    if miete.get("erhoehung") == "staffel":
        staffeln = miete.get("staffeln") or []
        rows = [["ab Monat", "Grundmiete"]]
        for s in staffeln:
            ab = str(s.get("ab") or "").strip()
            betrag = _fmt_eur(s.get("betrag"))
            if ab and betrag:
                rows.append([ab, betrag])
        if len(rows) > 1:
            story.append(Spacer(1, 4))
            t = Table(rows, colWidths=[45 * mm, 48 * mm])
            t.setStyle(data_table_style())
            story.append(Spacer(1, 6))
            story.append(KeepTogether([
                Paragraph("Staffelmiete", ParagraphStyle("bh", parent=base, fontName="Helvetica-Bold")),
                Spacer(1, 2),
                t,
            ]))

    if miete.get("erhoehung") == "index":
        idx = str(miete.get("indexAusgang") or "").strip()
        txt = "Es wird eine Indexmiete vereinbart."
        if idx:
            txt += f" Ausgangsindex: {idx}."
        story.append(Paragraph(txt, base))

    # § 4 Betriebskosten (hier als allgemeiner Absatz)
    story.append(section_heading("§ 4 Betriebskosten", styles, CONTENT_WIDTH))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Neben der Grundmiete trägt der Mieter die Betriebskosten nach den gesetzlichen Vorschriften, soweit sie tatsächlich anfallen. Art und Umfang richten sich nach der Betriebskostenverordnung sowie den im Vertrag getroffenen Vereinbarungen.",
        base_just,
    ))

    # § 5 Zahlung
    zahlung = data.get("zahlung") or {}
    story.append(section_heading("§ 5 Zahlung der Miete", styles, CONTENT_WIDTH))
    story.append(Spacer(1, 4))
    fa = str(zahlung.get("faelligkeit") or "").strip()
    if fa:
        story.append(Paragraph(f"Die Miete ist monatlich im Voraus spätestens {fa} zu zahlen.", base))
    else:
        story.append(Paragraph("Die Miete ist monatlich im Voraus bis zum dritten Werktag eines jeden Monats zu zahlen.", base))
    iban = str(zahlung.get("iban") or "").strip()
    bic = str(zahlung.get("bic") or "").strip()
    if iban or bic:
        story.append(Paragraph("Zahlung auf folgendes Konto des Vermieters:", base))
        if iban:
            story.append(Paragraph(f"IBAN: {iban}", base))
        if bic:
            story.append(Paragraph(f"BIC: {bic}", base))
    mandat = data.get("mandat") or {}
    if mandat.get("iban") or mandat.get("bic") or mandat.get("inhaber"):
        story.append(Spacer(1, 4))
        story.append(Paragraph("SEPA-Lastschriftmandat (optional):", base))
        if mandat.get("inhaber"):
            story.append(Paragraph(f"Kontoinhaber: {mandat.get('inhaber')}", base))
        if mandat.get("iban"):
            story.append(Paragraph(f"IBAN: {mandat.get('iban')}", base))
        if mandat.get("bic"):
            story.append(Paragraph(f"BIC: {mandat.get('bic')}", base))

    # § 6 Weitere Vereinbarungen
    story.append(section_heading("§ 6 Weitere Vereinbarungen", styles, CONTENT_WIDTH))
    story.append(Spacer(1, 4))
    clauses = data.get("clauses") or {}
    added = 0

    for key, title in [
        ("schoenheits", "Schönheitsreparaturen"),
        ("klein", "Kleinreparaturen"),
        ("tierhaltung", "Tierhaltung"),
        ("untervermietung", "Untervermietung"),
        ("besichtigung", "Besichtigungsrecht"),
        ("modernisierung", "Modernisierung"),
        ("garten", "Gartennutzung"),
        ("mehrere", "Mehrere Mieter"),
        ("hausordnung", "Hausordnung"),
        ("umbauten", "Bauliche Veränderungen"),
        ("haftung", "Haftung / Anzeigepflicht"),
        ("rauchmelder", "Rauchwarnmelder"),
        ("schriftform", "Schriftform"),
        ("ruhezeiten", "Ruhezeiten"),
        ("instandhaltung", "Instandhaltung"),
    ]:
        if clauses.get(key):
            body = CLAUSE_TEXTS.get(key, "")
            story.append(Paragraph(f"<b>{title}.</b> {body}", base_just))
            added += 1

    sonst = str(data.get("sonstigeVereinbarungen") or "").strip()
    if sonst:
        story.append(Spacer(1, 6))
        story.append(Paragraph("<b>Individuelle Vereinbarungen</b>", base))
        story.append(Paragraph(sonst.replace("\n", "<br/>"), base_just))
        added += 1

    if added == 0:
        story.append(Paragraph("Es wurden keine weiteren Vereinbarungen getroffen.", base))

    story.append(Spacer(1, 12))
    signature_start = len(story)
    story.append(section_heading("Unterzeichnung", styles, CONTENT_WIDTH))
    story.append(Spacer(1, 5))
    story.append(Paragraph("Ort, Datum: ________________________________________________", base))
    story.append(Spacer(1, 7))

    # Unterschriften: eine Zeile je Partei
    sig_rows = []
    max_len = max(len(vermieter), len(mieter), 1)
    for i in range(max_len):
        v_name = (vermieter[i].get("name") if i < len(vermieter) else "") or ""
        m_name = (mieter[i].get("name") if i < len(mieter) else "") or ""
        sig_rows.append([
            Paragraph(
                f"<b>Vermieter {i + 1}</b><br/><br/>"
                f"________________________________<br/>{v_name}",
                styles["signature"],
            ),
            Paragraph(
                f"<b>Mieter {i + 1}</b><br/><br/>"
                f"________________________________<br/>{m_name}",
                styles["signature"],
            ),
        ])
    sig_table = Table(sig_rows, colWidths=[CONTENT_WIDTH / 2, CONTENT_WIDTH / 2])
    sig_table.setStyle(signature_table_style())
    story.append(sig_table)
    story.append(Spacer(1, 5))
    story.append(Paragraph("Zwei gleichlautende Ausfertigungen für die Vertragsparteien.", small))
    story[signature_start:] = [KeepTogether(story[signature_start:])]

    doc.build(story, onFirstPage=decorate_page, onLaterPages=decorate_page)
    return buffer.getvalue()
