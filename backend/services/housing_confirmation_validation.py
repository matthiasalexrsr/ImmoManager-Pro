"""Pure validation of retained Wohnungsgeberbestätigung evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError as PydanticValidationError

from .housing_confirmation_types import CertificateData, CorrectionReference, SourceEtags

SCHEMA_VERSION = "housing-confirmation/1"
PDF_FORMAT_VERSION = "housing-confirmation-pdf/1"
_HASH = re.compile(r"^[a-f0-9]{64}$")


class HousingConfirmationValidationError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _value(row: Any, name: str):
    return row.get(name) if isinstance(row, Mapping) else getattr(row, name, None)


def validate_housing_confirmation_snapshot(row: Any, snapshot: Mapping[str, Any]) -> dict:
    """Validate immutable feature metadata against the generic version manifest."""
    if snapshot.get("document_type") != "housing_confirmation":
        return {}
    extension = snapshot.get("housing_confirmation")
    if not isinstance(extension, dict):
        raise HousingConfirmationValidationError("missing housing confirmation evidence")
    if set(extension) != {
        "schema_version",
        "review",
        "review_hash",
        "request_sha256",
        "actor_id",
        "idempotency_key",
        "confirmed_actual_move_in",
        "confirmed_authority",
        "confirmed_residents",
    }:
        raise HousingConfirmationValidationError("invalid housing confirmation evidence shape")
    if extension["schema_version"] != SCHEMA_VERSION:
        raise HousingConfirmationValidationError("unsupported housing confirmation schema")
    if (
        extension["actor_id"] != _value(row, "actor_id")
        or extension["request_sha256"] != _value(row, "request_sha256")
        or not isinstance(extension["review_hash"], str)
        or not _HASH.fullmatch(extension["review_hash"])
        or any(
            extension[name] is not True
            for name in (
                "confirmed_actual_move_in",
                "confirmed_authority",
                "confirmed_residents",
            )
        )
    ):
        raise HousingConfirmationValidationError("invalid housing confirmation publication proof")

    review = extension["review"]
    if not isinstance(review, dict) or set(review) != {
        "format_version",
        "data",
        "source",
        "correction_of",
        "pdf_sha256",
    }:
        raise HousingConfirmationValidationError("invalid housing confirmation review")
    if review["format_version"] != PDF_FORMAT_VERSION:
        raise HousingConfirmationValidationError("unsupported housing confirmation PDF format")
    if review["pdf_sha256"] != _value(row, "sha256") or digest(review) != extension["review_hash"]:
        raise HousingConfirmationValidationError("housing confirmation review hash mismatch")
    try:
        data = CertificateData.model_validate(review["data"])
        source_etags = SourceEtags.model_validate(review["source"]["etags"])
        correction = (
            CorrectionReference.model_validate(review["correction_of"])
            if review["correction_of"] is not None
            else None
        )
    except (PydanticValidationError, KeyError, TypeError):
        raise HousingConfirmationValidationError("invalid housing confirmation typed evidence") from None
    if data.model_dump(mode="json") != review["data"]:
        raise HousingConfirmationValidationError("housing confirmation data is not canonical")
    if source_etags.model_dump(mode="json") != review["source"]["etags"]:
        raise HousingConfirmationValidationError("housing confirmation source revisions are not canonical")
    if correction is not None and correction.model_dump(mode="json") != review["correction_of"]:
        raise HousingConfirmationValidationError("housing confirmation correction is not canonical")

    source = review["source"]
    if not isinstance(source, dict) or set(source) != {
        "portfolio",
        "property",
        "unit",
        "contract",
        "tenant",
        "wizard",
        "etags",
    }:
        raise HousingConfirmationValidationError("invalid housing confirmation source snapshot")
    for name in ("portfolio", "property", "unit", "contract", "tenant"):
        if not isinstance(source[name], dict):
            raise HousingConfirmationValidationError("invalid housing confirmation source object")
    if source["wizard"] is not None and not isinstance(source["wizard"], dict):
        raise HousingConfirmationValidationError("invalid housing confirmation wizard source")

    expected = {
        "portfolio": _value(row, "portfolio_id"),
        "property": _value(row, "property_id"),
        "unit": _value(row, "unit_id"),
        "contract": _value(row, "contract_id"),
        "tenant": _value(row, "tenant_id"),
    }
    if any(source[name].get("id") != identifier for name, identifier in expected.items()):
        raise HousingConfirmationValidationError("housing confirmation source identity mismatch")
    contract = source["contract"]
    if (
        contract.get("property_id") != expected["property"]
        or contract.get("unit_id") != expected["unit"]
        or contract.get("tenant_id") != expected["tenant"]
        or source["unit"].get("property_id") != expected["property"]
        or source["property"].get("portfolio_id") != expected["portfolio"]
    ):
        raise HousingConfirmationValidationError("housing confirmation source relationship mismatch")

    document_id = _value(row, "document_id")
    idempotency_key = extension["idempotency_key"]
    actor_id = extension["actor_id"]
    if (
        not isinstance(idempotency_key, str)
        or not 1 <= len(idempotency_key) <= 100
        or not isinstance(actor_id, str)
        or not actor_id
        or document_id
        != str(
            uuid5(
                NAMESPACE_URL,
                f"immo-manager:housing-confirmation:v1:{actor_id}:{idempotency_key}",
            )
        )
        or _value(row, "idempotency_key") != "generated-" + document_id
    ):
        raise HousingConfirmationValidationError(
            "housing confirmation command identity mismatch"
        )
    if (
        snapshot.get("id") != document_id
        or snapshot.get("contract_id") != expected["contract"]
        or snapshot.get("property_id") != expected["property"]
        or snapshot.get("unit_id") != expected["unit"]
        or snapshot.get("file_url") != f"/uploads/housing-confirmations/{document_id}.pdf"
        or snapshot.get("document_date") != data.issue_date.isoformat()
    ):
        raise HousingConfirmationValidationError("housing confirmation document binding mismatch")
    if not isinstance(review["pdf_sha256"], str) or not _HASH.fullmatch(review["pdf_sha256"]):
        raise HousingConfirmationValidationError("invalid housing confirmation PDF hash")
    expected_request_hash = digest(
        {
            "operation": "publish_housing_confirmation",
            "contract_id": expected["contract"],
            "payload": {
                "data": review["data"],
                "source_etags": source["etags"],
                "correction_of": review["correction_of"],
                "idempotency_key": idempotency_key,
                "review_hash": extension["review_hash"],
                "confirmed_actual_move_in": extension["confirmed_actual_move_in"],
                "confirmed_authority": extension["confirmed_authority"],
                "confirmed_residents": extension["confirmed_residents"],
            },
        }
    )
    if expected_request_hash != extension["request_sha256"]:
        raise HousingConfirmationValidationError(
            "housing confirmation request hash mismatch"
        )
    return extension
