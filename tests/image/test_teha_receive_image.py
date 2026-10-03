"""Real selected-image/Crypto API gate, separate from PureManifest and runtime.

Prepared source only; Root runs with --noconftest in its bounded native slot.
Only test fixtures create/mutate their isolated in-memory SQLite databases.
No Settings, Auth, Store, engine/session factory, provider or backend conftest.
The existing History image API imports static ORM metadata/event registration.
"""

import base64
import hashlib
import sqlite3
import time

import pytest
from sqlalchemy.dialects.sqlite import dialect
from sqlalchemy.schema import CreateIndex, CreateTable

from backend.db.document_version_models import DOCUMENT_VERSION_MODELS
from backend.db.integration_history_models import HISTORY_MODELS
from backend.db.teha_receive_release_l2 import frozen_l2_tables
from backend.models import Document
from backend.services.iban_encryption import IBANKeyring
from backend.services.integrations.history_crypto import CHUNK_BYTES, canonical, digest as history_digest, encrypt, event_identity, run_identity
from backend.services.integrations.history_types import HistoryLimits
from backend.services.providers.teha_import_validation import build_document_manifest, mapping_reference
from backend.services.providers.teha_receive_contract import ExternalIdentity, digest
from backend.services.providers.teha_receive_image import TehaImageError, TehaImageLimits, validate_teha_receive_image

STAMP = "2026-10-04T00:00:00+00:00"
LIMITS = TehaImageLimits(batch_size=2, row_bytes=8192, original_metadata_bytes=65536, schema_bytes=65536)
HISTORY_LIMITS = HistoryLimits(artifact_bytes=65536, page_bytes=131072, timeout_seconds=30, temp_bytes=262144)


def _insert(db, table, row):
    db.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))


class ImageFixture:
    def __init__(self, *, schema_change=None):
        self.db = sqlite3.connect(":memory:")
        self.keys = IBANKeyring("fixture", {"fixture": base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")})
        self.db.executescript("""
            CREATE TABLE portfolios (id VARCHAR PRIMARY KEY);
            CREATE TABLE properties (id VARCHAR PRIMARY KEY, portfolio_id VARCHAR NOT NULL);
            CREATE TABLE units (id VARCHAR PRIMARY KEY, property_id VARCHAR NOT NULL);
            CREATE TABLE tenants (id VARCHAR PRIMARY KEY);
            CREATE TABLE contracts (id VARCHAR PRIMARY KEY, property_id VARCHAR, unit_id VARCHAR, tenant_id VARCHAR);
            CREATE TABLE billing_periods (id VARCHAR PRIMARY KEY, property_id VARCHAR NOT NULL);
            CREATE TABLE tasks (id VARCHAR PRIMARY KEY, property_id VARCHAR, unit_id VARCHAR, title TEXT, status TEXT);
            CREATE TABLE documents (id VARCHAR PRIMARY KEY, property_id VARCHAR, unit_id VARCHAR, contract_id VARCHAR, file_url TEXT, document_type TEXT);
            CREATE TABLE resource_portfolio_grants (resource_type VARCHAR, resource_id VARCHAR, portfolio_id VARCHAR,
                                                   PRIMARY KEY(resource_type,resource_id,portfolio_id));
            CREATE TABLE operational_jobs (id VARCHAR PRIMARY KEY);
            CREATE TABLE operational_work_items (id VARCHAR PRIMARY KEY);
        """)
        for model in HISTORY_MODELS + DOCUMENT_VERSION_MODELS:
            self.db.execute(str(CreateTable(model.__table__).compile(dialect=dialect())))
        for table in frozen_l2_tables():
            sql = str(CreateTable(table).compile(dialect=dialect()))
            if schema_change == "check" and table.name == "teha_external_mappings":
                sql = sql.replace("generation > 0", "generation >= 0")
            if schema_change == "type" and table.name == "teha_external_mappings":
                sql = sql.replace("connection_key VARCHAR(200)", "connection_key TEXT")
            if schema_change == "nullable_pk" and table.name == "teha_external_mappings":
                assert "id VARCHAR NOT NULL" in sql
                sql = sql.replace("id VARCHAR NOT NULL", "id VARCHAR", 1)
            self.db.execute(sql)
            for index in table.indexes:
                self.db.execute(str(CreateIndex(index).compile(dialect=dialect())))
        self.db.execute("INSERT INTO portfolios VALUES ('P')")
        self.db.execute("INSERT INTO portfolios VALUES ('OTHER')")
        self.db.execute("INSERT INTO properties VALUES ('PROP','P')")
        self.db.execute("INSERT INTO properties VALUES ('PROP2','P')")
        self.db.execute("INSERT INTO properties VALUES ('FOREIGN','OTHER')")
        self.db.execute("INSERT INTO units VALUES ('UNIT','PROP')")
        self.db.execute("INSERT INTO billing_periods VALUES ('PERIOD','PROP')")
        self.db.execute("INSERT INTO tenants VALUES ('TENANT')")
        self.db.execute("INSERT INTO resource_portfolio_grants VALUES ('tenants','TENANT','P')")
        self.db.execute("INSERT INTO tasks VALUES ('TASK','PROP','UNIT','legitimately mutable','completed')")
        _insert(self.db, "integration_history_heads", {
            "integration_id": "teha", "run_sequence": 0, "event_sequence": 0, "clear_epoch": 0,
            "active_runs": 0, "history_started_at": STAMP,
        })
        self.property_row = {"liegId": {"id": 41, "abrechnungLaufendeNr": 7}, "liegenschaftenNummer": "L-41", "unknown": {"kept": True}}
        self.document_row = {"reference": "opaque", "properties": {"Nutzereinheit_ID": 501}, "unknown": [1, None, {"future": "retained"}]}
        self.order_row = {"terminId": 9001, "liegenschaftsnummer": "L-41", "status": "provider status"}
        self.history("mapping-run", "list_property_periods", {}, {"liegenschaften": [self.property_row]})
        self.history("source-run", "list_documents", {"lieg_nr": "L-41"}, {"documents": [self.document_row]})
        self.content = b"%PDF-1.7\n" + b"original bytes\n" * 5000  # multiple original chunks
        self.content_sha = hashlib.sha256(self.content).hexdigest()
        manifest = {"type": "TehaDocumentContent", "lieg_nr": "L-41", "reference": "opaque",
                    "sha256": self.content_sha, "size_bytes": len(self.content), "media_type": "application/pdf"}
        marker = {"omitted": "document_bytes", "sha256": self.content_sha, "size_bytes": len(self.content), "media_type": "application/pdf"}
        self.history("content-run", "read_document", {"lieg_nr": "L-41", "reference": "opaque"}, {"content": marker}, manifest=manifest)
        self.mapping_row = self.mapping("MAP", "property", {"object_id": 41}, "PROP", "mapping-run", self.property_row)
        _, mapping_sha = mapping_reference(self.mapping_row)
        identity = ExternalIdentity.create("document", lieg_nr="L-41", reference="opaque")
        self.receipt = {
            "id": "RECEIPT", "portfolio_id": "P", "connection_key": "C", "operational_job_id": None, "work_item_id": None,
            "source_history_run_id": "source-run", "source_kind": "document", "external_identity_hash": identity.token,
            "mapping_generation": 1, "mapping_id": "MAP", "mapping_sha256": mapping_sha, "source_sha256": digest(self.document_row),
            "content_sha256": self.content_sha, "document_id": "DOC", "document_version_id": "VERSION", "task_id": None,
            "state": "imported", "command_key": "command", "command_sha256": "a" * 64, "imported_by": "actor", "imported_at": STAMP,
        }
        binding = {"portfolio_id": "P", "property_id": "PROP", "unit_id": None, "contract_id": None, "tenant_id": None}
        target = {"portfolio_id": "P", "property_id": "PROP", "unit_id": None, "tenant_id": None, "billing_period_id": None}
        self.extension = build_document_manifest(
            receipt_id="RECEIPT", actor_id="actor", command_sha256="a" * 64, connection_key="C", source_history_run_id="source-run",
            content_history_run_id="content-run", external_identity_hash=identity.token, source_sha256=digest(self.document_row),
            content_sha256=self.content_sha, mapping_id="MAP", mapping_generation=1, mapping_sha256=mapping_sha,
            local_binding=binding, mapping_target_binding=target, document_type="unknown_provider_classification",
        )
        self.snapshot = Document(id="DOC", title="Original", property_id="PROP", file_url="generated/teha/DOC.pdf",
                                 document_type="unknown_provider_classification", created_at=STAMP, updated_at=STAMP).model_dump(mode="json")
        self.snapshot["teha_import"] = self.extension
        _insert(self.db, "documents", {"id": "DOC", "property_id": "PROP", "unit_id": None, "contract_id": None, "file_url": self.snapshot["file_url"]})
        _insert(self.db, "document_versions", {
            "id": "VERSION", "document_id": "DOC", **binding, "number": 1, "predecessor_id": None, "restored_from_id": None,
            "actor_id": "actor", "idempotency_key": "generated-DOC", "request_sha256": "a" * 64, "operation": "archive_original",
            "comment": "Fixture", "filename": "DOC.pdf", "media_type": "application/pdf", "sha256": self.content_sha,
            "size_bytes": len(self.content), "metadata_snapshot": canonical(self.snapshot).decode(), "created_at": STAMP,
        })
        for position, offset in enumerate(range(0, len(self.content), 65536)):
            _insert(self.db, "document_version_chunks", {"version_id": "VERSION", "position": position, "portfolio_id": "P", "data": self.content[offset:offset + 65536]})
        _insert(self.db, "teha_import_receipts", self.receipt)

    def history(self, identifier, operation, arguments, body, *, manifest=None, connection_key="C", terminal="completed", padding=None):
        head = self.db.execute("SELECT run_sequence,event_sequence FROM integration_history_heads WHERE integration_id='teha'").fetchone()
        run = {"id": identifier, "integration_id": "teha", "run_sequence": head[0] + 1, "actor_id": "actor",
               "origin": "authenticated_request", "scope_kind": "installation", "created_at": STAMP}
        identity = run_identity(run)
        run["metadata_ciphertext"] = encrypt(canonical({"identity": identity, "ticket_hash": "b" * 64}), {"kind": "run", "identity": identity}, self.keys)
        _insert(self.db, "integration_runs", run)
        request = {"payload": {"operation": operation, "arguments": arguments, "connection_key": connection_key}}
        details = {"operation": operation, "exchange": {"response": {"body": body}}, "result_manifest": manifest}
        if padding is not None:
            details["unknown_large_envelope"] = padding
        response = {"success": terminal == "completed", "message": "Fixture", "details": details}
        previous = ""
        for number, (state, artifacts) in enumerate((
                ("accepted", {"request": request, "schema": {}}), ("execution_started", {}),
                (terminal, {"response": response, "schema": {}})), 1):
            encoded = {kind: canonical(value) for kind, value in artifacts.items()}
            manifest_value = {kind: {"bytes": len(value), "chunks": max(1, (len(value) + CHUNK_BYTES - 1) // CHUNK_BYTES),
                                     "sha256": hashlib.sha256(value).hexdigest()} for kind, value in encoded.items()}
            event = {"id": identifier + "-" + str(number), "run_id": identifier, "integration_id": "teha", "event_number": number,
                     "journal_sequence": head[1] + number, "state": state, "success": int(response["success"]) if number == 3 else None,
                     "created_at": STAMP, "previous_hash": previous, "manifest": manifest_value}
            event_proof = event_identity(run, event)
            event["event_hash"] = history_digest(event_proof)
            event["metadata_ciphertext"] = encrypt(canonical(event_proof), {"kind": "event", "identity": event_proof}, self.keys)
            event["manifest"] = canonical(manifest_value).decode()
            _insert(self.db, "integration_run_events", event)
            for kind, value in encoded.items():
                for position in range(max(1, (len(value) + CHUNK_BYTES - 1) // CHUNK_BYTES)):
                    block = value[position * CHUNK_BYTES:(position + 1) * CHUNK_BYTES]
                    _insert(self.db, "integration_run_chunks", {"event_id": event["id"], "kind": kind, "position": position,
                            "ciphertext": encrypt(block, {"kind": kind, "position": position, "event": event_proof}, self.keys)})
            previous = event["event_hash"]
        self.db.execute("UPDATE integration_history_heads SET run_sequence=?,event_sequence=?,active_runs=active_runs+1 WHERE integration_id='teha'",
                        (head[0] + 1, head[1] + 3))

    def mapping(self, identifier, kind, parts, target, history, source, *, generation=1):
        identity = ExternalIdentity.create(kind, **parts)
        fields = dict.fromkeys(("internal_property_id", "billing_period_id", "unit_id", "tenant_id", "task_id"))
        fields[{"property": "internal_property_id", "period": "billing_period_id", "unit": "unit_id", "user": "tenant_id", "technical_order": "task_id"}[kind]] = target
        row = {"id": identifier, "portfolio_id": "P", "connection_key": "C", "kind": kind, "external_identity_hash": identity.token,
               "external_identity_json": identity.private_value(), **fields, "generation": generation, "state": "confirmed",
               "revision": "c" * 64, "confirmed_by": "actor", "confirmed_at": STAMP, "source_history_run_id": history,
               "source_sha256": digest(source), "created_at": STAMP, "updated_at": STAMP}
        _insert(self.db, "teha_external_mappings", {**row, "external_identity_json": canonical(row["external_identity_json"]).decode()})
        return row

    def seal(self, *, omit_guard=None):
        for table in ("teha_external_mappings", "teha_import_receipts"):
            for action in ("update", "delete"):
                name = f"preserve_{table}_{action}"
                if name != omit_guard:
                    self.db.execute(f"CREATE TRIGGER {name} BEFORE {action.upper()} ON {table} BEGIN SELECT RAISE(ABORT,'TEHA receive evidence is immutable'); END")
        self.db.commit()
        self.db.execute("PRAGMA query_only=ON")
        self.db.execute("PRAGMA trusted_schema=OFF")
        self.db.execute("BEGIN")

    def validate(self, *, keys=None, limits=LIMITS, history_limits=HISTORY_LIMITS):
        return validate_teha_receive_image(self.db, image_keys=self.keys if keys is None else keys,
                                          history_limits=history_limits, image_limits=limits, deadline=time.monotonic() + 20)


@pytest.fixture
def image():
    fixture = ImageFixture()
    try:
        yield fixture
    finally:
        fixture.db.close()


def test_complete_real_crypto_original_image_is_read_only(image):
    image.seal()
    before = image.db.total_changes
    statements = []
    image.db.set_trace_callback(statements.append)
    report = image.validate()
    image.db.set_trace_callback(None)
    assert (report.mappings, report.receipts, report.document_receipts, report.task_receipts) == (1, 1, 1, 0)
    assert not report.command_digest_reconstructed
    assert image.db.total_changes == before and image.db.in_transaction
    assert all(sql.lstrip().split()[0].upper() in {"SELECT", "PRAGMA"} for sql in statements)


def test_no_overall_mapping_row_cap_and_invalid_last_batch_is_seen(image):
    for generation in range(2, 12):
        image.mapping(f"MAP-{generation:02}", "property", {"object_id": 41}, "PROP", "mapping-run", image.property_row, generation=generation)
    image.db.execute("UPDATE teha_external_mappings SET source_sha256=? WHERE id='MAP-11'", ("f" * 64,))
    image.seal()
    with pytest.raises(TehaImageError, match="SOURCE_BINDING_INVALID"):
        image.validate()


def test_multiple_valid_keyset_batches_preserve_older_receipt_generation(image):
    for generation in range(2, 8):
        image.mapping(f"MAP-{generation:02}", "property", {"object_id": 41}, "PROP", "mapping-run", image.property_row, generation=generation)
    image.seal()
    assert image.validate().mappings == 7


@pytest.mark.parametrize("damage_last_parent", [False, True])
def test_all_receipt_batches_are_counted_and_late_parent_damage_is_seen(image, damage_last_parent):
    orders = [{**image.order_row, "terminId": 10000 + number} for number in range(11)]
    image.history("many-order-run", "list_technical_orders", {}, {"auftraege": orders})
    for number, source in enumerate(orders):
        task_id = f"Z-TASK-{number:02}"
        _insert(image.db, "tasks", {"id": task_id, "property_id": "PROP", "unit_id": "UNIT",
                                   "title": "Fixture work", "status": "completed"})
        receipt = {**image.receipt, "id": f"Z-RECEIPT-{number:02}", "source_kind": "technical_order",
                   "source_history_run_id": "many-order-run",
                   "external_identity_hash": ExternalIdentity.create("technical_order", termin_id=source["terminId"]).token,
                   "source_sha256": digest(source), "content_sha256": None, "document_id": None,
                   "document_version_id": None, "task_id": task_id, "command_key": f"task-command-{number}",
                   "command_sha256": "d" * 64}
        _insert(image.db, "teha_import_receipts", receipt)
    assert image.db.execute("SELECT COUNT(*) FROM teha_import_receipts").fetchone()[0] == 12
    if damage_last_parent:
        image.db.execute("UPDATE tasks SET property_id='PROP2',unit_id=NULL WHERE id='Z-TASK-10'")
    image.seal()
    if damage_last_parent:
        with pytest.raises(TehaImageError, match="TARGET_INVALID"):
            image.validate()
    else:
        report = image.validate()
        assert (report.receipts, report.task_receipts, report.document_receipts) == (12, 11, 1)


def _additional_document(image, number):
    source = {**image.document_row, "reference": f"opaque-{number}"}
    source_run, content_run = f"source-run-{number}", f"content-run-{number}"
    image.history(source_run, "list_documents", {"lieg_nr": "L-41"}, {"documents": [source]})
    identity = ExternalIdentity.create("document", lieg_nr="L-41", reference=source["reference"])
    manifest = {"type": "TehaDocumentContent", "lieg_nr": "L-41", "reference": source["reference"],
                "sha256": image.content_sha, "size_bytes": len(image.content), "media_type": "application/pdf"}
    marker = {"omitted": "document_bytes", "sha256": image.content_sha,
              "size_bytes": len(image.content), "media_type": "application/pdf"}
    image.history(content_run, "read_document", {"lieg_nr": "L-41", "reference": source["reference"]},
                  {"content": marker}, manifest=manifest)
    receipt = {**image.receipt, "id": f"Z-RECEIPT-{number}", "document_id": f"Z-DOC-{number}",
               "document_version_id": f"Z-VERSION-{number}", "command_key": f"document-command-{number}",
               "external_identity_hash": identity.token, "source_sha256": digest(source), "source_history_run_id": source_run}
    binding = {"portfolio_id": "P", "property_id": "PROP", "unit_id": None, "contract_id": None, "tenant_id": None}
    extension = build_document_manifest(
        receipt_id=receipt["id"], actor_id="actor", command_sha256=receipt["command_sha256"], connection_key="C",
        source_history_run_id=source_run, content_history_run_id=content_run, external_identity_hash=identity.token,
        source_sha256=receipt["source_sha256"], content_sha256=image.content_sha, mapping_id="MAP", mapping_generation=1,
        mapping_sha256=receipt["mapping_sha256"], local_binding=binding,
        mapping_target_binding={"portfolio_id": "P", "property_id": "PROP", "unit_id": None,
                                "tenant_id": None, "billing_period_id": None},
        document_type="unknown_provider_classification",
    )
    snapshot = {**image.snapshot, "id": receipt["document_id"],
                "file_url": f"generated/teha/{receipt['document_id']}.pdf", "teha_import": extension}
    _insert(image.db, "documents", {"id": receipt["document_id"], "property_id": "PROP", "unit_id": None,
                                   "contract_id": None, "file_url": snapshot["file_url"]})
    cursor = image.db.execute("SELECT * FROM document_versions WHERE id='VERSION'")
    version = dict(zip((column[0] for column in cursor.description), cursor.fetchone(), strict=True))
    cursor.close()
    _insert(image.db, "document_versions", {**version, "id": receipt["document_version_id"],
        "document_id": receipt["document_id"], "idempotency_key": "generated-" + receipt["document_id"],
        "filename": receipt["document_id"] + ".pdf", "metadata_snapshot": canonical(snapshot).decode()})
    for position, offset in enumerate(range(0, len(image.content), 65536)):
        _insert(image.db, "document_version_chunks", {"version_id": receipt["document_version_id"], "position": position,
                                                     "portfolio_id": "P", "data": image.content[offset:offset + 65536]})
    _insert(image.db, "teha_import_receipts", receipt)
    return receipt


def test_reverse_original_closure_detects_orphan_after_first_keyset_batch(image):
    _additional_document(image, 2)
    last = _additional_document(image, 3)
    assert image.db.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0] == 3
    image.db.execute("DELETE FROM teha_import_receipts WHERE id=?", (last["id"],))
    image.seal()
    with pytest.raises(TehaImageError, match="ORIGINAL_RECEIPT_MISSING"):
        image.validate()


def test_legitimate_live_classification_does_not_rewrite_original(image):
    image.db.execute("UPDATE documents SET document_type='later recategorized'")
    image.seal()
    assert image.validate().document_receipts == 1


@pytest.mark.parametrize("damage", [False, True])
def test_real_encrypted_history_spans_all_chunks(image, damage):
    image.history("large-run", "list_documents", {"lieg_nr": "L-41"}, {"documents": [image.document_row]}, padding="x" * 70000)
    image.db.execute("UPDATE teha_import_receipts SET source_history_run_id='large-run'")
    image.snapshot["teha_import"]["source_history_run_id"] = "large-run"
    image.db.execute("UPDATE document_versions SET metadata_snapshot=?", (canonical(image.snapshot).decode(),))
    if damage:
        image.db.execute("DELETE FROM integration_run_chunks WHERE event_id='large-run-3' AND kind='response' AND position=1")
    image.seal()
    limits = HistoryLimits(artifact_bytes=131072, page_bytes=262144, timeout_seconds=30, temp_bytes=524288)
    if damage:
        with pytest.raises(TehaImageError, match="HISTORY_INVALID"):
            image.validate(history_limits=limits)
    else:
        assert image.validate(history_limits=limits).document_receipts == 1


@pytest.mark.parametrize("wrong_property", [False, True])
def test_task_receipt_checks_parents_and_preserves_legitimate_later_state(image, wrong_property):
    image.history("order-run", "list_technical_orders", {}, {"auftraege": [image.order_row]})
    receipt = {**image.receipt, "id": "TASK-RECEIPT", "source_kind": "technical_order", "source_history_run_id": "order-run",
               "external_identity_hash": ExternalIdentity.create("technical_order", termin_id=9001).token,
               "source_sha256": digest(image.order_row), "content_sha256": None, "document_id": None, "document_version_id": None,
               "task_id": "TASK", "command_key": "task-command", "command_sha256": "d" * 64}
    _insert(image.db, "teha_import_receipts", receipt)
    if wrong_property:
        image.db.execute("UPDATE tasks SET property_id='PROP2',unit_id=NULL WHERE id='TASK'")
    image.seal()
    if wrong_property:
        with pytest.raises(TehaImageError, match="TARGET_INVALID"):
            image.validate()
    else:
        report = image.validate()
        assert report.task_receipts == 1 and report.document_receipts == 1
        assert image.db.execute("SELECT status,title FROM tasks WHERE id='TASK'").fetchone() == ("completed", "legitimately mutable")


@pytest.mark.parametrize("kind", ["period", "unit", "user", "technical_order"])
def test_each_actual_kind_specific_mapping_parent_is_checked(image, kind):
    if kind == "period":
        parts, target, run, source = {"object_id": 41, "period_number": 7}, "PERIOD", "mapping-run", image.property_row
    elif kind == "unit":
        parts, target, run, source = {"lieg_nr": "L-41", "unit_id": 501}, "UNIT", "source-run", image.document_row
    elif kind == "user":
        source = {"id": 601}
        image.history("user-run", "read_order_users", {"termin_id": 9001}, {"nutzerInAuftrag": [source]})
        parts, target, run = {"termin_id": 9001, "user_id": 601}, "TENANT", "user-run"
    else:
        source = image.order_row
        image.history("order-run", "list_technical_orders", {}, {"auftraege": [source]})
        parts, target, run = {"termin_id": 9001}, "TASK", "order-run"
    image.mapping("OTHER-MAP", kind, parts, target, run, source)
    image.seal()
    assert image.validate().mappings == 2


@pytest.mark.parametrize("damage", ["portfolio", "unit_parent", "tenant_grant", "period_parent", "task_parent"])
def test_missing_or_wrong_current_parent_is_closed(image, damage):
    if damage == "portfolio":
        image.db.execute("UPDATE properties SET portfolio_id='OTHER' WHERE id='PROP'")
    elif damage == "unit_parent":
        image.mapping("UNIT-MAP", "unit", {"lieg_nr": "L-41", "unit_id": 501}, "UNIT", "source-run", image.document_row)
        image.db.execute("UPDATE units SET property_id='FOREIGN' WHERE id='UNIT'")
    elif damage == "tenant_grant":
        image.history("user-run", "read_order_users", {"termin_id": 9001}, {"nutzerInAuftrag": [{"id": 601}]})
        image.mapping("USER-MAP", "user", {"termin_id": 9001, "user_id": 601}, "TENANT", "user-run", {"id": 601})
        image.db.execute("DELETE FROM resource_portfolio_grants")
    elif damage == "period_parent":
        image.mapping("PERIOD-MAP", "period", {"object_id": 41, "period_number": 7}, "PERIOD", "mapping-run", image.property_row)
        image.db.execute("UPDATE billing_periods SET property_id='missing' WHERE id='PERIOD'")
    else:
        image.history("order-run", "list_technical_orders", {}, {"auftraege": [image.order_row]})
        image.mapping("TASK-MAP", "technical_order", {"termin_id": 9001}, "TASK", "order-run", image.order_row)
        image.db.execute("UPDATE tasks SET unit_id='missing' WHERE id='TASK'")
    image.seal()
    with pytest.raises(TehaImageError):
        image.validate()


@pytest.mark.parametrize("field,value", [
    ("connection_key", "wrong"), ("mapping_sha256", "e" * 64), ("mapping_generation", 2),
    ("source_sha256", "d" * 64), ("source_history_run_id", "mapping-run"),
    ("operational_job_id", "JOB"), ("imported_by", "another actor"),
])
def test_receipt_cross_bindings_are_not_copied_authority(image, field, value):
    image.db.execute(f"UPDATE teha_import_receipts SET {field}=?", (value,))
    image.seal()
    with pytest.raises(TehaImageError):
        image.validate()


@pytest.mark.parametrize("damage", ["content_run", "classification", "target", "missing_receipt", "chunk", "duplicate_json"])
def test_original_content_and_reverse_closure(image, damage):
    if damage == "content_run":
        image.snapshot["teha_import"]["content_history_run_id"] = "source-run"
    elif damage == "classification":
        image.snapshot["document_type"] = "different"
    elif damage == "target":
        # The original's own subject and manifest agree; its selected mapping
        # still targets a different property in the SAME portfolio.
        image.db.execute("UPDATE documents SET property_id='PROP2'")
        image.db.execute("UPDATE document_versions SET property_id='PROP2'")
        image.snapshot["property_id"] = "PROP2"
        image.snapshot["teha_import"]["local_binding"]["property_id"] = "PROP2"
    elif damage == "missing_receipt":
        image.db.execute("DELETE FROM teha_import_receipts")
    elif damage == "chunk":
        image.db.execute("UPDATE document_version_chunks SET data=? WHERE position=1", (b"damaged",))
    if damage == "duplicate_json":
        value = canonical(image.snapshot).decode().replace('"schema_version":"teha-import/2"', '"schema_version":"teha-import/2","schema_version":"teha-import/2"')
    else:
        value = canonical(image.snapshot).decode()
    image.db.execute("UPDATE document_versions SET metadata_snapshot=?", (value,))
    image.seal()
    with pytest.raises(TehaImageError):
        image.validate()


@pytest.mark.parametrize("damage", ["ciphertext", "unknown_key", "namespace", "not_completed"])
def test_real_encrypted_image_binding_and_keys(image, damage):
    keys = None
    if damage == "ciphertext":
        image.db.execute("UPDATE integration_run_chunks SET ciphertext=substr(ciphertext,1,length(ciphertext)-1)||'A' WHERE event_id='source-run-3'")
    elif damage == "unknown_key":
        keys = IBANKeyring("other", {"other": base64.urlsafe_b64encode(bytes(reversed(range(32)))).decode("ascii")})
    else:
        image.history("replacement", "list_documents", {"lieg_nr": "L-41"}, {"documents": [image.document_row]},
                      connection_key="different" if damage == "namespace" else "C",
                      terminal="completed" if damage == "namespace" else "outcome_uncertain")
        image.db.execute("UPDATE teha_import_receipts SET source_history_run_id='replacement'")
        image.snapshot["teha_import"]["source_history_run_id"] = "replacement"
        image.db.execute("UPDATE document_versions SET metadata_snapshot=?", (canonical(image.snapshot).decode(),))
    image.seal()
    with pytest.raises(TehaImageError):
        image.validate(keys=keys)


@pytest.mark.parametrize("change", ["check", "type", "partial", "guard"])
def test_frozen_schema_proof_includes_constraints_and_guards(change):
    image = ImageFixture(schema_change=change)
    try:
        if change == "partial":
            image.db.execute("DROP INDEX uq_teha_import_document_version")
            image.db.execute("CREATE UNIQUE INDEX uq_teha_import_document_version ON teha_import_receipts(connection_key,external_identity_hash,source_sha256,content_sha256) WHERE source_kind='technical_order'")
        image.seal(omit_guard="preserve_teha_import_receipts_delete" if change == "guard" else None)
        with pytest.raises(TehaImageError, match="SCHEMA_INVALID"):
            image.validate()
    finally:
        image.db.close()


def test_frozen_varchar_primary_key_requires_native_not_null():
    image = ImageFixture(schema_change="nullable_pk")
    try:
        info = {row[1]: row for row in image.db.execute('PRAGMA main.table_info("teha_external_mappings")')}
        assert info["id"][2] == "VARCHAR" and info["id"][3] == 0 and info["id"][5] == 1
        assert image.db.execute("SELECT id FROM main.teha_external_mappings").fetchall() == [("MAP",)]
        image.seal()
        with pytest.raises(TehaImageError, match="TEHA_IMAGE_SCHEMA_INVALID"):
            image.validate()
    finally:
        image.db.close()


def test_empty_case_aliased_temp_shadows_cannot_hide_populated_main_image(image):
    # Main guards must be installed before unqualified names resolve to TEMP.
    # All mode changes and DDL below belong to this isolated fixture setup.
    image.seal()
    image.db.rollback()
    image.db.execute("PRAGMA query_only=OFF")
    aliases = {
        "teha_external_mappings": "TeHa_ExTeRnAl_MaPpInGs",
        "teha_import_receipts": "TEHA_IMPORT_RECEIPTS",
        "document_versions": "DoCuMeNt_VeRsIoNs",
        "document_version_chunks": "DOCUMENT_VERSION_CHUNKS",
    }
    for name, alias in aliases.items():
        ddl = image.db.execute(
            "SELECT sql FROM main.sqlite_schema WHERE type='table' AND name=?", (name,),
        ).fetchone()[0]
        prefix = f"CREATE TABLE {name}"
        assert ddl.startswith(prefix + " ")
        image.db.execute(ddl.replace(prefix, f'CREATE TEMP TABLE "{alias}"', 1))
        if name.startswith("teha_"):
            indices = image.db.execute(
                "SELECT name,sql FROM main.sqlite_schema WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (name,),
            ).fetchall()
            for index_name, index_ddl in indices:
                kind = "CREATE UNIQUE INDEX" if index_ddl.startswith("CREATE UNIQUE INDEX ") else "CREATE INDEX"
                prefix = f"{kind} {index_name}"
                assert index_ddl.startswith(prefix + " ") and f" ON {name} " in index_ddl
                temp_ddl = index_ddl.replace(prefix, f'{kind} temp."{index_name}"', 1)
                image.db.execute(temp_ddl.replace(f" ON {name} ", f' ON "{alias}" ', 1))
    image.db.commit()
    image.db.execute("PRAGMA query_only=ON")
    image.db.execute("BEGIN")
    main_counts = {name: image.db.execute(f'SELECT COUNT(*) FROM main."{name}"').fetchone()[0] for name in aliases}
    assert main_counts["teha_external_mappings"] == main_counts["teha_import_receipts"] == main_counts["document_versions"] == 1
    assert main_counts["document_version_chunks"] > 0
    assert all(image.db.execute(f'SELECT COUNT(*) FROM temp."{alias}"').fetchone()[0] == 0 for alias in aliases.values())
    assert all(image.db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] == 0 for name in aliases)
    assert image.db.in_transaction and image.db.execute("PRAGMA query_only").fetchone()[0] == 1
    assert image.db.execute("PRAGMA trusted_schema").fetchone()[0] == 0
    before = image.db.total_changes
    with pytest.raises(TehaImageError, match="TEHA_IMAGE_CONTEXT_REQUIRED"):
        image.validate()
    assert image.db.total_changes == before and image.db.in_transaction
    assert {name: image.db.execute(f'SELECT COUNT(*) FROM main."{name}"').fetchone()[0] for name in aliases} == main_counts


def test_explicit_resource_budget_rejects_instead_of_truncating_unknown_snapshot(image):
    image.snapshot["unknown"] = "preserve but exceed configured budget" * 5000
    image.db.execute("UPDATE document_versions SET metadata_snapshot=?", (canonical(image.snapshot).decode(),))
    image.seal()
    with pytest.raises(TehaImageError, match="BUDGET_EXCEEDED"):
        image.validate()


def test_missing_selected_read_transaction_is_rejected(image):
    image.db.commit()
    with pytest.raises(TehaImageError, match="CONTEXT_REQUIRED"):
        image.validate()


def test_actor_only_or_duck_key_configuration_is_not_an_image_keyring(image):
    image.seal()
    class PretendKeys:
        active_key_id = "fixture"
        keys = {}
    with pytest.raises(TehaImageError, match="KEYS_REQUIRED"):
        image.validate(keys=PretendKeys())


def test_absent_receipt_family_cannot_orphan_retained_teha_original(image):
    image.db.execute("DROP TABLE teha_import_receipts")
    image.db.execute("DROP TABLE teha_external_mappings")
    image.db.commit()
    image.db.execute("PRAGMA query_only=ON")
    image.db.execute("PRAGMA trusted_schema=OFF")
    image.db.execute("BEGIN")
    with pytest.raises(TehaImageError, match="FAMILY_MISSING"):
        image.validate()


def test_partial_l2_is_never_legacy_compatible(image):
    image.db.execute("DROP TABLE teha_import_receipts")
    image.db.commit()
    image.db.execute("PRAGMA query_only=ON")
    image.db.execute("PRAGMA trusted_schema=OFF")
    image.db.execute("BEGIN")
    with pytest.raises(TehaImageError, match="SCHEMA_INVALID"):
        image.validate()


def test_absent_l2_is_legacy_compatible_without_keys():
    db = sqlite3.connect(":memory:")
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN")
        report = validate_teha_receive_image(db, image_keys=None, history_limits=HISTORY_LIMITS,
                                            image_limits=LIMITS, deadline=time.monotonic() + 20)
        assert not report.family_present
    finally:
        db.close()
