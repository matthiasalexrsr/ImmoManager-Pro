"""Preserve authenticated generated draft PDF/ZIP without original claims."""

import hashlib
import json
from io import BytesIO
from zipfile import ZipFile

import pdfplumber
import pytest

from backend.services.utility_statement_original_source import (
    UtilityOriginalIntegrityError,
    source_digest,
    validate_preview,
)
from backend.tests.test_billing_disputes import context as context
from backend.tests.test_billing_disputes import draft_http as draft_http
from backend.tests.test_billing_disputes import finalized
from backend.tests.test_utility_statement_original_preview import BASE, bulk, get, independent_write, original_rows


def generated(context):
    context["key"]()
    for home in context["homes"]:
        context["meter"](home)
    result = context["generate"]()
    assert result.status_code == 201, result.text
    selected = next(row for row in result.json() if row["contract_id"] == context["leases"][0]["id"])
    # Native DateTime columns retain the actual persisted timestamp form;
    # compare exact stored GET JSON, rather than the precommit generate DTO.
    stored = context["active"].client.get(BASE + "/statements/" + selected["id"], headers=context["headers"])
    assert stored.status_code == 200, stored.text
    return stored.json()


def watermark(page):
    # A 45-degree watermark is not one word in geometric text extraction.
    # Require its actual large rotated glyphs in PDF paint order instead.
    return "".join(char["text"] for char in page.chars if char["size"] > 35 and abs(char["matrix"][1]) > 0.6)


def test_generated_draft_watermarked_private_sources_and_real_finalization_switch(context, monkeypatch, tmp_path):
    active = context["active"]
    statement = generated(context)
    context["patch"]("/tenants/" + context["leases"][0]["tenant_id"], {"full_name": "CURRENT_DRAFT_PROFILE"})
    assert get(context, statement).status_code == 409
    assert get(context, statement, "pdf", headers={}).status_code == 401
    monkeypatch.setattr(type(active.store), "create_document", lambda *_args, **_kwargs: pytest.fail("Draft preview created a document"))
    pdf = get(context, statement, "pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-"), pdf.text[:100]
    assert pdf.headers["x-utility-preview"] == "draft-derivation"
    assert pdf.headers["x-utility-render-profile"] == "utility-statement-draft-pdf-preview/1"
    assert "x-utility-original-sha256" not in pdf.headers
    assert pdf.headers["x-content-sha256"] == hashlib.sha256(pdf.content).hexdigest()
    assert get(context, statement, "pdf").content == pdf.content
    zipped = bulk(context, statement)
    assert zipped.status_code == 200, zipped.text[:100]
    assert bulk(context, statement).content == zipped.content
    with ZipFile(BytesIO(zipped.content)) as archive:
        source = json.loads(archive.read("statement_" + statement["id"] + ".source.json"))
        assert archive.read("statement_" + statement["id"] + ".pdf") == pdf.content
    assert source["mode"] == "draft" and source["schema_version"] == "utility-statement-draft-source/1"
    assert source["party_binding"] == "not_frozen" and source["original_party"] is None and source["previous_original"] is None
    assert source["statement_draft"] == {key: value for key, value in statement.items() if key not in {"delivery_status", "delivered_at", "delivery_channel", "updated_at"}}
    assert source["source_digest"] == pdf.headers["x-utility-source-sha256"] == source_digest({key: value for key, value in source.items() if key != "source_digest"})
    validate_preview(source)
    assert "CURRENT_DRAFT_PROFILE" not in json.dumps(source)
    altered = {**source, "original_party": {"identity": "guessed current party"}}
    altered["source_digest"] = source_digest({key: value for key, value in altered.items() if key != "source_digest"})
    with pytest.raises(UtilityOriginalIntegrityError):
        validate_preview(altered)
    with pdfplumber.open(BytesIO(pdf.content)) as document:
        text = "\n".join(page.extract_text() for page in document.pages)
        assert "Entwurf - nicht finalisiert" in text and "Mietpartei noch nicht eingefroren" in text
        assert all(watermark(page) == "ENTWURF" for page in document.pages)
        assert "CURRENT_DRAFT_PROFILE" not in text and "Originalhash der vollständigen Periode" not in text
    if active.engine is None:
        (tmp_path / "utility-draft-preview.pdf").write_bytes(pdf.content)
    response = active.client.post(BASE + "/periods/" + statement["billing_period_id"] + "/finalize", headers=context["headers"])
    assert response.status_code == 200, response.text
    original = get(context, statement)
    assert original.status_code == 200 and original.json()["original_party"]["identity"]["full_name"] == "CURRENT_DRAFT_PROFILE"
    actual = get(context, statement, "pdf")
    assert actual.status_code == 200 and actual.headers["x-utility-preview"] == "checked-derivation"
    assert actual.headers["x-utility-original-sha256"] == original.json()["statement_original"]["snapshot_hash"]
    with pdfplumber.open(BytesIO(actual.content)) as document:
        assert all(watermark(page) == "" for page in document.pages)


def test_actual_correction_draft_only_previous_original_is_frozen_and_full_source_hash_checked(context):
    active = context["active"]
    original = finalized(context)
    previous = get(context, original).json()
    response = active.client.post(BASE + "/periods/" + original["billing_period_id"] + "/revisions", headers=context["headers"])
    assert response.status_code == 200, response.text
    period_id = response.json()["new_period_id"]
    generated_response = active.client.post(BASE + "/periods/" + period_id + "/generate", headers=context["headers"])
    assert generated_response.status_code == 201, generated_response.text
    statement = next(row for row in generated_response.json() if row["contract_id"] == original["contract_id"])
    pdf, zipped = get(context, statement, "pdf"), bulk(context, statement)
    assert pdf.status_code == zipped.status_code == 200
    with ZipFile(BytesIO(zipped.content)) as archive:
        source = json.loads(archive.read("statement_" + statement["id"] + ".source.json"))
    assert source["original_party"] is None and source["party_binding"] == "not_frozen"
    assert source["previous_original"] == previous
    assert get(context, statement).status_code == 409
    sibling = next(row for row in original_rows(context) if row["billing_period_id"] == original["billing_period_id"] and row["id"] != original["id"])
    independent_write(context, "utility_statements", sibling["id"], total_cost=sibling["total_cost"] + 1)
    assert get(context, statement, "pdf").status_code == bulk(context, statement).status_code == 409


@pytest.mark.parametrize("draft_http", ["memory"], indirect=True)
def test_generated_multisheet_draft_has_watermark_on_every_page(context, tmp_path):
    key = context["key"](amount=2)
    for index in range(1, 37):
        context["post"]("/billing/cost-items", {"billing_period_id": context["period"]["id"], "allocation_key_id": key["id"], "amount": 2,
            "description": f"Entwurfsposition {index:02d}: Zoë Łukasz / Иван Петров / Μαρία Παπαδοπούλου - " + "Lange gespeicherte Entwurfsposition ohne Originalbehauptung. " * 2})
    for home in context["homes"]:
        context["meter"](home)
    result = context["generate"]()
    assert result.status_code == 201, result.text
    statement = next(row for row in result.json() if row["contract_id"] == context["leases"][0]["id"])
    pdf = get(context, statement, "pdf")
    assert pdf.status_code == 200, pdf.text[:100]
    (tmp_path / "utility-draft-multipage.pdf").write_bytes(pdf.content)
    with pdfplumber.open(BytesIO(pdf.content)) as document:
        assert 3 <= len(document.pages) <= 6
        for number, page in enumerate(document.pages, 1):
            text = page.extract_text()
            assert watermark(page) == "ENTWURF" and f"Seite {number}" in text
            if "Entwurfsposition " in text:
                assert "Kostenart" in text and "Anteil" in text
        text = "\n".join(page.filter(lambda item: item.get("object_type") != "char" or abs(item["matrix"][1]) < 0.6).extract_text()
            for page in document.pages)
        for index in range(1, 37):
            assert f"Entwurfsposition {index:02d}:" in text
