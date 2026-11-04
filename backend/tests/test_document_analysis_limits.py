"""Direct API analysis rejects partial real files clearly and keeps their originals."""

from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from test_meter_documents import ISTA, case  # noqa: F401

from backend.dependencies import store
from backend.services import assistant_providers, document_text, meter_documents_ai
from backend.services.document_text_reader import ExtractionPart
from backend.services.file_storage import get_file_storage


def mixed_pdf():
    output = BytesIO()
    pdf = canvas.Canvas(output)
    for index, line in enumerate(ISTA.splitlines()):
        pdf.drawString(50, 800 - 14 * index, line)
    pdf.showPage()
    # With OCR installed this exceeds the pixel budget before rendering;
    # without it the scanned page has an explicit missing-OCR warning.
    pdf.setPageSize((4000, 4000))
    pdf.drawImage(ImageReader(Image.new("RGB", (20, 20), "black")), 50, 50)
    pdf.showPage()
    pdf.save()
    return output.getvalue()


@pytest.mark.parametrize("consumer", ["reading_document", "reading_upload", "meter"])
@pytest.mark.parametrize("reader", ["local", "claude"])
def test_partial_mixed_pdf_is_422_without_partial_values_or_destroying_original(case, monkeypatch, consumer, reader):  # noqa: F811
    content = mixed_pdf()
    key = f"documents/{uuid4().hex}-mixed.pdf"
    get_file_storage().save(key, BytesIO(content), content_type="application/pdf")
    client = case["clients"]["eigentuemer"]
    response = client.post(
        "/api/v1/documents",
        json={"title": "Gemischter Beleg", "property_id": case["property"].id, "file_url": "/uploads/" + key},
    )
    assert response.status_code == 201, response.text
    document = response.json()

    def no_fallback(*args, **kwargs):
        pytest.fail("A partial local extraction must not start an implicit AI fallback")

    monkeypatch.setattr(
        assistant_providers, "connection_status", lambda *args: {"connected": True, "client_available": True}
    )
    monkeypatch.setattr(assistant_providers, "execute", no_fallback)
    monkeypatch.setattr(meter_documents_ai, "extract", no_fallback)
    before = (len(store.list_cost_items()), len(store.list_standalone_meter_readings()))
    if consumer == "meter":
        result = client.post(
            f"/api/v1/billing/meter-documents/{document['id']}/analysis",
            json={"billing_period_id": case["period"].id, "reader": reader},
        )
    else:
        source = (
            {"document_id": document["id"]} if consumer == "reading_document" else {"file_url": document["file_url"]}
        )
        result = client.post(
            "/api/v1/ai/readings",
            json={
                "surface": "document",
                "params": {"property_id": case["property"].id},
                "reader": reader,
                "idempotency_key": uuid4().hex,
                **source,
            },
        )
    assert result.status_code == 422, result.text
    error = result.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "nicht vollständig gelesen" in error["message"] and "keine Teilwerte" in error["message"]
    assert not any(key in result.json() for key in ["values", "costs", "readings"])
    assert (len(store.list_cost_items()), len(store.list_standalone_meter_readings())) == before
    original = client.get(f"/api/v1/documents/{document['id']}/file")
    assert original.status_code == 200 and original.content == content


@pytest.mark.parametrize("consumer", ["reading", "meter"])
def test_intact_real_pdf_still_produces_a_local_proposal(case, consumer):  # noqa: F811
    client = case["clients"]["eigentuemer"]
    if consumer == "reading":
        result = client.post(
            "/api/v1/ai/readings",
            json={
                "surface": "document",
                "document_id": case["document"]["id"],
                "params": {"property_id": case["property"].id},
                "reader": "local",
                "idempotency_key": uuid4().hex,
            },
        )
        assert result.status_code == 201, result.text
        reading = result.json()
        try:
            assert reading["reader"] == "local" and reading["values"]
        finally:
            # The shared meter fixture does not create personal conversations.
            # Remove only this test's new memory conversation before its
            # guarded business-data cleanup; SQL removes it with the test user.
            if not hasattr(store, "db"):
                families = store.__dict__.get("_integration_connections", {})
                for name in ["assistant_messages", "assistant_conversations"]:
                    rows = families.get(name, {})
                    for key, row in list(rows.items()):
                        if key == reading["id"] or getattr(row, "conversation_id", None) == reading["id"]:
                            rows.pop(key)
    else:
        result = client.post(
            f"/api/v1/billing/meter-documents/{case['document']['id']}/analysis",
            json={"billing_period_id": case["period"].id, "reader": "local"},
        )
        assert result.status_code == 200, result.text
        assert result.json()["company"] == "ista" and len(result.json()["costs"]) == 6


@pytest.mark.parametrize("readable_prefix", ["", "Lesbarer Anfang"])
def test_direct_extraction_uses_exactly_one_bounded_worker_even_without_text_progress(monkeypatch, readable_prefix):
    calls = []

    def continuing(*args, **kwargs):
        calls.append((args, kwargs))
        return ExtractionPart(
            text=readable_prefix,
            source="pdf_text",
            complete=False,
            indexed_units=500,
            total_units=1000,
            cursor={"page": 500, "offset": 0},
        )

    monkeypatch.setattr(document_text, "extract_part", continuing)
    with pytest.raises(ValueError, match="unvollständig"):
        document_text.extract(b"owned-test-input", "large.pdf")
    assert len(calls) == 1


@pytest.mark.parametrize("consumer", ["reading", "meter"])
def test_large_real_file_is_rejected_by_direct_analysis_but_durable_search_finishes_it(case, consumer):  # noqa: F811
    content = "x" * (document_text.MAX_CHARACTERS + 10) + " Endefund"
    key = f"documents/{uuid4().hex}-large.txt"
    get_file_storage().save(key, BytesIO(content.encode()), content_type="text/plain")
    client = case["clients"]["eigentuemer"]
    uploaded = client.post(
        "/api/v1/documents",
        json={"title": "Großer Beleg", "property_id": case["property"].id, "file_url": "/uploads/" + key},
    )
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()
    if consumer == "reading":
        response = client.post(
            "/api/v1/ai/readings",
            json={
                "surface": "document",
                "document_id": document["id"],
                "params": {"property_id": case["property"].id},
                "reader": "local",
                "idempotency_key": uuid4().hex,
            },
        )
    else:
        response = client.post(
            f"/api/v1/billing/meter-documents/{document['id']}/analysis",
            json={"billing_period_id": case["period"].id, "reader": "local"},
        )
    assert response.status_code == 422 and "keine Teilwerte" in response.json()["error"]["message"]
    # The production index still uses persisted continuation and reads the tail.
    while document_text.index_pending(store)[1] is not None:
        pass
    row = document_text.get(store, document["id"])
    assert row is not None and row.complete and row.warning is None and row.text == content
    assert document_text.search(store, "Endefund")["total"] == 1
