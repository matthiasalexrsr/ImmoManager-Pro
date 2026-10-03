"""Validate the TEHA receive family and install immutable evidence guards."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy import Index, Table, UniqueConstraint, inspect

from .teha_receive_models import TEHA_RECEIVE_MODELS, TEHA_RECEIVE_TABLES


class TehaReceiveSchemaError(RuntimeError):
    pass


_IDENTITY_PARTS: dict[str, tuple[str, ...]] = {
    "property": ("object_id",),
    "period": ("object_id", "period_number"),
    "unit": ("lieg_nr", "unit_id"),
    "user": ("termin_id", "user_id"),
    "technical_order": ("termin_id",),
}


def _component(value: Any) -> str | int:
    if type(value) is int:
        if value < 0:
            raise TehaReceiveSchemaError("negative TEHA identity component")
        return value
    if isinstance(value, str):
        if not value or value != value.strip() or any(ord(char) < 32 for char in value):
            raise TehaReceiveSchemaError("invalid TEHA identity component")
        return value
    raise TehaReceiveSchemaError("invalid TEHA identity component type")


def canonical_identity(kind: str, value: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """Validate that relational identity JSON contains opaque keys only."""
    expected = _IDENTITY_PARTS.get(kind)
    if expected is None or not isinstance(value, Mapping):
        raise TehaReceiveSchemaError("unsupported TEHA identity")
    if set(value) != {"kind", "parts"} or value.get("kind") != kind:
        raise TehaReceiveSchemaError("invalid TEHA identity shape")
    parts = value.get("parts")
    if not isinstance(parts, Mapping) or tuple(sorted(parts)) != tuple(sorted(expected)):
        raise TehaReceiveSchemaError("invalid TEHA identity parts")
    normalized = tuple(sorted((name, _component(parts[name])) for name in expected))
    canonical = {"kind": kind, "parts": dict(normalized)}
    token = hashlib.sha256(
        json.dumps(
            {"kind": kind, "parts": [list(item) for item in normalized]},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return canonical, token


def validate_identity_binding(kind: str, value: Mapping[str, Any], expected_hash: str) -> dict[str, Any]:
    canonical, actual = canonical_identity(kind, value)
    if actual != expected_hash:
        raise TehaReceiveSchemaError("TEHA identity hash mismatch")
    return canonical


def validate_teha_receive_schema(connection) -> bool:
    """Read-only schema validation. Missing is legacy-compatible; partial is not."""
    if isinstance(connection, sqlite3.Connection):
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

        def columns(name):
            return {
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{name}")')
            }

        def primary(name):
            rows = list(connection.execute(f'PRAGMA table_info("{name}")'))
            return tuple(
                row[1]
                for row in sorted(rows, key=lambda item: item[5])
                if row[5]
            )

        def uniques(name):
            result = set()
            for row in connection.execute(f'PRAGMA index_list("{name}")'):
                if row[2]:
                    result.add(
                        tuple(
                            item[2]
                            for item in connection.execute(
                                f'PRAGMA index_info("{row[1]}")'
                            )
                        )
                    )
            return result

        def foreign(name):
            grouped: dict[int, list[Any]] = {}
            for row in connection.execute(f'PRAGMA foreign_key_list("{name}")'):
                grouped.setdefault(row[0], []).append(row)
            return {
                (
                    tuple(row[3] for row in sorted(group, key=lambda item: item[1])),
                    group[0][2],
                    tuple(row[4] for row in sorted(group, key=lambda item: item[1])),
                    group[0][6].upper(),
                )
                for group in grouped.values()
            }

    else:
        inspector = inspect(connection)
        names = set(inspector.get_table_names())

        def columns(name):
            return {row["name"] for row in inspector.get_columns(name)}

        def primary(name):
            return tuple(
                inspector.get_pk_constraint(name).get("constrained_columns") or ()
            )

        def uniques(name):
            values = {
                tuple(row["column_names"])
                for row in inspector.get_unique_constraints(name)
            }
            values.update(
                tuple(row["column_names"])
                for row in inspector.get_indexes(name)
                if row.get("unique") and row.get("column_names")
            )
            return values

        def foreign(name):
            return {
                (
                    tuple(row["constrained_columns"]),
                    row["referred_table"],
                    tuple(row["referred_columns"]),
                    row.get("options", {}).get("ondelete", "NO ACTION").upper(),
                )
                for row in inspector.get_foreign_keys(name)
            }

    family = set(TEHA_RECEIVE_TABLES)
    if not names.intersection(family):
        return False
    if not family.issubset(names):
        raise TehaReceiveSchemaError("partial TEHA receive family")

    for model in TEHA_RECEIVE_MODELS:
        table = cast(Table, model.__table__)
        expected_unique = {
            tuple(column.name for column in item.columns)
            for item in table.constraints
            if isinstance(item, UniqueConstraint)
        }
        expected_unique.update(
            tuple(column.name for column in item.columns)
            for item in table.indexes
            if isinstance(item, Index) and item.unique
        )
        expected_fk = {
            (
                tuple(element.parent.name for element in item.elements),
                item.referred_table.name,
                tuple(element.column.name for element in item.elements),
                (item.ondelete or "NO ACTION").upper(),
            )
            for item in table.foreign_key_constraints
        }
        if (
            not set(table.columns.keys()).issubset(columns(table.name))
            or primary(table.name)
            != tuple(column.name for column in table.primary_key.columns)
            or not expected_unique.issubset(uniques(table.name))
            or foreign(table.name) != expected_fk
        ):
            raise TehaReceiveSchemaError("invalid TEHA receive schema")
    return True


def install_teha_receive_guards(connection) -> None:
    """Mappings/receipts are append-only; corrections insert a new generation."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        for table in TEHA_RECEIVE_TABLES:
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS preserve_{table}_update "
                f"BEFORE UPDATE ON {table} BEGIN "
                "SELECT RAISE(ABORT,'TEHA receive evidence is immutable'); END"
            )
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS preserve_{table}_delete "
                f"BEFORE DELETE ON {table} BEGIN "
                "SELECT RAISE(ABORT,'TEHA receive evidence is immutable'); END"
            )
    elif dialect == "postgresql":
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_teha_receive_immutable() "
            "RETURNS trigger AS $$ BEGIN "
            "RAISE EXCEPTION 'TEHA receive evidence is immutable'; "
            "END; $$ LANGUAGE plpgsql"
        )
        for table in TEHA_RECEIVE_TABLES:
            for action in ("update", "delete"):
                name = f"preserve_{table}_{action}"
                connection.exec_driver_sql(
                    f"DROP TRIGGER IF EXISTS {name} ON {table}"
                )
                connection.exec_driver_sql(
                    f"CREATE TRIGGER {name} BEFORE {action.upper()} ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION immo_teha_receive_immutable()"
                )
    else:
        raise TehaReceiveSchemaError(
            "TEHA receive persistence supports SQLite and PostgreSQL"
        )
