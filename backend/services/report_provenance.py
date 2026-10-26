"""Report evidence from the calculation's own snapshot; no independent money math."""
from collections import defaultdict
from contextlib import contextmanager
from datetime import timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..repositories.sql_store import SQLAlchemyStore
from ..storage import NotFoundError, ValidationError
from . import document_versions as archive
from .maintenance_rows import Rows
from .privacy.storage import is_restricted, read_unit
from .receivable_residuals import digest
from .tax_support import _snapshot

TABLES = {"booking": "bookings", "invoice": "invoices", "rent": "contracts", "rent-arrears": "contracts",
          "receivable": "receivables", "service-instalment": "service_contracts",
          "utility-statement": "utility_statements", "account-opening": "accounts"}
SECTIONS = ("sources", "opening_sources", "baseline_sources")


@contextmanager
def snapshot(store):
    if not hasattr(store, "db"):
        with archive.memory_archive(store).lock:
            yield store, "memory_locked"
        return
    bind = store.db.get_bind()
    engine = getattr(bind, "engine", bind)
    # Connection-bound sessions bypass the shared calculation/table caches.
    with _snapshot(engine) as connection, Session(bind=connection, expire_on_commit=False) as session:
        yield SQLAlchemyStore(session), "database_repeatable_read"


def _original(store, document_id, expected_sha):
    if not document_id:
        return {"status": "not_linked", "message": "Kein Originalbeleg verknüpft."}
    if is_restricted(store, "document", document_id):
        return {"status": "unavailable", "message": "Originalbeleg derzeit nicht freigegeben."}
    unit = read_unit(store)
    try:
        document, binding = archive.bind_document(unit, document_id)
        if unit.db is None:
            versions = [item for item in unit.archive.versions.values() if item.document_id == document_id]
        else:
            from sqlalchemy import select

            from ..db.document_version_models import DocumentVersionORM
            versions = list(unit.db.scalars(select(DocumentVersionORM).where(DocumentVersionORM.document_id == document_id)))
        candidates = [item for item in versions if not expected_sha or item.sha256 == expected_sha]
        version = max(candidates, key=lambda item: item.number, default=None)
        if version is None:
            return {"status": "missing_original", "message": "Kein archiviertes Original mit der erforderlichen Prüfsumme vorhanden."}
        version = archive.authorized_version(unit, document_id, version.id, binding)
        for _ in archive.verified_blocks(unit, version):
            pass
        return {"status": "verified_original", "document_id": document_id, "version_id": version.id,
                "version_number": version.number, "sha256": version.sha256, "title": document.title,
                "filename": version.filename, "reference": "receipt_sha256" if expected_sha else "current_archive",
                "message": "Geprüfte Originalfassung zum Rechnungseingang." if expected_sha else "Geprüfte aktuelle Originalfassung.",
                "download": f"/documents/{document_id}/work/versions/{version.id}/download"}
    except (HTTPException, NotFoundError, ValidationError):
        return {"status": "unavailable", "message": "Originalbeleg nicht zugänglich oder Integrität nicht bestätigt."}


def enrich(store, result, mode):
    rows = Rows.reading(store)
    wanted = defaultdict(set)
    for section in SECTIONS:
        for source in result.get(section, []):
            parts = source["identity"].split(":")
            if source.get("priority") != 3 and len(parts) > 1 and parts[0] in TABLES:
                wanted[TABLES[parts[0]]].add(parts[1])
    reviews = {item.invoice_id: item for item in rows.find("invoice_reviews", invoice_id=wanted["invoices"])}
    from ..db.orm_models import AccountORM, UtilityStatementORM
    from ..models import Account, UtilityStatement
    from .maintenance_rows import registry
    extra: dict[str, tuple[Any, Any]] = {"accounts": (AccountORM, Account), "utility_statements": (UtilityStatementORM, UtilityStatement)}
    records = {}
    for table, identifiers in wanted.items():
        if not identifiers:
            continue
        if table in registry():
            found = rows.find(table, id=identifiers)
        elif rows.db is None:
            found = [item for item in getattr(store, table).values() if item.id in identifiers]
        else:
            from sqlalchemy import select
            orm, model = extra[table]
            keys = sorted(identifiers)
            found = [model.model_validate({column.key: getattr(item, column.key) for column in orm.__table__.columns})
                     for start in range(0, len(keys), 500)
                     for item in rows.db.scalars(select(orm).where(orm.id.in_(keys[start:start + 500])))]
        records[table] = {item.id: item for item in found}
    resolved, originals, changes = {}, {}, []
    for section in SECTIONS:
        for source in result.get(section, []):
            if source.get("priority") == 3:
                source["provenance"] = {"kind": "assumption", "message": "Ausdrückliche Planungsannahme; kein erfasster Geschäftsvorgang."}
                continue
            parts = source["identity"].split(":")
            source_table = TABLES.get(parts[0])
            if source_table is None or len(parts) < 2:
                source["provenance"] = {"kind": "unresolved", "message": "Quellenart nicht eindeutig zugeordnet."}
                continue
            identifier = parts[1]
            key = (source_table, identifier)
            if key not in resolved:
                record = records.get(source_table, {}).get(identifier)
                if record is None:
                    raise HTTPException(409, "Eine Berichtsquelle ist nicht mehr verfügbar. Bitte neu berechnen.")
                data = record.model_dump(mode="json")
                changed = getattr(record, "updated_at", None) or getattr(record, "created_at", None)
                if changed is not None:
                    changes.append(changed.replace(tzinfo=timezone.utc) if changed.tzinfo is None else changed.astimezone(timezone.utc))
                reference = {"kind": "record", "table": source_table, "id": identifier, "source_sha256": digest(data),
                             "updated_at": changed.isoformat() if changed else None}
                document_id = getattr(record, "source_document_id", None)
                expected_sha = None
                if source_table == "invoices" and identifier in reviews:
                    review = reviews[identifier]
                    reference["review_updated_at"] = review.updated_at.isoformat()
                    reference["review_sha256"] = digest(review.model_dump(mode="json"))
                    document_id = review.document_id or document_id
                    expected_sha = review.document_sha256
                if document_id or source_table == "invoices":
                    document_key = (document_id, expected_sha)
                    if document_key not in originals:
                        originals[document_key] = _original(store, document_id, expected_sha)
                    reference["original"] = originals[document_key]
                resolved[key] = reference
            source["provenance"] = resolved[key]
    all_sources = [source for section in SECTIONS for source in result.get(section, [])]
    missing = sum(item.get("original", {}).get("status") != "verified_original"
                  for (table, _), item in resolved.items() if table == "invoices")
    unresolved = sum(item["provenance"]["kind"] == "unresolved" for item in all_sources)
    result["provenance"] = {"format": "immomanager-report-evidence/1", "snapshot": mode,
        "as_of": result["definition"]["as_of"], "latest_source_change": max(changes).isoformat() if changes else None,
        "source_records": len(resolved), "verified_originals": sum(item["status"] == "verified_original" for item in originals.values()),
        "invoices_without_verified_original": missing, "unresolved_sources": unresolved,
        "assumptions": sum(item["provenance"]["kind"] == "assumption" for item in all_sources),
        "completeness": "review_required" if missing or unresolved or result.get("warnings") else "recorded_scope",
        "coverage": "Berechnet aus den zum Abruf berechtigten, erfassten Daten und der ausgewiesenen Definition. Fehlende externe Geschäftsvorgänge sind hierdurch nicht nachgewiesen.",
        "warning_count": len(result.get("warnings", []))}


def recheck_originals(store, result):
    """The snapshot describes the data; current access still gates its release."""
    seen = set()
    for section in SECTIONS:
        for source in result.get(section, []):
            original = source.get("provenance", {}).get("original", {})
            if original.get("status") != "verified_original" or original["document_id"] in seen:
                continue
            seen.add(original["document_id"])
            if is_restricted(store, "document", original["document_id"]):
                raise HTTPException(409, "Ein Quellenbeleg wurde zwischenzeitlich gesperrt. Bitte den Bericht neu berechnen.")
            # Re-resolve the binding under today's access, without disclosing
            # a document merely because an earlier snapshot contained it.
            archive.bind_document(read_unit(store), original["document_id"])

