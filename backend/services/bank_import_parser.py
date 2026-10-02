"""Streaming bank rows with explicit mapping, integer cents and readable errors.

mt-940 converts each individual physical :61: independently. It never receives
the entire file, and cannot merge two legitimate transactions with equal text.
"""
import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from threading import Lock
from typing import BinaryIO, Literal

import mt940
from pydantic import BaseModel, ConfigDict, Field, model_validator

_csv_capacity_lock = Lock()


class BankMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    format: Literal["csv", "mt940"] = "csv"
    encoding: Literal["utf-8-sig", "utf-16", "cp1252"] = "utf-8-sig"
    delimiter: Literal[";", ",", "\t"] = ";"
    date_column: str = Field(default="date", min_length=1, max_length=200)
    amount_column: str = Field(default="amount", min_length=1, max_length=200)
    text_column: str | None = Field(default="text", min_length=1, max_length=200)
    reference_column: str | None = Field(default=None, min_length=1, max_length=200)
    reference_namespace: str = Field(default="bank_transaction_id", min_length=1, max_length=100)
    date_format: Literal["%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y"] = "%Y-%m-%d"
    decimal_separator: Literal[".", ",", "legacy"] = "legacy"
    thousands_separator: Literal[".", ",", " ", "\u00a0", "\u202f"] | None = None
    currency: Literal["EUR"] = "EUR"

    @model_validator(mode="after")
    def distinct(self):
        columns = [x for x in (self.date_column, self.amount_column, self.text_column, self.reference_column) if x]
        if len(columns) != len(set(columns)):
            raise ValueError("CSV-Spalten müssen verschieden sein.")
        if self.thousands_separator and self.decimal_separator in {self.thousands_separator, "legacy"}:
            raise ValueError("Tausender- und Dezimaltrennzeichen müssen ausdrücklich verschieden sein.")
        return self


class BankParseError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BankRow:
    ordinal: int
    source_line: int
    booking_date: date | None = None
    value_date: date | None = None
    amount_cents: int | None = None
    text: str = ""
    bank_reference: str | None = None
    identity: str | None = None
    error_code: str | None = None
    error_message: str | None = None


def parse_amount_cents(raw: str, mapping: BankMapping) -> int:
    """Exact syntax conversion independent of the application's money column."""
    value = raw.strip()
    separator = mapping.decimal_separator
    if separator == "legacy":
        if "," in value and "." in value:
            raise BankParseError("AMOUNT_AMBIGUOUS", "Dezimal-/Tausendertrennzeichen ausdrücklich auswählen.")
        separator = "," if "," in value else "."
    integer = r"\d+"
    if mapping.thousands_separator:
        group = re.escape(mapping.thousands_separator)
        integer = rf"(?:\d+|\d{{1,3}}(?:{group}\d{{3}})+)"
    if not re.fullmatch(rf"[+-]?{integer}(?:{re.escape(separator)}\d{{1,2}})?", value):
        raise BankParseError("AMOUNT_INVALID", "Betrag muss eine Zahl mit höchstens zwei Nachkommastellen sein.")
    normalized = value.replace(mapping.thousands_separator, "") if mapping.thousands_separator else value
    integer_part, _, fraction = normalized.replace(separator, ".").partition(".")
    sign = -1 if integer_part.startswith("-") else 1
    try:
        # Integer assembly avoids Decimal context rounding on large amounts.
        return sign * (int(integer_part.lstrip("+-")) * 100 + int(fraction.ljust(2, "0")))
    except ValueError:
        raise BankParseError("AMOUNT_CAPACITY", "Betragslänge überschreitet die technische Parserkapazität.") from None


def amount_cents(raw: str, mapping: BankMapping) -> int:
    cents = parse_amount_cents(raw, mapping)
    if not cents:
        raise BankParseError("AMOUNT_ZERO", "Eine Bankbuchung darf keinen Nullbetrag haben.")
    if abs(cents) > 999_999_999_999:
        raise BankParseError("AMOUNT_CAPACITY", "Betrag überschreitet die bestehende Datenbank-Geldspalte.")
    return cents


def _error(ordinal, line, error):
    return BankRow(ordinal, line, error_code=error.code, error_message=str(error))


def _csv_rows(stream, mapping, maximum_field_chars):
    # csv's process-global safety ceiling is only ever raised. Each input keeps
    # its own stricter bounded adapter, including quoted multi-line fields.
    with _csv_capacity_lock:
        if csv.field_size_limit() < maximum_field_chars:
            csv.field_size_limit(maximum_field_chars)
    reader = csv.reader(_csv_lines(stream, mapping.delimiter, maximum_field_chars), delimiter=mapping.delimiter, strict=True)
    ordinal = 0
    try:
        header = next(reader, None)
        required = [x for x in (mapping.date_column, mapping.amount_column, mapping.text_column, mapping.reference_column) if x]
        if not header or len(header) != len(set(header)) or not set(required) <= set(header):
            raise BankParseError("CSV_HEADER", "CSV-Kopfzeile fehlt, enthält doppelte Spalten oder passt nicht zur Zuordnung.")
        indices = {key: header.index(key) for key in required}
        for values in reader:
            if not values:
                continue
            ordinal += 1
            try:
                if len(values) != len(header):
                    raise BankParseError("CSV_COLUMNS", "Zeile hat eine andere Spaltenanzahl als die Kopfzeile.")
                if any(len(value) > maximum_field_chars for value in values):
                    raise BankParseError("FIELD_CAPACITY", "Feld überschreitet die konfigurierte Textkapazität; Mapping oder Serverkapazität prüfen.")
                raw_date = values[indices[mapping.date_column]].strip()
                try:
                    booking_date = datetime.strptime(raw_date, mapping.date_format).date()
                    if booking_date.strftime(mapping.date_format) != raw_date:
                        raise ValueError
                except ValueError:
                    raise BankParseError("DATE_INVALID", "Datum passt nicht zum ausdrücklich gewählten Datumsformat.") from None
                cents = amount_cents(values[indices[mapping.amount_column]], mapping)
                text = values[indices[mapping.text_column]].strip() if mapping.text_column else ""
                reference = values[indices[mapping.reference_column]].strip() if mapping.reference_column else None
                yield BankRow(ordinal, reader.line_num, booking_date, booking_date, cents, text,
                    reference or None, f"csv:{mapping.reference_namespace}:{reference}" if reference else None)
            except BankParseError as error:
                yield _error(ordinal, reader.line_num, error)
        if ordinal == 0:
            yield _error(1, reader.line_num, BankParseError("EMPTY_FILE", "CSV-Datei enthält keine Transaktionszeilen."))
    except csv.Error:
        yield _error(ordinal + 1, reader.line_num, BankParseError("CSV_SYNTAX", "CSV-Syntax oder Parser-Feldkapazität ungültig. Datei/Mappings bzw. Serverkapazität prüfen."))
    except BankParseError as error:
        yield _error(ordinal + 1, reader.line_num, error)


def _csv_lines(stream, delimiter, maximum):
    state, field_size = "start", 0
    while line := stream.readline(maximum * 8 + 1):
        if len(line) > maximum * 8:
            raise BankParseError("RECORD_CAPACITY", "CSV-Zeile überschreitet die konfigurierte technische Kapazität.")
        for character in line:
            if state == "quoted":
                if character == '"':
                    state = "after_quote"
                else:
                    field_size += 1
            elif state == "after_quote" and character == '"':
                state = "quoted"
                field_size += 1
            elif character == delimiter or character in "\r\n":
                state = "start"
                field_size = 0
            elif state == "start" and character == '"':
                state = "quoted"
            else:
                state = "plain"
                field_size += 1
            if field_size > maximum:
                raise BankParseError("FIELD_CAPACITY", "CSV-Feld überschreitet die konfigurierte Textkapazität.")
        yield line


def _tags(stream, maximum_field_chars):
    tag, content, first_line, content_size, line_number = None, [], 0, 0, 0
    while raw := stream.readline(maximum_field_chars + 1):
        line_number += 1
        if len(raw) > maximum_field_chars:
            raise BankParseError("FIELD_CAPACITY", "MT940-Zeile überschreitet die konfigurierte Textkapazität.")
        line = raw.rstrip("\r\n")
        match = re.match(r"^:(\d{2}[A-Z]?|NS):", line)
        if match:
            if tag is not None:
                yield tag, "\n".join(content), first_line
            tag, content, first_line = match.group(1), [line[match.end():]], line_number
            content_size = len(content[0])
        elif line in {"-}", "}"} or not line.strip() and tag is None:
            continue
        elif tag is None:
            if line.startswith("{1:") or line.startswith("{2:") or line in {"{4:", "\x01"}:
                continue
            raise BankParseError("MT940_STRUCTURE", "MT940-Inhalt außerhalb eines Feldes; Dateiformat prüfen.")
        else:
            content.append(line)
            content_size += len(line) + 1
        if content_size > maximum_field_chars:
            raise BankParseError("FIELD_CAPACITY", "MT940-Feld überschreitet die konfigurierte Textkapazität.")
    if tag is not None:
        yield tag, "\n".join(content), first_line


def _balance(raw):
    match = re.fullmatch(r"([CD])(\d{6})([A-Z]{3})(\d+(?:,\d{0,2})?)", raw)
    if not match:
        raise BankParseError("MT940_BALANCE", "MT940-Saldoformat ungültig.")
    try:
        date_value = datetime.strptime(match[2], "%y%m%d").date()
        cents = parse_amount_cents(match[4].rstrip(","), BankMapping(decimal_separator=","))
    except (ValueError, InvalidOperation):
        raise BankParseError("MT940_BALANCE", "MT940-Saldodatum oder Betrag ungültig.") from None
    return (cents if match[1] == "C" else -cents), match[3], date_value


def _mt940_rows(stream, mapping, maximum_field_chars, expected_account):
    ordinal, reference, account, number, statement_ordinal = 0, None, None, None, 0
    opening, delta, currency = None, 0, None
    pending, pending_line, details = None, 0, ""
    seen_opening = False

    def transaction(raw, line, text):
        nonlocal ordinal, delta, statement_ordinal
        ordinal += 1
        statement_ordinal += 1
        try:
            if not reference or not account or not number or opening is None:
                raise BankParseError("MT940_REQUIRED", "Transaktion benötigt vorher :20:, :25:, :28C: und einen Eröffnungssaldo.")
            actual = re.sub(r"\s+", "", account).upper()
            if not expected_account or actual != re.sub(r"\s+", "", expected_account).upper():
                raise BankParseError("ACCOUNT_MISMATCH", "MT940-Konto passt nicht zur gespeicherten IBAN des gewählten Kontos.")
            if currency != mapping.currency:
                raise BankParseError("CURRENCY_MISMATCH", "Dateiwährung passt nicht zur unterstützten Kontowährung.")
            parser = mt940.tags.Statement()
            if not parser.re.fullmatch(raw):
                raise BankParseError("MT940_TRANSACTION", "MT940-Transaktionszeile ist unvollständig oder ungültig.")
            # Direct tag conversion avoids library loggers containing raw bank
            # data, whole-file materialisation and transaction merge heuristics.
            context = mt940.models.Transactions(options=mt940.Options(reversal_sign=True, case_insensitive_marks=True))
            context.data["currency"] = currency
            groups = parser.re.fullmatch(raw).groupdict()
            groups["currency"] = currency
            result = parser(context, groups)
            money = result["amount"].amount
            if abs(money) > Decimal("9999999999.99"):
                raise BankParseError("AMOUNT_CAPACITY", "MT940-Betrag passt nicht in die bestehende Geldspalte.")
            if money != money.quantize(Decimal("0.01")):
                raise BankParseError("AMOUNT_INVALID", "MT940-Betrag hat mehr als zwei Nachkommastellen.")
            cents = int(money * 100)
            if not cents or abs(cents) > 999_999_999_999:
                raise BankParseError("AMOUNT_CAPACITY", "MT940-Betrag passt nicht in die bestehende Geldspalte.")
            delta += cents
            bank_ref = result.get("bank_reference")
            usable = str(bank_ref).strip() if bank_ref and str(bank_ref).strip().upper() != "NONREF" else None
            statement_key = f"mt940:{reference}:{number}"
            # Same bank reference can occur legitimately twice: workflow assigns
            # an occurrence index in SQL, rather than discarding either row.
            identity = f"{statement_key}:bank:{usable}" if usable else f"{statement_key}:line:{statement_ordinal}"
            value_date = result["date"]
            booking_date = result.get("entry_date", value_date)
            return BankRow(ordinal, line, date(booking_date.year, booking_date.month, booking_date.day),
                date(value_date.year, value_date.month, value_date.day), cents,
                text or result.get("extra_details", "") or result.get("customer_reference", ""), usable, identity)
        except BankParseError as error:
            return _error(ordinal, line, error)
        except (ValueError, KeyError, TypeError, InvalidOperation):
            return _error(ordinal, line, BankParseError("MT940_TRANSACTION", "MT940-Datum oder Transaktionsbetrag ungültig."))

    try:
        for tag, raw, line in _tags(stream, maximum_field_chars):
            if pending is not None and tag not in {"86", "NS"}:
                yield transaction(pending, pending_line, details)
                pending, details = None, ""
            if tag == "20":
                if opening is not None:
                    raise BankParseError("MT940_CLOSING_MISSING", "Vorheriger Kontoauszug hat keinen Schlusssaldo.")
                reference, account, number = raw, None, None
                statement_ordinal = 0
            elif tag == "25":
                account = raw
            elif tag in {"28", "28C"}:
                number = raw
                statement_ordinal = 0
            elif tag in {"60F", "60M"}:
                if opening is not None:
                    raise BankParseError("MT940_BALANCE", "Doppelter Eröffnungssaldo ohne Abschluss.")
                opening, currency, _ = _balance(raw)
                delta, seen_opening = 0, True
            elif tag == "61":
                pending, pending_line = raw, line
            elif tag in {"86", "NS"} and pending is not None:
                details += ("\n" if details else "") + raw
            elif tag in {"62F", "62M"}:
                closing, closing_currency, _ = _balance(raw)
                if opening is None or closing_currency != currency or opening + delta != closing:
                    yield _error(ordinal + 1, line, BankParseError("MT940_BALANCE_MISMATCH", "Eröffnungssaldo plus Transaktionen ergibt nicht den Schlusssaldo."))
                    ordinal += 1
                opening = None
            elif tag not in {"13D", "21", "64", "65", "90C", "90D", "86", "NS"}:
                raise BankParseError("MT940_TAG", f"Nicht unterstütztes MT940-Feld :{tag}:; Bankformat prüfen.")
        if pending is not None:
            yield transaction(pending, pending_line, details)
        if opening is not None or not seen_opening:
            raise BankParseError("MT940_CLOSING_MISSING", "Datei benötigt vollständige Eröffnungs- und Schlusssalden.")
    except BankParseError as error:
        yield _error(ordinal + 1, 0, error)


def parse_rows(source: BinaryIO, mapping: BankMapping, *, maximum_field_chars=100_000,
               expected_account: str | None = None) -> Iterator[BankRow]:
    wrapper = io.TextIOWrapper(source, encoding=mapping.encoding, errors="strict", newline="")
    try:
        rows = _csv_rows(wrapper, mapping, maximum_field_chars) if mapping.format == "csv" else _mt940_rows(
            wrapper, mapping, maximum_field_chars, expected_account)
        yield from rows
    except UnicodeError:
        yield BankRow(0, 0, error_code="ENCODING_INVALID", error_message="Datei lässt sich mit der ausgewählten Kodierung nicht lesen.")
    finally:
        wrapper.detach()  # Caller owns and closes the original upload stream.
