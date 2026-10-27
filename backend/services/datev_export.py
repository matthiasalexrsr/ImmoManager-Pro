"""Reviewed DATEV exports from one authorized repeatable SQL snapshot.

The complete ZIP is built and validated privately before HTTP headers are sent.
The complete original ZIP is retained in authenticated encrypted blocks.
Downloads verify the retained bytes and current scope before sending headers.
SQL compilation uses bounded buffers and never recreates history from live rows.
"""

import base64
import hashlib
import hmac
import importlib
import json
from contextlib import ExitStack, nullcontext
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from itertools import chain, groupby, islice
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError

from ..datev_models import DatevPreviewCreate, DatevProfileCreate
from ..db.booking_order import bytewise_id
from ..db.datev_models import DatevBlockORM, DatevExportORM, DatevProfileORM
from ..db.orm_models import AccountORM, BookingORM, CategoryORM, PropertyORM
from .annual_tax_source import cash_source
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
from .secret_box import SecretError, default_secret_box
from .tax_support import _memory_lock, _snapshot, finance_write, private_workspace

SQL_BATCH_SIZE = 1000  # Memory buffer, not an export limit.
PREVIEW_ROWS = 10  # Display samples; the entire export is still validated.


def scope_helpers():
    # This workflow requires the authoritative ACL service. Missing/broken scope
    # wiring is an unavailable export, never an unscoped fallback.
    try:
        portfolio_scope = importlib.import_module("backend.services.portfolio_scope")
    except ImportError as exc:
        raise HTTPException(503, "DATEV: Die Portfolio-Berechtigungsprüfung ist nicht verfügbar.") from exc
    return portfolio_scope


def database(store):
    return store.db if hasattr(store, "db") else None


def scoped(statement, model, captured):
    predicate = scope_helpers().scoped_clause(model, scope=captured)
    return statement.where(predicate) if predicate is not None else statement


def read_profile(row):
    try:
        spec = json.loads(row.spec_json)
        if hashlib.sha256(canonical(spec)).hexdigest() != row.sha256 or spec["portfolio_id"] != row.portfolio_id:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise HTTPException(503, "DATEV: Gespeicherte Profilfassung ist beschädigt.") from None
    return {"id": row.id, "portfolio_id": row.portfolio_id,
            "previous_version_id": row.previous_version_id, "actor_id": row.actor_id,
            "created_at": row.created_at.isoformat(), "sha256": row.sha256, "spec": spec}


def profile_row(store, version_id):
    db = database(store)
    if db is None:
        row = memory_state(store).profiles.get(version_id)
        if row is None:
            raise HTTPException(404, "DATEV-Profilfassung nicht gefunden.")
        store.get_portfolio(row.portfolio_id)
        read_profile(row)
        return row
    row = db.scalar(scoped(select(DatevProfileORM).where(DatevProfileORM.id == version_id),
                           DatevProfileORM, scope_helpers().current_scope()))
    if row is None:
        raise HTTPException(404, "DATEV-Profilfassung nicht gefunden.")
    store.get_portfolio(row.portfolio_id)
    return row


def list_profiles(store, portfolio_id, offset=0, limit=100):
    store.get_portfolio(portfolio_id)
    db = database(store)
    if db is None:
        rows = sorted((row for row in memory_state(store).profiles.values() if row.portfolio_id == portfolio_id),
            key=lambda row: (row.created_at, row.id), reverse=True)
        return {"total": len(rows), "items": [read_profile(row) for row in rows[offset:offset + limit]]}
    query = scoped(select(DatevProfileORM).where(DatevProfileORM.portfolio_id == portfolio_id),
                   DatevProfileORM, scope_helpers().current_scope())
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(DatevProfileORM.created_at.desc(), DatevProfileORM.id.desc())
                      .offset(offset).limit(limit)).all()
    return {"total": total, "items": [read_profile(row) for row in rows]}


def options(store, portfolio_id):
    from .ownership import owners

    store.get_portfolio(portfolio_id)
    db, captured = database(store), scope_helpers().current_scope()
    # the owners an export can be made for (create_preview: owner_contact_id)
    choices = {"owners": [{"id": owner["id"], "name": owner["name"]} for owner in owners(store)]}
    if db is None:
        return {"accounts": [{"id": row.id, "name": row.name, "account_type": row.account_type} for row in store.list_accounts() if row.portfolio_id == portfolio_id],
            "categories": [{"id": row.id, "name": row.name, "category_type": row.category_type} for row in store.list_categories() if row.portfolio_id == portfolio_id],
            "properties": [{"id": row.id, "name": row.name} for row in store.list_properties() if row.portfolio_id == portfolio_id]} | choices
    result = choices
    for key, model, columns in (
        ("accounts", AccountORM, (AccountORM.id, AccountORM.name, AccountORM.account_type)),
        ("categories", CategoryORM, (CategoryORM.id, CategoryORM.name, CategoryORM.category_type)),
        ("properties", PropertyORM, (PropertyORM.id, PropertyORM.name)),
    ):
        query = scoped(select(*columns).where(model.portfolio_id == portfolio_id), model, captured)
        result[key] = [dict(row) for row in db.execute(query.order_by(model.name, model.id)).mappings()]
    return result


@finance_write
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
            raise HTTPException(409, "Der Wiederholungsschlüssel gehört zu einem anderen Profilauftrag.")
        store.get_portfolio(row.portfolio_id)
        return read_profile(row)

    existing = db.scalar(select(DatevProfileORM).where(DatevProfileORM.idempotency_key == key)) if db is not None else next((row for row in memory_state(store).profiles.values() if row.idempotency_key == key), None)
    if existing:
        return replay(existing)
    if command.previous_version_id:
        previous = profile_row(store, command.previous_version_id)
        if previous.portfolio_id != command.portfolio_id:
            raise HTTPException(422, "Profilfassungen müssen zum selben Portfolio gehören.")
    for rule in command.rules:
        account = store.get_account(rule.account_id)
        category = store.get_category(rule.category_id)
        if account.portfolio_id != command.portfolio_id or category.portfolio_id != command.portfolio_id:
            raise HTTPException(422, "Konto und Kategorie müssen zum gewählten Portfolio gehören.")
        if rule.account_type != account.account_type:
            raise HTTPException(422, "Der Kontotyp wurde geändert. Bitte die Kontierung erneut prüfen.")
    values = dict(id=str(uuid4()), portfolio_id=command.portfolio_id,
        previous_version_id=command.previous_version_id, idempotency_key=key,
        actor_id=actor_id, spec_json=encoded, sha256=fingerprint,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None))
    if db is None:
        with _memory_lock:
            state = memory_state(store)
            if command.previous_version_id and any(row.previous_version_id == command.previous_version_id for row in state.profiles.values()):
                raise HTTPException(409, "DATEV-Profil wurde bereits ersetzt; aktuelle Fassung laden.")
            scope_helpers().refresh_scope(scope_helpers().current_scope())
            memory_row = SimpleNamespace(**values)
            state.profiles[memory_row.id] = memory_row
            return read_profile(memory_row)
    row = DatevProfileORM(**values)
    db.add(row)
    try:
        scope_helpers().refresh_scope(scope_helpers().current_scope())
        db.commit()
        return read_profile(row)
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(DatevProfileORM).where(DatevProfileORM.idempotency_key == key))
        if existing is None:
            raise HTTPException(409, "Die Profilfassung wurde bereits ersetzt oder gleichzeitig gespeichert. Bitte neu laden.") from None
        return replay(existing)


def entries(connection, portfolio_id, command, spec, captured, store=None):
    def evidence(identifier):
        if connection is None:
            row = store.get_booking(identifier).model_dump(mode="json")
        else:
            query = scoped(select(BookingORM.__table__).where(BookingORM.id == identifier), BookingORM, captured)
            result = connection.execute(query).mappings().first()
            if result is None:
                raise HTTPException(422, "DATEV: Der Stornoquellbeleg fehlt oder ist nicht berechtigt.")
            row = dict(result)
            row["booking_date"] = row["booking_date"].isoformat()
            row["updated_at"] = row["updated_at"].isoformat()
            row["created_at"] = row["created_at"].isoformat()
        row["amount"] = format(amount(row["amount"]), "f")
        return row
    for property_id in command.property_ids:
        if store.get_property(property_id).portfolio_id != portfolio_id:
            raise HTTPException(422, "Objektfilter gehört zu einem anderen Portfolio.")
    if connection is None:
        for year in range(command.start_date.year, command.end_date.year + 1):
            with cash_source(store, portfolio_id, year) as source:
                for row in source:
                    day = date.fromisoformat(row["booking_date"])
                    if row["status"] != "confirmed" or not command.start_date <= day <= command.end_date:
                        continue
                    if command.property_ids and row["property_id"] not in command.property_ids:
                        continue
                    account = store.get_account(row["account_id"])
                    yield Entry(id=row["id"], account_id=row["account_id"], category_id=row["category_id"],
                        account_portfolio_id=portfolio_id, category_portfolio_id=row["category_portfolio_id"],
                        account_type=account.account_type, booking_date=day, amount=row["amount"], status=row["status"],
                        updated_at=datetime.fromisoformat(row["updated_at"]), payment_text=row["payment_text"],
                        reversal_source=evidence(row["reverses_booking_id"]) if row["reverses_booking_id"] else None,
                        document_ref=row["id"] if spec["document_reference"] == "internal_booking_id" else "",
                        **{key: row[key] for key in ("receipt_url", "reverses_booking_id", "property_id", "unit_id", "tenant_id")})
        return
    account, category, booking = AccountORM.__table__, CategoryORM.__table__, BookingORM.__table__
    category_on = category.c.id == booking.c.category_id
    category_scope = scope_helpers().scoped_clause(CategoryORM, scope=captured)
    if category_scope is not None:
        category_on = and_(category_on, category_scope)
    query = select(booking.c.id, booking.c.account_id, booking.c.category_id,
        account.c.portfolio_id.label("account_portfolio_id"),
        category.c.portfolio_id.label("category_portfolio_id"), account.c.account_type,
        booking.c.booking_date, booking.c.amount,
        booking.c.status, booking.c.updated_at, booking.c.payment_text, booking.c.receipt_url, booking.c.reverses_booking_id,
        booking.c.property_id, booking.c.unit_id, booking.c.tenant_id).select_from(
        booking.join(account, account.c.id == booking.c.account_id).outerjoin(category, category_on)
    ).where(account.c.portfolio_id == portfolio_id, booking.c.status == "confirmed",
            booking.c.booking_date >= command.start_date, booking.c.booking_date <= command.end_date)
    for model in (BookingORM, AccountORM):
        query = scoped(query, model, captured)
    if command.property_ids:
        query = query.where(booking.c.property_id.in_(command.property_ids))
    predicate = scope_helpers().scoped_clause(BookingORM, scope=captured)
    if predicate is not None:
        hidden = select(1).select_from(booking.join(account, account.c.id == booking.c.account_id)).where(
            account.c.portfolio_id == portfolio_id, booking.c.status == "confirmed",
            booking.c.booking_date >= command.start_date, booking.c.booking_date <= command.end_date, ~predicate)
        if command.property_ids:
            hidden = hidden.where(booking.c.property_id.in_(command.property_ids))
        if connection.scalar(hidden.limit(1)):
            raise HTTPException(403, "DATEV: Objektbezüge erlauben keine vollständige Auswertung.")
    previous = None
    while True:
        page = query
        if previous:
            day, identifier = previous
            page = page.where((booking.c.booking_date > day) | and_(booking.c.booking_date == day, bytewise_id(booking.c.id) > identifier))
        rows = connection.execute(page.order_by(booking.c.booking_date, bytewise_id(booking.c.id))
                                  .limit(SQL_BATCH_SIZE)).mappings().all()
        if not rows:
            return
        scope_helpers().refresh_scope(captured)
        for row in rows:
            values = dict(row)
            # Full internal ID only after the profile explicitly selected it;
            # otherwise optional Belegfeld 1 remains empty, no invented invoice.
            values["document_ref"] = row["id"] if spec["document_reference"] == "internal_booking_id" else ""
            values["reversal_source"] = evidence(row["reverses_booking_id"]) if row["reverses_booking_id"] else None
            yield Entry(**values)
        previous = rows[-1]["booking_date"], rows[-1]["id"]


def owner_parts(store, command):
    """With an owner in the command: their part of each booking in the period (services.ownership)."""
    if not command.owner_contact_id:
        return None
    from .ownership import Ownership, owner_key

    ownership, key = Ownership(store), owner_key(command.owner_contact_id)
    return {booking.id: ownership.booking_split(booking).get(key) for booking in store.list_bookings()
            if command.start_date <= booking.booking_date <= command.end_date}


def owner_label(store, owner):
    from .ownership import NOBODY, owner_name

    if owner == NOBODY:
        return "Ohne Eigentümer"
    try:
        contact = store.get_contact(owner)
    except Exception:  # noqa: BLE001 - the command was validated; a later deletion keeps the id
        return "Eigentümer"
    return owner_name(contact)


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
            "rows": 0, "income": "0.00", "expense": "0.00", "files": [], "samples": [],
            **({"owner_contact_id": command.owner_contact_id, "owner_name": owner_label(store, command.owner_contact_id)}
               if command.owner_contact_id else {})}
        evidence_path = workspace / "sources.jsonl"
        evidence_output = cleanup.enter_context(evidence_path.open("xb"))
        digest, totals = hashlib.sha256(), {"income": 0, "expense": 0}
        engine = db.get_bind() if db is not None else None
        with scope_helpers().scope_context(captured), (_snapshot(engine) if engine is not None else nullcontext(None)) as connection:
            if connection is not None:
                version_query = scoped(select(DatevProfileORM.__table__).where(DatevProfileORM.id == version_id), DatevProfileORM, captured)
                frozen = connection.execute(version_query).mappings().first()
            else:
                frozen = {"sha256": profile.sha256, "spec_json": profile.spec_json}
            if frozen is None or frozen["sha256"] != profile.sha256:
                raise HTTPException(409, "Profilfassung wurde vor dem Export geändert.")
            spec = json.loads(frozen["spec_json"])
            if spec.get("portfolio_id") != portfolio_id or hashlib.sha256(canonical(spec)).hexdigest() != frozen["sha256"]:
                raise HTTPException(503, "DATEV-Profilintegrität verletzt.")
            DatevProfileCreate(**spec, idempotency_key="snapshot-validation")
            portfolio = store.get_portfolio(portfolio_id)
            if portfolio.currency != "EUR":
                raise ExportError("portfolio_currency")
            local_time = generated_at.astimezone(timezone.utc)  # Explicit UTC timestamp, also on Windows without OS tzdata.
            rules = {(r["account_id"], r["category_id"], r["flow"]): Rule(
                r["bank_gl"], r["counter_gl"], "EUR", r["no_vat_nonautomatic"], r["account_type"], r["counter_kind"])
                for r in spec["rules"]}

            parts = owner_parts(store, command)

            def observe():
                for entry in entries(connection, portfolio_id, command, spec, captured, store):
                    if parts is not None:
                        # one owner's export: their part of the booking, the booking left out without one
                        part = parts.get(entry.id)
                        if not part:
                            continue
                        entry = replace(entry, amount=format(part, "f"))
                    # The formatter validates this row before asking for the
                    # next one. Do not mask a source error as a filesystem error
                    # or accidentally report the previous booking's identifier.
                    yield entry
                    value = amount(entry.amount)
                    evidence_output.write(canonical({**asdict(entry), "amount": format(value, "f"),
                        "booking_date": entry.booking_date.isoformat(), "updated_at": entry.updated_at.isoformat()}) + b"\n")
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
                                raise HTTPException(503, f"DATEV {exc.code}: Die vollständige Exportdatei konnte nicht sicher erstellt werden.") from None
                            entry = current["entry"]
                            message = {"missing_rule": "Kontierung für diese Geldrichtung fehlt", "not_cp1252": "Zeichen ist in Windows-1252 nicht darstellbar",
                                "text_length_or_type": "Buchungstext oder Belegfeld überschreitet die zulässige Länge",
                                "formula_prefix": "Text beginnt mit einem unzulässigen Formelzeichen", "control_character": "Text enthält ein Steuerzeichen"}.get(exc.code, "Quellangaben oder Kontierung sind ungültig")
                            raise HTTPException(422, f"DATEV {exc.code}: {message}. Buchung {entry.id}; Konto {entry.account_id}; Kategorie {entry.category_id or '(fehlt)'}") from None
                if manifest["rows"] == 0:
                    raise HTTPException(422, "DATEV no_confirmed_bookings: Keine bestätigten Buchungen im gewählten Portfolio und Zeitraum.")
                manifest["source_sha256"] = digest.hexdigest()
                for flow, cents in totals.items():
                    whole, part = divmod(cents, 100)
                    manifest[flow] = f"{whole}.{part:02}"
                evidence_output.flush()
                archive.write(evidence_path, "sources.jsonl")
                info = ZipInfo("manifest.json", generated_at.timetuple()[:6])
                info.external_attr = 0o600 << 16
                archive.writestr(info, canonical(manifest))
            with ZipFile(archive_path) as verification:
                if verification.testzip() is not None:
                    raise HTTPException(503, "DATEV archive_integrity: Das vollständige Exportarchiv konnte nicht geprüft werden.")
            # Close/flush ZIP before computing its public fingerprint.
            with archive_path.open("rb") as completed_archive:
                manifest["sha256"] = hashlib.file_digest(completed_archive, "sha256").hexdigest()
            manifest["size"] = archive_path.stat().st_size
            if expected is not None and not hmac.compare_digest(manifest["sha256"], expected["sha256"]):
                raise HTTPException(409, "DATEV source_changed: Buchungen, Konten oder Kategorien haben sich seit der Vorschau geändert. Bitte eine neue Vorschau erstellen.")
            scope_helpers().refresh_scope(captured)
        return CompiledExport(archive_path, manifest, cleanup)
    except OSError:
        cleanup.close()
        raise HTTPException(503, "DATEV temporary_storage: Der vollständige Export konnte nicht geschrieben werden. Speicherplatz prüfen und erneut versuchen.") from None
    except BaseException:
        cleanup.close()
        raise


def read_export(row):
    try:
        if not hmac.compare_digest(hashlib.sha256(row.manifest_json.encode("ascii")).hexdigest(), row.manifest_sha256):
            raise ValueError()
        if not hmac.compare_digest(hashlib.sha256(row.request_json.encode("ascii")).hexdigest(), row.request_sha256):
            raise ValueError()
        manifest = json.loads(row.manifest_json)
        if (manifest["export_id"] != row.id or manifest["portfolio_id"] != row.portfolio_id
                or manifest["profile_version_id"] != row.profile_version_id):
            raise ValueError()
        return {**manifest, "id": row.id, "actor_id": row.actor_id}
    except (ValueError, TypeError, UnicodeError, KeyError):
        raise HTTPException(503, "DATEV: Integritätsprüfung der Exportquittung fehlgeschlagen.") from None


def export_row(store, export_id):
    db = database(store)
    if db is None:
        row = memory_state(store).exports.get(export_id)
        if row is None:
            raise HTTPException(404, "DATEV-Export nicht gefunden.")
        store.get_portfolio(row.portfolio_id)
        return row
    row = db.scalar(scoped(select(DatevExportORM).where(DatevExportORM.id == export_id),
                           DatevExportORM, scope_helpers().current_scope()))
    if row is None:
        raise HTTPException(404, "DATEV-Export nicht gefunden.")
    store.get_portfolio(row.portfolio_id)
    return row


@finance_write
def create_preview(store, command: DatevPreviewCreate, actor_id):
    db = database(store)
    profile = profile_row(store, command.profile_version_id)
    key = actor_id + ":" + command.idempotency_key
    if command.owner_contact_id and command.owner_contact_id != "none":
        from .ownership import require_owner
        require_owner(store, command.owner_contact_id, "Der Eigentümer des Exports")
    # without an owner the request reads as before, so earlier repeat keys still match
    omitted = {"idempotency_key"} | (set() if command.owner_contact_id else {"owner_contact_id"})
    request_json = canonical(command.model_dump(mode="json", exclude=omitted)).decode("ascii")

    def replay(row):
        if row.request_json != request_json:
            raise HTTPException(409, "Der Wiederholungsschlüssel gehört zu einem anderen Zeitraum oder Profil.")
        store.get_portfolio(row.portfolio_id)
        return read_export(row)

    existing = db.scalar(select(DatevExportORM).where(DatevExportORM.idempotency_key == key)) if db is not None else next((row for row in memory_state(store).exports.values() if row.idempotency_key == key), None)
    if existing:
        return replay(existing)
    identifier, generated = str(uuid4()), datetime.now(timezone.utc).replace(microsecond=0)
    compiled = compile_export(store, command, profile.id, identifier, generated)
    try:
        values = dict(id=identifier, portfolio_id=profile.portfolio_id,
            profile_version_id=profile.id, idempotency_key=key, actor_id=actor_id,
            request_json=request_json, manifest_json=canonical(compiled.manifest).decode("ascii"),
            manifest_sha256=hashlib.sha256(canonical(compiled.manifest)).hexdigest(),
            request_sha256=hashlib.sha256(request_json.encode("ascii")).hexdigest(),
            created_at=generated.replace(tzinfo=None))
        row = DatevExportORM(**values) if db is not None else SimpleNamespace(**values)
        if db is not None:
            db.add(row)
            db.flush()
        memory_blocks = []
        with compiled.path.open("rb") as source:
            sequence = 0
            while chunk := source.read(64 * 1024):
                sequence += 1
                block = dict(id=str(uuid4()), portfolio_id=row.portfolio_id, export_id=row.id,
                    sequence_number=sequence, token=default_secret_box().seal(base64.b64encode(chunk).decode("ascii"),
                        f"datev:{row.id}:{sequence}"))
                if db is not None:
                    db.add(DatevBlockORM(**block))
                else:
                    memory_blocks.append(SimpleNamespace(**block))
                if db is not None and sequence % 16 == 0:
                    db.flush()
        scope_helpers().refresh_scope(scope_helpers().current_scope())
        if db is None:
            state = memory_state(store)
            state.exports[row.id] = row
            state.blocks[row.id] = memory_blocks
            return read_export(row)
        try:
            db.commit()
            return read_export(row)
        except IntegrityError:
            db.rollback()
            existing = db.scalar(select(DatevExportORM).where(DatevExportORM.idempotency_key == key))
            if existing is None:
                raise HTTPException(409, "Der Export konnte nicht gespeichert werden. Bitte die Vorschau erneut erstellen.") from None
            return replay(existing)
    finally:
        compiled.close()


def list_exports(store, portfolio_id, offset=0, limit=100):
    store.get_portfolio(portfolio_id)
    db = database(store)
    if db is None:
        rows = sorted((row for row in memory_state(store).exports.values() if row.portfolio_id == portfolio_id),
            key=lambda row: (row.created_at, row.id), reverse=True)
        return {"total": len(rows), "items": [read_export(row) for row in rows[offset:offset + limit]]}
    query = scoped(select(DatevExportORM).where(DatevExportORM.portfolio_id == portfolio_id),
                   DatevExportORM, scope_helpers().current_scope())
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(DatevExportORM.created_at.desc(), DatevExportORM.id.desc())
                      .offset(offset).limit(limit)).all()
    return {"total": total, "items": [read_export(row) for row in rows]}


def prepare_saved_download(store, export_id):
    row = export_row(store, export_id)
    manifest = read_export(row)
    cleanup = ExitStack()
    try:
        workspace, _ = cleanup.enter_context(private_workspace())
        path = workspace / "datev.zip"
        digest, size, after = hashlib.sha256(), 0, 0
        with path.open("xb") as output:
            while True:
                blocks = store.db.scalars(select(DatevBlockORM).where(DatevBlockORM.export_id == row.id,
                    DatevBlockORM.sequence_number > after).order_by(DatevBlockORM.sequence_number).limit(16)).all() if hasattr(store, "db") else [block for block in memory_state(store).blocks.get(row.id, []) if block.sequence_number > after][:16]
                if not blocks:
                    break
                for block in blocks:
                    if block.sequence_number != after + 1:
                        raise ValueError("sequence")
                    chunk = base64.b64decode(default_secret_box().open(block.token, f"datev:{row.id}:{block.sequence_number}"), validate=True)
                    digest.update(chunk)
                    size += len(chunk)
                    output.write(chunk)
                    after = block.sequence_number
                scope_helpers().refresh_scope(scope_helpers().current_scope())
        if size != manifest["size"] or not hmac.compare_digest(digest.hexdigest(), manifest["sha256"]):
            raise ValueError("hash")
        with ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ValueError("zip")
            from .tax_support import check_saved_booking
            with archive.open("sources.jsonl") as sources:
                for line in sources:
                    check_saved_booking(store, json.loads(line)["id"])
        scope_helpers().refresh_scope(scope_helpers().current_scope())
        return CompiledExport(path, manifest, cleanup)
    except (ValueError, SecretError, OSError):
        cleanup.close()
        raise HTTPException(503, "DATEV: Gesicherte Exportbytes fehlen oder sind beschädigt; Vollbackup und Schlüssel prüfen.") from None
    except BaseException:
        cleanup.close()
        raise



def memory_state(store):
    return object.__getattribute__(store, "__dict__").setdefault("_datev_state", SimpleNamespace(profiles={}, exports={}, blocks={}))
