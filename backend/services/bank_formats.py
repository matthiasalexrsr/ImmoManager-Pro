"""Strict bank formats. Amounts are signed integer cents; raw source is never discarded."""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree import ElementTree as ET

from . import safe_xml


class BankFormatError(ValueError):
    pass


def cents(value: str, decimal: str = ".") -> int:
    value = value.strip().replace("\u00a0", "").replace(" ", "")
    if decimal == ",":
        if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d{1,2})?", value):
            raise BankFormatError("Ungültiger Centbetrag")
        value = value.replace(".", "").replace(",", ".")
    elif not re.fullmatch(r"[+-]?\d+(?:\.\d{1,2})?", value):
        raise BankFormatError("Ungültiger Centbetrag")
    try:
        result = Decimal(value) * 100
        if not result.is_finite() or abs(result) > 99999999999999:
            raise BankFormatError("Betrag außerhalb des unterstützten Bereichs")
        return int(result)
    except InvalidOperation:
        raise BankFormatError("Ungültiger Centbetrag") from None


def day(value: str, pattern: str = "%Y-%m-%d") -> str:
    try:
        return datetime.strptime(value.strip(), pattern).date().isoformat()
    except ValueError:
        raise BankFormatError("Ungültiges Buchungsdatum") from None


def csv_rows(text: str, options: dict) -> tuple[list, list, dict]:
    delimiter = options.get("delimiter", ";")
    if delimiter not in (";", ",", "\t", "|"):
        raise BankFormatError("Nicht unterstütztes Trennzeichen")
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        headers = next(reader)
    except (StopIteration, csv.Error):
        raise BankFormatError("Die CSV-Kopfzeile fehlt") from None
    if len(set(headers)) != len(headers) or any(not h.strip() for h in headers):
        raise BankFormatError("Spaltennamen müssen eindeutig und ausgefüllt sein")
    mapping = options.get("columns", {"date": "date", "amount": "amount", "text": "text"})
    if not all(mapping.get(key) in headers for key in ("date", "amount", "text")):
        raise BankFormatError("Bitte Datum, Betrag und Verwendungszweck vorhandenen Spalten zuweisen")
    rows, errors = [], []
    try:
        for number, values in enumerate(reader, 2):
            if not values:
                continue
            raw = dict(zip(headers, values, strict=False))
            try:
                if len(values) != len(headers):
                    raise BankFormatError("Anzahl der Spalten stimmt nicht mit der Kopfzeile überein")
                amount = cents(raw[mapping["amount"]], options.get("decimal", "."))
                if amount == 0:
                    raise BankFormatError("Nullbuchungen werden nicht übernommen")
                rows.append({"line": number, "date": day(raw[mapping["date"]], options.get("date_format", "%Y-%m-%d")),
                             "cents": amount, "currency": raw.get(mapping.get("currency"), "EUR").strip(),
                             "text": raw[mapping["text"]], "reference": raw.get(mapping.get("reference"), "").strip(), "raw": raw})
            except BankFormatError as exc:
                errors.append({"line": number, "error": str(exc), "raw": values})
    except csv.Error:
        errors.append({"line": reader.line_num, "error": "Ungültige CSV-Quotierung", "raw": []})
    return rows, errors, {"headers": headers}


def mt940_rows(text: str) -> tuple[list, list, dict]:
    tags = []
    for line in text.replace("\r\n", "\n").split("\n"):
        match = re.match(r"^:(\d{2}[A-Z]?):(.*)$", line)
        if match:
            tags.append([match[1], match[2]])
        elif tags:
            tags[-1][1] += "\n" + line
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    statements: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    opening: tuple[int, str] | None = None
    subtotal = 0
    for tag, value in tags:
        try:
            if tag in ("60F", "60M", "62F", "62M"):
                match = re.fullmatch(r"([CD])(\d{6})([A-Z]{3})([\d,]+)\s*", value)
                if not match:
                    raise BankFormatError("Ungültiger MT940-Saldo")
                amount = cents(match[4], ",") * (1 if match[1] == "C" else -1)
                if tag.startswith("60"):
                    if opening is not None:
                        raise BankFormatError("MT940-Abschlusssaldo fehlt")
                    opening, subtotal = (amount, match[3]), 0
                else:
                    if opening is None or opening[1] != match[3] or opening[0] + subtotal != amount:
                        raise BankFormatError("MT940-Salden stimmen nicht mit den Bewegungen überein")
                    statements.append({"opening_cents": opening[0], "closing_cents": amount, "currency": match[3]})
                    opening = None
            elif tag == "61":
                match = re.match(r"^(\d{6})(\d{4})?(R?[CD])([A-Z])?([\d,]+)([A-Z][A-Z0-9]{3})(.*)$", value, re.S)
                if not match or opening is None:
                    raise BankFormatError("Ungültige MT940-Bewegung oder fehlender Anfangssaldo")
                sign = {"C": 1, "D": -1, "RC": -1, "RD": 1}[match[3]]
                amount = cents(match[5], ",") * sign
                value_date = date.fromisoformat(day(match[1], '%y%m%d'))
                booked_date = value_date
                if match[2]:
                    month, day_of_month = int(match[2][:2]), int(match[2][2:])
                    candidates = []
                    for year in (value_date.year - 1, value_date.year, value_date.year + 1):
                        try:
                            candidates.append(date(year, month, day_of_month))
                        except ValueError:
                            continue
                    if not candidates:
                        raise BankFormatError('Ungültiges MT940-Buchungsdatum')
                    booked_date = min(candidates, key=lambda candidate: abs((candidate - value_date).days))
                reference = match[7].split("\n", 1)[0]
                # Customer references such as NONREF are not globally unique bank identifiers.
                bank_reference = reference.split("//", 1)[1] if "//" in reference else ""
                current = {"line": len(rows) + 1, "date": booked_date.isoformat(), "value_date": value_date.isoformat(), "cents": amount,
                           "currency": opening[1], "text": "", "reference": bank_reference,
                           "reversal": match[3].startswith("R"), "raw": {"61": value}}
                rows.append(current)
                subtotal += amount
            elif tag == "86" and current is not None:
                current["text"] += value
                current["raw"].setdefault("86", []).append(value)
        except BankFormatError as exc:
            errors.append({"line": len(rows) + 1, "error": str(exc), "raw": {tag: value}})
    if opening is not None or not statements:
        errors.append({"line": 0, "error": "Vollständige MT940-Anfangs-/Abschlusssalden fehlen", "raw": tags})
    return rows, errors, {"statements": statements, "tags": tags}


CAMT_NAMESPACES = {f"urn:iso:std:iso:20022:tech:xsd:camt.{kind}.001.{version}"
                   for kind in ("052", "053", "054") for version in ("02", "04", "08", "10")}


def camt_rows(text: str) -> tuple[list, list, dict]:
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise BankFormatError("XML-Dokumenttypen und Entitäten sind nicht erlaubt")
    try:
        root = safe_xml.fromstring(text)
    except ET.ParseError:
        raise BankFormatError("Ungültige CAMT-XML-Datei") from None
    namespace = root.tag.partition("}")[0].lstrip("{")
    if namespace not in CAMT_NAMESPACES or root.tag != f"{{{namespace}}}Document":
        raise BankFormatError("Nicht unterstützter CAMT-Namespace")
    ns = {"b": namespace}

    def nodes(element, path):
        return element.findall("/".join("b:" + part for part in path.split("/")), ns)

    def val(element, path, default=""):
        found = nodes(element, path)
        return (found[0].text or "").strip() if found else default

    def signed(element, amount_path="Amt", inherited=""):
        amounts = nodes(element, amount_path)
        if len(amounts) != 1:
            raise BankFormatError("Eindeutiger CAMT-Betrag fehlt")
        indicator = val(element, "CdtDbtInd", inherited)
        if indicator not in ("CRDT", "DBIT"):
            raise BankFormatError("CAMT-Soll-/Haben-Kennzeichen fehlt")
        number = cents(amounts[0].text or "")
        if number < 0:
            raise BankFormatError("CAMT-Betrag muss vorzeichenlos sein")
        return number * (1 if indicator == "CRDT" else -1), amounts[0].get("Ccy", "")

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    kind = namespace.split(':')[-1].split('.')[1]
    path = {'052': 'BkToCstmrAcctRpt/Rpt', '053': 'BkToCstmrStmt/Stmt', '054': 'BkToCstmrDbtCdtNtfctn/Ntfctn'}[kind]
    statements = nodes(root, path)
    if not statements:
        raise BankFormatError("Keine CAMT-Kontoauszüge gefunden")
    for statement in statements:
        total, balances = 0, {}
        for balance in nodes(statement, "Bal"):
            code = val(balance, "Tp/CdOrPrtry/Cd")
            if code in ("OPBD", "CLBD"):
                if code in balances:
                    raise BankFormatError("Mehrdeutiger CAMT-Buchsaldo")
                balances[code] = signed(balance)
        for entry in nodes(statement, "Ntry"):
            raw = ET.tostring(entry, encoding="unicode")
            try:
                amount, currency = signed(entry)
                status = val(entry, "Sts/Cd") or val(entry, "Sts")
                if status != "BOOK":
                    raise BankFormatError("Nur endgültig gebuchte CAMT-Bewegungen werden übernommen")
                booked = val(entry, "BookgDt/Dt") or val(entry, "BookgDt/DtTm")[:10]
                date.fromisoformat(booked)
                details = nodes(entry, "NtryDtls/TxDtls")
                pieces = []
                for detail in details:
                    if nodes(detail, "Amt"):
                        pieces.append(signed(detail, inherited=val(entry, "CdtDbtInd")))
                    elif nodes(detail, "AmtDtls/TxAmt/Amt"):
                        pieces.append(signed(detail, "AmtDtls/TxAmt/Amt", val(entry, "CdtDbtInd")))
                if pieces and (len(pieces) != len(details) or any(c != currency for _, c in pieces)
                               or sum(a for a, _ in pieces) != amount):
                    raise BankFormatError("CAMT-Unterpositionen stimmen nicht mit der Sammelbuchung überein")
                selected = list(zip(details, pieces)) if pieces else [(entry, (amount, currency))]
                for detail, (part, ccy) in selected:
                    reference = val(detail, "Refs/AcctSvcrRef") or val(detail, "AcctSvcrRef")
                    text_parts = [e.text for e in detail.iter() if e.tag in
                                  {f"{{{namespace}}}{name}" for name in ("Ustrd", "AddtlNtryInf", "AddtlTxInf", "Nm")} and e.text]
                    rows.append({"line": len(rows) + 1, "date": booked, "cents": part, "currency": ccy,
                                 "reference": reference, "text": " ".join(text_parts),
                                 "reversal": val(entry, "RvslInd") in ("true", "1"), "raw": raw})
                total += amount
            except (BankFormatError, ValueError) as exc:
                errors.append({"line": len(rows) + 1, "error": str(exc), "raw": raw})
        if "OPBD" in balances and "CLBD" in balances:
            start, end = balances["OPBD"], balances["CLBD"]
            if start[1] != end[1] or start[0] + total != end[0]:
                errors.append({"line": 0, "error": "CAMT-Salden stimmen nicht mit den Bewegungen überein", "raw": balances})
        summaries.append({"id": val(statement, "Id"), "iban": val(statement, "Acct/Id/IBAN"),
                          "balances": balances, "movement_cents": total})
    return rows, errors, {"namespace": namespace, "statements": summaries}


def parse(raw: bytes, format: str, options: dict) -> dict:
    for name in ('encoding', 'delimiter', 'decimal', 'date_format'):
        if name in options and (not isinstance(options[name], str) or len(options[name]) > 128):
            raise BankFormatError('Ungültige Formateinstellung: ' + name)
    if options.get('decimal', '.') not in ('.', ','):
        raise BankFormatError('Das Dezimalzeichen muss Punkt oder Komma sein')
    if 'columns' in options and (not isinstance(options['columns'], dict)
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in options['columns'].items())):
        raise BankFormatError('Spaltenzuordnungen müssen Spaltennamen enthalten')
    encoding = options.get("encoding", "utf-8-sig")
    if encoding not in ("utf-8", "utf-8-sig", "cp1252", "iso-8859-1", "utf-16"):
        raise BankFormatError("Nicht unterstützte Kodierung")
    try:
        text = raw.decode(encoding, errors="strict")
    except UnicodeError:
        raise BankFormatError("Datei passt nicht zur gewählten Kodierung") from None
    if format == "csv":
        rows, errors, metadata = csv_rows(text, options)
    elif format == "mt940":
        rows, errors, metadata = mt940_rows(text)
    elif format == "camt":
        rows, errors, metadata = camt_rows(text)
    else:
        raise BankFormatError("Nicht unterstütztes Bankformat")
    if not rows and not errors:
        errors.append({"line": 0, "error": "Keine Buchungen gefunden", "raw": ""})
    for row in rows:
        if row["currency"] != "EUR" or not row["cents"]:
            errors.append({"line": row["line"], "error": "Nur EUR-Buchungen mit einem Betrag ungleich Null sind unterstützt", "raw": row["raw"]})
    return {"rows": rows, "errors": errors, "metadata": metadata, "total_cents": sum(row["cents"] for row in rows)}
