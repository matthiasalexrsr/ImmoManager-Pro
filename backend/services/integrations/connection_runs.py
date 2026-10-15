"""Durable explicit action runs; a lost answer never starts a second external write.

The public commands authorize source/configuration before claiming a run. Only
an internal, already issued lease may finish its encrypted receipt afterward;
that completion cannot alter any business source, even after rights withdrawal.
"""

from __future__ import annotations

import hashlib
import secrets
from contextlib import contextmanager
from datetime import timedelta
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...db.integration_connection_models import (
    IntegrationActionRunORM,
    IntegrationConnectionORM,
    IntegrationSourceBlockORM,
)
from .. import document_versions as archive
from ..secret_box import SecretError
from ..sqlite_writes import sqlite_write_gate
from ..workspace_contexts import resolve_context
from . import connection_storage as storage
from .connection_types import RunCancellation, RunDispatch, RunPreparation
from .connections import Connections
from .validation import field_errors

LEASE_SECONDS = 300
FINAL = frozenset({"completed", "accepted", "cancelled", "reconciled"})


class ConnectionRuns(Connections):
    def _access(self, unit, run, *, write: bool = False):
        if run.actor_id != unit.actor_id and (write or unit.user["role"] != "eigentuemer"):
            raise HTTPException(404, "Vorgang nicht gefunden.")
        if run.source_kind and run.source_id:
            return resolve_context(unit.store, run.source_kind, run.source_id, unit.actor_id, lock=write)
        return None

    def public_run(self, unit, run) -> dict:
        self._access(unit, run)
        expired = run.state == "executing" and run.lease_until is not None and run.lease_until <= storage.now()
        checkpoint = storage.unseal(run.checkpoint_token, f"connection-run/{run.id}/checkpoint", self.box) if run.checkpoint_token else {}
        return {"id": run.id, "connection_id": run.connection_id, "actor_id": run.actor_id,
                "action": run.action, "effect": run.effect, "state": run.state,
                "interrupted": expired, "external_outcome_unknown": run.state == "unknown" or (expired and run.effect == "external_write"),
                "revision": run.revision, "config_revision": run.config_revision, "attempts": run.attempts,
                "source_kind": run.source_kind, "source_id": run.source_id, "source_revision": run.source_revision,
                "safe_summary": run.safe_summary, "completed_pages": checkpoint.get("completed_pages", 0),
                "has_more": run.state == "awaiting_page", "result_sha256": run.result_sha256,
                "result_bytes": run.result_bytes, "result_blocks": run.result_blocks,
                "created_at": storage.stamp(run.created_at), "updated_at": storage.stamp(run.updated_at)}

    def get_run(self, identifier: str, run_id: str, actor_id: str) -> dict:
        with storage.work(self.store, actor_id) as unit:
            storage.row(unit, IntegrationConnectionORM, identifier)
            run = storage.row(unit, IntegrationActionRunORM, run_id)
            if run.connection_id != identifier:
                raise HTTPException(404, "Vorgang nicht gefunden.")
            return self.public_run(unit, run)

    def runs(self, identifier: str, actor_id: str, *, cursor=None, limit=50) -> dict:
        with storage.work(self.store, actor_id) as unit:
            storage.row(unit, IntegrationConnectionORM, identifier)
            filters = {"connection_id": identifier}
            if unit.user["role"] != "eigentuemer":
                filters["actor_id"] = actor_id
            page = storage.page(unit, IntegrationActionRunORM, actor_id, cursor=cursor, limit=limit, **filters)
            page["items"] = [self.public_run(unit, run) for run in page["items"]]
            return page

    def prepare(self, identifier: str, payload: RunPreparation, actor_id: str) -> dict:
        with storage.work(self.store, actor_id, write=True) as unit:
            connection = storage.row(unit, IntegrationConnectionORM, identifier, lock=True)
            prior = storage.replay(unit, "prepare:" + identifier, payload)
            if prior:
                return self.public_run(unit, storage.row(unit, IntegrationActionRunORM, prior["run_id"]))
            storage.revision(connection, payload.config_revision)
            if connection.archived or not connection.enabled:
                raise HTTPException(409, "Diese Verbindung ist deaktiviert.")
            config = self.effective_config(unit, connection)
            self._checked(connection.provider_id, config, enabled=True)
            action = self.action(connection.provider_id, payload.action)
            inputs = action.get("inputs", [])
            errors = field_errors(payload.payload, inputs, required=True)
            allowed = {field["key"] for field in inputs}
            if set(payload.payload) - allowed or errors:
                raise HTTPException(422, {"code": "invalid_action", "message": "Bitte die Angaben für die ausgewählte Aktion prüfen.",
                                          "errors": errors, "unknown_fields": sorted(set(payload.payload) - allowed)})
            if payload.source_kind:
                assert payload.source_id is not None and payload.source_revision is not None
                source = resolve_context(unit.store, payload.source_kind, payload.source_id, actor_id, lock=True)
                storage.commands.check_revision(payload.source_revision, source["revision"])
            identifier_run = str(uuid4())
            request = {**payload.payload, "action": payload.action}
            stamp = storage.now()
            run = storage.put(unit, IntegrationActionRunORM, {
                "id": identifier_run, "connection_id": identifier, "actor_id": actor_id,
                "command_key": payload.idempotency_key, "fingerprint": storage.digest(payload.model_dump(mode="json")),
                "action": payload.action, "effect": action["effect"], "state": "prepared", "revision": 1,
                "config_revision": connection.revision, "source_kind": payload.source_kind, "source_id": payload.source_id,
                "source_revision": payload.source_revision,
                "config_snapshot_token": storage.seal(self.snapshot(connection), f"connection-run/{identifier_run}/configuration", self.box),
                "action_manifest_token": storage.seal(action, f"connection-run/{identifier_run}/action", self.box),
                "request_token": storage.seal(request, f"connection-run/{identifier_run}/request", self.box),
                "request_sha256": storage.digest(request), "checkpoint_token": None, "result_token": None,
                "result_sha256": None, "result_bytes": 0, "result_blocks": 0, "lease_token": None, "lease_until": None,
                "attempts": 0, "safe_summary": "Vorschau vorbereitet; noch nicht ausgeführt.", "created_at": stamp, "updated_at": stamp,
            })
            storage.record_event(unit, identifier, "run_prepared", {"request_sha256": run.request_sha256,
                "config_revision": run.config_revision, "effect": run.effect}, run_id=run.id, box=self.box)
            storage.receipt(unit, "prepare:" + identifier, payload, identifier, {"run_id": run.id})
            return self.public_run(unit, run)

    @contextmanager
    def _receipt_writer(self, actor_id: str):
        """Private capability boundary: caller still must check the exact active lease.

        Not exposed as an API. It persists facts about an already authorized
        attempt, never an application source or a new external attempt.
        """
        if not hasattr(self.store, "db"):
            memory = archive.memory_archive(self.store)
            with memory.lock:
                unit = archive.Unit(store=self.store, db=None, user={"id": actor_id, "role": "receipt_only"}, archive=memory)
                try:
                    yield unit
                except BaseException:
                    unit.rollback()
                    raise
            return
        from ...repositories.sql_store import SQLAlchemyStore
        bind = self.store.db.get_bind()
        with sqlite_write_gate(bind, "connection-receipt"):
            with Session(bind=getattr(bind, "engine", bind), autoflush=False, expire_on_commit=False) as db:
                try:
                    archive.begin_writer(db)
                    unit = archive.Unit(store=SQLAlchemyStore(db), db=db, user={"id": actor_id, "role": "receipt_only"}, archive=None)
                    yield unit
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise

    def _save_result(self, unit, run, raw: dict, category: str) -> dict[str, Any]:
        payload = storage.canonical(raw)
        sha = hashlib.sha256(payload).hexdigest()
        count = 0
        for number, start in enumerate(range(0, len(payload), storage.BLOCK_BYTES)):
            chunk = payload[start:start + storage.BLOCK_BYTES]
            import base64
            block_id = str(uuid4())
            storage.put(unit, IntegrationSourceBlockORM, {
                "id": block_id, "run_id": run.id, "category": category, "sequence": number,
                "sha256": hashlib.sha256(chunk).hexdigest(), "byte_length": len(chunk),
                "data_token": storage.seal(base64.b64encode(chunk).decode("ascii"), f"connection-block/{block_id}", self.box),
                "created_at": storage.now(),
            })
            count += 1
        return {"sha256": sha, "bytes": len(payload), "blocks": count, "category": category}

    def _finish(self, run_id: str, lease: str, actor_id: str, outcome: dict, action: dict) -> None:
        with self._receipt_writer(actor_id) as unit:
            run = storage.row(unit, IntegrationActionRunORM, run_id, lock=True)
            if run.lease_token != lease or run.state != "executing":
                # Never let an old worker publish after another worker fenced it.
                # Its explicit failure is not permission to repeat the external call.
                raise HTTPException(409, "Der Ausführungsstand wurde übernommen. Den externen Zustand vor weiteren Aktionen prüfen.")
            category = f"attempt-{run.attempts}"
            original = self._save_result(unit, run, outcome, category)
            checkpoint = storage.unseal(run.checkpoint_token, f"connection-run/{run_id}/checkpoint", self.box) if run.checkpoint_token else {"completed_pages": 0}
            more = False
            if outcome["success"]:
                checkpoint["completed_pages"] += 1
                if action.get("cursor_field") and run.effect != "external_write":
                    details = outcome.get("details")
                    has_more = details.get(action.get("has_more_field", "has_more")) if isinstance(details, dict) else None
                    cursor = details.get(action.get("next_cursor_field", "next_cursor")) if isinstance(details, dict) else None
                    valid = isinstance(has_more, bool)
                    more = has_more is True
                    if more:
                        valid = valid and isinstance(cursor, str) and bool(cursor)
                        if valid:
                            assert isinstance(cursor, str)
                            cursor_bytes = cursor.encode("utf-8")
                            cursor_hash = hashlib.sha256(cursor_bytes).hexdigest()
                            seen = storage.find_one(unit, IntegrationSourceBlockORM, run_id=run_id,
                                                    category="cursor-seen", sha256=cursor_hash)
                            valid = seen is None
                        if valid:
                            import base64
                            block_id = str(uuid4())
                            storage.put(unit, IntegrationSourceBlockORM, {
                                "id": block_id, "run_id": run_id, "category": "cursor-seen", "sequence": run.attempts,
                                "sha256": cursor_hash, "byte_length": len(cursor_bytes),
                                "data_token": storage.seal(base64.b64encode(cursor_bytes).decode("ascii"), f"connection-block/{block_id}", self.box),
                                "created_at": storage.now(),
                            })
                            checkpoint["cursor"] = cursor
                    if not valid:
                        outcome = {**outcome, "success": False, "cursor_error": True}
                        checkpoint["completed_pages"] -= 1
                        more = False
                state = "awaiting_page" if more else "accepted" if run.effect == "external_write" else "completed"
            else:
                state = "unknown" if run.effect == "external_write" else "retryable"
            if outcome.get("cursor_error"):
                state = "blocked"
            summary = {"awaiting_page": "Abschnitt gespeichert; weitere Daten sind verfügbar.",
                       "accepted": "Extern angenommen; eine Zustellung oder spätere Ausführung ist damit nicht bewiesen.",
                       "completed": "Aktion ausgeführt und Ergebnis gespeichert.",
                       "unknown": "Externer Ausgang unklar. Nicht erneut senden; zuerst abgleichen.",
                       "retryable": "Lesender oder lokaler Schritt fehlgeschlagen; ausdrücklich erneut versuchen.",
                       "blocked": "Die Fortsetzung der Quelle ist widersprüchlich. Keine Vollständigkeit bestätigt."}[state]
            updated = storage.put(unit, IntegrationActionRunORM, {**storage.values(run), "state": state,
                "revision": run.revision + 1, "lease_token": None, "lease_until": None,
                "safe_summary": summary, "result_sha256": original["sha256"],
                "result_bytes": (run.result_bytes or 0) + original["bytes"],
                "result_blocks": (run.result_blocks or 0) + original["blocks"],
                "result_token": storage.seal(original, f"connection-run/{run_id}/result", self.box),
                "checkpoint_token": storage.seal(checkpoint, f"connection-run/{run_id}/checkpoint", self.box), "updated_at": storage.now()})
            storage.record_event(unit, run.connection_id, "run_" + state, {"attempt": run.attempts,
                "result": original, "revision": updated.revision}, run_id=run.id, box=self.box)

    def dispatch(self, identifier: str, run_id: str, payload: RunDispatch, actor_id: str) -> dict:
        with storage.work(self.store, actor_id, write=True) as unit:
            connection = storage.row(unit, IntegrationConnectionORM, identifier, lock=True)
            run = storage.row(unit, IntegrationActionRunORM, run_id, lock=True)
            if run.connection_id != identifier:
                raise HTTPException(404, "Vorgang nicht gefunden.")
            source = self._access(unit, run, write=True)
            prior = storage.replay(unit, "dispatch:" + run_id, payload)
            if prior:
                return self.public_run(unit, run)
            storage.revision(run, payload.base_revision)
            if run.state == "executing":
                if run.lease_until is not None and run.lease_until > storage.now():
                    raise HTTPException(409, "Dieser Vorgang wird bereits ausgeführt.")
                state = "unknown" if run.effect == "external_write" else "retryable"
                run = storage.put(unit, IntegrationActionRunORM, {**storage.values(run), "state": state,
                    "lease_token": None, "lease_until": None, "revision": run.revision + 1,
                    "safe_summary": "Ein früherer Versuch wurde unterbrochen; Ergebnis zuerst prüfen.", "updated_at": storage.now()})
                storage.receipt(unit, "dispatch:" + run_id, payload, identifier, {"run_id": run_id})
                return self.public_run(unit, run)
            if run.state not in {"prepared", "retryable", "awaiting_page"} or (run.effect == "external_write" and run.state != "prepared"):
                raise HTTPException(409, "Dieser Vorgang darf nicht erneut ausgeführt werden. Bitte seinen Ergebnisstand prüfen.")
            storage.revision(connection, run.config_revision)
            if not connection.enabled or connection.archived:
                raise HTTPException(409, "Die Verbindung ist inzwischen deaktiviert.")
            if source:
                storage.commands.check_revision(run.source_revision, source["revision"])
            action = self.action(connection.provider_id, run.action)
            original_action = storage.unseal(run.action_manifest_token, f"connection-run/{run_id}/action", self.box)
            if storage.digest(action) != storage.digest(original_action):
                raise HTTPException(409, "Der Aktionsvertrag wurde geändert. Bitte eine neue Vorschau erstellen.")
            snapshot = storage.unseal(run.config_snapshot_token, f"connection-run/{run_id}/configuration", self.box)
            raw_config = self.effective_config(unit, connection, snapshot=snapshot)
            config = self._checked(connection.provider_id, raw_config, enabled=True)["applicable"]
            request = storage.unseal(run.request_token, f"connection-run/{run_id}/request", self.box)
            checkpoint = storage.unseal(run.checkpoint_token, f"connection-run/{run_id}/checkpoint", self.box) if run.checkpoint_token else {}
            if checkpoint.get("cursor") and action.get("cursor_field"):
                request[action["cursor_field"]] = checkpoint["cursor"]
            lease = secrets.token_urlsafe(32)
            run = storage.put(unit, IntegrationActionRunORM, {**storage.values(run), "state": "executing",
                "attempts": run.attempts + 1, "revision": run.revision + 1, "lease_token": lease,
                "lease_until": storage.now() + timedelta(seconds=LEASE_SECONDS),
                "safe_summary": "Ausführung begonnen; Ergebnis noch unbestätigt.", "updated_at": storage.now()})
            storage.record_event(unit, identifier, "dispatch_started", {"attempt": run.attempts, "effect": run.effect}, run_id=run_id, box=self.box)
            storage.receipt(unit, "dispatch:" + run_id, payload, identifier, {"run_id": run_id})
            provider = self.provider(connection.provider_id)
        # The claim and checkpoint are committed before the provider is entered.
        # There is no open business transaction during network IO.
        try:
            result = provider.run(request, config)
            outcome = {"success": bool(result.success), "message": result.message, "details": result.details}
        except Exception as error:
            outcome = {"success": False, "message": "Der Anbieteraufruf wurde nicht bestätigt.",
                       "details": {"error_type": type(error).__name__}}
        try:
            self._finish(run_id, lease, actor_id, outcome, action)
        except (SecretError, OSError, HTTPException, SQLAlchemyError):
            # The database still says executing (or a later fence); do not claim
            # 'not sent' or silently replace an unpersisted acknowledgement.
            raise HTTPException(503, "Die Ausführung ist nicht dauerhaft bestätigt. Externen Zustand abgleichen; nicht erneut senden.") from None
        return self.get_run(identifier, run_id, actor_id)

    def cancel(self, identifier: str, run_id: str, payload: RunCancellation, actor_id: str) -> dict:
        with storage.work(self.store, actor_id, write=True) as unit:
            storage.row(unit, IntegrationConnectionORM, identifier, lock=True)
            run = storage.row(unit, IntegrationActionRunORM, run_id, lock=True)
            if run.connection_id != identifier:
                raise HTTPException(404, "Vorgang nicht gefunden.")
            self._access(unit, run, write=True)
            prior = storage.replay(unit, "cancel:" + run_id, payload)
            if prior:
                return self.public_run(unit, run)
            storage.revision(run, payload.base_revision)
            if run.state not in {"prepared", "retryable", "awaiting_page"}:
                raise HTTPException(409, "Eine begonnene oder unklare externe Aktion kann nicht als ungesendet abgebrochen werden.")
            run = storage.put(unit, IntegrationActionRunORM, {**storage.values(run), "state": "cancelled",
                "revision": run.revision + 1, "safe_summary": "Weitere Schritte ausdrücklich abgebrochen; frühere Ergebnisse bleiben erhalten.",
                "updated_at": storage.now()})
            storage.record_event(unit, identifier, "run_cancelled", {"reason": payload.reason}, run_id=run_id, box=self.box)
            storage.receipt(unit, "cancel:" + run_id, payload, identifier, {"run_id": run_id})
            return self.public_run(unit, run)

    def preview(self, identifier: str, run_id: str, actor_id: str) -> dict:
        """Read the frozen, user-selected action, never the connection credentials."""
        with storage.work(self.store, actor_id) as unit:
            storage.row(unit, IntegrationConnectionORM, identifier)
            run = storage.row(unit, IntegrationActionRunORM, run_id)
            if run.connection_id != identifier:
                raise HTTPException(404, "Vorgang nicht gefunden.")
            self._access(unit, run)
            action = storage.unseal(run.action_manifest_token, f"connection-run/{run_id}/action", self.box)
            payload = storage.unseal(run.request_token, f"connection-run/{run_id}/request", self.box)
            if storage.digest(payload) != run.request_sha256:
                raise HTTPException(503, "Die gespeicherte Vorschau stimmt nicht mit ihrem Quellnachweis überein.")
            allowed = {field["key"] for field in action.get("inputs", [])}
            secret_fields = {field["key"] for field in action.get("inputs", []) if field.get("secret")}
            return {"run": self.public_run(unit, run), "action": action,
                    "payload": {key: "***" if key in secret_fields else value for key, value in payload.items() if key in allowed},
                    "request_sha256": run.request_sha256, "external_action_started": run.attempts > 0}
