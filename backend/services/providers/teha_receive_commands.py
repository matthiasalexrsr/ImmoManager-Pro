"""Transactional TEHA mapping and local import commands on existing cores."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Iterable, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException
from sqlalchemy import Table, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ... import auth
from ...config import settings
from ...db.access_models import ResourcePortfolioORM
from ...db.orm_models import (
    BillingPeriodORM,
    ContractORM,
    DocumentORM,
    PortfolioORM,
    PropertyORM,
    TaskORM,
    TenantORM,
    UnitORM,
)
from ...db.teha_receive_models import TehaExternalMappingORM, TehaImportReceiptORM
from ...db.teha_receive_schema import (
    TehaReceiveSchemaError,
    validate_identity_binding,
    validate_teha_receive_schema,
)
from ...models import Document, Task
from ...permissions import may_write_resource
from ...repositories.base import BaseRepository
from ...repositories.sql_store import SQLAlchemyStore
from .. import document_versions
from ..concurrency import etag
from ..contract_occupancy import begin_writer
from ..integrations.history_store import configured_history
from ..integrations.history_types import HistoryActor
from ..portfolio_scope import current_scope, refresh_scope, scope_context, scope_from_user
from ..request_authority import require_fresh_request_authority
from .teha_command_types import (
    ConfirmMapping,
    ImportDocument,
    ImportTechnicalOrder,
    OpaqueIdentity,
    PreviewImport,
)
from .teha_import_projection import document_projection, task_projection
from .teha_import_validation import (
    TehaImportEvidenceError,
    build_document_manifest,
    mapping_reference,
    validate_document_manifest,
)
from .teha_journal_reader import TehaReceiveError, history_exchange
from .teha_receive_contract import (
    ExplicitMapping,
    ExternalIdentity,
    MappingIndex,
    MappingRequirement,
    ObservedEvidence,
    PreviewDecision,
    TargetKind,
    digest,
    mapping_digest,
)

INTEGRATION_ID = "teha"


def _schema_unavailable() -> HTTPException:
    return HTTPException(503, {
        "code": "teha_l2_schema_requires_maintenance",
        "message": "TEHA-Mapping- und Importbelege benötigen die ausdrücklich geprüfte L2-Einrichtung. Keine Daten wurden repariert.",
        "maintenance_path": "docs/TEHA_L2_MAINTENANCE_20261004.md",
    })


def _commit_authority_unavailable() -> HTTPException:
    return HTTPException(503, {
        "code": "teha_write_unit_unavailable",
        "message": "Die zentrale TEHA-Schreibeinheit ist noch nicht implementiert. Der Fachschreibvorgang wurde vor Datenänderungen abgebrochen.",
    })


def _require_root_commit_authority(_authority: Any, _actor_id: str) -> None:
    """No positive contract exists: actor-only or Notification proofs cannot write.

    A future Root unit must own the actual Session, transaction, database target,
    operation and targets through commit. Checking a nominal Python type twice
    cannot bind the independent Session below to such a unit. Do not dynamically
    load or accept a proposed generic module while that real contract is absent.
    """
    raise _commit_authority_unavailable()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _conflict(message: str) -> HTTPException:
    return HTTPException(409, message)


def _identity(actor_id: str, *, write_kind: str | None = None):
    user = auth.get_user_by_id(actor_id)
    if not user or not user["is_active"]:
        raise HTTPException(401, "Anmeldung nicht mehr gültig.")
    if user["role"] not in {"eigentuemer", "verwalter"}:
        raise HTTPException(403, "Installationsverwaltung erforderlich.")
    captured = current_scope()
    if captured is not None and captured.user_id != actor_id:
        raise HTTPException(403, "Ungültige Benutzerbindung.")
    captured = refresh_scope(captured) if captured is not None else scope_from_user(user)
    if captured is None or not captured.unrestricted:
        raise HTTPException(403, "Installationsverwaltung erforderlich.")
    if write_kind == "document" and not may_write_resource(user["role"], "documents"):
        raise HTTPException(403, "Keine Berechtigung zur Dokumentverwaltung.")
    if write_kind == "task" and not may_write_resource(user["role"], "tasks"):
        raise HTTPException(403, "Keine Berechtigung zur Aufgabenverwaltung.")
    return user, captured


@contextmanager
def _work(
    store,
    actor_id: str,
    *,
    write: bool = False,
    write_kind: str | None = None,
    commit_authority: Any = None,
):
    if write:
        _require_root_commit_authority(commit_authority, actor_id)
    if not hasattr(store, "db"):
        raise HTTPException(503, "Persistente TEHA-Mappingdatenbank erforderlich.")
    user, captured = _identity(actor_id, write_kind=write_kind if write else None)
    require_fresh_request_authority(actor_id)
    bind = store.db.get_bind()
    db = Session(getattr(bind, "engine", bind), autoflush=False, expire_on_commit=False)
    active = SQLAlchemyStore(db)
    with scope_context(captured):
        try:
            if write:
                begin_writer(db)
                if isinstance(auth._user_store, auth.SQLUserStore):
                    auth._user_store._lock_management(db)
                    refresh_scope(captured)
            if not validate_teha_receive_schema(db.connection()):
                raise _schema_unavailable()
            yield SimpleNamespace(store=active, db=db, captured=captured, user=user)
            refresh_scope(captured)
            latest = auth.get_user_by_id(actor_id)
            if (
                not latest
                or not latest["is_active"]
                or latest["role"] != user["role"]
                or (
                    write_kind == "document"
                    and not may_write_resource(latest["role"], "documents")
                )
                or (
                    write_kind == "task"
                    and not may_write_resource(latest["role"], "tasks")
                )
            ):
                raise HTTPException(403, "Berechtigung wurde während des TEHA-Vorgangs geändert.")
            require_fresh_request_authority(actor_id)
            if write:
                _require_root_commit_authority(commit_authority, actor_id)
                db.commit()
        except TehaReceiveSchemaError:
            db.rollback()
            raise _schema_unavailable() from None
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()


def _history_detail(actor_id: str, run_id: str, history=None) -> dict[str, Any]:
    _, captured = _identity(actor_id)
    with scope_context(captured):
        principal = HistoryActor.authenticated()
        return (history or configured_history()).detail(INTEGRATION_ID, run_id, principal)


def _opaque(value: OpaqueIdentity) -> ExternalIdentity:
    try:
        return ExternalIdentity.create(value.kind, **value.parts)
    except (TypeError, ValueError):
        raise HTTPException(422, "Ungültige opaque TEHA-Identität.") from None


def _body(exchange: dict[str, Any]) -> dict[str, Any]:
    response = exchange.get("response")
    body = response.get("body") if isinstance(response, dict) else None
    if not isinstance(body, dict):
        raise TehaReceiveError("history_evidence_invalid")
    return body


def _args(detail: dict[str, Any]) -> dict[str, Any]:
    payload = detail.get("payload")
    arguments = payload.get("arguments") if isinstance(payload, dict) else None
    return arguments if isinstance(arguments, dict) else {}


def _history_connection_key(detail: dict[str, Any]) -> str:
    payload = detail.get("payload")
    connection_key = payload.get("connection_key") if isinstance(payload, dict) else None
    if (
        not isinstance(connection_key, str)
        or not connection_key
        or len(connection_key) > 200
    ):
        raise TehaReceiveError("history_connection_missing")
    return connection_key


def _part(value: Any, name: str) -> str | int:
    if type(value) is int:
        return value
    if isinstance(value, str) and value:
        return value
    raise ValueError(f"missing TEHA identity part: {name}")


def _source_candidates(
    detail: dict[str, Any],
    identity: ExternalIdentity,
    connection_key: str,
) -> Iterable[dict[str, Any]]:
    payload = detail.get("payload")
    operation = payload.get("operation") if isinstance(payload, dict) else None
    exchange = history_exchange(
        detail,
        expected_operation=operation if isinstance(operation, str) else None,
        expected_connection_key=connection_key,
    )
    body = _body(exchange)
    args = _args(detail)
    if identity.kind in {"property", "period"} and operation == "list_property_periods":
        rows = body.get("liegenschaften")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("liegId"), dict):
                    continue
                lieg = row["liegId"]
                candidate = ExternalIdentity.create(
                    identity.kind,
                    **({"object_id": lieg.get("id")} if identity.kind == "property" else {
                        "object_id": lieg.get("id"),
                        "period_number": lieg.get("abrechnungLaufendeNr"),
                    }),
                )
                if candidate == identity:
                    yield row
        return
    if identity.kind == "technical_order" and operation == "list_technical_orders":
        rows = body.get("auftraege")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    try:
                        candidate = ExternalIdentity.create("technical_order", termin_id=_part(row.get("terminId"), "terminId"))
                    except (TypeError, ValueError):
                        continue
                    if candidate == identity:
                        yield row
        return
    if identity.kind == "user" and operation == "read_order_users":
        termin_id = args.get("termin_id")
        rows = body.get("nutzerInAuftrag")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    try:
                        candidate = ExternalIdentity.create("user", termin_id=_part(termin_id, "termin_id"), user_id=_part(row.get("id"), "id"))
                    except (TypeError, ValueError):
                        continue
                    if candidate == identity:
                        yield row
        return
    if identity.kind == "unit" and operation == "list_documents":
        lieg_nr = args.get("lieg_nr")
        rows = body.get("documents")
        if isinstance(rows, list):
            for row in rows:
                props = row.get("properties") if isinstance(row, dict) else None
                if not isinstance(props, dict):
                    continue
                try:
                    candidate = ExternalIdentity.create("unit", lieg_nr=_part(lieg_nr, "lieg_nr"), unit_id=_part(props.get("Nutzereinheit_ID"), "Nutzereinheit_ID"))
                except (TypeError, ValueError):
                    continue
                if candidate == identity:
                    yield row
        return
    if identity.kind == "document" and operation == "list_documents":
        lieg_nr = args.get("lieg_nr")
        rows = body.get("documents")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    candidate = ExternalIdentity.create(
                        "document",
                        lieg_nr=_part(lieg_nr, "lieg_nr"),
                        reference=_part(row.get("reference"), "reference"),
                    )
                except (TypeError, ValueError):
                    continue
                if candidate == identity:
                    yield row
        return
    if identity.kind == "document" and operation == "read_document":
        try:
            candidate = ExternalIdentity.create(
                "document",
                lieg_nr=_part(args.get("lieg_nr"), "lieg_nr"),
                reference=_part(args.get("reference"), "reference"),
            )
        except (TypeError, ValueError):
            return
        if candidate == identity:
            yield body


def _verified_source(
    actor_id: str,
    run_id: str,
    connection_key: str,
    identity: ExternalIdentity,
    external_identity_hash: str,
    source_sha256: str,
    history=None,
):
    if identity.token != external_identity_hash:
        raise HTTPException(422, "Externe Identität und Hash stimmen nicht überein.")
    if identity.kind != "document":
        # Only mapping identities enter relational IdentityJSON. Documents are
        # source identities only and remain entirely in encrypted history.
        validate_identity_binding(
            identity.kind,
            identity.private_value(),
            external_identity_hash,
        )
    detail = _history_detail(actor_id, run_id, history)
    if _history_connection_key(detail) != connection_key:
        raise _conflict("TEHA-Quelllauf gehört zu einer anderen Verbindung.")
    if detail.get("history_status") != "completed" or detail.get("success") is not True:
        raise _conflict("TEHA-Quelllauf ist nicht vollständig bestätigt.")
    matches = [
        row
        for row in _source_candidates(detail, identity, connection_key)
        if digest(row) == source_sha256
    ]
    if len(matches) != 1:
        raise _conflict(
            "TEHA-Quellhash oder opaque Identität stimmt nicht mit dem Historienbeleg überein."
        )
    if digest(matches[0]) != source_sha256 or identity.token != external_identity_hash:
        raise _conflict("TEHA-Quellidentität wurde nicht unverändert bestätigt.")
    return detail, matches[0]


def _content_manifest(
    actor_id: str,
    run_id: str,
    connection_key: str,
    identity: ExternalIdentity,
    history=None,
) -> dict[str, Any]:
    if identity.kind != "document":
        raise HTTPException(422, "Dokumentinhalt benötigt Dokumentidentität.")
    detail = _history_detail(actor_id, run_id, history)
    if _history_connection_key(detail) != connection_key:
        raise _conflict("TEHA-Dokumentlauf gehört zu einer anderen Verbindung.")
    history_exchange(
        detail,
        expected_operation="read_document",
        expected_connection_key=connection_key,
    )
    args = _args(detail)
    expected = ExternalIdentity.create("document", lieg_nr=_part(args.get("lieg_nr"), "lieg_nr"), reference=_part(args.get("reference"), "reference"))
    manifest = (detail.get("details") or {}).get("result_manifest")
    if (
        detail.get("history_status") != "completed"
        or detail.get("success") is not True
        or expected != identity
        or not isinstance(manifest, dict)
    ):
        raise _conflict(
            "Dokumentinhalt ist nicht durch einen vollständigen TEHA-Historienlauf belegt."
        )
    parts = dict(identity.parts)
    sha256 = manifest.get("sha256")
    size_bytes = manifest.get("size_bytes")
    if (
        manifest.get("type") != "TehaDocumentContent"
        or manifest.get("reference") != parts.get("reference")
        or manifest.get("lieg_nr") != parts.get("lieg_nr")
        or not isinstance(sha256, str)
        or len(sha256) != 64
        or any(char not in "0123456789abcdef" for char in sha256)
        or type(size_bytes) is not int
        or size_bytes < 0
    ):
        raise _conflict("Dokumentmanifest ist unvollständig oder widersprüchlich.")
    exchange = history_exchange(
        detail,
        expected_operation="read_document",
        expected_connection_key=connection_key,
    )
    body = _body(exchange)
    content_marker = body.get("content")
    if (
        not isinstance(content_marker, dict)
        or content_marker.get("omitted") != "document_bytes"
        or content_marker.get("sha256") != sha256
        or content_marker.get("size_bytes") != size_bytes
    ):
        raise _conflict("Dokumentmanifest und verschlüsselter Quellenbeleg widersprechen sich.")
    return manifest


def _target_model(kind: str):
    return {
        "property": (PropertyORM, "properties"),
        "period": (BillingPeriodORM, "billing/periods"),
        "unit": (UnitORM, "units"),
        "user": (TenantORM, "tenants"),
        "technical_order": (TaskORM, "tasks"),
    }[kind]


def _lock_mapping_key(
    unit,
    connection_key: str,
    kind: str,
    external_identity_hash: str,
) -> None:
    """Serialize one external mapping identity without inventing another table."""
    if unit.db.get_bind().dialect.name != "postgresql":
        return
    lock_value = int.from_bytes(
        hashlib.sha256(
            f"immo-teha-mapping-v1\0{connection_key}\0{kind}\0{external_identity_hash}".encode(
                "utf-8"
            )
        ).digest()[:8],
        "big",
        signed=True,
    )
    unit.db.execute(
        text("SELECT pg_advisory_xact_lock(:mapping_lock)"),
        {"mapping_lock": lock_value},
    )


def _lock_import_key(
    unit,
    connection_key: str,
    source_kind: str,
    external_identity_hash: str,
) -> None:
    if unit.db.get_bind().dialect.name != "postgresql":
        return
    lock_value = int.from_bytes(
        hashlib.sha256(
            f"immo-teha-import-v1\0{connection_key}\0{source_kind}\0{external_identity_hash}".encode(
                "utf-8"
            )
        ).digest()[:8],
        "big",
        signed=True,
    )
    unit.db.execute(
        text("SELECT pg_advisory_xact_lock(:import_lock)"),
        {"import_lock": lock_value},
    )


def _locked_portfolio(unit, portfolio_id: str, *, lock: bool):
    statement = select(PortfolioORM).where(PortfolioORM.id == portfolio_id)
    if lock:
        statement = statement.with_for_update()
    row = unit.db.scalar(statement)
    if row is None:
        raise HTTPException(404, "Portfolio nicht zugänglich.")
    return row


def _target_binding(unit, kind: str, target_id: str, portfolio_id: str, *, lock: bool):
    model, collection = _target_model(kind)
    _locked_portfolio(unit, portfolio_id, lock=lock)

    def selected(model_type, identifier):
        statement = select(model_type).where(model_type.id == identifier)
        if lock:
            statement = statement.with_for_update()
        return unit.db.scalar(statement)

    local = {
        "portfolio_id": portfolio_id, "property_id": None, "unit_id": None,
        "tenant_id": None, "billing_period_id": None,
    }
    if kind == "property":
        row = selected(PropertyORM, target_id)
        actual_portfolio = row.portfolio_id if row is not None else None
        if row is not None:
            local["property_id"] = row.id
    elif kind in {"period", "unit"}:
        parent_id = unit.db.scalar(
            select(model.property_id).where(model.id == target_id)
        )
        parent = selected(PropertyORM, parent_id) if parent_id is not None else None
        row = selected(model, target_id)
        if (
            row is None
            or parent is None
            or row.property_id != parent.id
        ):
            raise HTTPException(404, "Lokales Mappingziel oder dessen Parent wurde geändert.")
        actual_portfolio = parent.portfolio_id
        local["property_id"] = parent.id
        if kind == "unit":
            local["unit_id"] = row.id
        else:
            local["billing_period_id"] = row.id
    elif kind == "user":
        grant_stmt = select(ResourcePortfolioORM).where(
            ResourcePortfolioORM.resource_type == "tenants",
            ResourcePortfolioORM.resource_id == target_id,
            ResourcePortfolioORM.portfolio_id == portfolio_id,
        )
        if lock:
            grant_stmt = grant_stmt.with_for_update()
        grant = unit.db.scalar(grant_stmt)
        row = selected(TenantORM, target_id)
        actual_portfolio = portfolio_id if grant is not None and row is not None else None
        local["tenant_id"] = row.id if row is not None else None
    else:
        parent_values = unit.db.execute(
            select(TaskORM.property_id, TaskORM.unit_id).where(TaskORM.id == target_id)
        ).first()
        property_id = parent_values[0] if parent_values else None
        task_unit_id = parent_values[1] if parent_values else None
        parent = selected(PropertyORM, property_id) if property_id else None
        parent_unit = selected(UnitORM, task_unit_id) if task_unit_id else None
        row = selected(TaskORM, target_id)
        if (
            row is None
            or parent is None
            or row.property_id != parent.id
            or row.unit_id != task_unit_id
            or (task_unit_id is not None and parent_unit is None)
            or (
                parent_unit is not None
                and parent_unit.property_id != parent.id
            )
        ):
            raise HTTPException(404, "Lokaler Technikauftrag oder dessen Parent wurde geändert.")
        actual_portfolio = parent.portfolio_id
        local["property_id"] = parent.id
        local["unit_id"] = parent_unit.id if parent_unit is not None else None

    if row is None:
        raise HTTPException(404, "Lokales Mappingziel nicht gefunden.")
    if actual_portfolio != portfolio_id:
        raise HTTPException(404, "Lokales Mappingziel gehört nicht zum gewählten Portfolio.")
    return row, etag(collection, row.id, row.updated_at), local


def _mapping_reference(row) -> tuple[dict[str, Any], str]:
    try:
        return mapping_reference(row)
    except (TehaImportEvidenceError, ValueError):
        raise HTTPException(
            503, "Gespeicherte TEHA-Mappingreferenz ist beschädigt."
        ) from None


def _mapping_public(row) -> dict[str, Any]:
    reference, reference_sha = _mapping_reference(row)
    return {
        **{key: value for key, value in reference.items() if key != "external_identity"},
        "mapping_sha256": reference_sha,
        "confirmed_by": row.confirmed_by,
        "confirmed_at": row.confirmed_at.replace(tzinfo=timezone.utc).isoformat(),
    }


def confirm_mapping(
    store,
    payload: ConfirmMapping,
    actor_id: str,
    *,
    history=None,
    commit_authority: Any = None,
) -> dict[str, Any]:
    _require_root_commit_authority(commit_authority, actor_id)
    identity = _opaque(payload.identity)
    if identity.kind == "document":
        raise HTTPException(422, "Dokumentidentitäten werden importiert, nicht als Mappingziel gespeichert.")
    validate_identity_binding(identity.kind, identity.private_value(), payload.external_identity_hash)
    _verified_source(
        actor_id,
        payload.source_history_run_id,
        payload.connection_key,
        identity,
        payload.external_identity_hash,
        payload.source_sha256,
        history,
    )
    request_hash = digest(payload.model_dump(mode="json"))
    mapping_id = str(uuid5(NAMESPACE_URL, f"immo-teha-mapping:{actor_id}:{payload.idempotency_key}"))
    with _work(
        store,
        actor_id,
        write=True,
        commit_authority=commit_authority,
    ) as unit:
        # Common parent first: competing generation-1 commands for the same
        # external identity but different local targets must serialize on one
        # stable row before target/mapping locks diverge.
        _locked_portfolio(unit, payload.portfolio_id, lock=True)
        # Re-read the immutable encrypted source under the actual commit
        # attempt; preview-time history evidence is not a commit authority.
        _verified_source(
            actor_id,
            payload.source_history_run_id,
            payload.connection_key,
            identity,
            payload.external_identity_hash,
            payload.source_sha256,
            history,
        )
        target, target_etag, _ = _target_binding(
            unit,
            identity.kind,
            payload.target.target_id,
            payload.portfolio_id,
            lock=True,
        )
        if target_etag != payload.target.expected_target_etag:
            raise HTTPException(412, "Lokales Mappingziel wurde geändert.")
        existing = unit.db.get(TehaExternalMappingORM, mapping_id)
        if existing is not None:
            if (
                existing.revision != request_hash
                or existing.confirmed_by != actor_id
                or existing.source_history_run_id != payload.source_history_run_id
                or existing.source_sha256 != payload.source_sha256
            ):
                raise _conflict("Mapping-Vorgangsreferenz wurde bereits anders verwendet.")
            latest_generation = unit.db.scalar(
                select(func.max(TehaExternalMappingORM.generation)).where(
                    TehaExternalMappingORM.connection_key == payload.connection_key,
                    TehaExternalMappingORM.kind == identity.kind,
                    TehaExternalMappingORM.external_identity_hash == identity.token,
                )
            )
            if latest_generation != existing.generation:
                raise HTTPException(412, "Eine neuere Mappinggeneration ist vorhanden.")
            return _mapping_public(existing)
        latest = unit.db.scalar(select(TehaExternalMappingORM).where(
            TehaExternalMappingORM.connection_key == payload.connection_key,
            TehaExternalMappingORM.kind == identity.kind,
            TehaExternalMappingORM.external_identity_hash == identity.token,
        ).order_by(TehaExternalMappingORM.generation.desc()).limit(1).with_for_update())
        if latest is None:
            if payload.expected_previous_revision != "new":
                raise HTTPException(412, "Mappinggeneration existiert nicht mehr wie erwartet.")
            generation = 1
        else:
            if latest.revision != payload.expected_previous_revision:
                raise HTTPException(412, "Mappinggeneration wurde geändert.")
            generation = latest.generation + 1
        fields = {
            "internal_property_id": None, "billing_period_id": None, "unit_id": None, "tenant_id": None, "task_id": None
        }
        fields[{"property": "internal_property_id", "period": "billing_period_id", "unit": "unit_id", "user": "tenant_id", "technical_order": "task_id"}[identity.kind]] = target.id
        stamp = _now()
        row = TehaExternalMappingORM(
            id=mapping_id, portfolio_id=payload.portfolio_id, connection_key=payload.connection_key,
            kind=identity.kind, external_identity_hash=identity.token, external_identity_json=identity.private_value(),
            generation=generation, state="confirmed", revision=request_hash, confirmed_by=actor_id, confirmed_at=stamp,
            source_history_run_id=payload.source_history_run_id, source_sha256=payload.source_sha256, created_at=stamp, updated_at=stamp,
            **fields,
        )
        try:
            with unit.db.begin_nested():
                unit.db.add(row)
                unit.db.flush()
        except IntegrityError:
            # The failed insert is rolled back to its savepoint before the
            # conflict leaves this transaction. Never reinterpret a concurrent
            # winner as this actor/key's replay.
            raise _conflict("Mapping wurde parallel geändert.") from None
        return _mapping_public(row)


def _load_mapping(unit, payload: PreviewImport, *, lock: bool):
    statement = select(TehaExternalMappingORM).where(TehaExternalMappingORM.id == payload.mapping.mapping_id)
    if lock:
        statement = statement.with_for_update()
    row = unit.db.scalar(statement)
    if row is None or row.portfolio_id != payload.portfolio_id or row.connection_key != payload.connection_key:
        raise HTTPException(404, "Mapping nicht zugänglich.")
    if row.revision != payload.mapping.expected_revision or row.generation != payload.mapping.expected_generation:
        raise HTTPException(412, "Mappinggeneration wurde geändert.")
    latest = unit.db.scalar(select(func.max(TehaExternalMappingORM.generation)).where(
        TehaExternalMappingORM.connection_key == row.connection_key,
        TehaExternalMappingORM.kind == row.kind,
        TehaExternalMappingORM.external_identity_hash == row.external_identity_hash,
    ))
    if latest != row.generation:
        raise HTTPException(412, "Eine neuere Mappinggeneration ist vorhanden.")
    target_id = next(
        getattr(row, name)
        for name in (
            "internal_property_id",
            "billing_period_id",
            "unit_id",
            "tenant_id",
            "task_id",
        )
        if getattr(row, name) is not None
    )
    target, target_etag, local_binding = _target_binding(
        unit, row.kind, target_id, row.portfolio_id, lock=lock
    )
    canonical_identity = validate_identity_binding(
        row.kind,
        row.external_identity_json,
        row.external_identity_hash,
    )
    identity = ExternalIdentity.create(row.kind, **canonical_identity["parts"])
    target_kind = cast(
        TargetKind,
        {
            "property": "property",
            "period": "billing_period",
            "unit": "unit",
            "user": "tenant",
            "technical_order": "task",
        }[row.kind],
    )
    mapping = ExplicitMapping(identity, target_kind, target.id, row.generation)
    _, reference_sha = _mapping_reference(row)
    return row, mapping, target, target_etag, local_binding, reference_sha


def _detail_operation(detail: dict[str, Any]) -> str:
    payload = detail.get("payload")
    operation = payload.get("operation") if isinstance(payload, dict) else None
    if not isinstance(operation, str):
        raise TehaReceiveError("history_evidence_invalid")
    return operation


def _source_lieg_nr(
    detail: dict[str, Any],
    snapshot: dict[str, Any],
    identity: ExternalIdentity,
) -> str | None:
    if identity.kind == "document":
        value = dict(identity.parts).get("lieg_nr")
        return value if isinstance(value, str) else None
    if identity.kind == "technical_order":
        value = snapshot.get("liegenschaftsnummer")
        return value if isinstance(value, str) else None
    return None


def _assert_mapping_parent_relation(
    source_detail: dict[str, Any],
    source_snapshot: dict[str, Any],
    source_identity: ExternalIdentity,
    mapping_identity: ExternalIdentity,
    mapping_snapshot: dict[str, Any],
) -> None:
    source_lieg_nr = _source_lieg_nr(
        source_detail, source_snapshot, source_identity
    )
    if mapping_identity.kind == "property":
        mapped_lieg_nr = mapping_snapshot.get("liegenschaftenNummer")
        if (
            source_lieg_nr is None
            or not isinstance(mapped_lieg_nr, str)
            or mapped_lieg_nr != source_lieg_nr
        ):
            raise _conflict(
                "TEHA-Quelle gehört nicht zur bestätigten externen Immobilie."
            )
        return
    if mapping_identity.kind == "unit":
        if source_identity.kind != "document":
            raise _conflict(
                "Technikaufträge benötigen ein bestätigtes Immobilienmapping."
            )
        parts = dict(mapping_identity.parts)
        if parts.get("lieg_nr") != source_lieg_nr:
            raise _conflict(
                "TEHA-Dokument und Einheitsmapping gehören zu verschiedenen Immobilien."
            )
        if _detail_operation(source_detail) != "list_documents":
            raise _conflict(
                "Einheitszuordnung benötigt den vollständigen TEHA-Dokumentlistenbeleg."
            )
        properties = source_snapshot.get("properties")
        observed_unit = (
            properties.get("Nutzereinheit_ID")
            if isinstance(properties, dict)
            else None
        )
        if observed_unit != parts.get("unit_id"):
            raise _conflict(
                "TEHA-Dokument gehört nicht zur bestätigten externen Einheit."
            )
        return
    raise HTTPException(
        422, "Import benötigt ein bestätigtes Property- oder Unit-Mapping."
    )


def _preview(
    unit,
    payload: PreviewImport,
    actor_id: str,
    proof: tuple[dict[str, Any], dict[str, Any]],
    *,
    lock: bool,
    history=None,
):
    identity = _opaque(payload.identity)
    if identity.token != payload.external_identity_hash:
        raise HTTPException(422, "Externe Identität und Hash stimmen nicht überein.")
    detail, snapshot = proof
    (
        mapping_row,
        mapping,
        _target,
        target_etag,
        local_binding,
        mapping_reference_sha,
    ) = _load_mapping(unit, payload, lock=lock)
    mapping_target_binding = dict(local_binding)
    _, mapping_snapshot = _verified_source(
        actor_id,
        mapping_row.source_history_run_id,
        mapping_row.connection_key,
        mapping.identity,
        mapping_row.external_identity_hash,
        mapping_row.source_sha256,
        history,
    )
    _assert_mapping_parent_relation(
        detail,
        snapshot,
        identity,
        mapping.identity,
        mapping_snapshot,
    )
    requirement = MappingRequirement(mapping.identity, mapping.target_kind)
    content_sha = content_size = None
    if payload.source_kind == "document":
        assert payload.content_history_run_id is not None
        manifest = _content_manifest(
            actor_id,
            payload.content_history_run_id,
            payload.connection_key,
            identity,
            history,
        )
        content_sha = cast(str, manifest["sha256"])
        content_size = cast(int, manifest["size_bytes"])
    evidence = ObservedEvidence(
        history_run_id=payload.source_history_run_id,
        identity=identity,
        source_snapshot=snapshot,
        source_sha256=payload.source_sha256,
        requirements=(requirement,),
        content_sha256=content_sha,
        content_size=content_size,
    )
    mapping_selection_sha = mapping_digest(
        evidence, MappingIndex((mapping,))
    )
    mapping_sha = mapping_reference_sha
    property_id = local_binding["property_id"]
    unit_id = local_binding["unit_id"]
    if not isinstance(property_id, str) or not property_id:
        raise HTTPException(503, "Bestätigtes Mapping besitzt keine lokale Immobilie.")
    target_etags = {"mapping_target": target_etag}
    contract_id = tenant_id = None
    if payload.source_kind == "document":
        doc_data = payload.document
        assert doc_data is not None
        contract_id = doc_data.contract_id
        if contract_id is not None:
            parent_values = unit.db.execute(
                select(
                    ContractORM.property_id,
                    ContractORM.unit_id,
                    ContractORM.tenant_id,
                ).where(ContractORM.id == contract_id)
            ).first()
            if parent_values is None or parent_values.property_id != property_id:
                raise HTTPException(404, "Dokumentvertrag passt nicht zum Mappingziel.")
            contract_unit_id = parent_values.unit_id
            unit_stmt = select(UnitORM).where(UnitORM.id == contract_unit_id)
            if lock:
                unit_stmt = unit_stmt.with_for_update()
            contract_unit = unit.db.scalar(unit_stmt)
            statement = select(ContractORM).where(ContractORM.id == contract_id)
            if lock:
                statement = statement.with_for_update()
            contract = unit.db.scalar(statement)
            if (
                contract is None
                or contract_unit is None
                or contract.property_id != property_id
                or contract.unit_id != contract_unit.id
                or contract_unit.property_id != property_id
                or (unit_id is not None and contract.unit_id != unit_id)
            ):
                raise HTTPException(404, "Dokumentvertrag oder Einheit wurde geändert.")
            current = etag("contracts", contract.id, contract.updated_at)
            if current != doc_data.expected_contract_etag:
                raise HTTPException(412, "Dokumentvertrag wurde geändert.")
            unit_id = contract.unit_id
            tenant_id = contract.tenant_id
            target_etags["contract"] = current
            target_etags["contract_unit"] = etag(
                "units", contract_unit.id, contract_unit.updated_at
            )
        local_binding = {
            "portfolio_id": local_binding["portfolio_id"],
            "property_id": property_id,
            "unit_id": unit_id,
            "contract_id": contract_id,
            "tenant_id": tenant_id,
        }
        decision = PreviewDecision(
            "new",
            identity.token,
            payload.source_sha256,
            mapping_sha,
            content_sha,
            (),
        )
        doc_projection = document_projection(
            evidence,
            decision,
            property_id=property_id,
            unit_id=unit_id,
            contract_id=contract_id,
            title=doc_data.title,
            document_date=doc_data.document_date,
            document_type=doc_data.document_type,
        )
        projected = doc_projection.document.model_dump(mode="json")
    else:
        task_data = payload.task
        assert task_data is not None
        local_binding = {
            "portfolio_id": local_binding["portfolio_id"],
            "property_id": property_id,
            "unit_id": unit_id,
            "contract_id": None,
            "tenant_id": None,
        }
        decision = PreviewDecision(
            "new",
            identity.token,
            payload.source_sha256,
            mapping_sha,
            None,
            (),
        )
        projected_task = task_projection(
            evidence,
            decision,
            property_id=property_id,
            unit_id=unit_id,
            title=task_data.title,
            due_date=task_data.due_date,
            assignee=task_data.assignee,
            priority=task_data.priority,
        )
        projected = projected_task.task.model_dump(mode="json")
    latest_receipt = unit.db.scalar(
        select(TehaImportReceiptORM)
        .where(
            TehaImportReceiptORM.connection_key == payload.connection_key,
            TehaImportReceiptORM.source_kind == payload.source_kind,
            TehaImportReceiptORM.external_identity_hash == identity.token,
        )
        .order_by(
            TehaImportReceiptORM.imported_at.desc(),
            TehaImportReceiptORM.id.desc(),
        )
        .limit(1)
    )
    state, reasons = "new", []
    if latest_receipt is not None:
        if latest_receipt.mapping_generation != mapping_row.generation:
            state, reasons = "conflicting", ["mapping_generation_changed"]
        else:
            _verify_receipt_target(
                unit, latest_receipt, mapping_row=mapping_row
            )
            if (
                latest_receipt.source_sha256 == payload.source_sha256
                and latest_receipt.content_sha256 == content_sha
            ):
                state = "unchanged"
            else:
                state, reasons = "changed", ["source_or_content_changed"]
    proof_value = {
        "connection_key": payload.connection_key,
        "portfolio_id": payload.portfolio_id,
        "source_kind": payload.source_kind,
        "source_history_run_id": payload.source_history_run_id,
        "content_history_run_id": payload.content_history_run_id,
        "identity": identity.private_value(),
        "identity_hash": identity.token,
        "source_sha256": payload.source_sha256,
        "content_sha256": content_sha,
        "mapping_id": mapping_row.id,
        "mapping_generation": mapping_row.generation,
        "mapping_revision": mapping_row.revision,
        "mapping_reference_sha256": mapping_reference_sha,
        "mapping_target_binding": mapping_target_binding,
        "mapping_sha256": mapping_sha,
        "mapping_selection_sha256": mapping_selection_sha,
        "target_etags": target_etags,
        "local_binding": local_binding,
        "projection": projected,
        "state": state,
        "reasons": reasons,
    }
    # The confirmation hash binds source, mapping, current local ETags and
    # projection. Comparison state/reasons are informational and may change
    # from "new" to "unchanged" solely because this exact command succeeded;
    # excluding them keeps an idempotent replay possible without weakening any
    # source/target/mapping CAS.
    confirmation_value = {
        key: value
        for key, value in proof_value.items()
        if key not in {"state", "reasons"}
    }
    return {
        **proof_value,
        "preview_hash": digest(confirmation_value),
        "content_size": content_size,
    }


def preview_import(store, payload: PreviewImport, actor_id: str, *, history=None) -> dict[str, Any]:
    identity = _opaque(payload.identity)
    proof = _verified_source(
        actor_id,
        payload.source_history_run_id,
        payload.connection_key,
        identity,
        payload.external_identity_hash,
        payload.source_sha256,
        history,
    )
    with _work(store, actor_id) as unit:
        return _preview(unit, payload, actor_id, proof, lock=False, history=history)


def _receipt_public(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "portfolio_id": row.portfolio_id,
        "connection_key": row.connection_key,
        "source_history_run_id": row.source_history_run_id,
        "source_kind": row.source_kind,
        "external_identity_hash": row.external_identity_hash,
        "mapping_id": row.mapping_id,
        "mapping_generation": row.mapping_generation,
        "mapping_sha256": row.mapping_sha256,
        "source_sha256": row.source_sha256,
        "content_sha256": row.content_sha256,
        "document_id": row.document_id,
        "document_version_id": row.document_version_id,
        "task_id": row.task_id,
        "state": row.state,
        "imported_by": row.imported_by,
        "imported_at": row.imported_at.replace(tzinfo=timezone.utc).isoformat(),
    }


def _verify_receipt_target(unit, row, *, mapping_row=None) -> None:
    if mapping_row is None:
        mapping_row = unit.db.get(TehaExternalMappingORM, row.mapping_id)
    if (
        mapping_row is None
        or mapping_row.id != row.mapping_id
        or mapping_row.connection_key != row.connection_key
        or mapping_row.portfolio_id != row.portfolio_id
        or mapping_row.generation != row.mapping_generation
    ):
        raise HTTPException(
            503, "TEHA-Importbeleg verweist auf ein fehlendes oder widersprüchliches Mapping."
        )
    mapping_reference_value, mapping_sha = _mapping_reference(mapping_row)
    if row.mapping_sha256 != mapping_sha:
        raise HTTPException(
            503, "TEHA-Importbeleg und unveränderliche Mappingreferenz widersprechen sich."
        )
    _, _, mapping_target_binding = _target_binding(
        unit, mapping_row.kind, mapping_reference_value["target_id"],
        mapping_row.portfolio_id, lock=False,
    )

    if row.source_kind == "document":
        if not row.document_id or not row.document_version_id or not row.content_sha256:
            raise HTTPException(503, "TEHA-Dokumentbeleg ist unvollständig.")
        _document, binding = document_versions._document(
            unit.store, unit.db, row.document_id
        )
        version = document_versions._authorized_version(
            unit.store,
            unit.db,
            row.document_id,
            row.document_version_id,
            binding,
        )
        try:
            validate_document_manifest(
                version,
                row,
                version.metadata_snapshot,
                mapping=mapping_row,
                mapping_target_binding=mapping_target_binding,
            )
        except TehaImportEvidenceError:
            raise HTTPException(
                503, "TEHA-Originalmanifest ist beschädigt."
            ) from None
        for _ in document_versions.verified_blocks(unit.store, version):
            pass
        return

    if not row.task_id:
        raise HTTPException(503, "TEHA-Aufgabenbeleg ist unvollständig.")
    task = unit.db.get(TaskORM, row.task_id)
    if task is None:
        raise HTTPException(503, "TEHA-Aufgabenbeleg verweist auf eine fehlende Aufgabe.")
    if (
        task.property_id != mapping_target_binding["property_id"]
        or task.unit_id != mapping_target_binding["unit_id"]
    ):
        raise HTTPException(503, "TEHA-Aufgabenbeleg und lokales Mappingziel widersprechen sich.")


def _claimed_receipt(
    unit,
    row,
    *,
    actor_id: str,
    key: str,
    command_sha: str,
    mapping_row=None,
):
    if (
        row.imported_by != actor_id
        or row.command_key != key
        or row.command_sha256 != command_sha
    ):
        raise _conflict(
            "Dieser TEHA-Quellstand wurde bereits durch einen anderen Importbefehl übernommen."
        )
    _verify_receipt_target(unit, row, mapping_row=mapping_row)
    return _receipt_public(row)


def _existing_command(unit, actor_id: str, key: str, command_sha: str, *, mapping_row=None):
    row = unit.db.scalar(
        select(TehaImportReceiptORM).where(
            TehaImportReceiptORM.imported_by == actor_id,
            TehaImportReceiptORM.command_key == key,
        )
    )
    if row is None:
        return None
    return _claimed_receipt(
        unit,
        row,
        actor_id=actor_id,
        key=key,
        command_sha=command_sha,
        mapping_row=mapping_row,
    )


def import_document(
    store,
    payload: ImportDocument,
    content: bytes,
    actor_id: str,
    *,
    history=None,
    commit_authority: Any = None,
) -> dict[str, Any]:
    _require_root_commit_authority(commit_authority, actor_id)
    identity = _opaque(payload.preview.identity)
    if (
        not isinstance(content, bytes)
        or not content.startswith(b"%PDF-")
        or len(content) > settings.max_upload_size_bytes
    ):
        raise HTTPException(422, "Dokumentbytes sind kein zulässiges PDF.")
    content_sha = hashlib.sha256(content).hexdigest()
    command_sha = digest(
        {
            "command": payload.model_dump(mode="json"),
            "content_sha256": content_sha,
        }
    )
    with _work(
        store,
        actor_id,
        write=True,
        write_kind="document",
        commit_authority=commit_authority,
    ) as unit:
        _lock_import_key(
            unit,
            payload.preview.connection_key,
            "document",
            identity.token,
        )
        proof = _verified_source(
            actor_id,
            payload.preview.source_history_run_id,
            payload.preview.connection_key,
            identity,
            payload.preview.external_identity_hash,
            payload.preview.source_sha256,
            history,
        )
        content_manifest = _content_manifest(
            actor_id,
            payload.content_history_run_id,
            payload.preview.connection_key,
            identity,
            history,
        )
        if (
            content_sha != content_manifest["sha256"]
            or len(content) != content_manifest["size_bytes"]
        ):
            raise _conflict(
                "Dokumentbytes stimmen nicht mit dem TEHA-Historienbeleg überein."
            )
        current = _preview(
            unit,
            payload.preview,
            actor_id,
            proof,
            lock=True,
            history=history,
        )
        if current["preview_hash"] != payload.preview_hash or current["content_sha256"] != content_sha:
            raise HTTPException(412, "Importvorschau ist nicht mehr aktuell.")
        if current["state"] == "conflicting":
            raise _conflict("Importvorschau besitzt einen Mappingkonflikt.")
        mapping_row = unit.db.get(
            TehaExternalMappingORM, current["mapping_id"]
        )
        if mapping_row is None:
            raise HTTPException(503, "Bestätigtes TEHA-Mapping fehlt.")
        replay = _existing_command(
            unit,
            actor_id,
            payload.idempotency_key,
            command_sha,
            mapping_row=mapping_row,
        )
        if replay is not None:
            return replay
        duplicate = unit.db.scalar(select(TehaImportReceiptORM).where(
            TehaImportReceiptORM.connection_key == payload.preview.connection_key,
            TehaImportReceiptORM.source_kind == "document",
            TehaImportReceiptORM.external_identity_hash == identity.token,
            TehaImportReceiptORM.source_sha256 == payload.preview.source_sha256,
            TehaImportReceiptORM.content_sha256 == content_sha,
        ))
        if duplicate is not None:
            return _claimed_receipt(
                unit,
                duplicate,
                actor_id=actor_id,
                key=payload.idempotency_key,
                command_sha=command_sha,
                mapping_row=mapping_row,
            )
        receipt_id = str(uuid4())
        document_id = str(uuid4())
        document_values = dict(current["projection"])
        document_values["file_url"] = f"/uploads/teha-import/{document_id}.pdf"
        stamp = _now()
        document = Document.model_validate(
            {
                "id": document_id,
                **document_values,
                "created_at": stamp,
                "updated_at": stamp,
            }
        )
        binding = dict(current["local_binding"])
        if (
            binding.get("portfolio_id") != payload.preview.portfolio_id
            or binding.get("property_id") != document.property_id
            or binding.get("unit_id") != document.unit_id
            or binding.get("contract_id") != document.contract_id
        ):
            raise HTTPException(503, "TEHA-Dokumentprojektion und lokale Bindung widersprechen sich.")
        unit.db.connection().execute(
            cast(Table, DocumentORM.__table__).insert(), document.model_dump()
        )
        manifest = build_document_manifest(
            receipt_id=receipt_id,
            actor_id=actor_id,
            command_sha256=command_sha,
            connection_key=payload.preview.connection_key,
            source_history_run_id=payload.preview.source_history_run_id,
            content_history_run_id=payload.content_history_run_id,
            external_identity_hash=identity.token,
            source_sha256=payload.preview.source_sha256,
            content_sha256=content_sha,
            mapping_id=current["mapping_id"],
            mapping_generation=current["mapping_generation"],
            mapping_sha256=current["mapping_sha256"],
            local_binding=binding,
            mapping_target_binding=current["mapping_target_binding"],
            document_type=cast(str, document.document_type),
        )
        version = document_versions.publish_generated_original(
            unit.store,
            unit.db,
            document,
            binding,
            actor_id,
            content,
            command_sha,
            metadata_extra={"teha_import": manifest},
        )
        receipt = TehaImportReceiptORM(
            id=receipt_id,
            portfolio_id=payload.preview.portfolio_id,
            connection_key=payload.preview.connection_key,
            operational_job_id=None,
            work_item_id=None,
            source_history_run_id=payload.preview.source_history_run_id,
            source_kind="document",
            external_identity_hash=identity.token,
            mapping_generation=current["mapping_generation"],
            mapping_id=current["mapping_id"],
            mapping_sha256=current["mapping_sha256"],
            source_sha256=payload.preview.source_sha256,
            content_sha256=content_sha,
            document_id=document.id,
            document_version_id=version.id,
            task_id=None,
            state="imported",
            command_key=payload.idempotency_key,
            command_sha256=command_sha,
            imported_by=actor_id,
            imported_at=stamp,
        )
        unit.db.add(receipt)
        unit.db.flush()
        try:
            validate_document_manifest(
                version, receipt, version.metadata_snapshot, mapping=mapping_row,
                mapping_target_binding=current["mapping_target_binding"],
            )
        except TehaImportEvidenceError:
            raise HTTPException(503, "TEHA-Originalmanifest konnte nicht bestätigt werden.") from None
        for _ in document_versions.verified_blocks(unit.store, version):
            pass
        return _receipt_public(receipt)


def import_technical_order(
    store,
    payload: ImportTechnicalOrder,
    actor_id: str,
    *,
    history=None,
    commit_authority: Any = None,
) -> dict[str, Any]:
    _require_root_commit_authority(commit_authority, actor_id)
    identity = _opaque(payload.preview.identity)
    command_sha = digest(payload.model_dump(mode="json"))
    with _work(
        store,
        actor_id,
        write=True,
        write_kind="task",
        commit_authority=commit_authority,
    ) as unit:
        _lock_import_key(
            unit,
            payload.preview.connection_key,
            "technical_order",
            identity.token,
        )
        proof = _verified_source(
            actor_id,
            payload.preview.source_history_run_id,
            payload.preview.connection_key,
            identity,
            payload.preview.external_identity_hash,
            payload.preview.source_sha256,
            history,
        )
        current = _preview(
            unit,
            payload.preview,
            actor_id,
            proof,
            lock=True,
            history=history,
        )
        if current["preview_hash"] != payload.preview_hash:
            raise HTTPException(412, "Importvorschau ist nicht mehr aktuell.")
        if current["state"] == "conflicting":
            raise _conflict("Importvorschau besitzt einen Mappingkonflikt.")
        mapping_row = unit.db.get(
            TehaExternalMappingORM, current["mapping_id"]
        )
        if mapping_row is None:
            raise HTTPException(503, "Bestätigtes TEHA-Mapping fehlt.")
        replay = _existing_command(
            unit,
            actor_id,
            payload.idempotency_key,
            command_sha,
            mapping_row=mapping_row,
        )
        if replay is not None:
            return replay
        duplicate = unit.db.scalar(
            select(TehaImportReceiptORM).where(
                TehaImportReceiptORM.connection_key
                == payload.preview.connection_key,
                TehaImportReceiptORM.source_kind == "technical_order",
                TehaImportReceiptORM.external_identity_hash == identity.token,
                TehaImportReceiptORM.source_sha256
                == payload.preview.source_sha256,
            )
        )
        if duplicate is not None:
            return _claimed_receipt(
                unit,
                duplicate,
                actor_id=actor_id,
                key=payload.idempotency_key,
                command_sha=command_sha,
                mapping_row=mapping_row,
            )
        task_data = payload.preview.task
        assert task_data is not None
        local_binding = current["local_binding"]
        decision = PreviewDecision(
            "new",
            identity.token,
            payload.preview.source_sha256,
            current["mapping_sha256"],
            None,
            (),
        )
        evidence = ObservedEvidence(
            payload.preview.source_history_run_id,
            identity,
            proof[1],
            payload.preview.source_sha256,
            (),
        )
        projection = task_projection(
            evidence,
            decision,
            property_id=local_binding["property_id"],
            unit_id=local_binding["unit_id"],
            title=task_data.title,
            due_date=task_data.due_date,
            assignee=task_data.assignee,
            priority=task_data.priority,
        )
        task = BaseRepository(
            unit.db, TaskORM, Task, "Aufgabe nicht gefunden"
        ).create(projection.task)
        if task.status != "open":
            raise HTTPException(
                503,
                "Technikauftrag wurde nicht als offene lokale Aufgabe angelegt.",
            )
        stamp = _now()
        receipt = TehaImportReceiptORM(
            id=str(uuid4()),
            portfolio_id=payload.preview.portfolio_id,
            connection_key=payload.preview.connection_key,
            operational_job_id=None,
            work_item_id=None,
            source_history_run_id=payload.preview.source_history_run_id,
            source_kind="technical_order",
            external_identity_hash=identity.token,
            mapping_generation=current["mapping_generation"],
            mapping_id=current["mapping_id"],
            mapping_sha256=current["mapping_sha256"],
            source_sha256=payload.preview.source_sha256,
            content_sha256=None,
            document_id=None,
            document_version_id=None,
            task_id=task.id,
            state="imported",
            command_key=payload.idempotency_key,
            command_sha256=command_sha,
            imported_by=actor_id,
            imported_at=stamp,
        )
        unit.db.add(receipt)
        unit.db.flush()
        _verify_receipt_target(unit, receipt, mapping_row=mapping_row)
        return _receipt_public(receipt)


def prepare_document_download(
    store,
    receipt_id: str,
    actor_id: str,
    *,
    parent=None,
):
    with _work(store, actor_id) as unit:
        row = unit.db.get(TehaImportReceiptORM, receipt_id)
        if row is None or row.source_kind != "document":
            raise HTTPException(404, "TEHA-Dokumentimport nicht gefunden.")
        _verify_receipt_target(unit, row)
        document_id, version_id = row.document_id, row.document_version_id
    assert document_id is not None and version_id is not None
    return document_versions.prepare_download(
        store,
        document_id,
        version_id,
        actor_id,
        parent=parent,
    )
