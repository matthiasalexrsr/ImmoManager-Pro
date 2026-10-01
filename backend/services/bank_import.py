"""Durable reviewed bank imports; one atomic publication, never matching/payments."""
import base64
import hashlib
import hmac
import json
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Table, create_engine, func, insert, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ..config import settings
from ..db.bank_import_models import BankImportORM, BankImportReceiptORM, BankImportRowORM, BankImportSourceORM
from ..db.bank_import_schema import ensure_bank_import_schema
from ..db.orm_models import AccountORM, BookingORM
from ..models import Booking
from ..permissions import may_write_resource
from .bank_import_parser import BankMapping, BankRow, parse_rows
from .payments import _memory_lock
from .portfolio_scope import refresh_scope, scope_context, scoped_clause


class BankImportError(ValueError):
    def __init__(self, code, message, status=409, recovery="reload_import"):
        super().__init__(message)
        self.code, self.status, self.recovery = code, status, recovery

    @property
    def detail(self):
        return {"clear_code": self.code, "message": str(self), "recovery": self.recovery}


class BankConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0, strict=True)
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def capacity():
    page = getattr(settings, "bank_import_page_max_size", 500)
    field = getattr(settings, "bank_import_field_max_chars", 100_000)
    if type(page) is not int or not 25 <= page <= 5000 or type(field) is not int or not 1024 <= field <= 100_000_000:
        raise RuntimeError("Bank import technical capacities must be validated server configuration.")
    return page, field


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fresh(scope, *, write=False):
    refresh_scope(scope)
    if write and scope is not None and not may_write_resource(scope.role, "bookings"):
        raise BankImportError("BANK_WRITE_DENIED", "Keine Berechtigung zum Bankimport.", 403)


@contextmanager
def journal(store, *, write=False):
    sql = hasattr(store, "db")
    if not sql:
        _memory_lock.acquire()
    try:
        if not sql and not hasattr(store, "_bank_import_engine"):
            store._bank_import_engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
            with store._bank_import_engine.begin() as connection:
                ensure_bank_import_schema(connection)
        db = store.db if sql else Session(store._bank_import_engine)
        # Journal visibility is checked against its current authoritative account.
        # Generic resource hooks must not infer visibility for sidecar rows.
        with scope_context(None):
            try:
                if write and db.get_bind().dialect.name == "sqlite":
                    connection = db.connection()
                    driver = connection.connection.driver_connection
                    if driver is None:
                        raise RuntimeError("SQLite bank import requires an active native connection.")
                    if not driver.in_transaction:
                        # Leading WITH DML is not detected by SQLite's legacy
                        # driver. Begin before any read, including snapshot/job
                        # reads, so every later chunk can really roll back.
                        connection.exec_driver_sql("BEGIN IMMEDIATE")
                yield db
            except BaseException:
                db.rollback()
                raise
            finally:
                if not sql:
                    db.close()
    finally:
        if not sql:
            _memory_lock.release()


def _account(store, db, account_id, scope, *, lock=False):
    _fresh(scope, write=lock)
    if not hasattr(store, "db"):
        with scope_context(scope):
            account = store.accounts.get(account_id)
    else:
        table = cast(Table, AccountORM.__table__)
        clause = scoped_clause(table, scope=scope)
        predicate = [table.c.id == account_id]
        if clause is not None:
            predicate.append(clause)
        if lock:
            # UPDATE obtains the SQLite writer lock and PG account row lock.
            result = db.execute(update(table).where(*predicate).values(id=table.c.id, updated_at=table.c.updated_at))
            affected = result.rowcount
            if affected == -1 and not result.returns_rows and db.get_bind().dialect.name == "sqlite":
                affected = db.connection().exec_driver_sql("SELECT changes()").scalar_one()
            if affected != 1:
                raise BankImportError("BANK_ACCOUNT_NOT_FOUND", "Konto nicht mehr verfügbar oder nicht freigegeben.", 404)
        account = db.scalar(select(AccountORM).where(*predicate).execution_options(populate_existing=True))
    if account is None:
        raise BankImportError("BANK_ACCOUNT_NOT_FOUND", "Konto nicht mehr verfügbar oder nicht freigegeben.", 404)
    return account


def _load(store, db, import_id, scope, *, write=False):
    _fresh(scope, write=write)
    job = db.get(BankImportORM, import_id, populate_existing=True)
    if not job:
        raise BankImportError("BANK_IMPORT_NOT_FOUND", "Import nicht gefunden.", 404)
    account = _account(store, db, job.account_id, scope, lock=write)
    if write:
        db.refresh(job)  # Another confirmer may have finished while we waited.
    if account.portfolio_id != job.portfolio_id:
        raise BankImportError("BANK_ACCOUNT_MOVED", "Konto wurde einem anderen Portfolio zugeordnet. Import neu prüfen.", 403)
    if write and job.state != "committed" and job.mapping.get("format") == "mt940" and job.mapping.get("account_binding_hash") != _account_binding(account):
        raise BankImportError("BANK_ACCOUNT_CHANGED", "Kontoverbindung wurde seit der Prüfung geändert. Datei mit aktuellem Konto neu prüfen.", 409, "recheck_file")
    return job


def _account_binding(account):
    canonical_iban = "".join((account.iban or "").split()).upper()
    return digest(["bank-account-binding-v1", account.id, canonical_iban])


def summary(job, persistent, *, replay=False):
    return {"id": job.id, "account_id": job.account_id, "portfolio_id": job.portfolio_id,
        "filename": job.filename, "source_sha256": job.source_sha256, "source_bytes": job.source_bytes,
        "mapping": job.mapping, "mapping_hash": job.mapping_hash, "preview_hash": job.preview_hash,
        "state": job.state, "revision": job.revision, "row_count": job.row_count,
        "error_count": job.error_count, "duplicate_count": job.duplicate_count,
        "published_count": job.published_count, "created_at": job.created_at.isoformat(),
        "committed_at": job.committed_at.isoformat() if job.committed_at else None,
        "persistent": persistent, "replay": replay, "maximum_page_size": capacity()[0]}


def _row_content(row):
    return {"booking_date": row.booking_date.isoformat() if row.booking_date else None,
        "value_date": row.value_date.isoformat() if row.value_date else None,
        "amount_cents": row.amount_cents, "payment_text": row.text}


def _prepare_chunk(db, job, rows):
    bases = {digest(row.identity) for row in rows if row.identity}
    occurrences = dict(db.execute(select(BankImportRowORM.identity_base, func.max(BankImportRowORM.identity_occurrence))
        .where(BankImportRowORM.import_id == job.id, BankImportRowORM.identity_base.in_(bases))
        .group_by(BankImportRowORM.identity_base)).all()) if bases else {}
    result = []
    for row in rows:
        base = digest(row.identity) if row.identity else None
        occurrence = occurrences.get(base, 0) + 1 if base else 1
        if base:
            occurrences[base] = occurrence
        fingerprint = digest([job.account_id, base, occurrence]) if base else digest([job.account_id, job.source_sha256, row.ordinal])
        content_hash = digest(_row_content(row))
        error_code, message = row.error_code, row.error_message
        if row.identity and row.identity.startswith("csv:") and occurrence > 1:
            error_code, message = "BANK_REFERENCE_REPEATED", "Als eindeutige Bank-ID gewählte Referenz kommt mehrfach vor. Spaltenzuordnung prüfen."
        result.append({"import_id": job.id, "ordinal": row.ordinal, "source_line": row.source_line,
            "booking_date": row.booking_date, "value_date": row.value_date, "amount_cents": row.amount_cents,
            "payment_text": row.text, "bank_reference": row.bank_reference,
            "identity_base": base, "identity_occurrence": occurrence,
            "fingerprint": fingerprint if row.amount_cents is not None else None,
            "content_hash": content_hash, "error_code": error_code, "error_message": message,
            "duplicate_booking_id": None})
    known = {receipt.fingerprint: receipt for receipt in db.scalars(select(BankImportReceiptORM).where(
        BankImportReceiptORM.account_id == job.account_id,
        BankImportReceiptORM.fingerprint.in_([item["fingerprint"] for item in result if item["fingerprint"]])))}
    for item in result:
        previous = known.get(item["fingerprint"])
        if previous:
            if previous.content_hash != item["content_hash"]:
                item["error_code"], item["error_message"] = "BANK_IDENTITY_CONFLICT", "Dieselbe Bank-/Quellidentität wurde bereits mit anderem Inhalt importiert. Vorhandene Buchung prüfen."
            else:
                item["duplicate_booking_id"] = previous.booking_id
    return result


def stage_import(store, source, account_id, mapping: BankMapping, *, filename="bank.csv", actor_id="internal", scope=None):
    _fresh(scope, write=True)
    maximum, maximum_field_chars = capacity()
    sha, size = hashlib.sha256(), 0
    source.seek(0)
    while block := source.read(65_536):
        sha.update(block)
        size += len(block)
    file_sha = sha.hexdigest()
    mapping_data = mapping.model_dump(mode="json")
    with journal(store, write=True) as db:
        account = _account(store, db, account_id, scope, lock=True)
        if mapping.format == "mt940":
            mapping_data["account_binding_hash"] = _account_binding(account)
        mapping_hash = digest(mapping_data)
        known = db.scalar(select(BankImportORM).where(BankImportORM.account_id == account_id,
            BankImportORM.source_sha256 == file_sha, BankImportORM.mapping_hash == mapping_hash))
        if known:
            response = summary(_load(store, db, known.id, scope), hasattr(store, "db"), replay=True)
            db.rollback()  # Release the account lock on a read-only replay.
            return response
        job = BankImportORM(id=str(uuid4()), account_id=account_id, portfolio_id=account.portfolio_id,
            creator_id=actor_id, scope_snapshot=asdict(scope) if scope else None,
            filename=filename.replace("\\", "/").rsplit("/", 1)[-1][:255] or "bank-file",
            source_sha256=file_sha, source_bytes=size, mapping=mapping_data, mapping_hash=mapping_hash,
            preview_hash="", state="preparing", revision=0, row_count=0, error_count=0,
            duplicate_count=0, published_count=0, created_at=_now())
        db.add(job)
        db.flush()
        source.seek(0)
        chunk_no = 0
        while block := source.read(65_536):
            db.execute(insert(BankImportSourceORM), {"import_id": job.id, "chunk_no": chunk_no, "data": block})
            chunk_no += 1
        source.seek(0)
        accumulator = hashlib.sha256()
        chunk: list[BankRow] = []

        def persist():
            items = _prepare_chunk(db, job, chunk)
            for item in items:
                job.row_count += 1
                job.error_count += bool(item["error_code"])
                job.duplicate_count += bool(item["duplicate_booking_id"] and not item["error_code"])
                accumulator.update(json.dumps({key: str(value) if key in {"booking_date", "value_date"} and value else value
                    for key, value in item.items()}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n")
            db.execute(insert(BankImportRowORM), items)
            chunk.clear()

        for row in parse_rows(source, mapping, maximum_field_chars=maximum_field_chars, expected_account=account.iban):
            # Encoding failures have no physical row; preserve unique ordinal.
            if row.ordinal <= job.row_count + len(chunk):
                from dataclasses import replace
                row = replace(row, ordinal=job.row_count + len(chunk) + 1)
            chunk.append(row)
            if len(chunk) >= maximum:
                persist()
        if chunk:
            persist()
        job.preview_hash = digest(["bank-import-preview-v1", account_id, file_sha, mapping_hash, accumulator.hexdigest()])
        job.state = "invalid" if job.error_count or not job.row_count else "ready"
        _verify_source(db, job)
        _fresh(scope, write=True)
        db.commit()
        return summary(job, hasattr(store, "db"))


def get_import(store, import_id, *, scope=None):
    with journal(store) as db:
        return summary(_load(store, db, import_id, scope), hasattr(store, "db"))


def _cursor(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(settings.jwt_secret_key.encode(), b"bank-import-page-v1\0" + payload, hashlib.sha256).digest()
    return ".".join(base64.urlsafe_b64encode(item).decode().rstrip("=") for item in (payload, signature))


def preview_import(store, import_id, *, page_size=100, cursor=None, errors_only=False, scope=None):
    if type(page_size) is not int or not 1 <= page_size <= capacity()[0]:
        raise BankImportError("BANK_PAGE_CAPACITY", "Kleinere technische Seitengröße auswählen.", 400)
    with journal(store) as db:
        job = _load(store, db, import_id, scope)
        binding = {"v": 1, "id": job.id, "hash": job.preview_hash, "size": page_size, "errors": errors_only,
            "scope": digest(asdict(scope) if scope else None)}
        after = 0
        if cursor:
            try:
                payload, _ = cursor.split(".")
                value = json.loads(base64.b64decode(payload + "=" * (-len(payload) % 4), altchars=b"-_", validate=True))
                if _cursor(value) != cursor or {key: value[key] for key in binding} != binding or type(value["after"]) is not int:
                    raise ValueError
                after = value["after"]
            except (ValueError, KeyError, TypeError):
                raise BankImportError("BANK_CURSOR_INVALID", "Vorschauauswahl geändert oder Token ungültig. Erste Seite neu laden.", 400, "restart_preview") from None
        statement = select(BankImportRowORM).where(BankImportRowORM.import_id == job.id, BankImportRowORM.ordinal > after)
        if errors_only:
            statement = statement.where(BankImportRowORM.error_code.is_not(None))
        rows = list(db.scalars(statement.order_by(BankImportRowORM.ordinal).limit(page_size + 1)))
        has_more = len(rows) > page_size
        rows = rows[:page_size]
        return {"import_id": job.id, "preview_hash": job.preview_hash, "items": [{"ordinal": row.ordinal,
            "source_line": row.source_line, "booking_date": row.booking_date.isoformat() if row.booking_date else None,
            "value_date": row.value_date.isoformat() if row.value_date else None, "amount_cents": row.amount_cents,
            "payment_text": row.payment_text, "bank_reference": row.bank_reference, "fingerprint": row.fingerprint,
            "identity_occurrence": row.identity_occurrence, "error_code": row.error_code, "error_message": row.error_message,
            "duplicate_booking_id": row.duplicate_booking_id} for row in rows], "has_more": has_more,
            "next_cursor": _cursor({**binding, "after": rows[-1].ordinal}) if has_more else None}


def list_imports(store, account_id, *, before=None, page_size=25, scope=None):
    if type(page_size) is not int or not 1 <= page_size <= capacity()[0]:
        raise BankImportError("BANK_PAGE_CAPACITY", "Kleinere Seitengröße auswählen.", 400)
    with journal(store) as db:
        account = _account(store, db, account_id, scope)
        query = select(BankImportORM).where(BankImportORM.account_id == account_id, BankImportORM.portfolio_id == account.portfolio_id)
        if before:
            item = db.get(BankImportORM, before)
            if not item or item.account_id != account_id or item.portfolio_id != account.portfolio_id:
                raise BankImportError("BANK_CURSOR_INVALID", "Importliste neu laden.", 400)
            query = query.where((BankImportORM.created_at < item.created_at) |
                ((BankImportORM.created_at == item.created_at) & (BankImportORM.id < item.id)))
        rows = list(db.scalars(query.order_by(BankImportORM.created_at.desc(), BankImportORM.id.desc()).limit(page_size + 1)))
        return {"items": [summary(row, hasattr(store, "db")) for row in rows[:page_size]],
            "has_more": len(rows) > page_size, "next_cursor": rows[page_size - 1].id if len(rows) > page_size else None}


def import_receipts(store, import_id, *, after=0, page_size=100, scope=None):
    if type(after) is not int or after < 0 or type(page_size) is not int or not 1 <= page_size <= capacity()[0]:
        raise BankImportError("BANK_PAGE_CAPACITY", "Gültige Seitengröße und Fortschrittsposition wählen.", 400)
    with journal(store) as db:
        job = _load(store, db, import_id, scope)
        rows = db.execute(select(BankImportReceiptORM.ordinal, BankImportReceiptORM.booking_id, BankImportReceiptORM.published_at)
            .where(BankImportReceiptORM.import_id == job.id, BankImportReceiptORM.ordinal > after)
            .order_by(BankImportReceiptORM.ordinal).limit(page_size + 1)).all()
        return {"import_id": job.id, "items": [{"ordinal": ordinal, "booking_id": booking_id, "published_at": timestamp.isoformat()}
            for ordinal, booking_id, timestamp in rows[:page_size]], "has_more": len(rows) > page_size,
            "next_after": rows[page_size - 1][0] if len(rows) > page_size else None}


def _checked_rows(db, job):
    after = 0
    while True:
        rows = db.execute(select(BankImportRowORM.__table__).where(BankImportRowORM.import_id == job.id,
            BankImportRowORM.ordinal > after).order_by(BankImportRowORM.ordinal).limit(capacity()[0])).mappings().all()
        if not rows:
            break
        yield rows
        after = rows[-1]["ordinal"]


def _verify_source(db, job):
    sha, size, after = hashlib.sha256(), 0, -1
    while True:
        chunks = db.execute(select(BankImportSourceORM.chunk_no, BankImportSourceORM.data).where(
            BankImportSourceORM.import_id == job.id, BankImportSourceORM.chunk_no > after)
            .order_by(BankImportSourceORM.chunk_no).limit(8)).all()
        if not chunks:
            break
        for chunk_no, data in chunks:
            if chunk_no != after + 1:
                raise BankImportError("BANK_SOURCE_INTEGRITY", "Gesicherte Quelldatei ist unvollständig.")
            sha.update(data)
            size += len(data)
            after = chunk_no
    if size != job.source_bytes or sha.hexdigest() != job.source_sha256 or digest(job.mapping) != job.mapping_hash:
        raise BankImportError("BANK_SOURCE_INTEGRITY", "Quelldatei oder geprüfte Zuordnung wurde verändert.")


def commit_import(store, import_id, payload: BankConfirm, *, scope=None):
    _fresh(scope, write=True)
    memory_prepared = {}
    with journal(store, write=True) as db:
        job = _load(store, db, import_id, scope, write=True)
        if payload.preview_hash != job.preview_hash:
            raise BankImportError("BANK_PREVIEW_CHANGED", "Bestätigung gehört zu einer anderen geprüften Vorschau.")
        if job.state == "committed":
            response = summary(job, hasattr(store, "db"), replay=True)
            db.rollback()
            return response
        if job.state != "ready" or job.error_count:
            raise BankImportError("BANK_PREVIEW_INVALID", "Datei enthält Fehler. Keine Buchung wurde veröffentlicht.", 422, "correct_file")
        claim = db.execute(update(BankImportORM).where(BankImportORM.id == job.id,
            BankImportORM.state == "ready", BankImportORM.revision == payload.revision)
            .values(revision=BankImportORM.revision + 1), execution_options={"synchronize_session": False})
        if claim.rowcount != 1:
            raise BankImportError("BANK_IMPORT_STALE", "Import wurde bereits geändert. Gespeicherten Stand neu laden.")
        db.refresh(job)
        _verify_source(db, job)
        accumulator = hashlib.sha256()
        published, duplicates = 0, 0
        try:
            for rows in _checked_rows(db, job):
                _fresh(scope, write=True)
                existing = {row.fingerprint: row for row in db.scalars(select(BankImportReceiptORM).where(
                    BankImportReceiptORM.account_id == job.account_id,
                    BankImportReceiptORM.fingerprint.in_([row["fingerprint"] for row in rows])))}
                bookings, receipts = [], []
                for row in rows:
                    accumulator.update(json.dumps({key: str(value) if key in {"booking_date", "value_date"} and value else value
                        for key, value in row.items()}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n")
                    previous = existing.get(row["fingerprint"])
                    if previous:
                        if previous.content_hash != row["content_hash"]:
                            raise BankImportError("BANK_IDENTITY_CONFLICT", "Bankidentität wurde gleichzeitig mit anderem Inhalt importiert.")
                        duplicates += 1
                        continue
                    booking_id, now = str(uuid4()), _now()
                    bookings.append({"id": booking_id, "account_id": job.account_id, "booking_date": row["booking_date"],
                        "amount": Decimal(row["amount_cents"]) / 100, "payment_text": row["payment_text"],
                        "status": "open", "allocated_amount": Decimal(0), "created_at": now, "updated_at": now})
                    receipts.append({"import_id": job.id, "ordinal": row["ordinal"], "account_id": job.account_id,
                        "fingerprint": row["fingerprint"], "content_hash": row["content_hash"], "booking_id": booking_id, "published_at": now})
                if bookings:
                    if hasattr(store, "db"):
                        db.execute(insert(cast(Table, BookingORM.__table__)), bookings)
                    else:
                        for values in bookings:
                            memory_prepared[values["id"]] = Booking.model_validate(values)
                    db.execute(insert(BankImportReceiptORM), receipts)
                    published += len(bookings)
            expected = digest(["bank-import-preview-v1", job.account_id, job.source_sha256, job.mapping_hash, accumulator.hexdigest()])
            if expected != job.preview_hash:
                raise BankImportError("BANK_PREVIEW_INTEGRITY", "Gesicherte Vorschau wurde verändert. Keine Buchungen veröffentlicht.")
            # Refresh actor and current account again before the single publication.
            _fresh(scope, write=True)
            _account(store, db, job.account_id, scope, lock=True)
            job.state, job.published_count, job.duplicate_count, job.committed_at = "committed", published, duplicates, _now()
            db.commit()
            if not hasattr(store, "db"):
                # One C-level dictionary update publishes the reference backend
                # only after every row and the journal commit succeeded.
                object.__getattribute__(store, "__dict__")["bookings"].update(memory_prepared)
        except BaseException:
            raise
        return summary(job, hasattr(store, "db"))
