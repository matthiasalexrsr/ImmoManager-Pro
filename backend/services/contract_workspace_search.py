"""Identical Unicode casefold search on SQLite, PostgreSQL and Memory.

SQLite's builtin lower()/NOCASE and database locale rules are insufficient.
The PostgreSQL expression uses the same Python Unicode mapping as the SQLite
connection-local function: translate single characters, then expand ligatures.
All mapping/search values are bind parameters; no DDL or stored-data rewrite.
"""

import sqlite3
from functools import lru_cache

from sqlalchemy import String, bindparam
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.visitors import InternalTraversal


@lru_cache(maxsize=1)
def casefold_mapping() -> tuple[str, str, tuple[tuple[str, str], ...]]:
    single_source, single_target, expansions = [], [], []
    for point in range(0x110000):
        original = chr(point)
        folded = original.casefold()
        if original == folded:
            continue
        if len(folded) == 1:
            single_source.append(original)
            single_target.append(folded)
        else:
            expansions.append((original, folded))
    # Casefold is idempotent. No expansion can introduce a character that a
    # later replacement would fold again, so iterative SQL replacement is exact.
    return "".join(single_source), "".join(single_target), tuple(expansions)


class UnicodeCasefold(ColumnElement[str]):
    type = String()
    inherit_cache = False
    _traverse_internals = [("column", InternalTraversal.dp_clauseelement)]

    def __init__(self, column):
        self.column = column

    @property
    def _from_objects(self):
        return self.column._from_objects


@compiles(UnicodeCasefold)
@compiles(UnicodeCasefold, "sqlite")
def sqlite_casefold(element, compiler, **kwargs):
    # The default rendering also lets SQLAlchemy inspect final FROM clauses
    # for the central scope middleware, before dialect-specific execution.
    return "immo_contract_casefold(" + compiler.process(element.column, **kwargs) + ")"


@compiles(UnicodeCasefold, "postgresql")
def postgres_casefold(element, compiler, **kwargs):
    single_source, single_target, expansions = casefold_mapping()

    def parameter(value: str) -> str:
        return compiler.process(bindparam(None, value, type_=String()), **kwargs)

    # Build SQL iteratively: a deeply nested SQLAlchemy function tree would
    # needlessly consume the Python compiler's recursion budget.
    expression = (
        "translate("
        + compiler.process(element.column, **kwargs)
        + ", "
        + parameter(single_source)
        + ", "
        + parameter(single_target)
        + ")"
    )
    for original, folded in expansions:
        expression = "replace(" + expression + ", " + parameter(original) + ", " + parameter(folded) + ")"
    return expression


def ensure_sqlite_casefold(session) -> None:
    """Register only our pure function on a borrowed live driver connection.

    Do not close/commit the connection, change builtin lower or issue SQL.
    Safe to call for each searched page, including already pooled connections.
    """
    if session.get_bind().dialect.name != "sqlite":
        return
    driver = session.connection().connection.driver_connection
    if not isinstance(driver, sqlite3.Connection):
        raise RuntimeError("Contract workspace search requires the SQLite synchronous driver")
    driver.create_function(
        "immo_contract_casefold", 1, lambda value: value.casefold() if value is not None else None, deterministic=True
    )
