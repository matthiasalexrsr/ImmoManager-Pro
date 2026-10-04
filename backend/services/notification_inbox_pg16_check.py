"""Narrow PG16 native identity-CHECK proof; caller owns catalog snapshot."""

from dataclasses import dataclass
from math import isfinite
from time import monotonic
from typing import Any, NoReturn

from sqlalchemy import text
from sqlalchemy.engine import Connection

TABLE = "notification_read_states"
GUARD = "ck_notification_read_identity"
IDENTITIES = frozenset({"actor_id", "notification_id"})


class PG16InboxCheckError(ValueError):
    """Only fixed codes, without SQL, identities or driver values."""


def _fail(suffix) -> NoReturn:
    raise PG16InboxCheckError(f"notification_inbox_pg16_check_{suffix}")


@dataclass(frozen=True)
class PG16InboxCheckLimits:
    tree_bytes: int = 65536
    tokens: int = 8192
    depth: int = 64
    catalog_rows: int = 64

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in (
            self.tree_bytes, self.tokens, self.depth, self.catalog_rows
        )):
            _fail("limits_invalid")


@dataclass(frozen=True)
class PG16IdentityColumn:
    """Parser input only. A caller-created DTO is not native catalog proof."""

    name: str
    attnum: int
    typmod: int
    collation: int


def _check(deadline):
    if deadline is not None and monotonic() >= deadline:
        _fail("timeout")


def _options(limits, deadline):
    if limits is None:
        limits = PG16InboxCheckLimits()
    if type(limits) is not PG16InboxCheckLimits:
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


def _rows(connection, sql, parameters, limits, deadline):
    _check(deadline)
    result: Any = None
    try:
        result = connection.execute(text(sql), parameters).mappings()
        rows = []
        while batch := result.fetchmany(min(32, limits.catalog_rows + 1)):
            for row in batch:
                _check(deadline)
                if len(rows) >= limits.catalog_rows:
                    _fail("budget_exceeded")
                rows.append(dict(row))
        _check(deadline)
        return rows
    finally:
        if result is not None:
            result.close()


def _one(connection, sql, parameters, limits, deadline):
    rows = _rows(connection, sql, parameters, limits, deadline)
    if len(rows) != 1:
        _fail("catalog_invalid")
    return rows[0]


def _integer(value):
    if (not isinstance(value, str) or not value or len(value) > 11
            or any(char not in "0123456789" for char in value.lstrip("-"))
            or value.startswith("--") or value == "-"):
        _fail("tree_unsupported")
    parsed = int(value)
    if not -(2 ** 31) <= parsed <= 2 ** 32 - 1:
        _fail("tree_unsupported")
    return parsed


def _lex(tree, limits, deadline):
    if not isinstance(tree, str):
        _fail("tree_unsupported")
    _check(deadline)
    if len(tree) > limits.tree_bytes or len(tree.encode("utf-8")) > limits.tree_bytes:
        _fail("budget_exceeded")
    tokens = []
    index = 0
    while index < len(tree):
        _check(deadline)
        char = tree[index]
        if char in " \t\r\n":
            index += 1
            continue
        if char in "{}()[]":
            token = char
            index += 1
        else:
            start = index
            if char == ":":
                index += 1
            while index < len(tree) and tree[index].isascii() and (
                tree[index].isalnum() or tree[index] in "_-"
            ):
                _check(deadline)
                index += 1
            if index == start or (char == ":" and index == start + 1):
                _fail("tree_unsupported")
            token = tree[start:index]
        if len(tokens) >= limits.tokens:
            _fail("budget_exceeded")
        tokens.append(token)
    _check(deadline)
    return tokens


def _parse(tree, limits, deadline):
    tokens = _lex(tree, limits, deadline)
    stack: list[dict[str, Any]] = []
    root: list[Any] = []
    index = 0

    def attach(value):
        if not stack:
            root.append(value)
        elif stack[-1]["kind"] == "node":
            frame = stack[-1]
            key = frame["pending"]
            if key is None:
                _fail("tree_unsupported")
            frame["value"][key] = value
            frame["pending"] = None
        else:
            stack[-1]["value"].append(value)

    while index < len(tokens):
        _check(deadline)
        token = tokens[index]
        if stack and stack[-1]["kind"] == "node":
            frame = stack[-1]
            if frame["tag"] is None:
                if not token.isascii() or not token.isalpha() or not token.isupper():
                    _fail("tree_unsupported")
                frame["tag"] = token
                frame["value"]["tag"] = token
                index += 1
                continue
            if frame["pending"] is None and token != "}":
                if not token.startswith(":") or token[1:] in frame["value"]:
                    _fail("tree_unsupported")
                frame["pending"] = token[1:]
                index += 1
                continue
            if frame["pending"] == "constvalue":
                width = _integer(token)
                if index + 1 >= len(tokens) or tokens[index + 1] != "[":
                    _fail("tree_unsupported")
                stack.append({"kind": "bytes", "value": [], "width": width})
                index += 2
                if len(stack) > limits.depth:
                    _fail("budget_exceeded")
                continue
        if token in ("{", "("):
            if token == "{":
                frame = {"kind": "node", "tag": None, "pending": None, "value": {}}
            else:
                frame = {"kind": "list", "value": []}
            stack.append(frame)
            if len(stack) > limits.depth:
                _fail("budget_exceeded")
            index += 1
            continue
        if token in ("}", ")", "]"):
            if not stack:
                _fail("tree_unsupported")
            frame = stack.pop()
            expected = {"node": "}", "list": ")", "bytes": "]"}[frame["kind"]]
            if token != expected or (frame["kind"] == "node" and (
                frame["tag"] is None or frame["pending"] is not None
            )):
                _fail("tree_unsupported")
            value = frame["value"]
            if frame["kind"] == "bytes":
                value = {"width": frame["width"], "bytes": value}
            attach(value)
            index += 1
            continue
        if token.startswith(":") or token == "[":
            _fail("tree_unsupported")
        attach(token)
        index += 1
    if stack or len(root) != 1 or not isinstance(root[0], dict):
        _fail("tree_unsupported")
    _check(deadline)
    return root[0]


def _node(node, tag, fields):
    if not isinstance(node, dict) or node.get("tag") != tag or set(node) != {"tag", *fields, "location"}:
        _fail("tree_unsupported")
    _integer(node["location"])


def _equals(node, expected):
    for key, value in expected.items():
        if node.get(key) != str(value):
            _fail("guard_invalid")


def _column_proof(node, column):
    _node(node, "VAR", {"varno", "varattno", "vartype", "vartypmod", "varcollid",
          "varnullingrels", "varlevelsup", "varnosyn", "varattnosyn"})
    _equals(node, {"varno": 1, "varattno": column.attnum, "vartype": 1043,
                  "vartypmod": column.typmod, "varcollid": column.collation,
                  "varlevelsup": 0, "varnosyn": 1, "varattnosyn": column.attnum})
    if node["varnullingrels"] != ["b"]:
        _fail("guard_invalid")


def _leaf(node, by_attnum):
    _node(node, "OPEXPR", {"opno", "opfuncid", "opresulttype", "opretset", "opcollid", "inputcollid", "args"})
    _equals(node, {"opno": 521, "opfuncid": 147, "opresulttype": 16,
                  "opretset": "false", "opcollid": 0, "inputcollid": 0})
    arguments = node["args"]
    if not isinstance(arguments, list) or len(arguments) != 2:
        _fail("guard_invalid")
    function, constant = arguments
    _node(constant, "CONST", {"consttype", "consttypmod", "constcollid", "constlen", "constbyval", "constisnull", "constvalue"})
    _equals(constant, {"consttype": 23, "consttypmod": -1, "constcollid": 0,
                       "constlen": 4, "constbyval": "true", "constisnull": "false"})
    if constant["constvalue"] != {"width": 4, "bytes": ["0"] * 8}:
        _fail("guard_invalid")
    _node(function, "FUNCEXPR", {"funcid", "funcresulttype", "funcretset", "funcvariadic", "funcformat", "funccollid", "inputcollid", "args"})
    _equals(function, {"funcid": 1317, "funcresulttype": 23, "funcretset": "false",
                       "funcvariadic": "false", "funcformat": 0, "funccollid": 0})
    if not isinstance(function["args"], list) or len(function["args"]) != 1:
        _fail("guard_invalid")
    relabel = function["args"][0]
    _node(relabel, "RELABELTYPE", {"arg", "resulttype", "resulttypmod", "resultcollid", "relabelformat"})
    _equals(relabel, {"resulttype": 25, "resulttypmod": -1, "relabelformat": 2})
    variable = relabel["arg"]
    if not isinstance(variable, dict):
        _fail("guard_invalid")
    column = by_attnum.get(_integer(variable.get("varattno")))
    if column is None:
        _fail("guard_invalid")
    _equals(function, {"inputcollid": column.collation})
    _equals(relabel, {"resultcollid": column.collation})
    _column_proof(variable, column)
    return column.name


def parse_pg16_notification_identity_tree(tree, columns, *, limits=None, deadline=None):
    """Pure syntax/semantic proof only; columns DTOs alone confer no authority."""
    limits = _options(limits, deadline)
    try:
        if (not isinstance(columns, tuple) or len(columns) != 2
                or any(type(column) is not PG16IdentityColumn for column in columns)
                or {column.name for column in columns} != IDENTITIES
                or any(type(column.attnum) is not int or not 0 < column.attnum < 32768
                       or type(column.typmod) is not int or column.typmod < -1
                       or type(column.collation) is not int or column.collation <= 0
                       for column in columns)
                or len({column.attnum for column in columns}) != 2):
            _fail("catalog_invalid")
        root = _parse(tree, limits, deadline)
        _node(root, "BOOLEXPR", {"boolop", "args"})
        if root["boolop"] != "and" or not isinstance(root["args"], list) or len(root["args"]) != 2:
            _fail("guard_invalid")
        fields = [_leaf(node, {column.attnum: column for column in columns}) for node in root["args"]]
        if len(fields) != 2 or set(fields) != IDENTITIES:
            _fail("guard_invalid")
        _check(deadline)
    except PG16InboxCheckError:
        raise
    except Exception:
        _fail("tree_unsupported")


def _context(connection, limits, deadline):
    context = _one(connection, """
        SELECT pg_catalog.current_setting('server_version_num') AS version,
               pg_catalog.current_schema() AS schema_name,
               pg_catalog.to_regnamespace(pg_catalog.current_schema())::oid AS namespace_oid,
               pg_catalog.to_regclass('notification_read_states')::oid AS visible_oid
    """, {}, limits, deadline)
    version = context["version"]
    if not isinstance(version, str) or not version.isascii() or not version.isdigit() or len(version) != 6 or int(version) // 10000 != 16:
        _fail("version_unsupported")
    schema = context["schema_name"]
    if (not isinstance(schema, str) or schema in {"pg_catalog", "information_schema"}
            or schema.startswith("pg_temp_") or schema.startswith("pg_toast")
            or type(context["namespace_oid"]) is not int):
        _fail("catalog_invalid")
    rows = _rows(connection, """
        SELECT c.oid, c.relnamespace, c.relkind, c.relpersistence, c.relispartition,
               EXISTS(SELECT 1 FROM pg_catalog.pg_inherits i
                      WHERE i.inhrelid=c.oid OR i.inhparent=c.oid) AS inherited
        FROM pg_catalog.pg_class c
        WHERE c.relnamespace=:namespace AND c.relname=:table
    """, {"namespace": context["namespace_oid"], "table": TABLE}, limits, deadline)
    if not rows and context["visible_oid"] is None:
        return None
    if len(rows) != 1:
        _fail("catalog_invalid")
    relation = rows[0]
    if (relation["oid"] != context["visible_oid"] or relation["relkind"] != "r"
            or relation["relpersistence"] not in {"p", "u"} or relation["relispartition"] is not False
            or relation["inherited"] is not False):
        _fail("catalog_invalid")
    return relation


def _columns(connection, relation, limits, deadline):
    rows = _rows(connection, """
        SELECT attname, attnum, atttypid, atttypmod, attcollation, attnotnull,
               attisdropped, attgenerated, attidentity
        FROM pg_catalog.pg_attribute
        WHERE attrelid=:relation AND attname IN ('actor_id','notification_id')
    """, {"relation": relation["oid"]}, limits, deadline)
    if len(rows) != 2 or {row["attname"] for row in rows} != IDENTITIES:
        _fail("catalog_invalid")
    columns: list[PG16IdentityColumn] = []
    for row in rows:
        if (row["atttypid"] != 1043 or row["attnotnull"] is not True
                or row["attisdropped"] is not False or row["attgenerated"] != ""
                or row["attidentity"] != ""):
            _fail("catalog_invalid")
        columns.append(PG16IdentityColumn(row["attname"], row["attnum"], row["atttypmod"], row["attcollation"]))
    return tuple(columns)


def _native_semantics(connection, limits, deadline):
    functions = _rows(connection, """
        SELECT p.oid, n.nspname AS namespace, p.proname, p.proargtypes::oid[] AS arguments,
               p.prorettype, p.provolatile, p.proisstrict, p.proretset, p.prokind,
               p.prosecdef, p.proconfig IS NULL AS no_config, l.lanname AS language,
               pg_catalog.octet_length(p.prosrc) AS source_size,
               pg_catalog.substr(p.prosrc,1,64) AS source
        FROM pg_catalog.pg_proc p
        JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
        JOIN pg_catalog.pg_language l ON l.oid=p.prolang
        WHERE p.oid IN (1317,147)
    """, {}, limits, deadline)
    if len(functions) != 2 or {row["oid"] for row in functions} != {1317, 147}:
        _fail("catalog_invalid")
    expected = {1317: ("length", [25], 23, "textlen"), 147: ("int4gt", [23, 23], 16, "int4gt")}
    for row in functions:
        name, arguments, result, source = expected[row["oid"]]
        if (row["namespace"] != "pg_catalog" or row["proname"] != name
                or list(row["arguments"]) != arguments or row["prorettype"] != result
                or row["provolatile"] != "i" or row["proisstrict"] is not True
                or row["proretset"] is not False or row["prokind"] != "f"
                or row["prosecdef"] is not False or row["no_config"] is not True
                or row["language"] != "internal" or row["source"] != source
                or row["source_size"] != len(source)):
            _fail("catalog_invalid")
    operator = _one(connection, """
        SELECT o.oid, n.nspname AS namespace, o.oprname, o.oprkind, o.oprleft,
               o.oprright, o.oprresult, o.oprcode::oid AS function_oid
        FROM pg_catalog.pg_operator o JOIN pg_catalog.pg_namespace n ON n.oid=o.oprnamespace
        WHERE o.oid=521
    """, {}, limits, deadline)
    if operator != {"oid": 521, "namespace": "pg_catalog", "oprname": ">", "oprkind": "b",
                    "oprleft": 23, "oprright": 23, "oprresult": 16, "function_oid": 147}:
        _fail("catalog_invalid")
    types = _rows(connection, """
        SELECT t.oid, n.nspname AS namespace, t.typname, t.typtype, t.typlen, t.typbyval
        FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
        WHERE t.oid IN (16,23,25,1043)
    """, {}, limits, deadline)
    expected_types = {16: ("bool", 1, True), 23: ("int4", 4, True),
                      25: ("text", -1, False), 1043: ("varchar", -1, False)}
    if len(types) != 4 or {row["oid"] for row in types} != set(expected_types):
        _fail("catalog_invalid")
    for row in types:
        name, length, by_value = expected_types[row["oid"]]
        if (row["namespace"] != "pg_catalog" or row["typname"] != name or row["typtype"] != "b"
                or row["typlen"] != length or row["typbyval"] is not by_value):
            _fail("catalog_invalid")
    cast = _one(connection, """
        SELECT castfunc::oid AS function_oid, castcontext, castmethod
        FROM pg_catalog.pg_cast WHERE castsource=1043 AND casttarget=25
    """, {}, limits, deadline)
    if cast != {"function_oid": 0, "castcontext": "i", "castmethod": "b"}:
        _fail("catalog_invalid")


def _constraint(connection, relation, columns, limits, deadline):
    catalog = _one(connection, """
        SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_attribute
                      WHERE attrelid='pg_catalog.pg_constraint'::pg_catalog.regclass
                        AND attname='conenforced' AND NOT attisdropped) AS has_enforced
    """, {}, limits, deadline)
    if type(catalog["has_enforced"]) is not bool:
        _fail("catalog_invalid")
    enforced = "c.conenforced" if catalog["has_enforced"] else "TRUE"
    rows = _rows(connection, f"""
        SELECT c.conrelid, c.connamespace, c.convalidated, c.conislocal,
               c.coninhcount, c.connoinherit, c.condeferrable, c.condeferred,
               c.contypid, c.confrelid, c.conkey, {enforced} AS enforced,
               pg_catalog.octet_length(pg_catalog.convert_to(c.conbin::text,'UTF8')) AS size,
               pg_catalog.substring(pg_catalog.convert_to(c.conbin::text,'UTF8'),1,:cap) AS tree
        FROM pg_catalog.pg_constraint c
        WHERE c.conrelid=:relation AND c.contype='c' AND c.conname=:guard
    """, {"relation": relation["oid"], "guard": GUARD, "cap": limits.tree_bytes}, limits, deadline)
    if not rows:
        _fail("guard_missing")
    if len(rows) != 1:
        _fail("guard_invalid")
    return _checked_constraint_tree(rows[0], relation, columns, limits, deadline)


def _checked_constraint_tree(row, relation, columns, limits, deadline):
    """Pure record check; only the real catalog reader can supply native proof."""
    _check(deadline)
    if (row["conrelid"] != relation["oid"] or row["connamespace"] != relation["relnamespace"]
            or row["convalidated"] is not True or row["enforced"] is not True
            or row["conislocal"] is not True or row["coninhcount"] != 0
            or row["connoinherit"] is not False or row["condeferrable"] is not False
            or row["condeferred"] is not False or row["contypid"] != 0 or row["confrelid"] != 0
            or not isinstance(row["conkey"], list) or len(row["conkey"]) != 2
            or set(row["conkey"]) != {column.attnum for column in columns}):
        _fail("guard_invalid")
    size, tree = row["size"], row["tree"]
    if type(size) is not int or size < 0 or not isinstance(tree, (bytes, bytearray, memoryview)):
        _fail("catalog_invalid")
    if size > limits.tree_bytes:
        _fail("budget_exceeded")
    if len(tree) != size:
        _fail("catalog_invalid")
    decoded = bytes(tree).decode("utf-8", errors="strict")
    _check(deadline)
    return decoded


def validate_pg16_notification_identity_check(connection, *, limits=None, deadline=None) -> bool:
    """Read actual catalog bindings plus bounded native conbin on this connection."""
    limits = _options(limits, deadline)
    try:
        if not isinstance(connection, Connection) or connection.dialect.name != "postgresql":
            _fail("catalog_invalid")
        relation = _context(connection, limits, deadline)
        if relation is None:
            return False
        columns = _columns(connection, relation, limits, deadline)
        _native_semantics(connection, limits, deadline)
        tree = _constraint(connection, relation, columns, limits, deadline)
        parse_pg16_notification_identity_tree(tree, columns, limits=limits, deadline=deadline)
        _check(deadline)
        return True
    except PG16InboxCheckError:
        raise
    except Exception:
        _fail("catalog_invalid")
