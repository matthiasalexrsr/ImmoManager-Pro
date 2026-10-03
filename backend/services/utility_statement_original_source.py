"""Pure selected-source contract and an operative, coherent original reader."""

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models import UtilityStatement
from .billing_originals import IMMUTABLE, snapshot_hash
from .billing_statement_parties import FROZEN_BINDING, StatementParty, family, party, validate_period_statement_parties

SCHEMA: Literal["utility-statement-original-source/1"] = "utility-statement-original-source/1"
PROFILE: Literal["utility-statement-pdf-preview/1"] = "utility-statement-pdf-preview/1"
UNPROVED: Literal["historical_party_unproved"] = "historical_party_unproved"
DRAFT_SCHEMA: Literal["utility-statement-draft-source/1"] = "utility-statement-draft-source/1"
DRAFT_PROFILE: Literal["utility-statement-draft-pdf-preview/1"] = "utility-statement-draft-pdf-preview/1"
MUTABLE = {"status", "delivery_status", "delivered_at", "delivery_channel", "updated_at"}
SHA = r"^[0-9a-f]{64}$"


class UtilityOriginalIntegrityError(ValueError):
    pass


class UtilityPreviewEmptyError(UtilityOriginalIntegrityError):
    pass


def source_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


class PeriodReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    basis: Literal["retained_period_reference"] = "retained_period_reference"
    id: str = Field(min_length=1)
    property_id: str = Field(min_length=1)
    start_date: date
    end_date: date
    revision_number: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def actual_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("Original period dates are reversed")
        return self


class SourceLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement_id: str
    contract_id: str
    unit_id: str
    revision: int = Field(ge=1, strict=True)
    snapshot_hash: str = Field(pattern=SHA)
    source_statement_id: str | None
    period_context: PeriodReference
    party_binding: Literal["frozen_at_statement_finalization", "historical_party_unproved"]
    original_party: StatementParty | None

    @model_validator(mode="after")
    def actual_party(self):
        if (self.original_party is None) != (self.party_binding == UNPROVED):
            raise ValueError("Source party proof is not explicit")
        if self.original_party is not None and any(getattr(self.original_party, field) != expected for field, expected in {
                "statement_id": self.statement_id, "period_id": self.period_context.id, "revision": self.revision,
                "contract_id": self.contract_id, "unit_id": self.unit_id, "property_id": self.period_context.property_id,
                "source_statement_id": self.source_statement_id}.items()):
            raise ValueError("Source party belongs to another original")
        return self


class UtilityStatementOriginalSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["utility-statement-original-source/1"]
    render_profile: Literal["utility-statement-pdf-preview/1"]
    statement_original: dict
    period_context: PeriodReference
    original_party: StatementParty | None
    party_binding: Literal["frozen_at_statement_finalization", "historical_party_unproved"]
    source_chain: list[SourceLink]
    source_digest: str = Field(pattern=SHA)

    @model_validator(mode="after")
    def exact_source(self):
        raw = self.statement_original
        typed = UtilityStatement.model_validate(raw).model_dump(mode="json", exclude=MUTABLE)
        if (source_digest(raw) != source_digest(typed) or raw["billing_period_id"] != self.period_context.id
                or raw["revision"] != self.period_context.revision_number
                or not re.fullmatch(SHA, raw["snapshot_hash"] or "")):
            raise ValueError("Selected source is not the exact typed original")
        current_id, current_revision, expected_source = raw["id"], raw["revision"], raw["source_statement_id"]
        current_party = self.original_party
        if (current_party is None) != (self.party_binding == UNPROVED):
            raise ValueError("Original party proof is not explicit")
        if current_party is not None and any(getattr(current_party, field) != expected for field, expected in {
                "statement_id": raw["id"], "period_id": self.period_context.id, "revision": raw["revision"],
                "contract_id": raw["contract_id"], "unit_id": raw["unit_id"], "property_id": self.period_context.property_id,
                "source_statement_id": raw["source_statement_id"]}.items()):
            raise ValueError("Original party belongs to another source")
        seen = {current_id}
        for link in self.source_chain:
            if (link.statement_id != expected_source or link.statement_id in seen or link.revision >= current_revision
                    or link.contract_id != raw["contract_id"] or link.unit_id != raw["unit_id"]
                    or link.period_context.property_id != self.period_context.property_id
                    or link.period_context.start_date != self.period_context.start_date
                    or link.period_context.end_date != self.period_context.end_date
                    or link.revision != link.period_context.revision_number
                    or (link.original_party is None) != (link.party_binding == UNPROVED)):
                raise ValueError("Original source chain is inconsistent")
            if current_party is not None and (current_party.source_statement_id != link.statement_id
                    or current_party.source_snapshot_hash != link.snapshot_hash):
                raise ValueError("Frozen source hash does not match")
            if current_party is not None and link.original_party is not None and (
                    current_party.tenant_id != link.original_party.tenant_id or current_party.identity != link.original_party.identity):
                raise ValueError("Original source party differs")
            seen.add(link.statement_id)
            current_id, current_revision, expected_source = link.statement_id, link.revision, link.source_statement_id
            current_party = link.original_party
        if expected_source is not None:
            raise ValueError("Incomplete source chain")
        if self.source_digest != source_digest(self.model_dump(mode="json", exclude={"source_digest"})):
            raise ValueError("Selected source digest differs")
        return self


def validate_source(value):
    try:
        return UtilityStatementOriginalSource.model_validate(value)
    except (ValueError, TypeError, KeyError) as error:
        raise UtilityOriginalIntegrityError("Die geprüfte Abrechnungsquelle ist beschädigt oder unvollständig.") from error


class UtilityStatementDraftSource(BaseModel):
    """Saved generated draft; no frozen identity or final original is asserted."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["utility-statement-draft-source/1"]
    mode: Literal["draft"] = "draft"
    render_profile: Literal["utility-statement-draft-pdf-preview/1"]
    statement_draft: dict
    period_context: PeriodReference
    original_party: None = None
    party_binding: Literal["not_frozen"] = "not_frozen"
    previous_original: UtilityStatementOriginalSource | None
    source_digest: str = Field(pattern=SHA)

    @model_validator(mode="after")
    def exact_draft(self):
        raw = self.statement_draft
        typed = UtilityStatement.model_validate(raw).model_dump(mode="json", exclude=MUTABLE - {"status"})
        if (source_digest(raw) != source_digest(typed) or raw["status"] not in {"draft", "review"} or raw["snapshot_hash"] is not None
                or raw["billing_period_id"] != self.period_context.id or raw["revision"] != self.period_context.revision_number):
            raise ValueError("Draft source is not the exact saved generated draft")
        previous = self.previous_original
        if (previous is None) != (raw["source_statement_id"] is None):
            raise ValueError("Correction draft requires its actual previous original")
        if previous is not None:
            old = previous.statement_original
            if (old["id"] != raw["source_statement_id"] or old["contract_id"] != raw["contract_id"] or old["unit_id"] != raw["unit_id"]
                    or old["revision"] >= raw["revision"] or previous.period_context.id == self.period_context.id
                    or previous.period_context.property_id != self.period_context.property_id
                    or previous.period_context.start_date != self.period_context.start_date or previous.period_context.end_date != self.period_context.end_date):
                raise ValueError("Draft refers to a different previous original")
        if self.source_digest != source_digest(self.model_dump(mode="json", exclude={"source_digest"})):
            raise ValueError("Draft source digest differs")
        return self

    @property
    def statement_original(self):
        # Shared renderer reads these saved financials without asserting an
        # original mode; the serialized DTO always calls them statement_draft.
        return self.statement_draft

    @property
    def source_chain(self):
        if self.previous_original is None:
            return []
        previous = self.previous_original
        raw = previous.statement_original
        return [SourceLink(statement_id=raw["id"], contract_id=raw["contract_id"], unit_id=raw["unit_id"], revision=raw["revision"],
            snapshot_hash=raw["snapshot_hash"], source_statement_id=raw["source_statement_id"], period_context=previous.period_context,
            party_binding=previous.party_binding, original_party=previous.original_party), *previous.source_chain]


def validate_preview(value):
    try:
        raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        if raw["schema_version"] == DRAFT_SCHEMA:
            return UtilityStatementDraftSource.model_validate(raw)
        return validate_source(raw)
    except (ValueError, TypeError, KeyError) as error:
        raise UtilityOriginalIntegrityError("Die gespeicherte Vorschauquelle ist beschädigt oder unvollständig.") from error


class _Reader:
    """Caller owns Work snapshot; only affected originals/parents are loaded."""

    def __init__(self, store):
        self.store, self.verified, self.verifying = store, {}, set()
        reader = self
        class Parents(Mapping):
            def __init__(self, name):
                self.name = name
                self.lookup = lru_cache(maxsize=128)(self._lookup)
            def _lookup(self, identifier):
                if self.name == "tenants":
                    # Actual parent existence only: no current name or hidden
                    # profile is read to replace a proved frozen party.
                    if hasattr(store, "db"):
                        from sqlalchemy import select

                        from ..db.orm_models import TenantORM
                        found = store.db.connection().scalar(select(TenantORM.__table__.c.id).where(TenantORM.__table__.c.id == identifier))
                    else:
                        found = identifier if identifier in store.tenants else None
                    if found is None:
                        raise KeyError(identifier)
                    return {"id": found}
                model = getattr(store, "get_" + {"properties": "property", "billing_periods": "billing_period", "utility_statements": "utility_statement"}.get(self.name, self.name[:-1]))(identifier)
                if self.name == "utility_statements":
                    reader.verify(model)
                return model.model_dump(mode="json")
            def __getitem__(self, identifier):
                return self.lookup(identifier)
            def __iter__(self):
                raise TypeError("Original parent maps are targeted")
            def __len__(self):
                raise TypeError("Original parent maps are targeted")
        self.parents = {name: Parents(name) for name in ("portfolios", "properties", "units", "contracts", "tenants", "billing_periods", "utility_statements")}

    def rows(self, identifier):
        if hasattr(self.store, "db"):
            from sqlalchemy import select

            from ..db.orm_models import UtilityStatementORM
            result = self.store.db.scalars(select(UtilityStatementORM).where(UtilityStatementORM.billing_period_id == identifier)
                .order_by(UtilityStatementORM.id).execution_options(yield_per=100))
            try:
                for row in result:
                    yield UtilityStatement.model_validate(row, from_attributes=True)
            finally:
                result.close()
        else:
            yield from sorted((row for row in self.store.utility_statements.values() if row.billing_period_id == identifier), key=lambda row: row.id)

    def period(self, identifier):
        period = self.store.get_billing_period(identifier)
        if identifier in self.verifying:
            raise UtilityOriginalIntegrityError("Die ursprüngliche Abrechnungsquelle enthält einen Quellenzyklus.")
        if identifier in self.verified:
            return period
        if period.status not in IMMUTABLE:
            raise UtilityOriginalIntegrityError("Die ursprüngliche Abrechnungsperiode ist nicht eindeutig finalisiert.")
        self.verifying.add(identifier)
        def statements():
            for statement in self.rows(identifier):
                contract = self.parents["contracts"][statement.contract_id]
                unit = self.parents["units"][statement.unit_id]
                if (statement.status not in IMMUTABLE or statement.snapshot_hash != digest or statement.revision != period.revision_number
                        or contract["property_id"] != period.property_id or unit["property_id"] != period.property_id or contract["unit_id"] != statement.unit_id):
                    raise UtilityOriginalIntegrityError("Die vollständige Periodenfassung weicht vom finalisierten Original ab.")
                yield statement.model_dump(mode="json")
        try:
            if hasattr(self.store, "db"):
                from .billing_statement_party_storage import statement_snapshot_hash
                digest = statement_snapshot_hash(self.store, period)
            else:
                digest = snapshot_hash(list(self.rows(identifier)), period.owner_cost_share)
            self.verified[identifier] = digest
            rows = statements()
            if family(period) is None:
                for _row in rows:
                    pass
            else:
                validate_period_statement_parties(period.model_dump(mode="json"), rows, parents=self.parents, verified_period_hash=digest)
        except BaseException:
            self.verified.pop(identifier, None)
            raise
        finally:
            self.verifying.remove(identifier)
        return period

    def verify(self, statement):
        period = self.period(statement.billing_period_id)
        if statement.status not in IMMUTABLE or statement.snapshot_hash != self.verified[period.id]:
            raise UtilityOriginalIntegrityError("Die konkrete Abrechnung weicht von ihrem Originalhash ab.")
        return period

    def source(self, identifier):
        statement = self.store.get_utility_statement(identifier)
        period = self.verify(statement)
        original = party(statement, period)
        chain, current, current_period, seen = [], statement, period, {statement.id}
        while current.source_statement_id:
            source = self.store.get_utility_statement(current.source_statement_id)
            source_period = self.verify(source)
            if (source.id in seen or source.revision >= current.revision or current_period.source_period_id != source_period.id
                    or source.contract_id != statement.contract_id or source.unit_id != statement.unit_id
                    or source_period.property_id != period.property_id or source_period.start_date != period.start_date or source_period.end_date != period.end_date):
                raise UtilityOriginalIntegrityError("Die Korrekturkette besitzt keine eindeutige tatsächliche Originalquelle.")
            frozen = party(source, source_period)
            chain.append(SourceLink(statement_id=source.id, contract_id=source.contract_id, unit_id=source.unit_id, revision=source.revision,
                snapshot_hash=source.snapshot_hash, source_statement_id=source.source_statement_id, period_context=_period_reference(source_period),
                party_binding="frozen_at_statement_finalization" if frozen else UNPROVED, original_party=frozen))
            seen.add(source.id)
            current, current_period = source, source_period
        if current_period.source_period_id is not None:
            raise UtilityOriginalIntegrityError("Die ursprüngliche Periodenquelle besitzt keine vollständige Statementkette.")
        body = {"schema_version": SCHEMA, "render_profile": PROFILE, "statement_original": statement.model_dump(mode="json", exclude=MUTABLE),
            "period_context": _period_reference(period).model_dump(mode="json"), "original_party": original.model_dump(mode="json") if original else None,
            "party_binding": FROZEN_BINDING if original else UNPROVED, "source_chain": [row.model_dump(mode="json") for row in chain]}
        return validate_source({**body, "source_digest": source_digest(body)})

    def preview(self, identifier):
        statement = self.store.get_utility_statement(identifier)
        period = self.store.get_billing_period(statement.billing_period_id)
        if period.status in IMMUTABLE:
            return self.source(identifier)
        if (period.status not in {"draft", "review"} or statement.status not in {"draft", "review"}
                or statement.snapshot_hash is not None or statement.revision != period.revision_number or family(period) is not None):
            raise UtilityOriginalIntegrityError("Entwurf und Abrechnungsperiode besitzen keine eindeutige unveröffentlichte Bindung.")
        contract, unit = self.parents["contracts"][statement.contract_id], self.parents["units"][statement.unit_id]
        prop = self.parents["properties"][period.property_id]
        self.parents["portfolios"][prop["portfolio_id"]]
        if contract["unit_id"] != unit["id"] or contract["property_id"] != prop["id"] or unit["property_id"] != prop["id"]:
            raise UtilityOriginalIntegrityError("Die gespeicherte Entwurfseinheit gehört nicht zur tatsächlichen Vertragsbindung.")
        previous = self.source(statement.source_statement_id) if statement.source_statement_id else None
        if previous is not None and period.source_period_id != previous.period_context.id:
            raise UtilityOriginalIntegrityError("Die Korrekturvorschau besitzt eine andere tatsächliche Periodenquelle.")
        body = {"schema_version": DRAFT_SCHEMA, "mode": "draft", "render_profile": DRAFT_PROFILE,
            "statement_draft": statement.model_dump(mode="json", exclude=MUTABLE - {"status"}), "period_context": _period_reference(period).model_dump(mode="json"),
            "original_party": None, "party_binding": "not_frozen", "previous_original": previous.model_dump(mode="json") if previous else None}
        return validate_preview({**body, "source_digest": source_digest(body)})


def _period_reference(period):
    return PeriodReference(id=period.id, property_id=period.property_id, start_date=period.start_date, end_date=period.end_date, revision_number=period.revision_number)


def original_source_preview(store, identifier, actor_id):
    from .billing_disputes import work
    with work(store, actor_id) as (active, _case, _period, _add):
        return _Reader(active).source(identifier)
