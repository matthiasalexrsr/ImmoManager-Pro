"""TEHA publication on the application's actual archive/account transaction.

Network IO belongs to public ConnectionRuns.prepare/dispatch/cancel. This
adapter only reads completed, hash-verified TEHA results and never dispatches
or retries a provider action. Business rows, original chunks, command receipt
and TEHA receipt all use the SAME Unit/Session and rollback together.
"""
from __future__ import annotations

import base64
import hashlib
import json
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from ..db.document_version_models import CHUNK_BYTES, DocumentVersionORM
from ..db.integration_connection_models import (
    IntegrationActionRunORM,
    IntegrationConnectionORM,
)
from ..db.orm_models import (
    BillingPeriodORM,
    ContractORM,
    DocumentORM,
    MaintenanceCaseORM,
    PropertyORM,
    TaskORM,
    TenantORM,
    UnitORM,
)
from ..db.teha_models import TehaBatchORM as Batch
from ..db.teha_models import TehaItemORM as Item
from ..db.teha_models import TehaMappingORM as Mapping
from ..db.teha_models import TehaReceiptORM as Receipt
from ..db.teha_models import TehaReturnDraftORM as ReturnDraft
from ..models import Document, MaintenanceCase, Task
from . import document_versions as archive
from .integrations import connection_storage as s
from .integrations.connection_runs import ConnectionRuns
from .portfolio_scope import current_scope, refresh_scope, scope_context, scope_from_user
from .providers.teha_provider import EVIDENCE_GAP
from .providers.teha_receive_contract import ExternalIdentity
from .providers.teha_types import TEHA_PORTAL_CONTRACT_VERSION, TehaError, parse_naive_iso_datetime
from .workspace_contexts import bound_actor, resolve_context


def conflict(message):
    raise HTTPException(409, message)


def identity(record):
    shapes = {"property": {"object_id"}, "period": {"object_id", "period_number"},
              "document": {"lieg_nr", "reference"}, "unit": {"lieg_nr", "unit_id"},
              "user": {"termin_id", "user_id"}, "technical_order": {"termin_id"}}
    try:
        kind, parts = record["kind"], record["identity"]
        if set(parts) != shapes[kind]:
            raise ValueError
        for key, value in parts.items():
            if key in {"lieg_nr", "reference"}:
                if not isinstance(value, str):
                    raise ValueError
            elif type(value) is not int or value < (0 if key == "period_number" else 1):
                raise ValueError
        return ExternalIdentity.create(kind, **parts).token
    except (KeyError, ValueError, TypeError):
        raise HTTPException(422, "TEHA-Identität fehlt oder ist widersprüchlich. Keine Zuordnung aus Namen oder Auftragsnummern möglich.") from None


def content(record):
    encoded = record.get("content_base64")
    if encoded is None:
        if record.get("content_sha256") is not None:
            raise HTTPException(422, "Ein Originalhash ohne tatsächliche Originalbytes ist kein Empfangsnachweis.")
        return None
    try:
        result = base64.b64decode(encoded.encode("ascii"), validate=True)
        if base64.b64encode(result).decode("ascii") != encoded or not result.startswith(b"%PDF-"):
            raise ValueError
        if hashlib.sha256(result).hexdigest() != record.get("content_sha256"):
            raise ValueError
        return result
    except (ValueError, UnicodeError, AttributeError):
        raise HTTPException(422, "Die empfangenen Originalbytes stimmen nicht mit dem PDF-/Hashnachweis überein.") from None


class TehaReceive:
    def __init__(self, store, runs: ConnectionRuns):
        self.store, self.runs, self.box = store, runs, runs.box

    @contextmanager
    def work(self, actor, *, write=False, publish=False):
        captured = current_scope()
        if captured is not None and captured.user_id != actor:
            raise HTTPException(403, "Die Benutzerbindung wurde geändert.")
        refresh_scope(captured)
        areas = ("/integrations", "/documents", "/tasks", "/maintenance") if publish else ("/integrations",)
        try:
            with archive.work(self.store, actor, write_areas=areas if write else ()) as unit:
                scope = scope_from_user(unit.user)
                if not scope.unrestricted:
                    raise HTTPException(403, "TEHA-Empfang benötigt derzeit Zugriff auf alle Portfolios.")
                with bound_actor(unit.user), scope_context(scope):
                    yield unit
                    refresh_scope(scope)
                    refresh_scope(captured)
        except SQLAlchemyError:
            raise HTTPException(503, "TEHA konnte nicht sicher gespeichert werden. Den Stand neu laden; Wiederholung mit demselben Schlüssel ist möglich.") from None

    def _connection(self, unit, connection, *, active=False):
        row = s.row(unit, IntegrationConnectionORM, connection, lock=active)
        if row.provider_id != "teha":
            raise HTTPException(404, "Keine TEHA-Verbindung.")
        if active and (row.archived or not row.enabled):
            conflict("Die TEHA-Verbindung wurde deaktiviert. Keine weitere Übernahme möglich.")
        return row

    def _result(self, unit, connection, run_id, *, revision=None, failed=False):
        """Read verified, metadata-bound v2 attempt bytes from the existing connection service.

        No copy of the old block decoder: the shared verifier checks source
        identity, block order/size/hash, run binding and the full result hash.
        """
        self._connection(unit, connection)
        run = s.row(unit, IntegrationActionRunORM, run_id, lock=revision is not None)
        if run.connection_id != connection:
            raise HTTPException(404, "Empfang nicht gefunden.")
        self.runs._access(unit, run)
        if revision is not None:
            s.revision(run, revision)
        if run.state not in ({"retryable", "blocked"} if failed else {"completed"}) or run.effect != "read":
            conflict("Nur ein vollständig bestätigter lesender Empfang kann übernommen werden. Fehler oder Abbruch zuerst im Empfangslauf bearbeiten.")
        manifest = s.unseal(run.result_token, f"connection-run/{run.id}/result", self.box)
        from .integrations.connection_evidence import RESULT_FORMAT, result_bytes

        if (not isinstance(manifest, dict) or manifest.get("format") != RESULT_FORMAT
                or manifest.get("category") != f"attempt-{run.attempts}"
                or manifest.get("sha256") != run.result_sha256):
            raise HTTPException(503, "Der Empfangsnachweis ist widersprüchlich.")
        raw = result_bytes(unit, run.id, manifest, self.box)
        try:
            result = json.loads(raw)
            details = result["details"]
            if details["contract"] != TEHA_PORTAL_CONTRACT_VERSION:
                raise ValueError
            if not failed and (result["success"] is not True or not isinstance(details["records"], list)):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "Unbekannte TEHA-Empfangsfassung. Adapter und Quelle müssen geprüft werden.") from None
        return (run, details) if failed else (run, details["records"])

    def diagnostic(self, connection, run_id, actor):
        messages = {"authentication_expired": "Die TEHA-Anmeldung ist abgelaufen. Zugang prüfen und den lesenden Empfang ausdrücklich erneut starten.",
                    "authentication_failed": "TEHA hat die Anmeldung abgelehnt. Die gespeicherten Zugangsdaten prüfen.",
                    "provider_permission_denied": "Das Portal hat den Zugriff verweigert. Die dortige Berechtigung prüfen.",
                    "provider_schema_changed": "Das Quellformat wurde geändert. Die neue Feldfassung muss geprüft werden.",
                    "provider_rate_limited": "TEHA begrenzt zurzeit die Abrufe. Die angegebene Wartezeit einhalten.",
                    "provider_temporarily_unavailable": "Das Portal ist vorübergehend nicht erreichbar.",
                    "provider_document_not_pdf": "Die gelieferten Bytes sind kein bestätigtes PDF-Original.",
                    "provider_document_invalid_base64": "Die Originaldaten sind beschädigt oder nicht kanonisch kodiert.",
                    "provider_order_property_mismatch": "Termin-ID und Liegenschaftsnummer stimmen im Portal nicht überein."}
        with self.work(actor) as unit:
            run, details = self._result(unit, connection, run_id, failed=True)
            code = details.get("code")
            return {"run_id": run.id, "code": code if code in messages else "teha_receive_requires_review",
                    "message": messages.get(code, "Der Empfang wurde nicht bestätigt. Quellformat, Originalgröße und Verbindungsstand prüfen."),
                    "retryable": details.get("retryable") is True, "retry_after_seconds": details.get("retry_after_seconds")}

    def _batch(self, unit, connection, batch_id, *, active=False):
        self._connection(unit, connection, active=active)
        batch = s.row(unit, Batch, batch_id, lock=active)
        if batch.connection_id != connection:
            raise HTTPException(404, "Empfang nicht gefunden.")
        run = s.row(unit, IntegrationActionRunORM, batch.run_id)
        self.runs._access(unit, run, write=active)
        if run.state != "completed" or run.result_sha256 != batch.source_sha256:
            conflict("Der Quelllauf wurde geändert oder zurückgezogen.")
        if active and batch.state in {"revoked", "cancelled"}:
            conflict("Dieser Empfang wurde abgebrochen oder seine Quelle wurde zurückgezogen. Frühere Originale und Belege bleiben erhalten.")
        return batch

    def stage(self, connection, run_id, command, actor):
        operation = "teha-stage:" + run_id
        with self.work(actor, write=True) as unit:
            self._connection(unit, connection, active=True)
            run, records = self._result(unit, connection, run_id, revision=command.run_revision)
            previous = s.replay(unit, operation, command)
            if previous:
                return previous
            batch = s.find_one(unit, Batch, run_id=run_id, lock=True)
            if batch is None:
                if command.batch_revision != 0:
                    conflict("Empfang noch nicht vorbereitet.")
                batch = s.put(unit, Batch, dict(id=str(uuid4()), connection_id=connection, run_id=run_id,
                    source_sha256=run.result_sha256, state="receiving", revision=1, next_index=0,
                    total=len(records), created_at=s.now()))
            else:
                self._batch(unit, connection, batch.id, active=True)
                if command.batch_revision == 0:
                    # Opening an already staged run is a safe local read, even
                    # with a new command key. Advancing still needs its revision.
                    response = self.public_batch(batch)
                    s.receipt(unit, operation, command, connection, response)
                    return response
                s.revision(batch, command.batch_revision)
            if batch.source_sha256 != run.result_sha256 or batch.total != len(records):
                conflict("Die Quelle hat sich geändert. Empfang neu prüfen.")
            stop = min(batch.next_index + command.limit, batch.total)
            if unit.db is None:
                seen = {row.identity_sha256 for row in s.memory(unit, Item).values() if row.batch_id == batch.id}
            else:
                seen = set(unit.db.scalars(select(Item.identity_sha256).where(Item.batch_id == batch.id)))
            for position in range(batch.next_index, stop):
                record = records[position]
                token = identity(record)
                if not isinstance(record.get("raw"), dict) or not isinstance(record.get("title"), str):
                    raise HTTPException(422, f"Empfangszeile {position + 1} hat ein unbekanntes Format.")
                if token in seen:
                    conflict(f"Doppelte externe Identität in Empfangszeile {position + 1}. Quelle prüfen.")
                seen.add(token)
                content(record)
                item_id = str(uuid4())
                snapshot = {key: value for key, value in record.items() if key != "content_base64"}
                s.put(unit, Item, dict(id=item_id, batch_id=batch.id, connection_id=connection, position=position,
                    kind=record["kind"], identity_sha256=token, source_sha256=s.digest(snapshot),
                    content_sha256=record.get("content_sha256"), source_token=s.seal(snapshot, f"teha-item/{item_id}", self.box), created_at=s.now()))
            batch = s.put(unit, Batch, {**s.values(batch), "next_index": stop, "state": "ready" if stop == batch.total else "receiving",
                                      "revision": batch.revision + 1})
            response = self.public_batch(batch)
            s.receipt(unit, operation, command, connection, response)
            return response

    @staticmethod
    def public_batch(batch):
        return {key: getattr(batch, key) for key in ("id", "run_id", "revision", "state", "next_index", "total", "source_sha256")}

    def batches(self, connection, actor, **page):
        with self.work(actor) as unit:
            self._connection(unit, connection)
            result = s.page(unit, Batch, actor, connection_id=connection, **page)
            result["items"] = [self.public_batch(self._batch(unit, connection, row.id)) for row in result["items"]]
            return result

    def connections(self, actor, **page):
        with self.work(actor) as unit:
            result = s.page(unit, IntegrationConnectionORM, actor, provider_id="teha", **page)
            result["items"] = [{"id": row.id, "name": row.name, "enabled": row.enabled, "archived": row.archived} for row in result["items"]]
            return result

    def choices(self, connection, kind, actor, *, cursor=None, limit=50, property_id=None):
        registry = {"property": (PropertyORM, "properties", "name"), "billing_period": (BillingPeriodORM, "billing_periods", "label"),
                    "unit": (UnitORM, "units", "label"), "tenant": (TenantORM, "tenants", "full_name"),
                    "contract": (ContractORM, "contracts", "contract_number")}
        if kind not in registry or not 1 <= limit <= 250:
            raise HTTPException(422, "Unbekannte Aktenart oder Seitengröße.")
        with self.work(actor) as unit:
            self._connection(unit, connection)
            model, collection, title = registry[kind]
            namespace = ["teha-targets-v1", actor, connection, kind, property_id]
            anchor = s.commands.cursor_decode(cursor, namespace)
            if anchor is not None and (len(anchor) != 1 or not isinstance(anchor[0], str)):
                raise HTTPException(422, "Ungültige Fortsetzung.")
            if unit.db is None:
                rows = list(getattr(unit.store, collection).values())
                if property_id and kind in {"unit", "billing_period", "contract"}:
                    rows = [r for r in rows if r.property_id == property_id]
                total = len(rows)
                rows = sorted((r for r in rows if not anchor or r.id > anchor[0]), key=lambda r: r.id)[:limit + 1]
            else:
                sql_model: Any = model  # registry selects among concrete typed ORM classes
                query = select(sql_model)
                filters = [sql_model.property_id == property_id] if property_id and kind in {"unit", "billing_period", "contract"} else []
                total = unit.db.scalar(select(func.count()).select_from(sql_model).where(*filters))
                if anchor:
                    filters.append(sql_model.id > anchor[0])
                rows = list(unit.db.scalars(query.where(*filters).order_by(sql_model.id).limit(limit + 1)))
            more, rows = len(rows) > limit, rows[:limit]
            return {"items": [{"kind": kind, "id": row.id, "title": getattr(row, title),
                               "revision": resolve_context(unit.store, kind, row.id, actor)["revision"]} for row in rows],
                    "total": total, "has_more": more,
                    "next_cursor": s.commands.cursor_encode(namespace, [rows[-1].id]) if more else None}

    def items(self, connection, batch_id, actor, **page):
        with self.work(actor) as unit:
            self._batch(unit, connection, batch_id)
            result = s.page(unit, Item, actor, batch_id=batch_id, **page)
            result["items"] = [self._public_item(row) for row in result["items"]]
            return result

    def _public_item(self, item):
        source = s.unseal(item.source_token, f"teha-item/{item.id}", self.box)
        if s.digest(source) != item.source_sha256 or identity(source) != item.identity_sha256:
            raise HTTPException(503, "Empfangszeile und Quellhash stimmen nicht überein.")
        return {"id": item.id, "kind": item.kind, "position": item.position, "source_sha256": item.source_sha256,
                "content_sha256": item.content_sha256, "source": source}

    def _item(self, unit, connection, item_id, *, active=False):
        item = s.row(unit, Item, item_id)
        if item.connection_id != connection:
            raise HTTPException(404, "Empfangszeile nicht gefunden.")
        batch = self._batch(unit, connection, item.batch_id, active=active)
        return batch, item

    def _targets(self, unit, targets):
        contexts = {}
        order = {kind: i for i, kind in enumerate(("tenant", "property", "unit", "contract", "billing_period", "maintenance", "task"))}
        for target in sorted(targets, key=lambda t: order.get(t["kind"], 99)):
            if target["kind"] in contexts:
                raise HTTPException(422, "Eine Zielart darf nur einmal zugeordnet werden.")
            ctx = resolve_context(unit.store, target["kind"], target["id"], unit.actor_id, lock=unit.db is not None)
            s.commands.check_revision(target["revision"], ctx["revision"])
            contexts[target["kind"]] = ctx
        if "property" not in contexts:
            raise HTTPException(422, "Bitte die Immobilie ausdrücklich zuordnen.")
        prop = contexts["property"]["entity_id"]
        for kind, ctx in contexts.items():
            if kind != "property" and (ctx["property_id"] != prop or (kind == "tenant" and prop not in {
                    c.property_id for c in unit.store.list_contracts() if c.tenant_id == ctx["entity_id"]})):
                conflict("Die zugeordneten Akten gehören nicht eindeutig zur selben Immobilie.")
        if "contract" in contexts:
            contract = contexts["contract"]["values"]
            for kind in ("unit", "tenant"):
                if kind in contexts and contexts[kind]["entity_id"] != contract[kind + "_id"]:
                    conflict("Vertrag, Einheit und Partei stimmen nicht überein.")
        return contexts

    def map(self, connection, item_id, command, actor):
        operation = "teha-map:" + item_id
        with self.work(actor, write=True) as unit:
            batch, item = self._item(unit, connection, item_id, active=True)
            if item.source_sha256 != command.source_sha256:
                conflict("Die angezeigte Quelle ist veraltet.")
            previous = s.replay(unit, operation, command)
            if previous:
                return previous
            newest = self._newest_source(unit, connection, item)
            if newest and newest.id != item.id:
                conflict("Eine neuere vollständige Empfangsfassung liegt vor. Bitte diese für die Zuordnung verwenden.")
            mapping = s.find_one(unit, Mapping, connection_id=connection, identity_sha256=item.identity_sha256, lock=True)
            if (mapping.revision if mapping else 0) != command.mapping_revision:
                conflict("Die Zuordnung wurde inzwischen geändert.")
            targets = sorted((value.model_dump() for value in command.targets), key=lambda value: value["kind"])
            contexts = self._targets(unit, targets)
            required = {"period": "billing_period", "unit": "unit", "user": "tenant"}.get(item.kind)
            if required and required not in contexts:
                raise HTTPException(422, "Bitte auch die zugehörige Periode, Einheit beziehungsweise Partei zuordnen.")
            if item.kind == "document" and "tenant" in contexts and "contract" not in contexts:
                raise HTTPException(422, "Ein personenbezogenes Original benötigt die ausdrückliche Vertragszuordnung, damit seine Originalbindung erhalten bleibt.")
            identifier = mapping.id if mapping else str(uuid4())
            mapping = s.put(unit, Mapping, dict(id=identifier, connection_id=connection, identity_sha256=item.identity_sha256,
                revision=(mapping.revision if mapping else 0) + 1,
                target_token=s.seal(targets, f"teha-mapping/{identifier}", self.box), created_at=mapping.created_at if mapping else s.now()))
            response = {"id": identifier, "revision": mapping.revision, "targets": targets}
            s.receipt(unit, operation, command, connection, response)
            return response

    def _latest(self, unit, connection, item):
        if unit.db is None:
            return max((r for r in s.memory(unit, Receipt).values() if r.connection_id == connection and r.identity_sha256 == item.identity_sha256),
                       key=lambda r: (r.created_at, r.id), default=None)
        return unit.db.scalar(select(Receipt).filter_by(connection_id=connection, identity_sha256=item.identity_sha256)
                              .order_by(Receipt.created_at.desc(), Receipt.id.desc()).limit(1))

    def _newest_source(self, unit, connection, item):
        if unit.db is None:
            batches = s.memory(unit, Batch)
            return max((r for r in s.memory(unit, Item).values() if r.connection_id == connection and
                        r.identity_sha256 == item.identity_sha256 and batches[r.batch_id].state == 'ready'),
                       key=lambda r: (r.created_at, r.id), default=None)
        return unit.db.scalar(select(Item).join(Batch, Item.batch_id == Batch.id).where(Item.connection_id == connection,
            Item.identity_sha256 == item.identity_sha256, Batch.state == 'ready').order_by(Item.created_at.desc(), Item.id.desc()).limit(1))

    def _reusable_document(self, unit, connection, item, targets):
        if unit.db is None:
            rows = [r for r in s.memory(unit, Receipt).values() if r.connection_id == connection and
                    r.identity_sha256 == item.identity_sha256 and r.source_sha256 == item.source_sha256]
        else:
            rows = unit.db.scalars(select(Receipt).filter_by(connection_id=connection, identity_sha256=item.identity_sha256,
                                                          source_sha256=item.source_sha256))
        expected = {(t['kind'], t['id']) for t in targets}
        for receipt in rows:
            if receipt.document_id and receipt.content_sha256 == item.content_sha256:
                proof = s.unseal(receipt.evidence_token, f'teha-receipt/{receipt.id}', self.box)
                if {(t['kind'], t['id']) for t in proof['targets']} == expected:
                    return receipt
        return None

    def _preview(self, unit, connection, item_id, *, active=False):
        batch, item = self._item(unit, connection, item_id, active=active)
        source = self._public_item(item)["source"]
        mapping = s.find_one(unit, Mapping, connection_id=connection, identity_sha256=item.identity_sha256, lock=active)
        targets = s.unseal(mapping.target_token, f"teha-mapping/{mapping.id}", self.box) if mapping else []
        prior = self._latest(unit, connection, item)
        state, errors, contexts = "new", [], {}
        try:
            newest = self._newest_source(unit, connection, item)
            if newest and newest.id != item.id:
                conflict("Eine neuere vollständige Empfangsfassung liegt vor. Bitte deren Vorschau öffnen.")
            if not mapping:
                conflict("Zuordnung fehlt.")
            contexts = self._targets(unit, targets)
            if batch.state != "ready":
                conflict("Empfang ist nicht vollständig oder wurde zurückgezogen.")
            if item.kind == "document" and not item.content_sha256:
                conflict("Nur das Verzeichnis wurde empfangen. Bitte das tatsächliche Dokumentoriginal empfangen.")
            if prior:
                evidence = s.unseal(prior.evidence_token, f"teha-receipt/{prior.id}", self.box)
                old_targets = {(t["kind"], t["id"]) for t in evidence["targets"]}
                if old_targets != {(t["kind"], t["id"]) for t in targets}:
                    conflict("Bereits übernommene externe Identität darf nicht still einer anderen Akte zugeordnet werden.")
                state = "unchanged" if prior.source_sha256 == item.source_sha256 and prior.content_sha256 == item.content_sha256 else "changed"
                if state == "changed" and prior.task_id:
                    for target in evidence.get("published_targets", []):
                        ctx = resolve_context(unit.store, target["kind"], target["id"], unit.actor_id, lock=active)
                        s.commands.check_revision(target["revision"], ctx["revision"])
        except HTTPException as error:
            if error.status_code != 409:
                raise
            state, errors = "conflict", [str(error.detail)]
        snapshot = {"item_id": item.id, "source_sha256": item.source_sha256, "content_sha256": item.content_sha256,
            "batch_revision": batch.revision, "mapping_revision": mapping.revision if mapping else 0,
            "targets": targets, "prior_id": prior.id if prior else None, "state": state}
        return {**snapshot, "preview_sha256": s.digest(snapshot), "errors": errors, "source": source,
                "publication": self._public_receipt(prior) if prior else None,
                "outbound_enabled": False, "evidence_gap": EVIDENCE_GAP}, (batch, item, prior, contexts)

    def preview(self, connection, item_id, actor):
        with self.work(actor) as unit:
            self._connection(unit, connection)
            return self._preview(unit, connection, item_id)[0]

    def _put_business(self, unit, model, collection, value):
        if unit.db is None:
            unit.insert(getattr(unit.store, collection), value.id, value)
        else:
            values = value.model_dump()
            obj = unit.db.get(model, value.id)
            if obj is None:
                unit.db.add(model(**values))
            else:
                for name, data in values.items():
                    setattr(obj, name, data)
            unit.db.flush()

    def publish(self, connection, item_id, command, actor):
        operation = "teha-publish:" + item_id
        with self.work(actor, write=True, publish=True) as unit:
            # Lock connection first: serializes independent batches for one identity on PostgreSQL.
            self._connection(unit, connection, active=True)
            self._item(unit, connection, item_id, active=True)
            previous = s.replay(unit, operation, command)
            if previous:
                self._authorize_receipt(unit, previous["id"])
                return previous
            preview, (batch, item, prior, contexts) = self._preview(unit, connection, item_id, active=True)
            if preview["preview_sha256"] != command.preview_sha256:
                conflict("Die Vorschau wurde geändert. Bitte die aktuelle Vorschau erneut prüfen und bestätigen.")
            if preview["state"] == "conflict":
                conflict(preview["errors"][0])
            if preview["state"] == "unchanged":
                response = self._authorize_receipt(unit, prior.id)
                s.receipt(unit, operation, command, connection, response)
                return response
            identifier, doc_id, version_id = str(uuid4()), None, None
            task_id, project_id = prior.task_id if prior else None, prior.project_id if prior else None
            source = preview["source"]
            prop = contexts["property"]["entity_id"]
            unit_id = contexts.get("unit", {}).get("entity_id")
            tenant_id = contexts.get("tenant", {}).get("entity_id")
            if item.kind == "document":
                run, records = self._result(unit, connection, batch.run_id)
                if run.result_sha256 != batch.source_sha256:
                    conflict("Der empfangene Quellstand wurde geändert.")
                record = records[item.position]
                if identity(record) != item.identity_sha256 or s.digest({k: v for k, v in record.items() if k != "content_base64"}) != item.source_sha256:
                    conflict("Original und Empfangszeile passen nicht zusammen.")
                original = content(record)
                if original is None:
                    conflict("Tatsächliche Originalbytes fehlen.")
                from ..config import settings
                if len(original) > settings.max_upload_size_bytes:
                    raise HTTPException(413, "Das empfangene Original überschreitet die Dokumentgrenze.")
                reusable = self._reusable_document(unit, connection, item, preview['targets'])
                if reusable:
                    self._authorize_receipt(unit, reusable.id)
                    doc_id, version_id = reusable.document_id, reusable.version_id
                    _, binding = archive.bind_document(unit, doc_id, lock=True)
                    archived = archive.authorized_version(unit, doc_id, version_id, binding)
                    if archive.original_bytes(unit, archived) != original:
                        raise HTTPException(503, "Das vorhandene Original stimmt nicht bytegleich mit dem Empfang überein.")
                else:
                    doc_id, version_id = str(uuid4()), str(uuid4())
                    document = Document(id=doc_id, property_id=prop, unit_id=unit_id, tenant_id=tenant_id,
                        contract_id=contexts.get("contract", {}).get("entity_id"),
                        title=source["title"], document_type="teha_original", description="TEHA-Empfang; unverändertes Anbieteroriginal",
                        file_url=f"/uploads/teha/{connection}/{identifier}.pdf")
                    self._put_business(unit, DocumentORM, "documents", document)
                    _, binding = archive.bind_document(unit, doc_id, lock=True)
                    row = DocumentVersionORM(id=version_id, document_id=doc_id, **binding, number=1,
                        predecessor_id=None, restored_from_id=None, actor_id=actor, idempotency_key="teha-" + identifier,
                        request_sha256=command.preview_sha256, operation="archive_original", comment="Unverändertes TEHA-Anbieteroriginal",
                        filename=archive.filename(source["title"]), media_type="application/pdf", sha256=item.content_sha256,
                        size_bytes=len(original), metadata_snapshot={**document.model_dump(mode="json"), "teha_receipt_id": identifier,
                            "teha_source_sha256": item.source_sha256, "teha_predecessor_receipt_id": prior.id if prior else None}, created_at=s.now())
                    archive.validate_manifest(row)
                    archive.persist_version_bytes(unit, row, (original[i:i + CHUNK_BYTES] for i in range(0, len(original), CHUNK_BYTES)))
            elif item.kind == "technical_order":
                raw = source["raw"]
                try:
                    start = parse_naive_iso_datetime(raw["terminVon"])
                    end = parse_naive_iso_datetime(raw["terminBis"])
                    if end < start or type(raw["auftragNummer"]) is not int:
                        raise ValueError
                except (KeyError, ValueError, TehaError):
                    # Provider date strings must never be replaced with server-local time.
                    raise HTTPException(422, "Terminzeit oder Auftragsnummer haben ein unbekanntes Format. Quelle prüfen.") from None
                task_id = task_id or contexts.get("task", {}).get("entity_id") or str(uuid4())
                project_id = project_id or contexts.get("maintenance", {}).get("entity_id") or str(uuid4())
                if prior is None and ("task" in contexts or "maintenance" in contexts):
                    conflict("Ein vorhandener Vorgang wird nicht überschrieben. Für diesen Empfang bitte nur die Immobilie und optional Einheit zuordnen.")
                description = f"TEHA-Auftragsnummer: {raw['auftragNummer']}; Termin-ID: {source['identity']['termin_id']}.\n{raw['terminVon']} bis {raw['terminBis']}\nProjekt: /maintenance/{project_id}"
                old_task = unit.store.get_task(task_id) if prior else None
                old_project = unit.store.get_maintenance_case(project_id) if prior else None
                from ..domain.revision_time import next_updated_at
                task = Task(**{**(old_task.model_dump() if old_task else {}), "id": task_id, "property_id": prop,
                    "unit_id": unit_id, "title": source["title"], "description": description, "due_date": start.date(),
                    "updated_at": next_updated_at(old_task.updated_at, s.now()) if old_task else s.now()})
                project = MaintenanceCase(**{**(old_project.model_dump() if old_project else {}), "id": project_id, "property_id": prop,
                    "unit_id": unit_id, "title": source["title"], "description": description + f"\nAufgabe: /tasks?focus_id={task_id}",
                    "appointment_at": start, "updated_at": next_updated_at(old_project.updated_at, s.now()) if old_project else s.now()})
                self._put_business(unit, TaskORM, "tasks", task)
                self._put_business(unit, MaintenanceCaseORM, "maintenance_cases", project)
            # Inventory/user/unit publication confirms an explicit mapping only; no inferred tenant/contract mutation.
            published_targets = []
            for kind, key in (("task", task_id), ("maintenance", project_id)):
                if key:
                    ctx = resolve_context(unit.store, kind, key, actor)
                    published_targets.append({"kind": kind, "id": key, "revision": ctx["revision"]})
            evidence = {"contract": TEHA_PORTAL_CONTRACT_VERSION, "targets": preview["targets"], "published_targets": published_targets,
                        "preview_sha256": command.preview_sha256, "mapping_revision": preview["mapping_revision"]}
            receipt = s.put(unit, Receipt, dict(id=identifier, connection_id=connection, item_id=item.id,
                identity_sha256=item.identity_sha256, source_sha256=item.source_sha256, content_sha256=item.content_sha256,
                mapping_sha256=s.digest(preview["targets"]), predecessor_id=prior.id if prior else None,
                document_id=doc_id, version_id=version_id, task_id=task_id, project_id=project_id, actor_id=actor,
                evidence_token=s.seal(evidence, f"teha-receipt/{identifier}", self.box), created_at=s.now()))
            response = self._public_receipt(receipt)
            s.receipt(unit, operation, command, connection, response)
            return response

    @staticmethod
    def _public_receipt(receipt):
        return {key: getattr(receipt, key) for key in ("id", "item_id", "source_sha256", "content_sha256", "mapping_sha256",
                    "predecessor_id", "document_id", "version_id", "task_id", "project_id")}

    def _authorize_receipt(self, unit, receipt_id):
        receipt = s.row(unit, Receipt, receipt_id)
        item = s.row(unit, Item, receipt.item_id)
        self._batch(unit, receipt.connection_id, item.batch_id)
        evidence = s.unseal(receipt.evidence_token, f"teha-receipt/{receipt.id}", self.box)
        for target in evidence["targets"]:
            resolve_context(unit.store, target["kind"], target["id"], unit.actor_id)
        for kind, key in (("document", receipt.document_id), ("task", receipt.task_id), ("maintenance", receipt.project_id)):
            if key:
                resolve_context(unit.store, kind, key, unit.actor_id)
        return self._public_receipt(receipt)

    def history(self, connection, actor, **page):
        with self.work(actor) as unit:
            self._connection(unit, connection)
            result = s.page(unit, Receipt, actor, connection_id=connection, **page)
            result["items"] = [self._authorize_receipt(unit, row.id) for row in result["items"]]
            return result

    def original(self, connection, receipt_id, actor):
        with self.work(actor) as unit:
            self._connection(unit, connection)
            receipt = s.row(unit, Receipt, receipt_id)
            if receipt.connection_id != connection:
                raise HTTPException(404, "Original nicht gefunden.")
            self._authorize_receipt(unit, receipt_id)
            if not receipt.document_id:
                raise HTTPException(404, "Dieser Beleg enthält kein Dokumentoriginal.")
            _, binding = archive.bind_document(unit, receipt.document_id)
            row = archive.authorized_version(unit, receipt.document_id, receipt.version_id, binding)
            original = archive.original_bytes(unit, row)
            if row.sha256 != receipt.content_sha256:
                raise HTTPException(503, "Original und Importbeleg stimmen nicht überein.")
            return original, row.filename

    def decide_batch(self, connection, batch_id, command, actor):
        operation = "teha-batch:" + batch_id
        with self.work(actor, write=True) as unit:
            self._connection(unit, connection, active=True)
            batch = self._batch(unit, connection, batch_id)
            previous = s.replay(unit, operation, command)
            if previous:
                return previous
            s.revision(batch, command.base_revision)
            batch = s.put(unit, Batch, {**s.values(batch), "state": command.state, "revision": batch.revision + 1})
            s.record_event(unit, connection, "teha_source_" + command.state, {"batch_id": batch.id, "reason": command.reason}, box=self.box)
            response = self.public_batch(batch)
            s.receipt(unit, operation, command, connection, response)
            return response

    def prepare_return(self, connection, item_id, command, actor):
        """Freeze a local review packet. It contains NO invented portal body/endpoint.

        Existing cost items, contracts and project are sources, never a new
        ledger. There is deliberately no dispatch method for these drafts.
        """
        operation = "teha-return:" + item_id
        with self.work(actor, write=True) as unit:
            self._connection(unit, connection, active=True)
            # An identical acknowledged command remains readable after source
            # edits/deletion. Do not revalidate a new source before replay.
            prior = s.replay(unit, operation, command)
            if prior:
                return prior
            batch, item = self._item(unit, connection, item_id, active=True)
            newest = self._newest_source(unit, connection, item)
            if batch.state != "ready" or (newest and newest.id != item.id):
                conflict("Nur die neueste vollständig aufbereitete Empfangsfassung kann für eine Rückübertragung vorbereitet werden.")
            mapping = s.find_one(unit, Mapping, connection_id=connection, identity_sha256=item.identity_sha256, lock=True)
            if not mapping:
                conflict("Vorbereitung benötigt eine bestätigte externe Zuordnung.")
            s.revision(mapping, command.mapping_revision)
            source = resolve_context(unit.store, command.source.kind, command.source.id, actor, lock=True)
            s.commands.check_revision(command.source.revision, source["revision"])
            targets = s.unseal(mapping.target_token, f"teha-mapping/{mapping.id}", self.box)
            contexts = self._targets(unit, targets)
            expected_kind = "billing_period" if command.kind == "cost_user_data" else "maintenance"
            if command.source.kind != expected_kind or source["property_id"] != contexts["property"]["entity_id"]:
                conflict("Die Vorbereitung gehört nicht zur zugeordneten Immobilie oder Quellart.")
            if command.kind == "cost_user_data" and contexts.get("billing_period", {}).get("entity_id") != source["entity_id"]:
                conflict("Die Abrechnungsperiode muss ausdrücklich dieser externen Periode zugeordnet sein.")
            if command.kind == "cost_user_data" and item.kind != "period":
                conflict("Kosten-/Nutzerdaten benötigen eine ausdrücklich zugeordnete externe Periode.")
            if command.follow_up is not None and command.kind != "maintenance_order":
                raise HTTPException(422, "Eine Folgeauftrag-Vorschau gehört ausschließlich zu einem Techniktermin.")
            if command.kind == "maintenance_order":
                published = self._latest(unit, connection, item)
                if item.kind != "technical_order" or not published or published.project_id != source["entity_id"]:
                    conflict("Wartungsvorbereitung benötigt den tatsächlich mit diesem TEHA-Termin verknüpften Projektvorgang.")
            snapshot = {"format": "immomanager-teha-local-preparation/2", "kind": command.kind,
                "source": s.commands.dump(source), "external_source": self._public_item(item)["source"],
                "targets": targets, "mapping_revision": mapping.revision, "external_write_enabled": False,
                "evidence_gap": EVIDENCE_GAP, "portal_contract": None}
            snapshot["currency"] = unit.store.get_portfolio(contexts["property"]["values"]["portfolio_id"]).currency
            if command.kind == "cost_user_data":
                snapshot.update(self._return_cost_data(unit, source, lock=True))
            if command.follow_up is not None:
                from .teha_follow_up import follow_up_preview
                if len({entry.item_id for entry in command.follow_up.users}) != len(command.follow_up.users):
                    raise HTTPException(422, "Jeden empfangenen Nutzer nur einmal auswählen.")
                sources = []
                for entry in command.follow_up.users:
                    sources.append(self._follow_up_source(unit, connection, item, entry.item_id, entry.source_sha256, active=True))
                snapshot["follow_up_sources"] = [{"item_id": entry.item_id, "source_sha256": entry.source_sha256, "source": value}
                                                 for entry, value in zip(command.follow_up.users, sources)]
                snapshot["portal_preview"] = follow_up_preview(snapshot["external_source"], command.follow_up, sources)
            identifier = str(uuid4())
            digest = s.digest(snapshot)
            s.put(unit, ReturnDraft, dict(id=identifier, connection_id=connection, item_id=item_id, actor_id=actor,
                kind=command.kind, snapshot_sha256=digest, snapshot_token=s.seal(snapshot, f"teha-return/{identifier}", self.box), created_at=s.now()))
            response = {"id": identifier, "snapshot_sha256": digest, "external_write_enabled": False, "evidence_gap": EVIDENCE_GAP}
            s.receipt(unit, operation, command, connection, response)
            return response

    def _follow_up_source(self, unit, connection, order, user_id, source_sha256, *, active=False):
        batch, item = self._item(unit, connection, user_id, active=active)
        source = self._public_item(item)["source"]
        order_source = self._public_item(order)["source"]
        newest = self._newest_source(unit, connection, item)
        if (batch.state != "ready" or item.kind != "user" or item.source_sha256 != source_sha256
                or source["identity"].get("termin_id") != order_source["identity"].get("termin_id")
                or (newest and newest.id != item.id)):
            conflict("Ausgewählter Nutzer gehört nicht zur aktuellen bestätigten Empfangsfassung dieses Techniktermins.")
        return source

    def follow_up_users(self, connection, item_id, actor, *, cursor=None, limit=50):
        with self.work(actor) as unit:
            _, order = self._item(unit, connection, item_id)
            if order.kind != "technical_order":
                raise HTTPException(422, "Nutzer für Folgeaufträge benötigen einen Techniktermin.")
            # Paginate the complete received user inventory; do not silently
            # truncate users to the first 50. Only matching latest rows display.
            result = s.page(unit, Item, actor, connection_id=connection, kind="user", cursor=cursor, limit=limit)
            output = []
            for item in result["items"]:
                source = self._public_item(item)["source"]
                if source["identity"].get("termin_id") != self._public_item(order)["source"]["identity"].get("termin_id"):
                    continue
                try:
                    self._follow_up_source(unit, connection, order, item.id, item.source_sha256)
                except HTTPException as error:
                    if error.status_code in {404, 409}:
                        continue
                    raise
                raw = source["raw"]
                output.append({"id": item.id, "source_sha256": item.source_sha256, "external_user_id": source["identity"]["user_id"],
                               "name": raw.get("bewohnerName") or source["title"], "sequence_number": raw.get("lfdNr"),
                               "selectable": raw.get("deleted") is not True and raw.get("erledigt") is not True})
            result["items"] = output
            result["count_scope"] = "received_user_inventory"
            return result

    def _return_cost_data(self, unit, source, *, lock=False, include_users=True):
        """One canonical collector for creation AND content drift checks."""
        from decimal import Decimal, InvalidOperation

        from ..db.orm_models import CostItemORM
        from ..domain.money import money
        if unit.db is None:
            costs = [c.model_dump(mode="json") for c in unit.store.cost_items.values() if c.billing_period_id == source["entity_id"]]
            contracts = [c.model_dump(mode="json") for c in unit.store.contracts.values() if c.property_id == source["property_id"]]
        else:
            def rows(model, criterion):
                query = select(model.__table__).where(criterion)
                return [dict(row) for row in unit.db.execute(query.with_for_update() if lock else query).mappings()]
            costs = rows(CostItemORM, CostItemORM.billing_period_id == source["entity_id"])
            contracts = rows(ContractORM, ContractORM.property_id == source["property_id"])
        costs.sort(key=lambda c: c["id"])
        try:
            for cost in costs:
                amount = Decimal(str(cost["amount"]))
                if not amount.is_finite():
                    raise ValueError
                cost["amount_decimal"] = format(money(amount), '.2f')
        except (InvalidOperation, ValueError, TypeError):
            raise HTTPException(422, "Ein lokaler Kostenbetrag kann nicht als endlicher Centbetrag vorbereitet werden.") from None
        period = source["values"]
        contracts = sorted((c for c in contracts if str(c["start_date"]) <= str(period["end_date"]) and
                            (not c.get("end_date") or str(c["end_date"]) >= str(period["start_date"]))), key=lambda c: c["id"])
        data = {"cost_items": s.commands.dump(costs), "contracts": s.commands.dump(contracts)}
        if include_users:
            users = []
            for contract in contracts:
                tenant = resolve_context(unit.store, "tenant", contract["tenant_id"], unit.actor_id, lock=lock)
                dwelling = resolve_context(unit.store, "unit", contract["unit_id"], unit.actor_id, lock=lock)
                # Local identities remain explicitly local. Keep unrelated bank
                # and contact fields out of this review export.
                users.append({"contract_id": contract["id"],
                              "tenant": {"id": tenant["entity_id"], "name": tenant["title"], "revision": tenant["revision"]},
                              "unit": {"id": dwelling["entity_id"], "label": dwelling["title"], "revision": dwelling["revision"]}})
            data["users"] = users
        return data

    def evidence(self, connection, actor):
        from .providers.teha_evidence import portal_evidence
        with self.work(actor) as unit:
            self._connection(unit, connection)
            return portal_evidence()

    def _return_view(self, unit, connection, row):
        from .teha_return_validation import validate_local_return
        # Enforce the existing run's private visibility before opening any
        # frozen resident data. A missing business source is recoverable below.
        access_item = s.row(unit, Item, row.item_id)
        access_batch = s.row(unit, Batch, access_item.batch_id)
        self.runs._access(unit, s.row(unit, IntegrationActionRunORM, access_batch.run_id))
        snapshot = s.unseal(row.snapshot_token, f"teha-return/{row.id}", self.box)
        if (s.digest(snapshot) != row.snapshot_sha256 or snapshot.get("kind") != row.kind
                or snapshot.get("external_write_enabled") is not False or snapshot.get("portal_contract") is not None):
            raise HTTPException(503, "Vorbereitung und Quellhash stimmen nicht überein.")
        source, issues = snapshot["source"], []
        def issue(code, message):
            issues.append({"code": code, "message": message})
        try:
            batch, item = self._item(unit, connection, row.item_id)
            if batch.state != "ready":
                issue("receive_inactive", "Die Empfangsquelle wurde abgebrochen oder zurückgezogen.")
            newest = self._newest_source(unit, connection, item)
            if newest and newest.id != item.id:
                issue("receive_superseded", "Eine neuere vollständige TEHA-Empfangsfassung liegt vor. Neu vorbereiten.")
            mapping = s.find_one(unit, Mapping, connection_id=connection, identity_sha256=item.identity_sha256)
            if (not mapping or mapping.revision != snapshot["mapping_revision"] or
                    s.unseal(mapping.target_token, f"teha-mapping/{mapping.id}", self.box) != snapshot["targets"]):
                issue("mapping_changed", "Die externe Zuordnung wurde inzwischen geändert. Neu vorbereiten.")
            # Check every explicitly mapped context, including property/unit,
            # instead of checking only the billing period's timestamp.
            self._targets(unit, snapshot["targets"])
            for entry in snapshot.get("follow_up_sources", []):
                self._follow_up_source(unit, connection, item, entry["item_id"], entry["source_sha256"])
        except HTTPException as error:
            if error.status_code not in {404, 409}:
                raise
            issue("mapping_source_unavailable", "Empfang oder zugeordnete Akte ist verändert oder nicht mehr vorhanden. Neu prüfen.")
        try:
            current = resolve_context(unit.store, source["kind"], source["entity_id"], unit.actor_id)
            if s.commands.dump(current) != source:
                issue("source_changed", "Die lokale Quellakte wurde inzwischen geändert. Neu vorbereiten.")
            if row.kind == "cost_user_data":
                data = self._return_cost_data(unit, current, include_users="users" in snapshot)
                if any(data[key] != snapshot.get(key) for key in data):
                    issue("related_data_changed", "Kosten, Verträge, Parteien oder Einheiten wurden inzwischen geändert. Neu vorbereiten.")
            prop = resolve_context(unit.store, "property", source["property_id"], unit.actor_id)
            if unit.store.get_portfolio(prop["values"]["portfolio_id"]).currency != snapshot.get("currency"):
                issue("currency_changed", "Die Portfoliowährung wurde inzwischen geändert. Neu vorbereiten.")
        except HTTPException as error:
            if error.status_code not in {404, 409, 422}:
                raise
            issue("local_source_unavailable", "Eine lokale Quelle fehlt oder ist nicht mehr prüfbar. Das eingefrorene Paket bleibt erhalten.")
        validation = validate_local_return(snapshot, issues=issues)
        return {"id": row.id, "item_id": row.item_id, "snapshot_sha256": row.snapshot_sha256, "snapshot": snapshot,
                "source_changed": bool(issues), "validation": validation, "external_write_enabled": False}

    def return_export(self, connection, draft_id, expected_sha256, actor):
        from .providers.teha_evidence import portal_evidence
        with self.work(actor) as unit:
            self._connection(unit, connection)
            row = s.row(unit, ReturnDraft, draft_id)
            if row.connection_id != connection:
                raise HTTPException(404, "Vorbereitung nicht gefunden.")
            # Private visibility precedes even a hash-mismatch response so a
            # foreign actor cannot probe whether another packet/hash exists.
            value = self._return_view(unit, connection, row)
            if row.snapshot_sha256 != expected_sha256:
                conflict("Der angezeigte Pakethash stimmt nicht mit der gespeicherten Vorbereitung überein. Neu laden.")
            envelope = {"format": "immomanager-teha-review-export/1", **value, "portal_evidence": portal_evidence(),
                        "message": "Lokales Prüfpaket; nicht versandt. Keine Portalbestätigung und kein freigegebenes TEHA-Importformat."}
            return s.canonical(envelope, enforce_budget=False), f"TEHA-Pruefpaket-{row.id}.json"

    def returns(self, connection, actor, **page):
        with self.work(actor) as unit:
            self._connection(unit, connection)
            visibility = {} if unit.user["role"] == "eigentuemer" else {"actor_id": actor}
            result = s.page(unit, ReturnDraft, actor, connection_id=connection, **visibility, **page)
            result["items"] = [self._return_view(unit, connection, row) for row in result["items"]]
            return result
