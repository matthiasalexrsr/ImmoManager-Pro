"""Strict command schemas for tenancy workflow templates and change files."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Direction = Literal["move_in", "move_out"]
Requirement = Literal["required", "optional"]
Anchor = Literal[
    "previous_contract_end",
    "next_contract_start",
    "move_out_handover",
    "move_in_handover",
]
EvidenceRequirement = Literal["none", "document_original", "handover_protocol", "meter_reading"]
Mode = Literal["move_out", "move_in", "turnover"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TemplateStepInput(Strict):
    stable_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    position: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    default_requirement: Requirement
    anchor: Anchor
    offset_days: int
    assignee_user_id: str | None = Field(default=None, min_length=1, max_length=100)
    assignee_role: str | None = Field(default=None, min_length=1, max_length=32)
    depends_on_step_keys: list[str] = Field(default_factory=list)
    evidence_requirement: EvidenceRequirement = "none"

    @model_validator(mode="after")
    def one_assignment(self):
        if bool(self.assignee_user_id) == bool(self.assignee_role):
            raise ValueError("Verantwortung benötigt genau einen Benutzer oder eine Rolle.")
        if len(self.depends_on_step_keys) != len(set(self.depends_on_step_keys)):
            raise ValueError("Abhängigkeiten dürfen nicht doppelt vorkommen.")
        return self


class CreateTemplate(Strict):
    idempotency_key: str = Field(min_length=1, max_length=100)
    expected_revision: Literal["new"]
    property_id: str = Field(min_length=1, max_length=100)
    unit_id: str | None = Field(default=None, min_length=1, max_length=100)
    direction: Direction
    steps: list[TemplateStepInput] = Field(min_length=1)


class CreateTemplateVersion(Strict):
    idempotency_key: str = Field(min_length=1, max_length=100)
    expected_revision: str = Field(min_length=1, max_length=100)
    based_on_version_id: str = Field(min_length=1, max_length=100)


class UpdateTemplateVersion(Strict):
    idempotency_key: str = Field(min_length=1, max_length=100)
    expected_revision: str = Field(min_length=1, max_length=100)
    steps: list[TemplateStepInput] = Field(min_length=1)


class PublishTemplateVersion(Strict):
    idempotency_key: str = Field(min_length=1, max_length=100)
    expected_revision: str = Field(min_length=1, max_length=100)


class ChangeSelection(Strict):
    property_id: str = Field(min_length=1, max_length=100)
    unit_id: str = Field(min_length=1, max_length=100)
    previous_contract_id: str | None = Field(default=None, min_length=1, max_length=100)
    next_contract_id: str | None = Field(default=None, min_length=1, max_length=100)
    mode: Mode
    move_out_handover_date: date | None = None
    move_in_handover_date: date | None = None
    move_out_template_version_id: str | None = Field(default=None, min_length=1, max_length=100)
    move_in_template_version_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def direction_requirements(self):
        if self.mode in {"move_out", "turnover"}:
            if not self.previous_contract_id or not self.move_out_template_version_id:
                raise ValueError("Auszug benötigt Altvertrag und veröffentlichte Auszugsvorlage.")
        elif self.previous_contract_id or self.move_out_template_version_id:
            raise ValueError("Ein reiner Einzug darf keinen Auszugsvertrag/-vorlage enthalten.")
        if self.mode in {"move_in", "turnover"}:
            if not self.next_contract_id or not self.move_in_template_version_id:
                raise ValueError("Einzug benötigt Neuvertrag und veröffentlichte Einzugsvorlage.")
        elif self.next_contract_id or self.move_in_template_version_id:
            raise ValueError("Ein reiner Auszug darf keinen Einzugsvertrag/-vorlage enthalten.")
        if self.previous_contract_id and self.next_contract_id == self.previous_contract_id:
            raise ValueError("Alt- und Neuvertrag müssen verschieden sein.")
        return self


class PreviewTenancyChange(ChangeSelection):
    pass


class StartTenancyChange(ChangeSelection):
    idempotency_key: str = Field(min_length=1, max_length=100)
    expected_revision: Literal["new"]
    preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_etags: dict[str, str] = Field(min_length=1, max_length=4)


class PatchTenancyChange(Strict):
    idempotency_key: str = Field(min_length=1, max_length=100)
    expected_revision: str = Field(min_length=1, max_length=100)
    state: Literal["cancelled"]
    reason: str = Field(min_length=1, max_length=1000)


class ReanchorPreview(Strict):
    expected_revision: str = Field(min_length=1, max_length=100)
    move_out_handover_date: date | None = None
    move_in_handover_date: date | None = None


class ReanchorTenancyChange(ReanchorPreview):
    idempotency_key: str = Field(min_length=1, max_length=100)
    preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_etags: dict[str, str] = Field(max_length=4)


class UpdateStep(Strict):
    idempotency_key: str = Field(min_length=1, max_length=100)
    expected_revision: str = Field(min_length=1, max_length=100)
    expected_change_revision: str = Field(min_length=1, max_length=100)
    state: Literal["open", "in_progress", "completed", "not_applicable"]
    not_applicable_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def reason_required(self):
        if self.state == "not_applicable" and not (self.not_applicable_reason or "").strip():
            raise ValueError("Nicht zutreffend benötigt einen bewussten Grund.")
        if self.state != "not_applicable" and self.not_applicable_reason is not None:
            raise ValueError("Ausnahmegrund ist nur für not_applicable zulässig.")
        return self


class CreateStepTask(Strict):
    idempotency_key: str = Field(min_length=1, max_length=100)
    expected_revision: str = Field(min_length=1, max_length=100)
    expected_change_revision: str = Field(min_length=1, max_length=100)


class EvidenceInput(Strict):
    kind: Literal["document_version", "handover_protocol", "meter_reading"]
    document_id: str | None = Field(default=None, max_length=100)
    document_version_id: str | None = Field(default=None, max_length=100)
    handover_protocol_id: str | None = Field(default=None, max_length=100)
    meter_reading_id: str | None = Field(default=None, max_length=100)


class AddEvidence(Strict):
    idempotency_key: str = Field(min_length=1, max_length=100)
    expected_revision: str = Field(min_length=1, max_length=100)
    expected_change_revision: str = Field(min_length=1, max_length=100)
    evidence: EvidenceInput


class RemoveEvidence(Strict):
    idempotency_key: str = Field(min_length=1, max_length=100)
    expected_revision: str = Field(min_length=1, max_length=100)
    expected_change_revision: str = Field(min_length=1, max_length=100)


class CompleteTenancyChange(Strict):
    idempotency_key: str = Field(min_length=1, max_length=100)
    expected_revision: str = Field(min_length=1, max_length=100)
