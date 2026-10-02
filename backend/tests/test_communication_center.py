from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.communication_models import (
    CommunicationBlockCreate,
    CommunicationBlockUpdate,
    CommunicationDraftCreate,
    CommunicationDraftUpdate,
    CommunicationTemplateCreate,
    CommunicationTemplateUpdate,
    RenderRequest,
)
from backend.db.communication_center_models import CommunicationDraftORM  # noqa: F401
from backend.db.orm_models import Base
from backend.models import ContractCreate, PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import communication_center as service
from backend.services.integrations.history_policy import request_observation, response_observation
from backend.services.integrations.providers import DeutschePostProvider, WhatsAppIntegrationProvider
from backend.services.portfolio_scope import AccessScope, scope_context
from backend.services.tenant_privacy import export_tenant_metadata


@pytest.fixture
def communication_store(tmp_path, monkeypatch):
    def integration(integration_id):
        configs = {
            "email": {
                "sender_name": "Vermieter GmbH",
                "sender_email": "verwaltung@example.test",
            },
            "deutsche-post": {
                "sender_name": "Vermieter GmbH",
                "sender_street": "Vermieterweg 1",
                "sender_zip_code": "60311",
                "sender_city": "Frankfurt am Main",
            },
        }
        return {"config": configs.get(integration_id, {})}

    monkeypatch.setattr(service.integration_manager, "get_integration", integration)
    engine = create_engine(f"sqlite:///{tmp_path / 'communication.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield SQLAlchemyStore(db)
    engine.dispose()


def seed_recipient(store):
    portfolio = store.create_portfolio(PortfolioCreate(name="Privatbestand", owner_name="Vermieter GmbH"))
    prop = store.create_property(PropertyCreate(
        portfolio_id=portfolio.id, name="Haus Mitte", property_type="residential",
        address_line="Vermieterweg 1", postal_code="60311", city="Frankfurt am Main", country="DE",
    ))
    unit = store.create_unit(UnitCreate(
        property_id=prop.id, label="WE 3", unit_type="apartment",
        area_sqm=72.5, cold_rent=900, service_charge_advance=200,
    ))
    tenant = store.create_tenant(TenantCreate(
        full_name="Mara Muster", email="mara@example.test", phone="+491701234567",
        address_line="Mieterstraße 7", postal_code="60313", city="Frankfurt am Main", country="DE",
    ))
    contract = store.create_contract(ContractCreate(
        contract_number="MV-2026-7", property_id=prop.id, unit_id=unit.id,
        tenant_id=tenant.id, start_date=date(2026, 1, 1),
    ))
    return portfolio, tenant, contract


def test_template_blocks_and_authoritative_preview(communication_store):
    portfolio, tenant, contract = seed_recipient(communication_store)
    service.create_block(communication_store, CommunicationBlockCreate(
        key="closing.standard", name="Grußformel", content_template="Mit freundlichen Grüßen\n{{portfolio.owner_name}}",
    ))
    template = service.create_template(communication_store, CommunicationTemplateCreate(
        name="Allgemeines Mieterschreiben", audience="tenant", channel="universal",
        subject_template="Vertrag {{contract.number}}",
        body_template="Guten Tag {{recipient.name}},\n\nObjekt: {{property.name}} / {{unit.label}}\n\n{{block:closing.standard}}",
    ))
    preview = service.preview(communication_store, portfolio.id, RenderRequest(
        recipient_type="tenant", recipient_id=tenant.id, contract_id=contract.id,
        template_id=template["id"],
    ))
    assert preview.subject == "Vertrag MV-2026-7"
    assert "Mara Muster" in preview.body
    assert "Haus Mitte / WE 3" in preview.body
    assert "Vermieter GmbH" in preview.body
    assert preview.recipient["street"] == "Mieterstraße 7"
    assert preview.context["sender"] == {
        "name": "Vermieter GmbH",
        "email": None,
        "street": None,
        "postal_code": None,
        "city": None,
    }
    assert preview.missing_fields == []
    assert len(preview.context_sha256) == 64


def test_review_freezes_snapshot_and_pdf_and_prevents_edit(communication_store):
    portfolio, tenant, contract = seed_recipient(communication_store)
    draft = service.create_draft(communication_store, CommunicationDraftCreate(
        portfolio_id=portfolio.id, title="Mietanpassung", channel="post",
        recipient_type="tenant", recipient_id=tenant.id, contract_id=contract.id,
        subject_template="Ihr Mietvertrag {{contract.number}}",
        body_template="Sehr geehrte Damen und Herren,\n\nwir schreiben an {{recipient.name}}.",
    ), "actor-1")
    reviewed = service.review_draft(communication_store, draft.id, draft.revision, "actor-2")
    assert reviewed.status == "reviewed"
    assert reviewed.reviewed_by == "actor-2"
    assert reviewed.pdf_sha256 and reviewed.snapshot_sha256
    pdf, filename = service.pdf_bytes(communication_store, draft.id)
    assert pdf.startswith(b"%PDF-")
    assert filename.endswith(".pdf")
    with pytest.raises(HTTPException) as exc:
        service.update_draft(communication_store, draft.id, CommunicationDraftUpdate(
            expected_revision=reviewed.revision, title="Manipuliert",
        ))
    assert exc.value.status_code == 409


def test_review_refuses_missing_required_merge_data(communication_store):
    portfolio, tenant, contract = seed_recipient(communication_store)
    draft = service.create_draft(communication_store, CommunicationDraftCreate(
        portfolio_id=portfolio.id, title="Fehlender Wert", channel="email",
        recipient_type="tenant", recipient_id=tenant.id, contract_id=contract.id,
        body_template="Unbekannt: {{contract.end_date}}",
    ), "actor")
    with pytest.raises(HTTPException) as exc:
        service.review_draft(communication_store, draft.id, draft.revision, "actor")
    assert exc.value.status_code == 409
    assert "contract.end_date" in exc.value.detail["missing_fields"]


def test_review_requires_explicit_contract_when_multiple_active(communication_store):
    portfolio, tenant, contract = seed_recipient(communication_store)
    second_unit = communication_store.create_unit(UnitCreate(
        property_id=contract.property_id, label="WE 4", unit_type="apartment",
    ))
    communication_store.create_contract(ContractCreate(
        contract_number="MV-2", property_id=contract.property_id, unit_id=second_unit.id,
        tenant_id=tenant.id, start_date=date(2026, 2, 1),
    ))
    with pytest.raises(HTTPException) as exc:
        service.preview(communication_store, portfolio.id, RenderRequest(
            recipient_type="tenant", recipient_id=tenant.id,
            body_template="Hallo {{recipient.name}}",
        ))
    assert exc.value.status_code == 409


def test_starter_library_is_idempotent_and_does_not_overwrite_user_content(communication_store):
    first = service.install_starter_library(communication_store)
    assert first["templates_added"] == 5
    assert first["blocks_added"] == 3
    template = next(row for row in service.list_templates(communication_store)
                    if row["name"] == "Allgemeines Mieterschreiben")
    original_revision = template["revision"]
    second = service.install_starter_library(communication_store)
    assert second["templates_added"] == 0
    assert second["blocks_added"] == 0
    unchanged = next(row for row in service.list_templates(communication_store)
                     if row["name"] == "Allgemeines Mieterschreiben")
    assert unchanged["revision"] == original_revision


def test_library_updates_reject_stale_revisions(communication_store):
    template = service.create_template(communication_store, CommunicationTemplateCreate(
        name="Parallel", body_template="Version 1",
    ))
    updated = service.update_template(communication_store, template["id"], CommunicationTemplateUpdate(
        expected_revision=1, name="Parallel", body_template="Version 2",
    ))
    assert updated["revision"] == 2
    with pytest.raises(HTTPException) as template_error:
        service.update_template(communication_store, template["id"], CommunicationTemplateUpdate(
            expected_revision=1, name="Parallel", body_template="Stale",
        ))
    assert template_error.value.status_code == 412

    block = service.create_block(communication_store, CommunicationBlockCreate(
        key="parallel.block", name="Parallel", content_template="Version 1",
    ))
    updated_block = service.update_block(communication_store, block["id"], CommunicationBlockUpdate(
        expected_revision=1, key="parallel.block", name="Parallel", content_template="Version 2",
    ))
    assert updated_block["revision"] == 2
    with pytest.raises(HTTPException) as block_error:
        service.update_block(communication_store, block["id"], CommunicationBlockUpdate(
            expected_revision=1, key="parallel.block", name="Parallel", content_template="Stale",
        ))
    assert block_error.value.status_code == 412


def test_draft_keeps_template_revision_used_at_creation(communication_store):
    portfolio, tenant, contract = seed_recipient(communication_store)
    template = service.create_template(communication_store, CommunicationTemplateCreate(
        name="Revisionsvorlage", audience="tenant", channel="email",
        subject_template="Revision 1", body_template="Hallo {{recipient.name}}",
    ))
    draft = service.create_draft(communication_store, CommunicationDraftCreate(
        portfolio_id=portfolio.id, title="Revisionstest", channel="email",
        recipient_type="tenant", recipient_id=tenant.id, contract_id=contract.id,
        template_id=template["id"],
    ), "actor")
    assert draft.template_revision == 1
    service.update_template(communication_store, template["id"], CommunicationTemplateUpdate(
        expected_revision=1, name="Revisionsvorlage", audience="tenant", channel="email",
        subject_template="Revision 2", body_template="Geändert {{recipient.name}}",
    ))
    reviewed = service.review_draft(communication_store, draft.id, draft.revision, "actor")
    assert reviewed.template_revision == 1
    assert reviewed.rendered_subject == "Revision 1"


def test_post_review_snapshots_configured_sender_not_property_address(communication_store):
    portfolio, tenant, contract = seed_recipient(communication_store)
    draft = service.create_draft(communication_store, CommunicationDraftCreate(
        portfolio_id=portfolio.id, title="Brief", channel="post",
        recipient_type="tenant", recipient_id=tenant.id, contract_id=contract.id,
        body_template="Hallo {{recipient.name}}",
    ), "actor")
    reviewed = service.review_draft(communication_store, draft.id, draft.revision, "actor")
    row = service.get_draft(communication_store, reviewed.id)
    context = __import__("json").loads(row.context_json)
    assert context["sender"]["street"] == "Vermieterweg 1"
    assert context["sender"]["postal_code"] == "60311"
    assert context["sender"] != context["property"]

    graph = export_tenant_metadata(communication_store, tenant.id)
    assert len(graph["communication_drafts"]) == 1
    evidence = graph["communication_drafts"][0]
    assert evidence["rendered_body"] == "Hallo Mara Muster"
    assert evidence["snapshot_sha256"] == row.snapshot_sha256
    assert graph["communication_pdf_files"][0]["sha256"] == row.pdf_sha256


def test_reviewed_correspondence_blocks_ordinary_store_reset(communication_store):
    portfolio, tenant, contract = seed_recipient(communication_store)
    draft = service.create_draft(communication_store, CommunicationDraftCreate(
        portfolio_id=portfolio.id, title="Retention", channel="post",
        recipient_type="tenant", recipient_id=tenant.id, contract_id=contract.id,
        body_template="Hallo {{recipient.name}}",
    ), "actor")
    service.review_draft(communication_store, draft.id, draft.revision, "actor")

    with pytest.raises(HTTPException) as exc:
        communication_store.clear_all()
    assert exc.value.status_code == 409
    assert "communication_history_exists" in str(exc.value.detail)


def test_whatsapp_provider_uses_official_messages_contract(monkeypatch):
    captured = {}
    class Response:
        status_code = 200
        def json(self):
            return {"messages": [{"id": "wamid.test"}]}
    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()
    monkeypatch.setattr("backend.services.integrations.providers.httpx.post", fake_post)
    provider = WhatsAppIntegrationProvider()
    result = provider.run({
        "action": "template", "to": "+49 170 1234567",
        "template_name": "rent_notice", "language_code": "de",
    }, {"phone_number_id": "123", "api_token": "secret", "graph_version": "v99.0"})
    assert result.success
    assert captured["url"].endswith("/v99.0/123/messages")
    assert captured["json"]["messaging_product"] == "whatsapp"
    assert captured["json"]["template"]["name"] == "rent_notice"
    assert result.details["external_reference"] == "wamid.test"


def test_whatsapp_direct_text_requires_separate_opt_in():
    result = WhatsAppIntegrationProvider().run({
        "action": "text", "to": "491701234567", "text": "Hallo",
    }, {"phone_number_id": "123", "api_token": "secret", "graph_version": "v99.0"})
    assert not result.success
    assert "nicht freigegeben" in result.message


def test_integration_history_does_not_retain_message_content_or_recipient():
    provider = WhatsAppIntegrationProvider()
    request, _schema, known = request_observation("whatsapp", {
        "action": "template", "to": "491701234567", "template_name": "private_notice",
        "text": "private content",
    }, {"phone_number_id": "123", "api_token": "secret"}, provider.manifest)
    response, _response_schema = response_observation({
        "success": True, "message": "accepted",
        "details": {"external_reference": "wamid.test", "response": {"private": "payload"}},
    }, known, integration_id="whatsapp")
    assert request["payload"] == {"action": "template"}
    assert response["details"] == {"external_reference": "wamid.test"}
    combined = {"request": request, "response": response}
    assert "491701234567" not in repr(combined)
    assert "private content" not in repr(combined)
    assert "private_notice" not in repr(combined)
    assert "'private'" not in repr(combined)


def test_epost_provider_defaults_to_test_flag(monkeypatch):
    calls = []
    class Response:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data
            self.is_success = status_code < 400
        def json(self):
            return self._data
    class Client:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def post(self, path, **kwargs):
            calls.append(("post", path, kwargs))
            if path == "/api/Login":
                return Response(200, {"token": "jwt"})
            return Response(200, [{"letterID": 7788}])
        def get(self, path, **kwargs):
            calls.append(("get", path, kwargs))
            return Response(200, {"status": 3})
    monkeypatch.setattr("backend.services.integrations.providers.httpx.Client", Client)
    provider = DeutschePostProvider()
    result = provider.run({
        "action": "send", "filename": "brief.pdf",
        "pdf_base64": __import__("base64").b64encode(b"%PDF-1.4 synthetic").decode(),
        "recipient": {"name": "Mara Muster", "street": "Mieterstraße 7",
                      "postal_code": "60313", "city": "Frankfurt am Main", "country": "DE"},
        "sender": {"name": "Vermieter GmbH"}, "test_mode": True,
    }, {"vendor_id": "v", "ekp": "1234567890", "secret": "s", "password": "pw"})
    assert result.success
    assert result.details["external_reference"] == "7788"
    letter_call = next(call for call in calls if call[0:2] == ("post", "/api/Letter"))
    letter = letter_call[2]["json"][0]
    assert letter["testFlag"] is True
    assert letter["testShowRestrictedArea"] is True
    assert letter["activateDuplicateFailsafe"] is True
    assert letter["country"] == ""


def test_epost_rejects_unapproved_base_url():
    result = DeutschePostProvider().run(
        {"action": "health"},
        {"base_url": "https://example.invalid", "vendor_id": "v", "ekp": "1234567890",
         "secret": "s", "password": "pw"},
    )
    assert not result.success
    assert "offizielle API-Adresse" in result.message


def test_epost_resolves_foreign_country_from_official_list(monkeypatch):
    submitted = {}
    class Response:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data
            self.is_success = status_code < 400
        def json(self):
            return self._data
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, path, **kwargs):
            if path == "/countries.json":
                return Response(200, [{"CountryCode": "AT", "Country": "ÖSTERREICH"}])
            return Response(200, {"status": 3})
        def post(self, path, **kwargs):
            if path == "/api/Login":
                return Response(200, {"token": "jwt"})
            submitted.update(kwargs["json"][0])
            return Response(200, [{"letterID": 9911}])
    monkeypatch.setattr("backend.services.integrations.providers.httpx.Client", Client)
    result = DeutschePostProvider().run({
        "action": "send", "filename": "brief.pdf",
        "pdf_base64": __import__("base64").b64encode(b"%PDF-1.4 synthetic").decode(),
        "recipient": {"name": "Mara Muster", "street": "Hauptplatz 1",
                      "postal_code": "1010", "city": "Wien", "country": "AT"},
        "test_mode": True,
    }, {"vendor_id": "v", "ekp": "1234567890", "secret": "s", "password": "pw"})
    assert result.success
    assert submitted["country"] == "ÖSTERREICH"


def test_epost_production_requires_pdfa_validation():
    provider = DeutschePostProvider()
    result = provider.run({
        "action": "send", "test_mode": False, "pdfa_validated": False,
        "pdf_base64": __import__("base64").b64encode(b"%PDF-1.4 synthetic").decode(),
    }, {
        "vendor_id": "v", "ekp": "1234567890", "secret": "s", "password": "pw",
        "production_enabled": True,
    })
    # Login is attempted only after explicit configuration; transport isn't
    # available here, but the adapter must never claim production success.
    assert not result.success


def test_renderer_respects_selected_portfolio_scope(communication_store):
    allowed, tenant, contract = seed_recipient(communication_store)
    hidden = communication_store.create_portfolio(PortfolioCreate(name="Hidden"))
    prop = communication_store.create_property(PropertyCreate(
        portfolio_id=hidden.id, name="Hidden house", property_type="residential",
    ))
    unit = communication_store.create_unit(UnitCreate(
        property_id=prop.id, label="H1", unit_type="apartment",
    ))
    hidden_tenant = communication_store.create_tenant(TenantCreate(full_name="Hidden tenant"))
    hidden_contract = communication_store.create_contract(ContractCreate(
        contract_number="HIDDEN-1", property_id=prop.id, unit_id=unit.id,
        tenant_id=hidden_tenant.id, start_date=date(2026, 1, 1),
    ))
    scope = AccessScope("actor", "verwalter", False, (allowed.id,))
    with scope_context(scope):
        visible = service.preview(communication_store, allowed.id, RenderRequest(
            recipient_type="tenant", recipient_id=tenant.id, contract_id=contract.id,
            body_template="Hallo {{recipient.name}}",
        ))
        assert visible.body == "Hallo Mara Muster"
        with pytest.raises(HTTPException) as exc:
            service.preview(communication_store, allowed.id, RenderRequest(
                recipient_type="tenant", recipient_id=hidden_tenant.id,
                contract_id=hidden_contract.id, body_template="Hallo {{recipient.name}}",
            ))
        assert exc.value.status_code == 404


def test_review_rejects_tenant_without_portfolio_contract(communication_store):
    portfolio = communication_store.create_portfolio(PortfolioCreate(
        name="Privatbestand", owner_name="Vermieter GmbH",
    ))
    tenant = communication_store.create_tenant(TenantCreate(
        full_name="Unzugeordnet", email="free@example.test",
    ))
    draft = service.create_draft(communication_store, CommunicationDraftCreate(
        portfolio_id=portfolio.id, title="Unzugeordnet", channel="email",
        recipient_type="tenant", recipient_id=tenant.id,
        body_template="Hallo {{recipient.name}}",
    ), "actor")
    with pytest.raises(HTTPException) as exc:
        service.review_draft(communication_store, draft.id, draft.revision, "actor")
    assert exc.value.status_code == 409
    assert "Vertrag" in str(exc.value.detail)


def test_template_audience_and_channel_are_enforced(communication_store):
    portfolio, tenant, contract = seed_recipient(communication_store)
    company = service.create_template(communication_store, CommunicationTemplateCreate(
        name="Firma", audience="company", channel="universal", body_template="Hallo",
    ))
    email = service.create_template(communication_store, CommunicationTemplateCreate(
        name="E-Mail", audience="tenant", channel="email", body_template="Hallo",
    ))
    for template_id, channel in ((company["id"], "email"), (email["id"], "post")):
        with pytest.raises(HTTPException) as exc:
            service.preview(communication_store, portfolio.id, RenderRequest(
                recipient_type="tenant", recipient_id=tenant.id, contract_id=contract.id,
                channel=channel, template_id=template_id,
            ))
        assert exc.value.status_code == 422


def test_global_template_library_remains_visible_inside_selected_portfolio_scope(communication_store):
    portfolio, _, _ = seed_recipient(communication_store)
    template = service.create_template(communication_store, CommunicationTemplateCreate(
        name="Scope-visible library template", audience="any", channel="universal",
        body_template="Global library content",
    ))
    scope = AccessScope("actor", "verwalter", False, (portfolio.id,))
    with scope_context(scope):
        assert template["id"] in {row["id"] for row in service.list_templates(communication_store)}


def test_draft_save_rejects_unknown_recipient_and_mismatched_contract(communication_store):
    portfolio, tenant, contract = seed_recipient(communication_store)
    with pytest.raises(HTTPException) as exc:
        service.create_draft(communication_store, CommunicationDraftCreate(
            portfolio_id=portfolio.id, title="Missing", channel="email",
            recipient_type="tenant", recipient_id="does-not-exist", body_template="Hallo",
        ), "actor")
    assert exc.value.status_code == 404
    other = communication_store.create_tenant(TenantCreate(full_name="Andere Mietpartei"))
    with pytest.raises(HTTPException) as exc:
        service.create_draft(communication_store, CommunicationDraftCreate(
            portfolio_id=portfolio.id, title="Mismatch", channel="email",
            recipient_type="tenant", recipient_id=other.id, contract_id=contract.id,
            body_template="Hallo {{recipient.name}}",
        ), "actor")
    assert exc.value.status_code == 409


def test_whatsapp_review_requires_approved_meta_template(communication_store):
    portfolio, tenant, contract = seed_recipient(communication_store)
    draft = service.create_draft(communication_store, CommunicationDraftCreate(
        portfolio_id=portfolio.id, title="WhatsApp", channel="whatsapp",
        recipient_type="tenant", recipient_id=tenant.id, contract_id=contract.id,
        body_template="Hallo {{recipient.name}}",
    ), "actor")
    with pytest.raises(HTTPException) as exc:
        service.review_draft(communication_store, draft.id, draft.revision, "actor")
    assert exc.value.status_code == 409
    assert "Meta-Template" in str(exc.value.detail)
