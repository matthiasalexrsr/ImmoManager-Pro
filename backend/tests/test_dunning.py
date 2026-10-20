"""Dunning through the API: stages and timing, fees and interest, payments, objections, disputes,
blocks, immutable letters, outbox, replies and long threads, the proposing job, roles, portfolios,
snapshots and the DSGVO export.

Runs on the memory store and, with TEST_STORE_BACKEND=sql, on SQLite (PostgreSQL:
test_dunning_postgres.py). Pure rules: test_dunning_process.py.
"""

import hashlib
import re
from datetime import date, datetime

import pytest
from archive_helpers import purge_originals
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import (
    AccountCreate,
    BillingObjectionCreate,
    BillingPeriodCreate,
    BookingCreate,
    ContractCreate,
    PortfolioCreate,
    PropertyCreate,
    ReceivableCreate,
    TenantCreate,
    UnitCreate,
    UtilityStatementCreate,
)
from backend.services.data_snapshot import clear_business_data, export_snapshot, import_snapshot
from backend.services.jobs.core import JobRunner, MemoryJobStore, SqlJobStore
from backend.services.jobs.scheduler import ESCALATION_KIND, escalation_handler

API = "/api/v1/dunning"


def _reset():
    purge_originals(store)
    clear_business_data(store)


@pytest.fixture(autouse=True)
def _clean():
    _reset()
    auth.clear_users()
    yield
    _reset()
    auth.clear_users()


@pytest.fixture
def client():
    return TestClient(app)


def _bearer(user) -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token(user.id)}"}


def _user(name, role="eigentuemer", *portfolios) -> dict:
    if portfolios:
        return _bearer(auth.register_user(name, f"{name}@example.com", name.title(), "Secret123", role,
                                          portfolio_access="selected", portfolio_ids=[p.id for p in portfolios]))
    return _bearer(auth.register_user(name, f"{name}@example.com", name.title(), "Secret123", role))


def _commit():
    if hasattr(store, "db"):
        store.db.commit()


def _lease(name="Nord", number="V-1", end=date(2026, 7, 31), email="max@example.com"):
    portfolio = store.create_portfolio(PortfolioCreate(name=name, owner_name=f"Hausverwaltung {name}"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name=f"{name}haus",
                                                property_type="residential", address_line="Weg 1",
                                                postal_code="12345", city="Stadt"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="W1", unit_type="residential", area_sqm=50,
                                        cold_rent=800, service_charge_advance=200))
    tenant = store.create_tenant(TenantCreate(full_name=f"Mieter {name}", email=email))
    contract = store.create_contract(ContractCreate(contract_number=number, property_id=prop.id, unit_id=unit.id,
                                                    tenant_id=tenant.id, start_date=date(2026, 7, 1),
                                                    end_date=end))
    account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Konto", account_type="bank"))
    return {"portfolio": portfolio, "property": prop, "unit": unit, "tenant": tenant, "contract": contract,
            "account": account}


def _pay(lease, day, amount):
    store.create_booking(BookingCreate(account_id=lease["account"].id, booking_date=date.fromisoformat(day),
                                       amount=amount, status="booked", tenant_id=lease["tenant"].id,
                                       unit_id=lease["unit"].id))
    _commit()


@pytest.fixture
def owner(client):
    headers = _user("owner")
    assert client.post(f"{API}/settings/base-rates", headers=headers,
                       json={"valid_from": "2026-01-01", "rate_percent": 1.27}).status_code == 201
    return headers


def _preview(client, headers, as_of, **scope):
    response = client.post(f"{API}/preview", headers=headers, json={"as_of": as_of, **scope})
    assert response.status_code == 200, response.text
    return response.json()


def _run(client, headers, contract_id, as_of, key=None):
    preview = _preview(client, headers, as_of, contract_id=contract_id)
    response = client.post(f"{API}/runs", headers=headers, json={
        "contract_id": contract_id, "as_of": as_of, "command_key": key or f"run-{contract_id}-{as_of}",
        "preview_hash": preview["preview_hash"]})
    assert response.status_code == 201, response.text
    return response.json()


def _finalize(client, headers, letter_id, key=None, channel="letter"):
    letter = client.get(f"{API}/letters/{letter_id}", headers=headers).json()
    return client.post(f"{API}/letters/{letter_id}/finalize", headers=headers, json={
        "command_key": key or f"fin-{letter_id}", "draft_hash": letter["draft_hash"], "confirmed": True,
        "channel": channel})


def _letter(client, headers, contract_id, as_of):
    run = _run(client, headers, contract_id, as_of)
    [letter] = run["letters"]
    response = _finalize(client, headers, letter["id"])
    assert response.status_code == 200, response.text
    return response.json()


def _dunning_receivables(lease):
    return sorted((r.description or "", r.amount_due) for r in store.list_receivables()
                  if r.contract_id == lease["contract"].id and r.statement_id is None)


# ─── stages, timing, fees, interest ──────────────────────────────────────────

def test_stages_follow_their_timing_and_charge_fee_and_interest_from_stage_two(client, owner):
    lease = _lease()
    contract = lease["contract"].id
    entry = _preview(client, owner, "2026-07-09", contract_id=contract)["entries"][0]
    assert (entry["status"], entry["next_stage"], entry["due_on"]) == ("not_yet", 1, "2026-07-10")

    preview = _preview(client, owner, "2026-07-10", contract_id=contract)
    entry = preview["entries"][0]
    assert entry["status"] == "due" and entry["next_stage_label"] == "Zahlungserinnerung"
    assert {k: entry["letter"][k] for k in ("principal", "fee", "interest", "total")} == {
        "principal": 1000.0, "fee": 0.0, "interest": 0.0, "total": 1000.0}
    assert _dunning_receivables(lease) == []          # a preview stores nothing
    first = _letter(client, owner, contract, "2026-07-10")
    assert (first["stage"], first["status"], first["payment_deadline"]) == (1, "final", "2026-07-24")
    assert first["reference"].startswith("M-2026-")

    entry = _preview(client, owner, "2026-07-24", contract_id=contract)["entries"][0]
    assert (entry["status"], entry["next_stage"], entry["due_on"]) == ("not_yet", 2, "2026-07-25")
    second = _preview(client, owner, "2026-07-25", contract_id=contract)["entries"][0]["letter"]
    # 1000 × (1.27 + 5) % × 22 days (4.–25.7.) / 365 = 3.779 → 3.78
    assert (second["fee"], second["interest"], second["total"]) == (2.5, 3.78, 1006.28)
    assert second["lines"][0]["interest_segments"][0]["days"] == 22

    letter = _letter(client, owner, contract, "2026-07-25")
    assert letter["stage"] == 2 and letter["total"] == 1006.28
    assert sorted(amount for _, amount in _dunning_receivables(lease)) == [2.5, 3.78]
    claims = client.get(f"{API}/contracts/{contract}", headers=owner, params={"as_of": "2026-07-26"}).json()["claims"]
    assert {c["description"] for c in claims if c["kind"] in ("fee", "interest")} == {
        f"Mahngebühr 1. Mahnung ({first['reference']})", f"Verzugszinsen bis 25.07.2026 ({first['reference']})"}
    third = _preview(client, owner, "2026-08-09", contract_id=contract)["entries"][0]["letter"]
    # earlier fee and interest are claimed again, interest only from the 26.7. on (no double charge)
    assert third["earlier_charges_total"] == 6.28 and third["fee"] == 5.0
    assert third["lines"][0]["interest_from"] == "2026-07-26"
    assert third["interest"] == 2.58                          # 1000 × 6.27 % × 15 / 365
    _letter(client, owner, contract, "2026-08-09")
    _letter(client, owner, contract, "2026-08-23")
    final = client.get(f"{API}/contracts/{contract}", headers=owner, params={"as_of": "2026-12-01"}).json()
    assert final["next"]["status"] == "final_stage" and final["cases"][0]["stage"] == 4


def test_stage_settings_are_configurable_and_installation_wide(client, owner):
    lease = _lease()
    stages = [{"stage": 1, "label": "Erinnerung", "days_after": 3, "fee": 1, "payment_deadline_days": 5,
               "charge_interest": True},
              {"stage": 2, "label": "Mahnung", "days_after": 10, "fee": 3.333, "payment_deadline_days": 7},
              {"stage": 3, "label": "Mahnung 2", "days_after": 10, "fee": 4, "payment_deadline_days": 7},
              {"stage": 4, "label": "Letzte", "days_after": 10, "fee": 6, "payment_deadline_days": 7}]
    saved = client.put(f"{API}/settings/stages", headers=owner, json={"stages": stages})
    assert saved.status_code == 200 and saved.json()["stages"][1]["fee"] == 3.33
    entry = _preview(client, owner, "2026-07-06", contract_id=lease["contract"].id)["entries"][0]
    assert entry["status"] == "due" and entry["letter"]["fee"] == 1.0 and entry["letter"]["interest"] == 0.52
    assert client.put(f"{API}/settings/stages", headers=owner, json={"stages": stages[:3]}).status_code == 422
    restricted = _user("nora", "verwalter", lease["portfolio"])
    assert client.put(f"{API}/settings/stages", headers=restricted, json={"stages": stages}).status_code == 403
    assert client.get(f"{API}/settings", headers=restricted).json()["stages"][0]["label"] == "Erinnerung"


def test_without_a_base_rate_no_interest_is_charged_and_it_is_said(client):
    headers = _user("owner")
    lease = _lease()
    _letter(client, headers, lease["contract"].id, "2026-07-10")
    letter = _preview(client, headers, "2026-07-25", contract_id=lease["contract"].id)["entries"][0]["letter"]
    assert letter["interest"] == 0.0 and letter["interest_missing_from"] == "2026-07-04"
    assert "kein Basiszinssatz" in letter["interest_note"]


# ─── payments, objections, disputes, blocks ──────────────────────────────────

def test_as_of_excludes_later_payments_and_reversals(client, owner):
    lease = _lease()
    contract = lease["contract"].id
    _pay(lease, "2026-07-20", 1000)
    before = _preview(client, owner, "2026-07-10", contract_id=contract)["entries"][0]
    assert before["status"] == "due" and before["letter"]["principal"] == 1000
    after = _preview(client, owner, "2026-07-20", contract_id=contract)["entries"][0]
    assert after["status"] == "nothing_due"
    _pay(lease, "2026-07-25", -1000)
    unchanged = _preview(client, owner, "2026-07-20", contract_id=contract)["entries"][0]
    assert unchanged["status"] == "nothing_due"
    reversed_payment = _preview(client, owner, "2026-07-25", contract_id=contract)["entries"][0]
    assert reversed_payment["status"] == "due" and reversed_payment["letter"]["principal"] == 1000


def test_draft_revalidation_does_not_count_future_bookings(client, owner, monkeypatch):
    from backend.services import dunning

    monkeypatch.setattr(dunning, "today", lambda: date(2026, 7, 15))
    lease = _lease()
    [draft] = _run(client, owner, lease["contract"].id, "2026-07-10")["letters"]
    _pay(lease, "2026-07-20", 1000)
    response = _finalize(client, owner, draft["id"])
    assert response.status_code == 200, response.text
    assert response.json()["principal"] == 1000


def test_a_payment_after_the_run_stops_the_draft_and_a_partial_one_reduces_it(client, owner):
    lease = _lease()
    contract = lease["contract"].id
    _letter(client, owner, contract, "2026-07-10")
    [draft] = _run(client, owner, contract, "2026-07-25")["letters"]
    assert draft["status"] == "draft" and _dunning_receivables(lease) == []
    _pay(lease, "2026-07-26", 400)
    refused = _finalize(client, owner, draft["id"])
    assert refused.status_code == 409 and "Zahlungen" in refused.json()["error"]["message"]
    refreshed = client.post(f"{API}/letters/{draft['id']}/refresh", headers=owner).json()
    assert (refreshed["principal"], refreshed["total"]) == (600.0, 606.28)   # interest up to the letter date
    assert _finalize(client, owner, draft["id"], key="fin-second").status_code == 200

    _pay(lease, "2026-07-30", 606.28)
    entry = _preview(client, owner, "2026-08-20", contract_id=contract)["entries"][0]
    assert entry["status"] == "nothing_due"
    case = client.get(f"{API}/contracts/{contract}", headers=owner, params={"as_of": "2026-08-20"}).json()["cases"][0]
    assert case["outstanding"] == 0.0
    result = client.post(f"{API}/cases/{case['id']}/result", headers=owner,
                         json={"result": "paid", "result_date": "2026-08-20", "reference": "Kontoauszug 8/26"})
    assert result.status_code == 200 and result.json()["result_label"] == "bezahlt"
    assert {r.status for r in store.list_receivables() if r.contract_id == contract} == {"paid"}


def test_an_objection_against_the_statement_pauses_the_back_payment_until_decided(client, owner):
    lease = _lease()
    period = store.create_billing_period(BillingPeriodCreate(property_id=lease["property"].id, label="NK 2025",
                                                             start_date=date(2025, 1, 1), end_date=date(2025, 12, 31),
                                                             status="finalized"))
    statement = store.create_utility_statement(UtilityStatementCreate(
        billing_period_id=period.id, contract_id=lease["contract"].id, unit_id=lease["unit"].id, total_cost=1350,
        advance_paid=1200, balance=150, status="finalized"))
    receivable = store.create_receivable(ReceivableCreate(contract_id=lease["contract"].id,
                                                          due_date=date(2026, 7, 15), amount_due=150,
                                                          statement_id=statement.id))
    store.create_receivable(ReceivableCreate(contract_id=lease["contract"].id, due_date=date(2026, 7, 3),
                                             amount_due=1000, description="Mietrückstand 07/2026"))
    objection = store.create_billing_objection(BillingObjectionCreate(
        billing_period_id=period.id, statement_id=statement.id, received_on=date(2026, 7, 20), reason="Heizkosten"))
    _commit()
    entry = _preview(client, owner, "2026-07-25", contract_id=lease["contract"].id)["entries"][0]
    assert [line["key"] for line in entry["letter"]["lines"]] == ["rent:2026-07"]
    reasons = {e["key"]: e["reason"] for e in entry["excluded"]}
    assert reasons[f"receivable:{receivable.id}"] == "objection"
    assert "manual" in reasons.values()          # never dunned twice next to the rent month
    store.update_billing_objection(objection.id, BillingObjectionCreate(
        **{**objection.model_dump(include=set(BillingObjectionCreate.model_fields)), "status": "resolved"}))
    _commit()
    entry = _preview(client, owner, "2026-07-25", contract_id=lease["contract"].id)["entries"][0]
    assert [line["key"] for line in entry["letter"]["lines"]] == ["rent:2026-07", f"receivable:{receivable.id}"]
    assert entry["letter"]["principal"] == 1150.0


def test_a_disputed_claim_waits_for_the_decision(client, owner):
    lease = _lease()
    contract = lease["contract"].id
    dispute = client.post(f"{API}/contracts/{contract}/disputes", headers=owner,
                          json={"claim_key": "rent:2026-07", "reason": "Mietminderung Heizung", "raised_on": "2026-07-08"})
    assert dispute.status_code == 201
    assert client.post(f"{API}/contracts/{contract}/disputes", headers=owner,
                       json={"claim_key": "rent:2030-01", "reason": "x"}).status_code == 422
    entry = _preview(client, owner, "2026-07-20", contract_id=contract)["entries"][0]
    assert entry["status"] == "nothing_due" and entry["excluded"][0]["reason"] == "dispute"
    client.post(f"{API}/disputes/{dispute.json()['id']}/decide", headers=owner, json={"decision": "rejected"})
    assert _preview(client, owner, "2026-07-20", contract_id=contract)["entries"][0]["status"] == "due"
    again = client.post(f"{API}/contracts/{contract}/disputes", headers=owner,
                        json={"claim_key": "rent:2026-07", "reason": "Minderung anerkannt"}).json()
    client.post(f"{API}/disputes/{again['id']}/decide", headers=owner, json={"decision": "upheld"})
    entry = _preview(client, owner, "2026-07-20", contract_id=contract)["entries"][0]
    assert entry["status"] == "nothing_due" and entry["excluded"][0]["reason"] == "dispute_upheld"


def test_a_dunning_block_holds_runs_and_finalization_until_lifted(client, owner):
    lease = _lease(end=None)
    contract = lease["contract"].id
    [draft] = _run(client, owner, contract, "2026-07-10")["letters"]
    block = client.post(f"{API}/contracts/{contract}/blocks", headers=owner,
                        json={"reason": "Ratenzahlung vereinbart", "blocked_until": "2030-01-31"})
    assert block.status_code == 201
    assert client.post(f"{API}/contracts/{contract}/blocks", headers=owner,
                       json={"reason": "x", "blocked_until": "2020-01-01"}).status_code == 422
    refused = _finalize(client, owner, draft["id"])
    assert refused.status_code == 409 and "Mahnsperre" in refused.json()["error"]["message"]
    client.post(f"{API}/letters/{draft['id']}/cancel", headers=owner, json={"reason": "Sperre"})
    entry = _preview(client, owner, "2026-08-20", contract_id=contract)["entries"][0]
    assert entry["status"] == "blocked" and "Ratenzahlung" in entry["reason"]
    assert client.post(f"{API}/blocks/{block.json()['id']}/lift", headers=owner, json={"note": "Rate geplatzt"}
                       ).status_code == 200
    entry = _preview(client, owner, "2026-08-20", contract_id=contract)["entries"][0]
    assert entry["status"] == "due" and entry["next_stage"] == 1


# ─── finalization, immutability, outbox ──────────────────────────────────────

def test_finalizing_is_idempotent_per_command_key_and_the_letter_stays_as_archived(client, owner):
    lease = _lease()
    contract = lease["contract"].id
    _letter(client, owner, contract, "2026-07-10")
    [draft] = _run(client, owner, contract, "2026-07-25")["letters"]
    letter = client.get(f"{API}/letters/{draft['id']}", headers=owner).json()
    preview_pdf = client.get(f"{API}/letters/{draft['id']}/pdf", headers=owner)
    assert preview_pdf.headers["x-archived-original"] == "false"
    body = {"command_key": "fin-stable-1", "draft_hash": letter["draft_hash"], "confirmed": True}
    assert client.post(f"{API}/letters/{draft['id']}/finalize", headers=owner,
                       json={**body, "confirmed": False}).status_code == 422
    first = client.post(f"{API}/letters/{draft['id']}/finalize", headers=owner, json=body)
    again = client.post(f"{API}/letters/{draft['id']}/finalize", headers=owner, json=body)
    assert first.status_code == again.status_code == 200 and first.json()["document_id"] == again.json()["document_id"]
    assert len(_dunning_receivables(lease)) == 2                       # fee and interest once
    other = client.post(f"{API}/letters/{draft['id']}/finalize", headers=owner,
                        json={**body, "command_key": "fin-stable-2"})
    assert other.status_code == 409 and len(_dunning_receivables(lease)) == 2

    original = client.get(f"{API}/letters/{draft['id']}/pdf", headers=owner)
    assert original.headers["x-archived-original"] == "true" and original.content == preview_pdf.content
    by_upload = client.get(first.json()["original_url"], headers=owner)     # the document's file: the original
    assert by_upload.status_code == 200 and by_upload.content == original.content
    for action, payload in (("cancel", {"reason": "x"}), ("refresh", None)):
        assert client.post(f"{API}/letters/{draft['id']}/{action}", headers=owner, json=payload).status_code == 409
    document = store.get_document(first.json()["document_id"])
    assert document.document_type == "dunning_letter" and document.contract_id == contract


def test_the_outbox_prepares_letters_and_email_drafts_but_sends_nothing(client, owner):
    lease = _lease()
    [draft] = _run(client, owner, lease["contract"].id, "2026-07-10")["letters"]
    queued = client.get(f"{API}/outbox", headers=owner, params={"status": "queued"}).json()
    assert queued["total"] == 1 and queued["items"][0]["letter"]["status"] == "draft"
    finalized = _finalize(client, owner, draft["id"], channel="email").json()
    entry = finalized["outbox"]
    assert (entry["status"], entry["channel"], entry["recipient_email"]) == ("ready", "email", "max@example.com")
    eml = client.get(f"{API}/outbox/{entry['id']}/eml", headers=owner)
    assert eml.status_code == 200 and b"X-Unsent: 1" in eml.content and b"application/pdf" in eml.content
    assert client.post(f"{API}/outbox/{entry['id']}/mark-sent", headers=owner,
                       json={"sent_on": "2026-07-01", "via": "E-Mail"}).status_code == 422
    sent = client.post(f"{API}/outbox/{entry['id']}/mark-sent", headers=owner,
                       json={"sent_on": "2026-07-11", "via": "E-Mail aus Outlook"})
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    assert client.post(f"{API}/outbox/{entry['id']}/mark-sent", headers=owner,
                       json={"sent_on": "2026-07-11", "via": "x"}).status_code == 409

    no_mail = _lease("Süd", "V-2", email=None)
    [draft] = _run(client, owner, no_mail["contract"].id, "2026-07-10")["letters"]
    refused = _finalize(client, owner, draft["id"], channel="email")
    assert refused.status_code == 409 and "E-Mail-Adresse" in refused.json()["error"]["message"]
    assert client.get(f"{API}/letters/{draft['id']}", headers=owner).json()["status"] == "draft"


def test_results_close_the_case_and_written_off_claims_are_not_dunned_again(client, owner):
    lease = _lease()
    contract = lease["contract"].id
    _letter(client, owner, contract, "2026-07-10")
    letter = _letter(client, owner, contract, "2026-07-25")
    case_id = letter["case_id"]
    refused = client.post(f"{API}/cases/{case_id}/result", headers=owner,
                          json={"result": "paid", "result_date": "2026-08-01", "reference": "x"})
    assert refused.status_code == 409
    assert client.post(f"{API}/cases/{case_id}/result", headers=owner, json={
        "result": "partially_paid", "result_date": "2026-08-01", "reference": "x"}).status_code == 409
    closed = client.post(f"{API}/cases/{case_id}/result", headers=owner, json={
        "result": "written_off", "result_date": "2026-08-01", "reference": "Beschluss 3/26", "note": "uneinbringlich"})
    assert closed.status_code == 200 and closed.json()["result_outstanding"] == 1006.28
    assert {r.status for r in store.list_receivables() if r.contract_id == contract} == {"cancelled"}
    entry = _preview(client, owner, "2026-09-01", contract_id=contract)["entries"][0]
    assert entry["status"] == "nothing_due" and entry["excluded"][0]["reason"] == "closed_case"
    assert client.post(f"{API}/cases/{case_id}/result", headers=owner, json={
        "result": "handed_over", "result_date": "2026-08-01", "reference": "x"}).status_code == 409


# ─── replies and threads ─────────────────────────────────────────────────────

def test_replies_attach_only_by_an_explicit_reference(client, owner):
    one, two = _lease(), _lease("Süd", "V-2")
    first = _letter(client, owner, one["contract"].id, "2026-07-10")
    second = _letter(client, owner, two["contract"].id, "2026-07-10")
    ref = first["reference"]

    def reply(**body):
        response = client.post(f"{API}/replies", headers=owner, json={"received_on": "2026-07-15", **body})
        assert response.status_code == 201, response.text
        return response.json()

    assigned = reply(body=f"Zu Ihrem Zeichen {ref.lower()}: ich zahle Freitag.", sender="Mieter Süd")
    assert (assigned["status"], assigned["case_id"], assigned["case_reference"]) == ("assigned", first["case_id"], ref)
    # the sender's name alone never decides: here it even names the other tenant
    assert reply(body="Ich zahle Freitag.", sender="Mieter Nord")["review_reason"] == "no_reference"
    assert reply(body="Betrifft M-2026-00000000")["review_reason"] == "unknown_reference"
    ambiguous = reply(body=f"Betrifft {ref} und {second['reference']}")
    assert (ambiguous["status"], ambiguous["review_reason"], ambiguous["case_id"]) == ("review", "ambiguous", None)

    review = client.get(f"{API}/replies", headers=owner).json()
    assert review["total"] == 3
    manual = client.post(f"{API}/replies/{ambiguous['id']}/assign", headers=owner,
                         json={"case_id": second["case_id"]}).json()
    assert manual["status"] == "assigned" and manual["case_reference"] == second["reference"]
    assert client.post(f"{API}/replies/{ambiguous['id']}/assign", headers=owner,
                       json={"case_id": first["case_id"]}).status_code == 409
    undone = client.post(f"{API}/replies/{ambiguous['id']}/unassign", headers=owner).json()
    assert undone["status"] == "review" and undone["review_reason"] == "unassigned"
    assert client.post(f"{API}/replies/{undone['id']}/dismiss", headers=owner).json()["status"] == "dismissed"
    thread = client.get(f"{API}/cases/{second['case_id']}/timeline", headers=owner).json()
    assert [e["kind"] for e in thread["items"]][-2:] == ["reply", "reply_unassigned"]
    phone = reply(body="Anruf: zahlt nächste Woche", channel="phone")
    by_reference = client.post(f"{API}/replies/{phone['id']}/assign", headers=owner, json={"reference": ref.lower()})
    assert by_reference.status_code == 200 and by_reference.json()["case_id"] == first["case_id"]
    assert client.post(f"{API}/replies/{phone['id']}/assign", headers=owner, json={}).status_code in (409, 422)


def test_timeline_preserves_write_order_when_the_clock_does_not_advance(client, owner, monkeypatch):
    from backend.services import dunning

    lease = _lease()
    letter = _letter(client, owner, lease["contract"].id, "2026-07-10")
    monkeypatch.setattr(dunning, "now", lambda: datetime(2030, 1, 1))
    for text in ("Erster Vermerk", "Zweiter Vermerk", "Dritter Vermerk"):
        response = client.post(f"{API}/cases/{letter['case_id']}/notes", headers=owner, json={"text": text})
        assert response.status_code == 201, response.text
    entries = client.get(f"{API}/cases/{letter['case_id']}/timeline", headers=owner).json()["items"]
    notes = [entry for entry in entries if entry["kind"] == "note"]
    assert [entry["summary"] for entry in notes] == ["Erster Vermerk", "Zweiter Vermerk", "Dritter Vermerk"]
    assert notes[0]["at"] < notes[1]["at"] < notes[2]["at"]


def test_a_long_thread_is_read_completely_page_by_page(client, owner):
    lease = _lease()
    letter = _letter(client, owner, lease["contract"].id, "2026-07-10")
    for number in range(230):
        assert client.post(f"{API}/replies", headers=owner, json={
            "body": f"Nachricht {number} zu {letter['reference']}", "received_on": "2026-07-15"}).status_code == 201
    seen, after, pages = [], None, 0
    while True:
        params = {"limit": 100, **({"after": after} if after else {})}
        page = client.get(f"{API}/cases/{letter['case_id']}/timeline", headers=owner, params=params).json()
        seen += page["items"]
        pages += 1
        if not page["has_more"]:
            break
        after = page["next_after"]
    assert pages == 3 and len(seen) == page["total"] == 233          # opened, drafted, finalized + 230
    assert len({e["id"] for e in seen}) == 233
    bodies = [e["reply"]["body"] for e in seen if e.get("reply")]
    assert bodies == [f"Nachricht {n} zu {letter['reference']}" for n in range(230)]
    assert client.get(f"{API}/cases/{letter['case_id']}/timeline", headers=owner,
                      params={"after": "kaputt"}).status_code == 422


# ─── the job proposes, once ──────────────────────────────────────────────────

def _jobs():
    if hasattr(store, "db"):
        from backend.db.session import engine

        return SqlJobStore(engine)
    return MemoryJobStore(store_factory=lambda: store)


def _escalate(jobs, as_of):
    jobs.enqueue(ESCALATION_KIND, f"{ESCALATION_KIND}@{as_of}", {"as_of": as_of})
    return JobRunner(jobs, {ESCALATION_KIND: escalation_handler}).run_until_idle()


def _proposals():
    return sorted(n.title for n in store.list_notifications() if n.notification_type == "dunning_proposal")


def test_the_escalation_job_proposes_each_due_stage_once_and_never_sends(client, owner):
    lease = _lease()
    _lease("Süd", "V-2")
    _commit()
    jobs = _jobs()
    runs = _escalate(jobs, "2026-07-09")
    assert runs[0].status == "succeeded" and runs[0].progress["dunning_contracts"] == 2 and _proposals() == []
    _escalate(jobs, "2026-07-10")
    _escalate(jobs, "2026-07-11")
    assert _proposals() == ["Mahnvorschlag: Zahlungserinnerung – Vertrag V-1",
                            "Mahnvorschlag: Zahlungserinnerung – Vertrag V-2"]
    # the amounts read as German money
    content = next(n.content for n in store.list_notifications() if n.title.endswith("Vertrag V-1"))
    assert re.search(r"über \d{1,3}(\.\d{3})*,\d{2} € \(Hauptforderung \d{1,3}(\.\d{3})*,\d{2} €\)", content), content
    assert client.get(f"{API}/overview", headers=owner).json()["counts"]["drafts"] == 0     # nothing created

    _letter(client, owner, lease["contract"].id, "2026-07-12")
    _escalate(jobs, "2026-07-27")
    _escalate(jobs, "2026-07-28")
    assert _proposals().count("Mahnvorschlag: 1. Mahnung – Vertrag V-1") == 1
    assert len(_proposals()) == 3


# ─── roles and portfolios ────────────────────────────────────────────────────

def test_bookkeeping_runs_dunning_technicians_and_readers_cannot(client, owner):
    lease = _lease()
    contract = lease["contract"].id
    for role in ("techniker", "readonly"):
        headers = _user(role, role)
        assert client.post(f"{API}/preview", headers=headers, json={"contract_id": contract}).status_code == 403
        assert client.post(f"{API}/replies", headers=headers, json={"body": "x"}).status_code == 403
    clerk = auth.register_user("clerk", "clerk@example.com", "Clerk", "Secret123", "buchhaltung")
    [draft] = _run(client, _bearer(clerk), contract, "2026-07-10")["letters"]
    auth.update_user(clerk.id, {"role": "techniker"})             # rights taken away before finalizing
    assert _finalize(client, _bearer(clerk), draft["id"]).status_code == 403
    assert client.get(f"{API}/letters/{draft['id']}", headers=owner).json()["status"] == "draft"
    auth.update_user(clerk.id, {"role": "buchhaltung"})
    assert _finalize(client, _bearer(clerk), draft["id"]).status_code == 200


def test_a_restricted_account_sees_and_changes_only_its_portfolios(client, owner):
    north, south = _lease(), _lease("Süd", "V-2")
    letter_n = _letter(client, owner, north["contract"].id, "2026-07-10")
    letter_s = _letter(client, owner, south["contract"].id, "2026-07-10")
    staff = _user("nora", "buchhaltung", north["portfolio"])
    overview = client.get(f"{API}/overview", headers=staff).json()
    assert [row["reference"] for row in overview["items"]] == [letter_n["reference"]]
    assert overview["counts"]["open_cases"] == 1
    assert client.get(f"{API}/outbox", headers=staff).json()["total"] == 1
    for path in (f"/contracts/{south['contract'].id}", f"/letters/{letter_s['id']}",
                 f"/letters/{letter_s['id']}/pdf", f"/cases/{letter_s['case_id']}/timeline"):
        assert client.get(API + path, headers=staff).status_code == 404, path
    assert client.get(letter_s["original_url"], headers=staff).status_code == 404
    assert client.post(f"{API}/preview", headers=staff, json={"contract_id": south["contract"].id}).status_code == 404
    assert client.post(f"{API}/preview", headers=staff,
                       json={"portfolio_id": south["portfolio"].id}).status_code == 404
    assert client.post(f"{API}/cases/{letter_s['case_id']}/result", headers=staff, json={
        "result": "written_off", "result_date": "2026-08-01", "reference": "x"}).status_code == 404
    foreign = client.post(f"{API}/replies", headers=staff, json={"body": f"Betrifft {letter_s['reference']}"}).json()
    assert foreign["review_reason"] == "unknown_reference"
    assert client.post(f"{API}/replies/{foreign['id']}/assign", headers=staff,
                       json={"case_id": letter_s["case_id"]}).status_code == 404
    assert client.get(f"{API}/replies", headers=owner).json()["total"] == 1      # the owner sees it to review
    own = _preview(client, staff, "2026-07-25", portfolio_id=north["portfolio"].id)
    assert [e["contract_id"] for e in own["entries"]] == [north["contract"].id]
    assert client.post(f"{API}/runs", headers=staff, json={
        "portfolio_id": north["portfolio"].id, "as_of": "2026-07-25", "command_key": "nora-run-1",
        "preview_hash": own["preview_hash"]}).status_code == 201


def test_a_portfolio_run_drafts_one_letter_per_due_contract_and_repeats_safely(client, owner):
    lease = _lease(end=None)
    payer = store.create_tenant(TenantCreate(full_name="Pünktlich"))
    unit = store.create_unit(UnitCreate(property_id=lease["property"].id, label="W2", unit_type="residential",
                                        cold_rent=500))
    second_contract = store.create_contract(ContractCreate(
        contract_number="V-1b", property_id=lease["property"].id, unit_id=unit.id, tenant_id=payer.id,
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 31)))
    store.create_booking(BookingCreate(account_id=lease["account"].id, booking_date=date(2026, 7, 2), amount=500,
                                       status="booked", tenant_id=payer.id, unit_id=unit.id))
    _commit()
    preview = _preview(client, owner, "2026-07-10", portfolio_id=lease["portfolio"].id)
    assert {e["contract_number"]: e["status"] for e in preview["entries"]} == {"V-1": "due", "V-1b": "nothing_due"}
    body = {"portfolio_id": lease["portfolio"].id, "as_of": "2026-07-10", "command_key": "portfolio-1",
            "preview_hash": preview["preview_hash"]}
    run = client.post(f"{API}/runs", headers=owner, json=body).json()
    assert [letter["contract_id"] for letter in run["letters"]] == [lease["contract"].id]
    assert run["summary"]["skipped"] == {"nothing_due": 1}
    assert client.post(f"{API}/runs", headers=owner, json=body).json()["id"] == run["id"]   # same command
    assert client.post(f"{API}/runs", headers=owner, json={**body, "as_of": "2026-07-11"}).status_code == 409
    stale = client.post(f"{API}/runs", headers=owner, json={**body, "command_key": "portfolio-2"})
    assert stale.status_code == 409          # the draft exists now: the preview changed
    assert second_contract.id


# ─── snapshot, DSGVO ─────────────────────────────────────────────────────────

def test_snapshots_and_the_data_access_export_carry_the_dunning_file(client, owner):
    lease = _lease()
    letter = _letter(client, owner, lease["contract"].id, "2026-07-10")
    client.post(f"{API}/replies", headers=owner, json={"body": f"Zu {letter['reference']}"})
    client.post(f"{API}/contracts/{lease['contract'].id}/blocks", headers=owner,
                json={"reason": "Urlaub", "blocked_until": "2030-01-01"})
    pdf = client.get(f"{API}/letters/{letter['id']}/pdf", headers=owner).content
    data = export_snapshot(store)
    assert data["format_version"] >= 6
    assert {name: len(data[name]) for name in ("dunning_cases", "dunning_letters", "dunning_outbox",
                                               "dunning_replies", "dunning_blocks", "dunning_base_rates")} == {
        "dunning_cases": 1, "dunning_letters": 1, "dunning_outbox": 1, "dunning_replies": 1, "dunning_blocks": 1,
        "dunning_base_rates": 1}
    assert [o["metadata_snapshot"]["document_type"] for o in data["document_originals"]] == ["dunning_letter"]
    timeline = client.get(f"{API}/cases/{letter['case_id']}/timeline", headers=owner).json()

    _reset()
    import_snapshot(store, data, replace=True)
    restored = client.get(f"{API}/letters/{letter['id']}/pdf", headers=owner)
    assert restored.headers["x-archived-original"] == "true"
    assert hashlib.sha256(restored.content).hexdigest() == hashlib.sha256(pdf).hexdigest()
    assert client.get(f"{API}/cases/{letter['case_id']}/timeline", headers=owner).json()["items"] == timeline["items"]

    export = client.get(f"/api/v1/admin/dsgvo/tenant/{lease['tenant'].id}/export", headers=owner).json()
    assert {name: len(export[name]) for name in ("dunning_cases", "dunning_letters", "dunning_replies",
                                                 "dunning_blocks", "dunning_events")} == {
        "dunning_cases": 1, "dunning_letters": 1, "dunning_replies": 1, "dunning_blocks": 1, "dunning_events": 5}


def _clear_letterhead():
    if hasattr(store, "db"):
        store.db.rollback()
        with store.db.get_bind().connect() as connection, connection.begin():
            connection.exec_driver_sql("DELETE FROM daily_setting_rules WHERE key LIKE 'document_%'")
    else:
        store.__dict__.pop("_daily_rules", None)


def test_letters_carry_the_letterhead_and_a_changed_letterhead_asks_for_a_recalculation(client, owner):
    from io import BytesIO
    from uuid import uuid4

    import pdfplumber

    from backend.domain.dunning_process import digest
    from backend.services import document_versions as archive
    from backend.services.dunning_letter_validation import (
        PDF_FORMAT_VERSION,
        DunningLetterValidationError,
        validate_dunning_letter_snapshot,
    )

    def setting(key, value, revision):
        response = client.put("/api/v1/auth/users/me/settings", headers=owner, json={
            "values": {key: value}, "base_revision": revision, "idempotency_key": str(uuid4()), "scope": "global"})
        assert response.status_code == 200, response.text

    lease = _lease()
    try:
        setting("document_bank", "Hausverwaltung Nord\nIBAN DE02 1203 0000 0000 2020 51", 0)
        [draft] = _run(client, owner, lease["contract"].id, "2026-07-10")["letters"]
        setting("document_contact", "Telefon 0341 123456", 0)
        refused = _finalize(client, owner, draft["id"])
        assert refused.status_code == 409 and "Briefkopf" in refused.json()["error"]["message"]
        assert client.post(f"{API}/letters/{draft['id']}/refresh", headers=owner).status_code == 200
        final = _finalize(client, owner, draft["id"], key="fin-letterhead")
        assert final.status_code == 200, final.text
        original = client.get(f"{API}/letters/{draft['id']}/pdf", headers=owner)
        with pdfplumber.open(BytesIO(original.content)) as document:
            text = "\n".join(page.extract_text() or "" for page in document.pages)
        assert "IBAN DE02 1203 0000 0000 2020 51" in text and "Telefon 0341 123456" in text
        assert "auf das Konto in der Fußzeile" in text

        with archive.work(store, auth.list_users()[0].id) as unit:
            row = archive.head(unit, final.json()["document_id"])
            assert row is not None
            snapshot = dict(row.metadata_snapshot)
        extension = snapshot["dunning_letter"]
        assert extension["content"]["format_version"] == "dunning-letter-pdf/2"
        values = {name: getattr(row, name) for name in ("actor_id", "request_sha256", "document_id", "contract_id")}
        # an original archived before the letterhead (format 1) stays valid
        older = {key: value for key, value in extension["content"].items() if key != "letterhead"}
        older["format_version"] = PDF_FORMAT_VERSION
        assert validate_dunning_letter_snapshot(values, {**snapshot, "dunning_letter": {
            **extension, "content": older, "draft_hash": digest(older)}})
        broken = {**older, "format_version": "dunning-letter-pdf/2"}
        with pytest.raises(DunningLetterValidationError):
            validate_dunning_letter_snapshot(values, {**snapshot, "dunning_letter": {
                **extension, "content": broken, "draft_hash": digest(broken)}})
    finally:
        _clear_letterhead()
