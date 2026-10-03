"""Atomic, reviewed dispute journal without implicit financial/status changes."""

import hashlib
import json
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from .. import auth
from ..db.billing_dispute_models import (
    DISPUTE_TABLES,
)
from ..db.billing_dispute_models import (
    BillingDisputeCaseORM as Case,
)
from ..db.billing_dispute_models import (
    BillingDisputeCommandORM as Command,
)
from ..db.billing_dispute_models import (
    BillingDisputeEventORM as Event,
)
from ..db.billing_dispute_models import (
    BillingDisputeEvidenceORM as Evidence,
)
from ..db.billing_dispute_schema import validate_dispute_schema
from ..db.document_version_models import DocumentVersionORM
from ..db.orm_models import BillingPeriodORM, ContractORM, TenantORM, UtilityStatementORM
from ..storage import NotFoundError
from .billing_dispute_types import AppendDisputeEvent, OpenDispute
from .billing_dispute_validation import DisputeIntegrityError, digest, event_hash, event_state, payload, validate_event
from .billing_settlement import IMMUTABLE, _root_period
from .contract_occupancy import begin_writer
from .measurement_history import _identity, lock_measurement_property
from .portfolio_scope import memory_visible, refresh_scope, scope_context


def conflict(message="Der geprüfte Stand wurde geändert. Bestand und Vorschau erneut laden."):
    return HTTPException(409, message)


def _rows(store, model, **filters):
    order = ("revision", "id") if model in {Command, Event} else ("id",)
    if hasattr(store, "db"):
        query = (select(model).where(*(getattr(model, name) == value for name, value in filters.items()))
                 .order_by(*(getattr(model, name) for name in order)).execution_options(yield_per=100))
        return store.db.scalars(query)
    return (row for row in sorted(store.__dict__.get(model.__tablename__, {}).values(), key=lambda item: tuple(getattr(item, name) for name in order))
            if all(getattr(row, name) == value for name, value in filters.items())
            and memory_visible(store, model.__tablename__, row))


def _statement_snapshot_hash(active, period):
    """Exact existing settlement digest, streamed by statement ID in SQL."""
    from ..models import UtilityStatement
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False)
    checksum = hashlib.sha256()
    def value(item):
        for block in encoder.iterencode(item):
            checksum.update(block.encode("utf-8"))
    checksum.update(b'{"owner_cost_share": ')
    value(period.owner_cost_share)
    checksum.update(b', "statements": [')
    if hasattr(active, "db"):
        rows = _rows(active, UtilityStatementORM, billing_period_id=period.id)
    else:
        rows = sorted((row for row in active.list_utility_statements() if row.billing_period_id == period.id), key=lambda row: row.id)
    try:
        for index, row in enumerate(rows):
            if index:
                checksum.update(b", ")
            statement = UtilityStatement.model_validate(row, from_attributes=True) if hasattr(active, "db") else row
            value(statement.model_dump(mode="json", exclude={"status", "snapshot_hash", "delivery_status", "delivered_at", "delivery_channel", "updated_at"}))
    finally:
        close = getattr(rows, "close", None)
        if close is not None:
            close()
    checksum.update(b"]}")
    return checksum.hexdigest()


def _case(store, case_id):
    row = store.db.get(Case, case_id) if hasattr(store, "db") else store.__dict__.get(Case.__tablename__, {}).get(case_id)
    if row is None or not memory_visible(store, Case.__tablename__, row):
        raise HTTPException(404, "Widerspruchsakte nicht verfügbar.")
    if row.original_hash != digest(row.original_snapshot):
        raise DisputeIntegrityError("Beanstandetes Abrechnungsoriginal ist beschädigt.")
    return row


@contextmanager
def work(store, actor_id, *, period_id=None, case_id=None, write=False):
    from .tenant_privacy import _memory_privacy_lock
    sql = hasattr(store, "db")
    with nullcontext() if sql else _memory_privacy_lock():
        captured = _identity(actor_id, write)
        with scope_context(captured):
            db = Session(store.db.get_bind(), autoflush=False, expire_on_commit=False) if sql else None
            active = store
            inserted = []
            previous_case = None
            if db is not None:
                from ..repositories.sql_store import SQLAlchemyStore
                active = SQLAlchemyStore(db)
            try:
                if db is not None:
                    if not write and db.get_bind().dialect.name == "postgresql":
                        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                    elif not write and db.get_bind().dialect.name == "sqlite":
                        connection = db.connection()
                        driver = connection.connection.driver_connection
                        assert driver is not None
                        if not driver.in_transaction:
                            connection.exec_driver_sql("BEGIN")
                    if not validate_dispute_schema(db.connection()):
                        raise HTTPException(503, "Widerspruchsjournal fehlt. Reguläre Datenbankmigration ausführen.")
                    if write:
                        db.info["dispute_write"] = True
                        begin_writer(db)
                        if isinstance(auth._user_store, auth.SQLUserStore):
                            auth._user_store._lock_management(db)
                        captured = _identity(actor_id, True)
                else:
                    present = set(DISPUTE_TABLES) & active.__dict__.keys()
                    if present and present != set(DISPUTE_TABLES):
                        raise DisputeIntegrityError("Unvollständiges Widerspruchsjournal.")
                    if write:
                        for name in DISPUTE_TABLES:
                            active.__dict__.setdefault(name, {})
                case = _case(active, case_id) if case_id else None
                period = active.get_billing_period(case.period_id if case else period_id) if case or period_id else None
                if period is not None:
                    prop = active.get_property(period.property_id)
                    active.get_portfolio(prop.portfolio_id)
                    if write:
                        lock_measurement_property(active, prop.id)
                        if db is not None:
                            root = _root_period(active, period.id)
                            db.scalar(select(BillingPeriodORM).where(BillingPeriodORM.id == root.id).with_for_update())
                            db.expire_all()
                            period = active.get_billing_period(period.id)
                            if period.property_id != prop.id:
                                raise conflict("Die Abrechnungszuordnung wurde geändert.")
                            if case is not None:
                                case = db.scalar(select(Case).where(Case.id == case.id).with_for_update())
                        elif case is not None:
                            previous_case = deepcopy(case)
                def add(row):
                    if db is not None:
                        db.add(row)
                        db.flush()
                    else:
                        active.__dict__[row.__tablename__][row.id] = row
                        inserted.append((row.__tablename__, row.id))
                yield active, case, period, add
                _identity(actor_id, write)
                refresh_scope(captured)
                if db is not None and write:
                    account_lock = getattr(auth._user_store, "_lock", None)
                    with account_lock if account_lock is not None else nullcontext():
                        _identity(actor_id, True)
                        refresh_scope(captured)
                        db.commit()
            except BaseException:
                if db is not None:
                    db.rollback()
                elif write:
                    for name, identifier in reversed(inserted):
                        active.__dict__[name].pop(identifier, None)
                    if previous_case is not None:
                        active.__dict__[Case.__tablename__][previous_case.id] = previous_case
                raise
            finally:
                if db is not None:
                    db.close()


def _mapped(operation):
    def call(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except NotFoundError as error:
            raise HTTPException(404, "Abrechnungsobjekt nicht verfügbar.") from error
        except IntegrityError as error:
            raise conflict("Eine Akte oder Revision wurde gleichzeitig bestätigt. Bestand laden und denselben Befehl wiederholen.") from error
        except OperationalError as error:
            sqlite_code = getattr(error.orig, "sqlite_errorcode", 0) & 255
            pg_code = getattr(error.orig, "sqlstate", getattr(error.orig, "pgcode", None))
            if sqlite_code not in {5, 6} and pg_code not in {"55P03", "40P01", "40001"}:
                raise
            raise conflict("Abrechnung oder Akte wird gerade bearbeitet. Unveränderten Befehl erneut versuchen.") from error
    return call


def _original(active, period, command):
    if period.status not in IMMUTABLE:
        raise conflict("Widerspruch benötigt eine finalisierte unveränderte Abrechnung.")
    prop = active.get_property(period.property_id)
    base = dict(portfolio_id=prop.portfolio_id, property_id=prop.id, period_id=period.id,
                case_kind=command.case_kind, statement_id=None, contract_id=None, tenant_id=None, unit_id=None,
                statement_revision=None, party_binding="no_tenant_property_review")
    if command.case_kind == "tenant_statement":
        statement = active.get_utility_statement(command.statement_id)
        if statement.billing_period_id != period.id or statement.status not in IMMUTABLE:
            raise HTTPException(404, "Einzelabrechnung gehört nicht zu dieser finalisierten Periode.")
        if statement.revision != command.expected_statement_revision or statement.snapshot_hash != command.expected_snapshot_hash:
            raise conflict("Revision oder Originalhash der Einzelabrechnung stimmt nicht mit der geprüften Fassung überein.")
        contract = active.get_contract(statement.contract_id)
        unit = active.get_unit(statement.unit_id)
        if contract.property_id != prop.id or unit.property_id != prop.id or contract.unit_id != unit.id:
            raise conflict("Der Abrechnungsvertrag besitzt eine widersprüchliche Objektbindung.")
        if hasattr(active, "db") and active.db.info.get("dispute_write"):
            active.db.scalar(select(ContractORM.id).where(ContractORM.id == contract.id).with_for_update())
            active.db.scalar(select(TenantORM.id).where(TenantORM.id == contract.tenant_id).with_for_update(read=True))
            active.db.scalar(select(UtilityStatementORM.id).where(UtilityStatementORM.id == statement.id).with_for_update())
        active.get_tenant(contract.tenant_id)
        if _statement_snapshot_hash(active, period) != statement.snapshot_hash:
            raise DisputeIntegrityError("Abrechnungsinhalt weicht vom finalisierten Originalhash ab.")
        if any(index >= len(statement.line_items or []) for index in command.line_item_refs):
            raise HTTPException(422, "Beanstandete Position existiert nicht im Abrechnungsoriginal.")
        original = statement.model_dump(mode="json", exclude={"status", "delivery_status", "delivered_at", "delivery_channel", "updated_at"})
        base.update(statement_id=statement.id, contract_id=contract.id, tenant_id=contract.tenant_id,
                    unit_id=unit.id, statement_revision=statement.revision, party_binding="verified_at_case_opening")
        return {**base, "snapshot_hash": statement.snapshot_hash, "original_snapshot": original, "original_hash": digest(original)}
    owner = period.owner_cost_share
    if owner is None:
        raise conflict("Objektprüfung benötigt eine bestätigte Eigentümerabrechnungsgrundlage.")
    original = {"period_id": period.id, "revision": period.revision_number, "owner_cost_share": owner}
    if command.expected_snapshot_hash != digest(original):
        raise conflict("Die geprüfte Eigentümerabrechnung wurde geändert.")
    return {**base, "snapshot_hash": digest(original), "original_snapshot": original, "original_hash": digest(original)}


def _evidence_version(active, binding, identifier):
    from .document_versions import validate_manifest
    row = active.db.get(DocumentVersionORM, identifier) if hasattr(active, "db") else active.__dict__.get("document_versions", {}).get(identifier)
    if (row is None or row.portfolio_id != binding["portfolio_id"] or row.property_id != binding["property_id"]
            or row.tenant_id not in {None, binding["tenant_id"]} or row.contract_id not in {None, binding["contract_id"]}
            or row.unit_id not in {None, binding["unit_id"]}):
        raise HTTPException(404, "Anlagenoriginal gehört nicht zur geprüften Akte.")
    validate_manifest(row)
    return row


def _evidence_manifest(row):
    return {"version_id": row.id, "document_id": row.document_id, "sha256": row.sha256,
            "filename": row.filename, "size_bytes": row.size_bytes, "media_type": row.media_type}


def _evidence(active, binding, identifiers):
    from .document_versions import verified_blocks
    rows = []
    for identifier in identifiers:
        row = _evidence_version(active, binding, identifier)
        for _block in verified_blocks(active, row):
            pass  # Stream/hash actual original bytes; do not materialize an entire file.
        rows.append(_evidence_manifest(row))
    return rows


def _preview(command, binding, evidence, *, state=None, previous_hash=None, correction=None):
    request = command.model_dump(mode="json", exclude={"preview_hash"})
    data = {"request": request, "binding": binding, "evidence": evidence,
            "state": state, "previous_hash": previous_hash, "correction": correction}
    return {"preview_hash": digest(data), **jsonable_encoder(data)}


def _prior(active, actor_id, command, *, case_id=None):
    row = next(iter(_rows(active, Command, actor_id=actor_id, idempotency_key=command.idempotency_key)), None)
    if row is not None:
        if row.request_hash != digest(command.model_dump(mode="json")) or case_id is not None and row.case_id != case_id:
            raise conflict("Diese Befehlskennung gehört bereits zu einem anderen Inhalt.")
        return deepcopy(row.result)
    return None


def _confirm_preview(command, preview):
    if command.preview_hash is None or command.preview_hash != preview["preview_hash"]:
        raise conflict("Vor dem Bestätigen bitte Grund, Originalfassung und Anlagen in der aktuellen Vorschau prüfen.")


@_mapped
def preview_open(store, command: OpenDispute, actor_id):
    with work(store, actor_id, period_id=command.period_id) as (active, _case, period, _add):
        binding = _original(active, period, command)
        return _preview(command, binding, _evidence(active, binding, command.evidence_version_ids))


def _publish(active, case, command, actor_id, kind, observed_on, evidence, add, *, previous_hash=None, correction=None):
    revision = case.revision
    command_id, event_id = str(uuid4()), str(uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = {"case_id": case.id, "revision": revision, "event_id": event_id}
    request = command.model_dump(mode="json")
    receipt = Command(id=command_id, case_id=case.id, portfolio_id=case.portfolio_id, actor_id=actor_id,
        idempotency_key=command.idempotency_key, revision=revision, request_hash=digest(request),
        request=request, result=result, created_at=now)
    add(receipt)
    row = Event(id=event_id, case_id=case.id, command_id=command_id, portfolio_id=case.portfolio_id,
        revision=revision, actor_id=actor_id, created_at=now, observed_on=observed_on, kind=kind, reason=command.reason,
        corrects_event_id=getattr(command, "corrects_event_id", None), statement_revision=case.statement_revision,
        snapshot_hash=case.snapshot_hash, line_item_refs=list(getattr(command, "line_item_refs", ())),
        correction_statement_id=correction["id"] if correction else None,
        correction_snapshot_hash=correction["snapshot_hash"] if correction else None,
        previous_hash=previous_hash)
    links = [Evidence(id=str(uuid4()), event_id=event_id, portfolio_id=case.portfolio_id,
        version_id=item["version_id"], sha256=item["sha256"]) for item in evidence]
    row.content_hash = event_hash(payload(row), [payload(link) for link in links])
    add(row)
    for link in links:
        add(link)
    return result


@_mapped
def open_case(store, command: OpenDispute, actor_id):
    with work(store, actor_id, period_id=command.period_id, write=True) as (active, _case, period, add):
        replay = _prior(active, actor_id, command)
        if replay is not None:
            return replay
        binding = _original(active, period, command)
        if command.statement_id and next(iter(_rows(active, Case, statement_id=command.statement_id)), None) is not None:
            raise conflict("Für diese Einzelabrechnung besteht bereits eine Akte. Die bestehende Chronik fortsetzen.")
        evidence = _evidence(active, binding, command.evidence_version_ids)
        _confirm_preview(command, _preview(command, binding, evidence))
        case = Case(id=str(uuid4()), **binding, revision=1, state="open", created_at=datetime.now(timezone.utc).replace(tzinfo=None))
        add(case)
        return _publish(active, case, command, actor_id, "opened", command.received_on, evidence, add)


def _event_rows(active, case_id, *, after=0, page_size=None):
    if hasattr(active, "db"):
        query = select(Event).where(Event.case_id == case_id, Event.revision > after).order_by(Event.revision)
        return list(active.db.scalars(query.limit(page_size) if page_size else query))
    ordered = sorted((row for row in _rows(active, Event, case_id=case_id) if row.revision > after), key=lambda row: row.revision)
    return ordered[:page_size] if page_size else ordered


def _verified(active, case, row):
    links = [payload(link) for link in _rows(active, Evidence, event_id=row.id)]
    value = payload(row)
    validate_event(value, links, payload(case))
    manifests = []
    for link in links:
        version = _evidence_version(active, payload(case), link["version_id"])
        if version.sha256 != link["sha256"]:
            raise DisputeIntegrityError("Widerspruchsanlage weicht vom eingefrorenen Originalhash ab.")
        manifests.append({**link, **_evidence_manifest(version)})
    return jsonable_encoder(deepcopy({**value, "evidence": manifests}))


def _append_preview(active, case, command):
    if command.expected_revision != case.revision:
        raise conflict()
    event_state(case.state, command.kind)
    previous = _event_rows(active, case.id, after=case.revision - 1)
    if len(previous) != 1 or previous[0].revision != case.revision:
        raise DisputeIntegrityError("Letztes bestätigtes Ereignis fehlt.")
    _verified(active, case, previous[0])
    if command.corrects_event_id:
        target = next(iter(_rows(active, Event, id=command.corrects_event_id, case_id=case.id)), None)
        if target is None or target.revision > case.revision:
            raise HTTPException(404, "Zu berichtigendes Originalereignis gehört nicht zu dieser Akte.")
        _verified(active, case, target)
    correction = None
    if command.correction_statement_id:
        statement = active.get_utility_statement(command.correction_statement_id)
        if statement.status not in IMMUTABLE or not statement.snapshot_hash or statement.contract_id != case.contract_id:
            raise conflict("Verknüpfung benötigt eine finalisierte Korrektur für dieselbe Einzelabrechnung.")
        correction_period = active.get_billing_period(statement.billing_period_id)
        if correction_period.property_id != case.property_id or _statement_snapshot_hash(active, correction_period) != statement.snapshot_hash:
            raise DisputeIntegrityError("Die verknüpfte Korrektur weicht von ihrem finalisierten Original ab.")
        visited = {statement.id}
        current = statement
        while current.source_statement_id:
            if current.source_statement_id == case.statement_id:
                break
            if current.source_statement_id in visited:
                raise DisputeIntegrityError("Zyklische Abrechnungskorrektur.")
            visited.add(current.source_statement_id)
            current = active.get_utility_statement(current.source_statement_id)
            if current.contract_id != case.contract_id:
                raise DisputeIntegrityError("Die Korrekturkette enthält eine andere Mietpartei.")
        else:
            raise conflict("Die Korrektur gehört nicht zur beanstandeten Originalfassung.")
        correction = {"id": statement.id, "revision": statement.revision, "snapshot_hash": statement.snapshot_hash}
    binding = payload(case)
    evidence = _evidence(active, binding, command.evidence_version_ids)
    return _preview(command, binding, evidence, state=case.state, previous_hash=previous[0].content_hash, correction=correction)


@_mapped
def preview_append(store, case_id, command: AppendDisputeEvent, actor_id):
    with work(store, actor_id, case_id=case_id) as (active, case, _period, _add):
        return _append_preview(active, case, command)


@_mapped
def append_event(store, case_id, command: AppendDisputeEvent, actor_id):
    with work(store, actor_id, case_id=case_id, write=True) as (active, case, _period, add):
        replay = _prior(active, actor_id, command, case_id=case_id)
        if replay is not None:
            return replay
        preview = _append_preview(active, case, command)
        _confirm_preview(command, preview)
        new_state = event_state(case.state, command.kind)
        if hasattr(active, "db"):
            changed = active.db.execute(update(Case).where(Case.id == case.id, Case.revision == command.expected_revision)
                .values(revision=case.revision + 1, state=new_state).execution_options(synchronize_session=False))
            if changed.rowcount != 1:
                raise conflict()
            active.db.refresh(case)
        else:
            case = deepcopy(case)
            case.revision += 1
            case.state = new_state
            active.__dict__[Case.__tablename__][case.id] = case
        return _publish(active, case, command, actor_id, command.kind, command.observed_on,
            preview["evidence"], add, previous_hash=preview["previous_hash"], correction=preview["correction"])


@_mapped
def read_case(store, case_id, actor_id):
    with work(store, actor_id, case_id=case_id) as (active, case, period, _add):
        latest = _event_rows(active, case.id, after=case.revision - 1)
        if len(latest) != 1:
            raise DisputeIntegrityError("Letzte Journalrevision fehlt.")
        return {**jsonable_encoder(deepcopy(payload(case))), "latest_event": _verified(active, case, latest[0]),
                "legacy_period_status": period.status == "disputed",
                "party_binding_note": "Mieterbezug beim Öffnen geprüft; die frühere Abrechnung speichert keine damalige Mieteridentität."}


@_mapped
def journal(store, case_id, actor_id, *, after=0, page_size=50):
    with work(store, actor_id, case_id=case_id) as (active, case, _period, _add):
        size = min(max(page_size, 1), 200)
        rows = _event_rows(active, case.id, after=after, page_size=size + 1)
        items = [_verified(active, case, row) for row in rows[:size]]
        return {"items": items, "next_after": items[-1]["revision"] if len(rows) > size else None, "revision": case.revision}


@_mapped
def original_event(store, case_id, event_id, actor_id):
    with work(store, actor_id, case_id=case_id) as (active, case, _period, _add):
        row = next(iter(_rows(active, Event, id=event_id, case_id=case.id)), None)
        if row is None:
            raise HTTPException(404, "Originalereignis nicht verfügbar.")
        return _verified(active, case, row)


@_mapped
def list_cases(store, actor_id, *, property_id=None, period_id=None, tenant_id=None, state=None, after_id="", page_size=50):
    with work(store, actor_id) as (active, _case, _period, _add):
        size = min(max(page_size, 1), 200)
        filters = {key: value for key, value in {"property_id": property_id, "period_id": period_id, "tenant_id": tenant_id, "state": state}.items() if value is not None}
        if hasattr(active, "db"):
            query = select(Case).where(Case.id > after_id, *(getattr(Case, key) == value for key, value in filters.items())).order_by(Case.id).limit(size + 1)
            rows = list(active.db.scalars(query))
        else:
            rows = sorted((row for row in _rows(active, Case, **filters) if row.id > after_id), key=lambda row: row.id)[:size + 1]
        items = [{key: jsonable_encoder(getattr(row, key)) for key in
            ("id", "property_id", "period_id", "statement_id", "statement_revision", "tenant_id", "case_kind", "revision", "state", "created_at")} for row in rows[:size]]
        return {"items": items, "next_after_id": items[-1]["id"] if len(rows) > size else None}


@_mapped
def period_status(store, period_id, actor_id):
    with work(store, actor_id, period_id=period_id) as (active, _case, period, _add):
        if hasattr(active, "db"):
            total = active.db.scalar(select(func.count(Case.id)).where(Case.period_id == period.id))
            opened = active.db.scalar(select(func.count(Case.id)).where(Case.period_id == period.id, Case.state.in_({"open", "in_review"})))
        else:
            cases = list(_rows(active, Case, period_id=period.id))
            total, opened = len(cases), sum(row.state in {"open", "in_review"} for row in cases)
        owner_original = ({"period_id": period.id, "revision": period.revision_number, "owner_cost_share": period.owner_cost_share}
                          if period.status in IMMUTABLE and period.owner_cost_share is not None else None)
        return {"period_id": period.id, "legacy_disputed_without_complete_case": period.status == "disputed" and not total,
                "case_count": total, "open_case_count": opened,
                "property_review_original": jsonable_encoder(deepcopy(owner_original)),
                "property_review_snapshot_hash": digest(owner_original) if owner_original is not None else None,
                "financial_effect": "none; financial changes require the existing explicit settlement process"}
