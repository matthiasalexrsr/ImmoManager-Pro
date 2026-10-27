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


def file_fingerprints(file_url):
    from hashlib import sha256

    from ...routers.files import _file_url_to_key
    target = _file_url_to_key(file_url)
    keys = {target} if target else set()
    if target.endswith('_ocr.txt'):
        keys.update(target[:-8] + '.' + extension for extension in ('pdf', 'png', 'jpg', 'jpeg', 'tiff', 'tif', 'bmp', 'webp'))
    return sorted(sha256(key.encode('utf-8')).hexdigest() for key in keys)


def remember_file(existing, file_url):
    return sorted(set((existing.file_keys_sha256 or []) if existing else []) | set(file_fingerprints(file_url)))


def ensure_file_available(store, file_url):
    """An upload locator must not bypass a restriction on its linked document."""
    from ...routers.files import _file_url_to_key
    target = _file_url_to_key(file_url)
    unit = read_unit(store)
    policies = [item for item in rows(unit, PrivacyControlORM, kind="document") if item.restricted or item.erased_at or item.erasure_due]
    candidates = set(file_fingerprints(file_url))
    if any(candidates.intersection(item.file_keys_sha256 or []) for item in policies):
        raise HTTPException(404, "Die Quelldatei ist aufgrund einer Datenschutzentscheidung gesperrt.")
    blocked = [item.record_id for item in policies]
    if not target or not blocked:
        return
    if unit.db is not None:
        from ...db.orm_models import DocumentORM
        table = DocumentORM.__table__
        urls = unit.db.scalars(select(table.c.file_url).where(table.c.id.in_(blocked)))
    else:
        urls = [item.file_url for item in store.documents.values() if item.id in blocked]
    if any(candidates.intersection(file_fingerprints(url)) for url in urls):
        raise HTTPException(404, "Die Quelldatei ist aufgrund einer Datenschutzentscheidung gesperrt.")


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
