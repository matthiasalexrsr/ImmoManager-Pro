"""Fixed synthetic corpus: exact sources, forged quotations and revoked access.

Provider responses are deterministic substitutes. These tests prove server
boundaries, not the accuracy or instruction resistance of an external model.
"""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend import auth
from backend.dependencies import store
from backend.models import DocumentCreate
from backend.privacy_models import ControlChange
from backend.services import (
    assistant_context,
    assistant_proposals,
    assistant_providers,
    assistant_tools,
    document_versions,
)
from backend.services.file_storage import LocalStorage, get_file_storage
from backend.services.privacy import controls
from backend.services.source_citations import annotate_values, locate
from backend.tests.test_ai_reading import _answer, _pdf, _start, _upload
from backend.tests.test_ai_reading import case as case

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "ai_evidence_corpus.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("sample", CORPUS, ids=lambda sample: sample["id"])
def test_quotes_are_located_in_archived_version_without_executing_document_instructions(case, monkeypatch, sample):
    raw = _pdf(sample["text"])
    doc = store.create_document(DocumentCreate(title="Prüfkorpus", property_id=case["property"].id, file_url=_upload(raw)))
    owner = case["users"]["eigentuemer"].id
    with document_versions.work(store, owner, write_areas=("/documents",)) as unit:
        _, binding = document_versions.bind_document(unit, doc.id)
        version = document_versions.publish_generated_original(unit, doc, binding, raw, "a" * 64, version_id=str(uuid4()))
    payload = {"values": {"gross_amount": {"value": sample["value"], "evidence": sample["quote"], "confidence": "high"}},
               "approve_payment": True, "bank_transfer": "attacker.invalid"}
    _answer(monkeypatch, case, "```immomanager-reading\n" + json.dumps(payload) + "\n```")
    result = _start(case, document_id=doc.id, reader="claude")
    assert result.status_code == 201, result.text
    data = result.json()
    citation = data["values"]["gross_amount"]["citation"]
    request = case["seen"][-1]["request"]
    text = request["attachments"][0]["text"]
    assert text[citation["start_char"]:citation["end_char"]] == sample["quote"]
    assert citation["file_sha256"] == hashlib.sha256(raw).hexdigest()
    assert citation["version_id"] == version.id == data["file"]["version_id"]
    assert citation["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert citation["multiple_occurrences"] == (sample["id"] == "repeated-quote")
    assert request["data_scope"] == "selected" and request["web_research"] is False
    assert not store.list_invoices() and not store.list_bookings() and "approve_payment" not in data


def test_fabricated_and_absent_quotes_are_visible_low_confidence(case, monkeypatch):
    _answer(monkeypatch, case, '```immomanager-reading\n{"values": {"gross_amount": {"value": "99", "evidence": "frei erfunden", "confidence": "high"}, "supplier": {"value": "Unbelegt"}}}\n```')
    result = _start(case, file_url=_upload(_pdf(CORPUS[0]["text"])), reader="claude")
    assert result.status_code == 201, result.text
    values = result.json()["values"]
    assert values["gross_amount"]["evidence_status"] == "not_found"
    assert values["supplier"]["evidence_status"] == "missing"
    assert all(item["confidence"] == "low" and item["citation"] is None for item in values.values())


def test_a_proposal_rejects_forged_offsets_text_hash_and_wrong_version(case):
    sample = CORPUS[1]
    raw = _pdf(sample["text"])
    doc = store.create_document(DocumentCreate(title="Quellenbeleg", property_id=case["property"].id, file_url=_upload(raw)))
    owner = case["users"]["eigentuemer"].id
    bundle = assistant_context.build_context(store, {"property_ids": [case["property"].id], "document_ids": [doc.id]}, owner)
    text, _ = assistant_tools._full_text(raw, "invoice.pdf")
    quote = locate(text, sample["quote"])
    location = {key: quote[key] for key in ("quote", "start_char", "end_char", "text_sha256")}
    evidence = [{key: source[key] for key in ("kind", "id", "revision", "sha256")} for source in bundle["sources"]]
    docref = next(item for item in evidence if item["kind"] == "document")
    docref["location"] = location
    proposal: dict[str, Any] = {"kind": "task", "anchor": {"kind": "property", "id": case["property"].id},
                "values": {"title": "Rechnung fachlich prüfen", "property_id": case["property"].id}, "evidence": evidence}
    reviewed = assistant_proposals.validate_proposal(store, proposal, owner, context_bundle=bundle)
    assert any(item.get("citation", {}).get("verified") for item in reviewed["evidence"] if item.get("citation"))
    for change, status in (({"location": {**location, "quote": "Falscher Rechnungsbetrag"}}, 422),
                           ({"location": {**location, "text_sha256": "0" * 64}}, 409),
                           ({"version_id": str(uuid4())}, 409)):
        invalid = deepcopy(proposal)
        next(item for item in invalid["evidence"] if item["kind"] == "document").update(change)
        with pytest.raises(HTTPException) as rejected:
            assistant_proposals.validate_proposal(store, invalid, owner, context_bundle=bundle)
        assert rejected.value.status_code == status
    assert not store.list_tasks()


@pytest.mark.parametrize("change,status", [("bytes", 409), ("rights", 404)])
def test_source_and_role_are_rechecked_after_provider_returns(case, monkeypatch, change, status):
    url = _upload(_pdf(CORPUS[0]["text"]))
    def execute(*args):
        if change == "bytes":
            storage = get_file_storage()
            assert isinstance(storage, LocalStorage)
            from backend.services.filesystem_paths import filesystem_path
            filesystem_path(storage._path(url.removeprefix("/uploads/"))).write_bytes(_pdf("Nachträglich geändert"))
        else:
            auth.update_user(case["users"]["eigentuemer"].id, {"role": "readonly"})
        return {"text": '```immomanager-reading\n{"values": {}}\n```'}
    monkeypatch.setattr(assistant_providers, "execute", execute)
    result = _start(case, file_url=url, reader="claude")
    assert result.status_code == status, result.text
    assert not store.list_invoices() and not store.list_bookings()


def test_restricted_document_cannot_be_read_via_its_upload_or_existing_reading(case):
    url = _upload(_pdf(CORPUS[0]["text"]))
    doc = store.create_document(DocumentCreate(title="Gesperrte Quelle", property_id=case["property"].id, file_url=url))
    initial = _start(case, file_url=url, reader="local")
    assert initial.status_code == 201, initial.text
    owner = case["users"]["eigentuemer"].id
    detail = controls.detail(store, owner, "document", doc.id)
    controls.change(store, owner, "document", doc.id, ControlChange(action="restrict", expected_revision=detail["revision"],
        source_sha256=detail["source_sha256"], reason="KI-Verarbeitung ausdrücklich gesperrt.", idempotency_key=uuid4().hex))
    assert _start(case, file_url=url, reader="local").status_code == 404
    assert _start(case, document_id=doc.id, reader="local").status_code == 404
    assert case["clients"]["eigentuemer"].get("/api/v1/ai/readings/" + initial.json()["id"]).status_code == 404


def test_quotes_outside_supplied_excerpt_and_image_observations_are_not_verified():
    found = annotate_values({"amount": {"value": "20", "evidence": "Betrag 20"}}, "Text ohne Betrag")
    assert found["amount"]["evidence_status"] == "not_found"
    image = annotate_values({"value": {"value": "10", "evidence": "Zähler 10"}}, "")
    assert image["value"]["evidence_status"] == "text_unavailable"
    assert locate("[Seite 900]\nBetrag 20", "Betrag 20")["line"] == 2


def test_document_restriction_also_filters_duplicate_search(case):
    raw = _pdf(CORPUS[0]["text"])
    doc = store.create_document(DocumentCreate(title="Vertraulicher Titel", property_id=case["property"].id, file_url=_upload(raw)))
    owner = case["users"]["eigentuemer"].id
    initial = _start(case, surface="document", file_url=_upload(raw), reader="local")
    assert initial.status_code == 201, initial.text
    assert initial.json()["duplicates"][0]["id"] == doc.id
    detail = controls.detail(store, owner, "document", doc.id)
    controls.change(store, owner, "document", doc.id, ControlChange(action="restrict", expected_revision=detail["revision"],
        source_sha256=detail["source_sha256"], reason="Dokument nicht für Suchverarbeitung freigegeben.", idempotency_key=uuid4().hex))
    new = _start(case, surface="document", file_url=_upload(raw), reader="local")
    assert new.status_code == 201 and new.json()["duplicates"] == []
    assert case["clients"]["eigentuemer"].get("/api/v1/ai/readings/" + initial.json()["id"]).status_code == 404


def test_pdf_extractor_works_without_optional_pdf_engine(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "fitz", None)
    text, warnings = assistant_tools._full_text(_pdf(CORPUS[0]["text"]), "invoice.pdf")
    assert CORPUS[0]["quote"] in text and "Bildseiten" in warnings[0]
    with pytest.raises(Exception):
        assistant_tools._full_text(b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///not-readable">]><x>&x;</x>', "invoice.xml")

