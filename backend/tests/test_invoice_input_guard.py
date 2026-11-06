"""The production plausibility dependency sees unparsed JSON before request DTOs."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend import dependencies
from backend.exceptions import register_exception_handlers
from backend.models import InvoiceCreate, InvoicePatch
from backend.routers import invoices
from backend.routing import plausibility_guard
from backend.tests.test_financial_input_and_cutoff import estate as _estate_fixture  # noqa: F401


@pytest.fixture(name="estate")
def _finance_estate(_estate_fixture):  # noqa: F811 - pytest injects the imported parametrized fixture
    return _estate_fixture


def test_invoice_guard_rejects_bad_numeric_values_and_string_arithmetic_without_writes(estate, monkeypatch):
    store, prop, _ = estate
    monkeypatch.setattr(invoices, "store", store)
    monkeypatch.setattr(dependencies, "store", store)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(invoices.router, dependencies=[Depends(plausibility_guard)])
    base = {"property_id": prop.id, "supplier": "Lieferant", "invoice_date": "2026-01-01",
            "net_amount": 100, "gross_amount": 100, "vat_rate": 0}
    with TestClient(app, raise_server_exceptions=False) as client:
        original = client.post("/invoices", json=base)
        assert original.status_code == 201, original.text
        key = original.json()["id"]
        before = [row.model_dump(mode="json") for row in store.list_invoices()]
        for method in ("post", "put", "patch"):
            path = "/invoices" if method == "post" else f"/invoices/{key}"
            for bad in (1e100, "1e100", "NaN", "Infinity"):
                body = {**base, "net_amount": bad, "gross_amount": bad}
                response = getattr(client, method)(path, json=body)
                assert response.status_code in (400, 422), (method, bad, response.status_code, response.text)
                assert [row.model_dump(mode="json") for row in store.list_invoices()] == before
            for mismatch in (
                {"net_amount": "200", "gross_amount": "100", "vat_rate": 0},
                {"net_amount": 100, "gross_amount": 100, "vat_rate": "19"},
            ):
                response = getattr(client, method)(path, json={**base, **mismatch})
                assert response.status_code == 400, (method, mismatch, response.status_code, response.text)
                assert [row.model_dump(mode="json") for row in store.list_invoices()] == before
        valid = client.patch(f"/invoices/{key}", json={"net_amount": "2.675", "gross_amount": "2.675"})
        assert valid.status_code == 200, valid.text
        assert valid.json()["gross_amount"] == valid.json()["net_amount"] == 2.68
        # A missing rate means the DTO's 19% default on create/replace. An
        # existing 0% invoice keeps its stored rate on a partial edit.
        omitted_rate = {k: v for k, v in base.items() if k != "vat_rate"}
        rejected = client.post("/invoices", json=omitted_rate)
        assert rejected.status_code == 400, rejected.text
        accepted = client.post("/invoices", json={**omitted_rate, "gross_amount": 119})
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["vat_rate"] == 19
        wrong_patch = client.patch(f"/invoices/{accepted.json()['id']}", json={"gross_amount": 100})
        assert wrong_patch.status_code == 400, wrong_patch.text
        zero_patch = client.patch(f"/invoices/{key}", json={"net_amount": 5, "gross_amount": 5})
        assert zero_patch.status_code == 200, zero_patch.text
        assert zero_patch.json()["vat_rate"] == 0
        explicit_zero = client.post("/invoices", json=base)
        assert explicit_zero.status_code == 201, explicit_zero.text


@pytest.mark.parametrize("rate", [True, False])
def test_invoice_boolean_vat_rate_is_a_validation_error_without_writes(estate, monkeypatch, rate):
    store, prop, _ = estate
    monkeypatch.setattr(invoices, "store", store)
    monkeypatch.setattr(dependencies, "store", store)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(invoices.router, dependencies=[Depends(plausibility_guard)])
    base = {"property_id": prop.id, "supplier": "Lieferant", "invoice_date": "2026-01-01",
            "net_amount": 100, "gross_amount": 119, "vat_rate": 19}
    bad = {**base, "gross_amount": 101 if rate else 100, "vat_rate": rate}
    with TestClient(app, raise_server_exceptions=False) as client:
        original = client.post("/invoices", json=base)
        assert original.status_code == 201, original.text
        key = original.json()["id"]
        before = [row.model_dump(mode="json") for row in store.list_invoices()]
        for method in ("post", "put", "patch"):
            path = "/invoices" if method == "post" else f"/invoices/{key}"
            result = getattr(client, method)(path, json=bad)
            assert result.status_code == 400, (method, rate, result.status_code, result.text)
            assert [row.model_dump(mode="json") for row in store.list_invoices()] == before
    with pytest.raises(ValueError):
        InvoiceCreate.model_validate(bad)
    with pytest.raises(ValueError):
        InvoicePatch.model_validate({"vat_rate": rate})
    # A percentage is not money. The input models retain supported decimal
    # precision and numeric strings instead of applying cent rounding to it.
    assert InvoiceCreate.model_validate({**base, "vat_rate": "12.3456"}).vat_rate == 12.3456
    assert InvoicePatch.model_validate({"vat_rate": "12.3456"}).vat_rate == 12.3456
