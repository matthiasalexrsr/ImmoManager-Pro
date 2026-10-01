"""Same bytewise ID tiebreak for SQLite, PostgreSQL and the Python reference.

The ChatGPT assistant's reviewed keyset draft explicitly used BINARY / C
collation. Keep that property in both the query and its index, independent of
the database's configured locale.
"""
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, CollationClause


class _BytewiseCollation(CollationClause):
    inherit_cache = True


@compiles(_BytewiseCollation, "sqlite")
def sqlite_collation(element, compiler, **kwargs):
    return '"BINARY"'


@compiles(_BytewiseCollation, "postgresql")
def postgres_collation(element, compiler, **kwargs):
    return '"C"'


def bytewise_id(column):
    return BinaryExpression(column, _BytewiseCollation("immo_bytewise"), operators.collate, type_=column.type)
