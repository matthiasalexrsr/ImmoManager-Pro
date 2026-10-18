"""Effective runtime export and database attachment inventory; never log values."""
import json
import re
import sqlite3
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .file_storage import validate_key

RUNTIME = "secrets/runtime.json"
TOKEN = re.compile(r"enc:v1:([^:]+):")


def capture(settings) -> tuple[dict, bytes]:
    from ..config import SETTING_ORIGIN_FILES, SETTING_ORIGINS
    from ..runtime_origins import ENV_FILE_ORIGINS
    values = settings.model_dump(mode="json")
    values.pop("backup_passphrase", None)
    public = {"version": 1, "settings": {name: {"origin": "launcher_env_file" if name in ENV_FILE_ORIGINS else SETTING_ORIGINS.get(name, "default"),
               **({"file": ENV_FILE_ORIGINS.get(name) or SETTING_ORIGIN_FILES[name]}
                  if name in ENV_FILE_ORIGINS or name in SETTING_ORIGIN_FILES else {}),
               "value_in": RUNTIME} for name in values}}
    return public, json.dumps(values, ensure_ascii=False).encode("utf-8")


def relocated(raw: bytes) -> bytes:
    values = json.loads(raw)
    # The restored archive carries remote originals locally, and never reconnects an old DB.
    for name in ("data_dir", "uploads_dir", "backup_dir", "database_url", "log_file",
                 "integration_state_file", "secret_key_file", "backup_second_target",
                 "restore_probe_postgres_url", "s3_endpoint_url", "s3_access_key", "s3_secret_key"):
        values.pop(name, None)
    values["file_storage_backend"] = "local"
    values["plugin_dirs"] = []  # trusted executable packages must be separately installed
    lines = []
    for name, value in values.items():
        if value is None:
            continue
        text = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value)
        # JSON strings are valid dotenv quoted values; embedded newlines stay escaped.
        lines.append(name.upper() + "=" + json.dumps(text, ensure_ascii=False))
    return ("\n".join(lines) + "\n").encode("utf-8")


def inventory(database) -> tuple[set[str], set[str]]:
    """Find retained upload references and encryption key IDs in all persisted families.

    External http URLs are not silently treated as owned originals. Dedicated package
    hooks add non-URL keys; generated DB-backed archives are validated by their owner.
    """
    from .upload_policy import ARCHIVED_PREFIXES
    references, keys = set(), set()
    def visit(value):
        if isinstance(value, str):
            keys.update(TOKEN.findall(value))
            if value.startswith(("{", "[")):
                try:
                    visit(json.loads(value))
                except ValueError:
                    pass
            parsed = urlparse(value)
            if value.startswith(("/uploads/", "uploads/")):
                key = value.split("uploads/", 1)[1]
            elif parsed.scheme == "s3":
                key = parsed.path.lstrip("/")
            else:
                return
            key = validate_key(unquote(key))
            if not key.startswith(ARCHIVED_PREFIXES):
                references.add(key)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    is_file = isinstance(database, Path)
    context = closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) if is_file else nullcontext(database)
    with context as database_connection:
        conn: Any = database_connection
        execute = conn.execute if is_file else conn.exec_driver_sql
        if is_file:
            tables = [row[0] for row in execute("SELECT name FROM sqlite_master WHERE type='table'")]
        else:
            from sqlalchemy import inspect
            inspector = inspect(conn)
            if inspector is None:
                raise ValueError("Datenbankinventar kann nicht gelesen werden")
            tables = inspector.get_table_names()
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            for row in execute("SELECT * FROM " + quoted):
                for value in row:
                    visit(value)
        if "upload_portfolio_grants" in tables:
            references.update(row[0] for row in execute("SELECT storage_key FROM upload_portfolio_grants")
                              if not row[0].startswith(ARCHIVED_PREFIXES))
        if "storage_bindings" in tables:
            references.update(row[0] for row in execute("SELECT storage_key FROM storage_bindings WHERE deleted = false"))
        if {"documents", "document_versions", "document_version_chunks"}.issubset(tables):
            virtual = {validate_key(unquote(row[0].split("uploads/", 1)[1])) for row in execute(
                "SELECT DISTINCT d.file_url FROM documents d JOIN document_versions v ON v.document_id=d.id "
                "WHERE d.file_url LIKE '/uploads/assistant-archive/%'")}
            if virtual:
                # These locators deliberately have no disk file. Exclude only
                # exact URLs of proven DB originals, never the whole namespace.
                # The MIME-aware archived_upload reader remains authoritative.
                from .document_version_validation import verify_document_versions
                verify_document_versions(conn)
                references.difference_update(virtual)
    from .backup_extensions import extensions
    for extension in extensions():
        references.update(validate_key(key) for key in extension.references(database))
    return references, keys
