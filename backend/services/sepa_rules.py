"""SEPA rules the direct debit file depends on: IBAN, BIC, creditor identifier, the
character set, TARGET2 business days, and the pain.008.001.08 message itself.

Pure functions without storage, so they can be checked in isolation. The message
follows ISO 20022 pain.008.001.08 as the German banks expect it since November 2023
(DFÜ-Abkommen, Anlage 3, Version 3.7): one payment information block per file,
SEPA Core, sequence type RCUR (since the 2016 rulebook a first collection may be
sent as RCUR too), purpose RENT.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal
from xml.etree import ElementTree as ET

NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"

# Lengths of the IBAN in SEPA countries (EPC409); others are checked by the checksum only.
IBAN_LENGTHS = {
    "AD": 24, "AT": 20, "BE": 16, "BG": 22, "CH": 21, "CY": 28, "CZ": 24, "DE": 22, "DK": 18, "EE": 20,
    "ES": 24, "FI": 18, "FR": 27, "GB": 22, "GI": 23, "GR": 27, "HR": 21, "HU": 28, "IE": 22, "IS": 26,
    "IT": 27, "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MC": 27, "MT": 31, "NL": 18, "NO": 15, "PL": 28,
    "PT": 25, "RO": 24, "SE": 24, "SI": 19, "SK": 24, "SM": 27, "VA": 22,
}
BIC = re.compile(r"^[A-Z]{6}[A-Z2-9][A-NP-Z0-9]([A-Z0-9]{3})?$")
CREDITOR_ID = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{3}[A-Z0-9]{1,28}$")
# Identifiers (mandate reference, message and end-to-end ids): the SEPA set without the space.
IDENTIFIER = re.compile(r"^[A-Za-z0-9+?/:().,'\-]{1,35}$")
_TEXT_ALLOWED = re.compile(r"[^A-Za-z0-9/?:().,'+\- ]")
_GERMAN = str.maketrans({"Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "&": "+",
                         "€": "EUR", "–": "-", "—": "-", "„": "", "“": "", "”": "", "‚": "", "‘": "", "’": "'"})


def _letters_to_digits(value: str) -> str:
    return "".join(str(int(char, 36)) for char in value)


def compact(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def iban_problem(value: str | None) -> str | None:
    """None for a valid IBAN, else what is wrong with it."""
    iban = compact(value)
    if not iban:
        return "IBAN fehlt."
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", iban):
        return "IBAN hat kein gültiges Format."
    if iban[:2] in IBAN_LENGTHS and len(iban) != IBAN_LENGTHS[iban[:2]]:
        return f"Eine IBAN aus {iban[:2]} hat {IBAN_LENGTHS[iban[:2]]} Stellen, nicht {len(iban)}."
    if int(_letters_to_digits(iban[4:] + iban[:4])) % 97 != 1:
        return "Die Prüfziffer der IBAN stimmt nicht."
    return None


def bic_problem(value: str | None) -> str | None:
    bic = compact(value)
    if bic and not BIC.match(bic):
        return "BIC hat kein gültiges Format (8 oder 11 Zeichen)."
    return None


def creditor_id_problem(value: str | None) -> str | None:
    """Gläubiger-Identifikationsnummer: country, check digits, business code, national id.

    The check digits are computed over the national id followed by the country and "00";
    the business code (positions 5-7) is not part of it."""
    creditor = compact(value)
    if not creditor:
        return "Gläubiger-ID fehlt."
    if len(creditor) > 35 or not CREDITOR_ID.match(creditor):
        return "Gläubiger-ID hat kein gültiges Format (z. B. DE98ZZZ09999999999)."
    check = 98 - int(_letters_to_digits(creditor[7:] + creditor[:2] + "00")) % 97
    if f"{check:02d}" != creditor[2:4]:
        return "Die Prüfziffer der Gläubiger-ID stimmt nicht."
    return None


def mandate_problem(value: str | None) -> str | None:
    reference = (value or "").strip()
    if not reference:
        return "Mandatsreferenz fehlt."
    if not IDENTIFIER.match(reference):
        return ("Mandatsreferenz: höchstens 35 Zeichen, nur Buchstaben ohne Umlaute, Ziffern und + ? / - : ( ) . , ' "
                "– Leerzeichen sind nicht zulässig.")
    return None


def text(value: str | None, limit: int) -> str:
    """Text in the SEPA character set: umlauts transliterated, other characters dropped."""
    plain = unicodedata.normalize("NFKD", (value or "").translate(_GERMAN))
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", _TEXT_ALLOWED.sub("", plain)).strip()[:limit].strip()


def identifier(value: str, limit: int = 35) -> str:
    return re.sub(r"[^A-Za-z0-9+?/:().,'\-]", "", text(value, 200).replace(" ", "-"))[:limit]


def mask_iban(iban: str | None) -> str:
    value = compact(iban)
    return f"{value[:4]} … {value[-4:]}" if len(value) > 8 else value


# ─── TARGET2 business days ───────────────────────────────────────────────────

def _easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def target_holiday(day: date) -> str | None:
    """The TARGET2 closing day, if `day` is one (weekends are checked separately)."""
    easter = _easter(day.year)
    fixed = {(1, 1): "Neujahr", (5, 1): "1. Mai", (12, 25): "1. Weihnachtstag", (12, 26): "2. Weihnachtstag"}
    if (day.month, day.day) in fixed:
        return fixed[(day.month, day.day)]
    if day == easter - timedelta(days=2):
        return "Karfreitag"
    if day == easter + timedelta(days=1):
        return "Ostermontag"
    return None


def business_day(day: date) -> bool:
    return day.weekday() < 5 and target_holiday(day) is None


def next_business_day(day: date) -> date:
    while not business_day(day):
        day += timedelta(days=1)
    return day


def collection_date_problem(day: date, today: date) -> str | None:
    """SEPA Core: the bank needs the file at least one TARGET2 business day before collection."""
    if day.weekday() >= 5 or target_holiday(day):
        reason = target_holiday(day) or ("Samstag" if day.weekday() == 5 else "Sonntag")
        return (f"Der {day:%d.%m.%Y} ist kein Bankarbeitstag ({reason}); nächster Bankarbeitstag: "
                f"{next_business_day(day):%d.%m.%Y}.")
    earliest = next_business_day(today + timedelta(days=1))
    if day < earliest:
        return f"Das Fälligkeitsdatum muss mindestens einen Bankarbeitstag nach heute liegen, frühestens {earliest:%d.%m.%Y}."
    if day > today + timedelta(days=365):
        return "Das Fälligkeitsdatum darf höchstens ein Jahr in der Zukunft liegen."
    return None


# ─── The message ─────────────────────────────────────────────────────────────

def _sub(parent: ET.Element, tag: str, value: str | None = None, **attributes: str) -> ET.Element:
    element = ET.SubElement(parent, tag, attributes)
    if value is not None:
        element.text = value
    return element


def _agent(parent: ET.Element, tag: str, bic: str | None) -> None:
    institution = _sub(_sub(parent, tag), "FinInstnId")
    if bic:
        _sub(institution, "BICFI", bic)
    else:
        _sub(_sub(institution, "Othr"), "Id", "NOTPROVIDED")


def amount(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def pain008(*, message_id: str, created: datetime, creditor_name: str, creditor_iban: str, creditor_bic: str | None,
            creditor_id: str, collection_date: date, transactions: list[dict]) -> bytes:
    """pain.008.001.08 with one payment information block.

    transactions: end_to_end_id, amount (Decimal), mandate_id, mandate_date (date),
    debtor_name, debtor_iban, debtor_bic (or None), remittance."""
    if not transactions:
        raise ValueError("Keine Lastschriften")
    total = sum((item["amount"] for item in transactions), Decimal("0"))
    ET.register_namespace("", NAMESPACE)
    document = ET.Element(f"{{{NAMESPACE}}}Document")
    root = _sub(document, "CstmrDrctDbtInitn")
    header = _sub(root, "GrpHdr")
    _sub(header, "MsgId", message_id)
    _sub(header, "CreDtTm", created.strftime("%Y-%m-%dT%H:%M:%S"))
    _sub(header, "NbOfTxs", str(len(transactions)))
    _sub(header, "CtrlSum", amount(total))
    _sub(_sub(header, "InitgPty"), "Nm", text(creditor_name, 70))
    block = _sub(root, "PmtInf")
    _sub(block, "PmtInfId", identifier(message_id + "-1"))
    _sub(block, "PmtMtd", "DD")
    _sub(block, "BtchBookg", "true")
    _sub(block, "NbOfTxs", str(len(transactions)))
    _sub(block, "CtrlSum", amount(total))
    kind = _sub(block, "PmtTpInf")
    _sub(_sub(kind, "SvcLvl"), "Cd", "SEPA")
    _sub(_sub(kind, "LclInstrm"), "Cd", "CORE")
    _sub(kind, "SeqTp", "RCUR")
    _sub(block, "ReqdColltnDt", collection_date.isoformat())
    _sub(_sub(block, "Cdtr"), "Nm", text(creditor_name, 70))
    _sub(_sub(_sub(block, "CdtrAcct"), "Id"), "IBAN", compact(creditor_iban))
    _agent(block, "CdtrAgt", compact(creditor_bic) or None)
    _sub(block, "ChrgBr", "SLEV")
    scheme = _sub(_sub(_sub(_sub(block, "CdtrSchmeId"), "Id"), "PrvtId"), "Othr")
    _sub(scheme, "Id", compact(creditor_id))
    _sub(_sub(scheme, "SchmeNm"), "Prtry", "SEPA")
    for item in transactions:
        entry = _sub(block, "DrctDbtTxInf")
        _sub(_sub(entry, "PmtId"), "EndToEndId", item["end_to_end_id"])
        _sub(entry, "InstdAmt", amount(item["amount"]), Ccy="EUR")
        mandate = _sub(_sub(entry, "DrctDbtTx"), "MndtRltdInf")
        _sub(mandate, "MndtId", item["mandate_id"])
        _sub(mandate, "DtOfSgntr", item["mandate_date"].isoformat())
        _agent(entry, "DbtrAgt", compact(item.get("debtor_bic")) or None)
        _sub(_sub(entry, "Dbtr"), "Nm", text(item["debtor_name"], 70))
        _sub(_sub(_sub(entry, "DbtrAcct"), "Id"), "IBAN", compact(item["debtor_iban"]))
        _sub(_sub(entry, "Purp"), "Cd", "RENT")
        _sub(_sub(entry, "RmtInf"), "Ustrd", text(item["remittance"], 140))
    ET.indent(document)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(document, encoding="utf-8")
