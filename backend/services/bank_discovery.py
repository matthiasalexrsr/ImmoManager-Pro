"""Complete private original discovery, independent of the booking projection.

Only existing source chunks are authoritative. A bounded record is materialized,
never the complete file. Syntax/decoding failures retain a complete raw inventory;
resource failures never publish a prefix. No values are written to loggers.
"""

import base64
import codecs
import csv
import hashlib
import json
import os
import re
import time
from contextlib import ExitStack
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any, BinaryIO

import mt940
from pydantic import ValidationError
from sqlalchemy import LargeBinary, case, func, select

from scripts.private_server_backup import private_workspace

from ..config import settings
from ..db.bank_import_models import BankImportSourceORM
from .bank_import import BankImportError, _load, digest, journal
from .bank_import_download import SourceDownload, _chunk_journal
from .bank_import_parser import BankMapping, _csv_capacity_lock

CHUNK_BYTES = 65_536


def failure(code: str, message: str, status: int = 422) -> BankImportError:
    return BankImportError(code, message, status, "adjust_discovery_resources_or_mapping")


@dataclass(frozen=True)
class DiscoveryLimits:
    record_chars: int
    field_chars: int
    temp_bytes: int
    timeout_seconds: float

    @classmethod
    def configured(cls):
        return cls(settings.bank_discovery_record_max_chars, settings.bank_discovery_field_max_chars,
                   settings.bank_discovery_temp_max_bytes, settings.bank_discovery_timeout_seconds)

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in (self.record_chars, self.field_chars, self.temp_bytes)):
            raise ValueError("Discovery byte/character budgets must be positive integers")
        if (type(self.timeout_seconds) not in (int, float) or not 0 < self.timeout_seconds < float("inf")):
            raise ValueError("Discovery time budget must be finite and positive")


class Budget:
    def __init__(self, limits: DiscoveryLimits):
        self.limits, self.started, self.bytes = limits, time.monotonic(), 0

    def check(self):
        if time.monotonic() - self.started >= self.limits.timeout_seconds:
            raise failure("BANK_DISCOVERY_TIMEOUT", "Datei vollständig prüfen: Zeitbudget erhöhen oder Quelle aufteilen.")

    def consume(self, size: int):
        self.check()
        self.bytes += size
        if self.bytes > self.limits.temp_bytes:
            raise failure("BANK_DISCOVERY_TEMP_CAPACITY", "Private Arbeitsdatei überschreitet das konfigurierte Bytebudget. Kapazität erhöhen.")


@dataclass
class DiscoveryDownload:
    path: Path
    manifest: dict[str, Any]
    source: SourceDownload
    mapping_hash: str
    resources: ExitStack

    def close(self):
        self.resources.close()


def check_authority(store, plan: DiscoveryDownload, *, scope=None):
    with _chunk_journal(store, plan.source) as (fresh_store, db):
        job = _load(fresh_store, db, plan.source.import_id, scope)
        if (job.source_sha256 != plan.source.sha256 or job.source_bytes != plan.source.source_bytes
                or job.mapping_hash != plan.mapping_hash or digest(job.mapping) != plan.mapping_hash):
            raise failure("BANK_SOURCE_INTEGRITY", "Gesicherte Bankdatei oder Zuordnung wurde verändert.", 409)


def original_blocks(store, plan: DiscoveryDownload, budget: Budget, *, scope=None):
    """Check BLOB length in SQL before the driver can allocate corrupted bytes."""
    source, total, ordinal, sha = plan.source, 0, 0, hashlib.sha256()
    table = BankImportSourceORM
    while total < source.source_bytes:
        budget.check()
        with _chunk_journal(store, source) as (fresh_store, db):
            job = _load(fresh_store, db, source.import_id, scope)
            if (job.source_sha256 != source.sha256 or job.source_bytes != source.source_bytes
                    or job.mapping_hash != plan.mapping_hash or digest(job.mapping) != plan.mapping_hash):
                raise failure("BANK_SOURCE_INTEGRITY", "Gesicherte Quelle oder Zuordnung wurde verändert.", 409)
            data = db.scalar(select(case((func.length(table.data).between(1, CHUNK_BYTES), table.data),
                                        else_=None).cast(LargeBinary)).where(
                table.import_id == source.import_id, table.chunk_no == ordinal))
            if data is None or len(data) != min(CHUNK_BYTES, source.source_bytes - total):
                raise failure("BANK_SOURCE_INTEGRITY", "Gesicherte Quelldatei ist unvollständig.", 409)
        block = bytes(data)
        sha.update(block)
        total += len(block)
        ordinal += 1
        yield block
    with _chunk_journal(store, source) as (fresh_store, db):
        _load(fresh_store, db, source.import_id, scope)
        extra = db.scalar(select(table.chunk_no).where(table.import_id == source.import_id,
                                                       table.chunk_no >= ordinal).limit(1))
        negative = db.scalar(select(table.chunk_no).where(table.import_id == source.import_id,
                                                          table.chunk_no < 0).limit(1))
    if extra is not None or negative is not None or sha.hexdigest() != source.sha256:
        raise failure("BANK_SOURCE_INTEGRITY", "Quelldatei enthält zusätzliche Stücke oder eine falsche Prüfsumme.", 409)


class ParseFailure(ValueError):
    def __init__(self, code: str, byte_offset: int, char_offset: int, line: int):
        self.code, self.byte_offset, self.char_offset, self.line = code, byte_offset, char_offset, line


@dataclass(frozen=True)
class SourceLine:
    raw: str
    byte_start: int
    char_start: int
    line: int


def encoding_layout(source: BinaryIO, encoding: str):
    source.seek(0)
    prefix = source.read(3)
    source.seek(0)
    if encoding == "utf-8-sig":
        return "utf-8", 3 if prefix.startswith(codecs.BOM_UTF8) else 0
    if encoding == "utf-16":
        if prefix.startswith(codecs.BOM_UTF16_LE):
            return "utf-16-le", 2
        if prefix.startswith(codecs.BOM_UTF16_BE):
            return "utf-16-be", 2
        raise ParseFailure("ENCODING_BOM_MISSING", 0, 0, 1)
    return encoding, 0


def decoded_lines(source: BinaryIO, codec: str, bom_bytes: int, budget: Budget):
    source.seek(bom_bytes)
    decoder = codecs.getincrementaldecoder(codec)(errors="strict")
    buffer, byte_start, char_start, line_number, read_offset = "", bom_bytes, 0, 1, bom_bytes
    while True:
        budget.check()
        block = source.read(CHUNK_BYTES)
        pending = len(decoder.getstate()[0])
        try:
            buffer += decoder.decode(block, final=not block)
        except UnicodeDecodeError as error:
            valid_prefix = error.object[:getattr(error, "start", 0)].decode(codec)
            before_error = buffer + valid_prefix
            raise ParseFailure("ENCODING_INVALID", read_offset - pending + getattr(error, "start", 0),
                               char_start + len(before_error),
                               line_number + len(re.findall(r"\r\n|\r|\n", before_error))) from None
        read_offset += len(block)
        while True:
            match = re.search(r"\r\n|\r|\n", buffer)
            if match is None or (block and match.group() == "\r" and match.end() == len(buffer)):
                break
            raw, buffer = buffer[:match.end()], buffer[match.end():]
            if len(raw) > budget.limits.record_chars:
                raise failure("BANK_DISCOVERY_RECORD_CAPACITY", "Quellzeile überschreitet das Zeichenbudget. Kapazität erhöhen.")
            yield SourceLine(raw, byte_start, char_start, line_number)
            byte_start += len(raw.encode(codec))
            char_start += len(raw)
            line_number += 1
        if len(buffer) > budget.limits.record_chars:
            raise failure("BANK_DISCOVERY_RECORD_CAPACITY", "Quellzeile überschreitet das Zeichenbudget. Kapazität erhöhen.")
        if not block:
            if buffer:
                yield SourceLine(buffer, byte_start, char_start, line_number)
            break


def position(start: SourceLine, raw: str, codec: str):
    return {"byte_start": start.byte_start, "byte_end": start.byte_start + len(raw.encode(codec)),
            "char_start": start.char_start, "char_end": start.char_start + len(raw),
            "line_start": start.line, "line_end": start.line + len(re.findall(r"\r\n|\r|\n", raw))}


def cell_spans(raw: str, delimiter: str):
    """Raw token boundaries; csv.reader remains the strict syntax authority."""
    quoted, start, cursor = False, 0, 0
    while cursor < len(raw):
        char = raw[cursor]
        if char == '"' and (quoted or cursor == start):
            if quoted and cursor + 1 < len(raw) and raw[cursor + 1] == '"':
                cursor += 2
                continue
            quoted = not quoted
        elif not quoted and (char == delimiter or char in "\r\n"):
            yield start, cursor
            if char != delimiter:
                return
            start = cursor + 1
        cursor += 1
    yield start, cursor


def csv_records(lines, codec: str, delimiter: str, budget: Budget, counts: dict[str, int]):
    pending: list[SourceLine] = []
    characters = 0

    def input_lines():
        nonlocal characters
        for line in lines:
            characters += len(line.raw)
            if characters > budget.limits.record_chars:
                raise failure("BANK_DISCOVERY_RECORD_CAPACITY", "CSV-Datensatz überschreitet das Zeichenbudget. Kapazität erhöhen.")
            pending.append(line)
            yield line.raw

    # Python's global CSV ceiling is raised only. Per-record/per-field checks
    # below remain independent when concurrent readers have different budgets.
    with _csv_capacity_lock:
        if csv.field_size_limit() < budget.limits.record_chars:
            csv.field_size_limit(budget.limits.record_chars)
    reader = csv.reader(input_lines(), delimiter=delimiter, strict=True)
    header: list[str] | None = None
    while True:
        budget.check()
        try:
            values = next(reader)
        except StopIteration:
            if header is None:
                raise ParseFailure("CSV_HEADER_MISSING", 0, 0, 1) from None
            return
        except csv.Error:
            first = pending[0] if pending else SourceLine("", 0, 0, 1)
            raise ParseFailure("CSV_SYNTAX", first.byte_start, first.char_start, first.line) from None
        raw, start = "".join(line.raw for line in pending), pending[0]
        cells, byte_cursor, char_cursor, line_cursor = [], start.byte_start, start.char_start, start.line
        spans = list(cell_spans(raw, delimiter)) if values else []
        if len(spans) != len(values):
            raise ParseFailure("CSV_SYNTAX", start.byte_start, start.char_start, start.line)
        for index, (value, (left, right)) in enumerate(zip(values, spans, strict=True)):
            if len(value) > budget.limits.field_chars:
                raise failure("BANK_DISCOVERY_FIELD_CAPACITY", "CSV-Feld überschreitet das Zeichenbudget. Kapazität erhöhen.")
            lexeme = raw[left:right]
            cell_start = SourceLine(lexeme, byte_cursor, char_cursor, line_cursor)
            cells.append({"column_index": index, "header": header[index] if header is not None and index < len(header) else None,
                          "value": value, "raw_value": lexeme, "position": position(cell_start, lexeme, codec)})
            consumed = raw[left:right + 1] if right < len(raw) and raw[right] == delimiter else lexeme
            byte_cursor += len(consumed.encode(codec))
            char_cursor += len(consumed)
            line_cursor += len(re.findall(r"\r\n|\r|\n", consumed))
        counts["physical_lines"] += len(pending)
        counts["csv_records"] += 1
        counts["csv_cells"] += len(cells)
        yield {"kind": "csv_header" if header is None else "csv_record", "ordinal": counts["csv_records"],
               "raw": raw, "position": position(start, raw, codec), "cells": cells}
        if header is None:
            header = values
        pending.clear()
        characters = 0


def raw_tag_fields(tag: str, raw_value: str, start: SourceLine, prefix: str, codec: str):
    key = int(tag) if tag.isdecimal() else tag
    parser = mt940.tags.TAG_BY_ID.get(key)
    match = parser.re.fullmatch(raw_value.rstrip("\r\n")) if parser is not None else None
    if match is None:
        return [], "unknown_tag" if parser is None else "raw_pattern_unmatched"
    fields = []
    for name, value in match.groupdict().items():
        if value is None:
            continue
        left, _ = match.span(name)
        before = prefix + raw_value[:left]
        field_start = SourceLine(value, start.byte_start + len(before.encode(codec)),
                                 start.char_start + len(before), start.line + len(re.findall(r"\r\n|\r|\n", before)))
        fields.append({"name": name, "value": value, "position": position(field_start, value, codec)})
    return fields, "matched_raw_fields"


def mt940_records(lines, codec: str, budget: Budget, counts: dict[str, int]):
    pending: list[SourceLine] = []
    tag, prefix, characters = None, "", 0

    def completed():
        raw, first = "".join(line.raw for line in pending), pending[0]
        if tag is None:
            return {"kind": "mt940_unassigned", "raw": raw, "position": position(first, raw, codec)}
        value = raw[len(prefix):]
        if len(value) > budget.limits.field_chars:
            raise failure("BANK_DISCOVERY_FIELD_CAPACITY", "MT940-Feld überschreitet das Zeichenbudget. Kapazität erhöhen.")
        counts["mt940_tags"] += 1
        fields, observation = raw_tag_fields(tag, value, first, prefix, codec)
        counts["mt940_raw_fields"] += len(fields)
        return {"kind": "mt940_tag", "ordinal": counts["mt940_tags"], "tag": tag, "raw": raw,
                "value": value, "position": position(first, raw, codec), "raw_fields": fields,
                "observation": observation}

    for line in lines:
        budget.check()
        counts["physical_lines"] += 1
        match = re.match(r"^:([^:\r\n]+):", line.raw)
        # Preserve SWIFT envelopes/trailers and blanks independently; none are
        # dropped or accidentally consumed as the previous field's value.
        boundary = match is not None or line.raw.rstrip("\r\n") in {"-}", "}", "{4:"}
        if pending and boundary:
            yield completed()
            pending, characters = [], 0
        if not pending:
            tag, prefix = (match.group(1), match.group()) if match else (None, "")
        characters += len(line.raw)
        if characters > budget.limits.record_chars:
            raise failure("BANK_DISCOVERY_RECORD_CAPACITY", "MT940-Quelldatensatz überschreitet das Zeichenbudget. Kapazität erhöhen.")
        pending.append(line)
    if pending:
        yield completed()


def prepare_discovery(store, import_id: str, *, scope=None, limits: DiscoveryLimits | None = None):
    budget, resources = Budget(limits or DiscoveryLimits.configured()), ExitStack()
    try:
        with journal(store) as db:
            job = _load(store, db, import_id, scope)
            if (type(job.source_bytes) is not int or job.source_bytes < 0 or digest(job.mapping) != job.mapping_hash
                    or job.mapping.get("format") not in {"csv", "mt940"}):
                raise failure("BANK_SOURCE_INTEGRITY", "Gesicherte Quellmetadaten sind ungültig.", 409)
            mapping = dict(job.mapping)
            try:
                BankMapping.model_validate({key: value for key, value in mapping.items() if key != "account_binding_hash"})
            except ValidationError:
                raise failure("BANK_SOURCE_INTEGRITY", "Gesicherte Spaltenzuordnung ist ungültig.", 409) from None
            metadata = {"kind": "manifest", "format_version": 1, "import_id": job.id,
                        "source_sha256": job.source_sha256, "source_bytes": job.source_bytes,
                        "mapping_hash": job.mapping_hash, "mapping": mapping, "business_state": job.state,
                        "parser": {"name": "bank-original-discovery", "version": 1,
                                   "mt940_library_version": version("mt-940"), "raw_fields": "regex_captures_no_conversion"},
                        "position_convention": {"bytes": "zero_based_original_including_bom_end_exclusive",
                                                "chars": "zero_based_decoded_excluding_bom_end_exclusive", "lines": "one_based"},
                        "policy": "private_original_discovery_no_booking_conversion"}
            source_plan = SourceDownload(job.id, job.filename, job.source_bytes, job.source_sha256,
                                         db.get_bind() if hasattr(store, "db") else None)
        workspace, _ = resources.enter_context(private_workspace())
        source_path, path = workspace / "source.bin", workspace / "discovery.jsonl"
        plan = DiscoveryDownload(path, {}, source_plan, metadata["mapping_hash"], resources)
        with os.fdopen(os.open(source_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
            for block in original_blocks(store, plan, budget, scope=scope):
                budget.consume(len(block))
                out.write(block)
        output_sha, records_sha, output_size = hashlib.sha256(), hashlib.sha256(), 0
        counts = {"physical_lines": 0, "csv_records": 0, "csv_cells": 0, "mt940_tags": 0, "mt940_raw_fields": 0}
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out, source_path.open("rb") as source:
            def write(record, *, evidence=True):
                nonlocal output_size
                encoded = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n"
                budget.consume(len(encoded))
                out.write(encoded)
                output_sha.update(encoded)
                output_size += len(encoded)
                if evidence:
                    records_sha.update(encoded)

            write(metadata)
            parsed = True
            try:
                codec, bom = encoding_layout(source, mapping["encoding"])
                write({"kind": "encoding", "codec": codec, "bom_bytes": bom})
                lines = decoded_lines(source, codec, bom, budget)
                records = csv_records(lines, codec, mapping["delimiter"], budget, counts) if mapping["format"] == "csv" else mt940_records(lines, codec, budget, counts)
                for record in records:
                    write(record)
            except ParseFailure as error:
                parsed = False
                write({"kind": "parser_error", "code": error.code,
                       "position": {"byte_offset": error.byte_offset, "char_offset": error.char_offset, "line": error.line},
                       "position_precision": "failed_record_start" if error.code.startswith("CSV_") else "exact_byte",
                       "recovery": "original_bytes_retained_choose_encoding_or_repair_source"})
                source.seek(0)
                offset = 0
                while block := source.read(CHUNK_BYTES):
                    write({"kind": "raw_source_chunk", "byte_start": offset, "byte_end": offset + len(block),
                           "base64": base64.b64encode(block).decode("ascii")})
                    offset += len(block)
            write({"kind": "eof", "import_id": import_id, "source_sha256": source_plan.sha256,
                   "source_bytes": source_plan.source_bytes, "mapping_hash": plan.mapping_hash,
                   "original_complete": True, "parser_complete": parsed, "counts": counts,
                   "records_sha256": records_sha.hexdigest()}, evidence=False)
        plan.manifest = {"size": output_size, "sha256": output_sha.hexdigest()}
        check_authority(store, plan, scope=scope)
        budget.check()
        return plan
    except BaseException:
        resources.close()
        raise
