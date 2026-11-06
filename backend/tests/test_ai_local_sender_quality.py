"""Local sender suggestions require a name in its actual source line."""
import pytest

from backend.services import ai_surfaces, assistant_providers
from backend.tests.test_ai_reading import _pdf, _start, _upload
from backend.tests.test_ai_reading import case as case

SAMPLE = """Rechnung TEST-AI-2026-1106
Hausservice Beispiel
Datum: 06.11.2026
Wartung Heizungsanlage Rosenhoefe Stuttgart
Nettobetrag:100,00 EUR
Umsatzsteuer19%:19,00 EUR
Gesamtbetrag119,00 EUR"""

SURFACES = (ai_surfaces.DOCUMENT, ai_surfaces.INVOICE, ai_surfaces.COST_ITEM)


@pytest.mark.parametrize("surface", SURFACES, ids=lambda surface: surface.id)
def test_local_sender_finds_company_after_document_heading_with_exact_evidence(surface):
    name = "sender" if surface.id == "document" else "supplier"
    values = ai_surfaces.local_values(surface, SAMPLE)
    assert values[name]["value"] == "Hausservice Beispiel"
    assert values[name]["evidence"] == "Hausservice Beispiel"


@pytest.mark.parametrize("surface", SURFACES, ids=lambda surface: surface.id)
@pytest.mark.parametrize("content", [
    "Rechnung TEST-AI-2026-1106\nUnbekannter Name\nGesamtbetrag119,00 EUR",
    "Rechnung Wasserwerke GmbH\nDatum: 06.11.2026\nGesamtbetrag 119,00 EUR",
    "Rechnungsempfänger: Hausverwaltung Andere GmbH\nGesamtbetrag 119,00 EUR",
    "Kunde: Hausservice Empfänger\nWartung der Heizung\nGesamtbetrag 119,00 EUR",
    "Rechnung\nAn:\nHausservice Empfänger GmbH\nMusterstraße 3\n70173 Stuttgart",
    "Wartung durch Hausservice Beispiel\nNettobetrag100,00 EUR",
    "Hausserviceweg 3\n70173 Stuttgart\nUmsatzsteuer19%:19,00 EUR",
])
def test_local_sender_does_not_invent_sender_from_headings_recipient_address_or_amount(surface, content):
    name = "sender" if surface.id == "document" else "supplier"
    assert name not in ai_surfaces.local_values(surface, content)


@pytest.mark.parametrize("surface", SURFACES, ids=lambda surface: surface.id)
@pytest.mark.parametrize("label", ["Absender", "Lieferant", "Rechnungssteller"])
def test_explicit_sender_label_wins_and_preserves_exact_source_line(surface, label):
    line = f"{label}: Max Mustermann"
    text = "Empfänger: Andere Hausverwaltung GmbH\n" + line + "\nRechnung Nr. R-88"
    name = "sender" if surface.id == "document" else "supplier"
    result = ai_surfaces.local_values(surface, text)[name]
    assert result["value"] == "Max Mustermann"
    assert result["evidence"] == line


@pytest.mark.parametrize("company", ["Objektservice Huber", "Gebäudeservice Meier", "Stadtwerke Pforzheim GmbH"])
def test_company_service_compounds_are_not_specific_to_a_demo_fixture(company):
    result = ai_surfaces.local_values(ai_surfaces.DOCUMENT, "Rechnung Nr. X-1\n" + company)
    assert result["sender"]["value"] == result["sender"]["evidence"] == company


@pytest.mark.parametrize("surface", SURFACES, ids=lambda surface: surface.id)
def test_local_reading_sender_has_a_verified_quote_without_external_provider(case, monkeypatch, surface):
    def external_call(*args, **kwargs):
        raise AssertionError("Local sender reading must not call a provider")
    monkeypatch.setattr(assistant_providers, "execute", external_call)
    params = {"property_id": case["property"].id}
    if surface.id == "cost_item":
        params["billing_period_id"] = case["period"].id
    response = _start(case, surface=surface.id, reader="local", file_url=_upload(_pdf(SAMPLE)), params=params)
    assert response.status_code == 201, response.text
    key = "sender" if surface.id == "document" else "supplier"
    result = response.json()["values"][key]
    assert result["value"] == result["evidence"] == "Hausservice Beispiel"
    assert result["evidence_status"] == "verified"
    assert result["citation"]["quote"] == "Hausservice Beispiel"
