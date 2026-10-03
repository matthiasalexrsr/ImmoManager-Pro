"""Strict local command DTOs for TEHA mapping and import confirmation."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


_IDENTITY_PARTS = {
    "property": {"object_id"},
    "period": {"object_id", "period_number"},
    "unit": {"lieg_nr", "unit_id"},
    "user": {"termin_id", "user_id"},
    "technical_order": {"termin_id"},
    "document": {"lieg_nr", "reference"},
}


class OpaqueIdentity(StrictModel):
    kind: Literal["property", "period", "unit", "user", "technical_order", "document"]
    parts: dict[str, StrictStr | StrictInt]

    @model_validator(mode="after")
    def exact_opaque_parts(self):
        if set(self.parts) != _IDENTITY_PARTS[self.kind]:
            raise ValueError("opaque identity contains unsupported or missing components")
        for value in self.parts.values():
            if type(value) is int:
                if value < 0:
                    raise ValueError("opaque integer identity components must not be negative")
            elif isinstance(value, str):
                if not value or value != value.strip() or any(ord(char) < 32 for char in value):
                    raise ValueError("opaque string identity components must be nonblank stable values")
            else:
                raise ValueError("opaque identity components must be strict strings or integers")
        return self


class MappingTarget(StrictModel):
    target_id: str = Field(min_length=1, max_length=100)
    expected_target_etag: str = Field(min_length=1, max_length=512)


class ConfirmMapping(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=100)
    connection_key: str = Field(min_length=1, max_length=200)
    portfolio_id: str = Field(min_length=1, max_length=100)
    identity: OpaqueIdentity
    external_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_history_run_id: str = Field(min_length=1, max_length=100)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_previous_revision: str = Field(min_length=1, max_length=100)
    target: MappingTarget


class MappingSelection(StrictModel):
    mapping_id: str = Field(min_length=1, max_length=100)
    expected_revision: str = Field(min_length=1, max_length=100)
    expected_generation: int = Field(ge=1)


class DocumentImportData(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    document_date: date | None = None
    document_type: str = Field(default="teha_document", min_length=1)
    contract_id: str | None = Field(default=None, min_length=1, max_length=100)
    expected_contract_etag: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def contract_etag_pair(self):
        if (self.contract_id is None) != (self.expected_contract_etag is None):
            raise ValueError("contract_id and expected_contract_etag belong together")
        return self


class TaskImportData(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    due_date: date | None = None
    assignee: str | None = Field(default=None, max_length=200)
    priority: str = Field(default="medium", min_length=1, max_length=30)


class PreviewImport(StrictModel):
    connection_key: str = Field(min_length=1, max_length=200)
    portfolio_id: str = Field(min_length=1, max_length=100)
    source_kind: Literal["document", "technical_order"]
    source_history_run_id: str = Field(min_length=1, max_length=100)
    content_history_run_id: str | None = Field(default=None, min_length=1, max_length=100)
    identity: OpaqueIdentity
    external_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping: MappingSelection
    document: DocumentImportData | None = None
    task: TaskImportData | None = None

    @model_validator(mode="after")
    def projection_shape(self):
        if self.source_kind == "document":
            if (
                self.identity.kind != "document"
                or self.document is None
                or self.task is not None
                or self.content_history_run_id is None
            ):
                raise ValueError(
                    "document import requires document identity, content history and document projection"
                )
        else:
            if (
                self.identity.kind != "technical_order"
                or self.task is None
                or self.document is not None
                or self.content_history_run_id is not None
            ):
                raise ValueError(
                    "technical order import requires technical_order identity and task projection"
                )
        return self


class ImportDocument(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=100)
    preview: PreviewImport
    preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_history_run_id: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def kind(self):
        if self.preview.source_kind != "document":
            raise ValueError("document command needs document preview")
        if self.preview.content_history_run_id != self.content_history_run_id:
            raise ValueError(
                "document command content run must match the reviewed preview"
            )
        return self


class ImportTechnicalOrder(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=100)
    preview: PreviewImport
    preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def kind(self):
        if self.preview.source_kind != "technical_order":
            raise ValueError("task command needs technical_order preview")
        return self
