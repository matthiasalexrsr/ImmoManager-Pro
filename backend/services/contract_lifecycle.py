"""Manual review/confirm commands; one transaction, original contracts preserved."""

import base64
import hashlib
import json
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from datetime import date, datetime, timezone
from heapq import nlargest
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .. import auth
from ..db.contract_lifecycle_models import LIFECYCLE_MODELS, ContractLifecycleCommandORM, ContractLifecycleDraftORM
from ..db.orm_models import ContractORM, ReceivableORM, RentChargeORM
from ..models import ContractCreate, ContractPatch
from ..permissions import may_write_resource
from ..storage import NotFoundError, ValidationError
from .concurrency import etag, next_updated_at, parse_revision, revision_scope
from .contract_lifecycle_types import DraftCreate, DraftEdit, RenewalData, TerminationData
from .contract_lifecycle_validation import (
    JournalValidationError,
    validate_command_evidence,
    validate_draft_evidence,
    validate_supersession_evidence,
)
from .contract_occupancy import assert_occupancy, begin_writer, lock_location
from .payments import _memory_lock
from .portfolio_scope import current_scope, refresh_scope, scope_context, scope_from_user

FINAL_STATES = frozenset({"confirmed", "pending_effective", "completed", "superseded"})
_lifecycle_parent: ContextVar[str | None] = ContextVar("immo_confirmed_lifecycle_parent", default=None)


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today() -> date:
    """Explicit server UTC day; end dates are inclusive, no automatic timer."""
    return datetime.now(timezone.utc).date()


def packed(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(packed(value).encode("utf-8")).hexdigest()


def conflict(message: str = "Der Stand wurde geändert. Entwurf erneut laden und prüfen.") -> HTTPException:
    return HTTPException(409, message)


def identity(actor_id: str, *, write: bool = False):
    user = auth.get_user_by_id(actor_id)
    if not user or not user["is_active"]:
        raise HTTPException(401, "Anmeldung nicht mehr gültig.")
    if write and not may_write_resource(user["role"], "contracts"):
        raise HTTPException(403, "Keine Berechtigung zur Vertragsverwaltung.")
    captured = current_scope()
    if captured is not None and captured.user_id != actor_id:
        raise HTTPException(403, "Ungültige Benutzerbindung.")
    return refresh_scope(captured) if captured is not None else scope_from_user(user)


class Work:
    def __init__(self, store, db, captured):
        self.store, self.db, self.captured = store, db, captured
        # Undo ONLY rows this command writes, never copy a 20-year collection.
        self.undo: dict[tuple[str, str], tuple[bool, Any]] = {}

    def touch(self, collection: str, identifier: str, *, inserted: bool = False) -> None:
        if self.db is None and (collection, identifier) not in self.undo:
            rows = self.store.__dict__.setdefault(collection, {})
            self.undo[collection, identifier] = (identifier in rows and not inserted,
                                               deepcopy(rows.get(identifier)) if not inserted else None)

    def add(self, row) -> None:
        if self.db is not None:
            self.db.add(row)
            self.db.flush()
        else:
            self.touch(row.__tablename__, row.id, inserted=True)
            self.store.__dict__[row.__tablename__][row.id] = row

    def rollback(self) -> None:
        for (collection, identifier), (present, value) in reversed(list(self.undo.items())):
            if present:
                self.store.__dict__[collection][identifier] = value
            else:
                self.store.__dict__[collection].pop(identifier, None)


@contextmanager
def work(store, actor_id: str, *, write: bool = False):
    captured = identity(actor_id, write=write)
    sql = hasattr(store, "db")
    with scope_context(captured), nullcontext() if sql else _memory_lock:
        if sql:
            from ..repositories.sql_store import SQLAlchemyStore
            bind = store.db.get_bind()
            # A Connection-bound caller also gets a separate owned transaction.
            db = Session(getattr(bind, "engine", bind), autoflush=False, expire_on_commit=False)
            active = SQLAlchemyStore(db)
        else:
            db, active = None, store
            for model in LIFECYCLE_MODELS:
                store.__dict__.setdefault(model.__tablename__, {})
        unit = Work(active, db, captured)
        try:
            if db is not None and write:
                begin_writer(db)
            yield unit
            refresh_scope(captured)
            if db is not None and write:
                db.commit()
        except BaseException:
            if db is not None:
                db.rollback()
            else:
                unit.rollback()
            raise
        finally:
            if db is not None:
                db.close()


def parent(unit: Work, contract_id: str, *, lock: bool = False):
    contract = unit.store.get_contract(contract_id)
    if lock:
        lock_location(unit.store, contract.property_id, contract.unit_id)
        if unit.db is not None:
            if unit.db.scalar(select(ContractORM.id).where(ContractORM.id == contract_id).with_for_update()) is None:
                raise NotFoundError("Vertrag nicht gefunden")
            contract = unit.store.get_contract(contract_id)
    property = unit.store.get_property(contract.property_id)
    location = unit.store.get_unit(contract.unit_id)
    unit.store.get_portfolio(property.portfolio_id)
    unit.store.get_tenant(contract.tenant_id)
    if location.property_id != property.id:
        raise HTTPException(503, "Widersprüchliche Vertragszuordnung. Bestand prüfen.")
    _complete_subject(unit, contract, property.portfolio_id)
    return contract, property


def _complete_subject(unit: Work, contract, portfolio_id: str) -> None:
    """Only a bool under an already freshly authorized exact parent.

    Do not silently omit a corrupt hidden journal. No foreign IDs, JSON or other
    portfolio records cross the Core connection boundary.
    """
    if unit.db is not None:
        drafts: Any = ContractLifecycleDraftORM.__table__
        commands: Any = ContractLifecycleCommandORM.__table__
        bad_draft = select(drafts.c.id).where(drafts.c.contract_id == contract.id, or_(
            drafts.c.portfolio_id != portfolio_id, drafts.c.property_id != contract.property_id,
            drafts.c.unit_id != contract.unit_id, drafts.c.tenant_id != contract.tenant_id))
        bad_command = select(commands.c.id).select_from(commands.outerjoin(drafts, drafts.c.id == commands.c.draft_id)).where(
            commands.c.contract_id == contract.id, or_(commands.c.portfolio_id != portfolio_id,
                drafts.c.id.is_(None), drafts.c.contract_id != contract.id, drafts.c.portfolio_id != portfolio_id))
        connection = unit.db.connection()
        bad = bool(connection.scalar(select(bad_draft.exists()))) or bool(connection.scalar(select(bad_command.exists())))
        leaf = select(drafts.c.id).where(drafts.c.contract_id == contract.id,
            drafts.c.state.in_(("pending_effective", "completed")), or_(
                drafts.c.data["termination_end_date"].as_string().is_(None),
                drafts.c.data["termination_end_date"].as_string() != (
                    contract.end_date.isoformat() if contract.end_date is not None else ""),
                and_(drafts.c.state == "pending_effective", contract.status != "active"),
                and_(drafts.c.state == "completed", contract.status != "terminated")))
        bad = bad or bool(connection.scalar(select(leaf.exists())))
        other = drafts.alias()
        duplicate = select(drafts.c.id).select_from(drafts.join(other,
            and_(other.c.contract_id == drafts.c.contract_id, other.c.id != drafts.c.id))).where(
            drafts.c.contract_id == contract.id, drafts.c.state.in_(("pending_effective", "completed")),
            other.c.state.in_(("pending_effective", "completed")))
        bad = bad or bool(connection.scalar(select(duplicate.exists())))
        for field, backwards in (("supersedes_draft_id", False), ("superseded_by_draft_id", True)):
            linked = drafts.alias()
            mismatched = or_(linked.c.id.is_(None), linked.c.contract_id != contract.id,
                linked.c.portfolio_id != portfolio_id, linked.c.property_id != contract.property_id,
                linked.c.unit_id != contract.unit_id, linked.c.tenant_id != contract.tenant_id)
            if backwards:
                mismatched = or_(mismatched, linked.c.supersedes_draft_id.is_(None),
                    linked.c.supersedes_draft_id != drafts.c.id, ~linked.c.state.in_(FINAL_STATES))
            else:
                mismatched = or_(mismatched, and_(drafts.c.state.in_(FINAL_STATES), or_(
                    linked.c.state != "superseded", linked.c.superseded_by_draft_id.is_(None),
                    linked.c.superseded_by_draft_id != drafts.c.id)))
            bad_link = select(drafts.c.id).select_from(drafts.outerjoin(linked,
                linked.c.id == drafts.c[field])).where(drafts.c.contract_id == contract.id,
                drafts.c[field].is_not(None), mismatched)
            bad = bad or bool(connection.scalar(select(bad_link.exists())))
    else:
        rows = unit.store.__dict__.get(ContractLifecycleDraftORM.__tablename__, {})
        bad = any(row.contract_id == contract.id and (row.portfolio_id, row.property_id, row.unit_id, row.tenant_id)
            != (portfolio_id, contract.property_id, contract.unit_id, contract.tenant_id) for row in rows.values())
        if not bad:
            bad = any(row.contract_id == contract.id and (row.portfolio_id != portfolio_id
                or row.draft_id not in rows or rows[row.draft_id].contract_id != contract.id
                or rows[row.draft_id].portfolio_id != portfolio_id)
                for row in unit.store.__dict__.get(ContractLifecycleCommandORM.__tablename__, {}).values())
        if not bad:
            leaves = 0
            for row in rows.values():
                if row.contract_id != contract.id:
                    continue
                if row.state in {"pending_effective", "completed"}:
                    leaves += 1
                    bad |= row.data.get("termination_end_date") != (
                        contract.end_date.isoformat() if contract.end_date is not None else "")
                    bad |= contract.status != ("active" if row.state == "pending_effective" else "terminated")
                for field, backwards in (("supersedes_draft_id", False), ("superseded_by_draft_id", True)):
                    identifier = getattr(row, field)
                    if identifier is None:
                        continue
                    linked = rows.get(identifier)
                    if linked is None or (linked.contract_id, linked.portfolio_id, linked.property_id,
                            linked.unit_id, linked.tenant_id) != (contract.id, portfolio_id,
                            contract.property_id, contract.unit_id, contract.tenant_id):
                        bad = True
                    elif backwards:
                        bad |= linked.state not in FINAL_STATES or linked.supersedes_draft_id != row.id
                    elif row.state in FINAL_STATES:
                        bad |= linked.state != "superseded" or linked.superseded_by_draft_id != row.id
            bad |= leaves > 1
    if bad:
        raise HTTPException(503, "Vertragsjournal enthält widersprüchliche Zuordnungen. Bestand prüfen.")


def source_match(contract, supplied: str) -> None:
    revision = parse_revision(supplied)
    if revision.collection != "contracts" or revision.entity_id != contract.id or supplied != contract_etag(contract):
        raise HTTPException(412, "Vertrag wurde geändert. Aktuellen Stand laden und neu prüfen.")


def contract_etag(contract) -> str:
    return etag("contracts", contract.id, contract.updated_at)


def month_of(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _load(unit: Work, contract, property, draft_id: str, actor_id: str, *, mutate: bool = False,
          finalize: bool = False):
    if unit.db is not None:
        query = select(ContractLifecycleDraftORM).where(ContractLifecycleDraftORM.id == draft_id,
                                                       ContractLifecycleDraftORM.contract_id == contract.id)
        row = unit.db.scalar(query.with_for_update() if mutate else query)
    else:
        row = unit.store.__dict__[ContractLifecycleDraftORM.__tablename__].get(draft_id)
    if row is None or row.contract_id != contract.id:
        raise HTTPException(404, "Vertragsvorgang nicht gefunden.")
    if (row.actor_id != actor_id and row.state not in FINAL_STATES) or (mutate and not finalize and row.actor_id != actor_id):
        raise HTTPException(404, "Eigener Vertragsentwurf nicht gefunden.")
    if (row.portfolio_id, row.property_id, row.unit_id, row.tenant_id) != (
            property.portfolio_id, contract.property_id, contract.unit_id, contract.tenant_id):
        raise HTTPException(503, "Historische Vertragsbindung ist widersprüchlich. Bestand prüfen.")
    _validate_stored(row)
    _validate_links(unit, row)
    return row


def _validate_stored(row) -> None:
    try:
        validate_draft_evidence(row)
    except JournalValidationError:
        raise HTTPException(503, "Gespeicherter Vertragsprüfstand ist widersprüchlich. Wiederherstellung prüfen.") from None


def _validate_links(unit: Work, row) -> None:
    def linked(identifier):
        if unit.db is not None:
            return unit.db.scalar(select(ContractLifecycleDraftORM).where(
                ContractLifecycleDraftORM.id == identifier, ContractLifecycleDraftORM.contract_id == row.contract_id))
        return unit.store.__dict__[ContractLifecycleDraftORM.__tablename__].get(identifier)
    try:
        if row.supersedes_draft_id is not None:
            previous = linked(row.supersedes_draft_id)
            if previous is None:
                raise JournalValidationError("Missing predecessor")
            validate_supersession_evidence(row, previous)
        if row.superseded_by_draft_id is not None:
            following = linked(row.superseded_by_draft_id)
            if following is None:
                raise JournalValidationError("Missing successor")
            validate_draft_evidence(following)
            validate_supersession_evidence(following, row)
    except JournalValidationError:
        raise HTTPException(503, "Gespeicherte Ablösungsbeziehung ist widersprüchlich. Wiederherstellung prüfen.") from None


def public(row, *, persistent: bool) -> dict:
    fields = ("id", "contract_id", "portfolio_id", "property_id", "unit_id", "tenant_id", "actor_id",
              "revision", "state", "data", "source_contract_etag", "review", "review_hash",
              "applied_contract_etag", "finalized_contract_etag", "successor_contract_id",
              "supersedes_draft_id", "superseded_by_draft_id")
    result = {key: deepcopy(getattr(row, key)) for key in fields}
    result.update(created_at=row.created_at.replace(tzinfo=timezone.utc).isoformat(),
                  updated_at=row.updated_at.replace(tzinfo=timezone.utc).isoformat(), persistent=persistent)
    return result


def _replay(unit: Work, contract_id: str, draft_id: str | None, actor_id: str, key: str, request_hash: str):
    if unit.db is not None:
        command = unit.db.scalar(select(ContractLifecycleCommandORM).where(
            ContractLifecycleCommandORM.actor_id == actor_id, ContractLifecycleCommandORM.command_key == key).limit(1))
    else:
        command = next((row for row in unit.store.__dict__[ContractLifecycleCommandORM.__tablename__].values()
                        if row.actor_id == actor_id and row.command_key == key), None)
    if command is not None:
        if command.contract_id != contract_id or (draft_id is not None and command.draft_id != draft_id) or command.request_hash != request_hash:
            raise conflict("Diese Vorgangsreferenz wurde bereits mit anderen Eingaben verwendet.")
        contract, property = parent(unit, contract_id)
        row = _load(unit, contract, property, command.draft_id, actor_id)
        _validate_command(command, row)
        return deepcopy(command.result)
    return None


def _record(unit: Work, row, actor_id: str, payload, operation: str) -> dict:
    if unit.db is not None:
        unit.db.flush()
    result = public(row, persistent=unit.db is not None)
    unit.add(ContractLifecycleCommandORM(id=str(uuid4()), portfolio_id=row.portfolio_id, contract_id=row.contract_id,
        draft_id=row.id, actor_id=actor_id, command_key=payload.idempotency_key, operation=operation,
        request=payload.model_dump(mode="json"),
        request_hash=digest({"operation": operation, "payload": payload.model_dump(mode="json")}),
        result=result, created_at=now()))
    return result


def _validate_command(command, draft) -> None:
    try:
        validate_command_evidence(command, draft)
    except JournalValidationError:
        raise HTTPException(503, "Gespeichertes Vertragsjournal ist widersprüchlich. Wiederherstellung prüfen.") from None


def _change(unit: Work, row) -> None:
    unit.touch(row.__tablename__, row.id)
    row.revision, row.updated_at = str(uuid4()), next_updated_at(row.updated_at).replace(tzinfo=None)


def _revision(row, payload) -> None:
    if row.revision != str(payload.expected_revision):
        raise conflict("Der Vertragsentwurf wurde geändert. Aktuellen Entwurf laden.")


def _successor_data(contract, data: RenewalData) -> ContractCreate:
    if contract.status not in {"active", "terminated", "expired"} or contract.end_date is None:
        raise conflict("Eine Verlängerung benötigt einen bestehenden Vertrag mit ausdrücklich festgelegtem Mietende.")
    if data.new_start_date <= contract.end_date:
        raise conflict("Der Folgevertrag muss nach dem inklusiven Mietende des Altvertrags beginnen.")
    return ContractCreate(contract_number=data.new_contract_number, property_id=contract.property_id,
        unit_id=contract.unit_id, tenant_id=contract.tenant_id, status="active", start_date=data.new_start_date,
        end_date=data.new_end_date)


def _validate(unit: Work, contract, data):
    if isinstance(data, RenewalData):
        successor = _successor_data(contract, data)
        if unit.store.get_tenant(contract.tenant_id).archived:
            raise conflict("Archivierten Mieter vor einem neuen Mietverhältnis ausdrücklich prüfen.")
        if unit.db is not None:
            exists = unit.db.scalar(select(ContractORM.id).where(
                ContractORM.contract_number == data.new_contract_number).limit(1)) is not None
        else:
            exists = any(c.contract_number == data.new_contract_number for c in unit.store.contracts.values())
        if exists:
            raise conflict("Die neue Vertragsnummer wird bereits verwendet.")
        try:
            assert_occupancy(unit.store, successor)
        except ValidationError as error:
            raise conflict(str(error)) from None
        return successor.model_dump(mode="json")
    if contract.status != "active":
        raise conflict("Eine Kündigungsfreigabe benötigt einen aktiven Vertrag.")
    if data.termination_end_date < contract.start_date:
        raise conflict("Das bestätigte Mietende liegt vor dem Mietbeginn.")
    if contract.end_date is not None and data.termination_end_date > contract.end_date:
        raise conflict("Eine Kündigung verlängert den Altvertrag nicht. Separaten Folgevertrag prüfen.")
    values = contract.model_dump(exclude={"id", "created_at", "updated_at"})
    values.update(end_date=data.termination_end_date,
                  status="terminated" if today() > data.termination_end_date else "active")
    try:
        assert_occupancy(unit.store, ContractCreate(**values), exclude_id=contract.id)
    except ValidationError as error:
        raise conflict(str(error)) from None
    return {"end_date": data.termination_end_date.isoformat(), "status_policy": "active_through_inclusive_end"}


def _obligations(unit: Work, contract, data) -> dict:
    """No whole collection, no inferred service period from a due date."""
    end = data.termination_end_date if isinstance(data, TerminationData) else contract.end_date
    result: dict[str, Any] = {"rent_charge_count": 0, "receivable_count": 0,
        "receivables_due_after_end_count": 0, "receivables_due_after_end_sample": [],
        "rent_period_conflict_count": 0, "rent_period_conflict_sample": [],
        "policy": "keep_all_obligations_unchanged;due_date_is_not_service_period"}
    fingerprint = hashlib.sha256()
    for model, collection in ((RentChargeORM, "rent_charges"), (ReceivableORM, "receivables")):
        if unit.db is not None:
            query = select(model).where(model.contract_id == contract.id).order_by(model.id)
            records = unit.db.scalars(query.execution_options(yield_per=1000))
        else:
            # Transient backend only; never a persistent global SQL getAll.
            records = iter(sorted((row for row in getattr(unit.store, collection).values()
                                   if row.contract_id == contract.id), key=lambda row: row.id))
        try:
            for item in records:
                inactive = item.status in {"cancelled", "void"}
                snapshot = {"id": item.id, "status": item.status, "updated_at": etag(collection, item.id, item.updated_at)}
                if collection == "rent_charges":
                    result["rent_charge_count"] += 1
                    snapshot["month"] = item.month
                    if not inactive and end is not None and (item.month > month_of(end) or item.month < month_of(contract.start_date)):
                        result["rent_period_conflict_count"] += 1
                        if len(result["rent_period_conflict_sample"]) < 20:
                            result["rent_period_conflict_sample"].append({"id": item.id, "month": item.month})
                else:
                    result["receivable_count"] += 1
                    snapshot["due_date"] = item.due_date.isoformat()
                    if not inactive and end is not None and item.due_date > end:
                        result["receivables_due_after_end_count"] += 1
                        if len(result["receivables_due_after_end_sample"]) < 20:
                            result["receivables_due_after_end_sample"].append({"id": item.id,
                                "due_date": item.due_date.isoformat(), "description": item.description,
                                "amount_due": str(item.amount_due), "amount_paid": str(item.amount_paid)})
                fingerprint.update(packed(snapshot).encode("utf-8"))
                fingerprint.update(b"\n")
        finally:
            close = getattr(records, "close", None)
            if close:
                close()
    result["snapshot_sha256"] = fingerprint.hexdigest()
    return result


def _review(unit: Work, contract, data) -> dict:
    proposed = _validate(unit, contract, data)
    property = unit.store.get_property(contract.property_id)
    location = unit.store.get_unit(contract.unit_id)
    tenant = unit.store.get_tenant(contract.tenant_id)
    previous = _pending(unit, contract.id) if isinstance(data, TerminationData) else None
    if previous is not None:
        _validate_stored(previous)
        if contract.end_date is None or previous.data["termination_end_date"] != contract.end_date.isoformat():
            raise HTTPException(503, "Ausstehende Freigabe passt nicht zum aktuellen Mietende. Bestand prüfen.")
        if data.termination_end_date >= contract.end_date:
            raise conflict("Eine Ablösung benötigt ein ausdrücklich früheres Mietende. Bestehende Freigabe bleibt unverändert.")
    return {"source_contract": contract.model_dump(mode="json"), "source_contract_etag": contract_etag(contract),
        "related_etags": {"property": etag("properties", property.id, property.updated_at),
            "unit": etag("units", location.id, location.updated_at), "tenant": etag("tenants", tenant.id, tenant.updated_at)},
        "proposed_contract": proposed, "data": data.model_dump(mode="json"),
        "obligations": _obligations(unit, contract, data),
        "supersedes": {"id": previous.id, "termination_end_date": previous.data["termination_end_date"],
                       "review_hash": previous.review_hash} if previous is not None else None,
        "date_policy": "inclusive_end;manual_finalize_after_end;server_utc_date",
        "notice_policy": "manual_management_only;no_delivery_or_legal_validity_asserted"}


def _pending(unit: Work, contract_id: str):
    if unit.db is not None:
        rows = list(unit.db.scalars(select(ContractLifecycleDraftORM).where(
            ContractLifecycleDraftORM.contract_id == contract_id,
            ContractLifecycleDraftORM.state == "pending_effective").limit(2).with_for_update()))
    else:
        rows = []
        for row in unit.store.__dict__[ContractLifecycleDraftORM.__tablename__].values():
            if row.contract_id == contract_id and row.state == "pending_effective":
                rows.append(row)
                if len(rows) == 2:
                    break
    if len(rows) > 1:
        raise HTTPException(503, "Mehrere aktuelle Kündigungsfreigaben widersprechen sich. Bestand prüfen.")
    return rows[0] if rows else None


def _period_conflict(review: dict) -> None:
    if review["obligations"]["rent_period_conflict_count"]:
        months = ", ".join(row["month"] for row in review["obligations"]["rent_period_conflict_sample"])
        raise conflict("Gebuchte Monatsforderungen liegen außerhalb der bestätigten Laufzeit (" + months +
                       "). Bestehende Belege ausdrücklich klären; keine automatische Löschung oder Neuberechnung.")


def create_draft(store, contract_id: str, payload: DraftCreate, actor_id: str) -> dict:
    with work(store, actor_id, write=True) as unit:
        contract, property = parent(unit, contract_id, lock=True)
        request_hash = digest({"operation": "create", "payload": payload.model_dump(mode="json")})
        replay = _replay(unit, contract_id, None, actor_id, payload.idempotency_key, request_hash)
        if replay is not None:
            return replay
        source_match(contract, payload.expected_contract_etag)
        row = ContractLifecycleDraftORM(id=str(uuid4()), portfolio_id=property.portfolio_id, contract_id=contract.id,
            property_id=contract.property_id, unit_id=contract.unit_id, tenant_id=contract.tenant_id, actor_id=actor_id,
            create_key=payload.idempotency_key, create_hash=request_hash, data=payload.data.model_dump(mode="json"),
            revision=str(uuid4()), state="draft", source_contract_etag=contract_etag(contract), review=None,
            review_hash=None, applied_contract_etag=None, finalized_contract_etag=None,
            successor_contract_id=None, supersedes_draft_id=None, superseded_by_draft_id=None,
            created_at=now(), updated_at=now())
        # Invalid proposals can be saved and corrected; mutation happens only at confirm.
        unit.add(row)
        return _record(unit, row, actor_id, payload, "create")


def get_draft(store, contract_id: str, draft_id: str, actor_id: str) -> dict:
    with work(store, actor_id) as unit:
        contract, property = parent(unit, contract_id)
        return public(_load(unit, contract, property, draft_id, actor_id), persistent=unit.db is not None)


def _command_start(unit: Work, contract_id: str, draft_id: str, payload, actor_id: str, operation: str):
    contract, property = parent(unit, contract_id, lock=True)
    row = _load(unit, contract, property, draft_id, actor_id, mutate=True, finalize=operation == "finalize")
    replay = _replay(unit, contract_id, draft_id, actor_id, payload.idempotency_key,
                    digest({"operation": operation, "payload": payload.model_dump(mode="json")}))
    if replay is None:
        if operation == "finalize" and row.state == "superseded":
            raise conflict("Diese Freigabe wurde ausdrücklich abgelöst. Nachfolger " + str(row.superseded_by_draft_id) + " laden und prüfen.")
        _revision(row, payload)
        source_match(contract, payload.expected_contract_etag)
        if operation != "edit" and operation != "finalize" and payload.expected_contract_etag != row.source_contract_etag:
            raise conflict("Der Altvertrag wurde geändert. Entwurf zunächst mit dem aktuellen Stand bearbeiten.")
    return contract, row, replay


def edit_draft(store, contract_id: str, draft_id: str, payload: DraftEdit, actor_id: str) -> dict:
    with work(store, actor_id, write=True) as unit:
        contract, row, replay = _command_start(unit, contract_id, draft_id, payload, actor_id, "edit")
        if replay is not None:
            return replay
        if row.state in FINAL_STATES:
            raise conflict("Bestätigte Vertragsfreigaben bleiben unverändert erhalten.")
        _change(unit, row)
        row.data, row.source_contract_etag = payload.data.model_dump(mode="json"), contract_etag(contract)
        row.state, row.review, row.review_hash = "draft", None, None
        row.supersedes_draft_id = None
        return _record(unit, row, actor_id, payload, "edit")


def review_draft(store, contract_id: str, draft_id: str, payload, actor_id: str) -> dict:
    with work(store, actor_id, write=True) as unit:
        contract, row, replay = _command_start(unit, contract_id, draft_id, payload, actor_id, "review")
        if replay is not None:
            return replay
        if row.state in FINAL_STATES:
            raise conflict("Dieser Vertragsvorgang ist bereits bestätigt.")
        data = DraftCreate(idempotency_key=row.create_key, expected_contract_etag=row.source_contract_etag, data=row.data).data
        review = _review(unit, contract, data)
        _change(unit, row)
        row.review, row.review_hash, row.state = review, digest(review), "reviewed"
        row.supersedes_draft_id = review["supersedes"]["id"] if review["supersedes"] else None
        return _record(unit, row, actor_id, payload, "review")


def _update_parent(unit: Work, contract, values: dict, expected: str):
    unit.touch("contracts", contract.id)
    token = _lifecycle_parent.set(contract.id)
    try:
        with revision_scope(parse_revision(expected)):
            if unit.db is not None:
                # BaseRepository validates occupancy/CAS and flushes, never commits.
                return unit.store.tenant._contracts.patch(contract.id, ContractPatch(**values))
            data = {**contract.model_dump(exclude={"id", "created_at", "updated_at"}), **values}
            return unit.store.update_contract(contract.id, ContractCreate(**data))
    finally:
        _lifecycle_parent.reset(token)


def _insert_successor(unit: Work, data: ContractCreate):
    if unit.db is not None:
        return unit.store.tenant._contracts.create(data)
    result = unit.store.create_contract(data)
    unit.touch("contracts", result.id, inserted=True)
    return result


def confirm_draft(store, contract_id: str, draft_id: str, payload, actor_id: str) -> dict:
    with work(store, actor_id, write=True) as unit:
        contract, row, replay = _command_start(unit, contract_id, draft_id, payload, actor_id, "confirm")
        if replay is not None:
            return replay
        if row.state != "reviewed" or row.review_hash != payload.reviewed_hash or digest(row.review) != payload.reviewed_hash:
            raise conflict("Die angezeigte Prüfung stimmt nicht mit dem gespeicherten Entwurf überein.")
        data = DraftCreate(idempotency_key=row.create_key, expected_contract_etag=row.source_contract_etag, data=row.data).data
        review = _review(unit, contract, data)
        if digest(review) != row.review_hash:
            raise conflict("Vertrag, Zuordnung oder Forderungen wurden geändert. Erneut prüfen.")
        _period_conflict(review)
        previous = _pending(unit, contract_id) if row.supersedes_draft_id is not None else None
        if row.supersedes_draft_id is not None and (previous is None or previous.id != row.supersedes_draft_id
                or previous.review_hash != row.review["supersedes"]["review_hash"]):
            raise conflict("Die vorherige Freigabe wurde geändert. Ablösung erneut prüfen.")
        _change(unit, row)
        if isinstance(data, RenewalData):
            successor = _insert_successor(unit, _successor_data(contract, data))
            row.successor_contract_id, row.state = successor.id, "confirmed"
            row.applied_contract_etag = contract_etag(contract)
        else:
            completed = today() > data.termination_end_date
            changed = _update_parent(unit, contract, {"end_date": data.termination_end_date,
                "status": "terminated" if completed else "active"}, payload.expected_contract_etag)
            row.applied_contract_etag = contract_etag(changed)
            row.state = "completed" if completed else "pending_effective"
            if previous is not None:
                _change(unit, previous)
                previous.state, previous.superseded_by_draft_id = "superseded", row.id
        return _record(unit, row, actor_id, payload, "confirm")


def finalize_draft(store, contract_id: str, draft_id: str, payload, actor_id: str) -> dict:
    with work(store, actor_id, write=True) as unit:
        contract, row, replay = _command_start(unit, contract_id, draft_id, payload, actor_id, "finalize")
        if replay is not None:
            return replay
        if row.state == "superseded":
            raise conflict("Diese Freigabe wurde ausdrücklich abgelöst. Nachfolger " + str(row.superseded_by_draft_id) + " laden und prüfen.")
        if row.state != "pending_effective" or row.review_hash != payload.reviewed_hash or digest(row.review) != row.review_hash:
            raise conflict("Keine passende ausstehende Kündigungsfreigabe vorhanden.")
        data = DraftCreate(idempotency_key=row.create_key, expected_contract_etag=row.source_contract_etag, data=row.data).data
        if not isinstance(data, TerminationData) or today() <= data.termination_end_date:
            raise conflict("Der letzte Miettag gehört noch zur Laufzeit. Abschluss erst nach dem bestätigten Mietende.")
        if contract.status != "active" or contract.end_date != data.termination_end_date:
            raise conflict("Status oder bestätigtes Mietende wurde geändert. Bestand ausdrücklich klären.")
        _period_conflict({"obligations": _obligations(unit, contract, data)})
        changed = _update_parent(unit, contract, {"status": "terminated"}, payload.expected_contract_etag)
        _change(unit, row)
        row.state, row.finalized_contract_etag = "completed", contract_etag(changed)
        return _record(unit, row, actor_id, payload, "finalize")


def _cursor(value: str | None):
    if value is None:
        return None
    try:
        decoded = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if not isinstance(decoded, list) or len(decoded) != 2 or not all(isinstance(x, str) for x in decoded):
            raise ValueError
        stamp = datetime.fromisoformat(decoded[0])
        if stamp.tzinfo is not None or not decoded[1]:
            raise ValueError
        return stamp, decoded[1]
    except (ValueError, TypeError, UnicodeDecodeError):
        raise HTTPException(422, "Ungültige Verlaufsseite.") from None


def list_drafts(store, contract_id: str, actor_id: str, *, before: str | None = None, limit: int = 25,
                history: bool = False) -> dict:
    if not 1 <= limit <= 1000:
        raise HTTPException(422, "Seitengröße muss zwischen 1 und 1000 liegen.")
    boundary = _cursor(before)
    with work(store, actor_id) as unit:
        contract, property = parent(unit, contract_id)
        model: Any = ContractLifecycleCommandORM if history else ContractLifecycleDraftORM
        if unit.db is not None:
            query = select(model).where(model.contract_id == contract_id, model.portfolio_id == property.portfolio_id)
            if history:
                query = query.where(model.operation.in_(("confirm", "finalize")))
            else:
                query = query.where(model.actor_id == actor_id, model.state.in_(("draft", "reviewed")))
            if boundary:
                query = query.where(or_(model.created_at < boundary[0],
                    and_(model.created_at == boundary[0], model.id < boundary[1])))
            records = list(unit.db.scalars(query.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)))
        else:
            records = nlargest(limit + 1, (row for row in unit.store.__dict__[model.__tablename__].values()
                if row.contract_id == contract_id and row.portfolio_id == property.portfolio_id
                and (row.operation in {"confirm", "finalize"} if history else row.actor_id == actor_id and row.state not in FINAL_STATES)
                and (boundary is None or (row.created_at, row.id) < boundary)), key=lambda row: (row.created_at, row.id))
        next_before = None
        if len(records) > limit:
            records = records[:limit]
            last = records[-1]
            next_before = base64.urlsafe_b64encode(packed([last.created_at.isoformat(), last.id]).encode()).decode().rstrip("=")
        items = []
        for row in records:
            draft = _load(unit, contract, property, row.draft_id if history else row.id, actor_id)
            if history:
                _validate_command(row, draft)
                items.append({"id": row.id, "draft_id": row.draft_id, "actor_id": row.actor_id,
                    "operation": row.operation, "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
                    "current_state": draft.state, "supersedes_draft_id": draft.supersedes_draft_id,
                    "superseded_by_draft_id": draft.superseded_by_draft_id,
                    "result": deepcopy(row.result)})
            else:
                items.append(public(draft, persistent=unit.db is not None))
        return {"items": items, "next_before": next_before, "persistent": unit.db is not None}


def guard_delete_link(store, entity_type: str, identifier: str) -> None:
    """Root hook: call inside ordinary shared delete/party-change transactions."""
    names = {"contract": ("contract_id", "successor_contract_id"), "tenant": ("tenant_id",),
             "property": ("property_id",), "unit": ("unit_id",), "portfolio": ("portfolio_id",)}
    kind = "property" if entity_type == "properties" else entity_type.removesuffix("s")
    fields = names.get(kind)
    if fields is None:
        return
    if hasattr(store, "db"):
        query = select(ContractLifecycleDraftORM.id).where(or_(
            *(getattr(ContractLifecycleDraftORM, field) == identifier for field in fields))).limit(1)
        exists = store.db.scalar(query) is not None
    else:
        exists = any(any(getattr(row, field) == identifier for field in fields)
            for row in store.__dict__.get(ContractLifecycleDraftORM.__tablename__, {}).values())
    if exists:
        raise ValidationError("Vertragsvorgang mit dauerhafter Mieter-/Altvertragsbindung vorhanden. Historie erhalten.")


def guard_contract_mutation(store, contract_id: str, changes: dict) -> None:
    """Root's ordinary CRUD hook, inside its actual transaction/RLock.

    Declared fields must lock before comparing, including an apparently unchanged
    legacy PUT: a simultaneous confirm may have changed the parent while waiting.
    The exact-parent private context is set ONLY by the reviewed lifecycle write.
    It does not permit party changes or bypass existing occupancy/receipt/CAS.
    """
    relevant = {"end_date", "status", "tenant_id", "property_id", "unit_id"}
    if not relevant.intersection(changes):
        return
    with nullcontext() if hasattr(store, "db") else _memory_lock:
        unit = Work(store, store.db if hasattr(store, "db") else None, current_scope())
        current, _ = parent(unit, contract_id, lock=True)
        if any(field in changes and changes[field] != getattr(current, field)
               for field in ("tenant_id", "property_id", "unit_id")):
            guard_delete_link(store, "contract", contract_id)
        if _lifecycle_parent.get() == contract_id:
            return
        if not any(field in changes and changes[field] != getattr(current, field) for field in ("end_date", "status")):
            return
        if unit.db is not None:
            accepted = unit.db.scalar(select(ContractLifecycleDraftORM.id).where(
                ContractLifecycleDraftORM.contract_id == contract_id,
                ContractLifecycleDraftORM.state.in_(("pending_effective", "completed")),
                ContractLifecycleDraftORM.data["operation"].as_string() == "termination").limit(1)) is not None
        else:
            accepted = any(row.contract_id == contract_id and row.state in {"pending_effective", "completed"}
                and row.data.get("operation") == "termination"
                for row in store.__dict__.get(ContractLifecycleDraftORM.__tablename__, {}).values())
        if accepted:
            raise ValidationError("Bestätigtes Mietende und Kündigungsstatus sind belegt. Änderung nur erneut prüfen/freigeben oder eigenständigen Folgevertrag anlegen.")


def guard_known_rent_period(store, contract_id: str, month: str) -> None:
    """Optional Root creation hook: only a known rent-service month, never due dates.

    Caller must hold its ordinary parent lock. No receivable restriction is added.
    """
    contract = store.get_contract(contract_id)
    if contract.end_date is None or month <= month_of(contract.end_date):
        return
    if hasattr(store, "db"):
        accepted = store.db.scalar(select(ContractLifecycleDraftORM.id).where(
            ContractLifecycleDraftORM.contract_id == contract_id,
            ContractLifecycleDraftORM.state.in_(("pending_effective", "completed"))).limit(1)) is not None
    else:
        accepted = any(row.contract_id == contract_id and row.state in {"pending_effective", "completed"}
            for row in store.__dict__.get(ContractLifecycleDraftORM.__tablename__, {}).values())
    if accepted:
        raise ValidationError("Monats-Leistungszeitraum liegt nach dem ausdrücklich bestätigten Mietende.")


def guard_destructive_reset(store) -> None:
    """Root reset/partial-JSON hook; never silently discard a reviewed journal."""
    for model in LIFECYCLE_MODELS:
        if hasattr(store, "db"):
            present = store.db.scalar(select(model.id).limit(1)) is not None
        else:
            present = bool(store.__dict__.get(model.__tablename__))
        if present:
            raise ValidationError("Vertragsfreigabe-Journal vorhanden. Vollständige Wiederherstellung verwenden; Teilimport oder Zurücksetzen würde Belege verlieren.")
