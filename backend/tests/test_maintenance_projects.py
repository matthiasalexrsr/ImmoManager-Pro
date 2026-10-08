"""Maintenance case as project file: dependencies without cycles, quote → order → change order →
invoice → payment without double counting, immutable protocols, roles and portfolio boundary.

Runs on the memory store and, with TEST_STORE_BACKEND=sql, on SQLite (PostgreSQL in
test_maintenance_projects_postgres.py).
"""

import hashlib
import os
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from archive_helpers import purge_originals
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.domain.project_costs import AllocationFacts, BookingFacts, InvoiceFacts, OrderFacts, roll_up
from backend.domain.project_graph import Edge, cycle_path, find_cycle, schedule_conflicts, topological_order
from backend.maintenance_models import QuoteDecision, WorkPackageCreate
from backend.models import AccountCreate, BookingCreate, ContactCreate, PortfolioCreate, PropertyCreate, UnitCreate
from backend.services.data_snapshot import clear_business_data, export_snapshot, import_snapshot

SQL = os.environ.get("TEST_STORE_BACKEND", "memory") == "sql"
API = "/api/v1"


# ─── the graph itself ────────────────────────────────────────────────────────

def test_cycle_detection_finds_direct_indirect_and_long_cycles():
    edges = [Edge("a", "b"), Edge("b", "c"), Edge("c", "d"), Edge("a", "e"), Edge("e", "d")]
    assert cycle_path(edges, Edge("b", "a")) == ["b", "a", "b"]                 # direct
    assert cycle_path(edges, Edge("c", "a")) == ["c", "a", "b", "c"]            # indirect
    assert cycle_path(edges, Edge("d", "a")) in (["d", "a", "b", "c", "d"], ["d", "a", "e", "d"])
    assert cycle_path(edges, Edge("x", "x")) == ["x", "x"]                       # itself
    assert cycle_path(edges, Edge("e", "b")) is None                             # a diamond is no cycle
    assert cycle_path(edges, Edge("d", "f")) is None
    chain = [Edge(str(i), str(i + 1)) for i in range(2000)]                      # no recursion limit
    assert cycle_path(chain, Edge("2000", "0")) == ["2000", *map(str, range(2001))]
    assert find_cycle(edges) is None
    assert find_cycle([*edges, Edge("d", "b")]) == ["b", "c", "d", "b"]


def test_topological_order_and_schedule_conflicts():
    edges = [Edge("a", "b"), Edge("b", "c"), Edge("a", "c")]
    assert topological_order(["c", "b", "a"], edges) == ["a", "b", "c"]
    assert topological_order(["a", "b"], [Edge("a", "b"), Edge("b", "a")]) is None
    found = schedule_conflicts(edges, {"b": date(2026, 3, 1), "c": date(2026, 3, 20)},
                               {"a": date(2026, 3, 5), "b": date(2026, 3, 10)})
    assert [(c.predecessor, c.successor) for c in found] == [("a", "b")]


def test_roll_up_counts_every_cent_once():
    """Two invoices, one booking paying both partly, a reversed booking, an over-allocation of an old booking."""
    t = date(2026, 1, 1)
    costs = roll_up(
        1500, [OrderFacts("o1", "active", Decimal("1190.00")), OrderFacts("o2", "cancelled", Decimal("500.00"))],
        [], [InvoiceFacts("i1", "o1", "open", Decimal("1000.00")), InvoiceFacts("i2", "o1", "open", Decimal("190.00"))],
        [AllocationFacts("a1", "i1", "b1", Decimal("900.00"), t), AllocationFacts("a2", "i2", "b1", Decimal("100.00"), t),
         AllocationFacts("a3", "i2", "b2", Decimal("90.00"), t),
         AllocationFacts("a0", "other", "b1", Decimal("50.00"), date(2025, 1, 1))],   # older, other project
        {"b1": BookingFacts("b1", Decimal("-1000.00"), Decimal("0")),
         "b2": BookingFacts("b2", Decimal("-90.00"), Decimal("90.00"))})              # fully reversed
    assert (costs.ordered, costs.invoiced) == (Decimal("1190.00"), Decimal("1190.00"))
    # b1 pays 1000: 50 went to the other project first, so 900 + 50 here; b2 was reversed
    assert costs.paid == Decimal("950.00")
    assert costs.invoice_paid == {"i1": Decimal("900.00"), "i2": Decimal("50.00")}
    assert {w["code"] for w in costs.warnings} == {"payment_reversed"}
    assert costs.as_json()["remaining_budget"] == 310.0


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean():
    purge_originals(store)
    clear_business_data(store)
    auth.clear_users()
    yield
    purge_originals(store)
    clear_business_data(store)
    auth.clear_users()


def _user(name, role="verwalter", portfolios=(), mode="all"):
    return auth.register_user(name, f"{name}@example.com", name.title(), "Secret123", role,
                              portfolio_access=mode, portfolio_ids=[p.id for p in portfolios])


def _client(user) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})


def _estate(name="Nord"):
    portfolio = store.create_portfolio(PortfolioCreate(name=f"Bestand {name}"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name=f"Haus {name}",
                                                property_type="residential", address_line="Bautzner Straße 61",
                                                postal_code="01099", city="Dresden"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="WE 3", unit_type="residential"))
    account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name=f"Konto {name}", account_type="bank"))
    return {"portfolio": portfolio, "property": prop, "unit": unit, "account": account}


@pytest.fixture
def estate():
    return _estate()


@pytest.fixture
def owner():
    return _client(_user("owner", "eigentuemer"))


@pytest.fixture
def roofer():
    return store.create_contact(ContactCreate(contact_type="supplier", company_name="Dach Müller GmbH",
                                              phone="0351 123"))


def _ok(response, code=200):
    assert response.status_code == code, response.text
    return response.json() if response.content else None


def _case(client, estate, **extra):
    return _ok(client.post(f"{API}/maintenance", json={
        "property_id": estate["property"].id, "unit_id": estate["unit"].id, "title": "Dachschaden nach Sturm",
        "category": "Dach", **extra}), 201)


def _project(client, case_id):
    return _ok(client.get(f"{API}/maintenance/{case_id}/project"))


def _package(client, case_id, title, **extra):
    return _ok(client.post(f"{API}/maintenance/{case_id}/work-packages", json={"title": title, **extra}), 201)


def _depend(client, case_id, before, after):
    return client.post(f"{API}/maintenance/{case_id}/dependencies",
                       json={"predecessor_id": before["id"], "successor_id": after["id"]})


def _booking(estate, amount, **extra):
    return store.create_booking(BookingCreate(account_id=estate["account"].id, property_id=estate["property"].id,
                                              booking_date=date(2026, 5, 2), amount=amount, **extra))


# ─── dependencies ────────────────────────────────────────────────────────────

def test_dependencies_refuse_direct_and_indirect_cycles_with_a_german_message(owner, estate):
    case = _case(owner, estate)
    a, b, c, d = (_package(owner, case["id"], title) for title in ("Gerüst", "Dach decken", "Dachrinne", "Abbau"))
    for before, after in ((a, b), (b, c), (c, d), (a, d)):
        _ok(_depend(owner, case["id"], before, after), 201)

    direct = _depend(owner, case["id"], b, a)
    assert direct.status_code == 409 and "Kreis" in direct.json()["error"]["message"]
    indirect = _depend(owner, case["id"], d, a)
    detail = indirect.json()["error"]["message"]
    assert indirect.status_code == 409
    assert detail.startswith("Abhängigkeit abgelehnt: Sie würde einen Kreis bilden („Abbau“ → „Gerüst“")
    assert "zirkulär" in detail
    assert "selbst" in _depend(owner, case["id"], a, a).json()["error"]["message"]
    assert _depend(owner, case["id"], a, b).status_code == 409                # already there
    other = _case(owner, estate, title="Anderer Fall")
    foreign = _package(owner, other["id"], "Fremd")
    assert _depend(owner, case["id"], a, foreign).status_code == 404         # never across projects

    project = _project(owner, case["id"])
    assert [wp["title"] for wp in project["work_packages"]] == ["Gerüst", "Dach decken", "Dachrinne", "Abbau"]
    assert len(project["dependencies"]) == 4
    by_title = {wp["title"]: wp for wp in project["work_packages"]}
    assert by_title["Abbau"]["blocked_by"] == sorted([c["id"], a["id"]]) or \
        set(by_title["Abbau"]["blocked_by"]) == {c["id"], a["id"]}


def test_work_follows_the_dependencies(owner, estate):
    case = _case(owner, estate)
    a, b = _package(owner, case["id"], "Gerüst"), _package(owner, case["id"], "Dach decken")
    _ok(_depend(owner, case["id"], a, b), 201)
    path = f"{API}/maintenance/{case['id']}/work-packages"

    early = owner.patch(f"{path}/{b['id']}", json={"status": "in_progress"})
    assert early.status_code == 409 and "erst beginnen" in early.json()["error"]["message"]
    _ok(owner.patch(f"{path}/{a['id']}", json={"status": "in_progress"}))
    assert _project(owner, case["id"])["case"]["status"] == "in_progress"      # work began
    _ok(owner.patch(f"{path}/{a['id']}", json={"status": "done"}))
    _ok(owner.patch(f"{path}/{b['id']}", json={"status": "in_progress"}))
    reopen = owner.patch(f"{path}/{a['id']}", json={"status": "in_progress"})
    assert reopen.status_code == 409 and "wieder geöffnet" in reopen.json()["error"]["message"]
    # a dependency that contradicts what already happened
    c = _package(owner, case["id"], "Nacharbeit")
    assert _depend(owner, case["id"], c, b).status_code == 409
    milestone = _package(owner, case["id"], "Abnahme", kind="milestone")
    assert owner.patch(f"{path}/{milestone['id']}", json={"status": "in_progress"}).status_code == 409


def test_planned_dates_against_dependencies_are_reported(owner, estate):
    case = _case(owner, estate)
    a = _package(owner, case["id"], "Gerüst", planned_start="2026-03-01", planned_end="2026-03-10")
    b = _package(owner, case["id"], "Dach", planned_start="2026-03-05", planned_end="2026-03-20")
    _ok(_depend(owner, case["id"], a, b), 201)
    conflicts = _project(owner, case["id"])["schedule_conflicts"]
    assert len(conflicts) == 1 and "05.03.2026" in conflicts[0]["message"]
    assert owner.post(f"{API}/maintenance/{case['id']}/work-packages",
                      json={"title": "X", "planned_start": "2026-03-05", "planned_end": "2026-03-01"}).status_code == 422


# ─── quote → order → change order → invoice → payment ────────────────────────

def _quote(client, case_id, net, gross, **extra):
    return _ok(client.post(f"{API}/maintenance/{case_id}/quotes", json={
        "quote_date": "2026-04-01", "net_amount": net, "gross_amount": gross, **extra}), 201)


def test_quote_order_change_order_invoice_payment_flow_and_costs(owner, estate, roofer):
    case = _case(owner, estate, estimated_cost=1500)
    base = f"{API}/maintenance/{case['id']}"
    roof = _package(owner, case["id"], "Dach decken")
    chosen = _quote(owner, case["id"], 1000, 1190, contact_id=roofer.id, work_package_id=roof["id"],
                    valid_until="2026-05-01")
    assert chosen["supplier_name"] == "Dach Müller GmbH"
    rival = _quote(owner, case["id"], 1100, 1309, supplier_name="Dach Schulze", work_package_id=roof["id"])

    order = _ok(owner.post(f"{base}/quotes/{chosen['id']}/accept",
                           json={"order_number": "A-2026-7", "reject_competing": True}), 201)
    assert (order["gross_amount"], order["status"], order["quote_id"]) == (1190.0, "active", chosen["id"])
    assert owner.post(f"{base}/quotes/{chosen['id']}/accept", json={}).status_code == 409   # one order per quote
    assert owner.patch(f"{base}/quotes/{chosen['id']}", json={"net_amount": 1}).status_code == 409
    assert owner.delete(f"{base}/quotes/{chosen['id']}").status_code == 409
    project = _project(owner, case["id"])
    assert {q["id"]: q["status"] for q in project["quotes"]} == {chosen["id"]: "accepted", rival["id"]: "rejected"}
    assert project["case"]["status"] == "in_progress"
    assert [p["contact"]["name"] for p in project["participants"]] == ["Dach Müller GmbH"]
    assert project["work_packages"][0]["order_ids"] == [order["id"]]

    extra = _ok(owner.post(f"{base}/orders/{order['id']}/change-orders",
                           json={"title": "Zusätzliche Lattung", "net_amount": 200, "gross_amount": 238}), 201)
    less = _ok(owner.post(f"{base}/orders/{order['id']}/change-orders",
                          json={"title": "Entfall Schneefang", "net_amount": -50, "gross_amount": -59.5}), 201)
    costs = _ok(owner.get(f"{base}/costs"))
    assert (costs["ordered"], costs["pending_change_orders"]) == (1190.0, 178.5)
    _ok(owner.post(f"{base}/change-orders/{extra['id']}/approve", json={"note": "geprüft"}))
    _ok(owner.post(f"{base}/change-orders/{less['id']}/reject", json={}))
    assert owner.post(f"{base}/change-orders/{extra['id']}/approve", json={}).status_code == 409

    first = _ok(owner.post(f"{base}/orders/{order['id']}/invoices", json={"invoice": {
        "invoice_number": "R-1", "invoice_date": "2026-05-01", "net_amount": 1000, "gross_amount": 1190}}), 201)
    assert first["invoice"]["property_id"] == estate["property"].id
    assert first["invoice"]["supplier"] == "Dach Müller GmbH"
    second = _ok(owner.post(f"{API}/invoices", json={
        "property_id": estate["property"].id, "supplier": "Dach Müller GmbH", "invoice_date": "2026-05-20",
        "net_amount": 200, "vat_amount": 38, "gross_amount": 238}), 201)
    _ok(owner.post(f"{base}/orders/{order['id']}/invoices", json={"invoice_id": second["id"]}), 201)
    again = owner.post(f"{base}/orders/{order['id']}/invoices", json={"invoice_id": second["id"]})
    assert again.status_code == 409 and "nur einmal" in again.json()["error"]["message"]
    elsewhere = _ok(owner.post(f"{API}/invoices", json={
        "property_id": _estate("Süd")["property"].id, "supplier": "X", "invoice_date": "2026-05-20",
        "net_amount": 1, "gross_amount": 1.19}), 201)
    assert owner.post(f"{base}/orders/{order['id']}/invoices", json={"invoice_id": elsewhere["id"]}).status_code == 409

    b1 = _booking(estate, -1190, payment_text="Dach Müller R-1")
    b2 = _booking(estate, -500, payment_text="Dach Müller Abschlag")
    b3 = _booking(estate, -38)
    pay = f"{API}/invoices/{first['invoice']['id']}/payments"
    _ok(owner.post(pay, json={"booking_id": b1.id, "amount": 1190}), 201)
    assert owner.post(pay, json={"booking_id": b2.id, "amount": 1}).status_code == 409          # fully paid
    pay2 = f"{API}/invoices/{second['id']}/payments"
    assert owner.post(pay2, json={"booking_id": b1.id, "amount": 10}).status_code == 409        # booking used up
    _ok(owner.post(pay2, json={"booking_id": b2.id, "amount": 200}), 201)
    _ok(owner.post(pay2, json={"booking_id": b3.id, "amount": 38}), 201)
    income = _booking(estate, 300)
    assert owner.post(pay2, json={"booking_id": income.id, "amount": 1}).status_code == 409     # not an expense
    # the 38 € payment is reversed (Storno): it no longer pays
    _booking(estate, 38, reverses_booking_id=b3.id)

    costs = _ok(owner.get(f"{base}/costs"))
    invoices = [store.get_invoice(first["invoice"]["id"]), store.get_invoice(second["id"])]
    assert costs["ordered"] == 1428.0 == 1190 + 238
    assert costs["invoiced"] == float(sum(Decimal(str(i.gross_amount)) for i in invoices)) == 1428.0
    assert costs["paid"] == 1390.0                              # 1190 + 200; the reversed 38 does not count
    assert (costs["open_to_invoice"], costs["open_to_pay"], costs["remaining_budget"]) == (0.0, 38.0, 72.0)
    assert {w["code"] for w in costs["warnings"]} == {"payment_reversed"}
    project = _project(owner, case["id"])
    assert {row["invoice"]["id"]: row["paid"] for row in project["invoices"]} == {
        first["invoice"]["id"]: 1190.0, second["id"]: 200.0}
    assert project["orders"][0]["change_orders"][0]["status"] in ("approved", "rejected")

    # an invoice of a project order, a booking that pays one: not deleted by a single click
    assert owner.delete(f"{API}/invoices/{second['id']}").status_code == 409
    assert owner.delete(f"{API}/bookings/{b2.id}").status_code == 409
    assert owner.post(f"{base}/orders/{order['id']}/cancel", json={"note": "x"}).status_code == 409


def test_one_booking_paying_two_projects_is_counted_once(owner, estate):
    base_a, base_b = (f"{API}/maintenance/{_case(owner, estate, title=t)['id']}" for t in ("A", "B"))
    invoices = []
    for base, gross in ((base_a, 600), (base_b, 700)):
        quote = _ok(owner.post(f"{base}/quotes", json={"supplier_name": "Firma", "quote_date": "2026-04-01",
                                                       "net_amount": gross, "gross_amount": gross}), 201)
        order = _ok(owner.post(f"{base}/quotes/{quote['id']}/accept", json={}), 201)
        invoices.append(_ok(owner.post(f"{base}/orders/{order['id']}/invoices", json={"invoice": {
            "invoice_date": "2026-05-01", "net_amount": gross, "gross_amount": gross}}), 201)["invoice"])
    booking = _booking(estate, -1000)
    _ok(owner.post(f"{API}/invoices/{invoices[0]['id']}/payments", json={"booking_id": booking.id, "amount": 600}), 201)
    refused = owner.post(f"{API}/invoices/{invoices[1]['id']}/payments", json={"booking_id": booking.id, "amount": 401})
    assert refused.status_code == 409 and "400,00 €" in refused.json()["error"]["message"]
    _ok(owner.post(f"{API}/invoices/{invoices[1]['id']}/payments", json={"booking_id": booking.id, "amount": 400}), 201)
    paid = [_ok(owner.get(f"{base}/costs"))["paid"] for base in (base_a, base_b)]
    assert paid == [600.0, 400.0] and sum(paid) == 1000.0
    listing = _ok(owner.get(f"{API}/invoices/{invoices[1]['id']}/payments"))
    assert (listing["allocated"], listing["open"]) == (400.0, 300.0)


# ─── status workflow ─────────────────────────────────────────────────────────

def test_status_workflow_with_gates_and_history(owner, estate):
    case = _case(owner, estate)
    base = f"{API}/maintenance/{case['id']}"
    a = _package(owner, case["id"], "Gerüst")
    blocked = owner.post(f"{base}/transition", json={"status": "completed"})
    assert blocked.status_code == 409 and "„Gerüst“" in blocked.json()["error"]["message"]
    # the old endpoints pass the same gate
    payload = {"property_id": estate["property"].id, "title": "Dachschaden nach Sturm", "status": "completed"}
    assert owner.put(f"{base}", json=payload).status_code == 409
    assert owner.patch(f"{base}", json={"status": "completed"}).status_code == 409
    assert owner.post(f"{base}/transition", json={"status": "cancelled"}).status_code == 422     # reason needed
    _ok(owner.patch(f"{base}/work-packages/{a['id']}", json={"status": "done"}))
    _ok(owner.post(f"{base}/transition", json={"status": "completed"}))
    assert owner.post(f"{base}/transition", json={"status": "open"}).status_code == 409       # not a path
    assert owner.post(f"{base}/work-packages", json={"title": "Später"}).status_code == 409    # closed file
    _ok(owner.post(f"{base}/transition", json={"status": "in_progress", "reason": "Nacharbeit"}))
    history = _project(owner, case["id"])["history"]
    assert [(h["old_value"], h["new_value"]) for h in history] == [
        ("completed", "in_progress"), ("in_progress", "completed"), ("open", "in_progress"), (None, "open")]
    assert history[0]["reason"] == "Nacharbeit" and history[0]["changed_by_name"] == "Owner"


def test_existing_maintenance_api_stays_compatible(owner, estate):
    created = _case(owner, estate, priority="high", estimated_cost=250.5, contractor="Firma Alt")
    base = f"{API}/maintenance/{created['id']}"
    assert set(created) >= {"id", "property_id", "title", "status", "estimated_cost", "contractor", "appointment_at"}
    updated = _ok(owner.put(base, json={"property_id": estate["property"].id, "title": "Neu", "status": "done"}))
    assert (updated["title"], updated["status"], updated["contractor"]) == ("Neu", "done", None)
    patched = _ok(owner.patch(base, json={"status": "in_progress", "assignee": "Hausmeister"}))
    assert (patched["status"], patched["assignee"], patched["title"]) == ("in_progress", "Hausmeister", "Neu")
    assert owner.put(base, json={"property_id": "missing", "title": "X"}).status_code == 400
    assert owner.put(f"{API}/maintenance/missing", json={"property_id": estate["property"].id,
                                                          "title": "X"}).status_code == 404
    listed = _ok(owner.get(f"{API}/maintenance?property_id={estate['property'].id}"))
    assert [row["id"] for row in listed] == [created["id"]]
    assert [h["new_value"] for h in _project(owner, created["id"])["history"]] == ["in_progress", "done", "open"]
    appointment = _ok(owner.post(f"{base}/appointments", json={"title": "Begehung", "event_date": "2026-06-01",
                                                                "event_time": "09:30", "kind": "inspection"}), 201)
    events = _ok(owner.get(f"{API}/calendar?property_id={estate['property'].id}"))
    assert [e["id"] for e in events] == [appointment["event"]["id"]]
    _ok(owner.delete(base), 204)
    assert owner.get(base).status_code == 404
    assert _ok(owner.get(f"{API}/calendar?property_id={estate['property'].id}")) == []    # its appointments too


# ─── protocols ───────────────────────────────────────────────────────────────

def _photo(client, case_id, caption="Riss First"):
    image = PILImage.new("RGB", (64, 48), (180, 40, 40))
    data = BytesIO()
    image.save(data, format="PNG")
    return _ok(client.post(f"{API}/photos/upload", params={"entity_type": "maintenance", "entity_id": case_id,
                                                          "caption": caption},
                           files={"file": ("riss.png", data.getvalue(), "image/png")}), 201)


def _acceptance(client, estate, roofer):
    case = _case(client, estate)
    base = f"{API}/maintenance/{case['id']}"
    quote = _quote(client, case["id"], 1000, 1190, contact_id=roofer.id)
    order = _ok(client.post(f"{base}/quotes/{quote['id']}/accept", json={"order_number": "A-1"}), 201)
    photo = _photo(client, case["id"])
    draft = _ok(client.post(f"{base}/protocols", json={
        "protocol_type": "acceptance", "protocol_date": "2026-06-10", "participants": "Owner, Herr Müller",
        "result": "accepted_with_defects", "order_id": order["id"], "photo_ids": [photo["id"]],
        "defects": [{"title": "Riss im First", "location": "Nordseite", "severity": "major",
                     "due_date": "2026-07-01", "photo_ids": [photo["id"]]}]}), 201)
    return case, base, order, photo, draft


def test_protocol_is_archived_as_immutable_original(owner, estate, roofer):
    case, base, order, photo, draft = _acceptance(owner, estate, roofer)
    preview = owner.get(f"{base}/protocols/{draft['id']}/pdf")
    assert preview.status_code == 200 and preview.content.startswith(b"%PDF-")
    final = _ok(owner.post(f"{base}/protocols/{draft['id']}/finalize", json={"idempotency_key": "abnahme-0001"}))
    assert final["status"] == "final" and final["content_sha256"] and final["document_id"]
    again = _ok(owner.post(f"{base}/protocols/{draft['id']}/finalize", json={"idempotency_key": "abnahme-0001"}))
    assert again == final                                                   # a lost answer: the same result
    assert owner.post(f"{base}/protocols/{draft['id']}/finalize",
                      json={"idempotency_key": "abnahme-0002"}).status_code == 409

    pdf = owner.get(f"{base}/protocols/{draft['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    virtual = owner.get(final["file_url"])
    assert virtual.status_code == 200 and virtual.content == pdf.content
    document = store.get_document(final["document_id"])
    assert (document.document_type, document.property_id) == ("maintenance_protocol", estate["property"].id)
    assert hashlib.sha256(pdf.content).hexdigest() == _archived_sha(final["document_id"])

    # immutable: no edit, no delete, the case keeps its evidence
    assert owner.patch(f"{base}/protocols/{draft['id']}", json={"notes": "x"}).status_code == 409
    assert owner.delete(f"{base}/protocols/{draft['id']}").status_code == 409
    assert owner.delete(base).status_code == 409
    assert owner.delete(f"{API}/documents/{final['document_id']}").status_code == 409
    project = _project(owner, case["id"])
    assert project["protocols"][0]["integrity"] == "verified"
    assert project["orders"][0]["status"] == "completed"                  # the acceptance completes the order
    assert any(d["source"] == "protocol" for d in project["documents"])


def _archived_sha(document_id):
    from backend.services import document_versions as archive
    from backend.services.maintenance_projects import _plain

    with _plain(store) as unit:
        return archive.head(unit, document_id).sha256


def test_a_changed_final_protocol_is_detected_or_refused(owner, estate, roofer):
    case, base, _, _, draft = _acceptance(owner, estate, roofer)
    _ok(owner.post(f"{base}/protocols/{draft['id']}/finalize", json={"idempotency_key": "abnahme-0001"}))
    if SQL:
        import sqlalchemy as sa

        with pytest.raises(sa.exc.DBAPIError, match="immutable"):
            with store.db.get_bind().connect() as connection, connection.begin():
                connection.exec_driver_sql("UPDATE maintenance_protocols SET notes = 'nachträglich'")
        return
    protocol = store.maintenance_protocols[draft["id"]]
    store.maintenance_protocols[draft["id"]] = protocol.model_copy(update={"result": "accepted"})
    assert _project(owner, case["id"])["protocols"][0]["integrity"] == "mismatch"
    assert owner.get(f"{base}/protocols/{draft['id']}/pdf").status_code == 503


def test_protocol_rules_before_finalizing(owner, estate):
    case = _case(owner, estate)
    base = f"{API}/maintenance/{case['id']}"
    other = _photo(owner, _case(owner, estate, title="Anderer")["id"])
    assert owner.post(f"{base}/protocols", json={"protocol_date": "2026-06-10",
                                                 "photo_ids": [other["id"]]}).status_code == 422
    draft = _ok(owner.post(f"{base}/protocols", json={"protocol_date": "2026-06-10"}), 201)
    finalize = f"{base}/protocols/{draft['id']}/finalize"
    assert owner.post(finalize, json={"idempotency_key": "k-00000001"}).status_code == 422       # no result
    _ok(owner.patch(f"{base}/protocols/{draft['id']}", json={"result": "accepted_with_defects"}))
    assert owner.post(finalize, json={"idempotency_key": "k-00000001"}).status_code == 422       # no defect
    _ok(owner.patch(f"{base}/protocols/{draft['id']}", json={"result": "refused"}))
    assert owner.post(finalize, json={"idempotency_key": "k-00000001"}).status_code == 422       # no reason
    blocked = owner.post(f"{base}/transition", json={"status": "completed"})
    assert blocked.status_code == 409 and "Protokollentwürfe" in blocked.json()["error"]["message"]


# ─── roles ───────────────────────────────────────────────────────────────────

def test_technician_and_bookkeeping_permission_matrix(owner, estate, roofer):
    tech = _client(_user("tech", "techniker"))
    books = _client(_user("books", "buchhaltung"))
    reader = _client(_user("reader", "readonly"))
    case = _case(owner, estate)
    base = f"{API}/maintenance/{case['id']}"

    # the technician plans and documents the work on site ...
    wp = _ok(tech.post(f"{base}/work-packages", json={"title": "Gerüst"}), 201)
    _ok(tech.patch(f"{base}/work-packages/{wp['id']}", json={"status": "in_progress"}))
    _ok(tech.post(f"{base}/appointments", json={"title": "Begehung", "event_date": "2026-06-01"}), 201)
    _ok(tech.post(f"{base}/participants", json={"contact_id": roofer.id, "trade": "Dach"}), 201)
    quote = _ok(tech.post(f"{base}/quotes", json={"contact_id": roofer.id, "quote_date": "2026-04-01",
                                                  "net_amount": 100, "gross_amount": 119}), 201)
    # ... but does not award or cancel orders, decide change orders or touch invoices
    for path in (f"/quotes/{quote['id']}/accept", f"/quotes/{quote['id']}/reject"):
        assert tech.post(base + path, json={}).status_code == 403, path
    assert books.post(f"{base}/quotes/{quote['id']}/accept", json={}).status_code == 403
    order = _ok(owner.post(f"{base}/quotes/{quote['id']}/accept", json={}), 201)
    change = _ok(tech.post(f"{base}/orders/{order['id']}/change-orders",
                           json={"title": "Mehr", "net_amount": 10, "gross_amount": 11.9}), 201)
    for path in (f"/change-orders/{change['id']}/approve", f"/orders/{order['id']}/cancel",
                 f"/orders/{order['id']}/complete"):
        assert tech.post(base + path, json={"note": "x"}).status_code == 403, path
    invoice = {"invoice": {"invoice_date": "2026-05-01", "net_amount": 100, "gross_amount": 119}}
    assert tech.post(f"{base}/orders/{order['id']}/invoices", json=invoice).status_code == 403
    # bookkeeping links invoices and payments, but does not plan
    linked = _ok(books.post(f"{base}/orders/{order['id']}/invoices", json=invoice), 201)
    booking = _booking(estate, -119)
    pay = f"{API}/invoices/{linked['invoice']['id']}/payments"
    assert tech.post(pay, json={"booking_id": booking.id, "amount": 119}).status_code == 403
    _ok(books.post(pay, json={"booking_id": booking.id, "amount": 119}), 201)
    assert books.post(f"{base}/work-packages", json={"title": "X"}).status_code == 403
    # protocols: the technician writes and finalizes them
    draft = _ok(tech.post(f"{base}/protocols", json={"protocol_type": "inspection",
                                                     "protocol_date": "2026-06-10", "notes": "Begehung"}), 201)
    _ok(tech.post(f"{base}/protocols/{draft['id']}/finalize", json={"idempotency_key": "begehung-01"}))
    # read-only: reads, changes nothing
    assert reader.get(f"{base}/project").status_code == 200
    for path, body in ((f"{base}/work-packages", {"title": "X"}), (f"{base}/transition", {"status": "cancelled"})):
        assert reader.post(path, json=body).status_code == 403

    abilities = _ok(tech.get(f"{base}/project"))["abilities"]
    assert abilities["plan"] and abilities["finalize_protocols"] and abilities["record_quotes"]
    assert not abilities["decide_quotes"] and not abilities["link_invoices"] and not abilities["allocate_payments"]
    assert not abilities["decide_change_orders"] and not abilities["manage_orders"]
    assert _ok(books.get(f"{base}/project"))["abilities"]["link_invoices"]


def test_rights_are_checked_again_inside_the_transaction(owner, estate):
    """The middleware reads the role once; the unit re-reads the account under its lock."""
    from backend.services import maintenance_projects as service

    tech = _user("tech2", "techniker")
    case = _case(owner, estate)
    quote = _quote(owner, case["id"], 100, 119, supplier_name="Firma")
    with pytest.raises(HTTPException) as refused:
        service.accept_quote(store, case["id"], quote["id"], QuoteDecision(), tech.id)
    assert refused.value.status_code == 403
    auth.update_user(tech.id, {"is_active": False})
    with pytest.raises(HTTPException) as gone:
        service.add_work_package(store, case["id"], WorkPackageCreate(title="X"), tech.id)
    assert gone.value.status_code == 401
    assert _project(owner, case["id"])["work_packages"] == []


# ─── portfolio boundary ──────────────────────────────────────────────────────

def test_restricted_account_sees_and_changes_only_projects_of_its_portfolios(owner, estate, roofer):
    south = _estate("Süd")
    case_north = _case(owner, estate)
    case_south = _case(owner, south, title="Wasserschaden Süd")
    quote = _quote(owner, case_south["id"], 100, 119, contact_id=roofer.id)
    south_booking = _booking(south, -119)
    staff = _client(_user("staff", "verwalter", [estate["portfolio"]], mode="selected"))

    assert staff.get(f"{API}/maintenance/{case_south['id']}/project").status_code == 404
    assert staff.get(f"{API}/maintenance/{case_south['id']}/costs").status_code == 404
    assert staff.post(f"{API}/maintenance/{case_south['id']}/work-packages", json={"title": "X"}).status_code == 404
    assert staff.post(f"{API}/maintenance/{case_south['id']}/quotes/{quote['id']}/accept",
                      json={}).status_code == 404
    assert [row["id"] for row in _ok(staff.get(f"{API}/maintenance"))] == [case_north["id"]]
    # its own projects work normally, with the shared address book
    base = f"{API}/maintenance/{case_north['id']}"
    _ok(staff.post(f"{base}/participants", json={"contact_id": roofer.id}), 201)
    own = _quote(staff, case_north["id"], 100, 119, contact_id=roofer.id)
    order = _ok(staff.post(f"{base}/quotes/{own['id']}/accept", json={}), 201)
    linked = _ok(staff.post(f"{base}/orders/{order['id']}/invoices", json={"invoice": {
        "invoice_date": "2026-05-01", "net_amount": 100, "gross_amount": 119}}), 201)
    # a booking of the other portfolio cannot pay its invoice
    refused = staff.post(f"{API}/invoices/{linked['invoice']['id']}/payments",
                         json={"booking_id": south_booking.id, "amount": 119})
    assert refused.status_code in (403, 404)
    assert _ok(staff.get(f"{base}/project"))["participants"][0]["contact"]["name"] == "Dach Müller GmbH"


# ─── snapshot ────────────────────────────────────────────────────────────────

def test_snapshot_export_and_import_keep_the_project_file(owner, estate, roofer):
    case = _case(owner, estate)
    base = f"{API}/maintenance/{case['id']}"
    a, b = _package(owner, case["id"], "A"), _package(owner, case["id"], "B")
    _ok(_depend(owner, case["id"], a, b), 201)
    quote = _quote(owner, case["id"], 100, 119, contact_id=roofer.id)
    order = _ok(owner.post(f"{base}/quotes/{quote['id']}/accept", json={}), 201)
    linked = _ok(owner.post(f"{base}/orders/{order['id']}/invoices", json={"invoice": {
        "invoice_date": "2026-05-01", "net_amount": 100, "gross_amount": 119}}), 201)
    booking = _booking(estate, -119)
    _ok(owner.post(f"{API}/invoices/{linked['invoice']['id']}/payments",
                   json={"booking_id": booking.id, "amount": 119}), 201)
    _ok(owner.post(f"{base}/appointments", json={"title": "Termin", "event_date": "2026-06-01"}), 201)
    _ok(owner.post(f"{base}/protocols", json={"protocol_date": "2026-06-10", "protocol_type": "site_visit"}), 201)
    before = _project(owner, case["id"])

    snapshot = export_snapshot(store)
    for key in ("maintenance_work_packages", "maintenance_dependencies", "maintenance_quotes", "maintenance_orders",
                "maintenance_order_invoices", "invoice_payments", "maintenance_appointments",
                "maintenance_protocols", "maintenance_participants"):
        assert snapshot[key], key
    import json
    restored = json.loads(json.dumps(snapshot))
    clear_business_data(store)
    assert owner.get(f"{base}/project").status_code == 404
    import_snapshot(store, restored, replace=True)
    after = _project(owner, case["id"])
    assert after["costs"] == before["costs"] and len(after["work_packages"]) == 2
    assert [d["id"] for d in after["dependencies"]] == [d["id"] for d in before["dependencies"]]
    assert import_snapshot(store, restored, replace=False)["imported"] == {}       # nothing twice
