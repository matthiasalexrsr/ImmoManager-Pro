"""Evidence must name the received bytes, with stable numbers and current grants."""
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.db.document_version_models import DocumentVersionORM
from backend.dependencies import store
from backend.finance_models import PlannedFlow, ReportDefinition
from backend.invoice_review_models import InvoiceReview
from backend.models import DocumentCreate, InvoiceCreate
from backend.privacy_models import ControlChange
from backend.services import document_versions as archive
from backend.services import finance_reports
from backend.services.maintenance_rows import Rows
from backend.services.privacy import controls
from backend.tests.test_finance_packages_v2 import clean as clean
from backend.tests.test_finance_packages_v2 import estate as estate


def evidence(estate):
    actor = auth.register_user("evidence", "evidence@example.test", "Prüfung", "Secret123", "eigentuemer")
    doc = store.create_document(DocumentCreate(title="Rechnungsoriginal", property_id=estate[1].id, file_url="/uploads/test/report.pdf"))
    with archive.work(store, actor.id, write_areas=("/documents",)) as unit:
        _, binding = archive.bind_document(unit, doc.id)
        first = archive.publish_generated_original(unit, doc, binding, b"%PDF-1.7\nfirst\n%%EOF", "a" * 64, version_id=str(uuid4()))
        # A subsequent archived version must not silently replace the receipt's proof.
        content = b"%PDF-1.7\nsecond\n%%EOF"
        import hashlib
        second = DocumentVersionORM(**{column.key: getattr(first, column.key) for column in first.__table__.columns})
        second.id, second.number, second.predecessor_id = str(uuid4()), 2, first.id
        second.sha256, second.size_bytes = hashlib.sha256(content).hexdigest(), len(content)
        second.idempotency_key, second.operation = uuid4().hex, "upload"
        archive.persist_version_bytes(unit, second, [content])
    invoice = store.create_invoice(InvoiceCreate(property_id=estate[1].id, supplier="Belegfirma",
        invoice_date=date(2026, 1, 10), net_amount=100, gross_amount=119, vat_amount=19))
    with archive.work(store, actor.id, write_areas=("/invoices",)) as unit:
        Rows.of(unit).add("invoice_reviews", InvoiceReview(id=str(uuid4()), invoice_id=invoice.id, received_on=date(2026, 1, 10),
            document_id=doc.id, document_sha256=first.sha256, property_id=estate[1].id))
    return actor, doc, invoice, first, second


def test_received_original_and_source_hash_survive_new_head_and_retrieval_clock(estate):
    actor, doc, invoice, first, second = evidence(estate)
    definition = ReportDefinition(kind="performance-period-v2", as_of=date(2026, 1, 31))
    result = finance_reports.compute(store, definition)
    original = next(item["provenance"]["original"] for item in result["sources"] if item["identity"] == "invoice:" + invoice.id)
    assert original["version_id"] == first.id != second.id and original["sha256"] == first.sha256
    assert original["reference"] == "receipt_sha256"
    assert result["provenance"]["verified_originals"] == 1
    again = finance_reports.compute(store, definition)
    assert result["result_hash"] == again["result_hash"] and result["generated_at"] != again["generated_at"]
    assert result["totals"] == again["totals"]
    with TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(actor.id)}) as client:
        response = client.get("/api/v1" + original["download"])
        assert response.status_code == 200, response.text
        assert b"first" in response.content and b"second" not in response.content
        for format_ in ("csv", "pdf"):
            output = client.get("/api/v1/reports/v2/preview", params={"definition": definition.model_dump_json(), "format": format_, "expected_result_hash": result["result_hash"]})
            assert output.status_code == 200, output.text[:500]
            if format_ == "csv":
                assert first.id in output.text and first.sha256 in output.text and "Datenabruf UTC" in output.text


def test_restricted_proof_is_redacted_and_stale_export_rejected(estate):
    actor, doc, invoice, first, second = evidence(estate)
    definition = ReportDefinition(kind="performance-period-v2", as_of=date(2026, 1, 31))
    before = finance_reports.compute(store, definition)
    item = controls.detail(store, actor.id, "document", doc.id)
    controls.change(store, actor.id, "document", doc.id, ControlChange(action="restrict", expected_revision=item["revision"],
        source_sha256=item["source_sha256"], reason="Original zur Datenschutzprüfung gesperrt.", idempotency_key=uuid4().hex))
    after = finance_reports.compute(store, definition)
    original = next(item["provenance"]["original"] for item in after["sources"] if item["identity"] == "invoice:" + invoice.id)
    assert original["status"] == "unavailable" and "document_id" not in original and "download" not in original
    assert after["provenance"]["invoices_without_verified_original"] == 1 and after["totals"] == before["totals"]
    assert after["result_hash"] != before["result_hash"]
    with TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(actor.id)}) as client:
        output = client.get("/api/v1/reports/v2/preview", params={"definition": definition.model_dump_json(), "format": "csv", "expected_result_hash": before["result_hash"]})
        assert output.status_code == 409, output.text


def test_mislabelled_planning_identity_is_still_an_assumption(estate):
    _, _, invoice, _, _ = evidence(estate)
    result = finance_reports.compute(store, ReportDefinition(kind="liquidity-v2", as_of=date(2026, 1, 15), months=3,
        planned_flows=[PlannedFlow.model_validate({"identity": "invoice:" + invoice.id, "day": "2026-01-20", "amount": "-42", "label": "Eigene Annahme"})]))
    planned = next(item for item in result["sources"] if item["identity"] == "invoice:" + invoice.id)
    assert planned["provenance"]["kind"] == "assumption"
    assert "original" not in planned["provenance"]
    assert result["provenance"]["assumptions"] == 1


def test_source_rows_come_from_the_calculation_snapshot(estate, monkeypatch):
    if not hasattr(store, "db"):
        pytest.skip("Independent SQL connection needed for concurrent update")
    from sqlalchemy import update

    from backend.db.orm_models import InvoiceORM
    from backend.services import report_provenance
    _, _, invoice, _, _ = evidence(estate)
    original = report_provenance.enrich
    def update_after_numbers(source, result, mode):
        with store.db.get_bind().begin() as connection:
            connection.execute(update(InvoiceORM).where(InvoiceORM.id == invoice.id).values(supplier="Changed after calculation"))
        return original(source, result, mode)
    monkeypatch.setattr(report_provenance, "enrich", update_after_numbers)
    result = finance_reports.compute(store, ReportDefinition(kind="performance-period-v2", as_of=date(2026, 1, 31)))
    source = next(item["provenance"] for item in result["sources"] if item["identity"] == "invoice:" + invoice.id)
    from backend.services.receivable_residuals import digest
    assert source["source_sha256"] == digest(invoice.model_dump(mode="json"))

