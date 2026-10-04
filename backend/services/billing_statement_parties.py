"""Versioned parties inside the existing, hashed settlement original JSON."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA: Literal["utility-statement-parties/1"] = "utility-statement-parties/1"
KEY = "statement_parties"
FROZEN_BINDING = "frozen_at_statement_finalization"
LEGACY_BINDING = "verified_at_case_opening"
IDENTITY_FIELDS = ("full_name", "address_line", "postal_code", "city", "country")


class StatementPartyIntegrityError(ValueError):
    pass


class PartyIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=1)
    address_line: str | None
    postal_code: str | None
    city: str | None
    country: str | None


class StatementParty(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement_id: str = Field(min_length=1)
    period_id: str = Field(min_length=1)
    revision: int = Field(ge=1, strict=True)
    portfolio_id: str = Field(min_length=1)
    property_id: str = Field(min_length=1)
    unit_id: str = Field(min_length=1)
    contract_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    identity: PartyIdentity
    captured_at: datetime
    captured_by: str | None
    basis: Literal["contract_at_finalization", "source_original", "contract_at_correction_finalization"]
    source_statement_id: str | None
    source_snapshot_hash: str | None = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("captured_at")
    @classmethod
    def actual_timestamp(cls, value):
        if value.tzinfo is None:
            raise ValueError("Party capture requires an explicit UTC timestamp")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def actual_source(self):
        if self.source_statement_id is None:
            if self.basis != "contract_at_finalization" or self.source_snapshot_hash is not None:
                raise ValueError("Original party has no correction source")
        elif self.basis == "contract_at_finalization" or self.basis == "source_original" and self.source_snapshot_hash is None:
            raise ValueError("Correction party requires its actual source")
        return self


class StatementParties(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["utility-statement-parties/1"]
    statements: dict[str, StatementParty]


def _data(value):
    return value if isinstance(value, dict) else value.model_dump(mode="json")


def family(period):
    """Absence is legacy; any present malformed family fails closed."""
    owner = _data(period).get("owner_cost_share")
    if owner is None:
        return None
    if not isinstance(owner, dict):
        raise StatementPartyIntegrityError("Das gespeicherte Periodenoriginal ist beschädigt.")
    if KEY not in owner:
        return None
    try:
        return StatementParties.model_validate(owner[KEY])
    except (ValueError, TypeError) as error:
        raise StatementPartyIntegrityError("Die gespeicherte Originalparteienfassung ist beschädigt.") from error


def party(statement, period):
    values, root = _data(statement), _data(period)
    frozen = family(root)
    if frozen is None:
        return None
    from .billing_originals import IMMUTABLE
    result = frozen.statements.get(values["id"])
    if (result is None or result.statement_id != values["id"] or result.period_id != root["id"]
            or values["billing_period_id"] != root["id"] or result.revision != values["revision"]
            or result.contract_id != values["contract_id"] or result.unit_id != values["unit_id"]
            or result.property_id != root["property_id"] or result.source_statement_id != values["source_statement_id"]):
        raise StatementPartyIntegrityError("Die eingefrorene Mietpartei gehört nicht zur konkreten Abrechnungsfassung.")
    if values["status"] not in IMMUTABLE or root["status"] not in IMMUTABLE or result.revision != root["revision_number"]:
        raise StatementPartyIntegrityError("Die gespeicherte Originalpartei benötigt ihre tatsächlich finalisierte Fassung.")
    return result


def protect_period_original(current, replacement):
    old, new = family(current), family(replacement)
    if old is not None and (new is None or old.model_dump(mode="json") != new.model_dump(mode="json")):
        raise StatementPartyIntegrityError("Eingefrorene Abrechnungsparteien dürfen nicht überschrieben werden.")
    if old is None and new is not None and (current.status not in {"draft", "review"} or replacement.status != "finalized"):
        raise StatementPartyIntegrityError("Originalparteien entstehen ausschließlich bei einer neuen tatsächlichen Finalisierung.")


def validate_period_statement_parties(period, statements, *, parents, verified_period_hash=None):
    """Pure original check; only a native internal caller supplies a streamed hash.

    With that hash, statements is consumed once without materializing its rows.
    Parent mappings may load actual referenced rows lazily. The caller computes
    the hash from the complete native period, never from a request or JSON cache.
    """
    from ..models import UtilityStatement
    from .billing_originals import IMMUTABLE, snapshot_hash
    try:
        frozen = family(period)
        if frozen is None:
            return
        if period["status"] not in IMMUTABLE:
            raise ValueError("nonfinal original parties")
        if verified_period_hash is None:
            statements = list(statements)
            digest = snapshot_hash([UtilityStatement.model_validate(row) for row in statements], period["owner_cost_share"])
        else:
            digest = verified_period_hash
        seen = set()
        for statement in statements:
            if statement["id"] in seen:
                raise ValueError("duplicate original statement")
            seen.add(statement["id"])
            original = party(statement, period)
            prop = parents["properties"][original.property_id]
            unit = parents["units"][original.unit_id]
            contract = parents["contracts"][original.contract_id]
            parents["tenants"][original.tenant_id]
            parents["portfolios"][original.portfolio_id]
            if (statement["snapshot_hash"] != digest or prop["portfolio_id"] != original.portfolio_id
                    or unit["property_id"] != original.property_id or contract["unit_id"] != original.unit_id
                    or contract["property_id"] != original.property_id):
                raise ValueError("original binding")
            if original.source_statement_id:
                source = parents["utility_statements"][original.source_statement_id]
                source_period = parents["billing_periods"][source["billing_period_id"]]
                source_party = party(source, source_period)
                if (source["snapshot_hash"] != original.source_snapshot_hash or source["contract_id"] != original.contract_id
                        or source["billing_period_id"] != period["source_period_id"] or source["revision"] >= original.revision
                        or source_period["property_id"] != original.property_id
                        or str(source_period["start_date"]) != str(period["start_date"])
                        or str(source_period["end_date"]) != str(period["end_date"])):
                    raise ValueError("source original")
                if source_party is not None:
                    if (original.basis != "source_original" or source_party.tenant_id != original.tenant_id
                            or source_party.identity != original.identity):
                        raise ValueError("source party")
                elif original.basis != "contract_at_correction_finalization":
                    raise ValueError("unknown historical party")
            elif original.source_snapshot_hash is not None or original.basis != "contract_at_finalization" or period["source_period_id"] is not None:
                raise ValueError("orphan party source")
        if set(frozen.statements) != seen:
            raise ValueError("incomplete original parties")
    except (ValueError, TypeError, KeyError) as error:
        raise StatementPartyIntegrityError("Originalparteienfassung ist beschädigt; unveränderte vollständige Originale wiederherstellen.") from error


def validate_statement_parties(*, parents):
    """Complete pure snapshot hook, including originals without a dispute."""
    by_period: dict[str, list] = {}
    try:
        for statement in parents["utility_statements"].values():
            by_period.setdefault(statement["billing_period_id"], []).append(statement)
        for period in parents["billing_periods"].values():
            validate_period_statement_parties(period, by_period.get(period["id"], []), parents=parents)
    except (ValueError, TypeError, KeyError) as error:
        raise StatementPartyIntegrityError("Originalparteienfassung ist beschädigt; unveränderte vollständige Originale wiederherstellen.") from error
