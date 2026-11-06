"""Selected form context and untrusted model values must not cross app boundaries."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.dependencies import store
from backend.models import ContractCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.services import ai_reading, ai_surfaces, meter_documents_ai
from backend.tests.test_ai_reading import _answer, _pdf, _start, _upload
from backend.tests.test_ai_reading import case as case


@pytest.mark.parametrize("mismatch", ["unit_property", "contract_property", "contract_unit", "contract_tenant", "period_unit"])
def test_reading_rejects_inconsistent_selected_context_before_provider(case, monkeypatch, mismatch):
    first = case["property"]
    second = store.create_property(PropertyCreate(portfolio_id=first.portfolio_id, name="Zweite Immobilie",
                                                  property_type="residential"))
    other_unit = store.create_unit(UnitCreate(property_id=second.id, label="OG", unit_type="apartment", area_sqm=55))
    tenant = store.create_tenant(TenantCreate(full_name="Test Mietpartei"))
    other_tenant = store.create_tenant(TenantCreate(full_name="Andere Mietpartei"))
    contract = store.create_contract(ContractCreate(contract_number="KI-2026", property_id=second.id,
        unit_id=other_unit.id, tenant_id=tenant.id, start_date=date(2026, 1, 1)))
    params = {"property_id": first.id}
    if mismatch == "unit_property":
        params["unit_id"] = other_unit.id
    elif mismatch == "contract_property":
        params["contract_id"] = contract.id
    elif mismatch == "contract_unit":
        same_property_other_unit = store.create_unit(UnitCreate(property_id=second.id, label="DG",
            unit_type="apartment", area_sqm=40))
        params.update(property_id=second.id, contract_id=contract.id, unit_id=same_property_other_unit.id)
    elif mismatch == "contract_tenant":
        params.update(property_id=second.id, contract_id=contract.id, tenant_id=other_tenant.id)
    else:
        params.update(billing_period_id=case["period"].id, unit_id=other_unit.id)
    _answer(monkeypatch, case, "Keine Antwort erforderlich.")
    result = _start(case, reader="claude", file_url=_upload(_pdf("Testdokument")), params=params)
    assert result.status_code == 422, result.text
    assert case["seen"] == []


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity", "1e9999", "10000000000", True,
                                  float("nan"), float("inf"), {"value": "12"}])
def test_meter_model_nonfinite_or_oversized_values_cannot_crash_or_enter_proposals(value):
    result = meter_documents_ai.parse_data({"total": value, "consumption_share_percent": value,
        "costs": [{"label": "Wasser", "amount": value}],
        "readings": [{"serial": "KWZ-1", "value": value, "previous": value}],
        "unit_results": [{"unit_label": "EG", "amount": value}]})
    assert result.total is None and result.consumption_share is None
    assert not result.costs and not result.readings and not result.unit_results


@pytest.mark.parametrize("value", [True, 17, 1.5, {"amount": "12.34"}])
def test_meter_model_collection_shapes_are_checked(value):
    result = meter_documents_ai.parse_data({"costs": value, "readings": value, "unit_results": value})
    assert not result.costs and not result.readings and not result.unit_results


def test_meter_model_keeps_decimal_precision_and_does_not_truncate_consumption_share():
    result = meter_documents_ai.parse_data({"total": "12.34", "consumption_share_percent": "70.9",
        "costs": [{"label": "Wasser", "amount": "12.34"}],
        "readings": [{"serial": "KWZ-1", "device_type": "KWZ", "value": "31.420", "previous": "12.105"}],
        "unit_results": [{"unit_label": "EG", "amount": "-2.34"}]})
    assert result.total == Decimal("12.34") and result.costs[0]["amount"] == Decimal("12.34")
    assert result.readings[0]["value"] == Decimal("31.420")
    assert result.readings[0]["previous"] == Decimal("12.105")
    assert result.unit_results[0]["amount"] == Decimal("-2.34")
    assert result.consumption_share is None and any("Prozentzahl" in note for note in result.notes)


def test_reading_followup_sends_reference_labels_without_internal_record_ids():
    source = ai_reading.Source(b"text", "document.txt", "text/plain", "a" * 64, "Vollständiger Beleg. " * 30, "plain")
    request, count = ai_reading._request(ai_surfaces.DOCUMENT, source,
        {"units": [{"id": "private-unit-id", "label": "EG"}]}, {"ai_context": "standard"},
        model=None, conversation=[], current={"unit": {"id": "private-unit-id", "label": "EG"}, "title": "Mietvertrag"})
    assert count == 0
    assert request["context"]["known"] == {"units": ["EG"]}
    assert request["context"]["current_values"] == {"unit": "EG", "title": "Mietvertrag"}
    assert "private-unit-id" not in str(request)


def test_image_page_omissions_reach_both_reading_and_meter_provider_requests(monkeypatch):
    from backend.services import ai_document_images
    omitted = "Für die KI wurden Seitenbilder von 1 der 3 Seiten übertragen."
    image = {"name": "scan.png", "mime": "image/png", "data_base64": "aW1hZ2U="}
    monkeypatch.setattr(ai_document_images, "render_page_images", lambda *args: {
        "images": [image], "pages_total": 3, "pages_sent": 1, "omissions": [omitted]})
    source = ai_reading.Source(b"scan", "scan.pdf", "application/pdf", "b" * 64, "", "none")
    request, count = ai_reading._request(ai_surfaces.INVOICE, source, {}, {}, model=None, conversation=[], current={})
    assert count == 1 and request["omissions"] == [omitted]
    assert request["attachments"][0]["image_coverage"] == {"pages_total": 3, "pages_sent": 1}
    assert request["_image_summary"]["image_omissions"] == [omitted]
    meter = meter_documents_ai.request(SimpleNamespace(content=b"scan", filename="scan.pdf", media_type="application/pdf"),
        "", SimpleNamespace(units=[], meters=[]), model=None, today=date(2026, 11, 6))
    assert meter["_task"] == "meter_document_extraction" and meter["omissions"] == [omitted]
    assert meter["attachments"][0]["omissions"] == [omitted]


def test_truncated_meter_text_is_not_presented_to_provider_as_complete():
    text = "Abrechnung " * 12000
    request = meter_documents_ai.request(SimpleNamespace(content=b"text", filename="text.txt", media_type="text/plain"),
        text, SimpleNamespace(units=[], meters=[]), model=None, today=date(2026, 11, 6))
    assert request["attachments"][0]["text_truncated"]
    assert len(request["attachments"][0]["text"]) == meter_documents_ai.MAX_TEXT
    assert request["omissions"] and "begrenzt" in request["omissions"][0]


@pytest.mark.parametrize("value", [{}, [], ["heating"]])
def test_meter_model_wrong_enum_shapes_are_ignored_without_server_error(value):
    result = meter_documents_ai.parse_data({"document_kind": value,
        "costs": [{"label": "Wartung", "amount": "12.34", "category": value}]})
    assert result.kind == "other" and result.costs[0]["category"] == "other"


@pytest.mark.parametrize("with_text", [True, False])
def test_only_a_known_missing_pdf_renderer_can_fall_back_to_complete_text(monkeypatch, with_text):
    from backend.services import ai_document_images
    def missing(*args):
        raise ai_document_images.ImageRendererUnavailable()
    monkeypatch.setattr(ai_document_images, "render_page_images", missing)
    text = "Kurzer vollständiger Dokumenttext." if with_text else ""
    source = ai_reading.Source(b"pdf", "short.pdf", "application/pdf", "c" * 64, text, "pdf_text")
    if not with_text:
        with pytest.raises(ai_document_images.ImageRendererUnavailable):
            ai_reading._images(source, 4)
        with pytest.raises(ai_document_images.ImageRendererUnavailable):
            meter_documents_ai._image_attachments(b"pdf", "application/pdf", "short.pdf", text=text)
    else:
        for result in (ai_reading._images(source, 4),
                       meter_documents_ai._image_attachments(b"pdf", "application/pdf", "short.pdf", text=text)):
            assert not result["images"] and any("ausschließlich" in note for note in result["omissions"])


def test_pdf_renderer_resource_failures_never_degrade_to_partial_ai_requests(monkeypatch):
    from fastapi import HTTPException

    from backend.services import ai_document_images
    def failed(*args):
        raise HTTPException(503, "Isoliertes Ressourcenlimit")
    monkeypatch.setattr(ai_document_images, "render_page_images", failed)
    source = ai_reading.Source(b"pdf", "short.pdf", "application/pdf", "d" * 64, "Vollständiger Text", "pdf_text")
    with pytest.raises(HTTPException, match="Ressourcenlimit"):
        ai_reading._images(source, 4)
    with pytest.raises(HTTPException, match="Ressourcenlimit"):
        meter_documents_ai._image_attachments(b"pdf", "application/pdf", "short.pdf", text=source.text)
