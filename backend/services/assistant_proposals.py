"""Typed, source-bound suggestions; explicit handoff saves private drafts only."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints, model_validator

from ..workspace_models import DraftWrite
from . import assistant_context, workspace, workspace_contexts

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Money = Annotated[Decimal, Field(ge=0, decimal_places=2, allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceReference(StrictModel):
    kind: assistant_context.SourceKind
    id: Identifier


class Evidence(SourceReference):
    revision: Text
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class TaskValues(StrictModel):
    title: Text
    description: str | None = None
    due_date: date | None = None
    priority: Literal["low", "medium", "high"] = "medium"
    status: Literal["open"] = "open"
    property_id: Identifier | None = None
    unit_id: Identifier | None = None


class NoteValues(StrictModel):
    body: Text
    conversation_kind: Literal["note"] = "note"


class InvoiceValues(StrictModel):
    supplier: Text
    invoice_date: date
    due_date: date | None = None
    performance_start: date | None = None
    performance_end: date | None = None
    net_amount: Money
    vat_rate: Annotated[Decimal, Field(ge=0, le=100, decimal_places=2, allow_inf_nan=False)] = Decimal("19")
    vat_amount: Money
    gross_amount: Money
    property_id: Identifier | None = None
    payment_terms: str | None = None
    status: Literal["open"] = "open"

    @model_validator(mode="after")
    def arithmetic_and_dates(self):
        if self.net_amount + self.vat_amount != self.gross_amount:
            raise ValueError("Netto plus Umsatzsteuer muss dem Bruttobetrag entsprechen")
        expected_vat = (self.net_amount * self.vat_rate / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if self.vat_amount != expected_vat:
            raise ValueError("Die Umsatzsteuer passt nicht zum angegebenen einheitlichen Steuersatz")
        if self.due_date and self.due_date < self.invoice_date:
            raise ValueError("Fälligkeit liegt vor dem Rechnungsdatum")
        if bool(self.performance_start) != bool(self.performance_end):
            raise ValueError("Leistungsbeginn und Leistungsende gemeinsam angeben")
        if self.performance_start and self.performance_end and self.performance_end < self.performance_start:
            raise ValueError("Der Leistungszeitraum endet vor seinem Beginn")
        return self


class ProposalBase(StrictModel):
    anchor: SourceReference
    evidence: list[Evidence] = Field(min_length=1)


class TaskProposal(ProposalBase):
    kind: Literal["task"]
    values: TaskValues


class NoteProposal(ProposalBase):
    kind: Literal["note"]
    values: NoteValues


class InvoiceProposal(ProposalBase):
    kind: Literal["invoice"]
    values: InvoiceValues


class Proposal(RootModel[Annotated[TaskProposal | NoteProposal | InvoiceProposal, Field(discriminator="kind")]]):
    pass


CONTEXTS = {"task": "tasks", "note": "conversation-note", "invoice": "invoices"}


def validate_proposal(store, proposal: Proposal | dict, actor_id: str, *, context_bundle: dict | None = None) -> dict:
    parsed = Proposal.model_validate(proposal).root
    workspace_contexts.actor(actor_id, store)
    if context_bundle is not None:
        current = assistant_context.revalidate_context(store, context_bundle, actor_id)
        permitted = {(source["kind"], source["id"]) for source in current["sources"]}
    else:
        permitted = None
    references = {(row.kind, row.id) for row in parsed.evidence}
    if len(references) != len(parsed.evidence):
        raise HTTPException(422, "Eine Quelle darf nur einmal belegt werden.")
    if (parsed.anchor.kind, parsed.anchor.id) not in references:
        raise HTTPException(422, "Der Entwurfsbezug muss durch eine freigegebene Quelle belegt sein.")
    if permitted is not None and not references.issubset(permitted):
        raise HTTPException(422, "Der Vorschlag enthält Quellen außerhalb des gewählten Kontexts.")
    evidence = []
    for ref in parsed.evidence:
        source = assistant_context._source(store, ref.kind, ref.id, actor_id)
        if source["revision"] != ref.revision or source["sha256"] != ref.sha256:
            raise HTTPException(409, {"code": "assistant_evidence_changed",
                                      "message": "Eine Vorschlagsquelle wurde geändert. Bitte neu prüfen."})
        evidence.append({key: source[key] for key in ("kind", "id", "revision", "sha256", "title", "href")})
    values = parsed.values.model_dump(mode="json", exclude_none=True)
    for field, kind in (("property_id", "property"), ("unit_id", "unit")):
        if values.get(field) and (kind, values[field]) not in references:
            raise HTTPException(422, "Jeder Entwurfsbezug muss ausdrücklich als Quelle gewählt und belegt sein.")
    if values.get("unit_id"):
        unit = workspace_contexts.resolve_context(store, "unit", values["unit_id"], actor_id)
        if values.get("property_id") and unit["values"]["property_id"] != values["property_id"]:
            raise HTTPException(422, "Die Einheit gehört nicht zur gewählten Immobilie.")
    if parsed.kind == "invoice" and not any(ref.kind == "document" for ref in parsed.evidence):
        raise HTTPException(422, "Ein Rechnungsvorschlag braucht einen ausdrücklich freigegebenen Dokumentbeleg.")
    context = CONTEXTS[parsed.kind]
    # This is the same role/reference/field validation used by human drafts.
    workspace_contexts.check_context(actor_id, context, edit=True)
    workspace_contexts.validate_values(store, context, values, actor_id)
    normalized = parsed.model_dump(mode="json")
    warnings = ["Vorschlag prüfen: Quellenbindung belegt die Herkunft, nicht die fachliche Richtigkeit des Modelltextes."]
    if parsed.kind == "invoice":
        warnings.append("Beträge, Steuersatz und Leistungszeitraum anhand des Originals bestätigen; keine Buchung oder Rechnungsfreigabe erfolgt.")
    review: dict[str, Any] = {"proposal": normalized, "normalized": normalized, "context": context,
                              "evidence": evidence, "warnings": warnings, "allowed": True,
                              "domain_writes": False, "confirmation_required": True}
    review["review_hash"] = assistant_context.content_hash(review)
    return review


def handoff_proposal(store, proposal: Proposal | dict, actor_id: str, *, draft_id: str,
                     base_revision: int = 0, idempotency_key: str, review_hash: str,
                     context_bundle: dict | None = None, unit=None) -> dict:
    """The caller records its own decision; this function only stores a draft.

No arbitrary route, command, URL, publish flag or financial operation is accepted.
    All context and evidence rows are checked inside the workspace transaction.
"""
    review = validate_proposal(store, proposal, actor_id, context_bundle=context_bundle)
    if review["review_hash"] != review_hash:
        raise HTTPException(409, "Der Vorschlag wurde nach der Prüfung geändert. Bitte erneut prüfen.")
    normalized = review["normalized"]
    anchor = normalized["anchor"]
    source = next(ref for ref in review["evidence"] if (ref["kind"], ref["id"]) == (anchor["kind"], anchor["id"]))
    values = normalized["values"]
    # None stays absent so existing form widgets receive their usual wire values.
    values = {key: value for key, value in values.items() if value is not None}
    body = DraftWrite(base_revision=base_revision, idempotency_key=idempotency_key,
                      context=review["context"], anchor=anchor, anchor_revision=source["revision"],
                      field_keys=sorted(values), form_key="", values=values)

    def preflight(locked_unit):
        refs = {(ref["kind"], ref["id"]) for ref in review["evidence"]}
        if context_bundle is not None:
            refs |= {(ref["kind"], ref["id"]) for ref in context_bundle["sources"]}
        for kind, identifier in sorted(refs):
            workspace_contexts.resolve_context(locked_unit.store, kind, identifier, actor_id, lock=True)
        locked_review = validate_proposal(locked_unit.store, proposal, actor_id, context_bundle=context_bundle)
        if locked_review["review_hash"] != review_hash:
            raise HTTPException(409, "Die Vorschlagsgrundlage wurde geändert. Bitte erneut prüfen.")

    draft = workspace.mutate(store, actor_id, "drafts", draft_id, body.model_dump(mode="json"),
                             source_guard=(anchor["kind"], anchor["id"], source["revision"]),
                             unit=unit, preflight=preflight)
    return {"draft": draft, "draft_id": draft["id"], "draft_revision": draft["revision"],
            "context": review["context"], "review_hash": review["review_hash"],
            "href": "/work-center", "to": {"task": "/tasks?neu=1", "invoice": "/invoices?neu=1", "note": "/work-center"}[normalized["kind"]],
            "state": {"prefill": values, "assistant_draft_id": draft["id"]},
            "anchor": anchor, "anchor_revision": source["revision"], "values": values,
            "title": source["title"], "domain_writes": False}
