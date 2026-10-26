"""Explicit reconciliation; imported evidence can tighten, never silently lift controls."""
from fastapi import HTTPException

from ...config import settings
from ...db.privacy_models import PrivacyControlORM, PrivacyDecisionORM, RestoreReviewORM
from ..data_transfer.common import digest
from ..integrations import connection_storage as db
from . import resources
from .storage import control, key, lock_sources, receipt, replay, rows, work

FORMAT = "immomanager-privacy-controls/1"


def snapshot(unit):
    controls = [{name: resources._plain(value) for name, value in db.values(item).items()}
                for item in rows(unit, PrivacyControlORM)]
    return {"format": FORMAT, "controls": controls, "sha256": digest({"format": FORMAT, "controls": controls})}


def export(store, actor_id):
    with work(store, actor_id) as unit:
        return snapshot(unit)


def review(unit):
    current = db.row(unit, RestoreReviewORM, "current", required=False)
    epoch_changed = bool(settings.privacy_restore_id and (not current or current.restore_id != settings.privacy_restore_id))
    if current is None or epoch_changed:
        current = db.put(unit, RestoreReviewORM, {"id": "current", "pending": epoch_changed,
            "revision": (current.revision if current else 0) + 1, "reason": "Wiederherstellung abgleichen." if epoch_changed else "Keine Wiederherstellung ausstehend.",
            "actor_id": None, "journal_sha256": None, "restore_id": settings.privacy_restore_id or None,
            "created_at": current.created_at if current else db.now(), "updated_at": db.now()})
    return current


def status(store, actor_id):
    with work(store, actor_id) as unit:
        current = review(unit)
        return {"pending": current.pending, "revision": current.revision, "reason": current.reason,
            "journal_sha256": snapshot(unit)["sha256"],
            "pending_erasure": [{"kind": item.kind, "id": item.record_id, "title": resources.inspect_resource(unit, item.kind, item.record_id)["title"]}
                                for item in rows(unit, PrivacyControlORM) if item.erasure_due]}


def complete(store, actor_id, command):
    with work(store, actor_id) as unit:
        if previous := replay(unit, "restore_review", "restore", "current", command):
            return previous
        current = review(unit)
        if current.revision != command.expected_revision or snapshot(unit)["sha256"] != command.journal_sha256:
            raise HTTPException(409, "Prüfstand oder Datenschutzjournal wurden geändert. Bitte neu laden.")
        if any(item.erasure_due for item in rows(unit, PrivacyControlORM)):
            raise HTTPException(409, "Vorgemerkte Löschungen sind noch offen. Zugriffe bleiben gesperrt.")
        db.put(unit, RestoreReviewORM, {**db.values(current), "pending": False, "revision": current.revision + 1,
            "actor_id": unit.actor_id, "reason": command.reason, "journal_sha256": command.journal_sha256, "updated_at": db.now()})
        return receipt(unit, "restore_review", "restore", "current", command, command.journal_sha256, {"pending": False})


def _present(unit, kind, identifier):
    if kind == "document":
        from ..maintenance_rows import Rows
        return Rows.of(unit).get("documents", identifier) is not None
    item = db.row(unit, resources.MODELS[kind], identifier, required=False)
    if item is None:
        return False
    if kind in ("import_batch", "portability_export"):
        return item.state != "erased"
    if kind == "portal_identity":
        return item.password_hash is not None or not item.email.startswith("erased-")
    if kind == "portal_case":
        from ...db.external_portal_models import PortalMessageORM
        return bool(rows(unit, PortalMessageORM, case_link_id=identifier))
    return True


def merge(store, actor_id, command):
    data = [item.model_dump(mode="json") for item in command.controls]
    if digest({"format": FORMAT, "controls": data}) != command.source_sha256 or len({item.id for item in command.controls}) != len(data):
        raise HTTPException(422, "Datenschutzjournal hat eine falsche Prüfsumme oder doppelte Einträge.")
    with work(store, actor_id) as unit:
        if previous := replay(unit, "import_journal", "journal", "current", command):
            return previous
        lock_sources(unit)
        count = 0
        for incoming in command.controls:
            if incoming.id != key(incoming.kind, incoming.record_id):
                raise HTTPException(422, "Datenschutzjournal enthält eine falsche Ressourcenkennung.")
            old = control(unit, incoming.kind, incoming.record_id)
            value = incoming.model_dump()
            due = bool((incoming.erased_at or incoming.erasure_due) and _present(unit, incoming.kind, incoming.record_id))
            # Never downgrade a local hold, restriction or executed tombstone.
            value.update(held=incoming.held or bool(old and old.held),
                restricted=incoming.restricted or bool(old and old.restricted) or due,
                erased_at=None if due else old.erased_at if old and old.erased_at else incoming.erased_at,
                erasure_due=due or bool(old and old.erasure_due), revision=max(incoming.revision, old.revision if old else 0) + 1,
                actor_id=unit.actor_id, reason=command.reason, updated_at=db.now())
            db.put(unit, PrivacyControlORM, value)
            count += 1
        current = review(unit)
        if any(item.erasure_due for item in rows(unit, PrivacyControlORM)):
            db.put(unit, RestoreReviewORM, {**db.values(current), "pending": True, "revision": current.revision + 1, "updated_at": db.now()})
        return receipt(unit, "import_journal", "journal", "current", command, command.source_sha256,
            {"merged": count, "journal_sha256": snapshot(unit)["sha256"], "notice": "Importierte Sperren werden nicht gelockert. Wiederhergestellte Löschkandidaten müssen ausdrücklich erneut gelöscht werden."})


def decisions(store, actor_id, *, skip=0, limit=25):
    with work(store, actor_id) as unit:
        items = sorted(rows(unit, PrivacyDecisionORM), key=lambda item: (item.created_at, item.id), reverse=True)
        return {"items": [{name: resources._plain(value) for name, value in db.values(item).items()
                 if name not in ("idempotency_key", "request_sha256")} for item in items[skip:skip + limit]], "total": len(items)}
