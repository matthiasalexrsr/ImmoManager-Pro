"""Reviewed dispute commands refer to one unchanged billing original."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DisputeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1)
    evidence_version_ids: tuple[str, ...] = ()
    preview_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("reason", "idempotency_key")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Eine nachvollziehbare Begründung und Befehlskennung sind erforderlich.")
        return value

    @field_validator("evidence_version_ids")
    @classmethod
    def distinct(cls, value):
        if len(set(value)) != len(value) or any(not item.strip() for item in value):
            raise ValueError("Anlagen benötigen eindeutige Originalkennungen.")
        return value


class OpenDispute(DisputeCommand):
    expected_case_revision: Literal[0] = 0
    case_kind: Literal["tenant_statement", "property_review"] = "tenant_statement"
    period_id: str = Field(min_length=1)
    statement_id: str | None = None
    expected_statement_revision: int | None = Field(default=None, ge=1, strict=True)
    expected_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    received_on: date
    line_item_refs: tuple[int, ...] = ()

    @model_validator(mode="after")
    def reference(self):
        if self.case_kind == "tenant_statement":
            if not self.statement_id or self.expected_statement_revision is None:
                raise ValueError("Die konkrete Einzelabrechnung samt Revision ist erforderlich.")
        elif self.statement_id is not None or self.expected_statement_revision is not None or self.line_item_refs:
            raise ValueError("Eine Objektprüfung darf keiner zufälligen Mietpartei zugeordnet werden.")
        if len(set(self.line_item_refs)) != len(self.line_item_refs) or any(index < 0 for index in self.line_item_refs):
            raise ValueError("Beanstandete Positionen benötigen eindeutige Originalindizes.")
        return self


class AppendDisputeEvent(DisputeCommand):
    expected_revision: int = Field(ge=1, strict=True)
    kind: Literal["note", "in_review", "correction", "withdrawn", "closed", "reopened", "correction_link"]
    observed_on: date
    corrects_event_id: str | None = None
    correction_statement_id: str | None = None

    @model_validator(mode="after")
    def references(self):
        if (self.kind == "correction") != bool(self.corrects_event_id):
            raise ValueError("Eine Berichtigung benennt genau das unveränderte Originalereignis.")
        if (self.kind == "correction_link") != bool(self.correction_statement_id):
            raise ValueError("Die Verknüpfung benennt eine tatsächlich erzeugte Korrekturabrechnung.")
        return self
