"""Atomic immutable profile/projection versions with retained source evidence."""

import hashlib
import hmac
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Table, func, inspect, select
from sqlalchemy.exc import IntegrityError

from ..db.orm_models import AccountORM, CategoryORM, PropertyORM
from ..db.tax_models import AnnualTaxProfileORM, AnnualTaxProjectionORM, AnnualTaxSourceORM
from .annual_tax_projection import canonical, compile_projection, fingerprint
from .annual_tax_source import BATCH_SIZE
from .payments import _memory_lock
from .portfolio_scope import current_scope, refresh_scope


def memory_state(store):
    raw = object.__getattribute__(store, "__dict__")
    with _memory_lock:
        return raw.setdefault("_annual_tax_state", SimpleNamespace(profiles={}, projections={}, sources={}))


def guard_destructive_reset(store):
    """Keep reviewed evidence before resets/imports can change its live parents."""
    if hasattr(store, "db"):
        tables = (AnnualTaxProfileORM, AnnualTaxProjectionORM, AnnualTaxSourceORM)
        existing = set(inspect(store.db.connection()).get_table_names())
        found = any(store.db.scalar(select(model.id).limit(1)) for model in tables if model.__tablename__ in existing)
    else:
        state = object.__getattribute__(store, "__dict__").get("_annual_tax_state")
        found = state is not None and any((state.profiles, state.projections, state.sources))
    if found:
        raise ValueError("Gesicherte Steuerzuordnungen/Jahresbelege dürfen nicht durch Zurücksetzen oder Teilimport ersetzt werden. Eine vollständige Datenbanksicherung mit Quellen verwenden und separat wiederherstellen.")


def options(store, portfolio_id):
    store.get_portfolio(portfolio_id)
    definitions = (("accounts", AccountORM, "name"), ("categories", CategoryORM, "name"), ("properties", PropertyORM, "name"))
    if hasattr(store, "db"):
        return {key: [dict(row) for row in store.db.execute(select(model.id, getattr(model, label).label("name"))
            .where(model.portfolio_id == portfolio_id).order_by(getattr(model, label), model.id)).mappings()]
            for key, model, label in definitions}
    return {key: [{"id": row.id, "name": row.name} for row in getattr(store, "list_" + key)() if row.portfolio_id == portfolio_id]
        for key, _, _ in definitions}


def read_profile(row):
    spec = verified_json(row.spec_json, row.sha256, "profile")
    return {"id": row.id, "portfolio_id": row.portfolio_id, "tax_year": row.tax_year,
        "previous_version_id": row.previous_version_id, "actor_id": row.actor_id,
        "spec": spec, "sha256": row.sha256, "created_at": row.created_at.isoformat()}


def verified_json(encoded, expected, kind):
    try:
        value = json.loads(encoded)
        valid = isinstance(value, dict) and hmac.compare_digest(fingerprint(value), expected)
    except (ValueError, TypeError, UnicodeError):
        valid = False
    if not valid:
        raise HTTPException(503, f"annual_tax_saved_{kind}_integrity_failed")
    return value


def get_profile(store, identifier):
    row = store.db.scalar(select(AnnualTaxProfileORM).where(AnnualTaxProfileORM.id == identifier)) if hasattr(store, "db") else memory_state(store).profiles.get(identifier)
    if row is None:
        raise HTTPException(404, "annual_tax_profile_not_found")
    store.get_portfolio(row.portfolio_id)
    return read_profile(row)


def list_profiles(store, portfolio_id, tax_year=None, offset=0, limit=100):
    store.get_portfolio(portfolio_id)
    if hasattr(store, "db"):
        query = select(AnnualTaxProfileORM).where(AnnualTaxProfileORM.portfolio_id == portfolio_id)
        if tax_year is not None:
            query = query.where(AnnualTaxProfileORM.tax_year == tax_year)
        total = store.db.scalar(select(func.count()).select_from(query.subquery()))
        rows = store.db.scalars(query.order_by(AnnualTaxProfileORM.created_at.desc(), AnnualTaxProfileORM.id.desc()).offset(offset).limit(limit)).all()
    else:
        rows = [row for row in memory_state(store).profiles.values() if row.portfolio_id == portfolio_id and (tax_year is None or row.tax_year == tax_year)]
        rows.sort(key=lambda row: (row.created_at, row.id), reverse=True)
        total, rows = len(rows), rows[offset:offset + limit]
    return {"total": total, "items": [read_profile(row) for row in rows]}


def create_profile(store, command, actor_id):
    portfolio = store.get_portfolio(command.portfolio_id)
    if portfolio.currency != command.currency:
        raise HTTPException(422, "annual_tax_currency: Das Portfolio muss ausdrücklich EUR verwenden.")
    for rule in command.rules:
        if store.get_account(rule.account_id).portfolio_id != command.portfolio_id:
            raise HTTPException(422, "annual_tax_mapping_account_portfolio")
        if rule.category_id and store.get_category(rule.category_id).portfolio_id != command.portfolio_id:
            raise HTTPException(422, "annual_tax_mapping_category_portfolio")
    if command.previous_version_id:
        previous = get_profile(store, command.previous_version_id)
        if (previous["portfolio_id"], previous["tax_year"]) != (command.portfolio_id, command.tax_year):
            raise HTTPException(422, "annual_tax_profile_revision_year_portfolio")
    spec = command.model_dump(mode="json", exclude={"idempotency_key", "previous_version_id"})
    encoded, key = canonical(spec).decode("ascii"), actor_id + ":" + command.idempotency_key
    digest = fingerprint(spec)

    def replay(row):
        store.get_portfolio(row.portfolio_id)
        if row.sha256 != digest or row.previous_version_id != command.previous_version_id:
            raise HTTPException(409, "annual_tax_profile_idempotency_conflict")
        return read_profile(row)

    values = dict(id=str(uuid4()), portfolio_id=command.portfolio_id, tax_year=command.tax_year,
        previous_version_id=command.previous_version_id, actor_id=actor_id, idempotency_key=key,
        spec_json=encoded, sha256=digest, created_at=datetime.now(timezone.utc).replace(tzinfo=None))
    if not hasattr(store, "db"):
        with _memory_lock:
            state = memory_state(store)
            old = next((row for row in state.profiles.values() if row.idempotency_key == key), None)
            if old:
                return replay(old)
            refresh_scope(current_scope())
            memory_row = SimpleNamespace(**values)
            state.profiles[memory_row.id] = memory_row
            return read_profile(memory_row)
    db = store.db
    old = db.scalar(select(AnnualTaxProfileORM).where(AnnualTaxProfileORM.idempotency_key == key))
    if old:
        return replay(old)
    row = AnnualTaxProfileORM(**values)
    try:
        db.add(row)
        refresh_scope(current_scope())
        db.commit()
        return read_profile(row)
    except IntegrityError:
        db.rollback()
        old = db.scalar(select(AnnualTaxProfileORM).where(AnnualTaxProfileORM.idempotency_key == key))
        if old:
            return replay(old)
        raise HTTPException(409, "annual_tax_profile_save_conflict") from None
    except BaseException:
        db.rollback()
        raise


def preflight(store, command):
    compiled = compile_projection(store, get_profile(store, command.profile_version_id), command)
    try:
        return compiled.manifest
    finally:
        compiled.close()


def read_projection(row):
    manifest = verified_json(row.manifest_json, row.manifest_sha256, "manifest")
    try:
        request = json.loads(row.request_json)
        reviewed = {key: value for key, value in request.items() if key not in {"preview_hash", "previous_projection_id", "revision_reason"}}
        expected = fingerprint({"profile": manifest["profile_sha256"], "source": manifest["source_sha256"],
            "request": reviewed, "totals": manifest["totals"], "groups": manifest["groups"], "issues": manifest["blocking_issue_counts"]})
        valid = hmac.compare_digest(expected, manifest["preview_hash"]) and request["preview_hash"] == expected
    except (ValueError, TypeError, AttributeError, KeyError, UnicodeError):
        valid = False
    if not valid:
        raise HTTPException(503, "annual_tax_saved_request_integrity_failed")
    return {"id": row.id, "actor_id": row.actor_id, "previous_projection_id": row.previous_projection_id,
        **manifest, "review_request": reviewed}


def projection_row(store, identifier):
    row = store.db.scalar(select(AnnualTaxProjectionORM).where(AnnualTaxProjectionORM.id == identifier)) if hasattr(store, "db") else memory_state(store).projections.get(identifier)
    if row is None:
        raise HTTPException(404, "annual_tax_projection_not_found")
    store.get_portfolio(row.portfolio_id)
    return row


def list_projections(store, portfolio_id, tax_year=None, offset=0, limit=100):
    store.get_portfolio(portfolio_id)
    if hasattr(store, "db"):
        query = select(AnnualTaxProjectionORM).where(AnnualTaxProjectionORM.portfolio_id == portfolio_id)
        if tax_year is not None:
            query = query.where(AnnualTaxProjectionORM.tax_year == tax_year)
        total = store.db.scalar(select(func.count()).select_from(query.subquery()))
        rows = store.db.scalars(query.order_by(AnnualTaxProjectionORM.created_at.desc(), AnnualTaxProjectionORM.id.desc()).offset(offset).limit(limit)).all()
    else:
        rows = [row for row in memory_state(store).projections.values() if row.portfolio_id == portfolio_id and (tax_year is None or row.tax_year == tax_year)]
        rows.sort(key=lambda row: (row.created_at, row.id), reverse=True)
        total, rows = len(rows), rows[offset:offset + limit]
    return {"total": total, "items": [read_projection(row) for row in rows]}


def create_projection(store, command, actor_id):
    key = actor_id + ":" + command.idempotency_key
    request = canonical(command.model_dump(mode="json", exclude={"idempotency_key"})).decode("ascii")

    def existing():
        if hasattr(store, "db"):
            return store.db.scalar(select(AnnualTaxProjectionORM).where(AnnualTaxProjectionORM.idempotency_key == key))
        return next((row for row in memory_state(store).projections.values() if row.idempotency_key == key), None)

    def replay(row):
        store.get_portfolio(row.portfolio_id)
        if row.request_json != request:
            raise HTTPException(409, "annual_tax_projection_idempotency_conflict")
        return read_projection(row)

    if old := existing():
        return replay(old)
    profile = get_profile(store, command.profile_version_id)
    previous = read_projection(projection_row(store, command.previous_projection_id)) if command.previous_projection_id else None
    if previous and (previous["portfolio_id"], previous["tax_year"]) != (profile["portfolio_id"], profile["tax_year"]):
        raise HTTPException(422, "annual_tax_projection_revision_year_portfolio")
    compiled = compile_projection(store, profile, command)
    try:
        manifest = compiled.manifest
        if not manifest["ready"]:
            raise HTTPException(422, {"code": "annual_tax_preflight_blocked", "issues": manifest["blocking_issue_counts"]})
        if not hmac.compare_digest(manifest["preview_hash"], command.preview_hash):
            raise HTTPException(409, "annual_tax_source_changed: Die Vorprüfung erneut ansehen und bestätigen.")
        manifest = {**manifest, "revision_number": previous["revision_number"] + 1 if previous else 1,
            "revision_reason": command.revision_reason, "immutable": True,
            "revision_delta_cents": {key: str(int(value) - int(previous["totals"][key])) for key, value in manifest["totals"].items()} if previous else None}
        identifier = str(uuid4())
        values = dict(id=identifier, portfolio_id=profile["portfolio_id"], tax_year=profile["tax_year"],
            profile_version_id=profile["id"], previous_projection_id=command.previous_projection_id,
            annual_root_key=None if previous else f"{profile['portfolio_id']}:{profile['tax_year']}",
            idempotency_key=key, actor_id=actor_id, request_json=request,
            manifest_json=canonical(manifest).decode("ascii"), manifest_sha256=fingerprint(manifest),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None))

        def rows():
            with compiled.sources.open("rb") as source:
                for sequence, line in enumerate(source, 1):
                    record = json.loads(line)
                    yield dict(id=str(uuid4()), portfolio_id=profile["portfolio_id"], projection_id=identifier,
                        booking_id=record["booking"]["id"], sequence_number=sequence,
                        source_json=line.rstrip(b"\n").decode("ascii"), sha256=hashlib.sha256(line.rstrip(b"\n")).hexdigest())
        if not hasattr(store, "db"):
            with _memory_lock:
                state = memory_state(store)
                if old := existing():
                    return replay(old)
                if any(row.annual_root_key == values["annual_root_key"] for row in state.projections.values() if values["annual_root_key"]) or any(row.previous_projection_id == command.previous_projection_id for row in state.projections.values() if previous):
                    raise HTTPException(409, "annual_tax_revision_exists: Die letzte Jahresfassung laden und ausdrücklich revidieren.")
                evidence = [SimpleNamespace(**row) for row in rows()]
                refresh_scope(current_scope())
                memory_row = SimpleNamespace(**values)
                state.projections[identifier] = memory_row
                state.sources[identifier] = evidence
                return read_projection(memory_row)
        db = store.db
        row = AnnualTaxProjectionORM(**values)
        try:
            db.add(row)
            db.flush()
            batch = []
            for source in rows():
                batch.append(source)
                if len(batch) == BATCH_SIZE:
                    db.execute(cast(Table, AnnualTaxSourceORM.__table__).insert(), batch)
                    batch = []
                    refresh_scope(current_scope())
            if batch:
                db.execute(cast(Table, AnnualTaxSourceORM.__table__).insert(), batch)
            refresh_scope(current_scope())
            db.commit()
            return read_projection(row)
        except IntegrityError:
            db.rollback()
            if old := existing():
                return replay(old)
            raise HTTPException(409, "annual_tax_revision_exists: Die letzte Jahresfassung laden und ausdrücklich revidieren.") from None
        except BaseException:
            db.rollback()
            raise
    finally:
        compiled.close()


def saved_sources(store, projection_id):
    row = projection_row(store, projection_id)
    captured, digest = current_scope(), hashlib.sha256()
    if hasattr(store, "db"):
        after = 0
        while True:
            rows = store.db.scalars(select(AnnualTaxSourceORM).where(AnnualTaxSourceORM.projection_id == projection_id,
                AnnualTaxSourceORM.sequence_number > after).order_by(AnnualTaxSourceORM.sequence_number).limit(BATCH_SIZE)).all()
            if not rows:
                break
            refresh_scope(captured)
            for source in rows:
                record = verified_json(source.source_json, source.sha256, "evidence")
                encoded = source.source_json.encode("ascii") + b"\n"
                digest.update(encoded)
                yield record
            after = rows[-1].sequence_number
    else:
        for source in memory_state(store).sources.get(projection_id, []):
            record = verified_json(source.source_json, source.sha256, "evidence")
            encoded = source.source_json.encode("ascii") + b"\n"
            digest.update(encoded)
            yield record
    if not hmac.compare_digest(digest.hexdigest(), read_projection(row)["source_sha256"]):
        raise HTTPException(503, "annual_tax_saved_evidence_incomplete")
    refresh_scope(captured)
