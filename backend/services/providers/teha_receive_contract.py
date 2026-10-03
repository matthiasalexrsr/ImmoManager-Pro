"""Pure TEHA receive identities, explicit mappings, preview and resume.

No provider call, database access, user lookup or business mutation occurs here.
Names/addresses/email values are never used as identity rules.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from itertools import islice
from typing import Any, Iterable, Literal

from .schema_observation import json_snapshot
from .teha_types import (
    TehaDocument,
    TehaDocumentContent,
    TehaOrderUser,
    TehaPropertyPeriod,
    TehaTechnicalOrder,
)

ExternalKind = Literal[
    "property",
    "period",
    "document",
    "unit",
    "user",
    "technical_order",
]
TargetKind = Literal[
    "property",
    "billing_period",
    "document",
    "unit",
    "tenant",
    "task",
]
PreviewState = Literal["new", "unchanged", "changed", "conflicting"]

_TARGET: dict[ExternalKind, TargetKind] = {
    "property": "property",
    "period": "billing_period",
    "document": "document",
    "unit": "unit",
    "user": "tenant",
    "technical_order": "task",
}


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError("TEHA evidence must be finite JSON") from None


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _component(value: str | int, name: str) -> str | int:
    if type(value) is int:
        if value < 0:
            raise ValueError(f"{name} must not be negative")
        return value
    if isinstance(value, str):
        if not value.strip() or value != value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError(f"{name} must be a nonblank stable string")
        return value
    raise TypeError(f"{name} must be string or integer")


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    kind: ExternalKind
    parts: tuple[tuple[str, str | int], ...]

    def __post_init__(self):
        if self.kind not in _TARGET:
            raise ValueError("unsupported external identity kind")
        names: set[str] = set()
        normalized = []
        for name, value in self.parts:
            if not isinstance(name, str) or not name or name in names:
                raise ValueError("identity component names must be unique")
            names.add(name)
            normalized.append((name, _component(value, name)))
        if not normalized:
            raise ValueError("external identity needs at least one component")
        if tuple(sorted(normalized)) != self.parts:
            raise ValueError("identity components must use canonical name order")

    @classmethod
    def create(cls, kind: ExternalKind, **parts: str | int) -> "ExternalIdentity":
        return cls(kind, tuple(sorted((name, _component(value, name)) for name, value in parts.items())))

    @property
    def token(self) -> str:
        return digest({"kind": self.kind, "parts": list(self.parts)})

    def private_value(self) -> dict[str, Any]:
        return {"kind": self.kind, "parts": dict(self.parts)}


def property_identity(object_id: int) -> ExternalIdentity:
    return ExternalIdentity.create("property", object_id=object_id)


def period_identity(object_id: int, period_number: int) -> ExternalIdentity:
    return ExternalIdentity.create(
        "period",
        object_id=object_id,
        period_number=period_number,
    )


def document_identity(lieg_nr: str, reference: str) -> ExternalIdentity:
    return ExternalIdentity.create("document", lieg_nr=lieg_nr, reference=reference)


def unit_identity(lieg_nr: str, unit_id: int) -> ExternalIdentity:
    return ExternalIdentity.create("unit", lieg_nr=lieg_nr, unit_id=unit_id)


def user_identity(termin_id: int, user_id: int) -> ExternalIdentity:
    return ExternalIdentity.create("user", termin_id=termin_id, user_id=user_id)


def order_identity(termin_id: int) -> ExternalIdentity:
    return ExternalIdentity.create("technical_order", termin_id=termin_id)


@dataclass(frozen=True, slots=True)
class MappingRequirement:
    identity: ExternalIdentity
    target_kind: TargetKind

    def __post_init__(self):
        if _TARGET[self.identity.kind] != self.target_kind:
            raise ValueError("mapping target does not match external identity kind")


@dataclass(frozen=True, slots=True)
class ObservedEvidence:
    history_run_id: str
    identity: ExternalIdentity
    source_snapshot: dict[str, Any] = field(repr=False)
    source_sha256: str
    requirements: tuple[MappingRequirement, ...]
    content_sha256: str | None = None
    content_size: int | None = None

    def __post_init__(self):
        if not isinstance(self.history_run_id, str) or not self.history_run_id.strip():
            raise ValueError("history_run_id is required")
        if digest(self.source_snapshot) != self.source_sha256:
            raise ValueError("source snapshot hash mismatch")
        if (self.content_sha256 is None) != (self.content_size is None):
            raise ValueError("content hash and size must be provided together")
        if self.content_sha256 is not None:
            if (
                len(self.content_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.content_sha256)
                or type(self.content_size) is not int
                or self.content_size < 0
            ):
                raise ValueError("invalid content manifest")
        tokens = [item.identity.token for item in self.requirements]
        if len(tokens) != len(set(tokens)):
            raise ValueError("mapping requirements must be unique")

    def private_source_copy(self) -> dict[str, Any]:
        return json_snapshot(self.source_snapshot)


def _evidence(
    run_id: str,
    identity: ExternalIdentity,
    source: dict[str, Any],
    requirements: Iterable[MappingRequirement],
    *,
    content_sha256: str | None = None,
    content_size: int | None = None,
) -> ObservedEvidence:
    snapshot = json_snapshot(source)
    return ObservedEvidence(
        history_run_id=run_id,
        identity=identity,
        source_snapshot=snapshot,
        source_sha256=digest(snapshot),
        requirements=tuple(requirements),
        content_sha256=content_sha256,
        content_size=content_size,
    )


def property_period_evidence(value: TehaPropertyPeriod, run_id: str) -> ObservedEvidence:
    prop = property_identity(value.object_id)
    period = period_identity(value.object_id, value.period_number)
    return _evidence(
        run_id,
        period,
        value.source_snapshot(),
        (
            MappingRequirement(prop, "property"),
            MappingRequirement(period, "billing_period"),
        ),
    )


def document_evidence(
    value: TehaDocument,
    run_id: str,
    *,
    property_key: ExternalIdentity,
    period_key: ExternalIdentity | None = None,
    unit_key: ExternalIdentity | None = None,
    user_key: ExternalIdentity | None = None,
    content: TehaDocumentContent | None = None,
) -> ObservedEvidence:
    if property_key.kind != "property":
        raise ValueError("document property relation must use property identity")
    requirements = [MappingRequirement(property_key, "property")]
    if period_key is not None:
        if period_key.kind != "period":
            raise ValueError("document period relation must use period identity")
        requirements.append(MappingRequirement(period_key, "billing_period"))
    if unit_key is not None:
        if unit_key.kind != "unit":
            raise ValueError("document unit relation must use unit identity")
        requirements.append(MappingRequirement(unit_key, "unit"))
    if user_key is not None:
        if user_key.kind != "user":
            raise ValueError("document user relation must use user identity")
        requirements.append(MappingRequirement(user_key, "tenant"))
    if content is not None:
        if content.reference != value.reference or content.lieg_nr != value.lieg_nr:
            raise ValueError("document content belongs to another provider source")
        if hashlib.sha256(content.content).hexdigest() != content.sha256:
            raise ValueError("document content hash mismatch")
    return _evidence(
        run_id,
        document_identity(value.lieg_nr, value.reference),
        value.source_snapshot(),
        requirements,
        content_sha256=content.sha256 if content is not None else None,
        content_size=content.size_bytes if content is not None else None,
    )


def technical_order_evidence(
    value: TehaTechnicalOrder,
    run_id: str,
    *,
    property_key: ExternalIdentity,
    period_key: ExternalIdentity | None = None,
) -> ObservedEvidence:
    if property_key.kind != "property":
        raise ValueError("technical order property relation must use property identity")
    requirements = [MappingRequirement(property_key, "property")]
    if period_key is not None:
        if period_key.kind != "period":
            raise ValueError("technical order period relation must use period identity")
        requirements.append(MappingRequirement(period_key, "billing_period"))
    return _evidence(
        run_id,
        order_identity(value.termin_id),
        value.source_snapshot(),
        requirements,
    )


def order_user_evidence(
    value: TehaOrderUser,
    run_id: str,
    *,
    termin_id: int,
    lieg_nr: str,
    property_key: ExternalIdentity,
) -> ObservedEvidence:
    if property_key.kind != "property":
        raise ValueError("order user property relation must use property identity")
    external_unit = unit_identity(lieg_nr, value.unit_id)
    external_user = user_identity(termin_id, value.user_id)
    return _evidence(
        run_id,
        external_user,
        value.source_snapshot(),
        (
            MappingRequirement(property_key, "property"),
            MappingRequirement(external_unit, "unit"),
            MappingRequirement(external_user, "tenant"),
        ),
    )


@dataclass(frozen=True, slots=True)
class ExplicitMapping:
    identity: ExternalIdentity
    target_kind: TargetKind
    target_id: str
    generation: int = 1

    def __post_init__(self):
        MappingRequirement(self.identity, self.target_kind)
        if not isinstance(self.target_id, str) or not self.target_id.strip():
            raise ValueError("explicit target id is required")
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("mapping generation must be positive")

    def public_binding(self) -> dict[str, Any]:
        return {
            "external_token": self.identity.token,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "generation": self.generation,
        }


class MappingIndex:
    def __init__(self, mappings: Iterable[ExplicitMapping]):
        self._by_token: dict[str, ExplicitMapping] = {}
        for mapping in mappings:
            token = mapping.identity.token
            if token in self._by_token:
                raise ValueError("duplicate external mapping")
            self._by_token[token] = mapping

    def require(self, requirement: MappingRequirement) -> ExplicitMapping:
        mapping = self._by_token.get(requirement.identity.token)
        if mapping is None:
            raise KeyError(requirement.identity.token)
        if (
            mapping.identity != requirement.identity
            or mapping.target_kind != requirement.target_kind
        ):
            raise ValueError("mapping identity or target kind changed")
        return mapping


def mapping_digest(evidence: ObservedEvidence, mappings: MappingIndex) -> str:
    selected = [
        mappings.require(requirement).public_binding()
        for requirement in evidence.requirements
    ]
    return digest(sorted(selected, key=lambda item: item["external_token"]))


@dataclass(frozen=True, slots=True)
class PriorReceipt:
    identity_token: str
    mapping_sha256: str
    source_sha256: str
    content_sha256: str | None
    local_document_version_id: str | None = None
    local_task_id: str | None = None

    def __post_init__(self):
        for value in (self.identity_token, self.mapping_sha256, self.source_sha256):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("receipt hashes must be lowercase SHA-256")
        if self.content_sha256 is not None and (
            len(self.content_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.content_sha256)
        ):
            raise ValueError("invalid receipt content hash")


@dataclass(frozen=True, slots=True)
class PreviewDecision:
    state: PreviewState
    identity_token: str
    source_sha256: str
    mapping_sha256: str | None
    content_sha256: str | None
    reasons: tuple[str, ...]


def classify_preview(
    evidence: ObservedEvidence,
    mappings: MappingIndex,
    prior: PriorReceipt | None = None,
) -> PreviewDecision:
    try:
        mapped = mapping_digest(evidence, mappings)
    except KeyError:
        return PreviewDecision(
            "conflicting",
            evidence.identity.token,
            evidence.source_sha256,
            None,
            evidence.content_sha256,
            ("mapping_required",),
        )
    except ValueError:
        return PreviewDecision(
            "conflicting",
            evidence.identity.token,
            evidence.source_sha256,
            None,
            evidence.content_sha256,
            ("mapping_conflict",),
        )
    if prior is None:
        return PreviewDecision(
            "new",
            evidence.identity.token,
            evidence.source_sha256,
            mapped,
            evidence.content_sha256,
            (),
        )
    if prior.identity_token != evidence.identity.token:
        return PreviewDecision(
            "conflicting",
            evidence.identity.token,
            evidence.source_sha256,
            mapped,
            evidence.content_sha256,
            ("identity_changed",),
        )
    if prior.mapping_sha256 != mapped:
        return PreviewDecision(
            "conflicting",
            evidence.identity.token,
            evidence.source_sha256,
            mapped,
            evidence.content_sha256,
            ("mapping_generation_changed",),
        )
    if (
        prior.source_sha256 == evidence.source_sha256
        and prior.content_sha256 == evidence.content_sha256
    ):
        return PreviewDecision(
            "unchanged",
            evidence.identity.token,
            evidence.source_sha256,
            mapped,
            evidence.content_sha256,
            (),
        )
    return PreviewDecision(
        "changed",
        evidence.identity.token,
        evidence.source_sha256,
        mapped,
        evidence.content_sha256,
        ("source_or_content_changed",),
    )


@dataclass(frozen=True, slots=True)
class ResumeCursor:
    history_run_id: str
    source_sha256: str
    offset: int

    def __post_init__(self):
        if not isinstance(self.history_run_id, str) or not self.history_run_id:
            raise ValueError("resume history run is required")
        if (
            len(self.source_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.source_sha256)
        ):
            raise ValueError("invalid resume source hash")
        if type(self.offset) is not int or self.offset < 0:
            raise ValueError("resume offset must be a nonnegative integer")


def receive_batch(
    values: Iterable[Any],
    *,
    history_run_id: str,
    source_sha256: str,
    cursor: ResumeCursor | None = None,
    batch_size: int,
) -> tuple[tuple[Any, ...], ResumeCursor | None]:
    """Consume one bounded packet without imposing a total-inventory limit."""
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    if cursor is not None and (
        cursor.history_run_id != history_run_id
        or cursor.source_sha256 != source_sha256
    ):
        raise ValueError("resume cursor belongs to another immutable source")
    offset = cursor.offset if cursor is not None else 0
    iterator = iter(values)
    for _ in range(offset):
        try:
            next(iterator)
        except StopIteration:
            return (), None
    selected = tuple(islice(iterator, batch_size + 1))
    if len(selected) <= batch_size:
        return selected, None
    return (
        selected[:batch_size],
        ResumeCursor(history_run_id, source_sha256, offset + batch_size),
    )
