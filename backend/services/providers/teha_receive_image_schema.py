"""Read-only SQLite proof of the frozen initial L2 schema and guards."""

import re
from collections import Counter

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.sqlite import dialect

from ...db.teha_receive_release_l2 import L2_TABLE_NAMES, frozen_l2_tables
from ...db.teha_receive_schema import TehaReceiveSchemaError, validate_teha_receive_schema

_TOKEN = re.compile(r"\s+|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|<=|>=|<>|!=|[(),.=><+*/;-]")


def _tokens(sql):
    if not isinstance(sql, str):
        raise TehaReceiveSchemaError("invalid TEHA image schema")
    result, end = [], 0
    for match in _TOKEN.finditer(sql):
        if match.start() != end:
            raise TehaReceiveSchemaError("invalid TEHA image schema")
        end = match.end()
        value = match.group()
        if value.isspace():
            continue
        if value.startswith('"'):
            value = value[1:-1].replace('""', '"').lower()
        elif not value.startswith("'"):
            value = value.lower()
        result.append(value)
    if end != len(sql):
        raise TehaReceiveSchemaError("invalid TEHA image schema")
    return tuple(result)


def _checks(sql):
    tokens, expressions, index = _tokens(sql), [], 0
    while index < len(tokens):
        if tokens[index] != "check":
            index += 1
            continue
        index += 1
        if index >= len(tokens) or tokens[index] != "(":
            raise TehaReceiveSchemaError("invalid TEHA image CHECK")
        start, depth = index + 1, 1
        index += 1
        while index < len(tokens) and depth:
            depth += (tokens[index] == "(") - (tokens[index] == ")")
            index += 1
        if depth:
            raise TehaReceiveSchemaError("invalid TEHA image CHECK")
        expressions.append(tokens[start:index - 1])
    return Counter(expressions)


def validate_teha_image_schema(connection, *, schema_bytes):
    """No DDL; semantic tokens come from frozen expressions, not live ORM."""
    family = {value[0] for value in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?)", L2_TABLE_NAMES,
    )}
    if not family:
        return False
    if family != set(L2_TABLE_NAMES):
        raise TehaReceiveSchemaError("partial TEHA image family")
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE tbl_name IN (?,?) AND "
        "(length(CAST(name AS BLOB))>? OR length(CAST(sql AS BLOB))>?) LIMIT 1",
        (*L2_TABLE_NAMES, schema_bytes, schema_bytes),
    ).fetchone():
        raise TehaReceiveSchemaError("TEHA image schema budget exceeded")
    # The frozen VARCHAR primary key has one SQLite autoindex; each full
    # UniqueConstraint adds another. Reject extra indexes before the existing
    # schema helper materializes index metadata. This is release-schema proof,
    # not an invented upper bound on the number of retained business rows.
    for table in frozen_l2_tables():
        expected = len(table.indexes) + 1 + sum(isinstance(item, UniqueConstraint) for item in table.constraints)
        count = connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND tbl_name=?", (table.name,)).fetchone()[0]
        if count != expected:
            raise TehaReceiveSchemaError("unexpected TEHA image indexes")
    validate_teha_receive_schema(connection)
    for table in frozen_l2_tables():
        row = connection.execute(
            "SELECT CASE WHEN length(CAST(sql AS BLOB))<=? THEN sql ELSE NULL END "
            "FROM sqlite_master WHERE type='table' AND name=?", (schema_bytes, table.name),
        ).fetchone()
        if row is None or row[0] is None:
            raise TehaReceiveSchemaError("invalid TEHA image schema")
        expected_checks = Counter(_tokens(str(item.sqltext)) for item in table.constraints
                                  if isinstance(item, CheckConstraint))
        if _checks(row[0]) != expected_checks:
            raise TehaReceiveSchemaError("invalid TEHA image CHECKs")
        info = list(connection.execute(f'PRAGMA table_info("{table.name}")'))
        actual_types = {value[1]: value[2].upper().replace(" ", "") for value in info}
        expected_types = {column.name: column.type.compile(dialect=dialect()).upper().replace(" ", "")
                          for column in table.columns}
        if actual_types != expected_types:
            raise TehaReceiveSchemaError("invalid TEHA image types")
        indices = list(connection.execute(f'PRAGMA index_list("{table.name}")'))
        full_uniques = set()
        named = {}
        for index in indices:
            # Index names are supplied by SQLite schema; bound before quoting.
            name = index[1]
            if not isinstance(name, str) or len(name.encode("utf-8")) > schema_bytes:
                raise TehaReceiveSchemaError("invalid TEHA image index")
            quoted = name.replace('"', '""')
            columns = tuple(value[2] for value in connection.execute(f'PRAGMA index_info("{quoted}")'))
            for value in connection.execute(f'PRAGMA index_xinfo("{quoted}")'):
                if value[5] and (value[1] < 0 or value[3] or value[4].upper() != "BINARY"):
                    raise TehaReceiveSchemaError("invalid TEHA image index ordering")
            named[name] = (bool(index[2]), bool(index[4]), columns)
            if index[2] and not index[4]:
                full_uniques.add(columns)
        required_full = {tuple(column.name for column in item.columns)
                         for item in table.constraints if isinstance(item, UniqueConstraint)}
        if not required_full <= full_uniques:
            raise TehaReceiveSchemaError("invalid TEHA image full uniqueness")
        expected_partial = set()
        for index in table.indexes:
            predicate = index.dialect_options["sqlite"].get("where")
            partial = predicate is not None
            if partial:
                expected_partial.add(index.name)
            expected = (bool(index.unique), partial, tuple(column.name for column in index.columns))
            if named.get(index.name) != expected:
                raise TehaReceiveSchemaError("invalid TEHA image index")
            index_sql = connection.execute(
                "SELECT CASE WHEN length(CAST(sql AS BLOB))<=? THEN sql ELSE NULL END "
                "FROM sqlite_master WHERE type='index' AND name=?", (schema_bytes, index.name),
            ).fetchone()
            if index_sql is None or index_sql[0] is None:
                raise TehaReceiveSchemaError("invalid TEHA image index")
            tokens = _tokens(index_sql[0])
            where = tokens.index("where") if "where" in tokens else None
            actual_predicate = tokens[where + 1:] if where is not None else None
            if actual_predicate != (_tokens(str(predicate)) if partial else None):
                raise TehaReceiveSchemaError("invalid TEHA image partial predicate")
        if {name for name, value in named.items() if value[1]} != expected_partial:
            raise TehaReceiveSchemaError("unexpected TEHA image partial index")
        expected_guards = {}
        for action in ("update", "delete"):
            name = f"preserve_{table.name}_{action}"
            expected_guards[name] = _tokens(
                f"CREATE TRIGGER {name} BEFORE {action.upper()} ON {table.name} BEGIN "
                "SELECT RAISE(ABORT,'TEHA receive evidence is immutable'); END"
            )
        actual_guards = {}
        for name, sql in connection.execute(
            "SELECT name, CASE WHEN length(CAST(sql AS BLOB))<=? THEN sql ELSE NULL END "
            "FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (schema_bytes, table.name),
        ):
            actual_guards[name] = _tokens(sql)
        if actual_guards != expected_guards:
            raise TehaReceiveSchemaError("invalid TEHA image immutable guards")
    return True
