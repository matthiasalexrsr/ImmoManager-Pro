"""Narrow native SQLite identity-CHECK proof; no DDL, DML or runtime imports.

Caller owns a consistent schema snapshot and exclusive connection use. This is
an observation of the actual connection, never a write/commit capability.
"""

import sqlite3
from dataclasses import dataclass
from math import isfinite
from time import monotonic

from sqlalchemy import text
from sqlalchemy.engine import Connection

TABLE = "notification_read_states"
GUARD = "ck_notification_read_identity"
IDENTITIES = frozenset({"actor_id", "notification_id"})
_FLAGS = 0x800 | 0x200000  # SQLITE_DETERMINISTIC | SQLITE_INNOCUOUS
_ASCII_FOLD = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


class SQLiteInboxCheckError(ValueError):
    """Only a fixed code, never native exception values or SQL."""


def _fail(suffix):
    raise SQLiteInboxCheckError(f"notification_inbox_sqlite_check_{suffix}")


@dataclass(frozen=True)
class SQLiteInboxCheckLimits:
    ddl_bytes: int = 65536
    tokens: int = 4096
    depth: int = 64
    catalog_rows: int = 512

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in (
            self.ddl_bytes, self.tokens, self.depth, self.catalog_rows
        )):
            _fail("limits_invalid")


def _check(deadline):
    if deadline is not None and monotonic() >= deadline:
        _fail("timeout")


def _options(limits, deadline):
    if limits is None:
        limits = SQLiteInboxCheckLimits()
    if type(limits) is not SQLiteInboxCheckLimits:
        _fail("limits_invalid")
    if deadline is not None:
        try:
            finite = type(deadline) in (int, float) and isfinite(deadline)
        except (OverflowError, ValueError):
            finite = False
        if not finite:
            _fail("limits_invalid")
    _check(deadline)
    return limits


def _ascii(value):
    return value.translate(_ASCII_FOLD)


def _rows(connection, sql, parameters, limits, deadline):
    _check(deadline)
    cursor = None
    try:
        if isinstance(connection, sqlite3.Connection):
            cursor = connection.execute(sql, parameters)
            names = tuple(column[0] for column in cursor.description)
        elif isinstance(connection, Connection) and connection.dialect.name == "sqlite":
            cursor = connection.execute(text(sql), parameters)
            names = tuple(cursor.keys())
        else:
            _fail("catalog_invalid")
        rows = []
        while batch := cursor.fetchmany(min(32, limits.catalog_rows + 1)):
            for values in batch:
                _check(deadline)
                if len(rows) >= limits.catalog_rows:
                    _fail("budget_exceeded")
                rows.append(dict(zip(names, values)))
        _check(deadline)
        return rows
    finally:
        if cursor is not None:
            cursor.close()


def _functions(connection, limits, deadline):
    required = {("length", 1), ("substr", 3)}
    found = set()
    rows = _rows(connection, "PRAGMA function_list", {}, limits, deadline)
    if not rows:
        _fail("function_invalid")
    for row in rows:
        if set(row) != {"name", "builtin", "type", "enc", "narg", "flags"}:
            _fail("function_invalid")
        name, arity = row["name"], row["narg"]
        if not isinstance(name, str) or type(arity) is not int:
            _fail("function_invalid")
        name = _ascii(name)
        if not any(name == target and arity in (count, -1) for target, count in required):
            continue
        if (type(row["builtin"]) is not int or row["builtin"] != 1
                or row["type"] != "s" or row["enc"] not in {"utf8", "utf16le", "utf16be"}
                or type(row["flags"]) is not int or row["flags"] & _FLAGS != _FLAGS):
            _fail("function_invalid")
        if (name, arity) in required:
            found.add((name, arity))
    if found != required:
        _fail("function_invalid")


def _enabled(connection, limits, deadline):
    rows = _rows(connection, "PRAGMA ignore_check_constraints", {}, limits, deadline)
    if len(rows) != 1 or set(rows[0]) != {"ignore_check_constraints"}:
        _fail("catalog_invalid")
    value = rows[0]["ignore_check_constraints"]
    if type(value) is not int or value != 0:
        _fail("disabled")


def _encoding(connection, limits, deadline):
    rows = _rows(connection, "PRAGMA main.encoding", {}, limits, deadline)
    if len(rows) != 1 or set(rows[0]) != {"encoding"}:
        _fail("catalog_invalid")
    encoding = {"UTF-8": "utf-8", "UTF-16le": "utf-16le", "UTF-16be": "utf-16be"}.get(
        rows[0]["encoding"]
    )
    if encoding is None:
        _fail("catalog_invalid")
    return encoding


def _decode(row, limits, encoding):
    size, value = row["size"], row["value"]
    if type(size) is not int or size < 0 or not isinstance(value, bytes):
        _fail("catalog_invalid")
    if size > limits.ddl_bytes:
        _fail("budget_exceeded")
    if len(value) != size:
        _fail("catalog_invalid")
    return value.decode(encoding, errors="strict")


def _present(connection, limits, deadline, encoding):
    matches = []
    for schema in ("main", "temp"):
        rows = _rows(connection, f"""
            SELECT type, length(CAST(name AS BLOB)) AS size,
                   substr(CAST(name AS BLOB), 1, :cap) AS value
            FROM {schema}.sqlite_master
        """, {"cap": limits.ddl_bytes}, limits, deadline)
        for row in rows:
            name = _decode(row, limits, encoding)
            if _ascii(name) == TABLE:
                matches.append((schema, row["type"], name))
    if not matches:
        return False
    if matches != [("main", "table", TABLE)]:
        _fail("catalog_invalid")
    return True


def _columns(connection, limits, deadline):
    rows = _rows(connection, 'PRAGMA main.table_xinfo("notification_read_states")',
                 {}, limits, deadline)
    fields = {}
    for row in rows:
        name = row.get("name")
        if not isinstance(name, str):
            _fail("catalog_invalid")
        folded = _ascii(name)
        if folded in fields:
            _fail("catalog_invalid")
        fields[folded] = row
    for name in IDENTITIES:
        row = fields.get(name)
        if row is None or row.get("hidden") != 0 or row.get("notnull") != 1:
            _fail("guard_invalid")
        declared = row.get("type")
        if not isinstance(declared, str):
            _fail("guard_invalid")
        declared = _ascii(declared).strip()
        if declared != "text" and not (
            declared == "varchar" or declared.startswith("varchar(")
        ):
            _fail("guard_invalid")


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str


def _tokens(ddl, limits, deadline):
    if not isinstance(ddl, str):
        _fail("syntax_unsupported")
    _check(deadline)
    # Character length is checked before allocating the encoded copy.
    if len(ddl) > limits.ddl_bytes or len(ddl.encode("utf-8")) > limits.ddl_bytes:
        _fail("budget_exceeded")
    output = []
    index = 0
    while index < len(ddl):
        _check(deadline)
        char = ddl[index]
        if char in " \t\r\n\f":
            index += 1
            continue
        if ddl.startswith("--", index):
            index += 2
            while index < len(ddl) and ddl[index] not in "\r\n":
                _check(deadline)
                index += 1
            continue
        if ddl.startswith("/*", index):
            index += 2
            while index + 1 < len(ddl) and ddl[index:index + 2] != "*/":
                _check(deadline)
                index += 1
            if index + 1 >= len(ddl):
                _fail("syntax_unsupported")
            index += 2
            continue
        if char in "'\"`[":
            quote = "]" if char == "[" else char
            kind = "string" if char == "'" else "identifier"
            index += 1
            value = []
            while index < len(ddl):
                _check(deadline)
                if ddl[index] == quote:
                    if char != "[" and index + 1 < len(ddl) and ddl[index + 1] == quote:
                        value.append(quote)
                        index += 2
                        continue
                    index += 1
                    break
                value.append(ddl[index])
                index += 1
            else:
                _fail("syntax_unsupported")
            token = _Token(kind, "".join(value))
        elif char.isascii() and (char.isalpha() or char == "_"):
            start = index
            index += 1
            while index < len(ddl) and ddl[index].isascii() and (
                ddl[index].isalnum() or ddl[index] in "_$"
            ):
                _check(deadline)
                index += 1
            token = _Token("word", ddl[start:index])
        elif char in "0123456789":
            start = index
            index += 1
            while index < len(ddl) and ddl[index] in "0123456789":
                _check(deadline)
                index += 1
            token = _Token("integer", ddl[start:index])
        elif char in "(),.;><=+-*/!|~%":
            token = _Token("symbol", char)
            index += 1
        else:
            _fail("syntax_unsupported")
        if len(output) >= limits.tokens:
            _fail("budget_exceeded")
        output.append(token)
    _check(deadline)
    return output


def _pairs(tokens, limits, deadline):
    stack = []
    pairs = {}
    for index, token in enumerate(tokens):
        _check(deadline)
        if token == _Token("symbol", "("):
            stack.append(index)
            if len(stack) > limits.depth:
                _fail("budget_exceeded")
        elif token == _Token("symbol", ")"):
            if not stack:
                _fail("syntax_unsupported")
            start = stack.pop()
            pairs[start] = index
    if stack:
        _fail("syntax_unsupported")
    return pairs


def _word(token, value):
    return token.kind == "word" and _ascii(token.value) == value


def _identifier(token):
    if token.kind not in {"word", "identifier"}:
        _fail("syntax_unsupported")
    return _ascii(token.value)


def _expression(tokens, pairs, start, end, deadline):
    values = []
    operators = []
    expected = True
    index = start

    def apply():
        if len(values) < 2:
            _fail("guard_invalid")
        right, left = values.pop(), values.pop()
        values.append((operators.pop(), left, right))

    while index < end:
        _check(deadline)
        token = tokens[index]
        if expected:
            if token == _Token("symbol", "("):
                operators.append("(")
                index += 1
                continue
            if token.kind in {"word", "identifier"} and _identifier(token) == "length":
                if index + 1 >= end or tokens[index + 1] != _Token("symbol", "("):
                    _fail("guard_invalid")
                close = pairs[index + 1]
                if close >= end:
                    _fail("guard_invalid")
                left, right = index + 2, close
                while left < right and tokens[left] == _Token("symbol", "(") and pairs[left] == right - 1:
                    _check(deadline)
                    left, right = left + 1, right - 1
                if right - left != 1 or _identifier(tokens[left]) not in IDENTITIES:
                    _fail("guard_invalid")
                values.append(("length", _identifier(tokens[left])))
                index = close + 1
            elif token.kind == "integer" and token.value and all(c == "0" for c in token.value):
                values.append(("zero",))
                index += 1
            else:
                _fail("guard_invalid")
            expected = False
            continue
        if token == _Token("symbol", ")"):
            while operators and operators[-1] != "(":
                apply()
            if not operators:
                _fail("guard_invalid")
            operators.pop()
            index += 1
            continue
        operation = "gt" if token == _Token("symbol", ">") else "and" if _word(token, "and") else None
        if operation is None:
            _fail("guard_invalid")
        priority = {"gt": 2, "and": 1}
        while operators and operators[-1] != "(" and priority[operators[-1]] >= priority[operation]:
            apply()
        operators.append(operation)
        expected = True
        index += 1
    if expected:
        _fail("guard_invalid")
    while operators:
        if operators[-1] == "(":
            _fail("guard_invalid")
        apply()
    if len(values) != 1:
        _fail("guard_invalid")
    pending = [values[0]]
    fields = []
    while pending:
        _check(deadline)
        node = pending.pop()
        if node[0] == "and":
            pending.extend(node[1:])
        elif node[0] == "gt" and node[1][0] == "length" and node[2] == ("zero",):
            fields.append(node[1][1])
        else:
            _fail("guard_invalid")
    if len(fields) != 2 or set(fields) != IDENTITIES:
        _fail("guard_invalid")


def parse_sqlite_notification_identity_ddl(ddl, *, limits=None, deadline=None):
    """Only a narrow DDL syntax proof; does not prove active native bindings."""
    limits = _options(limits, deadline)
    try:
        tokens = _tokens(ddl, limits, deadline)
        pairs = _pairs(tokens, limits, deadline)
        index = 0
        for keyword in ("create", "table"):
            if index >= len(tokens) or not _word(tokens[index], keyword):
                _fail("syntax_unsupported")
            index += 1
        if index < len(tokens) and _word(tokens[index], "if"):
            for keyword in ("if", "not", "exists"):
                if index >= len(tokens) or not _word(tokens[index], keyword):
                    _fail("syntax_unsupported")
                index += 1
        if index >= len(tokens):
            _fail("syntax_unsupported")
        name = _identifier(tokens[index])
        index += 1
        if index < len(tokens) and tokens[index] == _Token("symbol", "."):
            if name != "main" or index + 1 >= len(tokens):
                _fail("syntax_unsupported")
            name = _identifier(tokens[index + 1])
            index += 2
        if name != TABLE or index >= len(tokens) or tokens[index] != _Token("symbol", "("):
            _fail("syntax_unsupported")
        end = pairs[index]
        tail = tokens[end + 1:]
        if tail not in ([], [_Token("symbol", ";")]):
            _fail("syntax_unsupported")
        segments = []
        start = index + 1
        index = start
        while index < end:
            _check(deadline)
            if tokens[index] == _Token("symbol", "("):
                index = pairs[index] + 1
            elif tokens[index] == _Token("symbol", ","):
                segments.append((start, index))
                start = index + 1
                index += 1
            else:
                index += 1
        segments.append((start, end))
        guards = []
        for start, end in segments:
            _check(deadline)
            if start == end:
                _fail("syntax_unsupported")
            if not _word(tokens[start], "constraint"):
                continue
            if start + 1 >= end:
                _fail("syntax_unsupported")
            if _identifier(tokens[start + 1]) != GUARD:
                continue
            if (start + 3 >= end or not _word(tokens[start + 2], "check")
                    or tokens[start + 3] != _Token("symbol", "(")
                    or pairs[start + 3] != end - 1):
                _fail("guard_invalid")
            guards.append((start + 4, end - 1))
        if not guards:
            _fail("guard_missing")
        if len(guards) != 1:
            _fail("guard_invalid")
        _expression(tokens, pairs, *guards[0], deadline)
        _check(deadline)
    except SQLiteInboxCheckError:
        raise
    except Exception:
        _fail("syntax_unsupported")


def validate_sqlite_notification_identity_check(connection, *, limits=None, deadline=None) -> bool:
    """Check the actual main table and connection, without changing either."""
    limits = _options(limits, deadline)
    try:
        _functions(connection, limits, deadline)
        encoding = _encoding(connection, limits, deadline)
        if not _present(connection, limits, deadline, encoding):
            return False
        _enabled(connection, limits, deadline)
        _columns(connection, limits, deadline)
        rows = _rows(connection, """
            SELECT length(CAST(sql AS BLOB)) AS size,
                   substr(CAST(sql AS BLOB), 1, :cap) AS value
            FROM main.sqlite_master WHERE type='table' AND name=:name
        """, {"name": TABLE, "cap": limits.ddl_bytes}, limits, deadline)
        if len(rows) != 1:
            _fail("catalog_invalid")
        ddl = _decode(rows[0], limits, encoding)
        parse_sqlite_notification_identity_ddl(ddl, limits=limits, deadline=deadline)
        _enabled(connection, limits, deadline)
        _functions(connection, limits, deadline)
        _check(deadline)
        return True
    except SQLiteInboxCheckError:
        raise
    except Exception:
        _fail("catalog_invalid")
