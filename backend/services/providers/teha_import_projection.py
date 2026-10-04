"""Pure TEHA -> existing Document/Task projections.

The projections are deliberately not persistence functions. They require an
already reviewed mapping and immutable source/content hashes and never create a
booking, receivable, invoice, cost item or provider-side action.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ...models import DocumentCreate, TaskCreate
from .teha_receive_contract import ObservedEvidence, PreviewDecision

_SHA = re.compile(r"^[0-9a-f]{64}$")


def _id(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError(f"{name} must be a nonblank stable id")
    return value


def _text(value: str, name: str, *, maximum: int | None = 500, trim: bool = True) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text")
    value = value.strip() if trim else value
    if (
        not value.strip()
        or (maximum is not None and len(value) > maximum)
        or any(ord(char) < 32 and char not in "\n\t" for char in value)
    ):
        raise ValueError(f"{name} is invalid")
    return value


def _confirmed(decision: PreviewDecision, evidence: ObservedEvidence) -> None:
    if decision.identity_token != evidence.identity.token:
        raise ValueError("preview belongs to another external identity")
    if decision.source_sha256 != evidence.source_sha256:
        raise ValueError("preview belongs to another source revision")
    if decision.content_sha256 != evidence.content_sha256:
        raise ValueError("preview belongs to another content revision")
    if decision.state not in {"new", "changed"} or decision.mapping_sha256 is None:
        raise ValueError("only reviewed new/changed evidence can be projected")


@dataclass(frozen=True, slots=True)
class ImportProvenance:
    history_run_id: str
    external_identity_token: str
    source_sha256: str
    mapping_sha256: str
    content_sha256: str | None

    def __post_init__(self):
        _id(self.history_run_id, "history_run_id")
        for name in (
            "external_identity_token",
            "source_sha256",
            "mapping_sha256",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase SHA-256")
        if self.content_sha256 is not None and not _SHA.fullmatch(
            self.content_sha256
        ):
            raise ValueError("content_sha256 must be a lowercase SHA-256")

    def safe_description(self) -> str:
        """Stable non-PII receipt reference for ordinary domain metadata."""
        return (
            "TEHA import provenance: "
            f"history_run={self.history_run_id}; "
            f"external={self.external_identity_token}; "
            f"source_sha256={self.source_sha256}; "
            f"mapping_sha256={self.mapping_sha256}"
            + (
                f"; content_sha256={self.content_sha256}"
                if self.content_sha256 is not None
                else ""
            )
        )


@dataclass(frozen=True, slots=True)
class DocumentImportProjection:
    document: DocumentCreate
    provenance: ImportProvenance
    expected_content_sha256: str
    expected_content_size: int

    def __post_init__(self):
        if not _SHA.fullmatch(self.expected_content_sha256):
            raise ValueError("document content SHA-256 is invalid")
        if type(self.expected_content_size) is not int or self.expected_content_size < 0:
            raise ValueError("document content size is invalid")


@dataclass(frozen=True, slots=True)
class TaskImportProjection:
    task: TaskCreate
    provenance: ImportProvenance


def document_projection(
    evidence: ObservedEvidence,
    decision: PreviewDecision,
    *,
    property_id: str,
    title: str,
    document_date: date | None = None,
    unit_id: str | None = None,
    contract_id: str | None = None,
    document_type: str = "teha_document",
) -> DocumentImportProjection:
    """Project one reviewed PDF into the existing immutable document domain."""
    _confirmed(decision, evidence)
    mapping_sha256 = decision.mapping_sha256
    assert mapping_sha256 is not None
    if evidence.identity.kind != "document":
        raise ValueError("document projection requires document evidence")
    if evidence.content_sha256 is None or evidence.content_size is None:
        raise ValueError("document bytes must be fetched and hashed first")
    property_id = _id(property_id, "property_id")
    unit_id = _id(unit_id, "unit_id") if unit_id is not None else None
    contract_id = (
        _id(contract_id, "contract_id") if contract_id is not None else None
    )
    title = _text(title, "title")
    document_type = _text(document_type, "document_type", maximum=None, trim=False)
    provenance = ImportProvenance(
        history_run_id=evidence.history_run_id,
        external_identity_token=evidence.identity.token,
        source_sha256=evidence.source_sha256,
        mapping_sha256=mapping_sha256,
        content_sha256=evidence.content_sha256,
    )
    # Reserved local key only. The future transactional importer must create the
    # Document and persist the already verified provider bytes through the
    # existing DocumentVersion chunk core; generic /documents/import must not
    # fetch or re-download the provider source.
    file_url = (
        "/uploads/teha-import/"
        f"{evidence.identity.token}-{evidence.content_sha256[:16]}.pdf"
    )
    document = DocumentCreate(
        property_id=property_id,
        unit_id=unit_id,
        contract_id=contract_id,
        title=title,
        document_type=document_type,
        document_date=document_date,
        tags="teha",
        description=provenance.safe_description(),
        file_url=file_url,
    )
    return DocumentImportProjection(
        document=document,
        provenance=provenance,
        expected_content_sha256=evidence.content_sha256,
        expected_content_size=evidence.content_size,
    )


def task_projection(
    evidence: ObservedEvidence,
    decision: PreviewDecision,
    *,
    property_id: str,
    title: str,
    unit_id: str | None = None,
    due_date: date | None = None,
    assignee: str | None = None,
    priority: str = "medium",
) -> TaskImportProjection:
    """Project an explicitly mapped technical order as an open local task.

    Provider status/user flags never auto-complete the task. A future import
    command may compare provider changes, but completion remains a local fact.
    """
    _confirmed(decision, evidence)
    mapping_sha256 = decision.mapping_sha256
    assert mapping_sha256 is not None
    if evidence.identity.kind != "technical_order":
        raise ValueError("task projection requires technical-order evidence")
    property_id = _id(property_id, "property_id")
    unit_id = _id(unit_id, "unit_id") if unit_id is not None else None
    title = _text(title, "title")
    assignee = _text(assignee, "assignee", maximum=200) if assignee else None
    priority = _text(priority, "priority", maximum=30)
    provenance = ImportProvenance(
        history_run_id=evidence.history_run_id,
        external_identity_token=evidence.identity.token,
        source_sha256=evidence.source_sha256,
        mapping_sha256=mapping_sha256,
        content_sha256=None,
    )
    task = TaskCreate(
        title=title,
        description=provenance.safe_description(),
        assignee=assignee,
        due_date=due_date,
        priority=priority,
        status="open",
        property_id=property_id,
        unit_id=unit_id,
        recurrence_rule=None,
        parent_task_id=None,
    )
    return TaskImportProjection(task=task, provenance=provenance)
