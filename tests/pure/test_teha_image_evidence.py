"""Pure source reconstruction; no SQLite, cryptography, ORM or live runtime."""

from copy import deepcopy

import pytest

from backend.services.providers.teha_receive_contract import ExternalIdentity, digest
from backend.services.providers.teha_receive_image_evidence import (
    ImageExchange, TehaImageEvidenceError, exchange_from_artifacts, prove_content,
    prove_source, prove_source_association,
)


@pytest.mark.parametrize("kind,operation,args,row,parts,key", [
    ("property", "list_property_periods", {}, {"liegId": {"id": 41}}, {"object_id": 41}, "liegenschaften"),
    ("period", "list_property_periods", {}, {"liegId": {"id": 41, "abrechnungLaufendeNr": 7}},
     {"object_id": 41, "period_number": 7}, "liegenschaften"),
    ("unit", "list_documents", {"lieg_nr": "L-41"}, {"properties": {"Nutzereinheit_ID": 501}},
     {"lieg_nr": "L-41", "unit_id": 501}, "documents"),
    ("user", "read_order_users", {"termin_id": 9001}, {"id": 601}, {"termin_id": 9001, "user_id": 601}, "nutzerInAuftrag"),
    ("technical_order", "list_technical_orders", {}, {"terminId": 9001}, {"termin_id": 9001}, "auftraege"),
    ("document", "list_documents", {"lieg_nr": "L-41"}, {"reference": "opaque"},
     {"lieg_nr": "L-41", "reference": "opaque"}, "documents"),
])
def test_complete_source_identity_and_unknown_fields(kind, operation, args, row, parts, key):
    row = {**row, "unknown": {"future": [None, {"opaque": "preserve me"}]}}
    identity = ExternalIdentity.create(kind, **parts)
    exchange = ImageExchange(operation, args, {key: [row]}, None)
    assert prove_source(exchange, kind, identity.token, digest(row)) == (identity, row)
    changed = deepcopy(exchange.body)
    changed[key][0]["unknown"]["future"][1]["opaque"] = "changed"
    with pytest.raises(TehaImageEvidenceError):
        prove_source(ImageExchange(operation, args, changed, None), kind, identity.token, digest(row))


def test_duplicate_exact_source_is_not_accepted():
    row = {"terminId": 1}
    exchange = ImageExchange("list_technical_orders", {}, {"auftraege": [row, row]}, None)
    with pytest.raises(TehaImageEvidenceError):
        prove_source(exchange, "technical_order", ExternalIdentity.create("technical_order", termin_id=1).token, digest(row))


@pytest.mark.parametrize("change", ["connection", "terminal_operation", "success"])
def test_request_terminal_binding_is_exact(change):
    request = {"payload": {"operation": "list_documents", "arguments": {"lieg_nr": "L"}, "connection_key": "C"}}
    response = {"success": True, "details": {"operation": "list_documents", "exchange": {"response": {"body": {"documents": []}}}}}
    if change == "connection":
        request["payload"]["connection_key"] = "another"
    elif change == "terminal_operation":
        response["details"]["operation"] = "read_document"
    else:
        response["success"] = False
    with pytest.raises(TehaImageEvidenceError):
        exchange_from_artifacts(request, response, "C")


def test_unit_association_requires_complete_document_list_row():
    source_identity = ExternalIdentity.create("document", lieg_nr="L", reference="opaque")
    mapping_identity = ExternalIdentity.create("unit", lieg_nr="L", unit_id=1)
    row = {"reference": "opaque", "properties": {"Nutzereinheit_ID": 1}}
    source = ImageExchange("list_documents", {"lieg_nr": "L"}, {"documents": [row]}, None)
    prove_source_association(source, source_identity, row, mapping_identity, row)
    with pytest.raises(TehaImageEvidenceError):
        prove_source_association(ImageExchange("read_document", source.arguments, row, None), source_identity, row, mapping_identity, row)


def test_unknown_association_rule_is_explicitly_closed():
    source_identity = ExternalIdentity.create("document", lieg_nr="L", reference="opaque")
    with pytest.raises(TehaImageEvidenceError, match="ASSOCIATION_UNSUPPORTED"):
        prove_source_association(ImageExchange("list_documents", {}, {}, None), source_identity, {},
                                 ExternalIdentity.create("period", object_id=1, period_number=2), {})


@pytest.mark.parametrize("change", [None, "identity", "sha", "size", "marker", "media"])
def test_content_marker_and_manifest_bind_to_verified_original(change):
    identity = ExternalIdentity.create("document", lieg_nr="L", reference="opaque")
    version = {"sha256": "1" * 64, "size_bytes": 7, "media_type": "application/pdf"}
    manifest = {"type": "TehaDocumentContent", "lieg_nr": "L", "reference": "opaque", **version}
    marker = {"omitted": "document_bytes", **version}
    args = {"lieg_nr": "L", "reference": "opaque"}
    if change == "identity":
        args["reference"] = "other"
    elif change == "sha":
        manifest["sha256"] = "2" * 64
    elif change == "size":
        manifest["size_bytes"] = 8
    elif change == "marker":
        marker["omitted"] = "missing"
    elif change == "media":
        marker["media_type"] = "other"
    exchange = ImageExchange("read_document", args, {"content": marker}, manifest)
    if change is None:
        prove_content(exchange, identity, version)
    else:
        with pytest.raises(TehaImageEvidenceError):
            prove_content(exchange, identity, version)
