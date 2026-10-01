import sys
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import app as app_module
from backend import auth

WIZARD_ROOT = (
    Path(__file__).resolve().parent.parent.parent
    / "mietvertrag_wizard_fastapi_reportlab_pro"
)
if str(WIZARD_ROOT) not in sys.path:
    sys.path.insert(0, str(WIZARD_ROOT))

from mietvertrag_wizard.pdf_reportlab import _fmt_eur, _sum_money, build_contract_pdf  # noqa: E402
from mietvertrag_wizard.validation import (  # noqa: E402
    ContractValidationError,
    validate_contract_payload,
)


def payload():
    return {
        "vermieter": [{"name": "Vermieter & Co."}],
        "mieter": [{"name": "Mieter <Test>"}],
        "objekt": {
            "art": "Wohnung",
            "strasse": "Musterstraße 1",
            "plz": "60311",
            "ort": "Frankfurt",
            "schluessel": {},
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
        "sonstigeVereinbarungen": "<b>nur Text</b> & synthetisch",
    }


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("NaN", "endlicher Betrag"),
        ("Infinity", "endlicher Betrag"),
        ("-Infinity", "endlicher Betrag"),
        ("800.001", "centgenau"),
    ],
)
def test_required_rent_rejects_nonfinite_or_subcent_values(value, message):
    data = payload()
    data["miete"]["grund"] = value

    with pytest.raises(ContractValidationError, match=message):
        validate_contract_payload(data)

    with pytest.raises(ContractValidationError, match=message):
        build_contract_pdf(data)


@pytest.mark.parametrize("field", ["betrieb", "heizung", "kaution"])
def test_optional_money_is_exact_and_nonnegative(field):
    data = payload()
    data["miete"][field] = "12.345"
    with pytest.raises(ContractValidationError, match="centgenau"):
        validate_contract_payload(data)

    data = payload()
    data["miete"][field] = "-0.01"
    with pytest.raises(ContractValidationError, match="darf nicht negativ"):
        validate_contract_payload(data)


def test_exact_extra_zero_decimal_places_remain_valid_and_pdf_builds():
    data = payload()
    data["miete"]["grund"] = "800.0000"
    data["miete"]["betrieb"] = "0.0000"
    assert validate_contract_payload(data) is data
    pdf = build_contract_pdf(data)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


@pytest.mark.parametrize(
    ("value", "formatted"),
    [
        ("1234.56", "1.234,56 €"),
        ("1234,56", "1.234,56 €"),
        ("1.234,56", "1.234,56 €"),
        ("12.345.678,90", "12.345.678,90 €"),
    ],
)
def test_explicit_browser_and_german_money_notation_remain_valid(value, formatted):
    data = payload()
    data["miete"]["grund"] = value
    assert validate_contract_payload(data) is data
    assert _fmt_eur(value) == formatted


@pytest.mark.parametrize("value", ["12.34,56", "1.23.456,78", "1,234.56"])
def test_invalid_or_conflicting_grouping_is_rejected_without_reinterpretation(value):
    data = payload()
    data["miete"]["grund"] = value
    with pytest.raises(ContractValidationError, match="kein gültiger Betrag"):
        build_contract_pdf(data)


@pytest.mark.parametrize("value", ["1e3", "1E+1000000", "8.00e2", "1e-2"])
def test_exponential_money_notation_is_rejected_before_pdf(value):
    data = payload()
    data["miete"]["grund"] = value
    with pytest.raises(ContractValidationError, match="Exponentialnotation"):
        build_contract_pdf(data)


def test_large_cent_exact_sum_does_not_use_default_decimal_precision():
    left = "9999999999999999999999999999.99"
    right = "9999999999999999999999999999.99"
    total = _sum_money((left, right, "0.02"))
    assert total == Decimal("20000000000000000000000000000.00")
    assert _fmt_eur(total) == "20.000.000.000.000.000.000.000.000.000,00 €"


def test_large_cent_values_build_pdf_without_sum_rounding_failure():
    data = payload()
    data["miete"]["grund"] = "9999999999999999999999999999.99"
    data["miete"]["betrieb"] = "9999999999999999999999999999.99"
    data["miete"]["heizung"] = "0.02"
    pdf = build_contract_pdf(data)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


@pytest.mark.parametrize("party", ["vermieter", "mieter"])
def test_mixed_party_list_is_rejected_before_pdf_builder(party):
    data = payload()
    data[party].append("kein Objekt")

    with pytest.raises(ContractValidationError, match="darf nur Objekte enthalten"):
        build_contract_pdf(data)


def test_mixed_staffel_list_and_subcent_staffel_are_rejected():
    data = payload()
    data["miete"].update(
        erhoehung="staffel",
        staffeln=[{"ab": "01.2027", "betrag": "850.00"}, "kein Objekt"],
    )
    with pytest.raises(ContractValidationError, match="Staffel 2 muss ein Objekt"):
        build_contract_pdf(data)

    data["miete"]["staffeln"] = [{"ab": "01.2027", "betrag": "850.001"}]
    with pytest.raises(ContractValidationError, match="centgenau"):
        build_contract_pdf(data)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data.__setitem__("zahlung", []), "Zahlungsangaben muss ein Objekt"),
        (lambda data: data.__setitem__("mandat", "kein Objekt"), "SEPA-Mandat muss ein Objekt"),
        (lambda data: data.__setitem__("clauses", 7), "Weitere Vereinbarungen muss ein Objekt"),
        (
            lambda data: data["objekt"].__setitem__("schluessel", []),
            "Schlüsselangaben muss ein Objekt",
        ),
    ],
)
def test_optional_sections_reject_nonobjects_before_render(mutate, message):
    data = payload()
    mutate(data)
    with pytest.raises(ContractValidationError, match=message):
        build_contract_pdf(data)


def _real_http_client(monkeypatch):
    loaded = app_module._load_contract_wizard_mount()
    assert loaded is not None
    monkeypatch.setattr(app_module, "_load_contract_wizard_mount", lambda: loaded)
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    user = auth.register_user(
        "wizard-hardening-owner",
        "wizard-hardening@example.invalid",
        "Synthetic owner",
        "Strong123",
        "eigentuemer",
    )
    app = FastAPI()
    assert app_module._mount_contract_wizard_if_available(app)
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + auth.create_access_token(user.id)}
    return client, headers


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["miete"].__setitem__("grund", "NaN"),
        lambda data: data["vermieter"].append(17),
        lambda data: data.__setitem__("zahlung", []),
        lambda data: data["miete"].__setitem__("betrieb", "1.001"),
        lambda data: data["miete"].__setitem__("grund", "12.34,56"),
        lambda data: data["miete"].__setitem__("grund", "1E+1000000"),
    ],
)
def test_http_pdf_returns_422_for_validator_consistency_errors(monkeypatch, mutation):
    client, headers = _real_http_client(monkeypatch)
    data = payload()
    mutation(data)

    response = client.post(
        "/api/v1/contract-wizard/pdf",
        headers=headers,
        json=data,
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    assert isinstance(response.json()["detail"], str)
    assert response.json()["detail"]
