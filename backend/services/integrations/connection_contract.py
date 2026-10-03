"""DDL-free connection/provenance contract for integration package I.

Persistence of provider_connections and accepted mappings is deliberately left
for the migration slot owned by Root/domain_sol. These types prevent discovery,
observation, business mapping and acceptance from collapsing into one flag.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from .base import IntegrationManifest

Location = Literal["config", "request", "response"]
EvidenceStage = Literal["discovered", "observed", "mapped", "accepted"]


@dataclass(frozen=True, slots=True)
class ParameterEvidence:
    name: str
    location: Location
    expected_type: str = "unknown"
    required: bool = False
    secret: bool = False
    discovered: bool = False
    observed: bool = False
    mapped: bool = False
    accepted: bool = False
    business_field: str | None = None
    evidence_source: str | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("parameter name must be nonblank")
        if self.accepted and not self.mapped:
            raise ValueError("accepted parameters require an explicit business mapping")
        if self.mapped and not self.business_field:
            raise ValueError("mapped parameters require business_field")
        if self.business_field is not None and not self.business_field.strip():
            raise ValueError("business_field must be nonblank")


def manifest_parameters(manifest: IntegrationManifest) -> tuple[ParameterEvidence, ...]:
    """Only facts actually declared by the current provider manifest."""
    required = set(manifest.required_config_keys)
    secrets = set(manifest.secret_config_keys)
    return tuple(
        ParameterEvidence(
            name=name,
            location="config",
            required=name in required,
            secret=name in secrets,
            discovered=True,
            evidence_source=f"manifest:{manifest.integration_id}",
        )
        for name in sorted(required | secrets)
    )


def mark_observed(record: ParameterEvidence, *, source: str) -> ParameterEvidence:
    if not isinstance(source, str) or not source.strip():
        raise ValueError("observed evidence source is required")
    return replace(record, observed=True, evidence_source=source.strip())


def map_business_field(
    record: ParameterEvidence,
    *,
    business_field: str,
    source: str,
) -> ParameterEvidence:
    if not isinstance(business_field, str) or not business_field.strip():
        raise ValueError("business_field is required")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("mapping evidence source is required")
    return replace(
        record,
        mapped=True,
        business_field=business_field.strip(),
        evidence_source=source.strip(),
    )


def accept_mapping(record: ParameterEvidence, *, source: str) -> ParameterEvidence:
    if not record.mapped or not record.business_field:
        raise ValueError("only explicitly mapped parameters can be accepted")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("acceptance evidence source is required")
    return replace(record, accepted=True, evidence_source=source.strip())


@dataclass(frozen=True, slots=True)
class ConnectionProbeResult:
    integration_id: str
    status: Literal[
        "configuration_invalid",
        "not_supported",
        "checked",
        "failed",
    ]
    configured: bool
    probe_supported: bool
    network_checked: bool
    business_action_performed: bool
    test_message_sent: bool
    details: dict[str, Any]


def local_probe_result(
    integration_id: str,
    *,
    configured: bool,
    validation: dict[str, Any],
    supported: bool = False,
) -> ConnectionProbeResult:
    """Default connection-test result; deliberately performs no provider I/O."""
    return ConnectionProbeResult(
        integration_id=integration_id,
        status=(
            "not_supported"
            if configured and not supported
            else "configuration_invalid"
            if not configured
            else "checked"
        ),
        configured=configured,
        probe_supported=supported,
        network_checked=False,
        business_action_performed=False,
        test_message_sent=False,
        details={
            "validation": validation,
            "mail_test_policy": "explicit_outbox_recipient_only",
            "automatic_external_retry": False,
        },
    )
