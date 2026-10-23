"""Explicit, transactional upgrades for trusted in-process plugins' declared JSON data.

This is a compatibility/data lifecycle boundary, NOT a Python sandbox. It grants no
authority to financial tables. Plugins with other persistence must not use this API.
"""
import hashlib
import json
import re
from contextlib import ExitStack
from copy import deepcopy
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, text

from ..db.access_models import PluginInstallationORM

API_VERSION = 1
CAPABILITIES = {"owned_data", "owner_routes"}


def validate_schema(schema: dict, value, *, declaration: bool = False):
    """Small closed JSON-schema subset; unsupported constraints are refused."""
    allowed = {"type", "properties", "required", "additionalProperties", "items", "enum"}
    if not isinstance(schema, dict) or set(schema) - allowed:
        raise ValueError("Nicht unterstützte Plugin-Datendeklaration")
    kind = schema.get("type")
    types: dict[str, Any] = {"object": dict, "array": list, "string": str, "integer": int,
             "boolean": bool, "number": (int, float), "null": type(None)}
    if kind not in types:
        raise ValueError("Plugin-Datentyp fehlt")
    if kind == "object":
        if schema.get("additionalProperties") is not False:
            raise ValueError("Plugin-Objekte müssen Felder vollständig deklarieren")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ValueError("Ungültige Plugin-Felddeklaration")
        if not set(schema.get("required", [])).issubset(properties):
            raise ValueError("Unbekanntes Pflichtfeld")
        for child in properties.values():
            validate_schema(child, None, declaration=True)
    if kind == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            raise ValueError("Plugin-Listen benötigen eine Elementdeklaration")
        validate_schema(items, None, declaration=True)
    if declaration:
        return
    if not isinstance(value, types[kind]) or (kind in ("integer", "number") and isinstance(value, bool)):
        raise ValueError("Plugin-Daten entsprechen nicht der deklarierten Struktur")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Nicht erlaubter Plugin-Feldwert")
    if kind == "object":
        if set(value) - set(properties) or not set(schema.get("required", [])).issubset(value):
            raise ValueError("Plugin-Daten enthalten unbekannte oder fehlende Felder")
        for name, child in value.items():
            validate_schema(properties[name], child)
    if kind == "array":
        for child in value:
            validate_schema(schema["items"], child)


def manifest(plugin) -> dict:
    value = deepcopy(plugin.data_manifest)
    if (not re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", plugin.name)
            or not re.fullmatch(r"\d+\.\d+\.\d+", plugin.version)
            or set(value) != {"api_version", "schema_version", "schemas", "capabilities", "migrations"}
            or value["api_version"] != API_VERSION
            or not isinstance(value["schema_version"], int) or value["schema_version"] < 1
            or not set(value["capabilities"]).issubset(CAPABILITIES)
            or value["migrations"] != list(range(1, value["schema_version"] + 1))):
        raise ValueError("Plugin ist mit dieser API oder Datenmigration nicht kompatibel")
    for version in value["migrations"]:
        schema = value["schemas"].get(str(version))
        if not isinstance(schema, dict):
            raise ValueError("Deklariertes Plugin-Datenschema fehlt")
        validate_schema(schema, None, declaration=True)
        if not callable(plugin.data_migrations.get(version)):
            raise ValueError("Deklarierte Pluginmigration fehlt")
    return {"name": plugin.name, "version": plugin.version, **value,
            "package": deepcopy(getattr(plugin, "package_declaration", None))}


def change(factory, plugin, *, actor_id: str, expected_revision: int, idempotency_key: str,
           operation: str, backup_revision: int | None = None) -> dict:
    """Caller must enforce fresh owner + installation scope before calling, even on replay."""
    declared = manifest(plugin)
    if operation not in {"upgrade", "uninstall", "restore"} or not 8 <= len(idempotency_key) <= 120:
        raise ValueError("Ungültiger Pluginauftrag")
    command = {"operation": operation, "manifest": declared, "expected_revision": expected_revision,
               "backup_revision": backup_revision, "actor_id": actor_id}
    digest = hashlib.sha256(json.dumps(command, sort_keys=True).encode()).hexdigest()
    from .. import auth
    from ..services.portfolio_scope import scope_from_user
    with factory() as session, ExitStack() as locks:
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        else:
            # Serializes initial installation too, when there is no row yet.
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                            {"key": int.from_bytes(hashlib.sha256(plugin.name.encode()).digest()[:8], "big", signed=True)})
        user = locks.enter_context(auth.locked_account(actor_id, session))
        if not user or not user.get("is_active") or user.get("role") != "eigentuemer" or not scope_from_user(user).unrestricted:
            raise HTTPException(403, "Pluginverwaltung benötigt aktuelle uneingeschränkte Eigentümerrechte")
        row = session.execute(select(PluginInstallationORM).where(
            PluginInstallationORM.name == plugin.name).with_for_update()).scalar_one_or_none()
        commands = deepcopy(row.commands) if row else {}
        replay = commands.get(idempotency_key)
        if replay:
            if replay["digest"] != digest:
                raise HTTPException(409, "Wiederholungsschlüssel gehört zu einem anderen Pluginauftrag")
            return replay["result"]
        if expected_revision != (row.revision if row else 0):
            raise HTTPException(409, "Pluginstand wurde geändert. Bitte neu laden.")
        if row is None:
            if operation != "upgrade":
                raise HTTPException(404, "Plugin ist nicht installiert")
            row = PluginInstallationORM(name=plugin.name, revision=0, enabled=False, manifest={},
                                        payload={}, backups=[], commands={})
            session.add(row)
        snapshots = deepcopy(row.backups)
        if row.revision:
            snapshots.append({"revision": row.revision, "manifest": deepcopy(row.manifest),
                              "payload": deepcopy(row.payload), "enabled": row.enabled})
        payload = deepcopy(row.payload)
        if operation == "upgrade":
            old = row.manifest.get("schema_version", 0)
            if declared["schema_version"] < old:
                raise HTTPException(409, "Plugin-Downgrade benötigt eine explizite Wiederherstellung")
            for version in range(old + 1, declared["schema_version"] + 1):
                payload = plugin.data_migrations[version](deepcopy(payload))
                validate_schema(declared["schemas"][str(version)], payload)
            validate_schema(declared["schemas"][str(declared["schema_version"])], payload)
            row.manifest, row.payload, row.enabled = declared, payload, True
        elif operation == "uninstall":
            # Retain data and executable/schema declaration for complete future restoration.
            row.enabled = False
        else:
            snapshot = next((item for item in snapshots if item["revision"] == backup_revision), None)
            if snapshot is None:
                raise HTTPException(404, "Plugin-Sicherung nicht gefunden")
            saved = snapshot["manifest"]
            validate_schema(saved["schemas"][str(saved["schema_version"])], snapshot["payload"])
            row.manifest, row.payload = saved, deepcopy(snapshot["payload"])
            # Never enable old data against incompatible installed executable code.
            row.enabled = saved == declared and snapshot["enabled"]
        row.revision += 1
        result = {"name": row.name, "revision": row.revision, "enabled": row.enabled,
                  "version": row.manifest["version"], "schema_version": row.manifest["schema_version"],
                  "backup_revisions": [item["revision"] for item in snapshots],
                  "restart_required": True, "sandboxed": False}
        commands[idempotency_key] = {"digest": digest, "result": result}
        row.backups, row.commands = snapshots, commands
        session.commit()
        return result
