"""Pure evidence checks used by original reads, JSON import and database backup verification."""
import hashlib
import json
import re
from collections.abc import Mapping
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from .billing_letter_types import LetterData, LetterPublish

DOC_TYPE = "billing_statement_letter"
SCHEMA_VERSION = "billing-statement-letter/1"
FORMAT_VERSION = "billing-statement-letter-pdf/1"
VIRTUAL_PREFIX = "billing-letters/"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def document_id_for(actor, key):
    return str(uuid5(NAMESPACE_URL, f"immo-manager:billing-letter:v1:{actor}:{key}"))


def request_hash(statement_id, payload):
    return digest({"operation": "publish_billing_statement_letter", "statement_id": statement_id,
                   "payload": payload.model_dump(mode="json")})


def validate_billing_letter_snapshot(row, snapshot):
    if snapshot.get("document_type") != DOC_TYPE:
        return {}
    def value(key):
        return row.get(key) if isinstance(row, Mapping) else getattr(row, key, None)

    try:
        proof = snapshot["billing_statement_letter"]
        if set(proof) != {"schema_version", "review", "review_hash", "request_sha256", "actor_id", "idempotency_key"}:
            raise ValueError()
        review = proof["review"]
        if set(review) != {"format_version", "source", "source_revision", "data", "draft", "pdf_sha256"}:
            raise ValueError()
        source = review["source"]
        data = LetterData.model_validate(review["data"])
        payload = LetterPublish(data=data, source_revision=review["source_revision"],
                                review_hash=proof["review_hash"], idempotency_key=proof["idempotency_key"])
        expected = {name: value(name + "_id") for name in ("portfolio", "property", "unit", "contract", "tenant")}
        statement, period = source["statement"], source["period"]
        frozen = statement["final_document"]
        expected_document = {"title": frozen.get("title", "Betriebskostenabrechnung"),
            "facts": frozen.get("facts", []), "rows": frozen.get("rows", []),
            "advances": frozen.get("advances", []), "totals": frozen.get("totals", [])}
        if (proof["schema_version"] != SCHEMA_VERSION or review["format_version"] != FORMAT_VERSION
                or review["draft"] is not False or data.model_dump(mode="json") != review["data"]
                or review["pdf_sha256"] != value("sha256") or digest(review) != proof["review_hash"]
                or digest(source) != review["source_revision"]
                or proof["actor_id"] != value("actor_id") or proof["request_sha256"] != value("request_sha256")
                or proof["request_sha256"] != request_hash(statement["id"], payload)
                or value("document_id") != document_id_for(proof["actor_id"], proof["idempotency_key"])
                or value("idempotency_key") != "generated-" + value("document_id")
                or snapshot.get("file_url") != f"/uploads/{VIRTUAL_PREFIX}{value('document_id')}.pdf"
                or statement["party"] != "tenant" or not re.fullmatch(r"[a-f0-9]{64}", statement.get("snapshot_hash") or "")
                or not frozen or digest(source["document"]) != digest(expected_document)
                or period["status"] not in {"finalized", "delivered", "disputed"}
                or statement["billing_period_id"] != period["id"]
                or statement["contract_id"] != expected["contract"] or statement["unit_id"] != expected["unit"]
                or period["property_id"] != expected["property"]
                or source["contract"]["property_id"] != expected["property"]
                or source["contract"]["unit_id"] != expected["unit"]
                or source["contract"]["tenant_id"] != expected["tenant"]
                or source["unit"]["property_id"] != expected["property"]
                or source["property"]["portfolio_id"] != expected["portfolio"]
                or any(source[name]["id"] != identifier for name, identifier in expected.items())
                or not isinstance(source["document"], dict)):
            raise ValueError()
        return proof
    except (KeyError, TypeError, AttributeError, ValueError, ValidationError):
        raise ValueError("Ungültiger Nachweis des archivierten Abrechnungsschreibens.") from None
