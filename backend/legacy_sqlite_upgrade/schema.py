"""Read-only complete native SQLite schema proofs; no application imports."""

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


class LegacySchemaError(RuntimeError):
    """Fixed non-secret failure code for an unsupported or damaged schema."""


def quoted(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def normalized_sql(sql: str | None) -> str | None:
    if sql is None:
        return None
    # Keep quoted names/literals byte-for-byte. Remove formatting only between
    # tokens, never inside a string (including a retention guard's message).
    tokens = re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[(?:[^\]])*\]|(?:!=|<>|<=|>=|==|\|\||->>|->)|[A-Za-z_][A-Za-z_0-9]*|\d+(?:\.\d+)?|[^\s]", sql)
    return " ".join(token if token[0] in "'\"`[" else token.lower() for token in tokens)


def normalized_table_sql(sql: str | None) -> str | None:
    normalized = normalized_sql(sql)
    if normalized is None:
        return None
    tokens = re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[(?:[^\]])*\]|[^\s]+", normalized)
    if tokens[:2] != ["create", "table"] or "(" not in tokens:
        return normalized
    start = tokens.index("(")
    depth = 0
    pieces: list[list[str]] = []
    piece: list[str] = []
    for offset, token in enumerate(tokens[start + 1:], start + 1):
        if token == ")" and depth == 0:
            pieces.append(piece)
            end = offset
            break
        if token == "," and depth == 0:
            pieces.append(piece)
            piece = []
            continue
        depth += (token == "(") - (token == ")")
        piece.append(token)
    else:
        return normalized
    kinds = {"constraint", "primary", "foreign", "unique", "check"}
    columns = [value for value in pieces if value and value[0] not in kinds]
    constraints = sorted([value for value in pieces if value and value[0] in kinds])
    body: list[str] = []
    for value in columns + constraints:
        if body:
            body.append(",")
        body.extend(value)
    return " ".join(tokens[:start + 1] + body + tokens[end:])


def canonical_catalog(value: dict) -> dict:
    objects = [list(row) for row in value["objects"]]
    for row in objects:
        row[3] = normalized_table_sql(row[3]) if row[0] == "table" else normalized_sql(row[3])
    return {"objects": objects, "tables": value["tables"]}


def catalog(connection: sqlite3.Connection) -> dict:
    objects = [list(row) for row in connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' AND name <> 'alembic_version' ORDER BY type,name")]
    tables = {}
    for kind, name, _, _ in objects:
        if kind != "table":
            continue
        indices = []
        for entry in connection.execute(f"PRAGMA index_list({quoted(name)})"):
            # Native autoindex names are implementation details; their complete
            # ordered columns/collations/descending flags and uniqueness remain.
            _, index_name, unique, origin, partial = entry
            indices.append([index_name if origin == "c" else None, unique, origin, partial,
                            [list(row[1:]) for row in connection.execute(f"PRAGMA index_xinfo({quoted(index_name)})")]])
        indices.sort(key=lambda value: json.dumps(value, ensure_ascii=False))
        tables[name] = {
            "columns": [list(row) for row in connection.execute(f"PRAGMA table_xinfo({quoted(name)})")],
            "foreign_keys": sorted([list(row[1:]) for row in connection.execute(f"PRAGMA foreign_key_list({quoted(name)})")]),
            "indices": indices,
        }
    return canonical_catalog({"objects": objects, "tables": tables})


def catalog_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class LegacySchemaProof:
    profile_id: str
    source_commit: str
    schema_sha256: str
    missing_tables: frozenset[str]
    missing_columns: tuple[tuple[str, frozenset[str]], ...]

    def permits_missing(self, table: str, columns: set[str]) -> bool:
        if table in self.missing_tables:
            return True
        return columns <= dict(self.missing_columns).get(table, frozenset())

    def verify(self, connection: sqlite3.Connection) -> None:
        # Re-prove the entire profile. A dataclass constructed by a caller is not
        # a bypass, and a changed database cannot reuse a stale proof.
        if prove_legacy_schema(connection) != self:
            raise LegacySchemaError("legacy_schema_changed")


def profiles() -> dict:
    path = Path(__file__).with_name("release126_profiles.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value["format"] != 1:
            raise ValueError
        return value["profiles"]
    except (OSError, ValueError, KeyError, TypeError):
        raise LegacySchemaError("legacy_reference_unavailable") from None


def prove_legacy_schema(connection: sqlite3.Connection) -> LegacySchemaProof:
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'").fetchone():
        if connection.execute("SELECT 1 FROM alembic_version LIMIT 1").fetchone():
            raise LegacySchemaError("legacy_database_already_versioned")
        expected_version = [(0, "version_num", "VARCHAR(32)", 1, None, 1)]
        if connection.execute("PRAGMA table_info(alembic_version)").fetchall() != expected_version:
            raise LegacySchemaError("legacy_version_marker_unsupported")
        definitions = {
            normalized_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"),
            normalized_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"),
        }
        definition = connection.execute("SELECT sql FROM sqlite_master WHERE name='alembic_version'").fetchone()[0]
        if normalized_sql(definition) not in definitions:
            raise LegacySchemaError("legacy_version_marker_unsupported")
    actual = catalog(connection)
    digest = catalog_hash(actual)
    matches = [(name, reference) for name, reference in profiles().items()
               if reference["schema_sha256"] == digest and reference["catalog"] == actual]
    if len(matches) != 1:
        raise LegacySchemaError("legacy_schema_unrecognised")
    name, reference = matches[0]
    return LegacySchemaProof(name, reference["source_commit"], digest,
        frozenset(reference["missing_tables"]),
        tuple((table, frozenset(columns)) for table, columns in sorted(reference["missing_columns"].items())))


def inspect_legacy_sqlite(database: Path) -> LegacySchemaProof:
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA query_only=ON")
        return prove_legacy_schema(connection)
