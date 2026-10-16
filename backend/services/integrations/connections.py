"""Private, revision-checked connections and explicit external-source mappings.

No method in this module sends a message, buys postage or changes an external
account. Configuration fields not in a provider's contract remain encrypted
observations; they are never forwarded as newly permitted provider parameters.
"""

from __future__ import annotations

from copy import deepcopy
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException
from sqlalchemy import or_, select

from ...db.integration_connection_models import (
    IntegrationActionRunORM,
    IntegrationConnectionEventORM,
    IntegrationConnectionMappingORM,
    IntegrationConnectionORM,
    IntegrationConnectionSecretORM,
)
from ..secret_box import SecretBox
from ..workspace_contexts import resolve_context
from . import connection_storage as storage
from .connection_types import ConnectionCreate, ConnectionUpdate, LegacyAdoption, MappingDecision, SourceObservation
from .validation import config_fields, field_errors

# Effects are an allowlist maintained with the actual adapter, never inferred
# from a discovered endpoint or from a friendly action title.
BUILTIN_EFFECTS = {
    ("email", "check_connection"): "read",
    ("email", "send"): "external_write",
    ("contract-wizard", "preview"): "local",
}
ALLOWED_EFFECTS = frozenset({"local", "read", "external_write"})


class Connections:
    def __init__(self, store, manager, box: SecretBox | None = None):
        self.store, self.manager, self.box = store, manager, box

    def provider(self, provider_id: str):
        provider = self.manager._providers.get(provider_id)
        if provider is None:
            raise HTTPException(404, "Schnittstelle nicht gefunden.")
        return provider

    def catalog(self, actor_id: str) -> list[dict]:
        with storage.work(self.store, actor_id):
            return [self.provider_contract(identifier) for identifier in sorted(self.manager._providers)]

    def provider_contract(self, provider_id: str) -> dict:
        provider = self.provider(provider_id)
        manifest = provider.manifest
        actions = []
        for source in manifest.actions:
            action = deepcopy(source)
            effect = action.get("effect") or BUILTIN_EFFECTS.get((provider_id, action["id"]))
            action.update(effect=effect or "unclassified", enabled=not manifest.planned and isinstance(effect, str) and effect in ALLOWED_EFFECTS,
                          acceptance="not_live_verified", paginated=bool(action.get("cursor_field")))
            if not action["enabled"]:
                action["unavailable_reason"] = "Der Ausführungsvertrag dieser Aktion ist noch nicht freigegeben."
            actions.append(action)
        return {"provider_id": provider_id, "name": manifest.name, "description": manifest.description,
                "planned": manifest.planned, "config_fields": config_fields(manifest), "actions": actions}

    def action(self, provider_id: str, action_id: str) -> dict:
        selected = next((entry for entry in self.provider_contract(provider_id)["actions"] if entry["id"] == action_id), None)
        if selected is None or not selected["enabled"]:
            raise HTTPException(409, "Diese Aktion besitzt noch keinen freigegebenen Ausführungsvertrag.")
        return selected

    def effective_config(self, unit, connection, *, snapshot: dict | None = None) -> dict:
        config = storage.unseal(connection.config_token, f"connection/{connection.id}/config", self.box) if snapshot is None else deepcopy(snapshot["config"])
        references = storage.secret_references(connection) if snapshot is None else snapshot["secret_refs"]
        if not isinstance(config, dict) or not isinstance(references, dict):
            raise HTTPException(503, "Der geschützte Verbindungsstand ist beschädigt.")
        for field, identifier in references.items():
            item = storage.row(unit, IntegrationConnectionSecretORM, identifier)
            if item.connection_id != connection.id or item.field_name != field:
                raise HTTPException(503, "Eine Geheimnisreferenz passt nicht zur Verbindung.")
            config[field] = storage.unseal(item.value_token, f"connection-secret/{item.id}", self.box)
        return config

    def snapshot(self, connection) -> dict:
        return {"config": storage.unseal(connection.config_token, f"connection/{connection.id}/config", self.box),
                "secret_refs": storage.secret_references(connection), "revision": connection.revision,
                "provider_id": connection.provider_id}

    def validation(self, provider_id: str, config: dict, *, complete: bool) -> dict:
        provider = self.provider(provider_id)
        fields = config_fields(provider.manifest)
        known = {field["key"] for field in fields}
        applicable = {key: value for key, value in config.items() if key in known}
        errors = field_errors(applicable, fields, required=complete)
        if provider_id == "email":
            if applicable.get("smtp_use_ssl") and applicable.get("smtp_use_tls", True):
                errors["smtp_use_ssl"] = "STARTTLS und direktes TLS können nicht gleichzeitig aktiv sein."
            if complete and applicable.get("smtp_user") and not applicable.get("smtp_password"):
                errors["smtp_password"] = "Für den SMTP-Benutzer fehlt das Passwort."
        if hasattr(provider, "config_errors"):
            try:
                errors.update(provider.config_errors(applicable))
            except Exception:
                raise HTTPException(422, "Die Verbindungseinstellungen konnten nicht geprüft werden.") from None
        if complete:
            for key in provider.manifest.required_config_keys:
                if not applicable.get(key):
                    errors.setdefault(key, "Pflichtangabe fehlt.")
        return {"valid": not errors, "errors": errors, "applicable": applicable,
                "unmapped_fields": sorted(set(config) - known)}

    def _checked(self, provider_id: str, config: dict, *, enabled: bool) -> dict:
        validation = self.validation(provider_id, config, complete=enabled)
        if not validation["valid"]:
            # Provider validators describe fields, not submitted secret values.
            raise HTTPException(422, {"code": "invalid_connection", "message": "Bitte die markierten Verbindungsangaben prüfen.",
                                      "errors": validation["errors"]})
        return validation

    def _config_data(self, unit, connection_id: str, provider_id: str, revision: int,
                     config: dict, previous_refs: dict[str, str] | None = None) -> tuple[str, dict]:
        provider = self.provider(provider_id)
        secrets = set(provider.manifest.secret_config_keys) | {field["key"] for field in config_fields(provider.manifest) if field.get("secret")}
        references = dict(previous_refs or {})
        safe = {key: deepcopy(value) for key, value in config.items() if key not in secrets}
        for field in secrets:
            value = config.get(field)
            if value in (None, "", "***"):
                references.pop(field, None)
                continue
            if not isinstance(value, str):
                raise HTTPException(422, "Geheimnisfelder müssen Text enthalten.")
            old = storage.row(unit, IntegrationConnectionSecretORM, references[field], required=False) if field in references else None
            if old is not None and storage.unseal(old.value_token, f"connection-secret/{old.id}", self.box) == value:
                continue
            identifier = str(uuid4())
            storage.put(unit, IntegrationConnectionSecretORM, {
                "id": identifier, "connection_id": connection_id, "field_name": field, "revision": revision,
                "value_token": storage.seal(value, f"connection-secret/{identifier}", self.box),
                "created_at": storage.now(), "updated_at": storage.now(),
            })
            references[field] = identifier
        return storage.seal(safe, f"connection/{connection_id}/config", self.box), references

    def public(self, unit, connection) -> dict:
        raw = self.effective_config(unit, connection)
        provider = self.provider(connection.provider_id)
        checked = self.validation(connection.provider_id, raw, complete=True)
        secret_fields = set(provider.manifest.secret_config_keys) | {field["key"] for field in config_fields(provider.manifest) if field.get("secret")}
        known = {field["key"] for field in config_fields(provider.manifest)}
        display = {key: ("***" if key in secret_fields and value else value) for key, value in raw.items() if key in known}
        return {"id": connection.id, "provider_id": connection.provider_id, "provider_name": provider.manifest.name,
                "name": connection.name, "revision": connection.revision, "enabled": connection.enabled,
                "archived": connection.archived, "is_default": connection.is_default, "config": display,
                "configured": checked["valid"], "validation": {"valid": checked["valid"], "errors": checked["errors"]},
                "unmapped_fields": checked["unmapped_fields"], "secret_fields_present": sorted(connection.secret_refs),
                "source": "database", "created_at": storage.stamp(connection.created_at),
                "updated_at": storage.stamp(connection.updated_at), "planned": provider.manifest.planned}

    def _unreadable(self, connection) -> dict:
        # Keep the failed row visible, but never label an unreadable configuration
        # as empty, configured, or safely executable. No decryption is attempted.
        provider = self.provider(connection.provider_id)
        return {"id": connection.id, "provider_id": connection.provider_id,
                "provider_name": provider.manifest.name, "name": connection.name,
                "revision": connection.revision, "enabled": connection.enabled,
                "archived": connection.archived, "is_default": connection.is_default,
                "config": {}, "configured": None, "configuration_state": "unreadable",
                "read_error": "Geschützte Verbindungsdaten sind nicht lesbar. Schlüssel oder Wiederherstellung prüfen.",
                "validation": {"valid": None, "errors": {}}, "unmapped_fields": [],
                "secret_fields_present": [], "source": "database",
                "created_at": storage.stamp(connection.created_at),
                "updated_at": storage.stamp(connection.updated_at), "planned": provider.manifest.planned}

    def _public_or_problem(self, unit, connection) -> dict:
        try:
            return self.public(unit, connection)
        except HTTPException as failure:
            if failure.status_code != 503:
                raise
            return self._unreadable(connection)

    def state(self, identifier: str, actor_id: str) -> dict:
        """Explicit degraded-state view; an unreadable configuration is never empty success."""
        with storage.work(self.store, actor_id) as unit:
            return self._public_or_problem(unit, storage.row(unit, IntegrationConnectionORM, identifier))

    def get(self, identifier: str, actor_id: str) -> dict:
        with storage.work(self.store, actor_id) as unit:
            return self.public(unit, storage.row(unit, IntegrationConnectionORM, identifier))

    def list(self, actor_id: str, *, cursor=None, limit=50, include_archived=False) -> dict:
        with storage.work(self.store, actor_id) as unit:
            filters = {} if include_archived else {"archived": False}
            page = storage.page(unit, IntegrationConnectionORM, actor_id, cursor=cursor, limit=limit, **filters)
            page["items"] = [self._public_or_problem(unit, item) for item in page["items"]]
            return page

    def _create(self, unit, payload: ConnectionCreate, *, is_default=False, legacy_hash=None) -> dict:
        operation = "create"
        prior = storage.replay(unit, operation, payload)
        if prior:
            return self.public(unit, storage.row(unit, IntegrationConnectionORM, prior["connection_id"]))
        self.provider(payload.provider_id)
        raw = deepcopy(payload.config)
        secret_keys = set(self.provider(payload.provider_id).manifest.secret_config_keys) | {
            field["key"] for field in config_fields(self.provider(payload.provider_id).manifest) if field.get("secret")}
        if any(raw.get(key) == "***" for key in secret_keys):
            raise HTTPException(422, "Eine Geheimnismaske ist kein neuer Zugangsschlüssel. Bitte den tatsächlichen Wert eingeben.")
        self._checked(payload.provider_id, raw, enabled=payload.enabled)
        identifier = str(uuid5(NAMESPACE_URL, "immo:connection-default:" + payload.provider_id)) if is_default else str(uuid4())
        if storage.row(unit, IntegrationConnectionORM, identifier, required=False) is not None:
            raise HTTPException(409, "Die bestehende Anbieter-Verbindung wurde bereits übernommen.")
        stamp = storage.now()
        # Create the parent before immutable secret versions reference it.
        connection = storage.put(unit, IntegrationConnectionORM, {
            "id": identifier, "provider_id": payload.provider_id, "name": payload.name, "enabled": payload.enabled,
            "is_default": is_default, "archived": False, "revision": 1, "secret_refs": {},
            "config_token": storage.seal({}, f"connection/{identifier}/config", self.box),
            "legacy_source_hash": legacy_hash, "created_by": unit.actor_id, "created_at": stamp, "updated_at": stamp,
        })
        token, references = self._config_data(unit, identifier, payload.provider_id, 1, raw)
        connection = storage.put(unit, IntegrationConnectionORM, {**storage.values(connection), "config_token": token, "secret_refs": references})
        storage.record_event(unit, identifier, "created", {"revision": 1, "snapshot": self.snapshot(connection)}, box=self.box)
        storage.receipt(unit, operation, payload, identifier, {"connection_id": identifier})
        return self.public(unit, connection)

    def create(self, payload: ConnectionCreate, actor_id: str) -> dict:
        with storage.work(self.store, actor_id, write=True, command_key=payload.idempotency_key) as unit:
            return self._create(unit, payload)

    def update(self, identifier: str, payload: ConnectionUpdate, actor_id: str) -> dict:
        with storage.work(self.store, actor_id, write=True, command_key=payload.idempotency_key) as unit:
            connection = storage.row(unit, IntegrationConnectionORM, identifier, lock=True)
            prior = storage.replay(unit, "update:" + identifier, payload)
            if prior:
                return self._public_or_problem(unit, connection)
            storage.revision(connection, payload.base_revision)
            try:
                raw = self.effective_config(unit, connection)
            except HTTPException as failure:
                disabling_only = ((payload.enabled is False or payload.archived is True)
                                  and payload.name is None and payload.config is None and not payload.clear_secrets
                                  and payload.enabled is not True and payload.archived is not False)
                if failure.status_code != 503 or not disabling_only:
                    raise
                # An emergency stop never destroys unreadable ciphertext or
                # creates a replacement key. Its existing command receipt is
                # the durable actor/time/revision audit for this metadata-only
                # transition; no unencrypted config event is fabricated.
                connection = storage.put(unit, IntegrationConnectionORM, {**storage.values(connection),
                    "enabled": False, "archived": bool(payload.archived or connection.archived),
                    "revision": connection.revision + 1, "updated_at": storage.now()})
                storage.receipt(unit, "update:" + identifier, payload, identifier,
                    {"connection_id": identifier, "revision": connection.revision,
                     "operation": "disable_unreadable", "enabled": False,
                     "ciphertext_preserved": True})
                return self._unreadable(connection)
            fields = config_fields(self.provider(connection.provider_id).manifest)
            secrets = set(self.provider(connection.provider_id).manifest.secret_config_keys) | {field["key"] for field in fields if field.get("secret")}
            if set(payload.clear_secrets) - secrets:
                raise HTTPException(422, "Die Löschliste enthält kein bekanntes Geheimnisfeld.")
            for key, value in (payload.config or {}).items():
                if key in secrets and value in (None, "", "***"):
                    continue
                if key in payload.clear_secrets:
                    raise HTTPException(422, "Ein Geheimnis kann nicht gleichzeitig ersetzt und gelöscht werden.")
                raw[key] = value
            for key in payload.clear_secrets:
                raw.pop(key, None)
            enabled = payload.enabled if payload.enabled is not None else connection.enabled
            archived = payload.archived if payload.archived is not None else connection.archived
            if archived:
                enabled = False
            self._checked(connection.provider_id, raw, enabled=enabled)
            revision = connection.revision + 1
            token, references = self._config_data(unit, identifier, connection.provider_id, revision, raw, connection.secret_refs)
            connection = storage.put(unit, IntegrationConnectionORM, {
                **storage.values(connection), "revision": revision, "name": payload.name or connection.name,
                "enabled": enabled, "archived": archived, "config_token": token, "secret_refs": references, "updated_at": storage.now(),
            })
            storage.record_event(unit, identifier, "configuration_changed", {"revision": revision, "snapshot": self.snapshot(connection)}, box=self.box)
            storage.receipt(unit, "update:" + identifier, payload, identifier, {"connection_id": identifier, "revision": revision})
            return self.public(unit, connection)

    def legacy_preview(self, provider_id: str, actor_id: str) -> dict:
        with storage.work(self.store, actor_id) as unit:
            self.provider(provider_id)
            existing = storage.find_one(unit, IntegrationConnectionORM, provider_id=provider_id, is_default=True)
            if existing:
                return {"adopted": True, "connection": self.public(unit, existing)}
            raw = self.manager._store.load()
            source = {"enabled": raw.get("enabled", {}).get(provider_id, self.provider(provider_id).manifest.enabled_by_default),
                      "config": raw.get("config", {}).get(provider_id, {})}
            opened, _plaintext, errors = self.manager._unsealed(provider_id, source["config"])
            if errors:
                raise HTTPException(503, "Die bestehende Verbindung kann ohne ihren Schlüssel nicht übernommen werden.")
            checked = self.validation(provider_id, opened, complete=True)
            return {"adopted": False, "provider_id": provider_id, "source_hash": storage.digest(source),
                    "enabled": bool(source["enabled"]), "configured": checked["valid"],
                    "unmapped_field_count": len(checked["unmapped_fields"]), "secret_values_included": False}

    def adopt_legacy(self, payload: LegacyAdoption, actor_id: str) -> dict:
        if not getattr(self.manager, "connection_bridge_enabled", False):
            raise HTTPException(409, "Die eindeutige Umschaltung der bisherigen Konfiguration ist noch nicht aktiviert.")
        # The bridge uses this same writer lock for old configuration commands.
        with storage.work(self.store, actor_id, write=True, command_key=payload.idempotency_key) as unit:
            prior = storage.replay(unit, "adopt:" + payload.provider_id, payload)
            if prior:
                return self.public(unit, storage.row(unit, IntegrationConnectionORM, prior["connection_id"]))
            raw = self.manager._store.load()
            provider = self.provider(payload.provider_id)
            source = {"enabled": raw.get("enabled", {}).get(payload.provider_id, provider.manifest.enabled_by_default),
                      "config": raw.get("config", {}).get(payload.provider_id, {})}
            if storage.digest(source) != payload.expected_source_hash:
                raise HTTPException(409, "Die bisherige Konfiguration wurde geändert. Bitte die Übernahme neu prüfen.")
            opened, _plaintext, errors = self.manager._unsealed(payload.provider_id, source["config"])
            if errors:
                raise HTTPException(503, "Die bestehende Verbindung kann ohne ihren Schlüssel nicht übernommen werden.")
            create = ConnectionCreate(idempotency_key="adopt-internal:" + payload.idempotency_key, provider_id=payload.provider_id,
                                      name=provider.manifest.name, config=opened, enabled=bool(source["enabled"]))
            connection = self._create(unit, create, is_default=True, legacy_hash=payload.expected_source_hash)
            storage.receipt(unit, "adopt:" + payload.provider_id, payload, connection["id"], {"connection_id": connection["id"]})
            return connection

    def events(self, identifier: str, actor_id: str, *, cursor=None, limit=50) -> dict:
        with storage.work(self.store, actor_id) as unit:
            storage.row(unit, IntegrationConnectionORM, identifier)
            # A recovery event recorded by an owner still belongs to the run's
            # original creator. Filter by run identity before counts/paging,
            # not by whoever happened to record its latest review.
            condition = None if unit.user["role"] == "eigentuemer" else or_(
                IntegrationConnectionEventORM.run_id.is_(None), IntegrationConnectionEventORM.run_id.in_(
                    select(IntegrationActionRunORM.id).where(IntegrationActionRunORM.actor_id == actor_id)))
            def owns_event(item):
                if item.run_id is None:
                    return True
                run = storage.row(unit, IntegrationActionRunORM, item.run_id, required=False)
                return run is not None and run.actor_id == actor_id
            memory_condition = None if unit.user["role"] == "eigentuemer" else owns_event
            page = storage.page(unit, IntegrationConnectionEventORM, actor_id, cursor=cursor, limit=limit,
                                sql_condition=condition, memory_condition=memory_condition, connection_id=identifier)
            items = []
            for item in page["items"]:
                _detail, binding = storage.event_detail(item, self.box)
                # This is the shared metadata index, not a raw observation
                # export. Private source values remain in their encrypted proof.
                items.append({"id": item.id, "event_type": item.event_type, "actor_id": item.actor_id,
                              "run_id": item.run_id, "created_at": storage.stamp(item.created_at), "proof_binding": binding})
            page["items"] = items
            return page

    def observe(self, identifier: str, payload: SourceObservation, actor_id: str) -> dict:
        with storage.work(self.store, actor_id, write=True, command_key=payload.idempotency_key) as unit:
            storage.row(unit, IntegrationConnectionORM, identifier, lock=True)
            prior = storage.replay(unit, "observe:" + identifier, payload)
            if prior:
                return self.mapping_public(unit, storage.row(unit, IntegrationConnectionMappingORM, prior["mapping_id"]))
            if storage.digest(payload.raw) != payload.source_sha256:
                raise HTTPException(422, "Der Quellhash stimmt nicht mit den beobachteten Angaben überein.")
            key_hash = storage.digest([payload.source_kind, payload.external_key])
            current = storage.find_one(unit, IntegrationConnectionMappingORM, lock=True, connection_id=identifier,
                                       source_kind=payload.source_kind, external_key_hash=key_hash)
            if current:
                if payload.base_revision is None:
                    raise HTTPException(409, "Für die erneute Quellbeobachtung wird deren aktueller Stand benötigt.")
                storage.revision(current, payload.base_revision)
                mapping_id = current.id
                revision = current.revision + 1
                unchanged = current.source_sha256 == payload.source_sha256
                data = storage.values(current)
            else:
                if payload.base_revision is not None:
                    raise HTTPException(409, "Diese externe Quelle wurde noch nicht beobachtet.")
                mapping_id, revision, unchanged = str(uuid4()), 1, False
                data = {"id": mapping_id, "connection_id": identifier, "source_kind": payload.source_kind,
                        "external_key_hash": key_hash, "target_kind": None, "target_id": None,
                        "confirmed_by": None, "confirmed_at": None, "created_at": storage.now()}
            data.update(external_key_token=storage.seal(payload.external_key, f"connection-mapping/{mapping_id}/key", self.box),
                        state=data.get("state", "observed") if unchanged else "observed", revision=revision,
                        source_sha256=payload.source_sha256, observed_token=storage.seal(payload.raw, f"connection-mapping/{mapping_id}/raw", self.box),
                        manifest_token=storage.seal(storage.field_manifest(payload.raw), f"connection-mapping/{mapping_id}/manifest", self.box),
                        updated_at=storage.now())
            if not unchanged:
                data.update(confirmed_by=None, confirmed_at=None)
            mapping = storage.put(unit, IntegrationConnectionMappingORM, data)
            storage.record_event(unit, identifier, "source_observed", {"mapping_id": mapping_id, "source_sha256": payload.source_sha256,
                "source": payload.raw, "external_key": payload.external_key, "revision": revision}, box=self.box)
            storage.receipt(unit, "observe:" + identifier, payload, identifier, {"mapping_id": mapping_id})
            return self.mapping_public(unit, mapping)

    def mapping_public(self, unit, mapping) -> dict:
        if mapping.target_kind and mapping.target_id:
            resolve_context(unit.store, mapping.target_kind, mapping.target_id, unit.actor_id)
        return {"id": mapping.id, "connection_id": mapping.connection_id, "source_kind": mapping.source_kind,
                "external_key": storage.unseal(mapping.external_key_token, f"connection-mapping/{mapping.id}/key", self.box),
                "target_kind": mapping.target_kind, "target_id": mapping.target_id, "state": mapping.state,
                "revision": mapping.revision, "source_sha256": mapping.source_sha256,
                "fields": storage.unseal(mapping.manifest_token, f"connection-mapping/{mapping.id}/manifest", self.box),
                "confirmed_by": mapping.confirmed_by, "confirmed_at": storage.stamp(mapping.confirmed_at) if mapping.confirmed_at else None}

    def mappings(self, identifier: str, actor_id: str, *, cursor=None, limit=50) -> dict:
        with storage.work(self.store, actor_id) as unit:
            storage.row(unit, IntegrationConnectionORM, identifier)
            page = storage.page(unit, IntegrationConnectionMappingORM, actor_id, cursor=cursor, limit=limit, connection_id=identifier)
            page["items"] = [self.mapping_public(unit, item) for item in page["items"]]
            return page

    def decide_mapping(self, identifier: str, mapping_id: str, payload: MappingDecision, actor_id: str) -> dict:
        with storage.work(self.store, actor_id, write=True, command_key=payload.idempotency_key) as unit:
            storage.row(unit, IntegrationConnectionORM, identifier, lock=True)
            mapping = storage.row(unit, IntegrationConnectionMappingORM, mapping_id, lock=True)
            if mapping.connection_id != identifier:
                raise HTTPException(404, "Zuordnung nicht gefunden.")
            prior = storage.replay(unit, "mapping:" + mapping_id, payload)
            if prior:
                return self.mapping_public(unit, mapping)
            storage.revision(mapping, payload.base_revision)
            if payload.source_sha256 != mapping.source_sha256:
                raise HTTPException(409, "Die externe Quelle wurde seit der Vorschau geändert.")
            source = resolve_context(unit.store, payload.target_kind, payload.target_id, actor_id, lock=True)
            storage.commands.check_revision(payload.target_revision, source["revision"])
            data = {**storage.values(mapping), "revision": mapping.revision + 1, "target_kind": payload.target_kind,
                    "target_id": payload.target_id, "state": payload.decision, "confirmed_by": actor_id,
                    "confirmed_at": storage.now(), "updated_at": storage.now()}
            mapping = storage.put(unit, IntegrationConnectionMappingORM, data)
            storage.record_event(unit, identifier, "mapping_" + payload.decision, {"mapping_id": mapping_id, "source_sha256": mapping.source_sha256,
                "target_kind": mapping.target_kind, "target_id": mapping.target_id, "target_revision": source["revision"]}, box=self.box)
            storage.receipt(unit, "mapping:" + mapping_id, payload, identifier, {"mapping_id": mapping_id})
            return self.mapping_public(unit, mapping)
