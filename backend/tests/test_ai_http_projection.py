"""Real HTTP projections preserve full model evidence and honest partial states."""

from dataclasses import asdict, dataclass, field
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.routers import files, messages
from backend.services.ai.schemas import (
    AnalysisCoverage,
    DocumentAIResult,
    EntityMention,
    MissingRange,
    SourceRange,
    ThreadSummaryResult,
)


@dataclass
class FutureDocumentResult(DocumentAIResult):
    future_model_values: dict = field(default_factory=lambda: {"late": [0, False, "tail"]})


@dataclass
class FutureThreadResult(ThreadSummaryResult):
    future_model_values: dict = field(default_factory=lambda: {"late": [0, False, "tail"]})


@pytest.fixture
def http_context():
    store.clear_all()
    clear_users()
    user = register_user("projection", "projection@example.com", "Projection", "Synthetic123!", "eigentuemer")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    with TestClient(app) as client:
        yield client, headers
    clear_users()
    store.clear_all()


def _upload(client, headers, monkeypatch, *, text="synthetic complete source"):
    monkeypatch.setattr(files, "_perform_ocr", lambda _storage, _key, _ext: text)
    uploaded = client.post(
        "/api/v1/files/upload?folder=documents",
        files={"file": ("synthetic.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        headers=headers,
    )
    assert uploaded.status_code == 200, uploaded.text
    url = uploaded.json()["file_url"]
    ocr_key = files._ocr_key_from_file_key(files._file_url_to_key(url))
    files.get_file_storage().save(ocr_key, BytesIO(text.encode()), content_type="text/plain")
    return url


def _coverage(complete):
    return AnalysisCoverage(
        "ner", 10007, "a" * 64, complete, "tokens", 128,
        covered_ranges=[SourceRange(0, 0, 10000)],
        missing_ranges=[] if complete else [MissingRange(1, 10000, 10007, "pipeline_error", "RuntimeError")],
    )


@pytest.mark.parametrize("complete", [True, False])
@pytest.mark.parametrize("endpoint", ["/api/v1/files/analyze", "/api/v1/documents/ocr-analyze"])
def test_document_http_preserves_every_result_field_and_complete_state(http_context, monkeypatch, complete, endpoint):
    client, headers = http_context
    url = _upload(client, headers, monkeypatch)
    expected = FutureDocumentResult(
        document_type="Rechnung", invoice_number="TAIL-10007", total_amount=250.0,
        language="de", analysis_complete=complete, coverage={"ner": _coverage(complete)},
        entity_mentions=[EntityMention(1, 10000, 10007, "tail", source_start_offset=10000,
                                      source_end_offset=10007, model_fields={"unknown": {"value": False}})],
        classification_sections=[{"unknown_label_value": "tail"}],
        summary_sections=[{"end_offset": 10007, "summary_text": "later source"}],
    )
    observed = []

    def analyze(text, use_ai):
        observed.append((text, use_ai))
        return expected

    monkeypatch.setattr(files, "analyze_document", analyze)
    if endpoint.endswith("/files/analyze"):
        response = client.post(endpoint, params={"file_url": url, "use_ai": True}, headers=headers)
    else:
        response = client.post(endpoint, json={"file_url": url, "use_ai": True}, headers=headers)
    assert response.status_code == 200, response.text
    actual = response.json()
    assert observed == [("synthetic complete source", True)]
    assert actual["result"] == asdict(expected)
    assert actual["analyzed"] is complete
    assert actual["analysis_complete"] is complete
    assert actual["partial"] is (not complete)
    if complete:
        assert actual["message"] == "Analyse abgeschlossen"
    else:
        assert "Teilergebnis" in actual["message"]
        assert "Analyse abgeschlossen" not in actual["message"]
        assert actual["result"]["invoice_number"] == "TAIL-10007"
    if endpoint.endswith("/ocr-analyze"):
        assert actual["has_ocr"] is True
        assert actual["success"] is complete


@pytest.mark.parametrize("complete", [True, False])
def test_thread_http_preserves_full_evidence_and_source_count(http_context, monkeypatch, complete):
    client, headers = http_context
    response = client.post("/api/v1/messages/threads", json={"subject": "Synthetic thread"}, headers=headers)
    assert response.status_code == 201, response.text
    thread_id = response.json()["id"]
    for body in ["first", "late"]:
        posted = client.post(f"/api/v1/messages/threads/{thread_id}/messages",
                             json={"thread_id": thread_id, "sender_name": "Synthetic", "body": body}, headers=headers)
        assert posted.status_code == 201, posted.text
    expected = FutureThreadResult(summary="summary", analysis_complete=complete,
                                  coverage={"summarization": _coverage(complete)},
                                  summary_sections=[{"end_offset": 10007, "late": True}],
                                  action_items=[f"action {number}" for number in range(15)])
    observed = []

    def summarize(values, subject):
        observed.append((values, subject))
        return expected

    monkeypatch.setattr(messages, "summarize_thread", summarize)
    response = client.post(f"/api/v1/messages/threads/{thread_id}/summarize", headers=headers)
    assert response.status_code == 200, response.text
    assert observed == [([{"sender_name": "Synthetic", "body": "first"},
                         {"sender_name": "Synthetic", "body": "late"}], "Synthetic thread")]
    assert response.json() == {**asdict(expected), "thread_id": thread_id, "message_count": 2}


def test_analysis_empty_text_is_not_reported_as_partial_result(http_context, monkeypatch):
    client, headers = http_context
    url = _upload(client, headers, monkeypatch, text="")
    monkeypatch.setattr(files, "analyze_document", lambda *_args, **_kwargs: pytest.fail("no source to analyze"))
    response = client.post("/api/v1/files/analyze", params={"file_url": url}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"analyzed": False, "analysis_complete": False, "partial": False,
                               "message": "Kein Text extrahierbar", "result": None}


def test_analysis_authentication_still_precedes_model_processing(http_context, monkeypatch):
    client, headers = http_context
    url = _upload(client, headers, monkeypatch)
    monkeypatch.setattr(files, "analyze_document", lambda *_args, **_kwargs: pytest.fail("no authorized caller"))
    for endpoint in ["/api/v1/files/analyze", "/api/v1/documents/ocr-analyze"]:
        response = client.post(endpoint, params={"file_url": url}, json={"file_url": url})
        assert response.status_code == 401, response.text
