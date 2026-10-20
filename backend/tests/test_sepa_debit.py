"""SEPA direct debit file: rules, preview per contract, the pain.008 file, register and replay."""
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from archive_helpers import purge_originals
from fastapi.testclient import TestClient
from lxml import etree

from backend import audit, auth
from backend.app import app
from backend.dependencies import store
from backend.models import (
    AccountCreate,
    ContractCreate,
    PortfolioCreate,
    PropertyCreate,
    ReceivableCreate,
    TenantCreate,
    UnitCreate,
)
from backend.services import sepa_debit
from backend.services import sepa_rules as rules
from backend.services.data_snapshot import clear_business_data

XSD = Path(__file__).parent / "fixtures" / "pain.008.001.08.xsd"
NS = {"p": rules.NAMESPACE}
CREDITOR = "DE98ZZZ09999999999"


def _says(problem: str | None, part: str) -> bool:
    return problem is not None and part in problem


def test_iban_bic_creditor_id_and_mandate_reference():
    assert rules.iban_problem("DE89 3704 0044 0532 0130 00") is None
    assert _says(rules.iban_problem("DE89370400440532013001"), "Prüfziffer")
    assert _says(rules.iban_problem("DE8937040044053201300"), "22 Stellen")
    assert rules.iban_problem("") == "IBAN fehlt."
    assert rules.bic_problem("COBADEFFXXX") is None and rules.bic_problem("COBADEFF") is None and rules.bic_problem("") is None
    assert rules.bic_problem("COBA DE") is not None
    assert rules.creditor_id_problem(CREDITOR) is None
    assert _says(rules.creditor_id_problem("DE97ZZZ09999999999"), "Prüfziffer")
    assert rules.mandate_problem("MR-123456") is None
    assert _says(rules.mandate_problem("MR 123456"), "Leerzeichen")
    assert rules.text("Jürgen Weiß & Söhne – „Grünstraße“ 4", 70) == "Juergen Weiss + Soehne - Gruenstrasse 4"
    assert rules.mask_iban("DE02120300000000202051") == "DE02 … 2051"


def test_business_days_and_collection_date():
    assert rules.target_holiday(date(2027, 3, 26)) == "Karfreitag"
    assert rules.target_holiday(date(2027, 3, 29)) == "Ostermontag"
    assert rules.target_holiday(date(2026, 10, 3)) is None          # a German holiday, but TARGET2 is open
    assert rules.next_business_day(date(2026, 12, 25)) == date(2026, 12, 28)
    today = date(2026, 10, 20)
    assert rules.collection_date_problem(date(2026, 10, 21), today) is None
    assert _says(rules.collection_date_problem(date(2026, 10, 20), today), "Bankarbeitstag")
    assert _says(rules.collection_date_problem(date(2026, 10, 24), today), "Samstag")
    assert _says(rules.collection_date_problem(date(2026, 12, 25), today), "nächster Bankarbeitstag: 28.12.2026")


def test_the_message_is_valid_pain_008_001_08():
    xml = rules.pain008(message_id="IMMO-1", created=datetime(2026, 10, 20, 13, 0), creditor_name="Linda Reiser",
                        creditor_iban="DE89370400440532013000", creditor_bic=None, creditor_id=CREDITOR,
                        collection_date=date(2026, 11, 3), transactions=[
                            {"end_to_end_id": "202611-MV-1", "amount": Decimal("812.40"), "mandate_id": "MR-1",
                             "mandate_date": date(2021, 5, 1), "debtor_name": "Jürgen Weiß",
                             "debtor_iban": "DE02120300000000202051", "debtor_bic": "BYLADEM1001",
                             "remittance": "Miete 11/2026"}])
    document = etree.fromstring(xml)
    schema = etree.XMLSchema(etree.parse(str(XSD)))
    assert schema.validate(document), schema.error_log
    assert document.findtext(".//p:CdtrAgt/p:FinInstnId/p:Othr/p:Id", namespaces=NS) == "NOTPROVIDED"
    assert document.findtext(".//p:DbtrAgt/p:FinInstnId/p:BICFI", namespaces=NS) == "BYLADEM1001"
    assert document.findtext(".//p:Dbtr/p:Nm", namespaces=NS) == "Juergen Weiss"


@pytest.fixture
def case(monkeypatch):
    purge_originals(store)
    clear_business_data(store)
    auth.clear_users()
    audit.clear_audit_logs()
    monkeypatch.setattr(sepa_debit, "_today", lambda: date(2026, 10, 20))
    owner = auth.register_user("sepa-owner", "owner@example.test", "Linda Reiser", "Secret123", "eigentuemer")
    booker = auth.register_user("sepa-books", "books@example.test", "Nora Buch", "Secret123", "buchhaltung")
    technician = auth.register_user("sepa-tech", "tech@example.test", "Tom Technik", "Secret123", "techniker")
    portfolio = store.create_portfolio(PortfolioCreate(name="Bestand Reiser", owner_name="Linda Reiser"))
    other = store.create_portfolio(PortfolioCreate(name="Fremdbestand"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Bautzner Straße 61",
                                                property_type="residential"))
    foreign = store.create_property(PropertyCreate(portfolio_id=other.id, name="Fremdhaus", property_type="residential"))
    account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Mietkonto", bank_name="Testbank",
                                                 iban="DE89 3704 0044 0532 0130 00", account_type="bank"))

    def lease(number, tenant, place=prop, **rent):
        unit = store.create_unit(UnitCreate(property_id=place.id, label=f"Whg {number}", unit_type="apartment", area_sqm=60,
                                            **rent))
        return store.create_contract(ContractCreate(contract_number=number, property_id=place.id, unit_id=unit.id,
                                                    tenant_id=tenant.id, start_date=date(2021, 5, 1), status="active"))

    def debit(name, **values):
        return store.create_tenant(TenantCreate(full_name=name, payment_method="sepa_direct_debit", **values))

    complete = dict(sepa_iban="DE02120300000000202051", sepa_mandate="MR-100001", sepa_mandate_date=date(2021, 4, 20))
    contracts = {
        "ready": lease("MV-1", debit("Jürgen Weiß", **complete), cold_rent=700, service_charge_advance=150,
                       heating_advance=60),
        "no_iban": lease("MV-2", debit("Sabine Krause", sepa_mandate="MR-100002", sepa_mandate_date=date(2021, 4, 20))),
        "transfer": lease("MV-3", store.create_tenant(TenantCreate(full_name="Ida Überweisung", payment_method="bank_transfer"))),
        "foreign": lease("MV-4", debit("Fremd Mieter", **complete), foreign),
        "paid": lease("MV-5", debit("Paula Pünktlich", **{**complete, "sepa_mandate": "MR-100005",
                                                         "sepa_account_holder": "Paula und Peter Pünktlich"})),
    }
    receivables = {
        "back_payment": store.create_receivable(ReceivableCreate(contract_id=contracts["ready"].id, due_date=date(2026, 11, 3),
                                                                 amount_due=812.40, description="Nachzahlung 2025")),
        "extra": store.create_receivable(ReceivableCreate(contract_id=contracts["ready"].id, due_date=date(2026, 11, 3),
                                                          amount_due=55.00, description="Stellplatz")),
        "october": store.create_receivable(ReceivableCreate(contract_id=contracts["ready"].id, due_date=date(2026, 10, 3),
                                                            amount_due=812.40, description="Miete")),
    }
    for key in ("no_iban", "foreign"):
        store.create_receivable(ReceivableCreate(contract_id=contracts[key].id, due_date=date(2026, 11, 3), amount_due=600))
    store.create_receivable(ReceivableCreate(contract_id=contracts["paid"].id, due_date=date(2026, 11, 3), amount_due=700,
                                             status="paid"))
    clients = {name: TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(user.id)})
               for name, user in (("owner", owner), ("books", booker), ("tech", technician))}
    yield {"account": account, "contracts": contracts, "receivables": receivables, **clients}
    for client in clients.values():
        client.close()
    auth.clear_users()
    audit.clear_audit_logs()
    clear_business_data(store)


def _preview(client, case, **params):
    response = client.get("/api/v1/receivables/sepa-debits/preview",
                          params={"account_id": case["account"].id, "month": "2026-11", **params})
    assert response.status_code == 200, response.text
    return response.json()


def _file(client, case, contract_ids, key=None, **values):
    body = {"account_id": case["account"].id, "month": "2026-11", "collection_date": "2026-11-03",
            "creditor_id": CREDITOR, "creditor_name": "Linda Reiser", "contract_ids": contract_ids,
            "idempotency_key": key or str(uuid4()), **values}
    return client.post("/api/v1/receivables/sepa-debits/files", json=body)


def test_preview_lists_the_portfolio_s_direct_debit_contracts_with_what_is_open(case):
    preview = _preview(case["books"], case)
    lines = {line["contract_number"]: line for line in preview["lines"]}
    assert set(lines) == {"MV-1", "MV-2", "MV-5"}                      # not the transfer, not the other portfolio
    ready = lines["MV-1"]
    # the monthly rent from the tenant account (nothing paid) and the stored receivables due in November
    assert ready["ready"] and ready["amount"] == "1777.40" and ready["iban"] == "DE02 … 2051"
    assert [(item["description"], item["open"]) for item in ready["receivables"]] == [
        ("Miete", "910.00"), ("Nachzahlung 2025", "812.40"), ("Stellplatz", "55.00")]      # not October
    assert lines["MV-2"]["problems"] == ["IBAN fehlt."] and not lines["MV-2"]["ready"]
    assert lines["MV-5"]["amount"] == "0.00" and not lines["MV-5"]["ready"]
    assert lines["MV-5"]["account_holder"] == "Paula und Peter Pünktlich"
    assert preview["ready_count"] == 1 and preview["ready_total"] == "1777.40"
    assert preview["collection_date"] == "2026-11-02" and preview["collection_date_problem"] is None
    assert preview["creditor"]["creditor_id"] == ""
    assert preview["creditor"]["suggested_name"] == "Linda Reiser"                     # the portfolio's owner
    assert _preview(case["books"], case, collection_date="2026-11-01")["collection_date_problem"].startswith("Der 01.11.2026")


def test_the_file_is_valid_recorded_replayed_and_not_written_twice_by_accident(case):
    ready = case["contracts"]["ready"].id
    key = str(uuid4())
    response = _file(case["books"], case, [ready], key)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["count"] == 1 and result["total"] == "1777.40" and result["filename"] == "SEPA-Lastschriften_2026-11_2026-11-03.xml"
    document = etree.fromstring(result["xml"].encode())
    schema = etree.XMLSchema(etree.parse(str(XSD)))
    assert schema.validate(document), schema.error_log
    assert document.findtext(".//p:ReqdColltnDt", namespaces=NS) == "2026-11-03"
    assert document.findtext(".//p:CdtrSchmeId/p:Id/p:PrvtId/p:Othr/p:Id", namespaces=NS) == CREDITOR
    assert document.findtext(".//p:DrctDbtTxInf/p:InstdAmt", namespaces=NS) == "1777.40"
    assert document.findtext(".//p:MndtId", namespaces=NS) == "MR-100001"
    assert document.findtext(".//p:Ustrd", namespaces=NS) == "Miete, Nachzahlung 2025, Stellplatz 11/2026 Vertrag MV-1"
    # the same request again (a lost answer): the same file, no second record
    again = _file(case["books"], case, [ready], key)
    assert again.status_code == 200 and again.json()["message_id"] == result["message_id"]
    assert len([entry for entry in audit.list_audit_logs() if entry.action == sepa_debit.REGISTER]) == 1
    # a new request for the same receivables needs a confirmation
    preview = _preview(case["books"], case)
    line = next(item for item in preview["lines"] if item["contract_number"] == "MV-1")
    assert line["repeated"] and line["receivables"][0]["earlier"][0]["message_id"] == result["message_id"]
    assert preview["files"][0]["message_id"] == result["message_id"]
    assert preview["creditor"] | {"revision": 0} == {"revision": 0, "creditor_id": CREDITOR, "creditor_name": "Linda Reiser",
                                                     "suggested_name": preview["creditor"]["suggested_name"]}
    refused = _file(case["books"], case, [ready])
    assert refused.status_code == 409 and "MV-1" in str(refused.json())
    assert _file(case["books"], case, [ready], allow_repeat=True).status_code == 200


def test_what_is_refused(case):
    contracts = case["contracts"]
    assert _file(case["books"], case, [contracts["no_iban"].id]).status_code == 409
    assert _file(case["books"], case, [contracts["foreign"].id]).status_code == 409
    assert _file(case["books"], case, [contracts["ready"].id], creditor_id="DE97ZZZ09999999999").status_code == 422
    assert _file(case["books"], case, [contracts["ready"].id], collection_date="2026-11-07").status_code == 422   # Saturday
    assert _file(case["books"], case, [contracts["ready"].id], collection_date="2026-10-20").status_code == 422   # today
    assert _file(case["books"], case, []).status_code == 422
    assert _file(case["tech"], case, [contracts["ready"].id]).status_code == 403
    assert not [entry for entry in audit.list_audit_logs() if entry.action == sepa_debit.REGISTER]


def test_tenant_bank_details_are_checked_and_anonymized(case):
    owner = case["owner"]
    bad = owner.post("/api/v1/tenants", json={"full_name": "Falsch", "sepa_iban": "DE02120300000000202052"})
    assert bad.status_code == 422
    made = owner.post("/api/v1/tenants", json={"full_name": "Richtig", "sepa_iban": "de02 1203 0000 0000 2020 51",
                                               "sepa_bic": "byla dem1 001", "sepa_mandate_date": "2024-01-15"})
    assert made.status_code in (200, 201), made.text
    assert made.json()["sepa_iban"] == "DE02120300000000202051" and made.json()["sepa_bic"] == "BYLADEM1001"
    tenant_id = made.json()["id"]
    assert owner.patch(f"/api/v1/tenants/{tenant_id}", json={"sepa_iban": ""}).json()["sepa_iban"] is None
    owner.patch(f"/api/v1/tenants/{tenant_id}", json={"sepa_iban": "DE02120300000000202051"})
    anonymized = owner.post(f"/api/v1/admin/dsgvo/tenant/{tenant_id}/anonymize")
    assert anonymized.status_code == 200, anonymized.text
    tenant = store.get_tenant(tenant_id)
    assert (tenant.sepa_iban, tenant.sepa_bic, tenant.sepa_mandate_date) == (None, None, None)
