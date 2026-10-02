import re
import sys
from pathlib import Path

import pytest
from reportlab import rl_config

from backend.services.contract_wizard import build_pdf, digest
from backend.storage import ValidationError

ROOT = Path(__file__).resolve().parents[2]
WIZARD_PACKAGE = ROOT / "mietvertrag_wizard_fastapi_reportlab_pro"
if str(WIZARD_PACKAGE) not in sys.path:
    sys.path.insert(0, str(WIZARD_PACKAGE))

from mietvertrag_wizard.pdf_reportlab import build_contract_pdf  # noqa: E402


def _payload():
    return {
        "vermieter": [{
            "name": "Anna Vermieter",
            "strasse": "Musterweg 1",
            "plz": "60311",
            "ort": "Frankfurt am Main",
        }],
        "mieter": [{
            "name": "Max Mieter",
            "strasse": "Beispielstr. 7",
            "plz": "60313",
            "ort": "Frankfurt am Main",
        }],
        "objekt": {
            "strasse": "Wohnstrasse 12",
            "plz": "60316",
            "ort": "Frankfurt am Main",
            "art": "Wohnung",
            "wohnflaeche": "82,5",
            "geschoss": "2. OG",
            "zimmer": "3",
        },
        "mietzeit": {"beginn": "01.11.2026", "art": "unbefristet"},
        "miete": {
            "grund": "1250,00",
            "betrieb": "220,00",
            "heizung": "110,00",
            "kaution": "3750,00",
        },
        "zahlung": {"faelligkeit": "zum dritten Werktag"},
        "clauses": {
            "tierhaltung": True,
            "untervermietung": True,
            "hausordnung": True,
            "rauchmelder": True,
            "schriftform": True,
        },
        "sonstigeVereinbarungen": "Individuelle Vereinbarungen werden gesondert dokumentiert.",
    }


def test_contract_pdf_uses_theme_and_generates_complete_pages():
    pdf = build_contract_pdf(_payload())

    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) > 4_000
    assert len(re.findall(rb"/Type\s*/Page\b", pdf)) >= 2


def literal_text(pdf):
    # Only for our uncompressed synthetic ReportLab test PDFs: read text-show
    # operands, joining fragments so escaped markup cannot vanish as formatting.
    values = b"".join(re.findall(rb"\(((?:\\.|[^\\()])*)\)\s*Tj", pdf))
    values = re.sub(rb"\\([0-7]{3})", lambda match: bytes([int(match[1], 8)]), values)
    return values.decode("cp1252")


def test_legacy_visual_adaptation_preserves_literal_party_markup_and_exact_cents(monkeypatch):
    monkeypatch.setattr(rl_config, "pageCompression", 0)
    payload = _payload()
    payload["vermieter"][0]["name"] = "<b>Literal</b> & Änne"
    payload["miete"].update(grund="1250.10", betrieb="220.20", heizung="110.03")
    text = literal_text(build_contract_pdf(payload))
    assert "<b>Literal</b> & Änne" in text
    assert "1.580,33 €" in text
    assert "01.11.2026" in text and "Unterzeichnung" in text


def reviewed_snapshot():
    return dict(parameters=dict(contract_number="Synthetic reviewed 20-year archive",
        landlord_name="Synthetic owner <b>Literal</b> & Änne", landlord_address="Synthetic street 12",
        start_date="2026-10-01", end_date=None, deposit_amount="1500.00", index_rent="fixed", service_charge_settlement="annual"),
        tenant=dict(full_name="Synthetic tenant Öztürk", address_line="Synthetic address"),
        unit=dict(label="A", cold_rent=600.10, service_charge_advance=100.20, heating_advance=50.30),
        property=dict(name="Synthetic property"), portfolio=dict(currency="EUR"), template=dict(title="Own <version>", version=2),
        terms="\n".join(f"{index} Own complete synthetic agreement: äöüß € <b>Literal</b> & source. " * 4 for index in range(40))
            + "\nFINAL COMPLETE AGREEMENT.", attachments=[dict(id="original-id", title="Original <file> & note",
                mode="frozen_bytes", sha256="a" * 64, size_bytes=65537)])


def test_reviewed_multipage_pdf_preserves_final_terms_manifest_money_and_reference(monkeypatch):
    monkeypatch.setattr(rl_config, "pageCompression", 0)
    snapshot = reviewed_snapshot()
    pdf = build_pdf(snapshot)
    text = literal_text(pdf)
    assert len(re.findall(rb"/Type\s*/Page\b", pdf)) >= 3
    for expected in ["FINAL COMPLETE AGREEMENT.", "Original <file> & note", "a" * 64, "65537 Bytes",
                     "<b>Literal</b>", "600,10 €", "1.500,00 €", "Festmiete", digest(snapshot), "Manuelle Unterzeichnung"]:
        assert expected in text
    assert pdf.rstrip().endswith(b"%%EOF")


@pytest.mark.parametrize("amount", [float("inf"), 0.005])
def test_review_rejects_invalid_source_money_without_silent_rounding(amount):
    snapshot = reviewed_snapshot()
    snapshot["unit"]["cold_rent"] = amount
    with pytest.raises(ValidationError, match="Mietbeträge"):
        build_pdf(snapshot)
