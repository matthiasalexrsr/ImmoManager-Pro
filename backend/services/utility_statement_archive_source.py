"""Pure selected archive wrapper; absent context stays explicitly incomplete."""

from pydantic import ConfigDict, Field, model_validator

from .billing_statement_document_contexts import (
    DocumentContextIntegrityError,
    StatementDocumentContext,
    Strict,
    _same_context,
)
from .utility_statement_original_source import SHA, UtilityStatementOriginalSource, source_digest, validate_source

SCHEMA = "utility-statement-archive-source/1"


def _missing(financial, context):
    fields = []
    if financial.original_party is None:
        fields.append("original_party")
    else:
        for field in ("full_name", "address_line", "postal_code", "city"):
            if not (getattr(financial.original_party.identity, field) or "").strip():
                fields.append("original_party.identity." + field)
    if context is None:
        fields.append("document_context")
    else:
        if context.rental_object is None:
            fields.append("document_context.rental_object")
        else:
            for field in ("address_line", "postal_code", "city", "unit_label"):
                if not getattr(context.rental_object, field):
                    fields.append("document_context.rental_object." + field)
        if not context.contract_number:
            fields.append("document_context.contract_number")
        if context.issuer is None:
            fields.append("document_context.issuer")
        else:
            for label, identity in (("identity", context.issuer.identity),
                    *(([("landlord", context.issuer.landlord)]) if context.issuer.role == "representative" else [])):
                if identity is None:
                    fields.append("document_context.issuer." + label)
                else:
                    for field in ("name", "address_line", "postal_code", "city"):
                        if not getattr(identity, field):
                            fields.append("document_context.issuer." + label + "." + field)
    return sorted(fields)


class UtilityStatementArchiveSource(Strict):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(pattern=r"^utility-statement-archive-source/1$")
    financial_source: UtilityStatementOriginalSource
    document_context: StatementDocumentContext | None
    document_context_digest: str | None = Field(pattern=SHA)
    missing_fields: list[str]
    completeness: str = Field(pattern=r"^(complete|incomplete|unproved)$")
    archive_source_digest: str = Field(pattern=SHA)

    @model_validator(mode="after")
    def exact_archive_source(self):
        # Revalidate the existing DTO through JSON even when handed an existing
        # model instance, so mutations never bypass its financial digest checks.
        financial = validate_source(self.financial_source.model_dump(mode="json"))
        context = StatementDocumentContext.model_validate(self.document_context.model_dump(mode="json")) if self.document_context else None
        if context is not None:
            if financial.original_party is None:
                raise ValueError("Document context requires the actual frozen party")
            _same_context(context, financial.statement_original, {
                "id": financial.period_context.id, "property_id": financial.period_context.property_id,
                "start_date": financial.period_context.start_date.isoformat(), "end_date": financial.period_context.end_date.isoformat(),
            }, financial.original_party)
        expected_digest = source_digest(context.model_dump(mode="json")) if context else None
        missing = _missing(financial, context)
        completeness = "unproved" if context is None else "incomplete" if missing else "complete"
        if (self.document_context_digest != expected_digest or self.missing_fields != missing
                or self.completeness != completeness
                or self.archive_source_digest != source_digest(self.model_dump(mode="json", exclude={"archive_source_digest"}))):
            raise ValueError("Archive context digest/completeness differs")
        return self


def validate_archive_source(value):
    try:
        raw = value.model_dump(mode="json") if isinstance(value, UtilityStatementArchiveSource) else value
        return UtilityStatementArchiveSource.model_validate(raw)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise DocumentContextIntegrityError("Die ausgewählte Archivquelle ist beschädigt oder unvollständig gebunden.") from error


def build_archive_source(financial_source, document_context):
    """Root first proves actual whole period/family; this binds only its DTOs."""
    try:
        raw = financial_source.model_dump(mode="json") if isinstance(financial_source, UtilityStatementOriginalSource) else financial_source
        financial = validate_source(raw)
        raw_context = document_context.model_dump(mode="json") if isinstance(document_context, StatementDocumentContext) else document_context
        context = StatementDocumentContext.model_validate(raw_context) if raw_context is not None else None
        missing = _missing(financial, context)
        body = {"schema_version": SCHEMA, "financial_source": financial.model_dump(mode="json"),
            "document_context": context.model_dump(mode="json") if context else None,
            "document_context_digest": source_digest(context.model_dump(mode="json")) if context else None,
            "missing_fields": missing, "completeness": "unproved" if context is None else "incomplete" if missing else "complete"}
        return validate_archive_source({**body, "archive_source_digest": source_digest(body)})
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise DocumentContextIntegrityError("Archivquelle benötigt ihre tatsächlich belegten Originale.") from error


def require_complete_archive_source(value):
    source = validate_archive_source(value)
    if source.completeness != "complete":
        raise DocumentContextIntegrityError("Das vollständige Abrechnungsoriginal benötigt die belegten fehlenden Dokumentangaben: " + ", ".join(source.missing_fields))
    return source
