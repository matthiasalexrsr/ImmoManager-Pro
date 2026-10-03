"""Exact frozen dispute subjects and verified originals in the privacy snapshot."""

import hashlib
from copy import deepcopy

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import exists, select, text

from ..db.billing_dispute_models import BillingDisputeCaseORM as Case
from ..db.billing_dispute_models import BillingDisputeCommandORM as Command
from ..db.billing_dispute_models import BillingDisputeEventORM as Event
from ..db.billing_dispute_models import BillingDisputeEvidenceORM as Evidence
from ..db.document_version_models import DocumentVersionORM
from ..db.orm_models import ContractORM
from .billing_dispute_recovery import available
from .billing_dispute_validation import DisputeIntegrityError, payload
from .billing_disputes import _case, _rows, _verified
from .portfolio_scope import current_scope, memory_visible

PERSONAL_FIELDS = {"billing_dispute_cases": ["frozen tenant/contract reference", "reviewed original statement", "party binding at opening"],
                   "billing_dispute_events": ["original reason", "actual received/observed date", "actor", "original attachments"],
                   "billing_dispute_commands": ["actor", "revision", "receipt", "request hash"]}


def require_complete_scope(store, tenant_id):
    if not available(store):
        return
    captured = current_scope()
    if captured is None or captured.unrestricted:
        return
    if hasattr(store, "db"):
        table = Case.__table__
        hidden = store.db.connection().scalar(select(exists(select(table.c.id).where(table.c.tenant_id == tenant_id,
            table.c.portfolio_id.not_in(captured.portfolio_ids)))))
    else:
        hidden = any(row.tenant_id == tenant_id and row.portfolio_id not in captured.portfolio_ids
                     for row in store.__dict__.get(Case.__tablename__, {}).values())
    if hidden:
        raise HTTPException(403, "Die vollständige Widerspruchshistorie liegt auch in weiteren Portfolios. Alle ursprünglichen Personenbezüge müssen zugänglich sein.")


def lock_subject(store, tenant_id):
    if not available(store):
        return
    require_complete_scope(store, tenant_id)
    if not hasattr(store, "db"):
        return
    db = store.db
    cases, contracts = Case.__table__, ContractORM.__table__
    properties = set(db.connection().scalars(select(cases.c.property_id).where(cases.c.tenant_id == tenant_id)))
    properties.update(db.connection().scalars(select(contracts.c.property_id).where(contracts.c.tenant_id == tenant_id)))
    if db.get_bind().dialect.name == "postgresql":
        for property_id in sorted(properties):
            identifier = int.from_bytes(hashlib.sha256(("measurement:" + property_id).encode()).digest()[:8], "big", signed=True)
            if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:identifier)"), {"identifier": identifier}):
                from .tenant_privacy import PrivacyConflict
                raise PrivacyConflict("Eine Widerspruchsakte wird gerade bestätigt. Vorschau neu laden und erneut versuchen.")


def append_dispute_graph(store, graph):
    for name in ("billing_dispute_cases", "billing_dispute_commands", "billing_dispute_events", "billing_dispute_evidence_files"):
        graph[name] = []
    if not available(store):
        return graph
    tenant_id = graph["tenant"]["id"]
    require_complete_scope(store, tenant_id)
    for case in _rows(store, Case, tenant_id=tenant_id):
        _case(store, case.id)
        graph["billing_dispute_cases"].append(jsonable_encoder(deepcopy(payload(case))))
        for event in _rows(store, Event, case_id=case.id):
            original = _verified(store, case, event)
            graph["billing_dispute_events"].append(original)
            for link in original["evidence"]:
                version = store.db.get(DocumentVersionORM, link["version_id"]) if hasattr(store, "db") else store.__dict__.get("document_versions", {}).get(link["version_id"])
                if version is None:
                    raise DisputeIntegrityError("Widerspruchsanlage fehlt.")
                manifest = {"id": "dispute-version:" + event.id + ":" + version.id, "kind": "billing_dispute_evidence",
                    "case_id": case.id, "event_id": event.id, "version_id": version.id, "tenant_id": tenant_id,
                    "sha256": link["sha256"], "size_bytes": version.size_bytes, "encoding": "base64_blocks", "block_size": 65536}
                for _block in verified_blocks(store, manifest):
                    pass
                graph["billing_dispute_evidence_files"].append(manifest)
        for command in _rows(store, Command, case_id=case.id):
            graph["billing_dispute_commands"].append(jsonable_encoder({key: getattr(command, key) for key in
                ("id", "case_id", "actor_id", "revision", "request_hash", "result", "created_at")}))
    graph["scope"]["billing_disputes"] = "Exakt eingefrorene Akten dieser Person samt Originalgründen und Anlagen bleiben erhalten; Objektprüfungen und andere Mietparteien sind ausgeschlossen. Der Mieterbezug wurde beim Öffnen geprüft, frühere Abrechnungen speichern keine damalige Identität."
    return graph


def verified_blocks(store, manifest):
    from .document_versions import verified_blocks as blocks
    case = _case(store, manifest["case_id"])
    if case.tenant_id != manifest["tenant_id"]:
        raise DisputeIntegrityError("Widerspruchsanlage besitzt einen fremden Personenbezug.")
    event = next(iter(_rows(store, Event, id=manifest["event_id"], case_id=case.id)), None)
    link = next(iter(_rows(store, Evidence, event_id=manifest["event_id"], version_id=manifest["version_id"])), None)
    version = store.db.get(DocumentVersionORM, manifest["version_id"]) if hasattr(store, "db") else store.__dict__.get("document_versions", {}).get(manifest["version_id"])
    if event is None or link is None or version is None or not memory_visible(store, DocumentVersionORM.__tablename__, version):
        raise DisputeIntegrityError("Widerspruchsanlage ist nicht vollständig zugänglich.")
    _verified(store, case, event)
    if (version.sha256 != link.sha256 or version.sha256 != manifest["sha256"] or version.size_bytes != manifest["size_bytes"]
            or version.portfolio_id != case.portfolio_id or version.property_id != case.property_id
            or version.tenant_id not in {None, case.tenant_id} or version.contract_id not in {None, case.contract_id}
            or version.unit_id not in {None, case.unit_id}):
        raise DisputeIntegrityError("Widerspruchsanlage weicht vom eingefrorenen Original ab.")
    yield from blocks(store, version)
