"""Tenant-linked communication evidence for metadata/privacy exports."""

import hashlib
import json

from sqlalchemy import select

from ..db.communication_center_models import CommunicationDraftORM
from .portfolio_scope import current_scope
from .tenant_data_graph import TenantExportError

PERSONAL_FIELDS = {
    "communication_drafts": [
        "recipient identity", "subject/body templates", "rendered correspondence",
        "reviewed recipient/context snapshot", "review actor", "external reference/status",
    ],
    "communication_pdf_files": ["immutable reviewed PDF content"],
}


def _authorized_rows(store, tenant_id: str):
    db = getattr(store, "db", None)
    if db is None:
        return []
    rows = db.scalars(select(CommunicationDraftORM).where(
        CommunicationDraftORM.recipient_type == "tenant",
        CommunicationDraftORM.recipient_id == tenant_id,
    ).order_by(CommunicationDraftORM.created_at, CommunicationDraftORM.id)).all()
    scope = current_scope()
    if scope is not None and not scope.unrestricted:
        hidden = [row.id for row in rows if row.portfolio_id not in scope.portfolio_ids]
        if hidden:
            raise TenantExportError(
                "Tenant communication evidence exists outside the authorized portfolio scope"
            )
    return rows


def _public(row: CommunicationDraftORM) -> dict:
    try:
        context = json.loads(row.context_json) if row.context_json else None
    except (TypeError, ValueError):
        raise TenantExportError("Stored communication context is invalid") from None
    return {
        "id": row.id, "portfolio_id": row.portfolio_id, "title": row.title,
        "channel": row.channel, "recipient_type": row.recipient_type,
        "recipient_id": row.recipient_id, "contract_id": row.contract_id,
        "template_id": row.template_id, "template_revision": row.template_revision,
        "subject_template": row.subject_template,
        "body_template": row.body_template, "rendered_subject": row.rendered_subject,
        "rendered_body": row.rendered_body, "context": context,
        "context_sha256": row.context_sha256, "snapshot_sha256": row.snapshot_sha256,
        "pdf_sha256": row.pdf_sha256, "status": row.status, "revision": row.revision,
        "created_by": row.created_by, "reviewed_by": row.reviewed_by,
        "external_reference": row.external_reference, "external_status": row.external_status,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
    }
def append_communication_graph(store, graph: dict) -> dict:
    tenant_id = graph["tenant"]["id"]
    rows = _authorized_rows(store, tenant_id)
    graph["communication_drafts"] = [_public(row) for row in rows]
    graph["communication_pdf_files"] = [
        {"id": row.id, "sha256": row.pdf_sha256, "size_bytes": len(row.document_pdf)}
        for row in rows if row.document_pdf is not None and row.pdf_sha256
    ]
    graph["scope"]["communication_correspondence"] = {
        "selection": "direct recipient_type=tenant and recipient_id relationship",
        "retention": "reviewed snapshots and transport references remain immutable evidence",
        "pdf_content": "included in communication_pdf_contents of the full export",
    }
    if rows:
        graph["schema_version"] = "tenant-data-graph/5"
    return graph


def verified_blocks(store, manifest: dict):
    db = getattr(store, "db", None)
    if db is None:
        raise TenantExportError("Communication PDF source is unavailable")
    row = db.get(CommunicationDraftORM, manifest["id"])
    if row is None or row.document_pdf is None:
        raise TenantExportError("Communication PDF evidence is missing")
    content = bytes(row.document_pdf)
    if (len(content) != manifest["size_bytes"]
            or hashlib.sha256(content).hexdigest() != manifest["sha256"]
            or row.pdf_sha256 != manifest["sha256"]):
        raise TenantExportError("Communication PDF evidence failed integrity validation")
    yield content
