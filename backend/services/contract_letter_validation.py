"""Pure evidence checks of archived template letters (original reads, JSON import, backup verification)."""
import hashlib
import json
from collections.abc import Mapping
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from .contract_letter_types import LetterPublish, LetterText

DOC_TYPE = "template_letter"
SCHEMA_VERSION = "template-letter/1"
FORMAT_VERSION = "template-letter-pdf/1"
VIRTUAL_PREFIX = "template-letters/"
REVIEW_KEYS = {"format_version", "source", "source_revision", "template", "inputs", "data", "checks", "blocks",
               "draft", "pdf_sha256"}
PROOF_KEYS = {"schema_version", "review", "review_hash", "request_sha256", "actor_id", "idempotency_key"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def document_id_for(actor, key):
    return str(uuid5(NAMESPACE_URL, f"immo-manager:template-letter:v1:{actor}:{key}"))


def request_hash(contract_id, payload):
    return digest({"operation": "publish_template_letter", "contract_id": contract_id,
                   "payload": payload.model_dump(mode="json")})


def validate_contract_letter_snapshot(row, snapshot):
    if snapshot.get("document_type") != DOC_TYPE:
        return {}

    def value(key):
        return row.get(key) if isinstance(row, Mapping) else getattr(row, key, None)

    try:
        proof = snapshot[DOC_TYPE]
        if set(proof) != PROOF_KEYS:
            raise ValueError()
        review = proof["review"]
        if set(review) != REVIEW_KEYS:
            raise ValueError()
        source = review["source"]
        data = LetterText.model_validate(review["data"])
        payload = LetterPublish(data=data, source_revision=review["source_revision"],
                                template_id=review["template"]["id"], inputs=review["inputs"],
                                review_hash=proof["review_hash"], idempotency_key=proof["idempotency_key"])
        expected = {name: value(name + "_id") for name in ("portfolio", "property", "unit", "contract", "tenant")}
        contract = source["contract"]
        if (proof["schema_version"] != SCHEMA_VERSION or review["format_version"] != FORMAT_VERSION
                or review["draft"] is not False or data.model_dump(mode="json") != review["data"]
                or review["pdf_sha256"] != value("sha256") or digest(review) != proof["review_hash"]
                or digest(source) != review["source_revision"]
                or any(check.get("level") == "error" for check in review["checks"])
                or proof["actor_id"] != value("actor_id") or proof["request_sha256"] != value("request_sha256")
                or proof["request_sha256"] != request_hash(contract["id"], payload)
                or value("document_id") != document_id_for(proof["actor_id"], proof["idempotency_key"])
                or value("idempotency_key") != "generated-" + value("document_id")
                or snapshot.get("file_url") != f"/uploads/{VIRTUAL_PREFIX}{value('document_id')}.pdf"
                or contract["property_id"] != expected["property"] or contract["unit_id"] != expected["unit"]
                or contract["tenant_id"] != expected["tenant"]
                or source["unit"]["property_id"] != expected["property"]
                or source["property"]["portfolio_id"] != expected["portfolio"]
                or any(source[name]["id"] != identifier for name, identifier in expected.items())):
            raise ValueError()
        return proof
    except (KeyError, TypeError, AttributeError, ValueError, ValidationError):
        raise ValueError("Ungültiger Nachweis des archivierten Briefs.") from None
