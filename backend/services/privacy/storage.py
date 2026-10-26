from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import select, text

from ...db.privacy_models import PrivacyControlORM, PrivacyDecisionORM, RestoreReviewORM
from .. import document_versions as archive
from ..data_transfer.common import digest
from ..integrations import connection_storage as db
from ..portfolio_scope import scope_context, scope_from_user
from ..workspace_contexts import bound_actor


@contextmanager
def work(store, actor_id):
    with archive.work(store, actor_id, write_areas=("/privacy",)) as unit:
        scope = scope_from_user(unit.user)
        if unit.user["role"] not in ("eigentuemer", "verwalter") or not scope.unrestricted:
            raise HTTPException(403, "Datenschutzentscheidungen benötigen Verwaltungsrechte für den gesamten Bestand.")
        with scope_context(scope), bound_actor(unit.user):
            if unit.db is not None and unit.db.get_bind().dialect.name == "postgresql":
                unit.db.execute(text("SELECT pg_advisory_xact_lock(725627501)"))
            yield unit


def rows(unit, model, **filters):
    if unit.db is not None:
        return list(unit.db.scalars(select(model).filter_by(**filters).order_by(model.id)))
    return sorted((row for row in db.memory(unit, model).values() if all(getattr(row, key) == value for key, value in filters.items())), key=lambda row: row.id)


def lock_sources(unit):
    from types import SimpleNamespace

    from ...db.data_transfer_models import ImportFileORM, PortabilityExportORM
    from ...db.document_version_models import DocumentVersionORM
    from ..data_snapshot import entity_specs
    from ..data_transfer.common import lock_target
    from ..data_transfer.portable_archive import EVIDENCE_MODELS
    lock_target(unit, [*entity_specs(), *[SimpleNamespace(table=model.__table__) for model in (*EVIDENCE_MODELS, DocumentVersionORM, ImportFileORM, PortabilityExportORM)]])


def key(kind, identifier):
    return digest(["privacy-resource/1", kind, identifier])


def control(unit, kind, identifier):
    return db.row(unit, PrivacyControlORM, key(kind, identifier), required=False)


def read_unit(store):
    return archive.Unit(store, getattr(store, "db", None), {}, None if hasattr(store, "db") else archive.memory_archive(store))


def is_restricted(store, kind, identifier):
    item = control(read_unit(store), kind, identifier)
    return bool(item and (item.restricted or item.erased_at))


def ensure_available(store, kind, identifier):
    if is_restricted(store, kind, identifier):
        raise HTTPException(404, "Diese Quelle ist für Veröffentlichung, Suche und KI-Verarbeitung gesperrt.")


def ensure_no_hold(store, kind, identifier):
    item = control(read_unit(store), kind, identifier)
    if item and item.held:
        raise HTTPException(409, "Für diesen Datensatz besteht eine dokumentierte Aufbewahrungssperre. Sie muss zuerst ausdrücklich aufgehoben werden.")


def ensure_restore_reviewed(store):
    from ...config import settings
    item = db.row(read_unit(store), RestoreReviewORM, "current", required=False)
    if (item is not None and item.pending) or (settings.privacy_restore_id and (item is None or item.restore_id != settings.privacy_restore_id)):
        raise HTTPException(503, "Nach der Wiederherstellung müssen aktuelle Lösch- und Sperrentscheidungen im Datenschutzbereich abgeglichen werden.")


def replay(unit, operation, kind, identifier, command):
    previous = db.find_one(unit, PrivacyDecisionORM, actor_id=unit.actor_id, idempotency_key=command.idempotency_key)
    if previous is not None:
        if (previous.action, previous.kind, previous.record_id, previous.request_sha256) != (operation, kind, identifier, digest(command.model_dump(mode="json"))):
            raise HTTPException(409, "Diese Wiederholungskennung gehört zu einer anderen Datenschutzentscheidung.")
        return previous.result
    return None


def receipt(unit, operation, kind, identifier, command, source_sha256, result):
    from uuid import uuid4
    db.put(unit, PrivacyDecisionORM, {"id": str(uuid4()), "kind": kind, "record_id": identifier, "action": operation,
        "actor_id": unit.actor_id, "idempotency_key": command.idempotency_key, "request_sha256": digest(command.model_dump(mode="json")),
        "source_sha256": source_sha256, "reason": command.reason, "result": result, "created_at": db.now()})
    return result
