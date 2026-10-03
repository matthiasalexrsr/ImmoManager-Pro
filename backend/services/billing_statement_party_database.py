"""Read-only complete native party-original proof, including periods without cases."""

import sqlite3
from collections.abc import Mapping
from contextlib import closing
from functools import lru_cache

from sqlalchemy import func, inspect, select

from ..db.orm_models import Base
from .billing_dispute_database import _check, _period_hash, _read, _typed
from .billing_dispute_validation import DisputeIntegrityError
from .billing_originals import IMMUTABLE
from .billing_statement_document_contexts import (
    DocumentContextIntegrityError,
    document_context_family,
    validate_period_document_contexts,
)
from .billing_statement_parties import (
    StatementPartyIntegrityError,
    family,
    validate_period_statement_parties,
)
from .measurement_history_database import _rows
from .measurement_history_validation import MeasurementIntegrityError


class _NativeParents(Mapping):
    """Actual rows on demand; the cache budget never limits available identities."""

    def __init__(self, connection, table, deadline, verify_source):
        self.connection, self.table, self.deadline = connection, table, deadline

        @lru_cache(maxsize=128)
        def lookup(identifier):
            row = next(_read(connection, table, table.c.id == identifier, deadline=deadline), None)
            if row is None:
                raise KeyError(identifier)
            if table.name == "utility_statements":
                verify_source(row)
            return row

        self.lookup = lookup

    def __getitem__(self, identifier):
        _check(self.deadline)
        return self.lookup(identifier)

    def __iter__(self):
        for row in _rows(self.connection, select(self.table.c.id).order_by(self.table.c.id), deadline=self.deadline):
            yield row["id"]

    def __len__(self):
        row = next(_rows(self.connection, select(func.count()).select_from(self.table), deadline=self.deadline))
        return next(iter(row.values()))


class _NativeHashes(Mapping):
    """Internal complete native period digests; no request cache accepted."""

    def __init__(self, lookup):
        self.lookup = lookup

    def __getitem__(self, identifier):
        return self.lookup(identifier)

    def __iter__(self):
        raise TypeError("Original hashes are actual targeted period lookups")

    def __len__(self):
        raise TypeError("Original hashes are actual targeted period lookups")


def validate_statement_party_database(connection, *, deadline=None) -> bool:
    """Prove every present family; caller owns a consistent offline transaction."""
    try:
        _check(deadline)
        if isinstance(connection, sqlite3.Connection):
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        else:
            names = set(inspect(connection).get_table_names())
        required = {"billing_periods", "utility_statements"}
        if not names & required:
            return False
        if not required <= names:
            raise StatementPartyIntegrityError("Die ursprünglichen Abrechnungstabellen sind unvollständig.")
        periods, statements = (Base.metadata.tables[name] for name in ("billing_periods", "utility_statements"))

        @lru_cache(maxsize=32)
        def period(identifier):
            row = next(_read(connection, periods, periods.c.id == identifier, deadline=deadline), None)
            if row is None:
                raise StatementPartyIntegrityError("Die ursprüngliche Abrechnungsperiode fehlt.")
            return row

        @lru_cache(maxsize=32)
        def original_hash(identifier):
            return _period_hash(connection, period(identifier), deadline=deadline)

        def verify_source(row):
            source = period(row["billing_period_id"])
            if (row["status"] not in IMMUTABLE or source["status"] not in IMMUTABLE
                    or row["snapshot_hash"] != original_hash(source["id"])):
                raise StatementPartyIntegrityError("Die verknüpfte Quellenfassung besitzt keinen gültigen Originalhash.")

        parents = {name: _NativeParents(connection, Base.metadata.tables[name], deadline, verify_source)
                   for name in ("properties", "units", "contracts", "tenants", "portfolios", "utility_statements", "billing_periods")}
        hashes = _NativeHashes(original_hash)

        def source_rows(identifier):
            with closing(_read(connection, statements, statements.c.billing_period_id == identifier, deadline=deadline)) as stream:
                yield from stream

        after, found = None, False
        while True:
            query = select(periods).order_by(periods.c.id).limit(100)
            if after is not None:
                query = query.where(periods.c.id > after)
            # Keep the native keyset/limit in the actual executed statement.
            page = [_typed(row, periods, isinstance(connection, sqlite3.Connection))
                    for row in _rows(connection, query, deadline=deadline)]
            if not page:
                break
            for row in page:
                contexts = document_context_family(row)
                if family(row) is None and contexts is None:
                    continue
                found = True
                digest = original_hash(row["id"])
                with closing(_read(connection, statements, statements.c.billing_period_id == row["id"], deadline=deadline)) as stream:
                    if contexts is None:
                        validate_period_statement_parties(row, stream, parents=parents, verified_period_hash=digest)
                    else:
                        validate_period_document_contexts(row, stream, parents=parents,
                            verified_period_hashes=hashes, statements_for_period=source_rows)
            after = page[-1]["id"]
        _check(deadline)
        return found
    except StatementPartyIntegrityError:
        raise
    except DocumentContextIntegrityError:
        raise StatementPartyIntegrityError("Dokumentkontextoriginale sind beschädigt; vollständige unveränderte Sicherung erneut prüfen.") from None
    except (ValueError, TypeError, KeyError, DisputeIntegrityError, MeasurementIntegrityError):
        raise StatementPartyIntegrityError("Originalparteien sind beschädigt oder das Prüfbudget ist erschöpft; vollständige unveränderte Sicherung erneut prüfen.") from None
