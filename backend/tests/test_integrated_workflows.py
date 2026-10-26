"""Cross-module workflow guidance follows real source changes, scopes and decisions."""
from datetime import date, timedelta
from uuid import uuid4

import pytest
import test_e_invoice_intakes as receipt_fixtures
from archive_helpers import purge_payment_evidence
from fastapi.testclient import TestClient
from test_e_invoice_intakes import command, receipt

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.domain.clock import local_today
from backend.invoice_review_models import CheckRequest, DecisionRequest
from backend.models import ContractCreate, MaintenanceCaseCreate, TenantCreate, UnitCreate
from backend.payment_security_models import AuthorizePayment, RecipientChange
from backend.services import invoice_review, payment_security
from backend.services.e_invoice import service as intakes

estate = receipt_fixtures.estate
valid_engine = receipt_fixtures.valid_engine


@pytest.fixture
def office(estate):
    owner, prop, portfolio = estate
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)})
    yield owner, prop, portfolio, client
    purge_payment_evidence(store)


def items(client, kind, extra=""):
    result = client.get(f"/api/v1/work-center/items?kind={kind}{extra}")
    assert result.status_code == 200, result.text
    return result.json()["items"]


def test_invoice_chain_moves_from_intake_to_checks_and_exact_payment_proposal(office, estate, valid_engine):
    owner, _, _, client = office
    row = receipt(estate)
    incoming = items(client, "e_invoice")
    assert incoming[0]["workflow"]["stage"] == "intake_valid"
    assert incoming[0]["href"].endswith(row["id"])
    accepted = intakes.accept(store, owner.id, row["id"], command(row))
    identifier = accepted["invoice_id"]
    assert items(client, "e_invoice") == []
    assert items(client, "invoice")[0]["workflow"]["stage"] == "factual"
    invoice_review.factual_check(store, identifier, CheckRequest(result="confirmed"), owner.id)
    assert items(client, "invoice")[0]["workflow"]["stage"] == "arithmetic"
    invoice_review.arithmetic_check(store, identifier, CheckRequest(result="confirmed"), owner.id)
    assert items(client, "invoice")[0]["workflow"]["stage"] == "decision"
    invoice_review.decide(store, identifier, DecisionRequest(decision="approve"), owner.id)
    assert items(client, "invoice")[0]["workflow"]["stage"] == "bank_check"
    state = payment_security.read(store, owner.id, identifier)
    state = payment_security.change_recipient(store, owner.id, identifier, RecipientChange(
        expected_revision=state["revision"], idempotency_key=uuid4().hex, name="Testbetrieb",
        iban="DE89370400440532013000", reason="Angaben am Originalbeleg übernommen."))
    blocked = items(client, "invoice")[0]["workflow"]
    assert not blocked["next_action"]["allowed"] and blocked["waiting_for"]
    second = auth.register_user("bank-checker", "checker@example.test", "Gegenprüfung", "Secret123", "buchhaltung")
    payment_security.authorize(store, second.id, identifier, AuthorizePayment(expected_revision=state["revision"],
        idempotency_key=uuid4().hex, reason="Rechnung und Betrag fachlich geprüft.",
        bank_verification="Bankverbindung telefonisch unter bekannter Kontaktnummer bestätigt."))
    ready = items(client, "invoice")[0]["workflow"]
    assert ready["stage"] == "proposal" and ready["next_action"]["href"] == "/invoice-review?tab=proposals"


def test_turnover_exists_before_a_protocol_and_deferral_does_not_finish_it(office):
    owner, prop, _, client = office
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="WE1", unit_type="residential"))
    tenant = store.create_tenant(TenantCreate(full_name="Haushalt Eins"))
    end = local_today() - timedelta(days=1)
    contract = store.create_contract(ContractCreate(contract_number="ENDE-1", property_id=prop.id, unit_id=unit.id,
        tenant_id=tenant.id, start_date=date(2025, 1, 1), end_date=end, status="terminated", deposit_amount=0))
    row = items(client, "contract_end")[0]
    assert row["entity_id"] == contract.id and row["workflow"]["stage"] == "handover"
    assert row["workflow"]["steps"][3]["done"] is True
    assert not row["workflow"]["completed"]
    result = client.put("/api/v1/workspace/deferrals/" + row["work_item_key"], json={"base_revision": 0,
        "due_on": (local_today() + timedelta(days=7)).isoformat(), "reason": "Termin mit Mieter vereinbaren", "idempotency_key": uuid4().hex})
    assert result.status_code == 200, result.text
    assert items(client, "contract_end", "&deferred=active") == []
    assert items(client, "contract_end")[0]["due_date"] == end.isoformat()
    assert store.get_contract(contract.id).status == "terminated"


def test_damage_guidance_uses_live_assignment_and_revoked_write_rights(office):
    owner, prop, _, client = office
    case = store.create_maintenance_case(MaintenanceCaseCreate(property_id=prop.id, title="Fensterschaden"))
    assert items(client, "maintenance")[0]["workflow"]["stage"] == "responsibility"
    response = client.patch(f"/api/v1/maintenance/{case.id}", json={"assignee": "Hausverwaltung"})
    assert response.status_code == 200, response.text
    row = items(client, "maintenance")[0]
    assert row["workflow"]["stage"] == "order" and row["workflow"]["assignee"] == "Hausverwaltung"
    auth.update_user(owner.id, {"role": "readonly"})
    assert not items(client, "maintenance")[0]["workflow"]["next_action"]["allowed"]


def test_foreign_intake_is_absent_from_items_counts_and_direct_deferral(office, estate, valid_engine):
    row = receipt(estate)
    other = auth.register_user("other-scope", "other-scope@example.test", "Other", "Secret123", "buchhaltung",
        portfolio_access="selected", portfolio_ids=[])
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(other.id)})
    assert items(client, "e_invoice") == []
    summary = client.get("/api/v1/work-center/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["counts"]["e_invoice"] == 0
    result = client.put(f"/api/v1/workspace/deferrals/e_invoice:{row['id']}:intake_review", json={
        "base_revision": 0, "due_on": local_today().isoformat(), "reason": "Direkte fremde ID", "idempotency_key": uuid4().hex})
    assert result.status_code == 404
