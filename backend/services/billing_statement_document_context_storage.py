"""Caller-owned actual context capture/readers; no commit or ambient issuer."""

from collections.abc import Mapping
from datetime import datetime, timezone
from functools import lru_cache

from .billing_statement_document_contexts import (
    DocumentContextIntegrityError,
    ReviewedIssuer,
    capture_document_contexts,
    document_context_family,
    validate_period_document_contexts,
)


def capture_actor(actor_id: str | None = None) -> str | None:
    """Scope actor, or an explicitly approved internal caller argument only."""
    from .portfolio_scope import current_scope

    captured = current_scope()
    if actor_id is not None and (not isinstance(actor_id, str) or not actor_id.strip()):
        raise DocumentContextIntegrityError("Dokumentkontext benötigt eine tatsächliche Benutzerbindung.")
    if captured is not None:
        if actor_id is not None and actor_id != captured.user_id:
            raise DocumentContextIntegrityError("Dokumentkontext und aktuelle Benutzerbindung unterscheiden sich.")
        return captured.user_id
    return actor_id


class _Lookup(Mapping):
    """Lookup budget limits caching, never the available actual identities."""

    def __init__(self, lookup, *, budget=128):
        self.lookup = lru_cache(maxsize=budget)(lookup)

    def __getitem__(self, identifier):
        return self.lookup(identifier)

    def __iter__(self):
        raise TypeError("Document context parents are targeted actual lookups")

    def __len__(self):
        raise TypeError("Document context parents are targeted actual lookups")


class _Originals:
    def __init__(self, store, *, period=None, verified_period_hash=None):
        self.store = store
        singular = {"properties": "property", "billing_periods": "billing_period", "utility_statements": "utility_statement"}

        def parent(name, identifier):
            if name == "tenants":
                # Frozen originals need existence, not today's personal profile.
                if hasattr(store, "db"):
                    from sqlalchemy import select

                    from ..db.orm_models import TenantORM

                    found = store.db.connection().scalar(select(TenantORM.__table__.c.id).where(TenantORM.__table__.c.id == identifier))
                else:
                    found = identifier if identifier in store.tenants else None
                if found is None:
                    raise KeyError(identifier)
                return {"id": found}
            return getattr(store, "get_" + singular.get(name, name[:-1]))(identifier).model_dump(mode="json")

        self.parents = {name: _Lookup(lambda identifier, name=name: parent(name, identifier))
            for name in ("properties", "units", "contracts", "tenants", "portfolios", "billing_periods", "utility_statements")}

        def digest(identifier):
            from .billing_statement_party_storage import statement_snapshot_hash

            if period is not None and identifier == period.id and verified_period_hash is not None:
                return verified_period_hash
            actual = store.get_billing_period(identifier)
            return statement_snapshot_hash(store, actual)

        self.hashes = _Lookup(digest, budget=32)

    def rows(self, identifier):
        if hasattr(self.store, "db"):
            from sqlalchemy import select

            from ..db.orm_models import UtilityStatementORM
            from ..models import UtilityStatement

            stream = self.store.db.scalars(select(UtilityStatementORM).where(UtilityStatementORM.billing_period_id == identifier)
                .order_by(UtilityStatementORM.id).execution_options(yield_per=100))
            try:
                for row in stream:
                    yield UtilityStatement.model_validate(row, from_attributes=True).model_dump(mode="json")
            finally:
                stream.close()
        else:
            for row in sorted((row for row in self.store.utility_statements.values() if row.billing_period_id == identifier), key=lambda row: row.id):
                yield row.model_dump(mode="json")


def capture_finalization_context(store, period, statements, *,
                                 reviewed_issuers: Mapping[str, ReviewedIssuer] | None = None,
                                 actor_id: str | None = None) -> dict:
    """Return new owner JSON inside the existing locked finalization operation."""
    actor_id = capture_actor(actor_id)
    if reviewed_issuers is not None and not isinstance(reviewed_issuers, Mapping):
        raise DocumentContextIntegrityError("Ausstellerprüfungen benötigen die tatsächlichen Einzelabrechnungsreferenzen.")
    if document_context_family(period) is not None:
        raise DocumentContextIntegrityError("Ein vorhandenes Dokumentkontextoriginal darf nicht neu eingefroren werden.")
    if actor_id is None:
        if reviewed_issuers:
            raise DocumentContextIntegrityError("Eine ausdrückliche Ausstellerprüfung benötigt den tatsächlichen prüfenden Benutzer.")
        # Existing internal three-argument finalizers remain party-only. An
        # absent actor cannot become a guessed capture identity or issuer review.
        return period.owner_cost_share
    originals = _Originals(store)
    return capture_document_contexts(period, statements, parents=originals.parents,
        reviewed_issuers=reviewed_issuers if reviewed_issuers is not None else {}, actor_id=actor_id,
        captured_at=datetime.now(timezone.utc), verified_period_hashes=originals.hashes,
        statements_for_period=originals.rows)


def validate_stored_document_contexts(store, period, *, statements=None, verified_period_hash: str | None = None) -> None:
    """Read-only actual originals; supplied SHA is exclusively native internal."""
    if document_context_family(period) is None:
        return
    originals = _Originals(store, period=period, verified_period_hash=verified_period_hash)
    if statements is None:
        statements = originals.rows(period.id)
    validate_period_document_contexts(period, statements, parents=originals.parents,
        verified_period_hashes=originals.hashes, statements_for_period=originals.rows)
