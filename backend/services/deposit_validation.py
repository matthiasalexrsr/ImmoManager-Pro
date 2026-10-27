"""Pure validation of a finalized deposit settlement's archived evidence.

The archived original of a deposit settlement (Kautionsabrechnung, or the later
release of a retention) carries, next to the PDF, the reviewed facts the PDF was
rendered from (metadata `deposit-settlement/1`). This module checks that evidence
against the generic version manifest; it runs on live reads, on snapshot imports
and on backup verification (document_version_validation.validate_feature_snapshot).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .housing_confirmation_validation import digest

DOC_TYPE = "deposit_settlement"
VIRTUAL_PREFIX = "deposit-settlements/"
SCHEMA_VERSION = "deposit-settlement/1"
PDF_FORMAT_VERSION = "deposit-settlement-pdf/1"
# 2: a letter in the shared letterhead frame (source["letter"]); archived settlements of format 1 stay valid
LETTERHEAD_FORMAT_VERSION = "deposit-settlement-pdf/2"
_HASH = re.compile(r"^[a-f0-9]{64}$")
EXTENSION_KEYS = frozenset({"schema_version", "review", "review_hash", "request_sha256", "actor_id",
                            "idempotency_key", "deposit_id", "settlement_id", "confirmed", "payout_account_id"})
REVIEW_KEYS = frozenset({"format_version", "deposit", "settlement", "items", "receipts", "interest", "outcome",
                         "previous", "source", "pdf_sha256"})
SOURCE_KEYS = frozenset({"portfolio", "property", "unit", "contract", "tenant", "etags"})
OUTCOME_KEYS = frozenset({"principal", "interest", "credit", "new_claims", "offsets", "retention", "claims",
                          "result", "payout", "remaining_claim", "covered"})


class DepositValidationError(ValueError):
    pass


def _value(row: Any, name: str):
    return row.get(name) if isinstance(row, Mapping) else getattr(row, name, None)


def document_id_for(actor_id: str, command_key: str) -> str:
    """The same actor and command key always name the same document (safe retry)."""
    return str(uuid5(NAMESPACE_URL, f"immo-manager:deposit-settlement:v1:{actor_id}:{command_key}"))


def finalize_request_hash(settlement_id: str, payload: Mapping[str, Any]) -> str:
    return digest({"operation": "finalize_deposit_settlement", "settlement_id": settlement_id,
                   "payload": dict(payload)})


def validate_deposit_snapshot(row: Any, snapshot: Mapping[str, Any]) -> dict:
    """The extension of a deposit settlement original, checked; {} for other documents."""
    if snapshot.get("document_type") != DOC_TYPE:
        return {}
    extension = snapshot.get("deposit_settlement")
    if not isinstance(extension, dict) or set(extension) != EXTENSION_KEYS:
        raise DepositValidationError("invalid deposit settlement evidence shape")
    if extension["schema_version"] != SCHEMA_VERSION:
        raise DepositValidationError("unsupported deposit settlement schema")
    if (extension["actor_id"] != _value(row, "actor_id") or extension["request_sha256"] != _value(row, "request_sha256")
            or not isinstance(extension["review_hash"], str) or not _HASH.fullmatch(extension["review_hash"])
            or extension["confirmed"] is not True):
        raise DepositValidationError("invalid deposit settlement finalization proof")
    review = extension["review"]
    if not isinstance(review, dict) or set(review) != REVIEW_KEYS:
        raise DepositValidationError("invalid deposit settlement review")
    if review["format_version"] not in (PDF_FORMAT_VERSION, LETTERHEAD_FORMAT_VERSION):
        raise DepositValidationError("unsupported deposit settlement PDF format")
    if review["pdf_sha256"] != _value(row, "sha256") or digest(review) != extension["review_hash"]:
        raise DepositValidationError("deposit settlement review hash mismatch")
    settlement, deposit = review["settlement"], review["deposit"]
    if (not isinstance(settlement, dict) or settlement.get("id") != extension["settlement_id"]
            or not isinstance(deposit, dict) or deposit.get("id") != extension["deposit_id"]
            or settlement.get("deposit_id") != deposit.get("id")):
        raise DepositValidationError("deposit settlement identity mismatch")
    if settlement.get("kind") not in ("final", "retention_release") or not isinstance(
            settlement.get("settlement_date"), str):
        raise DepositValidationError("invalid deposit settlement header")
    if not isinstance(review["items"], list) or not all(
            isinstance(item, dict) and isinstance(item.get("id"), str) for item in review["items"]):
        raise DepositValidationError("invalid deposit settlement items")
    outcome = review["outcome"]
    if not isinstance(outcome, dict) or set(outcome) != OUTCOME_KEYS:
        raise DepositValidationError("invalid deposit settlement outcome")
    source = review["source"]
    keys = SOURCE_KEYS | {"letter"} if review["format_version"] == LETTERHEAD_FORMAT_VERSION else SOURCE_KEYS
    if not isinstance(source, dict) or set(source) != keys or not all(isinstance(source[name], dict) for name in keys):
        raise DepositValidationError("invalid deposit settlement source snapshot")
    expected = {"portfolio": _value(row, "portfolio_id"), "property": _value(row, "property_id"),
                "unit": _value(row, "unit_id"), "contract": _value(row, "contract_id"),
                "tenant": _value(row, "tenant_id")}
    if any(source[name].get("id") != identifier for name, identifier in expected.items()):
        raise DepositValidationError("deposit settlement source identity mismatch")
    contract = source["contract"]
    if (contract.get("property_id") != expected["property"] or contract.get("unit_id") != expected["unit"]
            or contract.get("tenant_id") != expected["tenant"] or deposit.get("contract_id") != expected["contract"]
            or source["unit"].get("property_id") != expected["property"]
            or source["property"].get("portfolio_id") != expected["portfolio"]):
        raise DepositValidationError("deposit settlement source relationship mismatch")
    previous = review["previous"]
    if previous is not None and (not isinstance(previous, dict) or not all(
            isinstance(previous.get(name), str) for name in ("settlement_id", "document_id", "version_id"))):
        raise DepositValidationError("invalid deposit settlement reference")

    document_id = _value(row, "document_id")
    key, actor_id = extension["idempotency_key"], extension["actor_id"]
    if (not isinstance(key, str) or not 1 <= len(key) <= 100 or not isinstance(actor_id, str) or not actor_id
            or document_id != document_id_for(actor_id, key)
            or _value(row, "idempotency_key") != "generated-" + document_id):
        raise DepositValidationError("deposit settlement command identity mismatch")
    if (snapshot.get("id") != document_id or snapshot.get("contract_id") != expected["contract"]
            or snapshot.get("property_id") != expected["property"] or snapshot.get("unit_id") != expected["unit"]
            or snapshot.get("file_url") != f"/uploads/{VIRTUAL_PREFIX}{document_id}.pdf"
            or snapshot.get("document_date") != settlement["settlement_date"]):
        raise DepositValidationError("deposit settlement document binding mismatch")
    payload = {"idempotency_key": key, "review_hash": extension["review_hash"], "confirmed": True,
               "payout_account_id": extension["payout_account_id"]}
    if finalize_request_hash(extension["settlement_id"], payload) != extension["request_sha256"]:
        raise DepositValidationError("deposit settlement request hash mismatch")
    return extension
