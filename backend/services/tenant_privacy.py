"""Coherent tenant metadata export and explicitly scoped profile anonymization."""

import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import is_dataclass
from tempfile import SpooledTemporaryFile

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..db.orm_models import ContractORM, TenantORM
from ..models import TenantPatch
from .concurrency import EditRevision, revision_scope, utc_datetime
from .data_transfer import _atomic_store
from .payments import _memory_lock
from .tenant_data_graph import TenantExportError, TenantNotFoundError, tenant_data_graph

PROFILE_FIELDS = (
    "full_name", "email", "phone", "address_line", "postal_code", "city", "country",
    "payment_method", "sepa_mandate", "notes", "archived",
)


class PrivacyConflict(RuntimeError):
    """The reviewed plan has changed or an active tenancy remains."""


def canonical_chunks(graph: dict):
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, allow_nan=False,
                               separators=(",", ":"))
    for text in encoder.iterencode(graph):
        for start in range(0, len(text), 16 * 1024):
            yield text[start:start + 16 * 1024].encode("utf-8")


def _graph_hash(graph: dict) -> str:
    digest = hashlib.sha256()
    for block in canonical_chunks(graph):
        digest.update(block)
    return digest.hexdigest()


def metadata_download(graph: dict):
    """Complete output before HTTP headers; spill large exports to disk."""
    output = SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
    try:
        for block in canonical_chunks(graph):
            output.write(block)
        output.seek(0)
    except BaseException:
        output.close()
        raise
    return output


def _scoped_graph(store, tenant_id):
    snapshot = store
    if getattr(store, "db", None) is not None:
        from .tenant_graph_source import TenantGraphSource
        store = TenantGraphSource(store, tenant_id)
    graph = tenant_data_graph(store, tenant_id)
    from .tenant_credit_graph import append_credit_graph
    return append_credit_graph(snapshot, graph)


@contextmanager
def _read_snapshot(active_store):
    if is_dataclass(active_store):
        with _memory_lock:
            # All records are detached; the pure graph cannot mutate the live store.
            yield deepcopy(active_store)
        return
    db = getattr(active_store, "db", None)
    if db is None or db.new or db.dirty or db.deleted:
        raise TenantExportError("Export requires a clean store session")
    engine = db.get_bind()
    if not isinstance(engine, Engine):
        raise TenantExportError("Unsupported snapshot backend")
    db.rollback()
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
        if engine.dialect.name == "sqlite":
            # sqlite3's legacy mode does not begin a transaction for SELECT.
            connection.exec_driver_sql("BEGIN")
        else:
            connection.begin()
        with Session(bind=connection, join_transaction_mode="rollback_only") as session:
            yield type(active_store)(session)
        connection.rollback()


def export_tenant_metadata(active_store, tenant_id: str) -> dict:
    with _read_snapshot(active_store) as snapshot:
        return _scoped_graph(snapshot, tenant_id)


def _plan(graph: dict) -> dict:
    active_contracts = sum(contract["status"] == "active" for contract in graph["contracts"])
    retained = {name: len(rows) for name, rows in graph.items() if isinstance(rows, list)}
    return {
        "tenant_id": graph["tenant"]["id"],
        "plan_hash": _graph_hash(graph),
        "scope": "tenant_profile_only",
        "fields": list(PROFILE_FIELDS),
        "active_contracts": active_contracts,
        "can_anonymize": active_contracts == 0,
        "retained_collections": retained,
        "retained_unlinked_records": graph["scope"]["not_covered"],
        "file_contents": "retained",
        "note": "Nur die Mieterstammdaten werden anonymisiert. Vertragsunterlagen, Dateien, "
                "Nachrichten und Finanzbelege bleiben erhalten und müssen gesondert geprüft werden.",
    }


def preview_tenant_anonymization(active_store, tenant_id: str) -> dict:
    return _plan(export_tenant_metadata(active_store, tenant_id))


def anonymize_tenant_profile(active_store, tenant_id: str, *, plan_hash: str,
                             confirm_tenant_id: str) -> dict:
    if confirm_tenant_id != tenant_id:
        raise PrivacyConflict("Die Bestätigung gehört zu einem anderen Mieter.")
    with _atomic_store(active_store) as staged:
        db = getattr(staged, "db", None)
        if db is not None:
            # The tenant lock also blocks new contract FKs on PostgreSQL.
            tenant_row = db.scalar(select(TenantORM).where(TenantORM.id == tenant_id).with_for_update())
            if tenant_row is None:
                raise TenantNotFoundError("Tenant not found")
            db.scalars(select(ContractORM).where(ContractORM.tenant_id == tenant_id).with_for_update()).all()
        graph = _scoped_graph(staged, tenant_id)
        plan = _plan(graph)
        if plan["plan_hash"] != plan_hash:
            raise PrivacyConflict("Der geprüfte Datenstand hat sich geändert. Vorschau neu laden.")
        if not plan["can_anonymize"]:
            raise PrivacyConflict("Aktive Mietverträge müssen vor der Stammdaten-Anonymisierung beendet werden.")
        patch = TenantPatch.model_validate({
            **{field: None for field in PROFILE_FIELDS if field not in {"full_name", "archived"}},
            "full_name": f"Anonymisiert-{tenant_id}", "archived": True,
        })
        revision = EditRevision("tenants", tenant_id, utc_datetime(graph["tenant"]["updated_at"]))
        with revision_scope(revision):
            result = staged._patch_entity("tenant", tenant_id, patch)
        expected = patch.model_dump()
        if any(getattr(result, field) != value for field, value in expected.items()):
            raise TenantExportError("Profile anonymization was not applied completely")
        return {"status": "profile_anonymized", "tenant_id": tenant_id,
                "anonymized_fields": list(PROFILE_FIELDS),
                "retained_collections": plan["retained_collections"],
                "scope": plan["scope"], "note": plan["note"]}
