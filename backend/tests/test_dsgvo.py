"""DSGVO: the data access export is complete and anonymization really removes personal data."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.models import (
    AccountCreate,
    BookingCreate,
    ContractCreate,
    DepositCreate,
    DocumentCreate,
    MessageCreate,
    MessageThreadCreate,
    PortfolioCreate,
    PropertyCreate,
    ReceivableCreate,
    RentChargeCreate,
    TenantCreate,
    UnitCreate,
)
from backend.services.data_snapshot import clear_business_data


@pytest.fixture
def client():
    clear_business_data(store)
    clear_users()
    owner = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    yield TestClient(app, headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})
    clear_users()
    clear_business_data(store)


@pytest.fixture
def lars():
    pf = store.create_portfolio(PortfolioCreate(name="Bestand"))
    prop = store.create_property(PropertyCreate(portfolio_id=pf.id, name="MFH", property_type="residential"))
    account = store.create_account(AccountCreate(portfolio_id=pf.id, name="Mietkonto", account_type="bank"))
    tenants, contracts = [], []
    for i, name in enumerate(["Lars Petersen", "Nachbarin"]):
        unit = store.create_unit(UnitCreate(property_id=prop.id, label=f"WE {i}", unit_type="Wohnung"))
        tenant = store.create_tenant(TenantCreate(
            full_name=name, email=f"t{i}@example.de", phone="+49 372 342754", address_line="Gohliser Str. 12",
            postal_code="04155", city="Leipzig", sepa_mandate="MANDAT-1", notes="zahlt pünktlich"))
        contract = store.create_contract(ContractCreate(
            contract_number=f"MV-0{i}", property_id=prop.id, unit_id=unit.id, tenant_id=tenant.id,
            start_date=date(2020, 1, 1), end_date=date(2025, 3, 31), status="terminated"))
        store.create_booking(BookingCreate(account_id=account.id, tenant_id=tenant.id, booking_date=date(2025, 3, 3),
                                           amount=640.0, payment_text=f"Miete 03/2025 {name}"))
        store.create_deposit(DepositCreate(contract_id=contract.id, amount=1500.0))
        store.create_receivable(ReceivableCreate(contract_id=contract.id, due_date=date(2025, 3, 3), amount_due=640.0))
        store.create_rent_charge(RentChargeCreate(contract_id=contract.id, month="2025-03", cold_rent=640.0))
        store.create_document(DocumentCreate(contract_id=contract.id, title="Mietvertrag", file_url="/f.pdf"))
        thread = store.create_message_thread(MessageThreadCreate(subject="Auszug", contract_id=contract.id))
        store.create_message(MessageCreate(thread_id=thread.id, sender_name=name, body="Schlüsselübergabe am 31.3."))
        tenants.append(tenant)
        contracts.append(contract)
    return tenants[0]


def test_data_access_export_contains_everything_of_the_tenant_only(client, lars):
    """Regression: bookings, documents and messages were never found (wrong link fields)."""
    export = client.get(f"/api/v1/admin/dsgvo/tenant/{lars.id}/export").json()

    counts = {key: len(value) for key, value in export.items() if isinstance(value, list)}
    assert counts == {"contracts": 1, "bookings": 1, "deposits": 1, "receivables": 1, "rent_charges": 1,
                      "rent_adjustments": 0, "utility_statements": 0, "documents": 1, "handover_protocols": 0,
                      "message_threads": 1, "messages": 1}
    assert export["tenant"]["full_name"] == "Lars Petersen"
    assert "Nachbarin" not in str(export)


def test_anonymization_removes_name_contact_and_address(client, lars):
    """Regression: the answer said "anonymized" while name, e-mail and phone stayed (validation error)."""
    response = client.post(f"/api/v1/admin/dsgvo/tenant/{lars.id}/anonymize")

    assert response.status_code == 200
    tenant = store.get_tenant(lars.id)
    assert tenant.full_name == f"Anonymisiert-{lars.id[:8]}" and tenant.archived
    assert [tenant.email, tenant.phone, tenant.address_line, tenant.postal_code, tenant.city,
            tenant.sepa_mandate, tenant.notes] == [None] * 7
    body = response.json()
    assert body["anonymized_fields"] == ["address_line", "city", "email", "full_name", "notes", "phone",
                                         "postal_code", "sepa_mandate"]
    assert body["retained_records"]["bookings"] == 1
    assert store.get_tenant(lars.id).full_name != "Lars Petersen"
    assert "Lars Petersen" not in client.get(f"/api/v1/tenants/{lars.id}").text
