"""Durable per-attempt facts, independent of whether a worker still owns a run.

An issued lease may record exactly its own result after expiry or permission
withdrawal. It cannot mutate a replacement run, grant rights, or call a provider.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from ...db.integration_attempt_models import IntegrationActionAttemptORM, IntegrationRunCursorORM
from ...db.integration_connection_models import (
    IntegrationActionRunORM,
    IntegrationConnectionORM,
    IntegrationSourceBlockORM,
)
from . import connection_evidence as evidence
from . import connection_storage as storage

SUMMARIES = {
    "awaiting_page": "Abschnitt gespeichert; weitere Daten sind verfügbar.",
    "accepted": "Extern angenommen; eine Zustellung oder spätere Ausführung ist damit nicht bewiesen.",
    "completed": "Aktion ausgeführt und Ergebnis gespeichert.",
    "unknown": "Externer Ausgang unklar. Nicht erneut senden; zuerst abgleichen.",
    "retryable": "Lesender oder lokaler Schritt fehlgeschlagen; ausdrücklich erneut versuchen.",
    "blocked": "Die Fortsetzung der Quelle ist widersprüchlich. Keine Vollständigkeit bestätigt.",
}


def identity(run, attempt) -> dict:
    return {"id": attempt.id, "run_id": run.id, "connection_id": run.connection_id,
            "number": attempt.number, "actor_id": attempt.actor_id,
            "lease_sha256": attempt.lease_sha256, "request_sha256": attempt.request_sha256,
            "action": run.action, "effect": run.effect, "config_revision": run.config_revision,
            "source_kind": run.source_kind, "source_id": run.source_id, "source_revision": run.source_revision,
            "created_at": storage.stamp(attempt.created_at)}


def claim(service, unit, run, lease: str, request: dict, snapshot: dict, action: dict):
    data = {"id": str(uuid4()), "run_id": run.id, "number": run.attempts, "actor_id": run.actor_id,
            "lease_sha256": hashlib.sha256(lease.encode()).hexdigest(), "request_sha256": storage.digest(request),
            "input_token": "", "state": "started", "success": None, "manifest_token": None,
            "result_sha256": None, "result_bytes": 0, "result_blocks": 0, "detached": False,
            "reviewed_by": None, "reviewed_at": None, "created_at": storage.now(), "finished_at": None}
    binding = identity(run, SimpleNamespace(**data))
    data["input_token"] = storage.seal({"identity": binding, "request": request,
        "configuration": snapshot, "action": action}, f"connection-attempt/{data['id']}/input", service.box)
    return storage.put(unit, IntegrationActionAttemptORM, data)


def checked_input(service, run, attempt) -> dict:
    value = storage.unseal(attempt.input_token, f"connection-attempt/{attempt.id}/input", service.box)
    if (not isinstance(value, dict) or value.get("identity") != identity(run, attempt)
            or attempt.actor_id != run.actor_id or storage.digest(value.get("request")) != attempt.request_sha256):
        raise evidence.invalid()
    return value


def save_result(service, unit, run, attempt, outcome: dict) -> dict:
    content = storage.canonical(outcome)
    category = f"attempt-{attempt.number}"
    for number, start in enumerate(range(0, len(content), storage.BLOCK_BYTES)):
        chunk = content[start:start + storage.BLOCK_BYTES]
        data = {"id": str(uuid4()), "run_id": run.id, "category": category, "sequence": number,
                "sha256": hashlib.sha256(chunk).hexdigest(), "byte_length": len(chunk),
                "data_token": "", "created_at": storage.now()}
        data["data_token"] = evidence.encode_block(SimpleNamespace(**data), chunk, service.box)
        storage.put(unit, IntegrationSourceBlockORM, data)
    return {"format": evidence.RESULT_FORMAT, "attempt_id": attempt.id, "run_id": run.id,
            "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
            "blocks": (len(content) + storage.BLOCK_BYTES - 1) // storage.BLOCK_BYTES,
            "category": category, "representation": "canonical_provider_result_json"}


def transition(unit, run, outcome: dict, action: dict, checkpoint: dict) -> tuple[str, dict]:
    checkpoint = dict(checkpoint)
    completed = checkpoint.get("completed_pages", 0)
    if type(completed) is not int or completed < 0:
        raise evidence.invalid()
    if outcome.get("success") is not True:
        return ("unknown" if run.effect == "external_write" else "retryable"), checkpoint
    more = False
    if action.get("cursor_field") and run.effect != "external_write":
        details = outcome.get("details")
        flag = details.get(action.get("has_more_field", "has_more")) if isinstance(details, dict) else None
        if type(flag) is not bool:
            return "blocked", checkpoint
        more = flag
        if more:
            assert isinstance(details, dict)
            cursor = details.get(action.get("next_cursor_field", "next_cursor"))
            if not isinstance(cursor, str) or not cursor:
                return "blocked", checkpoint
            digest = hashlib.sha256(cursor.encode()).hexdigest()
            if (digest in checkpoint.get("seen_cursor_hashes", []) or
                    storage.find_one(unit, IntegrationRunCursorORM, run_id=run.id, cursor_sha256=digest) is not None):
                return "blocked", checkpoint
            storage.put(unit, IntegrationRunCursorORM, {"id": str(uuid4()), "run_id": run.id,
                "cursor_sha256": digest, "first_attempt": run.attempts, "created_at": storage.now()})
            checkpoint["cursor"] = cursor
        else:
            checkpoint.pop("cursor", None)
    checkpoint["completed_pages"] = completed + 1
    state = "awaiting_page" if more else "accepted" if run.effect == "external_write" else "completed"
    return state, checkpoint


def finish(service, run_id: str, lease: str, actor_id: str, outcome: dict, _action: dict) -> None:
    with service._receipt_writer(actor_id) as unit:
        run = storage.row(unit, IntegrationActionRunORM, run_id, lock=True)
        lease_hash = hashlib.sha256(lease.encode()).hexdigest()
        attempt = storage.find_one(unit, IntegrationActionAttemptORM, lock=True, run_id=run_id, lease_sha256=lease_hash)
        if attempt is None or attempt.actor_id != actor_id:
            raise HTTPException(409, "Dieser Ergebnisnachweis gehört zu keinem ausgegebenen Ausführungsversuch.")
        issued = checked_input(service, run, attempt)
        if attempt.state == "finished":
            if attempt.result_sha256 == storage.digest(outcome):
                return
            raise HTTPException(409, "Ein abgeschlossener Ausführungsnachweis wird nicht ersetzt.")
        if attempt.state != "started":
            raise evidence.invalid()
        current = run.state == "executing" and run.lease_token == lease and run.attempts == attempt.number
        result = save_result(service, unit, run, attempt, outcome)
        stamp = storage.now()
        manifest = {"identity": identity(run, attempt), "result": result,
                    "finished_at": storage.stamp(stamp), "detached": not current}
        storage.put(unit, IntegrationActionAttemptORM, {**storage.values(attempt), "state": "finished",
            "success": outcome.get("success") is True, "manifest_token": storage.seal(manifest,
                f"connection-attempt/{attempt.id}/result", service.box),
            "result_sha256": result["sha256"], "result_bytes": result["bytes"], "result_blocks": result["blocks"],
            "detached": not current, "reviewed_at": stamp if current else None,
            "reviewed_by": actor_id if current else None, "finished_at": stamp})
        if not current:
            # A late acknowledgement remains retrievable without changing a
            # successor's state/checkpoint or issuing a new external command.
            storage.record_event(unit, run.connection_id, "late_result_retained",
                {"attempt_id": attempt.id, "number": attempt.number, "result": result}, run_id=run.id, box=service.box)
            return
        checkpoint = storage.unseal(run.checkpoint_token, f"connection-run/{run_id}/checkpoint", service.box) if run.checkpoint_token else {}
        state, checkpoint = transition(unit, run, outcome, issued["action"], checkpoint)
        storage.put(unit, IntegrationActionRunORM, {**storage.values(run), "state": state,
            "revision": run.revision + 1, "lease_token": None, "lease_until": None,
            "safe_summary": SUMMARIES[state], "result_sha256": result["sha256"],
            "result_bytes": (run.result_bytes or 0) + result["bytes"],
            "result_blocks": (run.result_blocks or 0) + result["blocks"],
            "result_token": storage.seal(result, f"connection-run/{run_id}/result", service.box),
            "checkpoint_token": storage.seal(checkpoint, f"connection-run/{run_id}/checkpoint", service.box),
            "updated_at": stamp})
        storage.record_event(unit, run.connection_id, "run_" + state,
            {"attempt_id": attempt.id, "number": attempt.number, "result": result}, run_id=run.id, box=service.box)


def checked_result(service, unit, run, attempt) -> tuple[dict, dict, Any]:
    issued = checked_input(service, run, attempt)
    if attempt.state != "finished" or not attempt.manifest_token or not attempt.finished_at:
        raise HTTPException(409, "Für diesen Versuch liegt noch kein abgeschlossener Ergebnisnachweis vor.")
    manifest = storage.unseal(attempt.manifest_token, f"connection-attempt/{attempt.id}/result", service.box)
    if (not isinstance(manifest, dict) or manifest.get("identity") != identity(run, attempt)
            or manifest.get("finished_at") != storage.stamp(attempt.finished_at)
            or manifest.get("detached") != attempt.detached):
        raise evidence.invalid()
    result = manifest.get("result", {})
    if (result.get("attempt_id") != attempt.id or result.get("sha256") != attempt.result_sha256
            or result.get("bytes") != attempt.result_bytes or result.get("blocks") != attempt.result_blocks):
        raise evidence.invalid()
    value = evidence.result_value(unit, run.id, result, service.box)
    if not isinstance(value, dict) or (value.get("success") is True) != attempt.success:
        raise evidence.invalid()
    return issued, result, value


def public_attempt(attempt) -> dict:
    return {"id": attempt.id, "run_id": attempt.run_id, "number": attempt.number, "state": attempt.state,
            "detached": attempt.detached, "reviewed_at": storage.stamp(attempt.reviewed_at) if attempt.reviewed_at else None,
            "success": attempt.success, "request_sha256": attempt.request_sha256,
            "result_sha256": attempt.result_sha256, "result_bytes": attempt.result_bytes,
            "result_blocks": attempt.result_blocks, "created_at": storage.stamp(attempt.created_at),
            "finished_at": storage.stamp(attempt.finished_at) if attempt.finished_at else None}


def summary(unit, run_id: str) -> dict:
    if unit.db is None:
        rows = [item for item in storage.memory(unit, IntegrationActionAttemptORM).values() if item.run_id == run_id]
        return {"recorded_attempts": len(rows), "retained_result_bytes": sum(item.result_bytes for item in rows),
                "late_result_count": sum(item.state == "finished" and item.detached and item.reviewed_at is None for item in rows)}
    model = IntegrationActionAttemptORM
    total, size = unit.db.execute(select(func.count(model.id), func.coalesce(func.sum(model.result_bytes), 0)).where(model.run_id == run_id)).one()
    late = unit.db.scalar(select(func.count(model.id)).where(model.run_id == run_id, model.state == "finished",
                                                            model.detached.is_(True), model.reviewed_at.is_(None)))
    return {"recorded_attempts": total, "retained_result_bytes": size, "late_result_count": late}


def list_attempts(service, identifier: str, run_id: str, actor_id: str, *, cursor=None, limit=50) -> dict:
    with storage.work(service.store, actor_id) as unit:
        run = storage.row(unit, IntegrationActionRunORM, run_id)
        if run.connection_id != identifier:
            raise HTTPException(404, "Vorgang nicht gefunden.")
        service._access(unit, run)
        page = storage.page(unit, IntegrationActionAttemptORM, actor_id, cursor=cursor, limit=limit, run_id=run_id)
        page["items"] = [public_attempt(item) for item in page["items"]]
        return page


def read_attempt(service, identifier: str, run_id: str, attempt_id: str, actor_id: str) -> dict:
    with storage.work(service.store, actor_id) as unit:
        connection = storage.row(unit, IntegrationConnectionORM, identifier)
        run = storage.row(unit, IntegrationActionRunORM, run_id)
        attempt = storage.row(unit, IntegrationActionAttemptORM, attempt_id)
        if run.connection_id != identifier or attempt.run_id != run_id:
            raise HTTPException(404, "Ergebnisnachweis nicht gefunden.")
        service._access(unit, run)
        issued, manifest, value = checked_result(service, unit, run, attempt)
        configuration = service.effective_config(unit, connection, snapshot=issued["configuration"])
        secret_values = [configuration[key] for key in issued["configuration"]["secret_refs"] if isinstance(configuration.get(key), str)]
        return {"attempt": public_attempt(attempt), "manifest": manifest, "verified": True,
                "projection": evidence.public_projection(value, secrets=secret_values),
                "projection_is_original": False, "original_representation": "canonical_provider_result_json"}


def reconcile_recorded(service, identifier: str, run_id: str, payload, actor_id: str) -> dict:
    """Apply a late result only after a separate explicit, revision-bound review.

    No provider callback is present in this path. The original result and its
    detached proof remain unchanged; the review is additional metadata/audit.
    """
    with storage.work(service.store, actor_id, write=True, command_key=payload.idempotency_key) as unit:
        storage.row(unit, IntegrationConnectionORM, identifier, lock=True)
        run = storage.row(unit, IntegrationActionRunORM, run_id, lock=True)
        if run.connection_id != identifier:
            raise HTTPException(404, "Vorgang nicht gefunden.")
        service._access(unit, run, write=True, recovery=True)
        prior = storage.replay(unit, "reconcile-recorded:" + run_id, payload)
        if prior:
            return service.public_run(unit, run)
        storage.revision(run, payload.base_revision)
        attempt = storage.row(unit, IntegrationActionAttemptORM, payload.attempt_id, lock=True)
        if attempt.run_id != run_id:
            raise HTTPException(404, "Ergebnisnachweis nicht gefunden.")
        if (run.state not in {"unknown", "retryable", "blocked"}
                or attempt.number != run.attempts or not attempt.detached or attempt.reviewed_at is not None):
            raise HTTPException(409, "Dieser Ergebnisnachweis kann den aktuellen Vorgang nicht ersetzen. Bitte den neuesten Stand prüfen.")
        issued, result, outcome = checked_result(service, unit, run, attempt)
        checkpoint = storage.unseal(run.checkpoint_token, f"connection-run/{run.id}/checkpoint", service.box) if run.checkpoint_token else {}
        state, checkpoint = transition(unit, run, outcome, issued["action"], checkpoint)
        stamp = storage.now()
        run = storage.put(unit, IntegrationActionRunORM, {**storage.values(run), "state": state,
            "revision": run.revision + 1, "lease_token": None, "lease_until": None,
            "safe_summary": SUMMARIES[state], "result_sha256": result["sha256"],
            "result_bytes": (run.result_bytes or 0) + result["bytes"],
            "result_blocks": (run.result_blocks or 0) + result["blocks"],
            "result_token": storage.seal(result, f"connection-run/{run.id}/result", service.box),
            "checkpoint_token": storage.seal(checkpoint, f"connection-run/{run.id}/checkpoint", service.box),
            "updated_at": stamp})
        storage.put(unit, IntegrationActionAttemptORM, {**storage.values(attempt),
            "reviewed_by": actor_id, "reviewed_at": stamp})
        storage.record_event(unit, identifier, "retained_result_reviewed", {
            "attempt_id": attempt.id, "number": attempt.number, "result_sha256": result["sha256"],
            "reason": payload.reason, "state": state, "provider_called": False}, run_id=run_id, box=service.box)
        storage.receipt(unit, "reconcile-recorded:" + run_id, payload, identifier,
            {"run_id": run_id, "attempt_id": attempt.id, "revision": run.revision})
        return service.public_run(unit, run)
