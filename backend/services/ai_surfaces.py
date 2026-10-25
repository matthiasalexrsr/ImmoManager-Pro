"""The places where a document is read into the application ("KI-Flächen").

Each surface names its task for the AI (`instructions`), the fields of the form it fills and how
each value is checked, the facts of the property that help the AI, the local rules used without an
account, and how an existing record for the same document is found. `ai_reading` runs a reading
for a surface; nothing here writes data.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from ..domain.clock import local_today
from .meter_documents import german_number, plain_number, serial_keys

DOCUMENT_TYPES = ("Mietvertrag", "Rechnung", "Nebenkostenabrechnung", "Protokoll", "Versicherung", "Grundbuchauszug",
                  "Energieausweis", "Betriebskostenabrechnung", "Mahnung", "Kündigung", "Übergabeprotokoll",
                  "Handwerkerrechnung", "Steuerbescheid", "Sonstiges")
# The cost types of the utility statement (services/billing_guide.BETRKV): invoices pass theirs on to cost items, and
# the statement compares them with the year before. Maintenance and administration are not recoverable.
COST_CATEGORIES = ("heating", "hot_water", "water", "electricity", "garbage", "street_cleaning", "cleaning", "garden",
                   "caretaker", "insurance", "property_tax", "elevator", "chimney", "cable", "laundry", "maintenance",
                   "administration", "other")
COST_CATEGORY_LABELS = {"heating": "Heizkosten", "hot_water": "Warmwasser", "water": "Wasser und Abwasser",
                        "electricity": "Allgemeinstrom", "garbage": "Müllabfuhr", "street_cleaning": "Straßenreinigung",
                        "cleaning": "Gebäudereinigung", "garden": "Gartenpflege", "caretaker": "Hauswart",
                        "insurance": "Versicherung", "property_tax": "Grundsteuer", "elevator": "Aufzug",
                        "chimney": "Schornsteinfeger", "cable": "Kabel/Antenne", "laundry": "Wäschepflege",
                        "maintenance": "Instandhaltung", "administration": "Verwaltung", "other": "Sonstiges"}
# what a model may still answer with, and the catalogue's code for it
CHOICE_ALIASES = {"waste": "garbage", "sewage": "water", "cable_tv": "cable", "lighting": "electricity"}
# document types older imports stored as English keys
DOCUMENT_TYPE_LABELS = {"invoice": "Rechnung", "contract": "Vertrag", "receipt": "Beleg", "protocol": "Protokoll",
                        "statement": "Abrechnung", "letter": "Brief", "other": "Sonstiges"}
CONFIDENCE = ("high", "medium", "low")
MAX_MONEY = Decimal("10000000")


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"          # text, long_text, date, money, percent, number, choice, iban, unit, tenant
    choices: tuple[str, ...] = ()
    hint: str = ""
    max_length: int = 200


@dataclass(frozen=True)
class Surface:
    id: str
    label: str
    entry: str                  # where the document is read in, in the words of the menu
    area: str                   # what taking the values over writes (permissions.may_write)
    purpose: str
    instructions: str
    fields: tuple[Field, ...] = ()
    rows: bool = False          # the metering document: lists of costs and readings instead of single fields
    needs_ai: bool = False      # no local rules (a photo of a meter has no text to read)

    def field(self, name: str) -> Optional[Field]:
        return next((field for field in self.fields if field.name == name), None)


DOCUMENT = Surface(
    "document", "Dokumentablage", "Dokumente → Hochladen", "/documents",
    "Ordnet ein hochgeladenes Dokument ein: Art, Titel, Datum, Absender, Gültigkeit und die Einheit oder den Mieter, zu denen es gehört.",
    """Aufgabe: Ordne das angehängte Dokument für die Dokumentablage einer Hausverwaltung ein.
Bestimme die Dokumentart (genau eine der erlaubten), einen kurzen sprechenden Titel (Art, Absender, Bezug, z. B.
"Mietvertrag Wohnung 3 – Anna Alt" oder "Gebäudeversicherung 2026 – Allianz"), das Datum des Dokuments, den Absender,
ein Ablaufdatum, wenn das Dokument eines hat (Energieausweis "gültig bis", Police "Vertragsende", Wartungsnachweis),
und eine Zusammenfassung in zwei bis vier Sätzen. Nenne Einheit und Mieter nur, wenn das Dokument sie eindeutig nennt
und sie in den bekannten Einheiten oder Mietern vorkommen; schreibe sie dann genau so wie dort.""",
    (Field("title", "Titel", max_length=200),
     Field("document_type", "Dokumentart", "choice", DOCUMENT_TYPES),
     Field("document_date", "Datum des Dokuments", "date"),
     Field("sender", "Absender", max_length=200),
     Field("valid_until", "Gültig bis", "date", hint="Ablaufdatum, nur wenn das Dokument eines nennt"),
     Field("description", "Zusammenfassung", "long_text", max_length=1200),
     Field("unit", "Einheit", "unit", hint="Bezeichnung aus den bekannten Einheiten"),
     Field("tenant", "Mieter", "tenant", hint="Name aus den bekannten Mietern")))

INVOICE = Surface(
    "invoice", "Rechnungseingang", "Rechnungsprüfung → Neuer Beleg", "/invoice-review/receipts",
    "Liest eine Eingangsrechnung oder Gutschrift: Lieferant, Nummer, Daten, Beträge je Steuersatz, IBAN, Skonto und Kostenart.",
    """Aufgabe: Lies die angehängte Eingangsrechnung (oder Gutschrift) eines Lieferanten oder Handwerkers für die
Rechnungsprüfung einer Hausverwaltung. Übernimm Lieferant, Rechnungsnummer, Rechnungsdatum, Fälligkeit, den
Leistungszeitraum, Netto, Umsatzsteuersatz, Umsatzsteuer und Brutto, die Bankverbindung (IBAN) des Lieferanten,
den Verwendungszweck, Skonto (Prozent und Tage) und das Zahlungsziel in Tagen. Schlage eine Kostenart vor.
Bei mehreren Steuersätzen nenne als Steuersatz den überwiegenden und schreibe die Aufteilung in notes.
Netto, Steuer und Brutto müssen zusammenpassen; wenn nicht, nenne das in notes und übernimm die Werte des Dokuments.
Ist es eine Gutschrift, setze document_kind auf "credit_note".""",
    (Field("supplier", "Lieferant", max_length=300),
     Field("invoice_number", "Rechnungsnummer", max_length=100),
     Field("invoice_date", "Rechnungsdatum", "date"),
     Field("due_date", "Fällig am", "date"),
     Field("performance_start", "Leistung von", "date"),
     Field("performance_end", "Leistung bis", "date"),
     Field("net_amount", "Netto", "money"),
     Field("vat_rate", "Umsatzsteuersatz (%)", "percent"),
     Field("vat_amount", "Umsatzsteuer", "money"),
     Field("gross_amount", "Brutto", "money"),
     Field("iban", "IBAN des Lieferanten", "iban"),
     Field("payment_reference", "Verwendungszweck", max_length=200),
     Field("skonto_percent", "Skonto (%)", "percent"),
     Field("skonto_days", "Skonto-Frist (Tage)", "number"),
     Field("payment_days", "Zahlungsziel (Tage)", "number"),
     Field("cost_category", "Kostenart", "choice", COST_CATEGORIES),
     Field("document_kind", "Belegart", "choice", ("invoice", "credit_note")),
     Field("description", "Leistung", "long_text", max_length=1000)))

COST_ITEM = Surface(
    "cost_item", "Kostenposition der Nebenkostenabrechnung", "Nebenkostenabrechnung → Beleg einlesen", "/billing/cost-items",
    "Macht aus einer Rechnung oder einem Bescheid eine Kostenposition des Abrechnungszeitraums: Bezeichnung, Betrag, Kostenart, Leistungszeitraum.",
    """Aufgabe: Lies den angehängten Beleg (Rechnung, Bescheid, Jahresabrechnung eines Versorgers oder Dienstleisters)
für die Betriebskostenabrechnung einer Immobilie. Übernimm eine Bezeichnung (Kostenart und Lieferant, z. B.
"Müllabfuhr Stadtreinigung 2025"), den umlagefähigen Gesamtbetrag (brutto, wie ihn der Vermieter bezahlt),
die Kostenart nach § 2 BetrKV und den Leistungszeitraum. Teile, die nicht umlagefähig sind (Reparaturen,
Verwaltung, Mahngebühren), nennst du in notes und rechnest sie nicht in den Betrag ein; setze recoverable=false,
wenn der ganze Beleg nicht umlagefähig ist.""",
    (Field("description", "Bezeichnung", max_length=200),
     Field("amount", "Betrag", "money"),
     Field("cost_category", "Kostenart", "choice", COST_CATEGORIES),
     Field("period_start", "Leistung von", "date"),
     Field("period_end", "Leistung bis", "date"),
     Field("recoverable", "Umlagefähig", "choice", ("true", "false")),
     Field("supplier", "Lieferant", max_length=200),
     Field("invoice_number", "Rechnungsnummer", max_length=100)))

METER_DOCUMENT = Surface(
    "meter_document", "Dokument des Messdienstes", "Nebenkosten-Assistent, Abrechnungen, Zähler → Messdienst-Dokument",
    "/billing/meter-documents",
    "Liest Heizkosten-, Wasser- und Ableseprotokolle von ista, Techem, Brunata-Metrona, Minol, KALO: Kosten, Verbrauchsanteil, Zählerstände.",
    "", rows=True)

METER_PHOTO = Surface(
    "meter_photo", "Zählerfoto", "Zähler → Stand aus Foto", "/meters",
    "Liest Gerätenummer und Stand vom Foto eines Zählers oder Heizkostenverteilers.",
    """Aufgabe: Lies vom angehängten Foto eines Zählers (Wasser, Wärme, Strom, Gas) oder Heizkostenverteilers die
Gerätenummer und den angezeigten Stand. Bei Rollenzählwerken zählen nur die schwarzen Ziffern vor dem Komma; rote
Ziffern oder Nachkommastellen nennst du in notes. Bei elektronischen Heizkostenverteilern den aktuellen Wert, nicht
den Stichtagswert, außer der Nutzer verlangt ihn. Das Ablesedatum nur, wenn es im Bild steht (Display, Zettel).
Die Gerätenummer genau wie im Bild; vergleiche sie mit den bekannten Zählern.""",
    (Field("serial", "Gerätenummer", max_length=60),
     Field("value", "Zählerstand", "number"),
     Field("reading_date", "Ablesedatum", "date"),
     Field("meter_type", "Zählerart", "choice", ("cold_water", "hot_water", "heating", "electricity", "gas", "other"))),
    needs_ai=True)

SURFACES: dict[str, Surface] = {surface.id: surface for surface in (DOCUMENT, INVOICE, COST_ITEM, METER_DOCUMENT, METER_PHOTO)}


# ─── Checking values ─────────────────────────────────────────────────────────

def _text(value: Any, limit: int, *, multiline: bool = False) -> Optional[str]:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = str(value)
    text = "".join(char for char in text if char == "\n" and multiline or ord(char) >= 32)
    text = re.sub(r"[ \t]+", " ", text).strip() if multiline else re.sub(r"\s+", " ", text).strip()
    return text[:limit] or None


def parse_day(value: Any) -> Optional[date]:
    """ISO ("2026-03-01") or German ("01.03.2026", "1.3.26") dates within a sensible range."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    found = None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text[:10]):
            found = date.fromisoformat(text[:10])
        else:
            match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})", text)
            if match:
                day, month, year = (int(part) for part in match.groups())
                found = date(year + 2000 if year < 100 else year, month, day)
    except ValueError:
        return None
    if found is None or not date(1950, 1, 1) <= found <= local_today() + timedelta(days=366 * 30):
        return None
    return found


def _money(value: Any) -> Optional[Decimal]:
    number = plain_number(value)
    if number is None or not number.is_finite() or abs(number) > MAX_MONEY:
        return None
    return number.quantize(Decimal("0.01"))


def clean_value(field: Field, value: Any, facts: dict) -> Any:
    """The value as the form takes it, or None when it does not pass. Never raises for model input."""
    try:
        if field.kind in ("text", "long_text"):
            return _text(value, field.max_length, multiline=field.kind == "long_text")
        if field.kind == "date":
            found = parse_day(value)
            return found.isoformat() if found else None
        if field.kind == "money":
            amount = _money(value)
            return str(amount) if amount is not None else None
        if field.kind in ("percent", "number"):
            number = plain_number(value)
            if number is None or not number.is_finite():
                return None
            if field.kind == "percent" and not Decimal("0") <= number <= Decimal("100"):
                return None
            if field.kind == "number" and abs(number) > Decimal("1000000000"):
                return None
            return str(int(number)) if number == number.to_integral() else format(number.normalize(), "f")
        if field.kind == "choice":
            text = str(value).strip() if isinstance(value, (str, bool)) else None
            if isinstance(value, bool):
                text = "true" if value else "false"
            text = CHOICE_ALIASES.get(text or "", text)
            return text if text in field.choices else None
        if field.kind == "iban":
            from .sepa_rules import compact, iban_problem
            iban = compact(_text(value, 60) or "")
            return iban if iban and iban_problem(iban) is None else None
        if field.kind in ("unit", "tenant"):
            return match_reference(facts.get("units" if field.kind == "unit" else "tenants") or [], value)
    except (InvalidOperation, ValueError, TypeError):
        return None
    return None


def _key(value: Any) -> str:
    return re.sub(r"[^0-9a-zäöüß]", "", str(value or "").casefold())


def match_reference(known: Iterable[dict], value: Any) -> Optional[dict]:
    """A unit or tenant of the property by its label or name: exactly one match, or nothing."""
    wanted = _key(value)
    if not wanted:
        return None
    rows = list(known)
    exact = [row for row in rows if _key(row["label"]) == wanted]
    if len(exact) == 1:
        return {"id": exact[0]["id"], "label": exact[0]["label"]}
    partial = [row for row in rows if wanted in _key(row["label"]) or _key(row["label"]) in wanted and len(_key(row["label"])) >= 3]
    return {"id": partial[0]["id"], "label": partial[0]["label"]} if len(partial) == 1 else None


def clean_values(surface: Surface, raw: Any, facts: dict, *, source: str) -> tuple[dict, list[str]]:
    """{field: {value, evidence, confidence, source}} from model or rule output, and what was dropped."""
    values: dict[str, dict] = {}
    dropped: list[str] = []
    if not isinstance(raw, dict):
        return values, dropped
    for name, item in raw.items():
        field = surface.field(str(name))
        if field is None:
            continue
        entry = item if isinstance(item, dict) else {"value": item}
        if entry.get("value") is None:
            continue
        value = clean_value(field, entry.get("value"), facts)
        if value is None:
            dropped.append(field.label)
            continue
        confidence = entry.get("confidence") if entry.get("confidence") in CONFIDENCE else None
        values[field.name] = {"value": value, "evidence": _text(entry.get("evidence"), 160),
                              "confidence": confidence, "source": source}
    return values, dropped


# ─── Facts that help the AI (and the local matching) ────────────────────────

def facts(store: Any, surface: Surface, params: dict, *, level: str = "standard") -> dict:
    """What the reading knows about the place it was started from. `level`: none, standard (units,
    meters, period) or extended (also tenant names and known suppliers)."""
    known: dict[str, Any] = {}
    property_id = params.get("property_id")
    if not property_id:
        return known
    prop = store.get_property(property_id)
    units = sorted((unit for unit in store.list_units() if unit.property_id == property_id), key=lambda unit: unit.label or "")
    known["property"] = prop.name
    known["units"] = [{"id": unit.id, "label": unit.label} for unit in units if unit.label]
    unit_ids = {unit.id for unit in units}
    if surface.id in ("meter_photo", "meter_document"):
        labels = {unit.id: unit.label for unit in units}
        known["meters"] = [{"id": meter.id, "serial": meter.serial_number, "type": meter.meter_type,
                            "unit": labels.get(meter.unit_id)} for meter in store.list_meters()
                           if meter.unit_id in unit_ids and meter.serial_number][:500]
    if params.get("billing_period_id"):
        period = store.get_billing_period(params["billing_period_id"])
        known["period"] = {"label": period.label, "start": period.start_date.isoformat(), "end": period.end_date.isoformat()}
    if surface.id == "document":
        today = local_today()
        tenants = {contract.tenant_id for contract in store.list_contracts()
                   if contract.unit_id in unit_ids and contract.tenant_id
                   and (contract.end_date is None or contract.end_date >= today - timedelta(days=730))}
        known["tenants"] = sorted(({"id": tenant.id, "label": tenant.full_name} for tenant in store.list_tenants()
                                   if tenant.id in tenants and tenant.full_name), key=lambda row: row["label"])
    if surface.id == "invoice" and level == "extended":
        known["suppliers"] = sorted({invoice.supplier for invoice in store.list_invoices()
                                     if invoice.property_id == property_id and invoice.supplier})[:80]
    return known


def for_model(known: dict, level: str) -> dict:
    """The part of the facts that goes to the provider: never ids, and personal names only at 'extended'."""
    if level == "none":
        return {}
    shown: dict[str, Any] = {}
    for key, value in known.items():
        if key == "units":
            shown["units"] = [row["label"] for row in value]
        elif key == "tenants":
            if level == "extended":
                shown["tenants"] = [row["label"] for row in value]
        elif key == "meters":
            shown["meters"] = [{"serial": row["serial"], "type": row["type"], "unit": row["unit"]} for row in value]
        else:
            shown[key] = value
    return shown


# ─── Local rules (no account) ────────────────────────────────────────────────

_DATE = r"(\d{1,2}\.\d{1,2}\.\d{2,4})"
_AMOUNT = r"(-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}|-?\d+\.\d{2})"
_CATEGORY_WORDS = (("heating", ("heizöl", "fernwärme", "heizung", "brennstoff", "gaslieferung")),
                   ("hot_water", ("warmwasser",)), ("water", ("abwasser", "schmutzwasser", "niederschlagswasser", "wasser")),
                   ("garbage", ("müll", "abfall", "restmüll", "biotonne")),
                   ("street_cleaning", ("straßenreinigung", "winterdienst")), ("electricity", ("allgemeinstrom", "strom")),
                   ("cleaning", ("treppenhausreinigung", "gebäudereinigung", "reinigung")), ("garden", ("garten", "grünpflege")),
                   ("caretaker", ("hausmeister", "hauswart")), ("insurance", ("versicherung", "police")),
                   ("property_tax", ("grundsteuer", "grundbesitzabgaben")), ("elevator", ("aufzug", "fahrstuhl")),
                   ("chimney", ("schornstein", "kaminkehrer")), ("cable", ("kabel", "antenne", "breitband")))


_COMPANY = re.compile(r"\b(GmbH|AG|KG|OHG|GbR|UG|e\.\s?K\.|e\.\s?V\.|mbH|Stadtwerke|Werke|Versorgung|Service|Handwerk|"
                      r"Sanitär|Elektro|Dach|Maler|Gebäude|Hausverwaltung|Versicherung|Energie|Wasser)\b", re.IGNORECASE)


def _sender(lines: list[str], labelled: Any) -> Optional[str]:
    """The sender of a letter: a top line that names a company, else a labelled sender ("Lieferant: …") that
    reads like a name, else the first line."""
    top = [line for line in lines[:6] if 3 <= len(line) <= 120 and not re.search(r"\d{2}\.\d{2}\.\d{2,4}", line)]
    company = next((line for line in top if _COMPANY.search(line)), None)
    if company:
        return company
    if isinstance(labelled, str) and re.match(r"[A-Za-zÄÖÜäöüß]", labelled.strip()) and 3 <= len(labelled.strip()) <= 120:
        return labelled.strip()
    return top[0] if top else None


def _first(pattern: str, text: str) -> Optional[str]:
    found = re.search(pattern, text, re.IGNORECASE)
    return found.group(1) if found else None


def guess_category(text: str) -> Optional[str]:
    lowered = text.casefold()
    for category, words in _CATEGORY_WORDS:
        if any(word in lowered for word in words):
            return category
    return None


def _amount_after(label: str, text: str) -> Optional[str]:
    raw = _first(label + r"[^\d\n-]{0,40}" + _AMOUNT, text)
    if raw is None:
        return None
    number = german_number(raw) if "," in raw else plain_number(raw)
    return str(number) if number is not None else None


def local_values(surface: Surface, text: str, *, filename: str = "", known: Optional[dict] = None) -> dict:
    """What the rules find in a text layer, in the shape of the AI answer (confidence 'low' or 'medium')."""
    from .ocr_service import _extract_invoice_fields
    known = known or {}
    raw: dict[str, Any] = {}
    fields = _extract_invoice_fields(text) if text.strip() else {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if surface.id == "document":
        from .ai.document_ai import analyze_document
        analysis = analyze_document(text, use_ai=False)
        if analysis.document_type in DOCUMENT_TYPES:
            raw["document_type"] = {"value": analysis.document_type, "confidence": "medium"}
        stem = re.sub(r"\.[^.]+$", "", filename).replace("_", " ").strip()
        title = next((line for line in lines[:8] if 6 <= len(line) <= 120), None) or stem
        if title:
            raw["title"] = {"value": title, "confidence": "low"}
        day = _first(r"(?:Datum|vom|den)\s*:?\s*" + _DATE, text) or _first(_DATE, text)
        if day:
            raw["document_date"] = {"value": day, "confidence": "low"}
        until = _first(r"gültig\s+bis\s*:?\s*" + _DATE, text)
        if until:
            raw["valid_until"] = {"value": until, "evidence": "gültig bis " + until, "confidence": "medium"}
        sender = _sender(lines, analysis.supplier)
        if sender:
            raw["sender"] = {"value": sender, "confidence": "low"}
        for kind, rows in (("unit", known.get("units") or []), ("tenant", known.get("tenants") or [])):
            hits = [row for row in rows if len(row["label"]) >= 3 and row["label"].casefold() in text.casefold()]
            if len(hits) == 1:
                raw[kind] = {"value": hits[0]["label"], "evidence": hits[0]["label"], "confidence": "medium"}
    elif surface.id in ("invoice", "cost_item"):
        supplier = _sender(lines, fields.get("supplier"))
        if supplier:
            raw["supplier"] = {"value": supplier, "confidence": "low"}
        if fields.get("invoice_number"):
            raw["invoice_number"] = {"value": fields["invoice_number"], "confidence": "medium"}
        gross = _amount_after(r"(?:Gesamtbetrag|Rechnungsbetrag|Bruttobetrag|Brutto|zu zahlen|Endbetrag)", text)
        if gross is None and fields.get("total_amount") is not None:
            gross = str(fields["total_amount"])
        category = guess_category(text)
        start = _first(r"(?:Leistungszeitraum|Abrechnungszeitraum|Zeitraum)\s*:?\s*(?:vom\s*)?" + _DATE, text)
        end = _first(r"(?:Leistungszeitraum|Abrechnungszeitraum|Zeitraum)\s*:?\s*(?:vom\s*)?\d{1,2}\.\d{1,2}\.\d{2,4}\s*(?:-|–|bis)\s*" + _DATE, text)
        if surface.id == "invoice":
            if fields.get("invoice_date"):
                raw["invoice_date"] = {"value": fields["invoice_date"], "confidence": "medium"}
            due = _first(r"(?:zahlbar\s+bis|fällig\s+am|fällig\s+bis|Fälligkeit)\s*:?\s*" + _DATE, text)
            if due:
                raw["due_date"] = {"value": due, "confidence": "medium"}
            net = _amount_after(r"(?:Netto(?:betrag)?|Summe netto|Zwischensumme)", text)
            vat = _amount_after(r"(?:MwSt|USt|Umsatzsteuer|Mehrwertsteuer)\.?\s*(?:\d{1,2}(?:,\d)?\s*%)?", text)
            rate = _first(r"(?:MwSt|USt|Umsatzsteuer|Mehrwertsteuer)\.?\s*(\d{1,2}(?:,\d)?)\s*%", text)
            for name, value in (("gross_amount", gross), ("net_amount", net), ("vat_amount", vat)):
                if value is not None:
                    raw[name] = {"value": value, "confidence": "low"}
            if rate:
                raw["vat_rate"] = {"value": rate.replace(",", "."), "confidence": "medium"}
            iban = _first(r"\b([A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?)\b", text)
            if iban:
                raw["iban"] = {"value": iban, "evidence": iban, "confidence": "medium"}
            skonto = re.search(r"(\d{1,2}(?:,\d+)?)\s*%\s*Skonto[^\n]{0,40}?(\d{1,3})\s*Tage", text, re.IGNORECASE)
            if skonto:
                raw["skonto_percent"] = {"value": skonto.group(1).replace(",", "."), "confidence": "medium"}
                raw["skonto_days"] = {"value": skonto.group(2), "confidence": "medium"}
            payable = _first(r"(?:innerhalb|binnen)\s+(\d{1,3})\s+Tagen", text)
            if payable:
                raw["payment_days"] = {"value": payable, "confidence": "low"}
            if category:
                raw["cost_category"] = {"value": category, "confidence": "low"}
            raw["document_kind"] = {"value": "credit_note" if re.search(r"\bgutschrift\b", text, re.IGNORECASE) else "invoice",
                                    "confidence": "low"}
        else:
            if gross is not None:
                raw["amount"] = {"value": gross, "confidence": "low"}
            if category:
                raw["cost_category"] = {"value": category, "confidence": "low"}
            label = COST_CATEGORY_LABELS.get(category or "", "")
            description = " ".join(part for part in (label, supplier) if part) or (lines[0][:120] if lines else None)
            if description:
                raw["description"] = {"value": description, "confidence": "low"}
            raw["recoverable"] = {"value": "false" if category in ("maintenance", "administration") else "true",
                                  "confidence": "low"}
        if start:
            raw["performance_start" if surface.id == "invoice" else "period_start"] = {"value": start, "confidence": "low"}
        if end:
            raw["performance_end" if surface.id == "invoice" else "period_end"] = {"value": end, "confidence": "low"}
    return raw


# ─── Records that may already exist for this document ───────────────────────

def _document_title(store: Any, document_id: str) -> Optional[Any]:
    from ..storage import NotFoundError
    try:
        return store.get_document(document_id)
    except NotFoundError:
        return None


def _same_stored_files(store: Any, sha256: str, size: Optional[int], ids: dict[str, str]) -> None:
    """Documents whose file in the local upload folder has the same bytes (a document filed from an upload has no
    archived original yet). Only files of the same size are hashed."""
    from urllib.parse import unquote

    from .file_storage import LocalStorage, get_file_storage
    storage = get_file_storage()
    if not size or not isinstance(storage, LocalStorage):
        return
    for document in store.list_documents():
        url = getattr(document, "file_url", None) or ""
        if ids.get(document.id) == "same_file" or not url.startswith("/uploads/"):
            continue
        try:
            path = storage._path(unquote(url.removeprefix("/uploads/").split("?", 1)[0]))
            if path.stat().st_size != size:
                continue
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
        except (OSError, ValueError):
            continue
        if digest.hexdigest() == sha256:
            ids[document.id] = "same_file"


def same_file_documents(store: Any, sha256: str, text: str, *, exclude: Optional[str] = None,
                        size: Optional[int] = None) -> list[tuple[Any, str]]:
    """Visible documents with the same file (archived original, analysed upload or stored file) or, failing that,
    the same read text (at least 200 characters, from the full-text index)."""
    ids: dict[str, str] = {}
    if hasattr(store, "db"):
        from sqlalchemy import select

        from ..db.business_qol_models import DocumentIntakeORM
        from ..db.document_version_models import DocumentVersionORM
        from ..db.orm_models import DocumentTextORM
        for document_id in store.db.scalars(select(DocumentVersionORM.document_id).where(DocumentVersionORM.sha256 == sha256)):
            ids.setdefault(document_id, "same_file")
        for document_id in store.db.scalars(select(DocumentIntakeORM.document_id).where(DocumentIntakeORM.sha256 == sha256)):
            ids.setdefault(document_id, "same_file")
        if len(text) >= 200:
            for row in store.db.execute(select(DocumentTextORM.document_id, DocumentTextORM.text)
                                        .where(DocumentTextORM.characters == len(text))):
                if row.text == text:
                    ids.setdefault(row.document_id, "same_text")
    else:
        from . import document_text
        from .document_versions import memory_archive
        for version in memory_archive(store).versions.values():
            if version.sha256 == sha256:
                ids.setdefault(version.document_id, "same_file")
        for intake in store.business_document_intake.values():
            if intake.sha256 == sha256:
                ids.setdefault(intake.document_id, "same_file")
        if len(text) >= 200:
            for row in document_text.memory_rows(store).values():
                if row.characters == len(text) and row.text == text:
                    ids.setdefault(row.document_id, "same_text")
    _same_stored_files(store, sha256, size, ids)
    ids.pop(exclude or "", None)
    found = []
    for document_id, reason in ids.items():
        document = _document_title(store, document_id)
        if document is not None:
            found.append((document, reason))
    return sorted(found, key=lambda item: item[0].created_at, reverse=True)[:10]


def _money_text(value: Any) -> str:
    amount = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    return f"{amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".") + " €"


def _day_text(value: Any) -> str:
    return value.strftime("%d.%m.%Y") if hasattr(value, "strftime") else str(value or "")


REASONS = {"same_file": "dieselbe Datei", "same_text": "derselbe Inhalt", "same_title_date": "gleicher Titel und gleiches Datum",
           "same_number": "gleiche Rechnungsnummer des Lieferanten", "same_amount_near_date": "gleicher Betrag des Lieferanten in Datumsnähe",
           "same_source": "aus diesem Dokument übernommen", "same_cost": "gleiche Bezeichnung und gleicher Betrag in diesem Zeitraum",
           "same_day": "Stand für diesen Zähler am selben Tag"}


def duplicates(store: Any, surface: Surface, params: dict, values: dict, *, sha256: str, text: str,
               document_id: Optional[str], size: Optional[int] = None) -> list[dict]:
    """Existing records that probably stem from the same document, with what can be done about each."""
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, record_id: str, title: str, href: str, reason: str, details: str = "", *, can_update: bool = False):
        if (kind, record_id) in seen:
            return
        seen.add((kind, record_id))
        found.append({"kind": kind, "id": record_id, "title": title, "href": href, "reason": reason,
                      "reason_label": REASONS.get(reason, reason), "details": details, "can_update": can_update})

    same = same_file_documents(store, sha256, text, exclude=document_id, size=size)
    source_ids = {document.id for document, _ in same} | ({document_id} if document_id else set())
    for document, reason in same:
        add("document", document.id, document.title or "Dokument", f"/documents/{document.id}", reason,
            " · ".join(part for part in (DOCUMENT_TYPE_LABELS.get(document.document_type or "", document.document_type),
                                         _day_text(document.document_date)) if part),
            can_update=surface.id == "document")
    value = {name: item["value"] for name, item in values.items()}
    if surface.id == "document" and value.get("title") and value.get("document_date"):
        title = _key(value["title"])
        for document in store.list_documents():
            if document.id != document_id and _key(document.title) == title and document.document_date \
                    and document.document_date.isoformat() == value["document_date"] \
                    and (not params.get("property_id") or document.property_id == params["property_id"]):
                add("document", document.id, document.title, f"/documents/{document.id}", "same_title_date",
                    _day_text(document.document_date), can_update=True)
    if surface.id in ("invoice", "cost_item"):
        for invoice in store.list_invoices():
            if invoice.source_document_id and invoice.source_document_id in source_ids:
                add("invoice", invoice.id, f"{invoice.supplier} vom {_day_text(invoice.invoice_date)}", f"/invoices?focus_id={invoice.id}",
                    "same_source", _money_text(invoice.gross_amount))
    if surface.id == "invoice" and value.get("supplier") and value.get("gross_amount") and value.get("invoice_date"):
        from .invoice_review import duplicate_check
        check = duplicate_check(store, supplier=value["supplier"], invoice_number=value.get("invoice_number"),
                                gross_amount=float(value["gross_amount"]), invoice_date=date.fromisoformat(value["invoice_date"]))
        for item in check["duplicates"]:
            add("invoice", item["invoice_id"], f"{value['supplier']} vom {_day_text(date.fromisoformat(item['invoice_date']))}",
                f"/invoice-review/{item['invoice_id']}", item["reason"],
                " · ".join(part for part in (item.get("invoice_number") and "Nr. " + str(item["invoice_number"]),
                                            _money_text(item["gross_amount"])) if part))
    if surface.id in ("cost_item", "meter_document"):
        period_id = params.get("billing_period_id")
        for item in store.list_cost_items():
            if period_id and item.billing_period_id != period_id:
                continue
            if item.source_document_id and item.source_document_id in source_ids:
                add("cost_item", item.id, item.description, f"/statements?period_id={item.billing_period_id}", "same_source",
                    _money_text(item.amount), can_update=surface.id == "cost_item")
            elif surface.id == "cost_item" and period_id and value.get("description") and value.get("amount") \
                    and _key(item.description) == _key(value["description"]) and _money(item.amount) == _money(value["amount"]):
                add("cost_item", item.id, item.description, f"/statements?period_id={item.billing_period_id}", "same_cost",
                    _money_text(item.amount), can_update=True)
    if surface.id == "meter_photo" and value.get("serial") and value.get("reading_date"):
        meter = match_meter(store, params, value["serial"])
        if meter is not None:
            for reading in store.list_standalone_meter_readings():
                if reading.meter_id == meter.id and reading.reading_date.isoformat() == value["reading_date"]:
                    add("meter_reading", reading.id, f"Zähler {meter.serial_number} am {_day_text(reading.reading_date)}",
                        f"/meters?focus_id={meter.id}", "same_day", f"gespeichert {reading.value:g}", can_update=True)
    return found


def match_meter(store: Any, params: dict, serial: str) -> Optional[Any]:
    """The meter of the property (or unit) with this device number, matched like the metering documents."""
    wanted = serial_keys(serial)
    if not wanted:
        return None
    property_id = params.get("property_id")
    units = {unit.id for unit in store.list_units() if not property_id or unit.property_id == property_id}
    hits = [meter for meter in store.list_meters() if meter.unit_id in units
            and (not params.get("unit_id") or meter.unit_id == params["unit_id"])
            and serial_keys(meter.serial_number) & wanted]
    return hits[0] if len(hits) == 1 else None
