"""Exact source cents and connection-local SQL sums; no stored-data changes."""

import re
import sqlite3
from decimal import Decimal, InvalidOperation

from sqlalchemy import BigInteger, Boolean, Numeric, String, literal
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

MAX_SOURCE = Decimal("9999999999.99")
CENT_TEXT = re.compile(r"(?:0|[1-9][0-9]*)\Z")
AGGREGATE = "immo_property_exact_cent_sum"
WHITESPACE = "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"


def source_cents(value):
    """None is missing; every malformed source is invalid, never rounded."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("invalid_property_rent")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid_property_rent") from None
    if not amount.is_finite() or amount < 0 or amount > MAX_SOURCE:
        raise ValueError("invalid_property_rent")
    if amount == 0:
        return 0
    _, digits, exponent = amount.as_tuple()
    coefficient = "".join(map(str, digits))
    shift = exponent + 2
    if shift < 0:
        if -shift > len(coefficient) - len(coefficient.rstrip("0")):
            raise ValueError("invalid_property_rent")
        coefficient, shift = coefficient[:shift], 0
    return int(coefficient or "0") * 10**shift


def cent_text(value):
    if type(value) is int:
        if value < 0:
            raise ValueError("invalid_property_cent_sum")
        return str(value)
    if isinstance(value, str) and CENT_TEXT.fullmatch(value):
        return value
    raise ValueError("invalid_property_cent_sum")


def money_text(value):
    cents = cent_text(value).rjust(3, "0")
    return cents[:-2] + "." + cents[-2:]


def currency_label(value):
    return value if isinstance(value, str) and value.strip(WHITESPACE) else None


class ExactCentAccumulator:
    """SQLite Integer inputs, arbitrary-size Python sum, exact Text output."""

    def __init__(self):
        self.total = 0

    def step(self, value):
        if value is None:
            return
        if type(value) is not int or value < 0:
            raise ValueError("invalid_property_cent_input")
        self.total += value

    def finalize(self):
        return cent_text(self.total)


def install_exact_sum(session, *, connection=None):
    """Only the actual borrowed connection; no engine-global event or SQL."""
    actual = session.connection()
    if connection is not None and actual is not connection:
        raise RuntimeError("property_inventory_connection_mismatch")
    if actual.dialect.name == "sqlite":
        driver = actual.connection.driver_connection
        if not isinstance(driver, sqlite3.Connection):
            raise RuntimeError("property_inventory_sqlite_driver_required")
        driver.create_aggregate(AGGREGATE, 1, ExactCentAccumulator)
        driver.create_function("immo_property_currency_label", 1, currency_label, deterministic=True)
    elif actual.dialect.name != "postgresql":
        raise RuntimeError("property_inventory_dialect_unsupported")


class SourceMoneyValid(FunctionElement):
    type = Boolean()
    inherit_cache = False


def _valid(column, *, sqlite):
    numeric = f"typeof({column}) IN ('integer','real') AND " if sqlite else ""
    return (f"({numeric}{column} IS NOT NULL AND {column} >= 0 AND "
            f"{column} <= 9999999999.99 AND {column} = round({column},2))")


@compiles(SourceMoneyValid, "sqlite")
def sqlite_valid(element, compiler, **kwargs):
    return _valid(compiler.process(list(element.clauses)[0], **kwargs), sqlite=True)


@compiles(SourceMoneyValid)
@compiles(SourceMoneyValid, "postgresql")
def postgres_valid(element, compiler, **kwargs):
    return _valid(compiler.process(list(element.clauses)[0], **kwargs), sqlite=False)


class SourceCents(FunctionElement):
    type = BigInteger()
    inherit_cache = False


@compiles(SourceCents, "sqlite")
def sqlite_cents(element, compiler, **kwargs):
    column = compiler.process(list(element.clauses)[0], **kwargs)
    return f"(CASE WHEN {_valid(column, sqlite=True)} THEN CAST(round({column}*100,0) AS BIGINT) ELSE NULL END)"


@compiles(SourceCents)
@compiles(SourceCents, "postgresql")
def postgres_cents(element, compiler, **kwargs):
    column = compiler.process(list(element.clauses)[0], **kwargs)
    return f"(CASE WHEN {_valid(column, sqlite=False)} THEN CAST({column}*100 AS BIGINT) ELSE NULL END)"


class ExactCentSum(FunctionElement):
    # Both dialects return canonical text, PG SUM(bigint) remains native Numeric.
    type = String()
    inherit_cache = False


@compiles(ExactCentSum, "sqlite")
def sqlite_sum(element, compiler, **kwargs):
    value = compiler.process(list(element.clauses)[0], **kwargs)
    return f"COALESCE({AGGREGATE}({value}),'0')"


@compiles(ExactCentSum)
@compiles(ExactCentSum, "postgresql")
def postgres_sum(element, compiler, **kwargs):
    value = compiler.process(list(element.clauses)[0], **kwargs)
    return f"CAST(COALESCE(SUM({value}),0) AS TEXT)"


class CurrencyLabel(FunctionElement):
    type = String()
    inherit_cache = False


@compiles(CurrencyLabel, "sqlite")
def sqlite_currency(element, compiler, **kwargs):
    value = compiler.process(list(element.clauses)[0], **kwargs)
    return f"immo_property_currency_label({value})"


@compiles(CurrencyLabel)
@compiles(CurrencyLabel, "postgresql")
def postgres_currency(element, compiler, **kwargs):
    value = compiler.process(list(element.clauses)[0], **kwargs)
    spaces = compiler.process(literal(WHITESPACE, type_=String()), **kwargs)
    return f"(CASE WHEN NULLIF(translate({value},{spaces},''),'') IS NULL THEN NULL ELSE {value} END)"


class CentRank(FunctionElement):
    """SQLite text magnitude, native PG Numeric; never an Int64 total."""

    type = Numeric()
    inherit_cache = False


@compiles(CentRank, "sqlite")
def sqlite_rank(element, compiler, **kwargs):
    return "length(" + compiler.process(list(element.clauses)[0], **kwargs) + ")"


@compiles(CentRank)
@compiles(CentRank, "postgresql")
def postgres_rank(element, compiler, **kwargs):
    return "CAST(" + compiler.process(list(element.clauses)[0], **kwargs) + " AS NUMERIC)"
