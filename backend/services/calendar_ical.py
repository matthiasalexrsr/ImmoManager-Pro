"""Bounded RFC 5545 export for existing CalendarEvent records."""

from __future__ import annotations

import hashlib
import heapq
import json
import re
from contextlib import ExitStack, contextmanager
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.engine import Connection, Engine

from ..db.orm_models import CalendarEventORM, PortfolioORM
from ..models import CalendarEvent, Portfolio
from ..storage import NotFoundError
from .booking_export import _snapshot
from .datev_export import CompiledExport
from .payments import _memory_lock
from .portfolio_scope import (
    AccessScope,
    current_scope,
    memory_visible,
    refresh_scope,
    scope_context,
    scoped_clause,
)

PRODID = "-//ImmoManager-Pro//Calendar Export//DE"
_TIME_RE = re.compile(r"^(\d{2}):(\d{2})(?::(\d{2}))?$")
ICAL_BATCH_SIZE = 1000  # Memory buffer, never an export-size limit.


class CalendarExportError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _escape_text(value: str, *, field: str) -> str:
    value = str(value)
    for char in value:
        code = ord(char)
        if (code < 32 and char not in {"\t", "\r", "\n"}) or code == 127:
            raise CalendarExportError(
                "invalid_text",
                f"Kalenderfeld '{field}' enthält nicht unterstützte Steuerzeichen.",
            )
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _fold_line(value: str) -> Iterator[bytes]:
    """Fold a content line to at most 75 UTF-8 octets per physical line."""
    current = bytearray()
    for char in value:
        encoded = char.encode("utf-8")
        if current and len(current) + len(encoded) > 75:
            yield bytes(current)
            current = bytearray(b" ")
        current.extend(encoded)
    yield bytes(current)


def _content_line(name: str, value: str) -> Iterator[bytes]:
    yield from _fold_line(f"{name}:{value}")


def _utc_stamp(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.strftime("%Y%m%dT%H%M%SZ")


def _stable_uid(event_id: str) -> str:
    try:
        identifier = UUID(event_id)
    except (ValueError, AttributeError):
        identifier = uuid5(NAMESPACE_URL, f"https://immomanager.local/calendar/{event_id}")
    return f"urn:uuid:{identifier}"


def _parse_time(value: str, event_id: str) -> time:
    match = _TIME_RE.fullmatch(value.strip())
    if not match:
        raise CalendarExportError(
            "invalid_event_time",
            f"Kalendereintrag {event_id}: Uhrzeit muss HH:MM oder HH:MM:SS sein.",
        )
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)
    try:
        return time(hour, minute, second)
    except ValueError as exc:
        raise CalendarExportError(
            "invalid_event_time",
            f"Kalendereintrag {event_id}: Uhrzeit ist ungültig.",
        ) from exc


def _local_to_utc(day: date, clock: time, zone: ZoneInfo, event_id: str) -> datetime:
    local = datetime.combine(day, clock)
    candidates: set[datetime] = set()
    for fold in (0, 1):
        candidate = local.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if candidate.astimezone(zone).replace(tzinfo=None) == local:
            candidates.add(candidate)
    if not candidates:
        raise CalendarExportError(
            "nonexistent_local_time",
            f"Kalendereintrag {event_id}: Uhrzeit existiert in der Portfolio-Zeitzone nicht.",
        )
    if len(candidates) > 1:
        raise CalendarExportError(
            "ambiguous_local_time",
            f"Kalendereintrag {event_id}: Uhrzeit ist wegen Zeitumstellung mehrdeutig.",
        )
    return candidates.pop()


def _event_lines(event: CalendarEvent, zone: ZoneInfo) -> Iterator[bytes]:
    yield b"BEGIN:VEVENT"
    yield from _content_line("UID", _stable_uid(event.id))
    yield from _content_line("DTSTAMP", _utc_stamp(event.updated_at))
    yield from _content_line("CREATED", _utc_stamp(event.created_at))
    yield from _content_line("LAST-MODIFIED", _utc_stamp(event.updated_at))

    raw_time = (event.event_time or "").strip()
    if raw_time:
        start = _local_to_utc(event.event_date, _parse_time(raw_time, event.id), zone, event.id)
        yield from _content_line("DTSTART", start.strftime("%Y%m%dT%H%M%SZ"))
    else:
        yield from _content_line("DTSTART;VALUE=DATE", event.event_date.strftime("%Y%m%d"))

    yield from _content_line("SUMMARY", _escape_text(event.title, field="title"))
    yield from _content_line("CATEGORIES", _escape_text(event.event_type, field="event_type"))
    if event.location:
        yield from _content_line("LOCATION", _escape_text(event.location, field="location"))
    if event.description:
        yield from _content_line("DESCRIPTION", _escape_text(event.description, field="description"))
    if event.participants:
        yield from _content_line(
            "X-IMMOMANAGER-PARTICIPANTS",
            _escape_text(event.participants, field="participants"),
        )
    yield b"END:VEVENT"


def _zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CalendarExportError(
            "invalid_timezone",
            f"Portfolio-Zeitzone '{timezone_name}' ist nicht verfügbar.",
        ) from exc


def _event_key(event: CalendarEvent) -> tuple[date, str, str]:
    return event.event_date, event.event_time or "", event.id


def _narrow_scope(scope: AccessScope, portfolio_id: str) -> AccessScope:
    if not scope.unrestricted and portfolio_id not in scope.portfolio_ids:
        raise NotFoundError("Portfolio nicht gefunden")
    return AccessScope(scope.user_id, scope.role, False, (portfolio_id,))


def _memory_events(store, scope: AccessScope, captured: AccessScope) -> Iterator[CalendarEvent]:
    raw = object.__getattribute__(store, "__dict__")["calendar_events"]
    after: tuple[date, str, str] | None = None
    while True:
        page = heapq.nsmallest(
            ICAL_BATCH_SIZE,
            (
                item
                for item in raw.values()
                if memory_visible(store, "calendar_events", item, scope=scope)
                and (after is None or _event_key(item) > after)
            ),
            key=_event_key,
        )
        if not page:
            return
        refresh_scope(captured)
        yield from page
        after = _event_key(page[-1])


def _sql_events(
    connection: Connection,
    scope: AccessScope,
    captured: AccessScope,
) -> Iterator[CalendarEvent]:
    table = CalendarEventORM.__table__
    time_key = func.coalesce(table.c.event_time, "")
    predicate = scoped_clause(table, scope=scope)
    base = select(*table.c)
    if predicate is not None:
        base = base.where(predicate)
    after: tuple[date, str, str] | None = None
    while True:
        query = base
        if after is not None:
            after_date, after_time, after_id = after
            query = query.where(
                or_(
                    table.c.event_date > after_date,
                    and_(table.c.event_date == after_date, time_key > after_time),
                    and_(
                        table.c.event_date == after_date,
                        time_key == after_time,
                        table.c.id > after_id,
                    ),
                )
            )
        rows = connection.execute(
            query.order_by(table.c.event_date, time_key, table.c.id).limit(ICAL_BATCH_SIZE)
        ).mappings().all()
        if not rows:
            return
        refresh_scope(captured)
        for row in rows:
            yield CalendarEvent.model_validate(dict(row))
        last = rows[-1]
        after = last["event_date"], last["event_time"] or "", last["id"]


def _sql_portfolio(connection: Connection, portfolio_id: str, scope: AccessScope) -> Portfolio:
    table = PortfolioORM.__table__
    query = select(*table.c).where(table.c.id == portfolio_id)
    predicate = scoped_clause(table, scope=scope)
    if predicate is not None:
        query = query.where(predicate)
    row = connection.execute(query).mappings().first()
    if row is None:
        raise NotFoundError("Portfolio nicht gefunden")
    return Portfolio.model_validate(dict(row))


@contextmanager
def _calendar_snapshot(store, portfolio_id: str, captured: AccessScope):
    narrowed = _narrow_scope(captured, portfolio_id)
    refresh_scope(captured)
    if getattr(store, "db", None) is None:
        with _memory_lock, scope_context(narrowed):
            portfolio = store.get_portfolio(portfolio_id)
            yield portfolio, _memory_events(store, narrowed, captured)
            refresh_scope(captured)
        return

    db = getattr(store, "db", None)
    if db is None or db.new or db.dirty or db.deleted:
        raise CalendarExportError(
            "export_session_dirty",
            "Kalenderexport benötigt eine saubere Datenbanksitzung.",
        )
    engine = db.get_bind()
    if not isinstance(engine, Engine):
        raise CalendarExportError("unsupported_backend", "Kalenderexport-Backend wird nicht unterstützt.")
    db.rollback()
    with scope_context(narrowed), _snapshot(engine) as connection:
        portfolio = _sql_portfolio(connection, portfolio_id, narrowed)
        yield portfolio, _sql_events(connection, narrowed, captured)
        refresh_scope(captured)


def _write_index_record(
    output: BinaryIO,
    start: int,
    end: int,
    event_id: str,
) -> None:
    output.write(
        json.dumps(
            [start, end, event_id],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _write_calendar(
    output: BinaryIO,
    identifiers: BinaryIO,
    events: Iterable[CalendarEvent],
    portfolio: Portfolio,
) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    size = 0
    count = 0
    zone = _zone(portfolio.timezone)

    def write(line: bytes) -> None:
        nonlocal size
        block = line + b"\r\n"
        output.write(block)
        digest.update(block)
        size += len(block)

    for line in (
        b"BEGIN:VCALENDAR",
        b"VERSION:2.0",
        *_content_line("PRODID", PRODID),
        b"CALSCALE:GREGORIAN",
        *_content_line("X-WR-CALNAME", _escape_text(portfolio.name, field="portfolio.name")),
        *_content_line(
            "X-IMMOMANAGER-SOURCE-TZID",
            _escape_text(portfolio.timezone, field="portfolio.timezone"),
        ),
    ):
        write(line)

    for event in events:
        event_start = size
        for line in _event_lines(event, zone):
            write(line)
        _write_index_record(identifiers, event_start, size, event.id)
        count += 1

    write(b"END:VCALENDAR")
    return count, size, digest.hexdigest()


def _decode_index_record(raw: bytes) -> tuple[int, int, str]:
    value = json.loads(raw)
    if (
        not isinstance(value, list)
        or len(value) != 3
        or type(value[0]) is not int
        or type(value[1]) is not int
        or not isinstance(value[2], str)
        or not value[2]
        or value[0] < 0
        or value[1] <= value[0]
    ):
        raise ValueError("invalid calendar range index")
    return value[0], value[1], value[2]


def _index_records(path: Path) -> Iterator[tuple[int, int, str]]:
    previous_end = -1
    try:
        with path.open("rb") as source:
            for raw in source:
                record = _decode_index_record(raw)
                if record[0] < previous_end:
                    raise ValueError("unordered calendar range index")
                previous_end = record[1]
                yield record
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            503,
            "Kalenderexport-Scopeprüfung konnte nicht vollständig gelesen werden.",
        ) from exc


def _identifier_batches(path: Path) -> Iterator[tuple[str, ...]]:
    batch: list[str] = []
    for _, _, event_id in _index_records(path):
        batch.append(event_id)
        if len(batch) >= ICAL_BATCH_SIZE:
            yield tuple(batch)
            batch.clear()
    if batch:
        yield tuple(batch)


def _scope_changed() -> HTTPException:
    return HTTPException(
        403,
        "Die Portfoliozuordnung eines Kalendertermins wurde geändert. Bitte den Export erneut starten.",
    )


def _check_live_batch(
    store,
    portfolio_id: str,
    event_ids: tuple[str, ...],
    captured: AccessScope,
) -> None:
    refresh_scope(captured)
    narrowed = _narrow_scope(captured, portfolio_id)
    db = getattr(store, "db", None)

    if db is None:
        raw = object.__getattribute__(store, "__dict__")
        with _memory_lock, scope_context(narrowed):
            portfolio = raw["portfolios"].get(portfolio_id)
            if portfolio is None or not memory_visible(
                store, "portfolios", portfolio, scope=narrowed
            ):
                raise _scope_changed()
            events = raw["calendar_events"]
            for event_id in event_ids:
                event = events.get(event_id)
                if event is None or not memory_visible(
                    store, "calendar_events", event, scope=narrowed
                ):
                    raise _scope_changed()
            refresh_scope(captured)
        return

    engine = db.get_bind()
    if not isinstance(engine, Engine):
        raise HTTPException(503, "Kalenderexport-Backend wird nicht unterstützt.")
    event_table = CalendarEventORM.__table__
    portfolio_table = PortfolioORM.__table__
    event_scope = scoped_clause(event_table, scope=narrowed)
    portfolio_scope = scoped_clause(portfolio_table, scope=narrowed)
    with engine.connect() as live, scope_context(narrowed):
        portfolio_query = select(portfolio_table.c.id).where(
            portfolio_table.c.id == portfolio_id
        )
        if portfolio_scope is not None:
            portfolio_query = portfolio_query.where(portfolio_scope)
        if live.scalar(portfolio_query) is None:
            raise _scope_changed()

        if event_ids:
            query = select(event_table.c.id).where(
                event_table.c.id.in_(event_ids)
            )
            if event_scope is not None:
                query = query.where(event_scope)
            visible = set(live.execute(query).scalars())
            if visible != set(event_ids):
                raise _scope_changed()
        refresh_scope(captured)


def _revalidate_live_scope(
    store,
    portfolio_id: str,
    identifiers: Path,
    captured: AccessScope,
) -> None:
    _check_live_batch(store, portfolio_id, (), captured)
    for batch in _identifier_batches(identifiers):
        _check_live_batch(store, portfolio_id, batch, captured)
    refresh_scope(captured)


class CalendarChunkScopeGuard:
    """Sequential range guard; each index record is read at most once."""

    def __init__(
        self,
        store,
        portfolio_id: str,
        index_path: Path,
        captured: AccessScope,
    ):
        self.store = store
        self.portfolio_id = portfolio_id
        self.captured = captured
        self.source = index_path.open("rb")
        self.pending: tuple[int, int, str] | None = None
        self.active: tuple[int, int, str] | None = None
        self.previous_end = -1
        self.expected_start = 0

    def close(self) -> None:
        self.source.close()

    def _next_record(self) -> tuple[int, int, str] | None:
        raw = self.source.readline()
        if not raw:
            return None
        try:
            record = _decode_index_record(raw)
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(
                503,
                "Kalenderexport-Scopeprüfung konnte nicht vollständig gelesen werden.",
            ) from exc
        if record[0] < self.previous_end:
            raise HTTPException(
                503,
                "Kalenderexport-Scopeprüfung ist nicht geordnet.",
            )
        self.previous_end = record[1]
        return record

    def _check(self, event_ids: list[str]) -> None:
        if event_ids:
            _check_live_batch(
                self.store,
                self.portfolio_id,
                tuple(event_ids),
                self.captured,
            )
            event_ids.clear()

    def __call__(self, start: int, end: int) -> None:
        if start != self.expected_start or end <= start:
            raise HTTPException(503, "Kalenderexport-Transferbereich ist ungültig.")
        self.expected_start = end

        # Always recheck the requested portfolio/grants, even for header-only
        # or trailer-only chunks.
        _check_live_batch(self.store, self.portfolio_id, (), self.captured)
        event_ids: list[str] = []

        if self.active is not None:
            if self.active[1] > start:
                event_ids.append(self.active[2])
                if self.active[1] > end:
                    self._check(event_ids)
                    return
            self.active = None

        while True:
            record = self.pending
            if record is None:
                record = self._next_record()
            else:
                self.pending = None
            if record is None:
                break
            if record[0] >= end:
                self.pending = record
                break
            if record[1] > start:
                event_ids.append(record[2])
                if len(event_ids) >= ICAL_BATCH_SIZE:
                    self._check(event_ids)
            if record[1] > end:
                self.active = record
                break

        self._check(event_ids)


def revalidate_calendar_download(store, compiled: CompiledExport, captured: AccessScope) -> None:
    """Repeat the complete bounded relationship guard before response release."""
    portfolio_id = str(compiled.manifest["portfolio_id"])
    identifiers = compiled.path.parent / "event-ranges.jsonl"
    _revalidate_live_scope(store, portfolio_id, identifiers, captured)


def calendar_chunk_scope_guard(
    store,
    compiled: CompiledExport,
    captured: AccessScope,
) -> CalendarChunkScopeGuard:
    """Create one sequential body guard owned by the compiled export cleanup."""
    guard = CalendarChunkScopeGuard(
        store,
        str(compiled.manifest["portfolio_id"]),
        compiled.path.parent / "event-ranges.jsonl",
        captured,
    )
    compiled.cleanup.callback(guard.close)
    return guard


def prepare_calendar_download(store, portfolio_id: str, *, parent: Path | None = None):
    """Compile one complete private file from one coherent read snapshot."""
    from scripts.private_server_backup import private_workspace, protected_new_file

    captured = current_scope()
    if captured is None:
        raise HTTPException(401, "Authentifizierung erforderlich.")

    cleanup = ExitStack()
    try:
        workspace, _ = cleanup.enter_context(private_workspace(parent))
        path = workspace / "calendar.ics"
        identifiers = workspace / "event-ranges.jsonl"
        with _calendar_snapshot(store, portfolio_id, captured) as (portfolio, events):
            with (
                protected_new_file(path) as output,
                protected_new_file(identifiers) as identifier_output,
            ):
                count, size, checksum = _write_calendar(
                    output, identifier_output, events, portfolio
                )
            refresh_scope(captured)

        _revalidate_live_scope(store, portfolio_id, identifiers, captured)
        manifest = {
            "portfolio_id": portfolio_id,
            "events": count,
            "size": size,
            "sha256": checksum,
            "timezone": portfolio.timezone,
        }
        return CompiledExport(path, manifest, cleanup), captured
    except OSError as exc:
        cleanup.close()
        raise HTTPException(
            503,
            "Kalenderexport konnte nicht vollständig im privaten Temporärspeicher erstellt werden.",
        ) from exc
    except BaseException:
        cleanup.close()
        raise
