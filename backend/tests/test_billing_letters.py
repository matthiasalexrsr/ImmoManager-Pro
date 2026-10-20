"""Real billing correspondence: unchanged issued PDFs, source fencing, originals and safe retry."""
import hashlib
from copy import deepcopy
from datetime import date
from io import BytesIO
from uuid import uuid4

import pytest
from archive_helpers import lease_with_document, purge_originals
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import AllocationKeyCreate, BillingPeriodCreate, CostItemCreate, CostItemPatch, TenantCreate
from backend.routers import billing
from backend.services import billing_letters as service
from backend.services import document_versions as archive
from backend.services.billing_letter_types import LetterPublish
from backend.services.billing_letter_validation import DOC_TYPE
from backend.services.data_snapshot import clear_business_data, export_snapshot
from backend.services.document_original_snapshot import parse
from backend.services.document_version_validation import validate_feature_snapshot, verify_document_versions


@pytest.fixture
def case():
    purge_originals(store)
    clear_business_data(store)
    auth.clear_users()
    owner = auth.register_user("billing-owner", "billing@example.test", "Linda Reiser", "Secret123", "eigentuemer")
    lease = lease_with_document(store)
    period = store.create_billing_period(BillingPeriodCreate(property_id=lease["property"].id, label="BK 2025",
        start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)))
    key = store.create_allocation_key(AllocationKeyCreate(property_id=lease["property"].id, name="Einheiten", key_type="unit_count"))
    cost = store.create_cost_item(CostItemCreate(billing_period_id=period.id, description="Wasser & Abwasser <2025>",
        amount=1200, allocation_key_id=key.id))
    statement = billing.generate_utility_statements(period.id)[0]
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)})
    yield {**lease, "period": period, "cost": cost, "key": key, "statement": statement, "owner": owner, "client": client}
    client.close()
    purge_originals(store)
    auth.clear_users()
    clear_business_data(store)


def base(case):
    return "/api/v1/billing/statements/" + case["statement"].id


def preview(case, *, finalized=True, **changes):
    if finalized and store.get_billing_period(case["period"].id).status == "draft":
        billing.finalize_billing_period(case["period"].id)
    context = case["client"].get(base(case) + "/letter-context")
    assert context.status_code == 200, context.text
    data = {**context.json()["defaults"], "sender_address": "Prießnitzstraße 4\n01099 Dresden",
            "recipient_name": "Zoë Łukasz Иван Μαρία", "recipient_address": "Neue Straße 15\n01097 Dresden", **changes}
    payload = {"source_revision": context.json()["source_revision"], "data": data}
    response = case["client"].post(base(case) + "/letter-preview", json=payload)
    assert response.status_code == 200, response.text
    return payload, response.json()


def command(payload, review, key="billing-letter-001"):
    return {**payload, "review_hash": review["review_hash"], "idempotency_key": key}


def publish(case, **changes):
    payload, review = preview(case, **changes)
    response = case["client"].post(base(case) + "/letter-publish", json=command(payload, review))
    assert response.status_code == 201, response.text
    return payload, review, response.json()


def test_context_warns_missing_addresses_and_draft_preview_is_marked_without_writes(case):
    response = case["client"].get(base(case) + "/letter-context")
    assert response.status_code == 200
    context = response.json()
    assert context["can_publish"] is False
    assert context["defaults"]["sender_name"] == "Linda Reiser"
    assert "Objektanschrift" in " ".join(context["warnings"])
    payload, shown = preview(case, finalized=False)
    assert shown["review"]["draft"] is True
    pdf = case["client"].post(base(case) + "/letter-preview-pdf", json=payload)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    assert hashlib.sha256(pdf.content).hexdigest() == shown["pdf_sha256"]
    import pdfplumber
    with pdfplumber.open(BytesIO(pdf.content)) as document:   # as the browser workflow reads it
        assert "ENTWURF – nicht zum Versand" in "\n".join(page.extract_text() or "" for page in document.pages)
    assert case["client"].post(base(case) + "/letter-publish", json=command(payload, shown)).status_code == 409
    assert archive.count_originals(store, "contract", case["contract"].id) == 0
    assert not [doc for doc in store.list_documents() if doc.document_type == DOC_TYPE]


def test_default_country_alone_is_not_a_recipient_address(case):
    store.update_tenant(case["tenant"].id, TenantCreate(full_name="Mieter ohne Anschrift", country="Deutschland"))
    context = case["client"].get(base(case) + "/letter-context").json()
    assert context["defaults"]["recipient_address"].startswith(case["property"].address_line)
    assert "Objektanschrift ist nur ein zu prüfender Vorschlag" in " ".join(context["warnings"])
    assert context["defaults"]["recipient_address"] != "Deutschland"


def test_saved_letter_replay_survives_correction_but_new_publication_is_draft_only(case):
    payload, shown, saved = publish(case)
    correction = billing.create_period_revision(case["period"].id)
    billing.generate_utility_statements(correction["new_period_id"])
    billing.finalize_billing_period(correction["new_period_id"])
    context = case["client"].get(base(case) + "/letter-context").json()
    assert context["period_status"] == "corrected" and not context["can_publish"]
    replayed = case["client"].post(base(case) + "/letter-publish", json=command(payload, shown))
    assert replayed.status_code == 201 and replayed.json() == saved
    assert case["client"].get("/api/v1" + saved["download_url"]).status_code == 200
    next_payload = {"source_revision": context["source_revision"], "data": payload["data"]}
    next_shown = case["client"].post(base(case) + "/letter-preview", json=next_payload).json()
    assert next_shown["review"]["draft"] is True
    refused = case["client"].post(base(case) + "/letter-publish",
        json=command(next_payload, next_shown, "billing-corrected-new"))
    assert refused.status_code == 409
    assert archive.count_originals(store, "contract", case["contract"].id) == 1


def test_publish_replays_exact_response_and_original_with_lost_success_response(case):
    payload, shown, saved = publish(case)
    pdf = case["client"].post(base(case) + "/letter-preview-pdf", json=payload)
    assert pdf.headers["x-review-sha256"] == shown["review_hash"]
    assert hashlib.sha256(pdf.content).hexdigest() == saved["pdf_sha256"] == shown["pdf_sha256"]
    first = case["client"].get("/api/v1" + saved["download_url"])
    assert first.status_code == 200 and first.content == pdf.content
    assert "private" in first.headers["cache-control"]
    repeated = case["client"].post(base(case) + "/letter-publish", json=command(payload, shown))
    assert repeated.status_code == 201 and repeated.json() == saved
    assert archive.count_originals(store, "contract", case["contract"].id) == 1
    assert case["client"].get(base(case) + "/letter-context").json()["originals"] == [saved]
    changed = command(payload, shown)
    changed["data"] = {**changed["data"], "subject": "Andere Verwendung derselben Vorgangskennung"}
    assert case["client"].post(base(case) + "/letter-publish", json=changed).status_code == 409


def test_stale_sources_and_wrong_review_never_publish_and_issued_pdf_is_unchanged(case):
    payload, shown = preview(case)
    legacy = billing.download_utility_statement_pdf(case["statement"].id).body
    wrong = {**command(payload, shown), "review_hash": "0" * 64}
    assert case["client"].post(base(case) + "/letter-publish", json=wrong).status_code == 409
    store.update_tenant(case["tenant"].id, TenantCreate(full_name="Neuer Name", address_line="Umgezogen 1"))
    assert case["client"].post(base(case) + "/letter-preview", json=payload).status_code == 412
    assert case["client"].post(base(case) + "/letter-publish", json=command(payload, shown)).status_code == 412
    assert billing.download_utility_statement_pdf(case["statement"].id).body == legacy
    assert archive.count_originals(store, "contract", case["contract"].id) == 0


def test_letter_reference_uses_frozen_labels_without_internal_ids_and_preserves_legacy_pdf(case):
    payload, shown = preview(case)
    legacy = billing.download_utility_statement_pdf(case["statement"].id).body
    pdf = case["client"].post(base(case) + "/letter-preview-pdf", json=payload)
    assert pdf.status_code == 200
    import pdfplumber
    with pdfplumber.open(BytesIO(pdf.content)) as document:
        cover = document.pages[0].extract_text() or ""
        text = "\n".join(page.extract_text() or "" for page in document.pages)
    assert "Bezug: Abrechnungszeitraum: 01.01.2025" in cover
    assert "Vertrag: " + case["contract"].contract_number in cover
    assert "Einheit: " + case["unit"].label in cover
    assert all(case[key].id not in text for key in ("statement", "period", "property", "unit", "contract", "tenant", "cost", "key"))
    assert shown["review"]["source"]["statement"]["id"] == case["statement"].id
    saved = case["client"].post(base(case) + "/letter-publish", json=command(payload, shown))
    assert saved.status_code == 201 and saved.json()["pdf_sha256"] == shown["pdf_sha256"]
    assert billing.download_utility_statement_pdf(case["statement"].id).body == legacy


def test_long_letter_keeps_reference_with_subject_and_has_no_reference_only_page(case):
    address = ("Prießnitzstraße 15, Aufgang Süd – z. Hd. Zoë Łukasz\n"
               "Abteilung Gebäudebetrieb und Betriebskosten\nHinterhaus, vierte Etage, rechte Tür\n01097 Dresden, Deutschland")
    intro = ("Guten Tag, anbei erhalten Sie die geprüfte Betriebskostenabrechnung. Straße, Gebäude und Müllabfuhr "
             "wurden vollständig berücksichtigt.\n\n" + "Bitte prüfen Sie alle Kostenpositionen und die Verteilung. " * 12)
    payload, _ = preview(case, sender_address=address, recipient_address=address, intro=intro,
                         subject="Betriebskostenabrechnung Brief QA 2025", signature="Zoë Łukasz Verwaltung")
    pdf = case["client"].post(base(case) + "/letter-preview-pdf", json=payload)
    assert pdf.status_code == 200
    import pdfplumber
    with pdfplumber.open(BytesIO(pdf.content)) as document:
        texts = [page.extract_text() or "" for page in document.pages]
    assert len(texts) == 2
    assert texts[0].index(payload["data"]["subject"]) < texts[0].index("Bezug:") < texts[0].index(payload["data"]["salutation"])
    assert "Mit freundlichen Grüßen" in texts[0] and "Zoë Łukasz Verwaltung" in texts[0]
    assert "Einzelabrechnung und Berechnungsgrundlagen" in texts[1]
    assert "Bezug:" not in texts[1]


def test_saved_original_and_idempotent_replay_survive_later_name_changes(case):
    payload, shown, saved = publish(case)
    before = case["client"].get(saved["file_url"]).content
    store.update_tenant(case["tenant"].id, TenantCreate(full_name="Später geändert"))
    replayed = case["client"].post(base(case) + "/letter-publish", json=command(payload, shown))
    assert replayed.status_code == 201 and replayed.json() == saved
    assert case["client"].get(saved["file_url"]).content == before


def test_current_roles_and_revoked_property_scope_win_even_for_retries(case):
    payload, shown = preview(case)
    manager = auth.register_user("billing-manager", "bm@example.test", "Verwalter", "Secret123", "verwalter")
    auth.update_user(manager.id, {"role": "techniker"})
    with pytest.raises(HTTPException) as failure:
        service.publish(store, case["statement"].id, LetterPublish.model_validate(command(payload, shown)), manager.id)
    assert failure.value.status_code == 403
    for role in ("buchhaltung", "techniker", "readonly"):
        account = auth.register_user("billing-" + role, role + "@example.test", role, "Secret123", role)
        with TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(account.id)}) as client:
            assert client.get(base(case) + "/letter-context").status_code == 200
            assert client.post(base(case) + "/letter-publish", json=command(payload, shown)).status_code == 403
    _, _, saved = publish(case)
    auth.update_user(case["owner"].id, {"role": "verwalter", "portfolio_access": "selected", "portfolio_ids": []})
    assert case["client"].get(saved["file_url"]).status_code in (403, 404)
    assert case["client"].post(base(case) + "/letter-publish", json=command(payload, shown)).status_code in (403, 404)


def test_archive_failure_rolls_back_document_and_original_then_same_command_retries(case, monkeypatch):
    payload, shown = preview(case)
    persist = archive.persist_version_bytes
    def fail_after_blocks(*args, **kwargs):
        persist(*args, **kwargs)
        raise RuntimeError("synthetic full disk")
    monkeypatch.setattr(archive, "persist_version_bytes", fail_after_blocks)
    with pytest.raises(RuntimeError, match="synthetic full disk"):
        service.publish(store, case["statement"].id, LetterPublish.model_validate(command(payload, shown)), case["owner"].id)
    assert archive.count_originals(store, "contract", case["contract"].id) == 0
    assert not [doc for doc in store.list_documents() if doc.document_type == DOC_TYPE]
    monkeypatch.setattr(archive, "persist_version_bytes", persist)
    assert case["client"].post(base(case) + "/letter-publish", json=command(payload, shown)).status_code == 201


def test_snapshot_import_validates_letter_metadata_and_unchanged_final_statement(case):
    _, _, saved = publish(case)
    exported = export_snapshot(store)
    records, problems = parse(exported["document_originals"])
    assert not problems and len(records) == 1
    if hasattr(store, "db"):
        assert verify_document_versions(store.db.connection()) == 1
    broken = deepcopy(exported["document_originals"])
    broken[0]["metadata_snapshot"][DOC_TYPE]["review"]["data"]["recipient_name"] = "Falscher Empfänger"
    parsed, problems = parse(broken)
    assert not problems  # decoding alone does not yet run the original verifier
    with pytest.raises(ValueError, match="Abrechnungsschreibens"):
        validate_feature_snapshot(parsed[0][0], parsed[0][0].metadata_snapshot)
    assert case["client"].get(saved["file_url"]).status_code == 200


def test_equal_amount_position_edit_requires_regeneration_before_finalize(case):
    billing.patch_cost_item(case["cost"].id, CostItemPatch(description="Gleiche Summe, geänderte Position"))
    preflight = billing.get_billing_period_preflight(case["period"].id)
    assert "STATEMENTS_OUTDATED" in {warning.code for warning in preflight.warnings}
    with pytest.raises(HTTPException) as failure:
        billing.finalize_billing_period(case["period"].id)
    assert failure.value.status_code == 400
    billing.generate_utility_statements(case["period"].id)
    assert billing.finalize_billing_period(case["period"].id).status == "finalized"


def test_unicode_long_text_and_many_positions_survive_multipage_pdf(case):
    for index in range(45):
        store.create_cost_item(CostItemCreate(billing_period_id=case["period"].id,
            description=f"Position {index:02d} - Zoë Łukasz Иван Μαρία & <Sonderzeichen> " + "LangerText" * 12,
            amount=1.23, allocation_key_id=case["key"].id))
    statement = billing.generate_utility_statements(case["period"].id)[0]
    case["statement"] = statement
    payload, shown = preview(case, intro="Ausführliche persönliche Erläuterung. " * 90)
    pdf = case["client"].post(base(case) + "/letter-preview-pdf", json=payload)
    assert pdf.status_code == 200
    import pdfplumber
    with pdfplumber.open(BytesIO(pdf.content)) as document:
        assert len(document.pages) >= 4
        assert all((page.extract_text() or "").count("Kostenposition") <= 1 for page in document.pages)
        assert all(label in document.pages[-1].extract_text() for label in ("Ihr Kostenanteil", "Vorauszahlungen", "Nachzahlung"))
        assert all(word["x0"] >= 40 and word["x1"] <= page.width - 40
                   and word["top"] >= 20 and word["bottom"] <= page.height - 20
                   for page in document.pages for word in page.extract_words())
        text = "\n".join(page.extract_text() or "" for page in document.pages)
    assert "Zoë Łukasz Иван Μαρία" in text and "Position 44" in text
    assert "<Sonderzeichen>" in text and "1.255,35" in text
    assert hashlib.sha256(pdf.content).hexdigest() == shown["pdf_sha256"]


def test_one_exceptionally_long_cost_row_can_continue_without_clipping(case):
    store.create_cost_item(CostItemCreate(billing_period_id=case["period"].id,
        description="Sehr ausführliche Erläuterung " * 300 + " EndeDerLangenPosition",
        amount=1.23, allocation_key_id=case["key"].id))
    case["statement"] = billing.generate_utility_statements(case["period"].id)[0]
    payload, _ = preview(case)
    pdf = case["client"].post(base(case) + "/letter-preview-pdf", json=payload)
    assert pdf.status_code == 200
    import pdfplumber
    with pdfplumber.open(BytesIO(pdf.content)) as document:
        text = "\n".join(page.extract_text() or "" for page in document.pages)
        assert len(document.pages) >= 3
        assert all((page.extract_text() or "").count("Kostenposition") <= 1 for page in document.pages)
    assert "EndeDerLangenPosition" in text and "1.201,23" in text


def test_letter_workspace_registry_is_bound_to_statement_and_never_changes_it(case):
    client = case["client"]
    payload, _ = preview(case)
    contexts = {row["context"]: row for row in client.get("/api/v1/workspace/contexts").json()["items"]}
    entry = contexts["billing-statement-letter"]
    assert entry["kind"] == "utility_statement" and entry["area"] == "/billing/statements"
    assert set(entry["field_keys"]) == set(payload["data"])
    path = "/api/v1/workspace/source/utility_statement/" + case["statement"].id
    source = client.get(path).json()
    assert any(dep["table"] == "billing_letter_settings" for dep in source["dependency_etags"])
    statement_before = store.get_utility_statement(case["statement"].id).model_dump(mode="json")
    identifier = str(uuid4())
    draft_path = "/api/v1/workspace/drafts/" + identifier
    draft = client.put(draft_path, json={"base_revision": 0, "idempotency_key": str(uuid4()),
        "context": "billing-statement-letter", "mode": "edit", "source": {
            "kind": "utility_statement", "id": case["statement"].id, "revision": source["revision"]},
        "anchor": {"kind": "utility_statement", "id": case["statement"].id},
        "field_keys": list(payload["data"]), "values": payload["data"]})
    assert draft.status_code == 200, draft.text
    assert draft.json()["source_state"]["status"] == "current"
    store.update_tenant(case["tenant"].id, TenantCreate(full_name="Geänderter Empfänger"))
    changed = client.get(draft_path)
    assert changed.status_code == 200 and changed.json()["source_state"]["status"] == "changed"
    assert store.get_utility_statement(case["statement"].id).model_dump(mode="json") == statement_before
    rejected = client.put("/api/v1/workspace/drafts/" + str(uuid4()), json={"base_revision": 0,
        "idempotency_key": str(uuid4()), "context": "billing-statement-letter", "values": {"balance": 0}})
    assert rejected.status_code == 422


def test_briefhead_settings_invalidate_preview_and_workspace_dependencies(case):
    client = case["client"]
    payload, shown = preview(case)
    path = "/api/v1/workspace/source/utility_statement/" + case["statement"].id
    before = client.get(path).json()
    changed = client.put("/api/v1/auth/users/me/settings", json={"base_revision": 0,
        "idempotency_key": str(uuid4()), "scope": "object:" + case["property"].id,
        "values": {"document_sender": "Neue Hausverwaltung"}})
    assert changed.status_code == 200, changed.text
    after = client.get(path).json()
    assert after["dependency_etags"] != before["dependency_etags"]
    assert client.post(base(case) + "/letter-preview", json=payload).status_code == 412
    assert client.post(base(case) + "/letter-publish", json=command(payload, shown)).status_code == 412
    context = client.get(base(case) + "/letter-context").json()
    assert context["defaults"]["sender_name"] == "Neue Hausverwaltung"


@pytest.mark.parametrize("field", ["sender_name", "sender_address", "recipient_name", "recipient_address", "subject", "salutation"])
def test_empty_required_letter_values_are_explicit_validation_errors(case, field):
    payload, _ = preview(case)
    payload["data"][field] = "  "
    response = case["client"].post(base(case) + "/letter-preview", json=payload)
    assert response.status_code == 422
    assert any(item["loc"][-1] == field for item in response.json()["detail"])


def test_letters_carry_the_letterhead_and_older_originals_stay_valid(case):
    from backend.services.billing_letter_types import LetterPublish
    from backend.services.billing_letter_validation import FORMAT_VERSION, digest, request_hash

    payload, shown, saved = publish(case)
    assert shown["review"]["format_version"] == "billing-statement-letter-pdf/2"
    assert shown["review"]["source"]["letterhead"]["sender_name"] == "Linda Reiser"
    with archive.work(store, case["owner"].id) as unit:
        row = archive.head(unit, saved["document_id"])
        assert row is not None
        snapshot = dict(row.metadata_snapshot)
        values = {name: getattr(row, name) for name in ("actor_id", "request_sha256", "document_id", "sha256",
                                                        "idempotency_key", "portfolio_id", "property_id", "unit_id",
                                                        "contract_id", "tenant_id")}
    proof = snapshot[DOC_TYPE]

    def variant(format_version, source):
        review = {**proof["review"], "format_version": format_version, "source": source,
                  "source_revision": digest(source)}
        command = LetterPublish(data=review["data"], source_revision=review["source_revision"],
                                review_hash=digest(review), idempotency_key=proof["idempotency_key"])
        request = request_hash(case["statement"].id, command)
        return ({**values, "request_sha256": request},
                {**snapshot, DOC_TYPE: {**proof, "review": review, "review_hash": digest(review), "request_sha256": request}})

    older = {key: value for key, value in proof["review"]["source"].items() if key != "letterhead"}
    from backend.services.billing_letter_validation import validate_billing_letter_snapshot
    assert validate_billing_letter_snapshot(*variant(FORMAT_VERSION, older))   # archived before the letterhead
    with pytest.raises(ValueError):
        validate_billing_letter_snapshot(*variant("billing-statement-letter-pdf/2", older))
