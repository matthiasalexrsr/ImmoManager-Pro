"""Letter templates: kinds with their inputs and checks, placeholders, built-in and own templates.

A template has a kind, a name, a subject, a salutation, a text, a closing and an
optional appendix (e.g. a declaration of consent to sign). The kind decides which
inputs a letter asks for and which checks the server calculates; the text uses
placeholders such as `{{mieter.name}}`. Built-in templates are fixed in code
(`builtin:<kind>`); own templates are installation-wide setting rules
(`letter_template:<id>` in daily_setting_rules) changed only against their
revision. Everything here is pure except the storage functions at the end.

`compose()` fills a template for a frozen source (contract, tenant, unit, property,
rent history, last issued statement, letterhead) and returns the text, the tables
and the checks. Preview and publication call `evaluate()` again on the same frozen
source, so tables and checks never come from the browser.
"""
from __future__ import annotations

import calendar
import re
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from ..db.daily_models import SettingRuleORM
from ..domain.calendar_days import national_holidays
from . import daily_state as state
from . import document_versions as archive
from . import price_index
from .ownership import owners_on
from .settings_catalogue import record_audit, rule

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+(?:\.[a-z_]+)*)\s*\}\}")
BLOCK_LINE = re.compile(r"^\s*\{\{\s*tabelle\.([a-z_]+)\s*\}\}\s*$")
MISSING = "[bitte ergänzen: {}]"
MISSING_MARK = "[bitte ergänzen:"
TEMPLATE_PREFIX = "letter_template:"
BUILTIN_PREFIX = "builtin:"
BUILTIN_REVISION = 1
WRITE_AREA = "/letter-templates"
ISSUED_STATUSES = ("finalized", "delivered", "disputed")
CENT = Decimal("0.01")

# ─── Placeholders ────────────────────────────────────────────────────────────

GENERAL = {
    "datum": "Briefdatum",
    "vermieter.name": "Vermieter / Absender",
    "vermieter.anschrift": "Anschrift des Absenders (eine Zeile)",
    "vermieter.bankverbindung": "Bankverbindung (eine Zeile)",
    "mieter.name": "Name des Mieters",
    "mieter.anschrift": "Anschrift des Mieters (eine Zeile)",
    "eigentuemer.namen": "Eigentümer der Einheit zum Briefdatum",
    "objekt.name": "Name des Objekts",
    "objekt.anschrift": "Anschrift des Objekts (eine Zeile)",
    "einheit.bezeichnung": "Bezeichnung der Einheit",
    "einheit.wohnflaeche": "Wohnfläche",
    "einheit.zimmer": "Zimmer",
    "vertrag.nummer": "Vertragsnummer",
    "vertrag.beginn": "Vertragsbeginn",
    "vertrag.ende": "Vertragsende",
    "vertrag.personen": "Personen im Haushalt",
    "miete.kalt": "Nettokaltmiete zum Briefdatum",
    "miete.betriebskosten": "Betriebskostenvorauszahlung zum Briefdatum",
    "miete.heizkosten": "Heizkostenvorauszahlung zum Briefdatum",
    "miete.gesamt": "Gesamtmiete zum Briefdatum",
    "kaution.betrag": "Vereinbarte Kaution",
}
BLOCKS = {"miete": "Tabelle: Miete zum Briefdatum (bzw. Stichtag)",
          "mieterhoehung": "Tabelle: Miete bisher und neu",
          "indexmiete": "Tabelle: Verbraucherpreisindex und Miete bisher und neu",
          "vorauszahlung": "Tabelle: Vorauszahlungen bisher und neu"}

JUSTIFICATIONS = [("mietspiegel", "Mietspiegel"), ("comparables", "Vergleichswohnungen"),
                  ("expert", "Sachverständigengutachten"), ("database", "Mietdatenbank")]
APPOINTMENTS = [("craftsman", "Handwerkertermin"), ("meter_reading", "Zählerablesung"),
                ("smoke_detector", "Rauchmelderwartung"), ("viewing", "Wohnungsbesichtigung"),
                ("other", "Termin in der Wohnung")]


def _input(key: str, label: str, kind: str, *, required: bool = True, hint: str = "", choices=None,
           multiline: bool = False) -> dict:
    field: dict[str, Any] = {"key": key, "label": label, "type": kind, "required": required, "hint": hint}
    if choices is not None:
        field["choices"] = [{"value": value, "label": text} for value, text in choices]
    if multiline:
        field["multiline"] = True
    return field


KINDS: dict[str, dict[str, Any]] = {
    "rent_increase": {
        "label": "Mieterhöhung (§ 558 BGB)",
        "description": "Zustimmung zur Erhöhung auf die ortsübliche Vergleichsmiete; prüft Sperrfrist, Wartefrist "
                       "und Kappungsgrenze und rechnet Wirksamkeit und Zustimmungsfrist.",
        "inputs": [
            _input("receipt_date", "Voraussichtlicher Zugang beim Mieter", "date",
                   hint="Davon hängen Zustimmungsfrist und Wirksamkeit ab (§ 558b BGB)."),
            _input("new_cold_rent", "Neue Nettokaltmiete (€ monatlich)", "amount"),
            _input("justification", "Begründung mit", "choice", choices=JUSTIFICATIONS),
            _input("justification_text", "Begründung im Einzelnen", "text", multiline=True,
                   hint="z. B. Mietspiegel der Stadt …, Feld …, Spanne … bis … €/m²"),
            _input("cap_percent", "Kappungsgrenze", "choice",
                   choices=[("20", "20 % in drei Jahren"), ("15", "15 % (Gebiet mit angespanntem Wohnungsmarkt)")]),
        ],
        "placeholders": {
            "erhoehung.zugang": "Voraussichtlicher Zugang", "erhoehung.neue_kaltmiete": "Neue Nettokaltmiete",
            "erhoehung.betrag": "Erhöhung in Euro", "erhoehung.prozent": "Erhöhung in Prozent",
            "erhoehung.wirksam_ab": "Wirksam ab", "erhoehung.zustimmung_bis": "Zustimmung bis",
            "erhoehung.begruendung": "Begründung", "erhoehung.kappungsgrenze": "Kappungsgrenze in Prozent",
            "erhoehung.neue_gesamtmiete": "Neue Gesamtmiete", "erhoehung.qm_bisher": "Bisher je m²",
            "erhoehung.qm_neu": "Neu je m²",
        },
        "blocks": ["mieterhoehung", "miete"],
    },
    "index_rent": {
        "label": "Mietanpassung bei Indexmiete (§ 557b BGB)",
        "description": "Neue Nettokaltmiete nach dem Verbraucherpreisindex; prüft die Indexvereinbarung und die "
                       "Jahresfrist und rechnet Miete und Wirksamkeit (übernächster Monat nach Zugang).",
        "inputs": [
            _input("receipt_date", "Voraussichtlicher Zugang beim Mieter", "date",
                   hint="Die neue Miete gilt ab dem übernächsten Monat nach Zugang (§ 557b Abs. 3 BGB)."),
            _input("base_month", "Ausgangsmonat des Index", "month",
                   hint="Monat, dessen Index der bisherigen Miete zugrunde liegt: bei der ersten Anpassung der in "
                        "der Indexklausel genannte Monat (meist Vertragsbeginn), sonst der Monat aus dem letzten "
                        "Anpassungsschreiben."),
            _input("base_index", "Index im Ausgangsmonat", "index"),
            _input("new_month", "Aktueller Indexmonat", "month",
                   hint="Der zuletzt veröffentlichte Monat (Statistisches Bundesamt, Tabelle 61111-0002)."),
            _input("new_index", "Aktueller Index", "index"),
        ],
        "placeholders": {
            "index.zugang": "Voraussichtlicher Zugang", "index.wirksam_ab": "Wirksam ab",
            "index.basismonat": "Ausgangsmonat", "index.basiswert": "Index im Ausgangsmonat",
            "index.neumonat": "Aktueller Indexmonat", "index.neuwert": "Aktueller Index",
            "index.basisjahr": "Basisjahr des Index", "index.veraenderung": "Veränderung des Index in Prozent",
            "index.bisherige_kaltmiete": "Bisherige Nettokaltmiete", "index.neue_kaltmiete": "Neue Nettokaltmiete",
            "index.erhoehung": "Erhöhung in Euro", "index.neue_gesamtmiete": "Neue Gesamtmiete",
        },
        "blocks": ["indexmiete", "miete"],
    },
    "advance_adjustment": {
        "label": "Anpassung der Vorauszahlungen (§ 560 Abs. 4 BGB)",
        "description": "Neue Betriebs- und Heizkostenvorauszahlung nach einer Abrechnung; schlägt den Betrag aus der "
                       "letzten ausgestellten Abrechnung vor.",
        "inputs": [
            _input("new_service_charge_advance", "Neue Betriebskostenvorauszahlung (€ monatlich)", "amount"),
            _input("new_heating_advance", "Neue Heizkostenvorauszahlung (€ monatlich)", "amount"),
            _input("effective_date", "Wirksam ab", "date", hint="In der Regel der Monatserste nach Zugang."),
            _input("statement_reference", "Bezug auf die Abrechnung", "text",
                   hint="z. B. „Betriebskostenabrechnung 2025 vom 15.06.2026“"),
        ],
        "placeholders": {
            "vorauszahlung.betriebskosten_neu": "Neue Betriebskostenvorauszahlung",
            "vorauszahlung.heizkosten_neu": "Neue Heizkostenvorauszahlung",
            "vorauszahlung.wirksam_ab": "Wirksam ab", "vorauszahlung.abrechnung": "Bezug auf die Abrechnung",
            "vorauszahlung.neue_gesamtmiete": "Neue Gesamtmiete", "vorauszahlung.differenz": "Änderung je Monat",
        },
        "blocks": ["vorauszahlung", "miete"],
    },
    "termination_confirmation": {
        "label": "Bestätigung der Kündigung",
        "description": "Eingang der Kündigung und Mietende bestätigen, Übergabetermin vorschlagen; prüft die "
                       "gesetzliche Kündigungsfrist des Mieters (§ 573c BGB).",
        "inputs": [
            _input("notice_received", "Kündigung eingegangen am", "date"),
            _input("tenancy_end", "Mietende", "date"),
            _input("handover", "Übergabetermin", "text", required=False,
                   hint="z. B. „am 31.01.2027 um 10:00 Uhr“; leer: nach Absprache"),
        ],
        "placeholders": {"kuendigung.eingang": "Eingang der Kündigung", "kuendigung.mietende": "Mietende",
                         "kuendigung.uebergabe": "Übergabetermin"},
        "blocks": ["miete"],
    },
    "rent_certificate": {
        "label": "Mietbescheinigung",
        "description": "Bescheinigt Mietverhältnis, Wohnung und Miete zum Stichtag, z. B. für Behörden.",
        "inputs": [
            _input("reference_date", "Stichtag", "date"),
            _input("purpose", "Zur Vorlage bei", "text", hint="z. B. „dem Jobcenter Leipzig“"),
            _input("no_arrears", "Es bestehen keine Mietrückstände (bitte vorher im Mieterkonto prüfen)", "bool",
                   required=False),
        ],
        "placeholders": {"bescheinigung.stichtag": "Stichtag", "bescheinigung.zweck": "Zur Vorlage bei",
                         "bescheinigung.rueckstaende": "Satz zu Mietrückständen (nur wenn bestätigt)"},
        "blocks": ["miete"],
    },
    "appointment_notice": {
        "label": "Ankündigung eines Termins",
        "description": "Handwerkertermin, Zählerablesung, Rauchmelderwartung oder Besichtigung in der Wohnung "
                       "ankündigen.",
        "inputs": [
            _input("appointment_type", "Art des Termins", "choice", choices=APPOINTMENTS),
            _input("appointment_date", "Datum", "date"),
            _input("time_from", "Uhrzeit von", "time", required=False),
            _input("time_to", "Uhrzeit bis", "time", required=False),
            _input("company", "Ausführende Firma oder Person", "text"),
            _input("reason", "Anlass", "text", multiline=True),
            _input("reply_by", "Rückmeldung bei Verhinderung bis", "date", required=False,
                   hint="leer: drei Tage vor dem Termin"),
        ],
        "placeholders": {"termin.art": "Art des Termins", "termin.datum": "Datum", "termin.zeit": "Uhrzeit",
                         "termin.firma": "Ausführende Firma", "termin.anlass": "Anlass",
                         "termin.rueckmeldung_bis": "Rückmeldung bis"},
        "blocks": ["miete"],
    },
    "free": {
        "label": "Freies Schreiben",
        "description": "Eigener Text mit den allgemeinen Platzhaltern.",
        "inputs": [],
        "placeholders": {},
        "blocks": ["miete"],
    },
}

BUILTIN: dict[str, dict[str, str]] = {
    "rent_increase": {
        "name": "Mieterhöhung auf die ortsübliche Vergleichsmiete (§ 558 BGB)",
        "subject": "Mieterhöhungsverlangen nach § 558 BGB – {{einheit.bezeichnung}}, {{objekt.anschrift}}",
        "salutation": "Guten Tag {{mieter.name}},",
        "body": (
            "die Nettokaltmiete für die von Ihnen gemietete Wohnung {{einheit.bezeichnung}} im Objekt "
            "{{objekt.anschrift}} (Mietvertrag {{vertrag.nummer}}) beträgt derzeit {{miete.kalt}} monatlich. Nach "
            "§ 558 BGB kann der Vermieter die Zustimmung zu einer Erhöhung der Miete bis zur ortsüblichen "
            "Vergleichsmiete verlangen.\n\n"
            "Ich bitte Sie daher, einer Erhöhung der Nettokaltmiete um {{erhoehung.betrag}} auf "
            "**{{erhoehung.neue_kaltmiete}}** monatlich mit Wirkung ab dem **{{erhoehung.wirksam_ab}}** zuzustimmen. "
            "Die Vorauszahlungen für Betriebs- und Heizkosten bleiben unverändert.\n\n"
            "{{tabelle.mieterhoehung}}\n\n"
            "Begründung: {{erhoehung.begruendung}}\n\n"
            "Die Miete ist seit mindestens 15 Monaten unverändert. Die Erhöhung hält die Kappungsgrenze von "
            "{{erhoehung.kappungsgrenze}} in drei Jahren ein (§ 558 Abs. 3 BGB).\n\n"
            "Bitte erklären Sie Ihre Zustimmung bis zum **{{erhoehung.zustimmung_bis}}**, zum Beispiel mit der "
            "unten stehenden Erklärung. Stimmen Sie nicht zu, kann die Zustimmung gerichtlich geltend gemacht "
            "werden (§ 558b Abs. 2 BGB).\n\n"
            "Sie haben nach § 561 BGB das Recht, das Mietverhältnis bis zum Ablauf des zweiten Monats nach dem "
            "Zugang dieses Schreibens außerordentlich zum Ablauf des übernächsten Monats zu kündigen."),
        "closing": "Mit freundlichen Grüßen",
        "appendix": (
            "**Zustimmungserklärung**\n\n"
            "Ich/Wir stimme(n) der Erhöhung der Nettokaltmiete für die Wohnung {{einheit.bezeichnung}} "
            "(Mietvertrag {{vertrag.nummer}}) auf {{erhoehung.neue_kaltmiete}} monatlich ab dem "
            "{{erhoehung.wirksam_ab}} zu.\n\n\n"
            "______________________________________\n"
            "Ort, Datum, Unterschrift {{mieter.name}}"),
    },
    "index_rent": {
        "name": "Mietanpassung bei Indexmiete (§ 557b BGB)",
        "subject": "Anpassung der Miete nach der Indexvereinbarung – {{einheit.bezeichnung}}, {{objekt.anschrift}}",
        "salutation": "Guten Tag {{mieter.name}},",
        "body": (
            "für die von Ihnen gemietete Wohnung {{einheit.bezeichnung}} im Objekt {{objekt.anschrift}} "
            "(Mietvertrag {{vertrag.nummer}}) ist eine Indexmiete vereinbart: Die Nettokaltmiete folgt dem vom "
            "Statistischen Bundesamt ermittelten Verbraucherpreisindex für Deutschland (§ 557b BGB).\n\n"
            "Der Index ist von {{index.basiswert}} Punkten im {{index.basismonat}} auf {{index.neuwert}} Punkte im "
            "{{index.neumonat}} gestiegen ({{index.basisjahr}} = 100). Das ist eine Veränderung um "
            "{{index.veraenderung}}.\n\n"
            "Die Nettokaltmiete ändert sich im gleichen Verhältnis von {{index.bisherige_kaltmiete}} um "
            "{{index.erhoehung}} auf **{{index.neue_kaltmiete}}** monatlich. Die neue Miete ist ab dem "
            "**{{index.wirksam_ab}}** zu zahlen (§ 557b Abs. 3 BGB). Die Vorauszahlungen für Betriebs- und "
            "Heizkosten bleiben unverändert.\n\n"
            "{{tabelle.indexmiete}}\n\n"
            "Bitte zahlen Sie ab diesem Zeitpunkt monatlich insgesamt **{{index.neue_gesamtmiete}}**. Haben Sie "
            "einen Dauerauftrag eingerichtet, passen Sie ihn bitte entsprechend an."),
        "closing": "Mit freundlichen Grüßen",
        "appendix": "",
    },
    "advance_adjustment": {
        "name": "Anpassung der Vorauszahlungen nach einer Abrechnung (§ 560 Abs. 4 BGB)",
        "subject": "Anpassung der Vorauszahlungen – {{einheit.bezeichnung}}, {{objekt.anschrift}}",
        "salutation": "Guten Tag {{mieter.name}},",
        "body": (
            "auf Grundlage der {{vorauszahlung.abrechnung}} passen wir die monatlichen Vorauszahlungen für die "
            "Wohnung {{einheit.bezeichnung}} im Objekt {{objekt.anschrift}} (Mietvertrag {{vertrag.nummer}}) nach "
            "§ 560 Abs. 4 BGB auf eine angemessene Höhe an.\n\n"
            "Ab dem **{{vorauszahlung.wirksam_ab}}** gelten folgende Beträge:\n\n"
            "{{tabelle.vorauszahlung}}\n\n"
            "Bitte zahlen Sie ab diesem Zeitpunkt monatlich insgesamt **{{vorauszahlung.neue_gesamtmiete}}**. "
            "Haben Sie einen Dauerauftrag eingerichtet, passen Sie ihn bitte entsprechend an."),
        "closing": "Mit freundlichen Grüßen",
        "appendix": "",
    },
    "termination_confirmation": {
        "name": "Bestätigung der Kündigung durch den Mieter",
        "subject": "Bestätigung Ihrer Kündigung – Mietvertrag {{vertrag.nummer}}",
        "salutation": "Guten Tag {{mieter.name}},",
        "body": (
            "Ihre Kündigung des Mietverhältnisses über die Wohnung {{einheit.bezeichnung}} im Objekt "
            "{{objekt.anschrift}} ist am {{kuendigung.eingang}} bei uns eingegangen. Wir bestätigen die Beendigung "
            "des Mietverhältnisses zum **{{kuendigung.mietende}}**.\n\n"
            "Für die Rückgabe der Wohnung schlagen wir folgenden Termin vor: {{kuendigung.uebergabe}}. Bitte "
            "geben Sie bei der Übergabe alle Schlüssel zurück. Die Zählerstände halten wir gemeinsam im "
            "Übergabeprotokoll fest.\n\n"
            "Bitte teilen Sie uns Ihre neue Anschrift mit, damit wir Ihnen die Abrechnungen der Betriebskosten "
            "und der Kaution zusenden können."),
        "closing": "Mit freundlichen Grüßen",
        "appendix": "",
    },
    "rent_certificate": {
        "name": "Mietbescheinigung",
        "subject": "Mietbescheinigung – {{mieter.name}}",
        "salutation": "",
        "body": (
            "Hiermit bescheinigen wir, dass {{mieter.name}} die Wohnung {{einheit.bezeichnung}} im Objekt "
            "{{objekt.anschrift}} seit dem {{vertrag.beginn}} gemietet hat (Mietvertrag {{vertrag.nummer}}).\n\n"
            "Wohnfläche: {{einheit.wohnflaeche}}\n"
            "Zimmer: {{einheit.zimmer}}\n"
            "Personen im Haushalt: {{vertrag.personen}}\n\n"
            "Die monatliche Miete beträgt zum {{bescheinigung.stichtag}}:\n\n"
            "{{tabelle.miete}}\n\n"
            "{{bescheinigung.rueckstaende}}\n\n"
            "Diese Bescheinigung wird auf Wunsch des Mieters zur Vorlage bei {{bescheinigung.zweck}} ausgestellt."),
        "closing": "Mit freundlichen Grüßen",
        "appendix": "",
    },
    "appointment_notice": {
        "name": "Ankündigung eines Termins in der Wohnung",
        "subject": "Ankündigung: {{termin.art}} am {{termin.datum}} – {{einheit.bezeichnung}}",
        "salutation": "Guten Tag {{mieter.name}},",
        "body": (
            "für die Wohnung {{einheit.bezeichnung}} im Objekt {{objekt.anschrift}} kündigen wir folgenden Termin "
            "an:\n\n"
            "- **{{termin.art}}** am **{{termin.datum}}**, {{termin.zeit}}\n"
            "- Ausführung: {{termin.firma}}\n"
            "- Anlass: {{termin.anlass}}\n\n"
            "Bitte ermöglichen Sie an diesem Tag den Zugang zur Wohnung oder beauftragen Sie eine Person Ihres "
            "Vertrauens. Passt Ihnen der Termin nicht, melden Sie sich bitte bis zum {{termin.rueckmeldung_bis}}, "
            "damit wir einen anderen Termin vereinbaren können.\n\n"
            "Vielen Dank für Ihre Unterstützung."),
        "closing": "Mit freundlichen Grüßen",
        "appendix": "",
    },
    "free": {
        "name": "Freies Schreiben",
        "subject": "Ihr Mietverhältnis {{vertrag.nummer}} – {{einheit.bezeichnung}}",
        "salutation": "Guten Tag {{mieter.name}},",
        "body": "",
        "closing": "Mit freundlichen Grüßen",
        "appendix": "",
    },
}
TEXT_LIMITS = {"name": 120, "subject": 300, "salutation": 300, "body": 20000, "closing": 500, "appendix": 6000}

# ─── Formatting and dates ────────────────────────────────────────────────────


def eur(value: Any) -> str:
    amount = Decimal(str(value)).quantize(CENT, ROUND_HALF_UP)
    return f"{amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".") + " €"


def number(value: Any, places: int = 2) -> str:
    amount = Decimal(str(value)).quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP)
    text = f"{amount:,.{places}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return text.rstrip("0").rstrip(",") if places and "," in text else text


def day(value: date | str | None) -> str:
    if not value:
        return ""
    return (value if isinstance(value, date) else date.fromisoformat(value)).strftime("%d.%m.%Y")


def add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year, month = value.year + month // 12, month % 12 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def month_end(value: date) -> date:
    return date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])


def working_day(value: date) -> bool:
    """A working day for notice periods: Monday to Saturday, no nationwide public holiday."""
    return value.weekday() < 6 and value not in national_holidays(value.year)


def tenant_notice_end(received: date) -> date:
    """§ 573c Abs. 1 BGB: notice by the third working day of a month ends the tenancy with the month after next."""
    count, current = 0, received.replace(day=1)
    while True:
        if working_day(current):
            count += 1
        if count == 3:
            break
        current += timedelta(days=1)
    return month_end(add_months(received.replace(day=1), 2 if received <= current else 3))


def amount(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, ROUND_HALF_UP)


def rent_on(steps: list[dict], value: date) -> dict | None:
    current = None
    for step in sorted(steps, key=lambda item: item["valid_from"]):
        if date.fromisoformat(step["valid_from"]) <= value:
            current = step
    return current


def rent_model(contract: dict) -> str | None:
    """"index", "stepped", "fixed" or None. The contract form stores these keys; imported and older data
    may hold a German text ("Indexmiete (VPI)", "Staffelmiete")."""
    value = str(contract.get("index_rent") or "").strip().lower()
    if not value:
        return None
    if value.startswith("index") or "vpi" in value:
        return "index"
    if value.startswith(("stepped", "staffel")):
        return "stepped"
    return "fixed" if value.startswith(("fixed", "fest")) else value


def residential(location: dict) -> bool | None:
    """True for a flat, False for business premises, None for other or unknown units (parking, cellar …)."""
    kind = str(location.get("unit_type") or "").strip().lower()
    if kind in ("", "wohnung", "residential", "apartment", "flat"):
        return True
    if kind in ("gewerbe", "commercial", "office", "büro", "laden", "retail"):
        return False
    return None


# § 558 Abs. 1 Satz 3, Abs. 3 Satz 1 BGB: increases after modernization (§ 559) and changes of the
# operating costs (§ 560) count neither for the waiting periods nor for the cap (R12-16)
NOT_COMPARATIVE = frozenset({"559", "560"})


def last_cold_rent_change(steps: list[dict]) -> date | None:
    """The day the cold rent last changed after the start of the contract (None: unchanged since then)."""
    ordered = sorted(steps, key=lambda item: item["valid_from"])
    changed = None
    for before, after in zip(ordered, ordered[1:]):
        if amount(after["cold_rent"]) != amount(before["cold_rent"]) and after.get("kind") not in NOT_COMPARATIVE:
            changed = date.fromisoformat(after["valid_from"])
    return changed


def excluded_increases(steps: list[dict], after: date, until: date) -> Decimal:
    """The cold rent raised by §§ 559, 560 after ``after`` until ``until``: left out of the cap."""
    ordered = sorted(steps, key=lambda item: item["valid_from"])
    total = Decimal("0")
    for before, step in zip(ordered, ordered[1:]):
        if step.get("kind") in NOT_COMPARATIVE and after < date.fromisoformat(step["valid_from"]) <= until:
            total += amount(step["cold_rent"]) - amount(before["cold_rent"])
    return total


# ─── Inputs ──────────────────────────────────────────────────────────────────


def parse_inputs(kind: str, raw: dict) -> dict[str, Any]:
    """Validated inputs of a kind (types, required fields, limits); unknown keys are refused."""
    if not isinstance(raw, dict):
        raise HTTPException(422, "Ungültige Angaben zum Brief.")
    fields = {field["key"]: field for field in KINDS[kind]["inputs"]}
    if set(raw) - set(fields):
        raise HTTPException(422, "Unbekannte Angaben zum Brief: " + ", ".join(sorted(set(raw) - set(fields))))
    result: dict[str, Any] = {}
    for key, field in fields.items():
        value = raw.get(key)
        if field["type"] == "bool":
            if value not in (None, True, False):
                raise HTTPException(422, f"„{field['label']}“: Ja oder Nein angeben.")
            result[key] = bool(value)
            continue
        if value is None or (isinstance(value, str) and not value.strip()):
            if field["required"]:
                raise HTTPException(422, f"Bitte „{field['label']}“ angeben.")
            result[key] = None
            continue
        if not isinstance(value, str):
            value = str(value)
        value = value.replace("\r\n", "\n").strip()
        if field["type"] == "date":
            try:
                result[key] = date.fromisoformat(value).isoformat()
            except ValueError:
                raise HTTPException(422, f"„{field['label']}“: kein gültiges Datum.") from None
        elif field["type"] == "month":
            if not re.fullmatch(r"(?:19|20)\d\d-(?:0[1-9]|1[0-2])", value):
                raise HTTPException(422, f"„{field['label']}“: Monat im Format JJJJ-MM angeben.")
            result[key] = value
        elif field["type"] == "index":
            result[key] = str(price_index.parse_value(value, f"„{field['label']}“"))
        elif field["type"] == "time":
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                raise HTTPException(422, f"„{field['label']}“: Uhrzeit im Format HH:MM angeben.")
            result[key] = value
        elif field["type"] == "amount":
            try:
                number_value = Decimal(value.replace(",", "."))
            except InvalidOperation:
                raise HTTPException(422, f"„{field['label']}“: kein gültiger Betrag.") from None
            if not number_value.is_finite() or number_value < 0 or number_value > 1_000_000 \
                    or number_value != number_value.quantize(CENT):
                raise HTTPException(422, f"„{field['label']}“: Betrag zwischen 0 und 1.000.000 € mit höchstens "
                                         "zwei Nachkommastellen angeben.")
            result[key] = str(number_value.quantize(CENT))
        elif field["type"] == "choice":
            if value not in {choice["value"] for choice in field["choices"]}:
                raise HTTPException(422, f"„{field['label']}“: ungültige Auswahl.")
            result[key] = value
        else:
            limit = 2000 if field.get("multiline") else 300
            if len(value) > limit or any((ord(char) < 32 and not (field.get("multiline") and char == "\n"))
                                         or ord(char) == 127 for char in value):
                raise HTTPException(422, f"„{field['label']}“: höchstens {limit} Zeichen ohne Steuerzeichen.")
            result[key] = value
    return result


def default_inputs(kind: str, source: dict, issue: date) -> dict[str, Any]:
    """Suggestions for a new letter; nothing is decided silently, every value can be changed."""
    steps = source["rent_steps"]
    current = rent_on(steps, issue) or {}
    if kind == "rent_increase":
        return {"receipt_date": (issue + timedelta(days=3)).isoformat(), "new_cold_rent": None,
                "justification": "mietspiegel", "justification_text": None, "cap_percent": "20"}
    if kind == "index_rent":
        series = (source.get("price_index") or {}).get("values") or {}
        changed = last_cold_rent_change(steps) or date.fromisoformat(source["contract"]["start_date"])
        base_month = changed.strftime("%Y-%m")
        published = [month for month in sorted(series) if month <= issue.strftime("%Y-%m")]
        new_month = published[-1] if published else None
        return {"receipt_date": (issue + timedelta(days=3)).isoformat(), "base_month": base_month,
                "base_index": series.get(base_month), "new_month": new_month,
                "new_index": series.get(new_month) if new_month else None}
    if kind == "advance_adjustment":
        statement = source.get("statement")
        service, heating = amount(current.get("service_charge_advance")), amount(current.get("heating_advance"))
        if statement and statement.get("months"):
            monthly = (amount(statement["total_cost"]) / Decimal(str(statement["months"]))).quantize(Decimal(1), ROUND_CEILING)
            service = max(Decimal(0), monthly - heating).quantize(CENT)
        reference = (f"Betriebskostenabrechnung „{statement['label']}“ vom {day(statement['issued_on'])}"
                     if statement and statement.get("issued_on") else
                     f"Betriebskostenabrechnung „{statement['label']}“" if statement else None)
        start = add_months(issue.replace(day=1), 1 if issue.day <= 15 else 2)
        return {"new_service_charge_advance": str(service), "new_heating_advance": str(heating),
                "effective_date": start.isoformat(), "statement_reference": reference}
    if kind == "termination_confirmation":
        contract = source["contract"]
        end = contract.get("end_date") or tenant_notice_end(issue).isoformat()
        return {"notice_received": issue.isoformat(), "tenancy_end": end, "handover": None}
    if kind == "rent_certificate":
        return {"reference_date": issue.isoformat(), "purpose": None, "no_arrears": False}
    if kind == "appointment_notice":
        return {"appointment_type": "craftsman", "appointment_date": (issue + timedelta(days=14)).isoformat(),
                "time_from": None, "time_to": None, "company": None, "reason": None, "reply_by": None}
    return {}


# ─── Evaluation: values, tables and checks ───────────────────────────────────


def _one_line(*parts: Any) -> str:
    return ", ".join(str(part).strip() for part in parts if part and str(part).strip())


def _address(row: dict | None) -> str:
    if not row:
        return ""
    city = " ".join(part for part in (row.get("postal_code"), row.get("city")) if part)
    return _one_line(row.get("address_line"), city)


def _check(level: str, text: str) -> dict:
    return {"level": level, "text": text}


def _rent_table(rent: dict, title: str = "Monatliche Miete") -> dict:
    cold, service, heating = (amount(rent.get(key)) for key in ("cold_rent", "service_charge_advance", "heating_advance"))
    return {"rows": [[title, "Betrag"], ["Nettokaltmiete", eur(cold)], ["Vorauszahlung Betriebskosten", eur(service)],
                     ["Vorauszahlung Heizkosten", eur(heating)], ["Gesamtmiete", eur(cold + service + heating)]],
            "numeric": [1], "widths": [0.7, 0.3], "total": True}


def evaluate(kind: str, source: dict, inputs: dict, issue: date) -> dict[str, Any]:
    """Placeholder values, tables and checks for a frozen source and validated inputs."""
    contract, tenant, location, prop = source["contract"], source["tenant"], source["unit"], source["property"]
    head = source["letterhead"]
    steps = source["rent_steps"]
    rent = rent_on(steps, issue) or {}
    cold, service, heating = (amount(rent.get(key)) for key in ("cold_rent", "service_charge_advance", "heating_advance"))
    area = Decimal(str(location["area_sqm"])) if location.get("area_sqm") else None
    values: dict[str, str | None] = {
        "datum": day(issue), "vermieter.name": head.get("sender_name") or None,
        "vermieter.anschrift": ", ".join(line.strip() for line in (head.get("sender_address") or "").split("\n") if line.strip()) or None,
        "vermieter.bankverbindung": ", ".join(line.strip() for line in (head.get("bank") or "").split("\n") if line.strip()) or None,
        "mieter.name": tenant["full_name"], "mieter.anschrift": _address(tenant) or None,
        # the recorded owners on the letter date (services.ownership.timeline), else the portfolio's owner
        "eigentuemer.namen": ", ".join(owner["name"] for owner in owners_on(source.get("owners") or [], issue))
        or (source.get("portfolio") or {}).get("owner_name") or None,
        "objekt.name": prop["name"], "objekt.anschrift": _address(prop) or prop["name"],
        "einheit.bezeichnung": location["label"],
        "einheit.wohnflaeche": f"{number(area)} m²" if area else None,
        "einheit.zimmer": number(location["rooms"], 1) if location.get("rooms") else None,
        "vertrag.nummer": contract["contract_number"], "vertrag.beginn": day(contract["start_date"]),
        "vertrag.ende": day(contract.get("end_date")) or "unbefristet",
        "vertrag.personen": str(contract["persons"]) if contract.get("persons") else None,
        "miete.kalt": eur(cold) if rent else None, "miete.betriebskosten": eur(service) if rent else None,
        "miete.heizkosten": eur(heating) if rent else None,
        "miete.gesamt": eur(cold + service + heating) if rent else None,
        "kaution.betrag": eur(contract["deposit_amount"]) if contract.get("deposit_amount") else None,
    }
    blocks: dict[str, dict] = {"miete": _rent_table(rent, f"Monatliche Miete zum {day(issue)}")} if rent else {}
    checks: list[dict] = []
    if not tenant.get("address_line") or not (tenant.get("postal_code") or tenant.get("city")):
        checks.append(_check("warning", "Die Anschrift des Mieters ist unvollständig. Vorgeschlagen ist die Anschrift "
                                        "des Objekts; bitte die Empfängeranschrift prüfen."))
    if contract["status"] not in ("active", "terminated"):
        checks.append(_check("warning", "Der Vertrag ist nicht aktiv. Bitte prüfen, ob dieser Brief noch passt."))

    if kind == "rent_increase":
        _rent_increase(source, inputs, issue, values, blocks, checks, area)
    elif kind == "index_rent":
        _index_rent(source, inputs, issue, values, blocks, checks)
    elif kind == "advance_adjustment":
        _advance_adjustment(source, inputs, issue, values, blocks, checks, rent)
    elif kind == "termination_confirmation":
        received, end = date.fromisoformat(inputs["notice_received"]), date.fromisoformat(inputs["tenancy_end"])
        values.update({"kuendigung.eingang": day(received), "kuendigung.mietende": day(end),
                       "kuendigung.uebergabe": inputs.get("handover") or "nach Absprache mit Ihnen"})
        earliest = tenant_notice_end(received)
        if end < received:
            checks.append(_check("error", "Das Mietende liegt vor dem Eingang der Kündigung."))
        elif end < earliest:
            checks.append(_check("warning", f"Nach der gesetzlichen Kündigungsfrist des Mieters (§ 573c Abs. 1 BGB) "
                                            f"endet das Mietverhältnis frühestens am {day(earliest)}. Ein früheres Ende "
                                            "gilt nur, wenn Sie es vereinbaren (z. B. Aufhebungsvertrag)."))
        if contract.get("notice_period"):
            checks.append(_check("info", f"Im Vertrag vermerkte Kündigungsfrist: {contract['notice_period']}."))
        if contract.get("end_date") != end.isoformat():
            checks.append(_check("info", "Das Vertragsende im Programm ist "
                                         + (day(contract["end_date"]) if contract.get("end_date") else "nicht eingetragen")
                                         + ". Der Brief ändert den Vertrag nicht; bitte das Mietende im Vertrag eintragen."))
    elif kind == "rent_certificate":
        stamp = date.fromisoformat(inputs["reference_date"])
        stamp_rent = rent_on(steps, stamp)
        values.update({"bescheinigung.stichtag": day(stamp), "bescheinigung.zweck": inputs["purpose"],
                       "bescheinigung.rueckstaende": "Zum Stichtag bestehen keine Mietrückstände."
                       if inputs.get("no_arrears") else ""})
        if stamp_rent:
            blocks["miete"] = _rent_table(stamp_rent, f"Monatliche Miete zum {day(stamp)}")
        if stamp < date.fromisoformat(contract["start_date"]):
            checks.append(_check("error", "Der Stichtag liegt vor dem Vertragsbeginn."))
        elif contract.get("end_date") and stamp > date.fromisoformat(contract["end_date"]):
            checks.append(_check("warning", "Der Stichtag liegt nach dem Vertragsende."))
        if inputs.get("no_arrears"):
            checks.append(_check("info", "Die Bescheinigung bestätigt, dass keine Mietrückstände bestehen. Bitte vorher "
                                         "das Mieterkonto prüfen."))
    elif kind == "appointment_notice":
        _appointment(inputs, issue, values, checks)
    for name in ("einheit.wohnflaeche", "einheit.zimmer", "vertrag.personen"):
        if values.get(name) is None and kind == "rent_certificate":
            checks.append(_check("warning", f"{GENERAL[name]} ist nicht erfasst. Bitte im Text ergänzen oder die Zeile "
                                            "entfernen."))
    return {"values": values, "blocks": blocks, "checks": checks}


def _rent_increase(source, inputs, issue, values, blocks, checks, area) -> None:
    contract, steps = source["contract"], source["rent_steps"]
    receipt = date.fromisoformat(inputs["receipt_date"])
    effective = add_months(receipt.replace(day=1), 3)
    consent_until = month_end(add_months(receipt.replace(day=1), 2))
    new_cold = amount(inputs["new_cold_rent"])
    cap = Decimal(inputs["cap_percent"])
    current = rent_on(steps, receipt) or {}
    cold = amount(current.get("cold_rent"))
    service, heating = amount(current.get("service_charge_advance")), amount(current.get("heating_advance"))
    label = dict(JUSTIFICATIONS)[inputs["justification"]]
    values.update({
        "erhoehung.zugang": day(receipt), "erhoehung.neue_kaltmiete": eur(new_cold),
        "erhoehung.betrag": eur(new_cold - cold), "erhoehung.wirksam_ab": day(effective),
        "erhoehung.zustimmung_bis": day(consent_until), "erhoehung.kappungsgrenze": f"{cap} %",
        "erhoehung.begruendung": f"{label} – {inputs['justification_text']}",
        "erhoehung.neue_gesamtmiete": eur(new_cold + service + heating),
        "erhoehung.prozent": f"{number((new_cold / cold - 1) * 100, 1)} %" if cold else None,
        "erhoehung.qm_bisher": f"{number(cold / area)} €/m²" if area and cold else None,
        "erhoehung.qm_neu": f"{number(new_cold / area)} €/m²" if area else None,
    })
    rows = [["", "bisher", f"ab {day(effective)}"], ["Nettokaltmiete", eur(cold), eur(new_cold)]]
    if area:
        rows.append(["Nettokaltmiete je m² Wohnfläche", f"{number(cold / area)} €" if cold else "—",
                     f"{number(new_cold / area)} €"])
    rows += [["Vorauszahlung Betriebskosten", eur(service), eur(service)],
             ["Vorauszahlung Heizkosten", eur(heating), eur(heating)],
             ["Gesamtmiete", eur(cold + service + heating), eur(new_cold + service + heating)]]
    blocks["mieterhoehung"] = {"rows": rows, "numeric": [1, 2], "widths": [0.5, 0.25, 0.25], "total": True}

    living = residential(source["unit"])
    if living is False:
        checks.append(_check("error", "Die Einheit ist als Gewerbe erfasst. § 558 BGB gilt nur für Wohnraum; bei "
                                      "Gewerbe richtet sich eine Mieterhöhung nach dem Vertrag."))
    elif living is None:
        checks.append(_check("warning", "Die Einheit ist keine Wohnung. § 558 BGB gilt für Wohnraum; bitte prüfen, ob "
                                        "das Verlangen hier passt."))
    if rent_model(contract) == "index":
        checks.append(_check("error", "Bei einer Indexmiete ist eine Mieterhöhung nach § 558 BGB ausgeschlossen "
                                      "(§ 557b Abs. 2 BGB)."))
    elif rent_model(contract) == "stepped":
        checks.append(_check("error", "Bei einer Staffelmiete ist eine Mieterhöhung nach § 558 BGB ausgeschlossen "
                                      "(§ 557a Abs. 2 BGB)."))
    if receipt < issue:
        checks.append(_check("error", "Der Zugang kann nicht vor dem Briefdatum liegen."))
    if not cold:
        checks.append(_check("error", "Die bisherige Nettokaltmiete ist im Mietverlauf nicht erfasst."))
        return
    if new_cold <= cold:
        checks.append(_check("error", "Die neue Nettokaltmiete muss höher sein als die bisherige."))
    start = date.fromisoformat(contract["start_date"])
    changed = last_cold_rent_change(steps)
    if changed is not None and receipt < add_months(changed, 12):
        checks.append(_check("error", f"Die letzte Mieterhöhung galt ab {day(changed)}. Ein neues Verlangen darf "
                                      f"frühestens ein Jahr danach zugehen, also ab {day(add_months(changed, 12))} "
                                      "(§ 558 Abs. 1 Satz 2 BGB)."))
    unchanged_since = changed or start
    if effective < add_months(unchanged_since, 15):
        checks.append(_check("error", f"Die Miete muss zum Wirksamwerden seit 15 Monaten unverändert sein "
                                      f"(§ 558 Abs. 1 Satz 1 BGB). Unverändert seit {day(unchanged_since)}, "
                                      f"also frühestens wirksam ab {day(add_months(unchanged_since, 15))}."))
    base_day = max(start, add_months(effective, -36))
    base = amount((rent_on(steps, base_day) or current).get("cold_rent"))
    modernized = excluded_increases(steps, base_day, effective)
    allowed = (base * (1 + cap / 100) + modernized).quantize(CENT, ROUND_HALF_UP)
    beside = (f" zuzüglich {eur(modernized)} aus Erhöhungen nach §§ 559, 560 BGB, die nicht zählen"
              if modernized else "")
    if new_cold > allowed:
        checks.append(_check("error", f"Die neue Miete überschreitet die Kappungsgrenze: höchstens {eur(allowed)} "
                                      f"({cap} % über {eur(base)} am {day(base_day)}{beside}, § 558 Abs. 3 BGB). "
                                      "Erhöhungen wegen Modernisierung zählen nur, wenn sie im Mietverlauf als "
                                      "Mietanpassung „Modernisierung“ erfasst sind."))
    else:
        checks.append(_check("info", f"Kappungsgrenze eingehalten: höchstens {eur(allowed)} ({cap} % über {eur(base)} "
                                     f"am {day(base_day)}{beside})."))
    first = min(date.fromisoformat(step["valid_from"]) for step in steps)
    checks.append(_check("info", f"Wirksam ab {day(effective)}, Zustimmung bis {day(consent_until)} (§ 558b BGB). "
                                 f"Grundlage der Fristen ist der Mietverlauf im Programm ab {day(first)}."))
    if not area:
        checks.append(_check("warning", "Die Wohnfläche ist nicht erfasst; Angaben je m² entfallen. Für eine "
                                        "Begründung mit dem Mietspiegel wird sie meist gebraucht."))


def _points(value: Decimal) -> str:
    """Index points as published: one decimal, more only when entered."""
    places = next(places for places in (1, 2, 3) if value == value.quantize(Decimal(1).scaleb(-places)))
    return number(value, places)


def _index_rent(source, inputs, issue, values, blocks, checks) -> None:
    contract, steps = source["contract"], source["rent_steps"]
    series = source.get("price_index") or {}
    stored, base_year = series.get("values") or {}, series.get("base_year")
    receipt = date.fromisoformat(inputs["receipt_date"])
    effective = add_months(receipt.replace(day=1), 2)
    base, new = Decimal(inputs["base_index"]), Decimal(inputs["new_index"])
    current = rent_on(steps, receipt) or {}
    cold = amount(current.get("cold_rent"))
    service, heating = amount(current.get("service_charge_advance")), amount(current.get("heating_advance"))
    new_cold = (cold * new / base).quantize(CENT, ROUND_HALF_UP) if base else cold
    change = (new / base - 1) * 100 if base else Decimal(0)
    base_label, new_label = price_index.month_label(inputs["base_month"]), price_index.month_label(inputs["new_month"])
    values.update({
        "index.zugang": day(receipt), "index.wirksam_ab": day(effective),
        "index.basismonat": base_label, "index.basiswert": _points(base),
        "index.neumonat": new_label, "index.neuwert": _points(new),
        "index.basisjahr": str(base_year) if base_year else None,
        "index.veraenderung": f"{number(change, 2)} %",
        "index.bisherige_kaltmiete": eur(cold), "index.neue_kaltmiete": eur(new_cold),
        "index.erhoehung": eur(new_cold - cold), "index.neue_gesamtmiete": eur(new_cold + service + heating),
    })
    blocks["indexmiete"] = {"rows": [
        ["", "bisher", f"ab {day(effective)}"],
        [f"Verbraucherpreisindex ({base_year} = 100)" if base_year else "Verbraucherpreisindex",
         f"{values['index.basiswert']} ({base_label})", f"{values['index.neuwert']} ({new_label})"],
        ["Nettokaltmiete", eur(cold), eur(new_cold)],
        ["Vorauszahlung Betriebskosten", eur(service), eur(service)],
        ["Vorauszahlung Heizkosten", eur(heating), eur(heating)],
        ["Gesamtmiete", eur(cold + service + heating), eur(new_cold + service + heating)]],
        "numeric": [1, 2], "widths": [0.44, 0.28, 0.28], "total": True}

    if residential(source["unit"]) is not True:
        checks.append(_check("warning", "Die Einheit ist keine Wohnung. § 557b BGB gilt für Wohnraum; bei Gewerbe oder "
                                        "Nebenflächen gilt die Wertsicherungsklausel des Vertrags. Bitte den Text "
                                        "(„Wohnung“, Paragrafen, Wirksamkeit) daran anpassen."))
    if rent_model(contract) != "index":
        checks.append(_check("error", "Für diesen Vertrag ist keine Indexmiete vereinbart (Vertrag → Mietanpassung "
                                      "„Indexmiete“). Ohne Indexvereinbarung ist eine Anpassung nach § 557b BGB "
                                      "nicht möglich."))
    if receipt < issue:
        checks.append(_check("error", "Der Zugang kann nicht vor dem Briefdatum liegen."))
    if not cold:
        checks.append(_check("error", "Die bisherige Nettokaltmiete ist im Mietverlauf nicht erfasst."))
        return
    if inputs["new_month"] <= inputs["base_month"]:
        checks.append(_check("error", "Der aktuelle Indexmonat muss nach dem Ausgangsmonat liegen."))
    if inputs["new_month"] > issue.strftime("%Y-%m"):
        checks.append(_check("error", "Der aktuelle Indexmonat liegt nach dem Briefdatum; es zählt nur ein "
                                      "veröffentlichter Index."))
    if new <= base:
        checks.append(_check("error", "Der Index ist seit dem Ausgangsmonat nicht gestiegen; eine Erhöhung nach der "
                                      "Indexvereinbarung ist nicht möglich."))
    for month, entered, label in ((inputs["base_month"], base, "Ausgangsmonat"),
                                  (inputs["new_month"], new, "aktuellen Indexmonat")):
        known = stored.get(month)
        if known is None:
            checks.append(_check("warning", f"Für {price_index.month_label(month)} ist kein Indexwert hinterlegt "
                                            "(Briefvorlagen → Verbraucherpreisindex). Bitte den eingegebenen Wert mit "
                                            "der Veröffentlichung des Statistischen Bundesamts abgleichen."))
        elif Decimal(known) != entered:
            checks.append(_check("warning", f"Der Index für den {label} ({price_index.month_label(month)}) weicht vom "
                                            f"hinterlegten Wert {_points(Decimal(known))} ab."))
    changed = last_cold_rent_change(steps) or date.fromisoformat(contract["start_date"])
    if effective < add_months(changed, 12):
        checks.append(_check("error", f"Bei einer Indexmiete muss die Miete jeweils mindestens ein Jahr unverändert "
                                      f"bleiben (§ 557b Abs. 2 BGB). Unverändert seit {day(changed)}, also frühestens "
                                      f"wirksam ab {day(add_months(changed, 12))}. Erhöhungen nach §§ 559 bis 560 BGB "
                                      "bleiben davon unberührt; gab es solche, bitte den Mietverlauf prüfen."))
    checks.append(_check("info", f"Neue Nettokaltmiete = bisherige Miete × {values['index.neuwert']} ÷ "
                                 f"{values['index.basiswert']}, auf Cent gerundet. Wirksam ab {day(effective)} ohne "
                                 "Zustimmung des Mieters; das Schreiben nennt die Änderung des Index und die neue "
                                 "Miete (§ 557b Abs. 3 BGB)."))
    checks.append(_check("info", "Nach dem Wirksamwerden bitte die neue Miete im Vertrag als Mietanpassung (Index) "
                                 "eintragen; der Brief ändert den Mietverlauf nicht."))


def _advance_adjustment(source, inputs, issue, values, blocks, checks, rent) -> None:
    effective = date.fromisoformat(inputs["effective_date"])
    old = rent_on(source["rent_steps"], effective) or rent or {}
    cold = amount(old.get("cold_rent"))
    service, heating = amount(old.get("service_charge_advance")), amount(old.get("heating_advance"))
    new_service, new_heating = amount(inputs["new_service_charge_advance"]), amount(inputs["new_heating_advance"])
    difference = new_service + new_heating - service - heating
    values.update({
        "vorauszahlung.betriebskosten_neu": eur(new_service), "vorauszahlung.heizkosten_neu": eur(new_heating),
        "vorauszahlung.wirksam_ab": day(effective), "vorauszahlung.abrechnung": inputs["statement_reference"],
        "vorauszahlung.neue_gesamtmiete": eur(cold + new_service + new_heating),
        "vorauszahlung.differenz": ("+" if difference > 0 else "") + eur(difference),
    })
    blocks["vorauszahlung"] = {"rows": [["", "bisher", f"ab {day(effective)}"],
                                        ["Nettokaltmiete (unverändert)", eur(cold), eur(cold)],
                                        ["Vorauszahlung Betriebskosten", eur(service), eur(new_service)],
                                        ["Vorauszahlung Heizkosten", eur(heating), eur(new_heating)],
                                        ["Gesamtmiete", eur(cold + service + heating),
                                         eur(cold + new_service + new_heating)]],
                               "numeric": [1, 2], "widths": [0.5, 0.25, 0.25], "total": True}
    if effective < issue:
        checks.append(_check("error", "Die Anpassung kann nicht rückwirkend gelten."))
    if effective.day != 1:
        checks.append(_check("warning", "Vorauszahlungen ändern sich üblicherweise zum Monatsersten."))
    if not difference and new_service == service:
        checks.append(_check("error", "Die Vorauszahlungen ändern sich nicht."))
    statement = source.get("statement")
    if not statement:
        checks.append(_check("warning", "Für diesen Vertrag liegt im Programm keine ausgestellte Betriebskostenabrechnung "
                                        "vor. Eine Anpassung nach § 560 Abs. 4 BGB setzt eine Abrechnung voraus."))
    elif statement.get("months"):
        monthly = (amount(statement["total_cost"]) / Decimal(str(statement["months"]))).quantize(CENT, ROUND_HALF_UP)
        checks.append(_check("info", f"Kosten laut Abrechnung „{statement['label']}“: {eur(statement['total_cost'])} für "
                                     f"{number(statement['months'], 1)} Monate, also {eur(monthly)} monatlich; bisherige "
                                     f"Vorauszahlungen {eur(service + heating)}."))
        if new_service + new_heating > monthly * Decimal("1.1"):
            checks.append(_check("warning", "Die neuen Vorauszahlungen liegen mehr als 10 % über den Kosten der letzten "
                                            "Abrechnung. Ein pauschaler Sicherheitszuschlag ist nur mit konkreten Gründen "
                                            "(z. B. angekündigte Preiserhöhungen) angemessen."))


def _appointment(inputs, issue, values, checks) -> None:
    when = date.fromisoformat(inputs["appointment_date"])
    start, end = inputs.get("time_from"), inputs.get("time_to")
    reply = date.fromisoformat(inputs["reply_by"]) if inputs.get("reply_by") else max(issue, when - timedelta(days=3))
    time_text = (f"zwischen {start} und {end} Uhr" if start and end else f"ab {start} Uhr" if start
                 else f"bis {end} Uhr" if end else "ganztägig")
    values.update({"termin.art": dict(APPOINTMENTS)[inputs["appointment_type"]], "termin.datum": day(when),
                   "termin.zeit": time_text, "termin.firma": inputs["company"], "termin.anlass": inputs["reason"],
                   "termin.rueckmeldung_bis": day(reply)})
    if when < issue:
        checks.append(_check("error", "Der Termin liegt vor dem Briefdatum."))
    elif when < issue + timedelta(days=7):
        checks.append(_check("warning", "Weniger als eine Woche Vorlauf. Termine in der Wohnung sind rechtzeitig "
                                        "anzukündigen (§ 555a Abs. 2 BGB); Modernisierungen drei Monate vorher "
                                        "(§ 555c BGB)."))
    if start and end and end <= start:
        checks.append(_check("error", "Die Uhrzeit „bis“ muss nach der Uhrzeit „von“ liegen."))
    if reply > when:
        checks.append(_check("error", "Die Rückmeldefrist liegt nach dem Termin."))


# ─── Filling and checking texts ──────────────────────────────────────────────


def known_placeholders(kind: str) -> dict[str, str]:
    return {**GENERAL, **KINDS[kind]["placeholders"]}


def fill(text: str, kind: str, values: dict[str, str | None]) -> str:
    """Placeholders replaced by values; a missing value becomes a visible note, tables stay as they are."""
    labels = known_placeholders(kind)

    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name.startswith("tabelle."):
            return match.group(0)
        value = values.get(name)
        if value is None:
            return MISSING.format(labels.get(name, name))
        return value

    return PLACEHOLDER.sub(replace, text)


def text_problems(kind: str, text: str, *, field: str, filled: bool) -> list[str]:
    """Unknown placeholders, tables not alone on a line, and (in a filled letter) open notes."""
    problems = []
    allowed = known_placeholders(kind)
    for line in text.split("\n"):
        block = BLOCK_LINE.match(line)
        for match in PLACEHOLDER.finditer(line):
            name = match.group(1)
            if name.startswith("tabelle."):
                table = name[len("tabelle."):]
                if table not in KINDS[kind]["blocks"]:
                    problems.append(f"{field}: Die Tabelle „{name}“ gibt es für diese Vorlagenart nicht.")
                elif not block:
                    problems.append(f"{field}: Der Platzhalter {{{{{name}}}}} muss allein in einer Zeile stehen.")
            elif filled or name not in allowed:
                problems.append(f"{field}: Unbekannter Platzhalter {{{{{name}}}}}." if name not in allowed
                                else f"{field}: Der Platzhalter {{{{{name}}}}} ist nicht ausgefüllt.")
    if filled and MISSING_MARK in text:
        problems.append(f"{field}: Bitte alle Stellen „[bitte ergänzen: …]“ ausfüllen oder entfernen.")
    return problems


# ─── Templates: built-in and own ─────────────────────────────────────────────


def builtin(kind: str) -> dict:
    return {"id": BUILTIN_PREFIX + kind, "kind": kind, "builtin": True, "revision": BUILTIN_REVISION,
            "archived": False, "based_on": None, **BUILTIN[kind]}


def _own_rows(unit) -> list[tuple[str, dict]]:
    if unit.db is None:
        rules = state.memory(unit, "rules")
        return [(key, deepcopy(value)) for (scope, key), value in list(rules.items())
                if scope == "global" and key.startswith(TEMPLATE_PREFIX)]
    rows = unit.db.scalars(select(SettingRuleORM).where(SettingRuleORM.scope == "global",
                                                        SettingRuleORM.key.like(TEMPLATE_PREFIX + "%")))
    return [(row.key, {"revision": row.revision, "payload": dict(row.payload or {})}) for row in rows]


def _own(key: str, saved: dict) -> dict | None:
    value = (saved.get("payload") or {}).get("value")
    if not isinstance(value, dict):
        return None
    return {**value, "id": key[len(TEMPLATE_PREFIX):], "builtin": False, "revision": saved["revision"]}


def all_templates(unit, *, archived: bool = False) -> list[dict]:
    own = [template for key, saved in _own_rows(unit) if (template := _own(key, saved))]
    own = [template for template in own if archived or not template.get("archived")]
    own.sort(key=lambda item: (item["kind"], item["name"].casefold(), item["id"]))
    return [builtin(kind) for kind in KINDS] + own


def template(unit, template_id: str) -> dict:
    if template_id.startswith(BUILTIN_PREFIX):
        kind = template_id[len(BUILTIN_PREFIX):]
        if kind not in BUILTIN:
            raise HTTPException(404, "Briefvorlage nicht gefunden.")
        return builtin(kind)
    if not re.fullmatch(r"[0-9a-f-]{36}", template_id):
        raise HTTPException(404, "Briefvorlage nicht gefunden.")
    found = _own(TEMPLATE_PREFIX + template_id, rule(unit, "global", TEMPLATE_PREFIX + template_id))
    if found is None:
        raise HTTPException(404, "Briefvorlage nicht gefunden.")
    return found


def catalogue() -> dict:
    """Kinds with inputs, placeholders and tables, for the template editor and the letter dialog."""
    return {"kinds": [{"kind": kind, "label": spec["label"], "description": spec["description"],
                       "inputs": spec["inputs"],
                       "placeholders": [{"name": name, "label": label} for name, label in known_placeholders(kind).items()],
                       "blocks": [{"name": "tabelle." + name, "label": BLOCKS[name]} for name in spec["blocks"]]}
                      for kind, spec in KINDS.items()]}


def _clean_text(payload: dict) -> dict:
    result = {}
    for key, limit in TEXT_LIMITS.items():
        value = payload.get(key, "")
        if not isinstance(value, str):
            raise HTTPException(422, "Ungültiger Text in der Vorlage.")
        value = value.replace("\r\n", "\n").strip()
        multiline = key in ("body", "appendix")
        if len(value) > limit or any((ord(char) < 32 and not (multiline and char == "\n")) or ord(char) == 127
                                     for char in value):
            raise HTTPException(422, f"Vorlage: höchstens {limit} Zeichen ohne Steuerzeichen.")
        result[key] = value
    if not result["name"] or not result["subject"]:
        raise HTTPException(422, "Bitte Name und Betreff der Vorlage angeben.")
    return result


def save(store, actor_id: str, payload: dict) -> dict:
    """Create (no id) or change an own template against its revision; the kind never changes."""
    allowed = {"id", "kind", "base_revision", "idempotency_key", "based_on", "archived", *TEXT_LIMITS}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise HTTPException(422, "Unbekannte Felder in der Vorlage.")
    key = payload.get("idempotency_key")
    if not isinstance(key, str) or not 8 <= len(key) <= 120:
        raise HTTPException(422, "Ungültige Vorgangskennung.")
    identifier = payload.get("id")
    kind = payload.get("kind")
    with archive.work(store, actor_id, write_areas=(WRITE_AREA,)) as unit:
        if unit.user["role"] not in ("eigentuemer", "verwalter"):
            raise HTTPException(403, "Briefvorlagen ändern Eigentümer und Verwaltung.")
        fingerprint = state.digest("letter_template", {k: v for k, v in payload.items() if k != "idempotency_key"})
        saved = state.replay(unit, key, fingerprint)
        if saved is not None:
            return saved
        before: dict[str, Any]
        created: dict[str, Any]
        if identifier is None:
            if kind not in KINDS:
                raise HTTPException(422, "Bitte eine gültige Vorlagenart wählen.")
            identifier, before = str(uuid4()), {"revision": 0, "payload": {}}
            base_revision = 0
            created = {"created_by": actor_id, "created_at": datetime.now(timezone.utc).isoformat()}
            based_on = payload.get("based_on")
            if based_on is not None and (not isinstance(based_on, str) or not based_on.startswith(BUILTIN_PREFIX)
                                         or based_on[len(BUILTIN_PREFIX):] not in BUILTIN):
                raise HTTPException(422, "Unbekannte Ausgangsvorlage.")
        else:
            if not isinstance(identifier, str) or identifier.startswith(BUILTIN_PREFIX):
                raise HTTPException(409, "Mitgelieferte Vorlagen sind fest. Bitte eine Kopie anlegen und diese ändern.")
            before = rule(unit, "global", TEMPLATE_PREFIX + identifier)
            current = _own(TEMPLATE_PREFIX + identifier, before)
            if current is None:
                raise HTTPException(404, "Briefvorlage nicht gefunden.")
            if kind is not None and kind != current["kind"]:
                raise HTTPException(422, "Die Art einer Vorlage lässt sich nicht ändern.")
            kind, based_on = current["kind"], current.get("based_on")
            expected = payload.get("base_revision")
            if type(expected) is not int or expected != before["revision"]:
                raise HTTPException(409, "Die Vorlage wurde zwischenzeitlich geändert. Bitte neu laden.")
            base_revision = expected
            created = {"created_by": current.get("created_by"), "created_at": current.get("created_at")}
        texts = _clean_text(payload)
        problems = [problem for field, label in (("subject", "Betreff"), ("salutation", "Anrede"), ("body", "Text"),
                                                 ("closing", "Schlussformel"), ("appendix", "Anhang"))
                    for problem in text_problems(kind, texts[field], field=label, filled=False)]
        if problems:
            raise HTTPException(422, " ".join(problems[:5]))
        archived = payload.get("archived", False)
        if type(archived) is not bool:
            raise HTTPException(422, "Ungültige Angabe zum Archivieren.")
        value = {"kind": kind, **texts, "archived": archived, "based_on": based_on, **created,
                 "updated_by": actor_id, "updated_at": datetime.now(timezone.utc).isoformat()}
        result: dict[str, Any] = {"revision": base_revision + 1, "payload": {"value": value}}
        rule_key = TEMPLATE_PREFIX + identifier
        if unit.db is None:
            unit.insert(state.memory(unit, "rules"), ("global", rule_key), result)
        else:
            row = unit.db.scalar(select(SettingRuleORM).where(SettingRuleORM.scope == "global",
                                                              SettingRuleORM.key == rule_key).with_for_update())
            if row is None:
                row = SettingRuleORM(scope="global", key=rule_key)
                unit.db.add(row)
            row.revision, row.payload, row.updated_at = result["revision"], result["payload"], state.now()
            unit.db.flush()
        record_audit(unit, key, "settings_change", rule_key, before.get("payload", {}).get("value"), value)
        response = {**value, "id": identifier, "builtin": False, "revision": result["revision"]}
        state.remember(unit, key, fingerprint, response)
        return response


def listing(store, actor_id: str, *, archived: bool = False) -> dict:
    with archive.work(store, actor_id) as unit:
        return {"items": all_templates(unit, archived=archived), **catalogue()}
