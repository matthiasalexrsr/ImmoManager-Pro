"""Pure future document context; no finalization, authorization or storage here."""

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from ..models import UtilityStatement
from .billing_originals import IMMUTABLE, snapshot_hash
from .billing_statement_parties import family as party_family
from .billing_statement_parties import party, validate_period_statement_parties
from .utility_statement_original_source import SHA, source_digest

KEY = "statement_document_contexts"
SCHEMA: Literal["utility-statement-document-contexts/1"] = "utility-statement-document-contexts/1"
Rows = Callable[[str], Iterable[Mapping]]


class DocumentContextIntegrityError(ValueError):
    pass


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def nonblank_strings(cls, value):
        if isinstance(value, str) and (not value.strip() or any(ord(c) < 32 and c not in "\n\t" for c in value)):
            raise ValueError("Context strings must be nonempty printable data")
        return value


class PostalIdentity(Strict):
    name: str = Field(min_length=1)
    address_line: str | None
    postal_code: str | None
    city: str | None
    country: str | None


class ReviewedIssuer(Strict):
    identity: PostalIdentity
    role: Literal["landlord", "representative"]
    landlord: PostalIdentity | None
    confirmed: StrictBool

    @model_validator(mode="after")
    def explicit_confirmation(self):
        if self.confirmed is not True or self.role == "landlord" and self.landlord is not None:
            raise ValueError("Explicit issuer review required; landlord issuer is its own identity")
        return self


class RentalObject(Strict):
    address_line: str | None
    postal_code: str | None
    city: str | None
    country: str | None
    property_name: str | None
    unit_label: str | None
    floor: str | None


class StatementDocumentContext(Strict):
    statement_id: str
    period_id: str
    revision: int = Field(ge=1, strict=True)
    portfolio_id: str
    property_id: str
    unit_id: str
    contract_id: str
    party_digest: str = Field(pattern=SHA)
    start_date: date
    end_date: date
    contract_number: str | None
    rental_object: RentalObject | None
    issuer: ReviewedIssuer | None
    captured_at: datetime
    captured_by: str | None
    object_binding: Literal["current_parents_at_initial_finalization", "source_original", "historical_object_unproved"]
    source_statement_id: str | None
    source_snapshot_hash: str | None = Field(pattern=SHA)
    source_context_digest: str | None = Field(pattern=SHA)

    @field_validator("captured_at")
    @classmethod
    def utc_capture(cls, value):
        if value.tzinfo is None:
            raise ValueError("Capture time needs an explicit timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def honest_capture(self):
        if self.end_date < self.start_date or self.issuer is not None and self.captured_by is None:
            raise ValueError("Context capture/date/reviewer is incomplete")
        if self.source_statement_id is None:
            if (self.source_snapshot_hash is not None or self.source_context_digest is not None
                    or self.object_binding != "current_parents_at_initial_finalization" or self.rental_object is None):
                raise ValueError("Initial object capture has no correction source")
        elif self.source_snapshot_hash is None or self.object_binding == "current_parents_at_initial_finalization":
            raise ValueError("Correction context requires its actual original source")
        elif self.object_binding == "source_original":
            if self.rental_object is None or self.source_context_digest is None:
                raise ValueError("Copied object requires the actual preceding context")
        elif self.rental_object is not None or self.contract_number is not None:
            raise ValueError("Unproved historical object cannot acquire current names/address")
        return self


class StatementDocumentContexts(Strict):
    schema_version: Literal["utility-statement-document-contexts/1"]
    statements: dict[str, StatementDocumentContext]


def _data(value):
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


def document_context_family(period):
    try:
        owner = _data(period).get("owner_cost_share")
        if owner is None:
            return None
        if not isinstance(owner, dict):
            raise ValueError("Owner original is not an object")
        return StatementDocumentContexts.model_validate(_data(owner[KEY])) if KEY in owner else None
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise DocumentContextIntegrityError("Das gespeicherte Dokumentkontextoriginal ist beschädigt.") from error


def protect_period_document_contexts(current, replacement):
    """Keep originals immutable, including an old intentionally absent family."""
    old, new = document_context_family(current), document_context_family(replacement)
    if old is not None and (new is None or old.model_dump(mode="json") != new.model_dump(mode="json")):
        raise DocumentContextIntegrityError("Eingefrorene Dokumentkontextoriginale dürfen nicht überschrieben werden.")
    if old is None and new is not None and (_data(current)["status"] not in {"draft", "review"} or _data(replacement)["status"] != "finalized"):
        raise DocumentContextIntegrityError("Dokumentkontextoriginale entstehen ausschließlich bei einer neuen tatsächlichen Finalisierung.")


def _same_context(context, statement, period, original):
    expected = {"statement_id": statement["id"], "period_id": period["id"], "revision": statement["revision"],
        "portfolio_id": original.portfolio_id, "property_id": period["property_id"], "unit_id": statement["unit_id"],
        "contract_id": statement["contract_id"], "source_statement_id": statement["source_statement_id"],
        "source_snapshot_hash": original.source_snapshot_hash, "party_digest": source_digest(original.model_dump(mode="json"))}
    if (any(getattr(context, key) != value for key, value in expected.items())
            or context.start_date.isoformat() != str(period["start_date"])
            or context.end_date.isoformat() != str(period["end_date"])):
        raise ValueError("Context belongs to another original/party/date")


def _parents(statement, period, original, parents):
    prop = parents["properties"][period["property_id"]]
    unit = parents["units"][statement["unit_id"]]
    contract = parents["contracts"][statement["contract_id"]]
    portfolio = parents["portfolios"][prop["portfolio_id"]]
    if (prop["id"] != period["property_id"] or unit["id"] != statement["unit_id"] or contract["id"] != statement["contract_id"]
            or portfolio["id"] != prop["portfolio_id"]
            or unit["property_id"] != period["property_id"] or contract["property_id"] != period["property_id"]
            or contract["unit_id"] != statement["unit_id"]):
        raise ValueError("Actual context parents differ")
    if original is not None:
        tenant = parents["tenants"][original.tenant_id]
        if (tenant["id"] != original.tenant_id or original.statement_id != statement["id"] or original.period_id != period["id"]
                or original.revision != statement["revision"] or original.revision != period["revision_number"]
                or original.property_id != period["property_id"] or original.unit_id != statement["unit_id"]
                or original.contract_id != statement["contract_id"] or original.portfolio_id != prop["portfolio_id"]
                or original.source_statement_id != statement["source_statement_id"]):
            raise ValueError("Party/context parent binding differs")
    return prop, unit, contract


class _Verifier:
    """Actual supplied snapshots only; optional hashes/row readers are internal."""

    def __init__(self, parents, hashes, rows):
        self.parents, self.hashes, self.rows = parents, hashes, rows
        self.verified, self.verifying = set(), set()

    def source(self, statement, period):
        source = self.parents["utility_statements"][statement["source_statement_id"]]
        old = self.parents["billing_periods"][source["billing_period_id"]]
        if (source["id"] != statement["source_statement_id"] or old["id"] != source["billing_period_id"]
                or source["contract_id"] != statement["contract_id"]
                or source["unit_id"] != statement["unit_id"] or source["revision"] >= statement["revision"]
                or old["id"] != period["source_period_id"] or old["property_id"] != period["property_id"]
                or str(old["start_date"]) != str(period["start_date"]) or str(old["end_date"]) != str(period["end_date"])):
            raise ValueError("Context correction has another actual source")
        self.period(old)
        previous = document_context_family(old)
        return source, previous.statements[source["id"]] if previous is not None else None

    def period(self, period, statements=None):
        identifier = period["id"]
        if identifier in self.verifying:
            raise ValueError("Document context source cycle")
        if identifier in self.verified:
            return
        if period["status"] not in IMMUTABLE:
            raise ValueError("Document context source is not finalized")
        self.verifying.add(identifier)
        try:
            frozen = document_context_family(period)
            parties = party_family(period)
            if frozen is not None and parties is None:
                raise ValueError("Document context has no original party family")
            if statements is None:
                statements = self.rows(identifier) if self.rows else (
                    row for row in self.parents["utility_statements"].values() if row["billing_period_id"] == identifier)
            if self.hashes is None:
                statements = list(statements)
                digest = snapshot_hash([UtilityStatement.model_validate(row) for row in statements], period["owner_cost_share"])
            else:
                digest = self.hashes[identifier]
                if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise ValueError("Actual native period hash is missing/invalid")
            seen = set()

            def checked_rows():
                for statement in statements:
                    if (statement["id"] in seen or statement["billing_period_id"] != identifier
                            or statement["revision"] != period["revision_number"] or statement["status"] not in IMMUTABLE
                            or statement["snapshot_hash"] != digest):
                        raise ValueError("Complete actual period hash/rows differ")
                    seen.add(statement["id"])
                    original = party(statement, period) if parties is not None else None
                    _parents(statement, period, original, self.parents)
                    source, previous = self.source(statement, period) if statement["source_statement_id"] else (None, None)
                    if source is None and period["source_period_id"] is not None:
                        raise ValueError("Context source period without source Statement")
                    if frozen is not None:
                        context = frozen.statements[statement["id"]]
                        _same_context(context, statement, period, original)
                        if source is not None:
                            if (context.source_snapshot_hash != source["snapshot_hash"]
                                    or context.source_context_digest != (source_digest(previous.model_dump(mode="json")) if previous else None)
                                    or context.rental_object != (previous.rental_object if previous else None)
                                    or context.contract_number != (previous.contract_number if previous else None)
                                    or context.object_binding != ("source_original" if previous and previous.rental_object else "historical_object_unproved")):
                                raise ValueError("Correction replaced its actual historical object/context")
                    yield statement

            rows = checked_rows()
            if parties is not None:
                validate_period_statement_parties(period, rows, parents=self.parents, verified_period_hash=digest)
            else:
                for _row in rows:
                    pass
            if frozen is not None and set(frozen.statements) != seen:
                raise ValueError("Document context original family is incomplete")
            self.verified.add(identifier)
        finally:
            self.verifying.remove(identifier)


def validate_period_document_contexts(period, statements, *, parents, verified_period_hashes=None, statements_for_period=None):
    """Full real context family; native hashes/readers must come only from DB."""
    try:
        period = _data(period)
        if document_context_family(period) is not None:
            _Verifier(parents, verified_period_hashes, statements_for_period).period(period, statements)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise DocumentContextIntegrityError("Dokumentkontextoriginale sind beschädigt oder unvollständig.") from error


def validate_document_context_snapshot(*, parents):
    """Complete pure snapshot hook, also with no existing archive/dispute."""
    try:
        verifier = _Verifier(parents, None, None)
        for period in parents["billing_periods"].values():
            if document_context_family(period) is not None:
                verifier.period(period)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise DocumentContextIntegrityError("Dokumentkontextsnapshot ist beschädigt oder unvollständig.") from error


def _optional(value):
    return value if value is not None and str(value).strip() else None


def capture_document_contexts(period, statements, *, parents, reviewed_issuers, actor_id, captured_at,
                              verified_period_hashes=None, statements_for_period=None):
    """NEW owner JSON only. Root owns explicit review, locks/hash/finalize/undo."""
    try:
        period, statements = _data(period), [_data(row) for row in statements]
        if period["status"] not in {"draft", "review"} or document_context_family(period) is not None:
            raise ValueError("Only a new actual future finalization can capture document context")
        parties = party_family(period)
        identifiers = {row["id"] for row in statements}
        if (parties is None or len(identifiers) != len(statements) or set(parties.statements) != identifiers
                or set(reviewed_issuers) - identifiers):
            raise ValueError("Actual complete Statement/party/review selection differs")
        verifier, entries = _Verifier(parents, verified_period_hashes, statements_for_period), {}
        for statement in statements:
            if (statement["status"] not in {"draft", "review"} or statement["snapshot_hash"] is not None
                    or statement["billing_period_id"] != period["id"]):
                raise ValueError("Finalized/historical Statement cannot acquire new context")
            original = parties.statements[statement["id"]]
            prop, unit, contract = _parents(statement, period, original, parents)
            source, previous = verifier.source(statement, period) if statement["source_statement_id"] else (None, None)
            if (source is None and period["source_period_id"] is not None
                    or source is not None and original.source_snapshot_hash != source["snapshot_hash"]
                    or source is None and (original.basis != "contract_at_finalization" or original.tenant_id != contract["tenant_id"])):
                raise ValueError("Captured context has another frozen source")
            rental = previous.rental_object if previous else None
            number = previous.contract_number if previous else None
            if source is None:
                rental = RentalObject(**{name: _optional(prop.get(name)) for name in ("address_line", "postal_code", "city", "country")},
                    property_name=_optional(prop.get("name")), unit_label=_optional(unit.get("label")), floor=_optional(unit.get("floor")))
                number = _optional(contract.get("contract_number"))
            issuer = ReviewedIssuer.model_validate(_data(reviewed_issuers[statement["id"]])) if statement["id"] in reviewed_issuers else None
            entries[statement["id"]] = StatementDocumentContext(statement_id=statement["id"], period_id=period["id"],
                revision=statement["revision"], portfolio_id=prop["portfolio_id"], property_id=prop["id"],
                unit_id=unit["id"], contract_id=contract["id"], party_digest=source_digest(original.model_dump(mode="json")),
                start_date=period["start_date"], end_date=period["end_date"], contract_number=number, rental_object=rental,
                issuer=issuer, captured_at=captured_at, captured_by=actor_id,
                object_binding="current_parents_at_initial_finalization" if source is None else "source_original" if rental else "historical_object_unproved",
                source_statement_id=source["id"] if source else None, source_snapshot_hash=source["snapshot_hash"] if source else None,
                source_context_digest=source_digest(previous.model_dump(mode="json")) if previous else None)
        return {**deepcopy(period["owner_cost_share"]), KEY: StatementDocumentContexts(schema_version=SCHEMA, statements=entries).model_dump(mode="json")}
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise DocumentContextIntegrityError("Neue Dokumentkontextfassung benötigt eine eindeutige geprüfte Quelle.") from error
