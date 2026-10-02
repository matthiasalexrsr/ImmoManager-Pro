"""Reviewed DATEV exports from one authorized repeatable SQL snapshot.

The complete ZIP is built and validated privately before HTTP headers are sent.
Only an immutable reference/manifest is retained. Downloads rebuild the same
snapshot reference and refuse source changes rather than silently exporting a
different file. No booking list, CSV or ZIP is accumulated in application RAM.
"""

import hashlib
import hmac
import importlib
import json
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from itertools import chain, groupby, islice
from pathlib import Path
from typing import Any
from uuid import uuid4
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError

from scripts.private_server_backup import private_workspace

from ..datev_models import DatevPreviewCreate, DatevProfileCreate
from ..db.datev_models import DatevExportORM, DatevProfileORM
from ..db.orm_models import AccountORM, BookingORM, CategoryORM, PortfolioORM
from .booking_export import _snapshot
from .datev_streaming import (
    DATEV_BATCH_ROWS,
    Batch,
    Entry,
    ExportError,
    Profile,
    Rule,
    amount,
    canonical,
    prepare_download,
)

SQL_BATCH_SIZE = 1000  # Memory buffer, not an export limit.
PREVIEW_ROWS = 10  # Display samples; the entire export is still validated.


def scope_helpers():
    # This workflow requires the authoritative ACL service. Missing/broken scope
    # wiring is an unavailable export, never an unscoped fallback.
    try:
        portfolio_scope = importlib.import_module("backend.services.portfolio_scope")
    except ImportError as exc:
        raise HTTPException(503, "DATEV portfolio authorization is unavailable") from exc
    return portfolio_scope


def database(store):
    if not hasattr(store, "db"):
        raise HTTPException(503, "DATEV profiles require the persistent SQL backend")
    return store.db


def scoped(statement, model, captured):
    predicate = scope_helpers().scoped_clause(model, scope=captured)
    return statement.where(predicate) if predicate is not None else statement


def read_profile(row):
    spec = json.loads(row.spec_json)
    return {"id": row.id, "portfolio_id": row.portfolio_id,
            "previous_version_id": row.previous_version_id, "actor_id": row.actor_id,
            "created_at": row.created_at.isoformat(), "sha256": row.sha256, "spec": spec}


def profile_row(store, version_id):
    db = database(store)
    row = db.scalar(scoped(select(DatevProfileORM).where(DatevProfileORM.id == version_id),
                           DatevProfileORM, scope_helpers().current_scope()))
    if row is None:
        raise HTTPException(404, "DATEV profile version not found")
    store.get_portfolio(row.portfolio_id)
    return row


def list_profiles(store, portfolio_id, offset=0, limit=100):
    store.get_portfolio(portfolio_id)
    db = database(store)
    query = scoped(select(DatevProfileORM).where(DatevProfileORM.portfolio_id == portfolio_id),
                   DatevProfileORM, scope_helpers().current_scope())
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(DatevProfileORM.created_at.desc(), DatevProfileORM.id.desc())
                      .offset(offset).limit(limit)).all()
    return {"total": total, "items": [read_profile(row) for row in rows]}


def options(store, portfolio_id):
    store.get_portfolio(portfolio_id)
    db, captured = database(store), scope_helpers().current_scope()
    result = {}
    for key, model, columns in (
        ("accounts", AccountORM, (AccountORM.id, AccountORM.name, AccountORM.account_type)),
        ("categories", CategoryORM, (CategoryORM.id, CategoryORM.name, CategoryORM.category_type)),
    ):
        query = scoped(select(*columns).where(model.portfolio_id == portfolio_id), model, captured)
        result[key] = [dict(row) for row in db.execute(query.order_by(model.name, model.id)).mappings()]
    return result


def create_profile(store, command: DatevProfileCreate, actor_id):
    db = database(store)
    store.get_portfolio(command.portfolio_id)
    spec = command.model_dump(mode="json", exclude={"idempotency_key", "previous_version_id"})
    encoded = canonical(spec).decode("ascii")
    fingerprint = hashlib.sha256(encoded.encode("ascii")).hexdigest()
    key = actor_id + ":" + command.idempotency_key

    def replay(row):
        if (row.sha256 != fingerprint or row.previous_version_id != command.previous_version_id
                or row.portfolio_id != command.portfolio_id):
            raise HTTPException(409, "This profile reference already belongs to a different draft")
        store.get_portfolio(row.portfolio_id)
        return read_profile(row)

    existing = db.scalar(select(DatevProfileORM).where(DatevProfileORM.idempotency_key == key))
    if existing:
        return replay(existing)
    if command.previous_version_id:
        previous = profile_row(store, command.previous_version_id)
        if previous.portfolio_id != command.portfolio_id:
            raise HTTPException(422, "Profile versions must belong to the same portfolio")
    for rule in command.rules:
        account = store.get_account(rule.account_id)
        category = store.get_category(rule.category_id)
        if account.portfolio_id != command.portfolio_id or category.portfolio_id != command.portfolio_id:
            raise HTTPException(422, "Mapping account/category belongs to a different portfolio")
        if rule.account_type != account.account_type:
            raise HTTPException(422, "Mapping account type differs from the actual account type")
    row = DatevProfileORM(id=str(uuid4()), portfolio_id=command.portfolio_id,
        previous_version_id=command.previous_version_id, idempotency_key=key,
        actor_id=actor_id, spec_json=encoded, sha256=fingerprint,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None))
    db.add(row)
    try:
        scope_helpers().refresh_scope(scope_helpers().current_scope())
        db.commit()
        return read_profile(row)
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(DatevProfileORM).where(DatevProfileORM.idempotency_key == key))
        if existing is None:
            raise HTTPException(409, "Profile could not be saved; reload the portfolio") from None
        return replay(existing)


def entries(connection, portfolio_id, command, spec, captured):
    account, category, booking = AccountORM.__table__, CategoryORM.__table__, BookingORM.__table__
    category_on = category.c.id == booking.c.category_id
    category_scope = scope_helpers().scoped_clause(CategoryORM, scope=captured)
    if category_scope is not None:
        category_on = and_(category_on, category_scope)
    query = select(booking.c.id, booking.c.account_id, booking.c.category_id,
        account.c.portfolio_id.label("account_portfolio_id"),
        category.c.portfolio_id.label("category_portfolio_id"), account.c.account_type,
        booking.c.booking_date, booking.c.amount,
        booking.c.status, booking.c.updated_at, booking.c.payment_text).select_from(
        booking.join(account, account.c.id == booking.c.account_id).outerjoin(category, category_on)
    ).where(account.c.portfolio_id == portfolio_id, booking.c.status == "confirmed",
            booking.c.booking_date >= command.start_date, booking.c.booking_date <= command.end_date)
    for model in (BookingORM, AccountORM):
        query = scoped(query, model, captured)
    previous = None
    while True:
        page = query
        if previous:
            day, identifier = previous
            page = page.where((booking.c.booking_date > day) | and_(booking.c.booking_date == day, booking.c.id > identifier))
        rows = connection.execute(page.order_by(booking.c.booking_date, booking.c.id)
                                  .limit(SQL_BATCH_SIZE)).mappings().all()
        if not rows:
            return
        scope_helpers().refresh_scope(captured)
        for row in rows:
            values = dict(row)
            # Full internal ID only after the profile explicitly selected it;
            # otherwise optional Belegfeld 1 remains empty, no invented invoice.
            values["document_ref"] = row["id"] if spec["document_reference"] == "internal_booking_id" else ""
            yield Entry(**values)
        previous = rows[-1]["booking_date"], rows[-1]["id"]


@dataclass
class CompiledExport:
    path: Path
    manifest: dict[str, Any]
    cleanup: ExitStack

    def close(self):
        self.cleanup.close()


def compile_export(store, command, version_id, export_id, generated_at, *, expected=None, parent=None):
    db = database(store)
    profile = profile_row(store, version_id)
    portfolio_id = profile.portfolio_id
    captured = scope_helpers().current_scope()
    cleanup = ExitStack()
    try:
        workspace, _ = cleanup.enter_context(private_workspace(parent))
        archive_path = workspace / "datev.zip"
        manifest = {"format": "immomanager-datev", "version": 1, "export_id": export_id,
            "profile_version_id": version_id, "profile_sha256": profile.sha256,
            "portfolio_id": portfolio_id, "start_date": command.start_date.isoformat(),
            "end_date": command.end_date.isoformat(), "generated_at": generated_at.isoformat(), "timestamp_timezone": "UTC",
            "rows": 0, "income": "0.00", "expense": "0.00", "files": [], "samples": []}
        digest, totals = hashlib.sha256(), {"income": 0, "expense": 0}
        engine = db.get_bind()
        with scope_helpers().scope_context(captured), _snapshot(engine) as connection:
            version_query = scoped(select(DatevProfileORM.__table__).where(DatevProfileORM.id == version_id), DatevProfileORM, captured)
            frozen = connection.execute(version_query).mappings().first()
            if frozen is None or frozen["sha256"] != profile.sha256:
                raise HTTPException(409, "Profile changed before the export snapshot")
            spec = json.loads(frozen["spec_json"])
            if (spec.get("portfolio_id") != portfolio_id
                    or hashlib.sha256(canonical(spec)).hexdigest() != frozen["sha256"]):
                raise HTTPException(409, "DATEV profile_integrity: saved mapping fingerprint does not match")
            DatevProfileCreate(**spec, idempotency_key="snapshot-validation")
            timezone_query = scoped(select(PortfolioORM.timezone, PortfolioORM.currency)
                                   .where(PortfolioORM.id == portfolio_id), PortfolioORM, captured)
            portfolio = connection.execute(timezone_query).one()
            if portfolio.currency != "EUR":
                raise ExportError("portfolio_currency")
            local_time = generated_at.astimezone(timezone.utc)  # Explicit UTC timestamp, also on Windows without OS tzdata.
            rules = {(r["account_id"], r["category_id"], r["flow"]): Rule(
                r["bank_gl"], r["counter_gl"], "EUR", r["no_vat_nonautomatic"], r["account_type"], r["counter_kind"])
                for r in spec["rules"]}

            def observe():
                for entry in entries(connection, portfolio_id, command, spec, captured):
                    # The formatter validates this row before asking for the
                    # next one. Do not mask a source error as a filesystem error
                    # or accidentally report the previous booking's identifier.
                    yield entry
                    value = amount(entry.amount)
                    digest.update(canonical({**asdict(entry), "amount": format(value, "f"),
                        "booking_date": entry.booking_date.isoformat(), "updated_at": entry.updated_at.isoformat()}) + b"\n")
                    cents = int(value * 100)
                    totals["income" if cents > 0 else "expense"] += abs(cents)
                    if len(manifest["samples"]) < PREVIEW_ROWS:
                        manifest["samples"].append({"id": entry.id, "date": entry.booking_date.isoformat(),
                            "account_id": entry.account_id, "category_id": entry.category_id,
                            "amount": format(value, "f"), "text": entry.payment_text})
                    manifest["rows"] += 1

            with archive_path.open("xb") as output, ZipFile(output, "w", compression=ZIP_STORED, allowZip64=True) as archive:
                for year, annual in groupby(observe(), key=lambda entry: entry.booking_date.year):
                    period_start, period_end = max(command.start_date, date(year, 1, 1)), min(command.end_date, date(year, 12, 31))
                    profile_plan = Profile(spec["adviser"], spec["client"], date(year, 1, 1),
                        spec["gl_length"], portfolio_id, spec["chart"], spec["freeze"], version_id, spec["reviewed_by"], rules)
                    sequence = 0
                    while (first := next(annual, None)) is not None:
                        sequence += 1
                        filename = f"EXTF_Buchungsstapel_{year}_{sequence:04}.csv"
                        batch = Batch(period_start, period_end, local_time, f"{export_id}/{year}/{sequence}", f"Immo {year} {sequence}")
                        current = {"entry": first}

                        def track():
                            for entry in chain((first,), islice(annual, DATEV_BATCH_ROWS - 1)):
                                current["entry"] = entry
                                yield entry

                        try:
                            with prepare_download(track(), profile_plan, batch, spool_dir=workspace) as prepared:
                                info = ZipInfo(filename, generated_at.timetuple()[:6])
                                info.external_attr = 0o600 << 16
                                with prepared.path.open("rb") as source, archive.open(info, "w", force_zip64=True) as target:
                                    while chunk := source.read(1024 * 1024):
                                        target.write(chunk)
                                manifest["files"].append({"name": filename, "rows": prepared.rows,
                                    "size": prepared.size, "sha256": prepared.sha256})
                        except ExportError as exc:
                            if exc.code in {"build_failed", "spool_unavailable", "cleanup_failed"}:
                                raise HTTPException(503, f"DATEV {exc.code}: private temporary file could not be completed") from None
                            entry = current["entry"]
                            raise HTTPException(422, f"DATEV {exc.code}: booking {entry.id}; account {entry.account_id}; category {entry.category_id or '(missing)'}") from None
                if manifest["rows"] == 0:
                    raise HTTPException(422, "DATEV no_confirmed_bookings: no confirmed bookings in this portfolio and period")
                manifest["source_sha256"] = digest.hexdigest()
                for flow, cents in totals.items():
                    whole, part = divmod(cents, 100)
                    manifest[flow] = f"{whole}.{part:02}"
                info = ZipInfo("manifest.json", generated_at.timetuple()[:6])
                info.external_attr = 0o600 << 16
                archive.writestr(info, canonical(manifest))
            with ZipFile(archive_path) as verification:
                if verification.testzip() is not None:
                    raise HTTPException(503, "DATEV archive_integrity: complete export could not be verified")
            # Close/flush ZIP before computing its public fingerprint.
            with archive_path.open("rb") as completed_archive:
                manifest["sha256"] = hashlib.file_digest(completed_archive, "sha256").hexdigest()
            manifest["size"] = archive_path.stat().st_size
            if expected is not None and not hmac.compare_digest(manifest["sha256"], expected["sha256"]):
                raise HTTPException(409, "DATEV source_changed: bookings/account/category changed since preview; create a new preview")
            scope_helpers().refresh_scope(captured)
        return CompiledExport(archive_path, manifest, cleanup)
    except OSError:
        cleanup.close()
        raise HTTPException(503, "DATEV temporary_storage: complete private export could not be written") from None
    except BaseException:
        cleanup.close()
        raise


def read_export(row):
    return {"id": row.id, "actor_id": row.actor_id, **json.loads(row.manifest_json)}


def export_row(store, export_id):
    db = database(store)
    row = db.scalar(scoped(select(DatevExportORM).where(DatevExportORM.id == export_id),
                           DatevExportORM, scope_helpers().current_scope()))
    if row is None:
        raise HTTPException(404, "DATEV export reference not found")
    store.get_portfolio(row.portfolio_id)
    return row


def create_preview(store, command: DatevPreviewCreate, actor_id):
    db = database(store)
    profile = profile_row(store, command.profile_version_id)
    key = actor_id + ":" + command.idempotency_key
    request_json = canonical(command.model_dump(mode="json", exclude={"idempotency_key"})).decode("ascii")

    def replay(row):
        if row.request_json != request_json:
            raise HTTPException(409, "This export reference belongs to a different period/profile")
        store.get_portfolio(row.portfolio_id)
        return read_export(row)

    existing = db.scalar(select(DatevExportORM).where(DatevExportORM.idempotency_key == key))
    if existing:
        return replay(existing)
    identifier, generated = str(uuid4()), datetime.now(timezone.utc).replace(microsecond=0)
    compiled = compile_export(store, command, profile.id, identifier, generated)
    try:
        row = DatevExportORM(id=identifier, portfolio_id=profile.portfolio_id,
            profile_version_id=profile.id, idempotency_key=key, actor_id=actor_id,
            request_json=request_json, manifest_json=canonical(compiled.manifest).decode("ascii"),
            created_at=generated.replace(tzinfo=None))
        db.add(row)
        scope_helpers().refresh_scope(scope_helpers().current_scope())
        try:
            db.commit()
            return read_export(row)
        except IntegrityError:
            db.rollback()
            existing = db.scalar(select(DatevExportORM).where(DatevExportORM.idempotency_key == key))
            if existing is None:
                raise HTTPException(409, "Export reference could not be saved; create a new preview") from None
            return replay(existing)
    finally:
        compiled.close()


def list_exports(store, portfolio_id, offset=0, limit=100):
    store.get_portfolio(portfolio_id)
    db = database(store)
    query = scoped(select(DatevExportORM).where(DatevExportORM.portfolio_id == portfolio_id),
                   DatevExportORM, scope_helpers().current_scope())
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(DatevExportORM.created_at.desc(), DatevExportORM.id.desc())
                      .offset(offset).limit(limit)).all()
    return {"total": total, "items": [read_export(row) for row in rows]}


def prepare_saved_download(store, export_id):
    row = export_row(store, export_id)
    command = DatevPreviewCreate(**json.loads(row.request_json), idempotency_key="download")
    generated = row.created_at.replace(tzinfo=timezone.utc)
    return compile_export(store, command, row.profile_version_id, row.id, generated,
                          expected=json.loads(row.manifest_json))
