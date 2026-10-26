"""Malformed JSON containers are invalid previews, never HTTP 500s or partial imports."""
import hashlib
import io
import json
import zipfile
from typing import Any
from uuid import uuid4

import pytest
import test_data_transfer as transfer_fixtures

from backend.dependencies import store
from backend.services import data_snapshot
from backend.services.data_transfer import portable_archive as package
from backend.services.data_transfer.common import encoded

migration = transfer_fixtures.migration


def malformed_archive(field, value):
    snapshot = {"format": data_snapshot.SNAPSHOT_FORMAT, "format_version": data_snapshot.SNAPSHOT_FORMAT_VERSION,
                **{spec.key: [] for spec in data_snapshot.entity_specs()}}
    documents = {"business.json": snapshot, "originals.json": [], "evidence.json": [],
                 "attachments.json": [], "schema.json": {}}
    if field in documents:
        documents[field] = value
    parts = {name: encoded(body) for name, body in documents.items()}
    parts["README.md"] = b"Synthetic archive shape test."
    manifest = {"format": package.FORMAT, "version": package.VERSION,
                "controls": package._controls([(spec, []) for spec in data_snapshot.entity_specs()]), "originals": [],
                "files": {name: {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
                          for name, raw in parts.items()}}
    if field == "manifest":
        manifest = value
    elif field.startswith("manifest."):
        manifest[field.removeprefix("manifest.")] = value
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in parts.items():
            archive.writestr(name, raw)
        archive.writestr("manifest.json", encoded(manifest))
    return output.getvalue()


@pytest.mark.parametrize(("field", "value"), [
    ("manifest", []), ("manifest", None), ("manifest", "bad"),
    ("manifest.files", []), ("manifest.controls", []), ("manifest.originals", {}),
    ("manifest.version", True), ("business.json", []), ("schema.json", []),
    ("originals.json", {}), ("evidence.json", {}), ("attachments.json", {}),
    ("originals.json", [None]), ("evidence.json", [None]), ("attachments.json", [None]),
])
def test_customer_archive_requires_explicit_json_object_and_row_shapes(field, value):
    with pytest.raises(ValueError, match="Kundenexport"):
        package.read(malformed_archive(field, value))


def test_empty_well_shaped_customer_archive_remains_readable():
    snapshot, evidence, assets, _, _ = package.read(malformed_archive("unchanged", None))
    assert snapshot["format"] == data_snapshot.SNAPSHOT_FORMAT
    assert evidence == [] and assets == []


@pytest.mark.parametrize(("table", "field", "wrong"), [
    ("e_invoice_intakes", "reading", []), ("e_invoice_intakes", "blockers", {}),
    ("e_invoice_validations", "messages", {}), ("external_portal_grants", "binding", []),
    ("privacy_requests", "outcome", []), ("privacy_controls", "file_keys_sha256", {}),
    ("e_invoice_intakes", "blockers", [None]), ("e_invoice_intakes", "blockers", [{}]),
    ("e_invoice_validations", "messages", [None]), ("e_invoice_validations", "messages", [{}]),
    ("e_invoice_validations", "messages", [{"severity": "error", "text": {"nested": "object"}}]),
    ("privacy_controls", "file_keys_sha256", [None]), ("privacy_controls", "file_keys_sha256", ["invalid-hash"]),
    ("e_invoice_intakes", "reading", {"supplier": {"nested": "object"}}),
    ("e_invoice_intakes", "reading", {"taxes": [None]}),
    ("e_invoice_intakes", "reading", {"lines": [{"name": []}]}),
    ("e_invoice_intakes", "reading", {"supplier_tax_ids": [{}]}),
])
def test_nested_evidence_containers_are_checked_before_domain_services(table, field, wrong):
    from sqlalchemy import JSON
    model = next(model for model in package.EVIDENCE_MODELS if model.__tablename__ == table)
    payload: dict[str, Any] = {column.name: None for column in model.__table__.columns}
    payload["id"] = uuid4().hex
    for column in model.__table__.columns:
        if isinstance(column.type, JSON):
            payload[column.name] = [] if (table, column.name) in package.JSON_LIST_FIELDS else {}
    payload[field] = wrong
    record = {"source_type": table, "record_id": payload["id"], "payload": payload,
              "sha256": hashlib.sha256(encoded(payload)).hexdigest()}
    with pytest.raises(ValueError, match="Kundenexport"):
        package.read(malformed_archive("evidence.json", [record]))


@pytest.mark.parametrize(("field", "wrong"), [("source_type", []), ("record_id", []), ("record_id", None),
                                               ("sha256", []), ("historical", "true")])
def test_evidence_identifiers_and_history_marker_have_explicit_types(field, wrong):
    record = {"source_type": "payment_authorizations", "record_id": "synthetic", "payload": {},
              "sha256": hashlib.sha256(encoded({})).hexdigest()}
    record[field] = wrong
    with pytest.raises(ValueError, match="Kundenexport"):
        package.read(malformed_archive("evidence.json", [record]))


def test_corrupted_deflate_is_a_controlled_import_error():
    raw = bytearray(malformed_archive("unchanged", None))
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entry = archive.getinfo("business.json")
    offset = entry.header_offset + 30 + len(entry.filename.encode()) + len(entry.extra)
    # BTYPE=3 is reserved and cannot be a valid DEFLATE block.
    raw[offset] = 0xff
    with pytest.raises(ValueError, match="Kundenexport"):
        package.read(bytes(raw))


@pytest.mark.parametrize("manifest", [[], None, "bad"])
def test_malformed_archive_http_preview_is_invalid_and_cannot_write_business_data(migration, manifest):
    _, _, client = migration
    def business_records():
        backend = data_snapshot._backend(store)
        return {spec.key: [row.model_dump(mode="json") for row in backend.records(spec)]
                for spec in data_snapshot.entity_specs()}
    before = business_records()
    response = client.post("/api/v1/data/import-batches",
        data={"options": json.dumps({"source_system": "Malformed container QA"})},
        files=[("files", ("customer.zip", malformed_archive("manifest", manifest), "application/zip"))],
        headers={"Idempotency-Key": uuid4().hex})
    assert response.status_code == 201, response.text
    batch = response.json()
    assert batch["state"] == "invalid"
    assert batch["preview"]["error_count"]
    assert "JSON-Objekt" in " ".join(batch["preview"]["errors"])
    refused = client.post(f"/api/v1/data/import-batches/{batch['id']}/commit", json={
        "expected_revision": batch["revision"], "idempotency_key": uuid4().hex,
        "acknowledge_warnings": True, "reason": "Defekten Archivaufbau kontrolliert ablehnen."})
    assert refused.status_code == 409, refused.text
    assert business_records() == before
