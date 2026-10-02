"""Explicit tenant relationships in reviewed contract journals and stored originals.

The caller owns one coherent, authorized snapshot. Binary values are read in
bounded blocks; only manifests enter the metadata graph. No name/email matching,
remote fetch or mutation of immutable evidence is performed.
"""

import hashlib
import json
from copy import deepcopy
from datetime import date, datetime
from itertools import chain
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import OperationalError

from ..db.contract_wizard_models import (
    ContractAttachmentChunkORM,
    ContractAttachmentORM,
    ContractDraftORM,
    ContractSignatureORM,
    ContractTemplateORM,
    ContractWizardCommandORM,
)
from ..db.orm_models import ContractORM
from .contract_wizard import digest
from .portfolio_scope import current_scope, scoped_clause
from .tenant_data_graph import TenantExportError

BLOCK_SIZE = 64 * 1024  # Serialization buffer, never a total file/stock limit.
COLLECTIONS = ("contract_wizard_drafts", "contract_wizard_commands", "contract_template_versions",
               "contract_signature_evidence", "contract_attachment_evidence", "contract_wizard_files")
PERSONAL_FIELDS = {
    "contract_wizard_drafts": ["data", "review", "published_tenant_id", "reviewed PDF"],
    "contract_wizard_commands": ["result.data", "result.review"],
    "contract_template_versions": ["title", "body"],
    "contract_signature_evidence": ["tenant_signer", "landlord_signer", "reference", "note"],
    "contract_attachment_evidence": ["metadata_snapshot", "original file contents"],
}


def _fail(message):
    raise TenantExportError(message)


def _json(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False,
        default=lambda item: item.isoformat() if isinstance(item, (datetime, date)) else _fail("Invalid wizard field")))


def _dump(row, model):
    return _json({column.name: getattr(row, column.name) for column in model.__table__.columns
                  if column.name != "pdf"})


def _snapshot_matches(value, tenant_id, contract_ids, *, new_tenant=None):
    if not isinstance(value, dict):
        _fail("Invalid wizard snapshot")
    data, review = value.get("data") or {}, value.get("review") or {}
    if not isinstance(data, dict) or not isinstance(review, dict):
        _fail("Invalid wizard subject")
    tenant = review.get("tenant") or {}
    if not isinstance(tenant, dict):
        _fail("Invalid reviewed tenant")
    subjects = {identifier for identifier in (data.get("tenant_id"), tenant.get("id")) if identifier}
    contract_id = value.get("contract_id")
    matches = tenant_id in subjects or contract_id in contract_ids
    # Before publishing a newly created tenant, exact structured equality to
    # the final reviewed party is the only recoverable binding. Other abandoned
    # prospective parties are excluded, even within the same draft history.
    matches |= (new_tenant is not None and data.get("new_tenant") == new_tenant)
    if matches and (subjects - {tenant_id} or (contract_id and contract_id not in contract_ids)):
        _fail("Conflicting wizard tenant identity")
    return matches


def _subject_condition(model, tenant_id, contracts):
    if model is ContractDraftORM:
        return or_(model.published_tenant_id == tenant_id, model.contract_id.in_(contracts),
            model.data["tenant_id"].as_string() == tenant_id,
            model.review["tenant"]["id"].as_string() == tenant_id)
    return or_(model.result["data"]["tenant_id"].as_string() == tenant_id,
        model.result["review"]["tenant"]["id"].as_string() == tenant_id,
        model.result["contract_id"].as_string().in_(contracts))


def _rows(store, model, condition=None):
    if getattr(store, "db", None) is not None:
        columns = [column for column in model.__table__.columns if column.name != "pdf"]
        query = select(*columns).where(condition).execution_options(yield_per=100)
        return (SimpleNamespace(**row) for row in store.db.execute(query).mappings())
    scope = current_scope()
    return (row for row in store.__dict__.get(model.__tablename__, {}).values()
            if scope is None or scope.unrestricted or row.portfolio_id in scope.portfolio_ids)


def _safe_snapshot(value, graph, portfolio_id):
    """Validate explicit identities before copying opaque/file reference metadata."""
    result = deepcopy(value)
    data = result.get("data") or {}
    review = result.get("review") or {}
    prop = review.get("property") or {}
    if prop and (prop.get("portfolio_id") != portfolio_id or prop.get("id") != data.get("property_id")):
        _fail("Conflicting reviewed portfolio")
    template = review.get("template")
    if template is not None and (not isinstance(template, dict) or template.get("id") != data.get("template_id")):
        _fail("Conflicting reviewed template identity")
    own_contracts = {row["id"] for row in graph["contracts"]}
    for attachment in review.get("attachments", []):
        if not isinstance(attachment, dict) or (attachment.get("contract_id")
                and attachment["contract_id"] not in own_contracts):
            _fail("Wizard evidence references another tenant contract")
        if (attachment.get("property_id") != data.get("property_id")
                or attachment.get("unit_id") not in (None, data.get("unit_id"))):
            _fail("Wizard evidence references another property/unit")
        attachment.pop("file_url", None)
    for key in ("pdf_url", "preview_url"):
        result.pop(key, None)
    if data and not isinstance(data.get("attachment_ids", []), list):
        _fail("Invalid wizard attachment references")
    return result


def _drafts(store, tenant_id, contract_ids):
    if getattr(store, "db", None) is not None:
        contracts = select(ContractORM.id).where(ContractORM.tenant_id == tenant_id)
        command_drafts = select(ContractWizardCommandORM.draft_id).where(
            _subject_condition(ContractWizardCommandORM, tenant_id, contracts))
        condition = or_(_subject_condition(ContractDraftORM, tenant_id, contracts), ContractDraftORM.id.in_(command_drafts))
        return list(_rows(store, ContractDraftORM, condition))
    commands = list(_rows(store, ContractWizardCommandORM))
    historical = {row.draft_id for row in commands if _snapshot_matches(row.result, tenant_id, contract_ids)}
    return [row for row in _rows(store, ContractDraftORM)
            if row.published_tenant_id == tenant_id or row.id in historical
            or _snapshot_matches(_dump(row, ContractDraftORM), tenant_id, contract_ids)]


def file_blocks(store, manifest):
    """One exact authorized evidence source; never materialize a complete SQL BLOB."""
    db = getattr(store, "db", None)
    if manifest["kind"] == "reviewed_pdf":
        if db is None:
            row = store.__dict__.get(ContractDraftORM.__tablename__, {}).get(manifest["draft_id"])
            if row is None or row.portfolio_id != manifest["portfolio_id"]:
                _fail("Missing reviewed PDF")
            for offset in range(0, len(row.pdf or b""), BLOCK_SIZE):
                yield row.pdf[offset:offset + BLOCK_SIZE]
        else:
            for offset in range(0, manifest["size_bytes"], BLOCK_SIZE):
                value = db.scalar(select(func.substr(ContractDraftORM.pdf, offset + 1, BLOCK_SIZE))
                    .where(ContractDraftORM.id == manifest["draft_id"],
                           ContractDraftORM.portfolio_id == manifest["portfolio_id"]))
                if not isinstance(value, bytes):
                    _fail("Missing reviewed PDF block")
                yield value
    else:
        if db is None:
            chunks = sorted((row for row in _rows(store, ContractAttachmentChunkORM)
                             if row.attachment_id == manifest["attachment_id"]), key=lambda row: row.position)
        else:
            chunks = store.db.scalars(select(ContractAttachmentChunkORM)
                .where(ContractAttachmentChunkORM.attachment_id == manifest["attachment_id"])
                .order_by(ContractAttachmentChunkORM.position).execution_options(yield_per=8))
        for position, row in enumerate(chunks):
            if (row.position != position or row.portfolio_id != manifest["portfolio_id"]
                    or not isinstance(row.data, bytes) or not 0 < len(row.data) <= BLOCK_SIZE):
                _fail("Invalid archived attachment block")
            yield row.data


def verified_blocks(store, manifest):
    checksum, size, first = hashlib.sha256(), 0, True
    for block in file_blocks(store, manifest):
        if first and manifest["kind"] == "reviewed_pdf" and not block.startswith(b"%PDF-"):
            _fail("Invalid reviewed PDF")
        first = False
        checksum.update(block)
        size += len(block)
        yield block
    if first and manifest["kind"] == "reviewed_pdf":
        _fail("Missing reviewed PDF")
    if size != manifest["size_bytes"] or checksum.hexdigest() != manifest["sha256"]:
        _fail("Incomplete or corrupt immutable wizard file")


def _file(graph, store, manifest):
    if (not isinstance(manifest["size_bytes"], int) or manifest["size_bytes"] < 0
            or not isinstance(manifest["sha256"], str) or len(manifest["sha256"]) != 64):
        _fail("Invalid wizard file manifest")
    for _ in verified_blocks(store, manifest):
        pass
    graph["contract_wizard_files"].append({**manifest, "encoding": "base64_blocks", "block_size": BLOCK_SIZE})


def append_wizard_graph(store, graph):
    """Complete explicit G07 relationships, with manifest-only binary metadata."""
    try:
        for name in COLLECTIONS:
            graph[name] = []
        tenant_id = graph["tenant"]["id"]
        contracts = {row["id"]: row for row in graph["contracts"]}
        documents = {row["id"]: row for row in graph["documents"]}
        linked = _drafts(store, tenant_id, contracts)
        template_ids, redactions = set(), []
        for row in sorted(linked, key=lambda item: item.id):
            store.get_portfolio(row.portfolio_id)
            values = _dump(row, ContractDraftORM)
            new_tenant = row.data.get("new_tenant") if row.published_tenant_id == tenant_id else None
            current = _snapshot_matches(values, tenant_id, contracts, new_tenant=new_tenant)
            if row.published_tenant_id == tenant_id and not current:
                _fail("Conflicting published tenant identity")
            if current:
                prop, unit = store.get_property(row.data["property_id"]), store.get_unit(row.data["unit_id"])
                if prop.portfolio_id != row.portfolio_id or unit.property_id != prop.id:
                    _fail("Conflicting wizard location")
                if row.state in {"committed", "signed"}:
                    contract, document = contracts.get(row.contract_id), documents.get(row.document_id)
                    if (row.published_tenant_id != tenant_id or contract is None or document is None
                            or document["contract_id"] != row.contract_id
                            or contract["property_id"] != prop.id or contract["unit_id"] != unit.id
                            or document["property_id"] != prop.id or document["unit_id"] != unit.id):
                        _fail("Conflicting published wizard relationships")
                if row.state in {"reviewed", "committed", "signed"} and (row.review is None or not row.pdf_sha256):
                    _fail("Incomplete reviewed wizard evidence")
                if row.review is not None and digest(row.review) != row.review_hash:
                    _fail("Corrupt reviewed wizard snapshot")
                if row.review is not None and row.review.get("parameters") != row.data:
                    _fail("Reviewed parameters do not match the current draft")
                values = _safe_snapshot(values, graph, row.portfolio_id)
                if row.data.get("template_id"):
                    template_ids.add((row.data["template_id"], row.portfolio_id))
                if row.pdf_sha256:
                    size = len(row.pdf or b"") if getattr(store, "db", None) is None else store.db.scalar(
                        select(func.length(ContractDraftORM.pdf)).where(ContractDraftORM.id == row.id))
                    _file(graph, store, {"id": "wizard-pdf:" + row.id, "kind": "reviewed_pdf", "draft_id": row.id,
                        "portfolio_id": row.portfolio_id, "size_bytes": size, "sha256": row.pdf_sha256})
            else:
                # A draft changed from A to B. Export A's command snapshots, not
                # the current B party, PDF, contract or review identifiers.
                for name in ("data", "review", "review_hash", "pdf_sha256", "contract_id", "document_id", "published_tenant_id"):
                    values[name] = None
                redactions.append({"draft_id": row.id, "reason": "current_party_not_this_tenant"})
            values["current_subject_included"] = current
            graph["contract_wizard_drafts"].append(values)
            commands = _rows(store, ContractWizardCommandORM, ContractWizardCommandORM.draft_id == row.id)
            for command in sorted(commands, key=lambda item: item.id):
                if command.draft_id != row.id:
                    continue
                if command.portfolio_id != row.portfolio_id or command.actor_id != row.actor_id:
                    _fail("Conflicting wizard command parent")
                if not _snapshot_matches(command.result, tenant_id, contracts, new_tenant=new_tenant):
                    continue
                result = _safe_snapshot(command.result, graph, row.portfolio_id)
                if result.get("review") is not None and digest(command.result["review"]) != result.get("review_hash"):
                    _fail("Corrupt historical wizard review")
                if result.get("data", {}).get("template_id"):
                    template_ids.add((result["data"]["template_id"], row.portfolio_id))
                graph["contract_wizard_commands"].append({**_dump(command, ContractWizardCommandORM), "result": result})
            if not current:
                continue
            for model, collection in ((ContractSignatureORM, "contract_signature_evidence"),
                                      (ContractAttachmentORM, "contract_attachment_evidence")):
                for evidence in sorted(_rows(store, model, model.draft_id == row.id), key=lambda item: item.id):
                    if evidence.draft_id != row.id:
                        continue
                    if evidence.portfolio_id != row.portfolio_id or row.state not in {"committed", "signed"}:
                        _fail("Conflicting wizard evidence parent")
                    record = _dump(evidence, model)
                    if model is ContractSignatureORM:
                        signed = documents.get(evidence.signed_document_id) if evidence.signed_document_id else None
                        if evidence.signed_document_id and (signed is None or signed["contract_id"] != row.contract_id):
                            _fail("Foreign signature document")
                    else:
                        metadata = deepcopy(evidence.metadata_snapshot)
                        if (metadata.get("id") != evidence.source_document_id
                                or metadata.get("property_id") != row.data["property_id"]
                                or metadata.get("unit_id") not in (None, row.data["unit_id"])
                                or metadata.get("contract_id") and metadata["contract_id"] not in contracts):
                            _fail("Foreign or conflicting archived attachment")
                        metadata.pop("file_url", None)
                        record["metadata_snapshot"] = metadata
                        if evidence.mode == "frozen_bytes":
                            _file(graph, store, {"id": "wizard-attachment:" + evidence.id, "kind": "frozen_attachment",
                                "draft_id": row.id, "attachment_id": evidence.id, "portfolio_id": row.portfolio_id,
                                "size_bytes": evidence.size_bytes, "sha256": evidence.sha256})
                        elif evidence.mode != "metadata_only" or evidence.sha256 is not None or evidence.size_bytes is not None:
                            _fail("Invalid attachment evidence mode")
                    graph[collection].append(record)
        template_snapshots: dict[str, dict] = {}
        reviews = chain((row["review"] for row in graph["contract_wizard_drafts"]),
                        (row["result"].get("review") for row in graph["contract_wizard_commands"]))
        for review in reviews:
            if review is None or review.get("template") is None:
                continue
            template = review["template"]
            identifier = template["id"]
            if identifier in template_snapshots and template_snapshots[identifier] != template:
                _fail("Conflicting immutable template snapshots")
            template_snapshots[identifier] = template
        for identifier, portfolio_id in sorted(template_ids):
            found = next((row for row in _rows(store, ContractTemplateORM, ContractTemplateORM.id == identifier)
                          if row.id == identifier), None)
            if found is None or found.portfolio_id != portfolio_id:
                _fail("Missing or foreign wizard template version")
            expected = {key: getattr(found, key) for key in ("id", "version", "title", "body")}
            if identifier in template_snapshots and template_snapshots[identifier] != expected:
                _fail("Corrupt immutable template version")
            graph["contract_template_versions"].append(_dump(found, ContractTemplateORM))
        if linked:
            graph["schema_version"] = "tenant-data-graph/3"
        graph["scope"]["wizard"] = {"selection": "explicit_current_or_historical_tenant_ids; exact_published_new_party",
            "file_content": "verified stored PDF/originals in wizard_file_contents of the export download",
            "unassigned_prospects": "excluded; no name/email inference",
            "shared_opaque_sources": "explicit selected evidence only; foreign contract references fail closed",
            "redactions": redactions, "retention": "immutable evidence preserved; profile anonymization is not document erasure",
            "portfolio_selection": "authorized actor scope; no expansion to hidden portfolios"}
        graph["scope"]["not_covered"] = sorted(set(graph["scope"]["not_covered"]) | {
            "unassigned_wizard_prospects", "unselected_template_versions", "private_form_draft_contents"})
        return graph
    except TenantExportError:
        raise
    except Exception as error:
        raise TenantExportError("Wizard privacy export failed; no partial export") from error


def has_historical_tenant_reference(store, tenant_id):
    """A changed draft must not silently orphan its earlier reviewed party."""
    if getattr(store, "db", None) is not None:
        condition = or_(ContractWizardCommandORM.result["data"]["tenant_id"].as_string() == tenant_id,
                       ContractWizardCommandORM.result["review"]["tenant"]["id"].as_string() == tenant_id)
        return store.db.scalar(select(ContractWizardCommandORM.id).where(condition).limit(1)) is not None
    return any(_snapshot_matches(row.result, tenant_id, set()) for row in _rows(store, ContractWizardCommandORM))


def require_complete_subject_scope(store, tenant_id):
    """Shared profiles cannot be changed from a view hiding retained references.

    The SQL exception to scoped materialization reads one existence boolean for
    this exact subject, not records/PII. It only denies a destructive operation.
    """
    captured = current_scope()
    if captured is None or captured.unrestricted:
        return
    if getattr(store, "db", None) is not None:
        contracts = select(ContractORM.id).where(ContractORM.tenant_id == tenant_id)
        conditions = []
        for model, subject in ((ContractORM, ContractORM.tenant_id == tenant_id),
                               (ContractDraftORM, _subject_condition(ContractDraftORM, tenant_id, contracts)),
                               (ContractWizardCommandORM, _subject_condition(ContractWizardCommandORM, tenant_id, contracts))):
            visible = scoped_clause(model, scope=captured)
            if visible is not None:
                conditions.append(exists(select(1).select_from(model).where(subject, ~visible)))
        # Deliberately use Core on the same exclusive transaction, so the ORM
        # cannot filter out the very hidden existence this guard must detect.
        hidden = store.db.connection().scalar(select(or_(*conditions)))
    else:
        raw = store.__dict__
        memory_contracts = {row.id: row for row in raw["contracts"].values() if row.tenant_id == tenant_id}
        hidden = any(raw["properties"][row.property_id].portfolio_id not in captured.portfolio_ids
                     for row in memory_contracts.values())
        hidden |= any(row.portfolio_id not in captured.portfolio_ids
                      and (row.published_tenant_id == tenant_id
                           or _snapshot_matches(_dump(row, ContractDraftORM), tenant_id, memory_contracts))
                      for row in raw.get(ContractDraftORM.__tablename__, {}).values())
        hidden |= any(row.portfolio_id not in captured.portfolio_ids
                      and _snapshot_matches(row.result, tenant_id, memory_contracts)
                      for row in raw.get(ContractWizardCommandORM.__tablename__, {}).values())
    if hidden:
        raise HTTPException(403, "Die Mieterstammdaten haben weitere Portfolio-Bezüge. "
                            "Anonymisierung benötigt Zugriff auf alle verknüpften Portfolios.")


def lock_subject_journals(store, tenant_id):
    """Hold current/historical draft parents until the reviewed profile write.

    Wizard commands lock their draft before related tenants. NOWAIT avoids a
    reversed tenant→draft lock-order deadlock and returns a recoverable conflict.
    SQLite's outer BEGIN IMMEDIATE already serializes the writer transactions.
    """
    db = getattr(store, "db", None)
    if db is None or db.get_bind().dialect.name != "postgresql":
        return
    contracts = select(ContractORM.id).where(ContractORM.tenant_id == tenant_id)
    command_drafts = select(ContractWizardCommandORM.draft_id).where(
        _subject_condition(ContractWizardCommandORM, tenant_id, contracts))
    condition = or_(_subject_condition(ContractDraftORM, tenant_id, contracts),
                    ContractDraftORM.id.in_(command_drafts))
    try:
        for _ in db.scalars(select(ContractDraftORM.id).where(condition)
                            .order_by(ContractDraftORM.id).with_for_update(nowait=True)):
            pass
    except OperationalError as error:
        if getattr(error.orig, "sqlstate", getattr(error.orig, "pgcode", None)) != "55P03":
            raise
        from .tenant_privacy import PrivacyConflict
        raise PrivacyConflict("Vertragsnachweise werden gerade geändert. Vorschau neu laden und erneut versuchen.") from error
