"""Deterministic investigations through real authenticated loopback MCP."""
import json
from datetime import date
from io import BytesIO

import pytest

from backend import auth
from backend.dependencies import store
from backend.invoice_review_models import InvoiceReview
from backend.maintenance_models import InvoicePayment
from backend.models import AccountCreate, BookingCreate, DocumentCreate, InvoiceCreate, TaskCreate, UnitCreate
from backend.services import assistant, assistant_runner, assistant_tools, file_storage
from backend.services.maintenance_projects import work
from backend.services.maintenance_rows import Rows
from backend.tests.test_assistant_tools import (  # noqa: F401
    clean,
    house,
    isolated_assistant,
    start,
    tool,
)


@pytest.fixture
def actor():
    return auth.register_user("investigation-reader", "investigate@example.test", "Prüfender Leser", "Secret123", "readonly")


def investigate(actor, run, callback):
    pages: list[dict] = []

    def execute(actor_id, provider, request, emit, cancelled):
        callback(request["_application_mcp"], pages)
        return {"text": "Prüfung mit Quellen abgeschlossen."}

    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    return pages, assistant.get_run(store, actor.id, run["id"])


def invoice(prop, **extra):
    return store.create_invoice(InvoiceCreate(property_id=prop.id, supplier="Prüfbetrieb",
        invoice_date=date(2026, 10, 1), due_date=date(2026, 10, 5),
        net_amount=100, vat_amount=19, gross_amount=119, **extra))


def test_investigation_anchor_paginates_evidence_and_no_domain_writes(actor):
    selected, neighbor = house("Prüfhaus"), house("Nachbarhaus")
    own = [store.create_task(TaskCreate(title="Prüfen " + str(index), property_id=selected.id,
             due_date=date(2026, 10, 2))) for index in range(3)]
    store.create_task(TaskCreate(title="Nachbar", property_id=neighbor.id, due_date=date(2026, 10, 2)))
    unit = store.create_unit(UnitCreate(property_id=selected.id, label="Ohne Fläche", unit_type="apartment"))
    before = {task.id: task.model_dump() for task in store.list_tasks()}
    _, run = start(actor)

    def check(connection, pages):
        cursor = None
        while True:
            page = tool(connection, "immo_investigate", {"anchor": {"kind": "property", "id": selected.id},
                "kinds": ["task", "unit"], "as_of": "2026-10-18", "limit": 1, "cursor": cursor})
            assert page["ok"], page
            assert page["coverage"]["scanned"] == 1
            assert page["coverage"]["truncated"] is False
            pages.append(page)
            cursor = page["coverage"]["next_cursor"]
            if not page["coverage"]["has_more"]:
                break

    pages, finished = investigate(actor, run, check)
    assert {source["id"] for page in pages for source in page["items"]} == {unit.id, *(task.id for task in own)}
    findings = [item for page in pages for item in page["findings"]]
    assert sorted(item["code"] for item in findings) == ["task_overdue"] * 3 + ["unit_area_missing"]
    assert all(len(item["id"]) == 64 and item["evidence"][0]["title"] and item["evidence"][0]["href"]
               and item["evidence"][0]["sha256"] for item in findings)
    assert all(item["as_of"] == "2026-10-18" for item in findings)
    assert finished["verification_status"] == "current"
    assert sum(len(item["findings"]) for item in finished["activity"]) == 4
    assert before == {task.id: task.model_dump() for task in store.list_tasks()}


@pytest.mark.parametrize("scope", ["selected", "none"])
def test_investigation_obeys_original_grant_and_does_not_expand_from_parent(actor, scope):
    prop = house("Einheitenhaus")
    own = store.create_unit(UnitCreate(property_id=prop.id, label="Eigene", unit_type="apartment"))
    other = store.create_unit(UnitCreate(property_id=prop.id, label="Fremde", unit_type="apartment"))
    first = store.create_task(TaskCreate(title="Eigene Aufgabe", property_id=prop.id, unit_id=own.id))
    second = store.create_task(TaskCreate(title="Fremde Aufgabe", property_id=prop.id, unit_id=other.id))
    _, run = start(actor, data_scope=scope, selection={"unit_ids": [own.id]} if scope == "selected" else {})

    def check(connection, pages):
        if scope == "selected":
            assert tool(connection, "immo_read", {"kind": "property", "id": prop.id})["ok"]
        pages.append(tool(connection, "immo_investigate", {"anchor": {"kind": "property", "id": prop.id},
            "kinds": ["task"], "as_of": "2026-10-18"}))

    pages, _ = investigate(actor, run, check)
    if scope == "none":
        assert pages[0]["error"]["code"] == "source_unavailable"
    else:
        assert pages[0]["ok"] and [source["id"] for source in pages[0]["items"]] == [first.id]
        assert second.id not in json.dumps(pages)


def test_investigation_scan_limit_requires_continuation_even_with_no_findings(actor, monkeypatch):
    prop = house("Viele Aufgaben")
    tasks = [store.create_task(TaskCreate(title=str(index), property_id=prop.id, status="completed")) for index in range(5)]
    monkeypatch.setattr(assistant_tools, "SCAN_LIMIT", 2)
    _, run = start(actor)

    def check(connection, pages):
        cursor = None
        while True:
            page = tool(connection, "immo_investigate", {"kinds": ["task"], "as_of": "2026-10-18", "cursor": cursor})
            assert page["ok"] and page["findings"] == []
            pages.append(page)
            cursor = page["coverage"]["next_cursor"]
            if not page["coverage"]["has_more"]:
                break

    pages, finished = investigate(actor, run, check)
    assert len(pages) == 3 and {source["id"] for page in pages for source in page["items"]} == {task.id for task in tasks}
    assert finished["verification_status"] == "current"


@pytest.mark.parametrize("change_review", [False, True])
def test_invoice_uses_mixed_rate_core_and_selected_payments_are_explicitly_skipped(actor, change_review):
    prop = house("Gemischte Rechnung")
    bill = store.create_invoice(InvoiceCreate(property_id=prop.id, supplier="Gemischt", invoice_date=date(2026, 10, 1),
        net_amount=200, vat_rate=19, vat_amount=26, gross_amount=226))
    with work(store, None, ()) as unit:
        Rows.of(unit).add("invoice_reviews", InvoiceReview(id="mixed-review", invoice_id=bill.id,
            received_on=date(2026, 10, 1), property_id=prop.id,
            vat_lines=[{"rate": 19, "net": 100, "vat": 19}, {"rate": 7, "net": 100, "vat": 7}]))
    _, run = start(actor, data_scope="selected", selection={"invoice_ids": [bill.id]})

    def check(connection, pages):
        page = tool(connection, "immo_investigate", {"kinds": ["invoice"],
            "checks": ["invoice_arithmetic", "invoice_payments"], "as_of": "2026-10-18"})
        pages.append(page)
        assert [(source["kind"], source["id"]) for source in page["sources"]] == [("invoice", bill.id)]
        assert page["sources"][0]["sha256"] and page["sources"][0]["revision"]
        if change_review:
            with work(store, None, ()) as unit:
                Rows.of(unit).update("invoice_reviews", "mixed-review",
                    vat_lines=[{"rate": 19, "net": 100, "vat": 19}, {"rate": 7, "net": 100, "vat": 8}])

    pages, finished = investigate(actor, run, check)
    assert pages[0]["ok"] and pages[0]["findings"] == []
    assert pages[0]["coverage"]["skipped_checks"][0]["check"] == "invoice_payments"
    assert pages[0]["calculations"][0]["engine"] == "invoice_review"
    assert finished["verification_status"] == ("stale" if change_review else "current")


@pytest.mark.parametrize("drift", ["new_task", "payment"])
def test_investigation_revalidates_negative_scan_and_auxiliary_payment_changes(actor, drift):
    prop = house("Veränderliche Akte")
    bill = invoice(prop, status="paid")
    account = store.create_account(AccountCreate(portfolio_id=prop.portfolio_id, name="Bank", account_type="bank", iban="SECRET-IBAN"))
    payment = store.create_booking(BookingCreate(account_id=account.id, property_id=prop.id,
        booking_date=date(2026, 10, 2), amount=-119))
    _, run = start(actor)

    def check(connection, pages):
        page = tool(connection, "immo_investigate", {"kinds": ["task"] if drift == "new_task" else ["invoice"],
            "as_of": "2026-10-18"})
        assert page["ok"], page
        assert "SECRET-IBAN" not in json.dumps(page)
        pages.append(page)
        if drift == "new_task":
            assert page["findings"] == [] and page["coverage"]["complete"]
            store.create_task(TaskCreate(title="Neue Aufgabe", property_id=prop.id))
        else:
            assert any(item["code"] == "invoice_paid_without_full_allocation" for item in page["findings"])
            with work(store, None, ()) as unit:
                Rows.of(unit).add("invoice_payments", InvoicePayment(id="late-allocation", invoice_id=bill.id,
                    booking_id=payment.id, amount=119))

    _, finished = investigate(actor, run, check)
    assert finished["verification_status"] == "stale", finished


def test_investigation_cursor_rejects_different_checks_and_strict_arguments(actor):
    prop = house("Fortsetzung")
    for index in range(2):
        store.create_task(TaskCreate(title=str(index), property_id=prop.id))
    _, run = start(actor)

    def check(connection, pages):
        args = {"kinds": ["task"], "as_of": "2026-10-18", "limit": 1}
        first = tool(connection, "immo_investigate", args)
        assert first["coverage"]["has_more"]
        invalid = tool(connection, "immo_investigate", {**args, "checks": ["deadlines"], "cursor": first["coverage"]["next_cursor"]})
        assert invalid["error"]["code"] == "source_or_run_changed"
        unknown = tool(connection, "immo_investigate", {**args, "actor_id": "intruder"})
        assert unknown["error"]["code"] == "invalid_arguments"
        pages.append(first)

    _, finished = investigate(actor, run, check)
    assert finished["verification_status"] == "current"


def test_investigation_refreshes_actor_rights(actor):
    prop = house("Rechteentzug")
    store.create_task(TaskCreate(title="Privat", property_id=prop.id))
    _, run = start(actor)
    seen = []

    def execute(actor_id, provider, request, emit, cancelled):
        auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
        result = tool(request["_application_mcp"], "immo_investigate", {
            "anchor": {"kind": "property", "id": prop.id}, "as_of": "2026-10-18"})
        seen.append(result)
        return {"text": "Keine freigegebene Quelle."}

    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    assert seen[0]["error"]["code"] == "source_unavailable"


@pytest.mark.parametrize("selection_mode", ["authorized", "document", "invoice", "property"])
def test_precise_invoice_document_relations_preserve_selected_grant(actor, monkeypatch, tmp_path, selection_mode):
    prop = house("Belegverknüpfung")
    storage = file_storage.LocalStorage(tmp_path)
    monkeypatch.setattr(file_storage, "_storage", storage)
    docs = []
    for index in range(2):
        key = f"documents/linked-{index}.txt"
        storage.save(key, BytesIO(b"Rechnungsbeleg"))
        docs.append(store.create_document(DocumentCreate(property_id=prop.id, title=f"Beleg {index}",
            file_url="/uploads/" + key)))
    bills = [invoice(prop) for _ in range(2)]
    with work(store, None, ()) as unit:
        for bill, doc in zip(bills, docs):
            Rows.of(unit).update("invoices", bill.id, source_document_id=doc.id)
    selected = {"document": {"document_ids": [docs[0].id]}, "invoice": {"invoice_ids": [bills[0].id]},
                "property": {"property_ids": [prop.id]}}.get(selection_mode, {})
    _, run = start(actor, selection=selected, data_scope="authorized" if selection_mode == "authorized" else "selected")

    def check(connection, pages):
        for name in ("immo_related", "immo_investigate"):
            for anchor, target_kind, target_id, denied_mode in (
                ({"kind": "document", "id": docs[0].id}, "invoice", bills[0].id, "invoice"),
                ({"kind": "invoice", "id": bills[0].id}, "document", docs[0].id, "document"),
            ):
                args = ({**anchor, "target_kinds": [target_kind]} if name == "immo_related" else
                        {"anchor": anchor, "kinds": [target_kind], "checks": ["missing_data"], "as_of": "2026-10-18"})
                result = tool(connection, name, args)
                pages.append(result)
                if selection_mode == denied_mode:
                    assert result["error"]["code"] == "source_unavailable"
                else:
                    assert result["ok"], result
                    expected = [target_id] if selection_mode in ("authorized", "property") else []
                    assert [source["id"] for source in result["items"]] == expected
                assert bills[1].id not in json.dumps(result) and docs[1].id not in json.dumps(result)

    _, finished = investigate(actor, run, check)
    assert finished["verification_status"] == "current", finished
