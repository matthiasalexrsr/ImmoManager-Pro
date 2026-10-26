from uuid import uuid4

from fastapi import HTTPException

from ...db.privacy_models import PrivacyRequestORM
from ..data_transfer.common import digest
from ..integrations import connection_storage as db
from . import subjects
from .resources import _plain
from .storage import lock_sources, receipt, replay, rows, work


def public(row):
    return {key: _plain(value) for key, value in db.values(row).items() if key not in ("idempotency_key", "request_sha256")}


def listing(store, actor_id, *, skip=0, limit=25):
    with work(store, actor_id) as unit:
        found = sorted(rows(unit, PrivacyRequestORM), key=lambda item: (item.due_on, item.id))
        return {"items": [public(item) for item in found[skip:skip + limit]], "total": len(found)}


def create(store, actor_id, command):
    with work(store, actor_id) as unit:
        before = db.find_one(unit, PrivacyRequestORM, created_by=unit.actor_id, idempotency_key=command.idempotency_key)
        sha = digest(command.model_dump(mode="json"))
        if before:
            if before.request_sha256 != sha:
                raise HTTPException(409, "Wiederholungskennung gehört zu einer anderen Anfrage.")
            return public(before)
        subjects.inventory(unit, command.subject_kind, command.subject_id)
        row = db.put(unit, PrivacyRequestORM, {"id": str(uuid4()), **command.model_dump(exclude={"idempotency_key"}),
            "state": "open", "revision": 1, "outcome": {}, "created_by": unit.actor_id, "idempotency_key": command.idempotency_key,
            "request_sha256": sha, "created_at": db.now(), "updated_at": db.now()})
        return public(row)


def detail(store, actor_id, identifier):
    with work(store, actor_id) as unit:
        item = db.row(unit, PrivacyRequestORM, identifier)
        return {**public(item), **subjects.inventory(unit, item.subject_kind, item.subject_id)}


def decide(store, actor_id, identifier, command):
    with work(store, actor_id) as unit:
        if previous := replay(unit, "request_decision", "request", identifier, command):
            return previous
        lock_sources(unit)
        item = db.row(unit, PrivacyRequestORM, identifier, lock=True)
        current = subjects.inventory(unit, item.subject_kind, item.subject_id)
        if item.revision != command.expected_revision or current["source_sha256"] != command.source_sha256:
            raise HTTPException(409, "Die Anfrage oder zugehörige Daten wurden geändert. Bitte erneut prüfen.")
        if item.request_type == "erasure" and command.outcome == "fulfilled":
            data = current["data"]
            from ...routers.admin import _CONTACT_PERSONAL_FIELDS, _TENANT_PERSONAL_FIELDS
            fields = _TENANT_PERSONAL_FIELDS if item.subject_kind == "tenant" else _CONTACT_PERSONAL_FIELDS
            masked = (data["subject"].get("full_name") or data["subject"].get("last_name") or "").startswith("Anonymisiert-") and not any(data["subject"].get(field) for field in fields)
            if not masked or current["retained_records"] or any(data["extensions"][name] for name in ("portal_messages", "portal_images", "e_invoice_intakes", "import_references")):
                raise HTTPException(409, "Es sind weiterhin zugehörige personenbezogene Daten vorhanden. Bitte die teilweise Erfüllung oder Zurückstellung mit den aufbewahrten Beständen dokumentieren.")
        outcome = {"state": command.outcome, "reason": command.reason, "source_sha256": command.source_sha256,
            "retained_records": current["retained_records"], "actor_id": unit.actor_id, "decided_at": db.now().isoformat()}
        row = db.put(unit, PrivacyRequestORM, {**db.values(item), "state": command.outcome, "outcome": outcome,
            "revision": item.revision + 1, "updated_at": db.now()})
        return receipt(unit, "request_decision", "request", identifier, command, command.source_sha256, public(row))
