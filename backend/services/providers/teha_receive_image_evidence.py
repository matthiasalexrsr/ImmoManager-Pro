"""Pure source reconstruction from already authenticated TEHA image artifacts.

No Store, transport, auth, Settings, keys, connection or callback is accepted.
The image boundary authenticates artifacts before calling these functions.
"""

from dataclasses import dataclass, field
from typing import Any

from .teha_receive_contract import ExternalIdentity, digest


class TehaImageEvidenceError(ValueError):
    """Constant-only failures: no provider payload in diagnostics."""


@dataclass(frozen=True)
class ImageExchange:
    operation: str
    arguments: dict[str, Any] = field(repr=False)
    body: dict[str, Any] = field(repr=False)
    result_manifest: Any = field(repr=False)


def exchange_from_artifacts(request, response, connection_key) -> ImageExchange:
    payload = request.get("payload") if isinstance(request, dict) else None
    details = response.get("details") if isinstance(response, dict) else None
    if (not isinstance(payload, dict) or payload.get("connection_key") != connection_key
            or not isinstance(payload.get("operation"), str)
            or not isinstance(payload.get("arguments"), dict)
            or not isinstance(response, dict) or response.get("success") is not True
            or not isinstance(details, dict) or details.get("operation") != payload["operation"]):
        raise TehaImageEvidenceError("TEHA_IMAGE_SOURCE_BINDING_INVALID")
    exchange = details.get("exchange")
    wire_response = exchange.get("response") if isinstance(exchange, dict) else None
    body = wire_response.get("body") if isinstance(wire_response, dict) else None
    if not isinstance(body, dict):
        raise TehaImageEvidenceError("TEHA_IMAGE_SOURCE_BINDING_INVALID")
    return ImageExchange(payload["operation"], payload["arguments"], body, details.get("result_manifest"))


def _candidates(exchange, kind):
    args, body, operation = exchange.arguments, exchange.body, exchange.operation
    if kind in {"property", "period"} and operation == "list_property_periods":
        records = body.get("liegenschaften")
    elif kind == "technical_order" and operation == "list_technical_orders":
        records = body.get("auftraege")
    elif kind == "user" and operation == "read_order_users":
        records = body.get("nutzerInAuftrag")
    elif kind in {"unit", "document"} and operation == "list_documents":
        records = body.get("documents")
    elif kind == "document" and operation == "read_document":
        records = [body]
    else:
        return
    if not isinstance(records, list):
        return
    for row in records:
        if not isinstance(row, dict):
            continue
        try:
            if kind in {"property", "period"}:
                lieg = row.get("liegId")
                if not isinstance(lieg, dict):
                    continue
                parts = {"object_id": lieg.get("id")}
                if kind == "period":
                    parts["period_number"] = lieg.get("abrechnungLaufendeNr")
            elif kind == "technical_order":
                parts = {"termin_id": row.get("terminId")}
            elif kind == "user":
                parts = {"termin_id": args.get("termin_id"), "user_id": row.get("id")}
            elif kind == "unit":
                properties = row.get("properties")
                if not isinstance(properties, dict):
                    continue
                parts = {"lieg_nr": args.get("lieg_nr"), "unit_id": properties.get("Nutzereinheit_ID")}
            else:
                parts = {"lieg_nr": args.get("lieg_nr"), "reference": (
                    args.get("reference") if operation == "read_document" else row.get("reference"))}
            yield ExternalIdentity.create(kind, **parts), row
        except (ValueError, TypeError):
            continue


def prove_source(exchange, kind, external_identity_hash, source_sha256, *, expected_identity=None):
    """Exactly one complete sanitized row; unknown fields affect the digest."""
    match = None
    for identity, row in _candidates(exchange, kind):
        if (identity.token == external_identity_hash and digest(row) == source_sha256
                and (expected_identity is None or identity == expected_identity)):
            if match is not None:
                raise TehaImageEvidenceError("TEHA_IMAGE_SOURCE_BINDING_INVALID")
            match = identity, row
    if match is None:
        raise TehaImageEvidenceError("TEHA_IMAGE_SOURCE_BINDING_INVALID")
    return match


def prove_source_association(source, source_identity, source_row, mapping_identity, mapping_row):
    parts = dict(source_identity.parts)
    lieg_nr = (parts.get("lieg_nr") if source_identity.kind == "document"
               else source_row.get("liegenschaftsnummer") if source_identity.kind == "technical_order" else None)
    if mapping_identity.kind == "property":
        valid = isinstance(lieg_nr, str) and mapping_row.get("liegenschaftenNummer") == lieg_nr
    elif mapping_identity.kind == "unit":
        properties = source_row.get("properties")
        mapped = dict(mapping_identity.parts)
        valid = (source_identity.kind == "document" and source.operation == "list_documents"
                 and isinstance(lieg_nr, str) and mapped.get("lieg_nr") == lieg_nr
                 and isinstance(properties, dict) and properties.get("Nutzereinheit_ID") == mapped.get("unit_id"))
    else:
        raise TehaImageEvidenceError("TEHA_IMAGE_ASSOCIATION_UNSUPPORTED")
    if not valid:
        raise TehaImageEvidenceError("TEHA_IMAGE_SOURCE_TARGET_INVALID")


def prove_content(exchange, identity, version):
    """Bind the authenticated omitted-bytes marker to the verified original."""
    try:
        actual = ExternalIdentity.create("document", lieg_nr=exchange.arguments.get("lieg_nr"),
                                         reference=exchange.arguments.get("reference"))
    except (TypeError, ValueError):
        raise TehaImageEvidenceError("TEHA_IMAGE_CONTENT_BINDING_INVALID") from None
    manifest, marker = exchange.result_manifest, exchange.body.get("content")
    parts = dict(identity.parts)
    if (exchange.operation != "read_document" or actual != identity
            or not isinstance(manifest, dict) or not isinstance(marker, dict)
            or manifest.get("type") != "TehaDocumentContent"
            or manifest.get("reference") != parts.get("reference") or manifest.get("lieg_nr") != parts.get("lieg_nr")
            or manifest.get("sha256") != version["sha256"]
            or type(manifest.get("size_bytes")) is not int or manifest["size_bytes"] != version["size_bytes"]
            or manifest.get("media_type") != version["media_type"]
            or marker.get("omitted") != "document_bytes" or marker.get("sha256") != version["sha256"]
            or type(marker.get("size_bytes")) is not int or marker["size_bytes"] != version["size_bytes"]
            or marker.get("media_type") != version["media_type"]):
        raise TehaImageEvidenceError("TEHA_IMAGE_CONTENT_BINDING_INVALID")
