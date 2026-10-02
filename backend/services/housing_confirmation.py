"""Stateless review and immutable publication of Wohnungsgeberbestätigungen."""

from __future__ import annotations

import hashlib
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from heapq import nlargest
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import Table, and_, or_, select
from sqlalchemy.orm import Session

from .. import auth
from ..db.contract_wizard_models import ContractDraftORM
from ..db.document_version_models import (
    DOCUMENT_VERSION_MODELS,
    DocumentVersionORM,
)
from ..db.orm_models import DocumentORM
from ..models import Document, DocumentCreate
from ..permissions import may_write_resource
from ..storage import NotFoundError
from . import document_versions
from .concurrency import etag
from .contract_occupancy import begin_writer
from .housing_confirmation_render import render_pdf
from .housing_confirmation_types import (
    CorrectionReference,
    PreviewRequest,
    SaveRequest,
    SourceEtags,
)
from .housing_confirmation_validation import (
    PDF_FORMAT_VERSION,
    SCHEMA_VERSION,
    HousingConfirmationValidationError,
    digest,
    validate_housing_confirmation_snapshot,
)
from .portfolio_scope import (
    current_scope,
    refresh_scope,
    scope_context,
    scope_from_user,
)
from .tenancy_workflow import decode_cursor, encode_cursor
from .tenant_privacy import PrivacyConflict
from .tenant_privacy_fence import lock_subject_write_fence, memory_account_fence

DOC_TYPE = "housing_confirmation"
VIRTUAL_PREFIX = "housing-confirmations/"


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _identity(actor_id: str, *, write: bool = False):
    user = auth.get_user_by_id(actor_id)
    if not user or not user["is_active"]:
        raise HTTPException(401, "Anmeldung nicht mehr gültig.")
    if write and not (
        may_write_resource(user["role"], "contracts")
        and may_write_resource(user["role"], "documents")
    ):
        raise HTTPException(
            403,
            "Wohnungsgeberbestätigungen dürfen nur mit Vertrags- und Dokumentrechten freigegeben werden.",
        )
    captured = current_scope()
    if captured is not None and captured.user_id != actor_id:
        raise HTTPException(403, "Ungültige Benutzerbindung.")
    return user, (
        refresh_scope(captured)
        if captured is not None
        else scope_from_user(user)
    )


class Work:
    def __init__(self, store, db, captured, user):
        self.store, self.db, self.captured, self.user = store, db, captured, user
        self.undo: dict[tuple[str, Any], tuple[bool, Any]] = {}

    def touch(self, collection: str, key: Any, *, inserted: bool = False):
        if self.db is not None or (collection, key) in self.undo:
            return
        rows = self.store.__dict__.setdefault(collection, {})
        self.undo[collection, key] = (
            key in rows and not inserted,
            deepcopy(rows.get(key)) if not inserted else None,
        )

    def rollback(self):
        for (collection, key), (present, value) in reversed(list(self.undo.items())):
            rows = self.store.__dict__.setdefault(collection, {})
            if present:
                rows[key] = value
            else:
                rows.pop(key, None)


@contextmanager
def _account_fence(store, *, sqlite_staged=False):
    try:
        with memory_account_fence(store, sqlite_staged=sqlite_staged):
            yield
    except PrivacyConflict as error:
        raise HTTPException(409, str(error)) from None


@contextmanager
def work(store, actor_id: str, *, write: bool = False):
    sql = hasattr(store, "db")
    # SQLite must acquire its writer before Memory account management. Keep
    # the account fence outside the real commit, including its rollback path.
    # PostgreSQL SQL accounts are fenced by the parent lock in _parents.
    with ExitStack() as fences:
        fences.enter_context(_account_fence(store))
        user, captured = _identity(actor_id, write=write)
        with scope_context(captured):
            if sql:
                from ..repositories.sql_store import SQLAlchemyStore

                bind = store.db.get_bind()
                db = Session(
                    getattr(bind, "engine", bind),
                    autoflush=False,
                    expire_on_commit=False,
                )
                active = SQLAlchemyStore(db)
            else:
                db, active = None, store
                for model in DOCUMENT_VERSION_MODELS:
                    active.__dict__.setdefault(model.__tablename__, {})
            unit = Work(active, db, captured, user)
            try:
                if db is not None and write:
                    begin_writer(db)
                    fences.enter_context(_account_fence(active, sqlite_staged=True))
                    refresh_scope(captured)
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


def _wizard_snapshot(unit: Work, contract) -> dict | None:
    if unit.db is not None:
        row = unit.db.scalar(
            select(ContractDraftORM)
            .where(
                ContractDraftORM.contract_id == contract.id,
                ContractDraftORM.state.in_(("committed", "signed")),
            )
            .order_by(ContractDraftORM.updated_at.desc(), ContractDraftORM.id.desc())
            .limit(1)
        )
    else:
        row = max(
            (
                value
                for value in unit.store.__dict__.get(
                    ContractDraftORM.__tablename__, {}
                ).values()
                if value.contract_id == contract.id
                and value.state in {"committed", "signed"}
            ),
            key=lambda value: (value.updated_at, value.id),
            default=None,
        )
    if row is None:
        return None
    data = row.data
    if (
        row.published_tenant_id != contract.tenant_id
        or data.get("property_id") != contract.property_id
        or data.get("unit_id") != contract.unit_id
        or not isinstance(data.get("landlord_name"), str)
        or not isinstance(data.get("landlord_address"), str)
    ):
        raise HTTPException(
            503,
            "Der veröffentlichte Vertragsassistent besitzt eine widersprüchliche Quellenbindung.",
        )
    return {
        "id": row.id,
        "revision": row.revision,
        "review_hash": row.review_hash,
        "landlord_name": data["landlord_name"],
        "landlord_address": data["landlord_address"],
    }


def _address(prop) -> str | None:
    lines = []
    if prop.address_line:
        lines.append(prop.address_line)
    city = " ".join(value for value in (prop.postal_code, prop.city) if value)
    if city:
        lines.append(city)
    if prop.country:
        lines.append(prop.country)
    return "\n".join(lines) or None


def _parents(unit: Work, contract_id: str, *, lock: bool = False):
    contract = unit.store.get_contract(contract_id)
    original = (
        contract.property_id,
        contract.unit_id,
        contract.tenant_id,
    )
    if lock:
        try:
            lock_subject_write_fence(unit.store, contract.tenant_id)
        except PrivacyConflict as error:
            raise HTTPException(409, str(error)) from None
        contract = unit.store.get_contract(contract_id)
        if original != (
            contract.property_id,
            contract.unit_id,
            contract.tenant_id,
        ):
            raise HTTPException(
                409,
                "Die Vertragszuordnung wurde während der Prüfung geändert.",
            )
    prop = unit.store.get_property(contract.property_id)
    location = unit.store.get_unit(contract.unit_id)
    tenant = unit.store.get_tenant(contract.tenant_id)
    portfolio = unit.store.get_portfolio(prop.portfolio_id)
    if location.property_id != prop.id:
        raise HTTPException(503, "Widersprüchliche Vertragszuordnung. Bestand prüfen.")
    return contract, prop, location, tenant, portfolio


def _source_snapshot(unit: Work, contract, prop, location, tenant, portfolio):
    wizard = _wizard_snapshot(unit, contract)
    source = {
        "portfolio": {
            "id": portfolio.id,
            "name": portfolio.name,
            "owner_name": portfolio.owner_name,
        },
        "property": {
            "id": prop.id,
            "portfolio_id": prop.portfolio_id,
            "name": prop.name,
            "address_line": prop.address_line,
            "postal_code": prop.postal_code,
            "city": prop.city,
            "country": prop.country,
        },
        "unit": {
            "id": location.id,
            "property_id": location.property_id,
            "label": location.label,
        },
        "contract": {
            "id": contract.id,
            "contract_number": contract.contract_number,
            "property_id": contract.property_id,
            "unit_id": contract.unit_id,
            "tenant_id": contract.tenant_id,
            "status": contract.status,
            "start_date": contract.start_date.isoformat(),
            "end_date": contract.end_date.isoformat()
            if contract.end_date
            else None,
        },
        "tenant": {
            "id": tenant.id,
            "full_name": tenant.full_name,
        },
        "wizard": wizard,
    }
    etags = SourceEtags(
        portfolio=etag("portfolios", portfolio.id, portfolio.updated_at),
        contract=etag("contracts", contract.id, contract.updated_at),
        property=etag("properties", prop.id, prop.updated_at),
        unit=etag("units", location.id, location.updated_at),
        tenant=etag("tenants", tenant.id, tenant.updated_at),
        wizard_revision=digest(wizard) if wizard is not None else None,
    )
    source["etags"] = etags.model_dump(mode="json")
    return source, etags


def source(store, contract_id: str, actor_id: str) -> dict[str, Any]:
    with work(store, actor_id) as unit:
        contract, prop, location, tenant, portfolio = _parents(unit, contract_id)
        snapshot, revisions = _source_snapshot(
            unit, contract, prop, location, tenant, portfolio
        )
        wizard = snapshot["wizard"]
        return {
            "contract_id": contract.id,
            "source": snapshot,
            "source_etags": revisions.model_dump(mode="json"),
            "suggestions": {
                "housing_provider_name": wizard["landlord_name"] if wizard else None,
                "housing_provider_address": wizard["landlord_address"] if wizard else None,
                "owner_name": portfolio.owner_name,
                "apartment_address": _address(prop),
                "apartment_label": location.label,
                "resident_names": [tenant.full_name],
                "contract_start_date_for_reference": contract.start_date.isoformat(),
                "actual_move_in_date": None,
            },
            "policy": {
                "main_tenant_is_suggestion_only": True,
                "contract_start_is_not_actual_move_in": True,
                "handover_date_is_not_actual_move_in": True,
                "additional_residents_require_explicit_input": True,
            },
        }


def _assert_source_etags(expected: SourceEtags, actual: SourceEtags):
    if expected != actual:
        raise HTTPException(
            412,
            "Vertrag, Objekt, Einheit, Mieter oder geprüfte Vertragsquelle wurden geändert. Vorschau neu laden.",
        )


def _load_correction(
    unit: Work,
    contract,
    reference: CorrectionReference | None,
) -> dict | None:
    if reference is None:
        return None
    try:
        document = unit.store.get_document(reference.document_id)
    except NotFoundError:
        raise HTTPException(404, "Korrekturbeleg nicht zugänglich.") from None
    if document.contract_id != contract.id:
        raise HTTPException(404, "Korrekturbeleg nicht zugänglich.")
    document, binding = document_versions._document(
        unit.store, unit.db, document.id
    )
    row = document_versions._authorized_version(
        unit.store,
        unit.db,
        document.id,
        reference.version_id,
        binding,
    )
    _validated_evidence(row)
    for _ in document_versions.verified_blocks(unit.store, row):
        pass
    return {
        "document_id": document.id,
        "version_id": row.id,
    }


def _review(
    unit: Work,
    contract_id: str,
    payload: PreviewRequest | SaveRequest,
    *,
    lock: bool = False,
):
    contract, prop, location, tenant, portfolio = _parents(
        unit, contract_id, lock=lock
    )
    snapshot, revisions = _source_snapshot(
        unit, contract, prop, location, tenant, portfolio
    )
    _assert_source_etags(payload.source_etags, revisions)
    correction = _load_correction(unit, contract, payload.correction_of)
    base = {
        "format_version": PDF_FORMAT_VERSION,
        "data": payload.data.model_dump(mode="json"),
        "source": snapshot,
        "correction_of": correction,
    }
    pdf = render_pdf(base)
    pdf_sha256 = hashlib.sha256(pdf).hexdigest()
    review = {**base, "pdf_sha256": pdf_sha256}
    return contract, prop, location, tenant, review, digest(review), pdf


def preview(
    store,
    contract_id: str,
    payload: PreviewRequest,
    actor_id: str,
) -> dict[str, Any]:
    with work(store, actor_id) as unit:
        _, _, _, _, review, review_hash, pdf = _review(
            unit, contract_id, payload
        )
        return {
            "review_hash": review_hash,
            "pdf_sha256": review["pdf_sha256"],
            "review": review,
            "size_bytes": len(pdf),
            "state": "preview",
            "signature_recorded": False,
            "authority_transmission_recorded": False,
        }


def preview_pdf(
    store,
    contract_id: str,
    payload: PreviewRequest,
    actor_id: str,
) -> tuple[bytes, str, str]:
    with work(store, actor_id) as unit:
        _, _, _, _, review, review_hash, pdf = _review(
            unit, contract_id, payload
        )
        return pdf, review["pdf_sha256"], review_hash


def _document_id(actor_id: str, command_key: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"immo-manager:housing-confirmation:v1:{actor_id}:{command_key}",
        )
    )


def _request_hash(contract_id: str, payload: SaveRequest) -> str:
    return digest(
        {
            "operation": "publish_housing_confirmation",
            "contract_id": contract_id,
            "payload": payload.model_dump(mode="json"),
        }
    )


def _head(unit: Work, document_id: str):
    return document_versions._head(unit.store, unit.db, document_id)


def _validated_evidence(row) -> dict[str, Any]:
    try:
        document_versions.validate_manifest(row)
        return validate_housing_confirmation_snapshot(
            row, row.metadata_snapshot
        )
    except HousingConfirmationValidationError:
        raise HTTPException(
            503,
            "Die archivierte Wohnungsgeberbestätigung ist beschädigt.",
        ) from None


def _public(row) -> dict[str, Any]:
    evidence = _validated_evidence(row)
    review = evidence["review"]
    return {
        "document_id": row.document_id,
        "version_id": row.id,
        "contract_id": row.contract_id,
        "review_hash": evidence["review_hash"],
        "pdf_sha256": row.sha256,
        "data": deepcopy(review["data"]),
        "correction_of": deepcopy(review["correction_of"]),
        "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "file_url": row.metadata_snapshot["file_url"],
        "download_url": (
            f"/contracts/{row.contract_id}/housing-confirmations/"
            f"{row.document_id}/download"
        ),
        "version_download_url": (
            f"/documents/{row.document_id}/versions/{row.id}/download"
        ),
        "signature_recorded": False,
        "authority_transmission_recorded": False,
    }


def _replay(
    unit: Work,
    contract,
    document: Document,
    request_hash: str,
    payload: SaveRequest,
):
    if (
        document.contract_id != contract.id
        or document.property_id != contract.property_id
        or document.unit_id != contract.unit_id
        or document.file_url
        != f"/uploads/{VIRTUAL_PREFIX}{document.id}.pdf"
    ):
        raise HTTPException(
            409,
            "Die Vorgangsreferenz ist bereits mit einem anderen Dokument belegt.",
        )
    row = _head(unit, document.id)
    if row is None:
        raise HTTPException(
            503,
            "Die gespeicherte Bestätigung besitzt kein archiviertes Original.",
        )
    if row.request_sha256 != request_hash or row.actor_id != unit.captured.user_id:
        raise HTTPException(
            409,
            "Die Vorgangsreferenz wurde bereits mit anderen Eingaben verwendet.",
        )
    evidence = _validated_evidence(row)
    if evidence["review_hash"] != payload.review_hash:
        raise HTTPException(
            409,
            "Die Vorgangsreferenz wurde bereits mit einer anderen Vorschau verwendet.",
        )
    _, binding = document_versions._document(
        unit.store, unit.db, document.id
    )
    document_versions._authorized_version(
        unit.store, unit.db, document.id, row.id, binding
    )
    for _ in document_versions.verified_blocks(unit.store, row):
        pass
    return _public(row)


def publish(
    store,
    contract_id: str,
    payload: SaveRequest,
    actor_id: str,
) -> dict[str, Any]:
    request_hash = _request_hash(contract_id, payload)
    document_id = _document_id(actor_id, payload.idempotency_key)
    with work(store, actor_id, write=True) as unit:
        contract, _, _, _, _ = _parents(unit, contract_id)
        try:
            existing = unit.store.get_document(document_id)
        except NotFoundError:
            existing = None
        if existing is not None:
            return _replay(
                unit, contract, existing, request_hash, payload
            )

        (
            contract,
            prop,
            location,
            tenant,
            review,
            review_hash,
            pdf,
        ) = _review(unit, contract_id, payload, lock=True)
        if review_hash != payload.review_hash:
            raise HTTPException(
                409,
                "Die freizugebende Fassung stimmt nicht mit der Vorschau überein.",
            )
        if review["pdf_sha256"] != hashlib.sha256(pdf).hexdigest():
            raise HTTPException(503, "Die PDF-Vorschau konnte nicht reproduziert werden.")

        stamp = now()
        file_url = f"/uploads/{VIRTUAL_PREFIX}{document_id}.pdf"
        values = {
            "id": document_id,
            **DocumentCreate(
                property_id=prop.id,
                unit_id=location.id,
                contract_id=contract.id,
                title=f"Wohnungsgeberbestätigung – {contract.contract_number}",
                document_type=DOC_TYPE,
                document_date=payload.data.issue_date,
                tags="wohnungsgeberbestaetigung",
                description="Lokal freigegebene Wohnungsgeberbestätigung",
                file_url=file_url,
            ).model_dump(),
            "ai_document_type": None,
            "ai_summary": None,
            "ai_entities_json": None,
            "ai_confidence": None,
            "ai_model": None,
            "ai_analyzed_at": None,
            "created_at": stamp,
            "updated_at": stamp,
        }
        document = Document.model_validate(values)
        if unit.db is not None:
            # Exact generated virtual key under already checked parent/scope
            # locks. Avoid the ordinary uploaded-file guard and, critically,
            # avoid the facade method that commits per document.
            unit.db.connection().execute(cast(Table, DocumentORM.__table__).insert(), values)
        else:
            unit.touch("documents", document.id, inserted=True)
            unit.store.__dict__["documents"][document.id] = document

        binding = {
            "portfolio_id": prop.portfolio_id,
            "property_id": prop.id,
            "unit_id": location.id,
            "contract_id": contract.id,
            "tenant_id": tenant.id,
        }
        extension = {
            "schema_version": SCHEMA_VERSION,
            "review": review,
            "review_hash": review_hash,
            "request_sha256": request_hash,
            "actor_id": actor_id,
            "idempotency_key": payload.idempotency_key,
            "confirmed_actual_move_in": payload.confirmed_actual_move_in,
            "confirmed_authority": payload.confirmed_authority,
            "confirmed_residents": payload.confirmed_residents,
        }
        row = document_versions.publish_generated_original(
            unit.store,
            unit.db,
            document,
            binding,
            actor_id,
            pdf,
            request_hash,
            before_insert=lambda collection, key: unit.touch(
                collection, key, inserted=True
            ),
            metadata_extra={"housing_confirmation": extension},
        )
        _validated_evidence(row)
        return _public(row)


def _cursor_binding(unit: Work, contract_id: str, limit: int) -> dict[str, Any]:
    scope = unit.captured
    return {
        "kind": "housing_confirmations",
        "user_id": scope.user_id,
        "role": scope.role,
        "unrestricted": scope.unrestricted,
        "portfolio_ids": list(scope.portfolio_ids),
        "contract_id": contract_id,
        "limit": limit,
    }


def listing(
    store,
    contract_id: str,
    actor_id: str,
    *,
    after: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    if type(limit) is not int or limit < 1 or limit > 500:
        raise HTTPException(422, "Bitte eine Seitengröße zwischen 1 und 500 wählen.")
    with work(store, actor_id) as unit:
        contract, _, _, _, _ = _parents(unit, contract_id)
        binding = _cursor_binding(unit, contract.id, limit)
        try:
            point = decode_cursor(after, binding)
        except HTTPException:
            raise HTTPException(
                422,
                "Ungültige oder abgelaufene Bestätigungsseite. Erste Seite neu laden.",
            ) from None
        point_time = point_id = None
        if point is not None:
            if (
                len(point) != 2
                or not all(isinstance(value, str) for value in point)
            ):
                raise HTTPException(422, "Ungültige Bestätigungsseite.")
            try:
                point_time = datetime.fromisoformat(point[0])
            except ValueError:
                raise HTTPException(422, "Ungültige Bestätigungsseite.") from None
            point_id = point[1]
        if unit.db is not None:
            model = DocumentVersionORM
            query = select(model).where(
                model.contract_id == contract.id,
                model.number == 1,
                model.metadata_snapshot["document_type"].as_string()
                == DOC_TYPE,
            )
            if point_time is not None:
                query = query.where(
                    or_(
                        model.created_at < point_time,
                        and_(
                            model.created_at == point_time,
                            model.id < point_id,
                        ),
                    )
                )
            found = list(
                unit.db.scalars(
                    query.order_by(
                        model.created_at.desc(), model.id.desc()
                    ).limit(limit + 1)
                )
            )
        else:
            rows = (
                row
                for row in unit.store.__dict__.get(
                    DocumentVersionORM.__tablename__, {}
                ).values()
                if row.contract_id == contract.id
                and row.number == 1
                and isinstance(row.metadata_snapshot, dict)
                and row.metadata_snapshot.get("document_type") == DOC_TYPE
                and (
                    point_time is None
                    or (row.created_at, row.id) < (point_time, point_id)
                )
            )
            found = nlargest(
                limit + 1,
                rows,
                key=lambda row: (row.created_at, row.id),
            )
        items = found[:limit]
        for row in items:
            document_versions.validate_manifest(row)
        return {
            "items": [_public(row) for row in items],
            "has_more": len(found) > limit,
            "next_cursor": (
                encode_cursor(
                    binding,
                    [items[-1].created_at.isoformat(), items[-1].id],
                )
                if len(found) > limit and items
                else None
            ),
        }


def prepare_download(
    store,
    contract_id: str,
    document_id: str,
    actor_id: str,
    *,
    parent=None,
):
    with work(store, actor_id) as unit:
        contract, _, _, _, _ = _parents(unit, contract_id)
        document = unit.store.get_document(document_id)
        if document.contract_id != contract.id:
            raise HTTPException(404, "Bestätigung nicht zugänglich.")
        row = _head(unit, document.id)
        if row is None:
            raise HTTPException(404, "Bestätigung nicht veröffentlicht.")
        document_versions.validate_manifest(row)
        version_id = row.id
    return document_versions.prepare_download(
        store, document_id, version_id, actor_id, parent=parent
    )


def read_pdf_for_key(store, key: str, actor_id: str):
    if not key.startswith(VIRTUAL_PREFIX) or not key.endswith(".pdf"):
        return None
    identifier = key[len(VIRTUAL_PREFIX) : -4]
    try:
        if str(UUID(identifier)) != identifier:
            return None
    except ValueError:
        return None
    with work(store, actor_id) as unit:
        document = unit.store.get_document(identifier)
        if document.file_url != f"/uploads/{key}":
            raise HTTPException(404, "Bestätigung nicht verfügbar.")
        document, binding = document_versions._document(
            unit.store, unit.db, document.id
        )
        row = _head(unit, document.id)
        if row is None:
            raise HTTPException(404, "Bestätigung nicht veröffentlicht.")
        row = document_versions._authorized_version(
            unit.store, unit.db, document.id, row.id, binding
        )
        _validated_evidence(row)
        return b"".join(document_versions.verified_blocks(unit.store, row))
