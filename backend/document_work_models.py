"""Persisted document commands; no document bytes or money ledger here."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentWorkEvent(BaseModel):
    id: str
    document_id: str
    portfolio_id: str
    protocol_id: str | None = None
    actor_id: str
    kind: Literal["archive", "session", "annotations", "export", "analysis", "invoice_proposal", "invoice_taken", "evidence", "version"]
    resource_id: str
    revision: int = Field(ge=1)
    command_key: str
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload: dict
    created_at: datetime


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_key: str = Field(min_length=1, max_length=100)
    expected_version: str | None = None
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_document_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class OpenSession(Command):
    mode: Literal["docx", "text", "annotations"]


class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["highlight", "comment", "text", "freehand", "stamp", "drawn_signature", "image_signature"]
    id: str | None = Field(default=None, pattern=r"^[a-f0-9-]{36}$")
    page: int = Field(ge=0)
    # Unrotated page points, top left origin; rotation is displayed-page rotation.
    rect: tuple[float, float, float, float]
    rotation: Literal[0, 90, 180, 270] = 0
    text: str = Field(default="", max_length=10000)
    points: list[tuple[float, float]] = Field(default_factory=list, max_length=10000)
    image_base64: str | None = Field(default=None, max_length=8_000_000)


class AnnotationSave(Command):
    session_revision: int = Field(ge=0)
    annotations: list[Annotation] = Field(max_length=2000)


class SessionRebase(Command):
    session_revision: int = Field(ge=1)
    confirmed_comparison: Literal[True]


class ExportRequest(Command):
    operation: Literal["copy", "flatten", "rotate", "pages", "insert", "merge", "split", "crop", "forms",
                       "redact", "edit_content", "optimize", "ocr", "docx_pdf"]
    options: dict = Field(default_factory=dict)
    sources: list[dict[str, str]] = Field(default_factory=list, max_length=100)


class InvoiceTakeover(Command):
    proposal_id: str
    confirmed: Literal[True]
    # Reuse the complete existing review receipt contract, including VAT/Skonto.
    receipt: dict
    field_sources: dict[str, str]


class EvidenceRequest(Command):
    protocol_id: str
    expected_protocol_revision: str
    purpose: Literal["original_photo", "signed_return"]


class EvidenceUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_key: str = Field(min_length=1, max_length=100)
    expected_protocol_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    purpose: Literal["original_photo", "signed_return"]
