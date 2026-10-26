from fastapi import HTTPException

from ...db.privacy_models import PrivacyControlORM, PrivacyDecisionORM
from ..integrations import connection_storage as db
from . import resources
from .storage import control, key, lock_sources, receipt, replay, rows, work


def detail(store, actor_id, kind, identifier):
    with work(store, actor_id) as unit:
        result = resources.inspect_resource(unit, kind, identifier)
        result["decisions"] = [{"action": row.action, "reason": row.reason, "actor_id": row.actor_id, "created_at": row.created_at.isoformat(),
                                "result": row.result} for row in sorted(rows(unit, PrivacyDecisionORM, kind=kind, record_id=identifier), key=lambda item: (item.created_at, item.id))]
        return result


def change(store, actor_id, kind, identifier, command):
    with work(store, actor_id) as unit:
        if previous := replay(unit, command.action, kind, identifier, command):
            return previous
        # All private lifecycle mutations share the import/portal fence; SQLite
        # and memory hold their existing single writer for the entire operation.
        lock_sources(unit)
        current = resources.inspect_resource(unit, kind, identifier)
        if current["revision"] != command.expected_revision or current["source_sha256"] != command.source_sha256:
            raise HTTPException(409, "Daten oder Datenschutzentscheidung wurden inzwischen geändert. Bitte erneut prüfen.")
        if current["erased_at"]:
            raise HTTPException(409, "Eine ausgeführte Löschentscheidung kann nicht aufgehoben werden.")
        existing = control(unit, kind, identifier)
        value = db.values(existing) if existing else {"id": key(kind, identifier), "kind": kind, "record_id": identifier,
            "held": False, "restricted": False, "erased_at": None, "erasure_due": False, "revision": 0, "created_at": db.now()}
        outcome = {}
        if command.action == "erase":
            if not current["can_erase"]:
                raise HTTPException(409, "Löschen gesperrt: " + " ".join(current["blockers"]))
            outcome = resources.erase(unit, kind, identifier)
            value.update(restricted=True, erased_at=db.now(), erasure_due=False)
        elif command.action in ("hold", "release_hold"):
            value["held"] = command.action == "hold"
        else:
            if command.action == "release_restriction" and value.get("erasure_due"):
                raise HTTPException(409, "Die nach Wiederherstellung vorgemerkte Löschung muss zuerst ausgeführt werden.")
            value["restricted"] = command.action == "restrict"
        value.update(revision=value["revision"] + 1, reason=command.reason, actor_id=unit.actor_id,
                     source_sha256=command.source_sha256, updated_at=db.now())
        db.put(unit, PrivacyControlORM, value)
        result = {"resource": resources.inspect_resource(unit, kind, identifier), "outcome": outcome}
        return receipt(unit, command.action, kind, identifier, command, command.source_sha256, result)
