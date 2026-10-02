"""Explicit tenant document journals and bounded original bytes in one snapshot."""

import json
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import exists, or_, select

from ..db.document_version_models import DocumentVersionORM
from . import document_versions as versions
from .portfolio_scope import current_scope
from .tenant_data_graph import TenantExportError

PERSONAL_FIELDS = {
    "document_versions": ["metadata_snapshot", "comment", "actor_id", "original file contents"],
}


def _require_complete_document_scope(store, document_ids):
    """A visible document must not lose a corrupt journal tail to scope filters.

    The unscoped query reads only an existence bit for already authorized document
    identities. Originals of separate hidden documents remain excluded.
    """
    captured = current_scope()
    if not document_ids or captured is None or captured.unrestricted:
        return
    if getattr(store, "db", None) is not None:
        table = DocumentVersionORM.__table__
        hidden = store.db.connection().scalar(select(exists(select(1).select_from(table).where(
            table.c.document_id.in_(document_ids),
            or_(table.c.portfolio_id.is_(None), table.c.portfolio_id.not_in(captured.portfolio_ids))))))
    else:
        hidden = any(row.document_id in document_ids and row.portfolio_id not in captured.portfolio_ids
                     for row in store.__dict__.get("document_versions", {}).values())
    if hidden:
        raise TenantExportError("Conflicting document version portfolio; no partial export")


def _rows(store, tenant_id, document_ids):
    captured = current_scope()
    if getattr(store, "db", None) is not None:
        query = select(DocumentVersionORM).where(or_(
            DocumentVersionORM.tenant_id == tenant_id,
            DocumentVersionORM.document_id.in_(document_ids)))
        if captured is not None and not captured.unrestricted:
            query = query.where(DocumentVersionORM.portfolio_id.in_(captured.portfolio_ids))
        return store.db.scalars(query.order_by(DocumentVersionORM.document_id, DocumentVersionORM.number)
                               .execution_options(yield_per=100))
    return sorted((row for row in store.__dict__.get("document_versions", {}).values()
        if (row.tenant_id == tenant_id or row.document_id in document_ids)
        and (captured is None or captured.unrestricted or row.portfolio_id in captured.portfolio_ids)),
        key=lambda row: (row.document_id, row.number))


def _authorized_row(store, row):
    _, binding = versions._document(store, getattr(store, "db", None), row.document_id)
    return versions._authorized_version(store, getattr(store, "db", None), row.document_id, row.id, binding)


def verified_blocks(store, manifest):
    """Recheck exact source/manifest and every bounded byte block before release."""
    try:
        row = versions._row(store, getattr(store, "db", None), manifest["version_id"])
        if row is None:
            raise TenantExportError("Missing immutable document version")
        row = _authorized_row(store, row)
        if any(manifest[key] != getattr(row, key) for key in
               ("document_id", "portfolio_id", "tenant_id", "sha256", "size_bytes")):
            raise TenantExportError("Conflicting immutable document manifest")
        yield from versions.verified_blocks(store, row)
    except TenantExportError:
        raise
    except Exception as error:
        raise TenantExportError("Invalid immutable document bytes; no partial export") from error


def append_document_versions(store, graph):
    """No name inference or property-only expansion into unrelated originals."""
    try:
        graph["document_versions"], graph["document_version_files"] = [], []
        tenant_id = graph["tenant"]["id"]
        contracts = {row["id"] for row in graph["contracts"]}
        documents = {row["id"] for row in graph["documents"]}
        _require_complete_document_scope(store, documents)
        previous: dict[str, DocumentVersionORM] = {}
        identities: dict[str, DocumentVersionORM] = {}
        for row in _rows(store, tenant_id, documents):
            row = _authorized_row(store, row)
            if row.tenant_id != tenant_id or row.contract_id not in contracts or row.document_id not in documents:
                raise TenantExportError("Conflicting document version tenant identity")
            before = previous.get(row.document_id)
            if ((before is None and (row.number != 1 or row.operation != "archive_original" or row.predecessor_id))
                    or (before is not None and (row.number != before.number + 1 or row.predecessor_id != before.id
                                               or row.operation not in {"upload", "restore"}))):
                raise TenantExportError("Incomplete immutable document version chain")
            if row.operation == "restore":
                restored = identities.get(row.restored_from_id)
                if (restored is None or restored.document_id != row.document_id
                        or (restored.sha256, restored.size_bytes, restored.filename, restored.media_type)
                        != (row.sha256, row.size_bytes, row.filename, row.media_type)):
                    raise TenantExportError("Conflicting immutable restored document version")
            elif row.restored_from_id is not None:
                raise TenantExportError("Unexpected document restoration source")
            previous[row.document_id] = row
            identities[row.id] = row
            value = versions.public(row)
            value.pop("download_url")
            value.update({key: getattr(row, key) for key in
                          ("portfolio_id", "property_id", "unit_id", "contract_id", "tenant_id")})
            value["metadata_snapshot"] = deepcopy(value["metadata_snapshot"])
            value["metadata_snapshot"].pop("file_url", None)
            json.dumps(value, ensure_ascii=False, allow_nan=False)
            manifest = {"id": "document-version:" + row.id, "kind": "document_version", "version_id": row.id,
                        **{key: getattr(row, key) for key in
                           ("document_id", "portfolio_id", "tenant_id", "sha256", "size_bytes")},
                        "encoding": "base64_blocks", "block_size": 65536}
            for _ in verified_blocks(store, manifest):
                pass
            graph["document_versions"].append(value)
            graph["document_version_files"].append(manifest)
        graph["scope"]["document_versions"] = {
            "selection": "exact stored tenant and current authorized document/contract relationships",
            "file_content": "verified originals in document_version_contents of the export download",
            "source_urls": "redacted from detached metadata; immutable stored snapshots preserved",
            "shared_property_documents": "excluded without explicit tenant/contract identity",
            "retention": "immutable history preserved by profile-only anonymization",
        }
        if graph["document_versions"]:
            graph["schema_version"] = "tenant-data-graph/4"
        return graph
    except TenantExportError:
        raise
    except Exception as error:
        raise TenantExportError("Document privacy export failed; no partial export") from error


def require_complete_subject_scope(store, tenant_id):
    """Deny destructive profile edits when this subject has hidden journals."""
    captured = current_scope()
    if captured is None or captured.unrestricted:
        return
    if getattr(store, "db", None) is not None:
        table = DocumentVersionORM.__table__
        hidden = store.db.connection().scalar(select(exists(select(1).select_from(table).where(
            table.c.tenant_id == tenant_id,
            or_(table.c.portfolio_id.is_(None), table.c.portfolio_id.not_in(captured.portfolio_ids))))))
    else:
        hidden = any(row.tenant_id == tenant_id and row.portfolio_id not in captured.portfolio_ids
                     for row in store.__dict__.get("document_versions", {}).values())
    if hidden:
        raise HTTPException(403, "Die Dokumenthistorie dieses Mieters liegt auch in weiteren Portfolios. "
                                 "Anonymisierung benötigt Zugriff auf alle verknüpften Portfolios.")
