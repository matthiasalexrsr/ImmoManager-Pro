"""Serverseitige PDF-Erzeugung (ReportLab).

Ziel: robuste, offline-fähige PDF-Erstellung ohne Browser-Abhängigkeiten.

Eingabeformat:
  Das JSON entspricht dem Output des Wizards (collectFormData / exportWizardData).
  Felder sind optional; fehlende Felder werden unterdrückt.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (  # type: ignore
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether,
)


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


def _fmt_eur(x: Any) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    if not s:
        return ""
    # akzeptiere bereits formatiertes de-DE (1.234,56) oder raw "1234.56"
    # Versuche float
    try:
        s2 = s.replace("€", "").replace(" ", "")
        s2 = s2.replace(".", "").replace(",", ".")
        val = float(s2)
        # de-DE
        euros = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return euros + " €"
    except Exception:
        return s + " €" if "€" not in s else s


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
    """Erzeugt ein PDF als Bytes."""

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=25 * mm,
        bottomMargin=18 * mm,
        title="Wohnraum-Mietvertrag",
    )

    styles = getSampleStyleSheet()
    base = ParagraphStyle(
        "base",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        spaceAfter=4,
    )
    base_just = ParagraphStyle(
        "base_just",
        parent=base,
        alignment=4,  # justify
    )
    h1 = ParagraphStyle(
        "h1",
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=20,
        alignment=1,
        spaceAfter=6,
    )
    h2 = ParagraphStyle(
        "h2",
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=14,
        spaceBefore=8,
        spaceAfter=6,
    )
    h2_box = ParagraphStyle(
        "h2_box",
        parent=h2,
        backColor=colors.whitesmoke,
        borderPadding=6,
    )
    small = ParagraphStyle(
        "small",
        parent=base,
        fontSize=9,
        leading=12,
        textColor=colors.grey,
    )

    def on_page(canvas, doc_obj):
        """Kopf-/Fußzeile (schwarz/weiß-drucktauglich)."""
        canvas.saveState()
        canvas.setStrokeColor(colors.grey)
        canvas.setLineWidth(0.5)
        canvas.line(doc_obj.leftMargin, A4[1] - 18 * mm, A4[0] - doc_obj.rightMargin, A4[1] - 18 * mm)
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.black)
        canvas.drawString(doc_obj.leftMargin, A4[1] - 14 * mm, "Wohnraum-Mietvertrag")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawRightString(A4[0] - doc_obj.rightMargin, A4[1] - 14 * mm, f"Seite {doc_obj.page}")
        canvas.setStrokeColor(colors.lightgrey)
        canvas.line(doc_obj.leftMargin, 14 * mm, A4[0] - doc_obj.rightMargin, 14 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(doc_obj.leftMargin, 10 * mm, "Erstellt mit Mietvertrag-Wizard")
        canvas.restoreState()

    story: List[Any] = []

    title_table = Table(
        [[Paragraph("WOHNRAUM-MIETVERTRAG", ParagraphStyle("t", parent=h1, textColor=colors.black))]],
        colWidths=[A4[0] - doc.leftMargin - doc.rightMargin],
    )
    title_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.append(title_table)
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
        colWidths=[85 * mm, 85 * mm],
    )
    parties_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    )
    story.append(parties_table)
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.black, spaceBefore=4, spaceAfter=6))

    # § 1 Mieträume
    obj = data.get("objekt") or {}
    story.append(Paragraph("§ 1 Mieträume", h2_box))
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
    story.append(Paragraph("§ 2 Mietzeit", h2_box))
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
    story.append(Paragraph("§ 3 Miete", h2_box))
    grund = miete.get("grund")
    betrieb = miete.get("betrieb")
    heizung = miete.get("heizung")

    rows = [["Position", "Betrag", "Einheit"]]
    if grund:
        rows.append(["Grundmiete", _fmt_eur(grund), "pro Monat"])
    if betrieb:
        rows.append(["Betriebskosten-VZ", _fmt_eur(betrieb), "pro Monat"])
    if heizung:
        rows.append(["Heizkosten-VZ", _fmt_eur(heizung), "pro Monat"])

    try:
        def _to_float(v):
            s = str(v).replace("€", "").replace(" ", "")
            s = s.replace(".", "").replace(",", ".")
            return float(s)
        total = 0.0
        for v in (grund, betrieb, heizung):
            if v:
                total += _to_float(v)
        if total > 0:
            euros = f"{total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"
            rows.append(["Gesamt (monatlich)", euros, "pro Monat"])
    except Exception:
        pass

    if len(rows) > 1:
        t = Table(rows, colWidths=[70 * mm, 35 * mm, 30 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.black),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ALIGN", (1, 1), (1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
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
            t = Table(rows, colWidths=[40 * mm, 45 * mm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
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
    story.append(Paragraph("§ 4 Betriebskosten", h2_box))
    story.append(Paragraph(
        "Neben der Grundmiete trägt der Mieter die Betriebskosten nach den gesetzlichen Vorschriften, soweit sie tatsächlich anfallen. Art und Umfang richten sich nach der Betriebskostenverordnung sowie den im Vertrag getroffenen Vereinbarungen.",
        base_just,
    ))

    # § 5 Zahlung
    zahlung = data.get("zahlung") or {}
    story.append(Paragraph("§ 5 Zahlung der Miete", h2_box))
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
    story.append(Paragraph("§ 6 Weitere Vereinbarungen", h2_box))
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

    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.black, spaceBefore=6, spaceAfter=8))
    story.append(Paragraph("Ort, Datum: ______________________________", base))
    story.append(Spacer(1, 10))

    # Unterschriften: eine Zeile je Partei
    sig_rows = []
    max_len = max(len(vermieter), len(mieter), 1)
    for i in range(max_len):
        v_name = (vermieter[i].get("name") if i < len(vermieter) else "") or ""
        m_name = (mieter[i].get("name") if i < len(mieter) else "") or ""
        sig_rows.append([
            Paragraph(f"_________________________<br/><font size=9>Vermieter {i+1}: {v_name}</font>", base),
            Paragraph(f"_________________________<br/><font size=9>Mieter {i+1}: {m_name}</font>", base),
        ])
    sig_table = Table(sig_rows, colWidths=[85 * mm, 85 * mm])
    sig_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(sig_table)
    story.append(Spacer(1, 6))
    story.append(Paragraph("(Zwei gleichlautende Exemplare)", small))

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()
