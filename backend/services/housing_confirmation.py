"""Wohnungsgeberbestätigung (§ 19 BMG): stateless review, then one immutable original.

The landlord confirms a tenancy's actual move-in for the residents' registration.
Nothing is filled in silently: the contract start and the main tenant are only
suggestions, the actual move-in date and every further resident are entered by
hand, and the three confirmations (actual move-in, authority to issue, list of
residents) are required. Preview and publication render the same PDF from the
same reviewed facts; the publication stores it as a document of type
`housing_confirmation` with an archived original (document_versions) in one
transaction. A correction is a new document with a new original that names the
one it corrects; the earlier original stays byte for byte.

Ported from the earlier release branch (f588c7fc), with the metadata format
`housing-confirmation/1` and PDF format `housing-confirmation-pdf/1` unchanged.
Adapted to this application:

* Rights: publishing needs write access to the contract's confirmations and to
  documents (backend/permissions.py), checked again under the account lock up to
  the commit (document_versions.work). Reading is open to every active user, as
  everywhere in this application (no portfolio read restriction exists yet).
* The contract wizard of the release branch is not part of this application:
  its source is always absent (`wizard: null`), no table of it is queried.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from copy import deepcopy
from datetime import datetime, timezone
from heapq import nlargest
from typing import Any
from urllib.parse import quote
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import HTTPException
from sqlalchemy import and_, insert, or_, select

from ..config import settings
from ..db.document_version_models import DocumentVersionORM
from ..db.orm_models import ContractORM, DocumentORM, PropertyORM, TenantORM, UnitORM
from ..models import Document, DocumentCreate
from ..storage import NotFoundError
from . import document_versions as archive
from .housing_confirmation_render import render_pdf
from .housing_confirmation_types import CorrectionReference, PreviewRequest, SaveRequest, SourceEtags
from .housing_confirmation_validation import (
    PDF_FORMAT_VERSION,
    SCHEMA_VERSION,
    HousingConfirmationValidationError,
    canonical,
    digest,
    validate_housing_confirmation_snapshot,
)

DOC_TYPE = "housing_confirmation"
VIRTUAL_PREFIX = "housing-confirmations/"
CURSOR_LIFETIME = 3600


def write_areas(contract_id: str) -> tuple[str, str]:
    return (f"/contracts/{contract_id}/housing-confirmations", archive.DOCUMENTS_AREA)


def etag(collection: str, entity_id: str, updated_at: datetime | str) -> str:
    stamp = updated_at if isinstance(updated_at, datetime) else datetime.fromisoformat(updated_at)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    text = stamp.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return f'"immo-v1:{quote(collection, safe="")}:{quote(entity_id, safe="")}:{text}"'


# ─── Source: contract, unit, property, tenant ────────────────────────────────

def _parents(unit: archive.Unit, contract_id: str, *, lock: bool = False):
    """The contract and its subject; with `lock` (SQL) locked in the archive's order and read again."""
    store = unit.store
    contract = store.get_contract(contract_id)
    if lock and unit.db is not None:
        before = (contract.property_id, contract.unit_id, contract.tenant_id)
        for model, key in ((TenantORM, contract.tenant_id), (PropertyORM, contract.property_id),
                           (UnitORM, contract.unit_id), (ContractORM, contract.id)):
            if unit.db.scalar(select(model.id).where(model.id == key).with_for_update()) is None:
                raise HTTPException(404, "Vertrag oder Zuordnung nicht mehr vorhanden.")
        unit.db.expire_all()
        contract = store.get_contract(contract_id)
        if before != (contract.property_id, contract.unit_id, contract.tenant_id):
            raise HTTPException(409, "Die Vertragszuordnung wurde während der Prüfung geändert.")
    prop = store.get_property(contract.property_id)
    location = store.get_unit(contract.unit_id)
    tenant = store.get_tenant(contract.tenant_id)
    portfolio = store.get_portfolio(prop.portfolio_id)
    if location.property_id != prop.id:
        raise HTTPException(503, "Einheit und Objekt des Vertrags passen nicht zusammen. Bestand prüfen.")
    return contract, prop, location, tenant, portfolio


def _address(prop) -> str | None:
    lines = [prop.address_line] if prop.address_line else []
    city = " ".join(value for value in (prop.postal_code, prop.city) if value)
    if city:
        lines.append(city)
    if getattr(prop, "country", None):
        lines.append(prop.country)
    return "\n".join(lines) or None


def _source_snapshot(contract, prop, location, tenant, portfolio) -> tuple[dict, SourceEtags]:
    source: dict[str, Any] = {
        "portfolio": {"id": portfolio.id, "name": portfolio.name, "owner_name": portfolio.owner_name},
        "property": {"id": prop.id, "portfolio_id": prop.portfolio_id, "name": prop.name,
                     "address_line": prop.address_line, "postal_code": prop.postal_code, "city": prop.city,
                     "country": getattr(prop, "country", None)},
        "unit": {"id": location.id, "property_id": location.property_id, "label": location.label},
        "contract": {"id": contract.id, "contract_number": contract.contract_number,
                     "property_id": contract.property_id, "unit_id": contract.unit_id,
                     "tenant_id": contract.tenant_id, "status": contract.status,
                     "start_date": contract.start_date.isoformat(),
                     "end_date": contract.end_date.isoformat() if contract.end_date else None},
        "tenant": {"id": tenant.id, "full_name": tenant.full_name},
        "wizard": None,
    }
    etags = SourceEtags(
        portfolio=etag("portfolios", portfolio.id, portfolio.updated_at),
        contract=etag("contracts", contract.id, contract.updated_at),
        property=etag("properties", prop.id, prop.updated_at),
        unit=etag("units", location.id, location.updated_at),
        tenant=etag("tenants", tenant.id, tenant.updated_at),
        wizard_revision=None,
    )
    source["etags"] = etags.model_dump(mode="json")
    return source, etags


def source(store, contract_id: str, actor_id: str) -> dict[str, Any]:
    with archive.work(store, actor_id) as unit:
        contract, prop, location, tenant, portfolio = _parents(unit, contract_id)
        snapshot, revisions = _source_snapshot(contract, prop, location, tenant, portfolio)
        return {
            "contract_id": contract.id,
            "source": snapshot,
            "source_etags": revisions.model_dump(mode="json"),
            "suggestions": {
                "housing_provider_name": portfolio.owner_name,
                "housing_provider_address": None,
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


# ─── Review (preview) ────────────────────────────────────────────────────────

def _validated_evidence(row) -> dict[str, Any]:
    archive.validate_manifest(row)
    try:
        evidence = validate_housing_confirmation_snapshot(row, row.metadata_snapshot)
    except HousingConfirmationValidationError:
        raise HTTPException(503, "Die archivierte Wohnungsgeberbestätigung ist beschädigt.") from None
    if not evidence:
        raise HTTPException(404, "Keine Wohnungsgeberbestätigung.")
    return evidence


def _load_correction(unit: archive.Unit, contract, reference: CorrectionReference | None) -> dict | None:
    if reference is None:
        return None
    try:
        document = unit.store.get_document(reference.document_id)
    except NotFoundError:
        raise HTTPException(404, "Die zu korrigierende Bestätigung ist nicht vorhanden.") from None
    if document.contract_id != contract.id or document.document_type != DOC_TYPE:
        raise HTTPException(404, "Die zu korrigierende Bestätigung gehört nicht zu diesem Vertrag.")
    _, binding = archive.bind_document(unit, document.id)
    row = archive.authorized_version(unit, document.id, reference.version_id, binding)
    _validated_evidence(row)
    for _ in archive.verified_blocks(unit, row):
        pass
    return {"document_id": document.id, "version_id": row.id}


def _review(unit: archive.Unit, contract_id: str, payload: PreviewRequest, *, lock: bool = False):
    contract, prop, location, tenant, portfolio = _parents(unit, contract_id, lock=lock)
    snapshot, revisions = _source_snapshot(contract, prop, location, tenant, portfolio)
    if payload.source_etags != revisions:
        raise HTTPException(412, "Vertrag, Objekt, Einheit oder Mieter wurden geändert. Bitte die Vorschau neu laden.")
    correction = _load_correction(unit, contract, payload.correction_of)
    base = {"format_version": PDF_FORMAT_VERSION, "data": payload.data.model_dump(mode="json"),
            "source": snapshot, "correction_of": correction}
    pdf = render_pdf(base)
    review = {**base, "pdf_sha256": hashlib.sha256(pdf).hexdigest()}
    return contract, prop, location, tenant, review, digest(review), pdf


def preview(store, contract_id: str, payload: PreviewRequest, actor_id: str) -> dict[str, Any]:
    with archive.work(store, actor_id) as unit:
        _, _, _, _, review, review_hash, pdf = _review(unit, contract_id, payload)
        return {"review_hash": review_hash, "pdf_sha256": review["pdf_sha256"], "review": review,
                "size_bytes": len(pdf), "state": "preview", "signature_recorded": False,
                "authority_transmission_recorded": False}


def preview_pdf(store, contract_id: str, payload: PreviewRequest, actor_id: str) -> tuple[bytes, str, str]:
    with archive.work(store, actor_id) as unit:
        _, _, _, _, review, review_hash, pdf = _review(unit, contract_id, payload)
        return pdf, review["pdf_sha256"], review_hash


# ─── Publication ─────────────────────────────────────────────────────────────

def document_id_for(actor_id: str, command_key: str) -> str:
    """The same actor and command key always name the same document (safe retry)."""
    return str(uuid5(NAMESPACE_URL, f"immo-manager:housing-confirmation:v1:{actor_id}:{command_key}"))


def _request_hash(contract_id: str, payload: SaveRequest) -> str:
    return digest({"operation": "publish_housing_confirmation", "contract_id": contract_id,
                   "payload": payload.model_dump(mode="json")})


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
        "download_url": f"/contracts/{row.contract_id}/housing-confirmations/{row.document_id}/download",
        "signature_recorded": False,
        "authority_transmission_recorded": False,
    }


def _replay(unit: archive.Unit, contract, document: Document, request_hash: str, payload: SaveRequest):
    """The same command again (e.g. after a lost answer): the stored original, checked; never a second one."""
    if (document.contract_id != contract.id or document.property_id != contract.property_id
            or document.unit_id != contract.unit_id
            or document.file_url != f"/uploads/{VIRTUAL_PREFIX}{document.id}.pdf"):
        raise HTTPException(409, "Die Vorgangsreferenz gehört bereits zu einem anderen Dokument.")
    row = archive.head(unit, document.id)
    if row is None:
        raise HTTPException(503, "Die gespeicherte Bestätigung hat kein archiviertes Original.")
    if row.request_sha256 != request_hash or row.actor_id != unit.actor_id:
        raise HTTPException(409, "Die Vorgangsreferenz wurde bereits mit anderen Eingaben verwendet.")
    evidence = _validated_evidence(row)
    if evidence["review_hash"] != payload.review_hash:
        raise HTTPException(409, "Die Vorgangsreferenz wurde bereits mit einer anderen Vorschau verwendet.")
    _, binding = archive.bind_document(unit, document.id)
    archive.authorized_version(unit, document.id, row.id, binding)
    for _ in archive.verified_blocks(unit, row):
        pass
    return _public(row)


def publish(store, contract_id: str, payload: SaveRequest, actor_id: str) -> dict[str, Any]:
    request_hash = _request_hash(contract_id, payload)
    document_id = document_id_for(actor_id, payload.idempotency_key)
    with archive.work(store, actor_id, write_areas=write_areas(contract_id)) as unit:
        # Locks first: a parallel request with the same key then finds this one's document.
        contract, _, _, _, _ = _parents(unit, contract_id, lock=True)
        try:
            existing = unit.store.get_document(document_id)
        except NotFoundError:
            existing = None
        if existing is not None:
            return _replay(unit, contract, existing, request_hash, payload)
        contract, prop, location, tenant, review, review_hash, pdf = _review(unit, contract_id, payload)
        if review_hash != payload.review_hash:
            raise HTTPException(409, "Die freizugebende Fassung stimmt nicht mit der Vorschau überein. "
                                     "Bitte die Vorschau neu laden.")

        stamp = archive.now()
        values = {
            "id": document_id,
            **DocumentCreate(
                property_id=prop.id, unit_id=location.id, contract_id=contract.id,
                title=f"Wohnungsgeberbestätigung – {contract.contract_number}", document_type=DOC_TYPE,
                document_date=payload.data.issue_date, tags="wohnungsgeberbestaetigung",
                description="Erzeugte und freigegebene Wohnungsgeberbestätigung",
                file_url=f"/uploads/{VIRTUAL_PREFIX}{document_id}.pdf",
            ).model_dump(),
            "ai_document_type": None, "ai_summary": None, "ai_entities_json": None, "ai_confidence": None,
            "ai_model": None, "ai_analyzed_at": None, "created_at": stamp, "updated_at": stamp,
        }
        document = Document.model_validate(values)
        if unit.db is not None:
            # Inside this transaction: the store's create_document() would commit on its own.
            unit.db.execute(insert(DocumentORM), values)
        else:
            unit.insert(unit.store.documents, document.id, document)

        binding = {"portfolio_id": prop.portfolio_id, "property_id": prop.id, "unit_id": location.id,
                   "contract_id": contract.id, "tenant_id": tenant.id}
        extension = {
            "schema_version": SCHEMA_VERSION, "review": review, "review_hash": review_hash,
            "request_sha256": request_hash, "actor_id": actor_id, "idempotency_key": payload.idempotency_key,
            "confirmed_actual_move_in": payload.confirmed_actual_move_in,
            "confirmed_authority": payload.confirmed_authority,
            "confirmed_residents": payload.confirmed_residents,
        }
        row = archive.publish_generated_original(unit, document, binding, pdf, request_hash,
                                                 version_id=str(uuid4()),
                                                 metadata_extra={"housing_confirmation": extension})
        _validated_evidence(row)
        return _public(row)


# ─── Reading published confirmations ─────────────────────────────────────────

_CURSOR_KEY = hashlib.sha256(b"immo-housing-cursor:" + settings.jwt_secret_key.encode()).digest()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def encode_cursor(binding: dict, position: list) -> str:
    issued = int(datetime.now(timezone.utc).timestamp())
    payload = canonical({"v": 1, "binding": digest(binding), "position": position, "expires": issued + CURSOR_LIFETIME})
    return _b64(payload) + "." + _b64(hmac.new(_CURSOR_KEY, payload, hashlib.sha256).digest())


def decode_cursor(cursor: str | None, binding: dict) -> list | None:
    if cursor is None:
        return None
    try:
        left, right = cursor.split(".", 1)
        payload = _unb64(left)
        if not hmac.compare_digest(_unb64(right), hmac.new(_CURSOR_KEY, payload, hashlib.sha256).digest()):
            raise ValueError("signature")
        value = json.loads(payload)
        if value.get("v") != 1 or value.get("binding") != digest(binding):
            raise ValueError("binding")
        if int(datetime.now(timezone.utc).timestamp()) >= value["expires"]:
            raise ValueError("expired")
        position = value["position"]
        if not isinstance(position, list) or len(position) != 2 or not all(isinstance(p, str) for p in position):
            raise ValueError("position")
        return position
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise HTTPException(422, "Ungültige oder abgelaufene Seite. Bitte die erste Seite neu laden.") from None


def listing(store, contract_id: str, actor_id: str, *, after: str | None = None, limit: int = 25) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= 500:
        raise HTTPException(422, "Bitte eine Seitengröße zwischen 1 und 500 wählen.")
    with archive.work(store, actor_id) as unit:
        contract, _, _, _, _ = _parents(unit, contract_id)
        binding = {"kind": "housing_confirmations", "user_id": unit.actor_id, "role": unit.user.get("role"),
                   "contract_id": contract.id, "limit": limit}
        point = decode_cursor(after, binding)
        point_time = datetime.fromisoformat(point[0]) if point else None
        point_id = point[1] if point else None
        if unit.db is not None:
            model = DocumentVersionORM
            query = select(model).where(model.contract_id == contract.id, model.number == 1,
                                        model.metadata_snapshot["document_type"].as_string() == DOC_TYPE)
            if point_time is not None:
                query = query.where(or_(model.created_at < point_time,
                                        and_(model.created_at == point_time, model.id < point_id)))
            found = list(unit.db.scalars(query.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)))
        else:
            assert unit.archive is not None
            found = nlargest(limit + 1, (
                row for row in unit.archive.versions.values()
                if row.contract_id == contract.id and row.number == 1
                and isinstance(row.metadata_snapshot, dict) and row.metadata_snapshot.get("document_type") == DOC_TYPE
                and (point_time is None or (row.created_at, row.id) < (point_time, point_id))),
                key=lambda row: (row.created_at, row.id))
        items = found[:limit]
        more = len(found) > limit
        return {
            "items": [_public(row) for row in items],
            "has_more": more,
            "next_cursor": encode_cursor(binding, [items[-1].created_at.isoformat(), items[-1].id])
            if more and items else None,
        }


def read_original(store, contract_id: str, document_id: str, actor_id: str) -> tuple[bytes, Any]:
    """The verified PDF of a published confirmation of this contract, and its manifest."""
    with archive.work(store, actor_id) as unit:
        contract, _, _, _, _ = _parents(unit, contract_id)
        try:
            document = unit.store.get_document(document_id)
        except NotFoundError:
            raise HTTPException(404, "Bestätigung nicht vorhanden.") from None
        if document.contract_id != contract.id:
            raise HTTPException(404, "Bestätigung nicht vorhanden.")
        return _verified(unit, document)


def _verified(unit: archive.Unit, document: Document) -> tuple[bytes, Any]:
    row = archive.head(unit, document.id)
    if row is None:
        raise HTTPException(404, "Die Bestätigung hat kein archiviertes Original.")
    _, binding = archive.bind_document(unit, document.id)
    row = archive.authorized_version(unit, document.id, row.id, binding)
    _validated_evidence(row)
    return archive.original_bytes(unit, row), row


def read_pdf_for_key(store, key: str, actor_id: str) -> bytes | None:
    """/uploads/housing-confirmations/<id>.pdf: always the verified original, never a file on disk."""
    if not key.startswith(VIRTUAL_PREFIX) or not key.endswith(".pdf"):
        return None
    identifier = key[len(VIRTUAL_PREFIX):-4]
    try:
        if str(UUID(identifier)) != identifier:
            raise ValueError
    except ValueError:
        raise HTTPException(404, "Bestätigung nicht vorhanden.") from None
    with archive.work(store, actor_id) as unit:
        try:
            document = unit.store.get_document(identifier)
        except NotFoundError:
            raise HTTPException(404, "Bestätigung nicht vorhanden.") from None
        if document.file_url != f"/uploads/{key}":
            raise HTTPException(404, "Bestätigung nicht vorhanden.")
        return _verified(unit, document)[0]
