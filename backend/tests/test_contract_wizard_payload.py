import sys
from pathlib import Path

import pytest

WIZARD_ROOT = (
    Path(__file__).resolve().parent.parent.parent
    / "mietvertrag_wizard_fastapi_reportlab_pro"
)
if str(WIZARD_ROOT) not in sys.path:
    sys.path.insert(0, str(WIZARD_ROOT))

from mietvertrag_wizard.pdf_reportlab import _fmt_eur, build_contract_pdf  # noqa: E402
from mietvertrag_wizard.validation import (  # noqa: E402
    ContractValidationError,
    validate_contract_payload,
)


def _valid_payload():
    return {
        "vermieter": [{"name": "Vermieter & Co."}],
        "mieter": [{"name": "Mieter <Test>"}],
        "objekt": {
            "art": "Wohnung",
            "strasse": "Musterstraße 1",
            "plz": "60311",
            "ort": "Frankfurt",
        },
        "mietzeit": {
            "art": "unbefristet",
            "beginn": "01.11.2026",
            "ende": "",
        },
        "miete": {
            "grund": "800.00",
            "betrieb": "150.00",
            "heizung": "100.00",
            "kaution": "1600.00",
            "erhoehung": "keine",
            "staffeln": [],
            "indexAusgang": "",
        },
        "zahlung": {},
        "mandat": {},
        "clauses": {},
        "sonstigeVereinbarungen": "",
    }


def test_browser_decimal_money_is_not_scaled_by_one_hundred():
    assert _fmt_eur("800.00") == "800,00 €"
    assert _fmt_eur("1.234,56") == "1.234,56 €"


def test_validation_accepts_minimum_coherent_payload():
    payload = _valid_payload()
    assert validate_contract_payload(payload) is payload


def test_validation_rejects_missing_contract_identity():
    payload = _valid_payload()
    payload["vermieter"] = []
    payload["objekt"]["strasse"] = ""
    payload["miete"]["grund"] = ""

    with pytest.raises(ContractValidationError) as exc:
        validate_contract_payload(payload)

    message = str(exc.value)
    assert "Vermieter" in message
    assert "Straße" in message
    assert "Grundmiete" in message


def test_validation_rejects_inconsistent_fixed_term_dates():
    payload = _valid_payload()
    payload["mietzeit"] = {
        "art": "befristet",
        "beginn": "01.11.2026",
        "ende": "31.10.2026",
    }

    with pytest.raises(ContractValidationError, match="nach dem Mietbeginn"):
        validate_contract_payload(payload)


def test_reportlab_escapes_user_markup_and_builds_pdf():
    payload = _valid_payload()
    payload["vermieter"][0]["name"] = "<b>Vermieter</b> & <img src=x>"
    payload["sonstigeVereinbarungen"] = "<script>alert('x')</script> & Sonderabrede"

    pdf = build_contract_pdf(payload)

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000
