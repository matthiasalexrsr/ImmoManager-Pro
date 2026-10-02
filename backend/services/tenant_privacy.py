"""Coherent tenant metadata export and explicitly scoped profile anonymization."""

import base64
import hashlib
import json
from contextlib import ExitStack, contextmanager, nullcontext
from copy import deepcopy
from dataclasses import is_dataclass
from datetime import datetime, timezone
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


def _memory_copy(store):
    # Separate memory journals may hold a persistent engine. A metadata snapshot
    # never mutates those engines and must not try to pickle connection pools.
    return deepcopy(store, {id(value): value for value in store.__dict__.values() if isinstance(value, Engine)})


def _memory_state(value):
    from ..db.contract_wizard_models import WIZARD_MODELS
    if isinstance(value, WIZARD_MODELS):
        return {column.name: _memory_state(getattr(value, column.name)) for column in value.__table__.columns}
    if isinstance(value, dict):
        return {key: _memory_state(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_memory_state(item) for item in value]
    return value


@contextmanager
def _memory_privacy_lock():
    from .. import auth
    # G40 compound writes use account management -> financial state. Fresh
    # in-memory auth reads also take the account lock; keep that order here.
    account_lock = getattr(auth._user_store, "_lock", None)
    with account_lock if account_lock is not None else nullcontext():
        with _memory_lock:
            yield


@contextmanager
def _privacy_write(active_store):
    if not is_dataclass(active_store):
        with _atomic_store(active_store) as staged:
            yield staged
        return
    with _memory_privacy_lock():
        staged = _memory_copy(active_store)
        before = _memory_state(_memory_copy(active_store).__dict__)
        yield staged
        if _memory_state(active_store.__dict__) != before:
            raise PrivacyConflict("Daten wurden während der Anonymisierung geändert. Vorschau neu laden.")
        object.__setattr__(active_store, "__dict__", staged.__dict__)


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
    from .tenant_private_draft_guard import private_draft_retention
    from .tenant_wizard_graph import append_wizard_graph
    graph = append_wizard_graph(snapshot, append_credit_graph(snapshot, graph))
    graph["scope"]["private_form_drafts"] = private_draft_retention(snapshot, tenant_id)
    return graph


@contextmanager
def _read_snapshot(active_store):
    from .portfolio_scope import current_scope, refresh_scope
    captured = current_scope()
    refresh_scope(captured)
    if is_dataclass(active_store):
        with _memory_privacy_lock():
            # All records are detached; the pure graph cannot mutate the live store.
            yield _memory_copy(active_store)
            refresh_scope(captured)
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
            refresh_scope(captured)
        connection.rollback()


def export_tenant_metadata(active_store, tenant_id: str) -> dict:
    with _read_snapshot(active_store) as snapshot:
        return _scoped_graph(snapshot, tenant_id)


def prepare_tenant_export(active_store, tenant_id: str, *, parent=None):
    """Validated complete JSON download, including bounded stored wizard bytes.

    The metadata API stays a detached graph. Actual binary evidence is written
    from the same snapshot directly into one private output, before publication.
    """
    from scripts.private_server_backup import private_workspace, protected_new_file

    from .datev_export import CompiledExport
    from .portfolio_scope import current_scope, refresh_scope
    from .tenant_wizard_graph import verified_blocks
    cleanup = ExitStack()
    try:
        workspace, _ = cleanup.enter_context(private_workspace(parent))
        path = workspace / "tenant-export.json"
        checksum, size = hashlib.sha256(), 0
        captured = current_scope()
        with _read_snapshot(active_store) as snapshot, protected_new_file(path) as output:
            graph = _scoped_graph(snapshot, tenant_id)
            graph["exported_at"] = datetime.now(timezone.utc).isoformat()
            graph["scope"]["file_content"] = "stored wizard PDF/originals included; other files metadata only"
            def write(block):
                nonlocal size
                output.write(block)
                checksum.update(block)
                size += len(block)
            def value(item):
                for block in canonical_chunks(item):
                    write(block)
            write(b"{")
            for position, (key, item) in enumerate(graph.items()):
                if position:
                    write(b",")
                value(key)
                write(b":")
                value(item)
            write(b',"wizard_file_contents":[')
            for index, manifest in enumerate(graph["contract_wizard_files"]):
                if index:
                    write(b",")
                write(b'{"id":')
                value(manifest["id"])
                write(b',"blocks":[')
                for position, block in enumerate(verified_blocks(snapshot, manifest)):
                    if position:
                        write(b",")
                    value({"position": position, "data_base64": base64.b64encode(block).decode("ascii")})
                write(b"]}")
            write(b"]}")
            refresh_scope(captured)
        return CompiledExport(path, {"size": size, "sha256": checksum.hexdigest()}, cleanup), captured
    except BaseException:
        cleanup.close()
        raise


def _plan(graph: dict) -> dict:
    active_contracts = sum(contract["status"] == "active" for contract in graph["contracts"])
    retained = {name: len(rows) for name, rows in graph.items() if isinstance(rows, list)}
    from .tenant_wizard_graph import PERSONAL_FIELDS
    wizard_retained = {name: {"count": len(graph.get(name, [])), "personal_fields": fields}
                       for name, fields in PERSONAL_FIELDS.items() if graph.get(name)}
    private = graph["scope"]["private_form_drafts"]
    if private["count"]:
        wizard_retained["private_form_drafts"] = {"count": private["count"],
            "personal_fields": ["private encrypted current/original editor values"], "contents_exported": False}
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
        "retained_personal_evidence": wizard_retained,
        "note": "Nur die Mieterstammdaten werden anonymisiert. Vertragsunterlagen, Dateien, "
                "Nachrichten und Finanzbelege bleiben erhalten und müssen gesondert geprüft werden."
                + (" Auch gespeicherte Vertragsentwürfe, frühere Prüfsnapshots/Vorgangsergebnisse, "
                   "Vorlagentexte, Unterzeichner und archivierte PDF-/Anlageninhalte enthalten weiterhin "
                   "Personenangaben. Sie werden durch diese Stammdaten-Aktion nicht anonymisiert."
                   if any(name != "private_form_drafts" for name in wizard_retained) else "")
                + (" Private Stammdaten-Formularentwürfe anderer Benutzer bleiben verschlüsselt erhalten. "
                   "Sie sind nicht Teil dieses Beziehungsexports und müssen vom jeweiligen Benutzer geprüft/verworfen werden."
                   if private["count"] else ""),
    }


def preview_tenant_anonymization(active_store, tenant_id: str) -> dict:
    from .tenant_wizard_graph import require_complete_subject_scope
    with _read_snapshot(active_store) as snapshot:
        graph = _scoped_graph(snapshot, tenant_id)
        require_complete_subject_scope(snapshot, tenant_id)
        return _plan(graph)


def anonymize_tenant_profile(active_store, tenant_id: str, *, plan_hash: str,
                             confirm_tenant_id: str) -> dict:
    if confirm_tenant_id != tenant_id:
        raise PrivacyConflict("Die Bestätigung gehört zu einem anderen Mieter.")
    with _privacy_write(active_store) as staged:
        from .portfolio_scope import current_scope, refresh_scope
        captured = current_scope()
        refresh_scope(captured)
        db = getattr(staged, "db", None)
        if db is not None:
            # The tenant lock also blocks new contract FKs on PostgreSQL.
            tenant_row = db.scalar(select(TenantORM).where(TenantORM.id == tenant_id).with_for_update())
            if tenant_row is None:
                raise TenantNotFoundError("Tenant not found")
            db.scalars(select(ContractORM).where(ContractORM.tenant_id == tenant_id).with_for_update()).all()
        from .tenant_wizard_graph import lock_subject_journals, require_complete_subject_scope
        require_complete_subject_scope(staged, tenant_id)
        lock_subject_journals(staged, tenant_id)
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
        refresh_scope(captured)
        return {"status": "profile_anonymized", "tenant_id": tenant_id,
                "anonymized_fields": list(PROFILE_FIELDS),
                "retained_collections": plan["retained_collections"],
                "retained_personal_evidence": plan["retained_personal_evidence"],
                "scope": plan["scope"], "note": plan["note"]}
