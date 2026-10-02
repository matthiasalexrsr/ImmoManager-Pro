"""EXTF 700/21/v13; EUR, reviewed nonautomatic accounts, no VAT. Published field constraints."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from decimal import Context, Decimal, DecimalException, localcontext
from pathlib import Path
from types import MappingProxyType

APP = "IMMOEXTF3"
DATEV_BATCH_ROWS = 99_999  # Official per-file limit; complete exports split into files.
_columns = (
    "Umsatz (ohne Soll/Haben-Kz);Soll/Haben-Kennzeichen;WKZ Umsatz;Kurs;"
    "Basis-Umsatz;WKZ Basis-Umsatz;Konto;Gegenkonto (ohne BU-Schlüssel);"
    "BU-Schlüssel;Belegdatum;Belegfeld 1;Belegfeld 2;Skonto;Buchungstext;"
    "Postensperre;Diverse Adressnummer;Geschäftspartnerbank;Sachverhalt;Zinssperre;Beleglink"
).split(";")
for i in range(1, 9):
    _columns += [f"Beleginfo - Art {i}", f"Beleginfo - Inhalt {i}"]
_columns += (
    "KOST1 - Kostenstelle;KOST2 - Kostenstelle;Kost-Menge;"
    "EU-Land u. UStID (Bestimmung);EU-Steuersatz (Bestimmung);Abw. Versteuerungsart;"
    "Sachverhalt L+L;Funktionsergänzung L+L;BU 49 Hauptfunktionstyp;"
    "BU 49 Hauptfunktionsnummer;BU 49 Funktionsergänzung"
).split(";")
for i in range(1, 21):
    _columns += [f"Zusatzinformation - Art {i}", f"Zusatzinformation- Inhalt {i}"]
_columns += (
    "Stück;Gewicht;Zahlweise;Forderungsart;Veranlagungsjahr;Zugeordnete Fälligkeit;"
    "Skontotyp;Auftragsnummer;Buchungstyp;USt-Schlüssel (Anzahlungen);EU-Land (Anzahlungen);"
    "Sachverhalt L+L (Anzahlungen);EU-Steuersatz (Anzahlungen);Erlöskonto (Anzahlungen);"
    "Herkunft-Kz;Buchungs GUID;KOST-Datum;SEPA-Mandatsreferenz;Skontosperre;"
    "Gesellschaftername;Beteiligtennummer;Identifikationsnummer;Zeichnernummer;"
    "Postensperre bis;Bezeichnung SoBil-Sachverhalt;Kennzeichen SoBil-Buchung;"
    "Festschreibung;Leistungsdatum;Datum Zuord. Steuerperiode;Fälligkeit;"
    "Generalumkehr (GU);Steuersatz;Land;Abrechnungsreferenz;BVV-Position;"
    "EU-Land u. UStID (Ursprung);EU-Steuersatz (Ursprung);Abw. Skontokonto"
).split(";")
COLUMNS = tuple(_columns)
TEXT = frozenset(
    {2, 3, 6, 9, 11, 12, 14, 16, 20, 37, 38, 40, 42, 91, 95, 96, 98,
     102, 103, 105, 107, 109, 110, 112, 118, 120, 121, 123}
    | set(range(21, 37)) | set(range(48, 88))
)
HEADER_TEXT = {1, 4, 8, 9, 10, 17, 18, 22, 24, 27, 30, 31}

class ExportError(ValueError):
    """Fixed code; row=0 for profile, otherwise 1-based data-row number."""
    def __init__(self, code: str, row: int = 0):
        self.code, self.row = code, row
        super().__init__(f"{code} [row={row}]")

def need(condition, code):
    if not condition:
        raise ExportError(code)

def identifier(value):
    need(isinstance(value, str) and bool(value), "missing_identifier")
    return value

def text(value, length, pattern=None):
    need(isinstance(value, str) and len(value) <= length, "text_length_or_type")
    need(not any(ord(c) < 32 or 127 <= ord(c) < 160 for c in value), "control_character")
    need(not value.lstrip().startswith(("=", "+", "-", "@")), "formula_prefix")
    if pattern:
        need(re.fullmatch(pattern, value) is not None, "text_format")
    try:
        value.encode("cp1252")
    except UnicodeError:
        raise ExportError("not_cp1252") from None
    return value

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("ascii")

def amount(value):
    need(type(value) in (str, int, float, Decimal), "amount_type")
    try:
        d = Decimal(str(value))
        need(d.is_finite() and 0 < d.copy_abs() <= Decimal("9999999999.99"), "amount_range")
        with localcontext(Context(prec=32)):
            q = d.quantize(Decimal("0.01"))
        need(q == d, "subcent_amount")
        return q
    except DecimalException:
        raise ExportError("invalid_amount") from None

@dataclass(frozen=True)
class Rule:
    bank_gl: str
    counter_gl: str
    currency: str
    no_vat_nonautomatic: bool
    account_type: str
    counter_kind: str = "general"

@dataclass(frozen=True)
class Profile:
    adviser: int
    client: int
    fiscal_start: date
    gl_length: int
    portfolio_id: str
    chart: str
    freeze: int
    mapping_revision: str
    approved_by: str
    rules: Mapping[tuple[str, str, str], Rule]

@dataclass(frozen=True)
class Batch:
    start: date
    end: date
    generated_at: datetime  # Explicit accounting-local time with UTC offset.
    batch_id: str
    label: str

@dataclass(frozen=True)
class Entry:
    """One joined row; document_ref must be explicitly supplied."""
    id: str
    account_id: str
    category_id: str
    account_portfolio_id: str
    category_portfolio_id: str
    account_type: str
    booking_date: date
    amount: Decimal | str | int | float
    status: str
    updated_at: datetime
    document_ref: str
    payment_text: str | None = None

def _plan(profile, batch):
    need(isinstance(profile, Profile) and isinstance(batch, Batch), "profile_type")
    need(isinstance(profile.rules, Mapping), "rule_matrix")
    p = replace(profile, rules=MappingProxyType(dict(profile.rules)))
    for value, lo, hi in ((p.adviser, 1001, 9999999), (p.client, 1, 99999),
                         (p.gl_length, 4, 8), (p.freeze, 0, 1)):
        need(type(value) is int and lo <= value <= hi, "header_number")
    identifier(p.portfolio_id)
    identifier(p.approved_by)
    identifier(text(p.mapping_revision, 210))
    text(p.chart, 4, r"(?:[0-9]{2}|[0-9]{4})?")
    identifier(text(batch.batch_id, 210))
    identifier(text(batch.label, 30, r"[\w ./-]+"))
    for day in (p.fiscal_start, batch.start, batch.end):
        need(type(day) is date and 2000 <= day.year <= 2099, "header_date")
    need(p.fiscal_start == date(batch.start.year, 1, 1)
         and batch.start <= batch.end and batch.end.year == batch.start.year, "fiscal_period")
    need(isinstance(batch.generated_at, datetime) and batch.generated_at.utcoffset() is not None
         and 2000 <= batch.generated_at.year <= 2099, "generated_at")
    digest = hashlib.sha256()
    digest.update(canonical({k: (v.isoformat() if isinstance(v, date) else v)
                            for k, v in vars(p).items() if k != "rules"}))
    # Include unused rules in validation and fingerprint.
    for key, rule in p.rules.items():
        need(type(key) is tuple and len(key) == 3, "rule_key")
        for part in key:
            identifier(part)
        need(key[2] in {"income", "expense"} and isinstance(rule, Rule), "rule_type")
        need(rule.counter_kind in {"general", "person"}, "counter_kind")
        identifier(rule.account_type)
        for gl, maximum in ((rule.bank_gl, p.gl_length),
                            (rule.counter_gl, p.gl_length + (rule.counter_kind == "person"))):
            need(isinstance(gl, str) and re.fullmatch(rf"[0-9]{{1,{maximum}}}", gl)
                 and int(gl) != 0, "gl_mapping")
        need(int(rule.bank_gl) != int(rule.counter_gl), "identical_accounts")
        need(rule.currency == "EUR" and rule.no_vat_nonautomatic is True, "tax_currency_scope")
    for key in sorted(p.rules):
        digest.update(b"\n" + canonical([*key, asdict(p.rules[key])]))
    return p, digest.hexdigest()

def _line(values, quoted):
    parts = []
    for pos, value in enumerate(values, 1):
        item = "" if value is None else str(value)
        parts.append('"' + item.replace('"', '""') + '"' if pos in quoted else item)
    return (";".join(parts) + "\r\n").encode("cp1252")

def _lines(entries, p, batch):
    stamp = batch.generated_at.strftime("%Y%m%d%H%M%S") + f"{batch.generated_at.microsecond // 1000:03}"
    yield _line(["EXTF", 700, 21, "Buchungsstapel", 13, stamp, None, "IM", "ImmoManager", "",
                 p.adviser, p.client, p.fiscal_start.strftime("%Y%m%d"), p.gl_length,
                 batch.start.strftime("%Y%m%d"), batch.end.strftime("%Y%m%d"), batch.label,
                 "", 1, 0, p.freeze, "EUR", None, "", None, None, p.chart, None, None, "", APP], HEADER_TEXT)
    yield (";".join(COLUMNS) + "\r\n").encode("cp1252")
    previous = None
    for number, entry in enumerate(entries, 1):
        try:
            need(isinstance(entry, Entry), "entry_type")
            need(entry.status == "confirmed", "not_confirmed")
            identifier(text(entry.id, 210))
            need(type(entry.booking_date) is date
                 and batch.start <= entry.booking_date <= batch.end, "booking_date")
            key = (entry.booking_date, entry.id)
            need(previous is None or previous < key, "unordered_or_duplicate_key")
            previous = key
            need(isinstance(entry.category_id, str) and bool(entry.category_id), "missing_category")
            need(entry.account_portfolio_id == entry.category_portfolio_id == p.portfolio_id,
                 "portfolio_mismatch")
            identifier(entry.account_id)
            identifier(entry.category_id)
            money = amount(entry.amount)
            flow = "income" if money > 0 else "expense"
            need(number <= DATEV_BATCH_ROWS, "batch_row_limit")
            rule = p.rules.get((entry.account_id, entry.category_id, flow))
            need(rule is not None, "missing_rule")
            need(entry.account_type == rule.account_type, "account_type_changed")
            ref = text(entry.document_ref, 36, r"[A-Za-z0-9_$&%*+/-]*")
            memo = text("" if entry.payment_text is None else entry.payment_text, 60)
            need(isinstance(entry.updated_at, datetime), "source_revision")
            source = asdict(entry)
            source.update(amount=format(money, "f"), booking_date=entry.booking_date.isoformat(),
                          updated_at=entry.updated_at.isoformat())
            revision = hashlib.sha256(canonical(source)).hexdigest()
            row: list[object] = [None] * 125
            row[:14] = [format(money.copy_abs(), "f").replace(".", ","),
                        "S" if money > 0 else "H", "EUR", None, None, None,
                        rule.bank_gl, rule.counter_gl, None, entry.booking_date.strftime("%d%m"),
                        ref, None, None, memo]
            row[47:55] = ["Immo-ID", entry.id, "Quellrevision", revision,
                          "Mapping-Revision", p.mapping_revision, "Stapel-ID", batch.batch_id]
            row[113] = p.freeze
            yield _line(row, TEXT)
        except ExportError as exc:
            raise ExportError(exc.code, number) from None

def iter_extf_lines(entries: Iterable[Entry], profile: Profile, batch: Batch) -> Iterator[bytes]:
    """Internal only: use prepare_download before any HTTP response.

    Entries: one authorized snapshot, ASC (booking_date, id), unique booking IDs.
    The producer guarantees ID uniqueness; repeated sort keys are also rejected.
    """
    p, _ = _plan(profile, batch)
    yield from _lines(entries, p, batch)

@dataclass(frozen=True)
class PreparedDownload:
    path: Path
    rows: int
    size: int
    sha256: str
    profile_sha256: str
    token: str
    _directory: tempfile.TemporaryDirectory

    def close(self):
        try:
            self._directory.cleanup()
        except OSError:
            raise ExportError("cleanup_failed") from None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

def prepare_download(entries: Iterable[Entry], profile: Profile, batch: Batch,
                     *, spool_dir: Path, expected_token: str | None = None) -> PreparedDownload:
    """Return a final path only after EOF, validation, fsync and close.

    Use private disk-backed spool_dir, never an HTTP static directory.
    Caller owns the source transaction and closes the download after transfer.
    """
    p, profile_hash = _plan(profile, batch)
    try:
        directory = tempfile.TemporaryDirectory(prefix="immo-extf-", dir=spool_dir)
    except OSError:
        raise ExportError("spool_unavailable") from None
    root = Path(directory.name)
    partial, final = root / "export.partial", root / "EXTF_Buchungsstapel.csv"
    digest, size, lines = hashlib.sha256(), 0, 0
    try:
        with partial.open("xb") as output:
            for block in _lines(entries, p, batch):
                if output.write(block) != len(block):
                    raise OSError("short_write")
                digest.update(block)
                size += len(block)
                lines += 1
            output.flush()
            os.fsync(output.fileno())
        checksum = digest.hexdigest()
        token = hashlib.sha256(canonical([APP, checksum, profile_hash,
                    batch.generated_at.isoformat(), batch.batch_id])).hexdigest()
        if expected_token is not None:
            need(isinstance(expected_token, str) and re.fullmatch(r"[0-9a-f]{64}", expected_token)
                 and hmac.compare_digest(token, expected_token), "preview_changed")
        os.replace(partial, final)  # Inside a new private directory.
        return PreparedDownload(final, lines - 2, size, checksum, profile_hash, token, directory)
    except BaseException as exc:
        try:
            directory.cleanup()
        except OSError:
            raise ExportError("cleanup_failed") from None
        if isinstance(exc, ExportError):
            raise
        if isinstance(exc, OSError):
            raise ExportError("build_failed") from None
        # The producer owns authorization and its snapshot. Preserve its
        # failures (including a revoked grant) after cleaning the spool.
        raise
