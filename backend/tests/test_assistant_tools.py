"""Real loopback MCP, synthetic provider only, isolated application fixtures."""
import json
from datetime import date, datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend import auth
from backend.assistant_models import ConversationEdit, RevisionCommand, RunCreate
from backend.business_qol_models import NoteCreate
from backend.dependencies import store
from backend.models import AccountCreate, BookingCreate, PortfolioCreate, PropertyCreate, TaskCreate, UnitCreate
from backend.services import assistant, assistant_runner, assistant_tools
from backend.services import business_qol as office
from backend.services.workspace_contexts import resolve_context
from backend.tests.test_assistant_workspace import (  # noqa: F401
    clean as clean,
)
from backend.tests.test_assistant_workspace import (
    command,
    conversation,
)
from backend.tests.test_assistant_workspace import (
    isolated_assistant as isolated_assistant,
)


@pytest.fixture
def actor():
    return auth.register_user("assistant-tools-reader", "tools@example.test", "Werkzeugleser", "Secret123", "readonly")


def rpc(connection, method, params=None, *, token=True, identifier=1):
    payload = {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params or {}}
    headers = {"Content-Type": "application/json", **(connection["headers"] if token else {})}
    with urlopen(Request(connection["url"], json.dumps(payload).encode(), headers), timeout=15) as response:
        return json.load(response)


def tool(connection, name, arguments):
    return rpc(connection, "tools/call", {"name": name, "arguments": arguments})["result"]["structuredContent"]


def start(actor, *, selection=None, data_scope="authorized", attachment_ids=None):
    chat = conversation(actor, provider="codex")
    run = assistant.submit(store, actor.id, chat["id"], RunCreate(**command(expected_revision=chat["revision"],
        content="Prüfe die aktuellen Akten", context=selection or {}, data_scope=data_scope,
        attachment_ids=attachment_ids or [])))
    return chat, run


def house(name):
    portfolio = store.create_portfolio(PortfolioCreate(name=name + " Portfolio"))
    return store.create_property(PropertyCreate(portfolio_id=portfolio.id, name=name, property_type="residential"))


def test_real_mcp_auth_strict_tools_and_persisted_provenance(actor):
    selected = house("Recherchehaus")
    task = store.create_task(TaskCreate(title="Heizung prüfen", property_id=selected.id, due_date=date(2026, 10, 20)))
    chat, run = start(actor)
    seen = []

    def execute(actor_id, provider, request, emit, cancelled):
        connection = request["_application_mcp"]
        assert connection["url"].startswith("http://127.0.0.1:")
        with pytest.raises(HTTPError) as denied:
            rpc(connection, "tools/list", token=False)
        assert denied.value.code == 401
        with pytest.raises(HTTPError) as malformed:
            rpc({**connection, "headers": {"Authorization": "Bearer ä-invalid"}}, "tools/list")
        assert malformed.value.code == 401
        initialized = rpc(connection, "initialize", {"protocolVersion": "2025-03-26"})
        assert initialized["result"]["serverInfo"]["name"] == "immomanager"
        listing = rpc(connection, "tools/list")["result"]["tools"]
        assert {item["name"] for item in listing} == set(assistant_tools.TOOLS)
        invalid = tool(connection, "immo_read", {"kind": "property", "id": selected.id, "actor_id": "intruder"})
        assert invalid["error"]["code"] == "invalid_arguments"
        result = tool(connection, "immo_related", {"kind": "property", "id": selected.id, "target_kinds": ["task"]})
        assert [item["id"] for item in result["items"]] == [task.id]
        assert result["sources"][1]["revision"] and result["sources"][1]["sha256"]
        seen.append(connection)
        return {"text": "Aufgabe mit aktuellem Quellenbeleg gefunden."}

    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    finished = assistant.get_run(store, actor.id, run["id"])
    assert finished["state"] == "completed", finished
    assert [event["status"] for event in finished["activity"]] == ["failed", "completed"]
    assert {source["id"] for source in finished["sources"]} == {selected.id, task.id}
    assert "Bearer" not in json.dumps(finished)
    with pytest.raises(OSError):
        rpc(seen[0], "tools/list")
    messages = assistant.list_records(store, actor.id, assistant.Message, conversation_id=chat["id"])["items"]
    assert messages[-1]["provider"] == "codex" and messages[-1]["sources"]


@pytest.mark.parametrize("scope,allowed", [("authorized", True), ("selected", False), ("none", False)])
def test_data_scope_does_not_expand_through_model_ids(actor, scope, allowed):
    selected, neighbor = house("Ausgewählt"), house("Nachbar")
    _, run = start(actor, selection={"property_ids": [selected.id]} if scope != "none" else {}, data_scope=scope)
    results = []

    def execute(actor_id, provider, request, emit, cancelled):
        results.append(tool(request["_application_mcp"], "immo_read", {"kind": "property", "id": neighbor.id}))
        return {"text": "Auswahl geprüft."}

    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    assert results[0]["ok"] is allowed
    assert assistant.get_run(store, actor.id, run["id"])["state"] == "completed"


def test_selected_unit_relations_exclude_sibling_unit_and_search_paginates(actor):
    selected = house("Haus")
    first = store.create_unit(UnitCreate(property_id=selected.id, label="Wohnung 1", unit_type="apartment"))
    second = store.create_unit(UnitCreate(property_id=selected.id, label="Wohnung 2", unit_type="apartment"))
    tasks = [store.create_task(TaskCreate(title="Eigene Aufgabe " + str(index), property_id=selected.id, unit_id=first.id)) for index in range(3)]
    store.create_task(TaskCreate(title="Fremde Einheit", property_id=selected.id, unit_id=second.id))
    _, run = start(actor, selection={"unit_ids": [first.id]}, data_scope="selected")
    found: list[str] = []

    def execute(actor_id, provider, request, emit, cancelled):
        # Parent metadata is useful, but must not authorize sibling units'
        # financial figures or their property's entire correspondence.
        connection = request["_application_mcp"]
        assert tool(connection, "immo_read", {"kind": "property", "id": selected.id})["ok"]
        assert tool(connection, "immo_report", {"definition": {"version": 2, "kind": "cash-v2",
            "as_of": "2026-10-18", "property_id": selected.id}})["ok"] is False
        assert tool(connection, "immo_timeline", {"kind": "property", "id": selected.id})["ok"] is False
        cursor = None
        while True:
            page = tool(request["_application_mcp"], "immo_search", {"kind": "task", "limit": 1, "cursor": cursor})
            assert page["ok"] and page["coverage"]["truncated"] is False
            found.extend(item["id"] for item in page["items"])
            cursor = page["coverage"]["next_cursor"]
            if not page["coverage"]["has_more"]:
                break
        return {"text": "Alle erreichbaren Aufgaben gelesen."}

    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    assert set(found) == {task.id for task in tasks} and len(found) == 3


def test_private_document_cursor_reads_beyond_initial_excerpt_and_no_data_scope(actor):
    chat = conversation(actor, provider="codex")
    text = "Anfang\n" + "x" * 80000 + "\nENDE DES ORIGINALS"
    attached = assistant.add_attachment(store, actor.id, chat["id"], text.encode(), "vollständig.txt")
    run = assistant.submit(store, actor.id, chat["id"], RunCreate(**command(expected_revision=chat["revision"],
        content="Lies bis zum Ende", data_scope="none", attachment_ids=[attached["id"]])))
    parts = []

    def execute(actor_id, provider, request, emit, cancelled):
        cursor = None
        while True:
            page = tool(request["_application_mcp"], "immo_document", {"kind": "attachment", "id": attached["id"], "cursor": cursor})
            assert page["ok"], page
            parts.append(page["items"][0]["text"])
            cursor = page["coverage"]["next_cursor"]
            if not page["coverage"]["has_more"]:
                break
        return {"text": "Ende gefunden."}

    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    assert "".join(parts) == text
    assert assistant.get_run(store, actor.id, run["id"])["state"] == "completed"


def test_fresh_rights_stop_tool_after_revocation_and_hide_history(actor):
    selected = house("Privates Haus")
    _, run = start(actor)
    results = []

    def execute(actor_id, provider, request, emit, cancelled):
        connection = request["_application_mcp"]
        assert tool(connection, "immo_read", {"kind": "property", "id": selected.id})["ok"]
        auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
        results.append(tool(connection, "immo_read", {"kind": "property", "id": selected.id}))
        assert cancelled()
        return {"text": "Darf nach Entzug nicht ausgeliefert werden."}

    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    assert results[0]["ok"] is False
    with pytest.raises(HTTPException) as denied:
        assistant.get_run(store, actor.id, run["id"])
    assert denied.value.status_code == 404


def test_report_tool_uses_real_cents_and_detects_drift(actor):
    selected = house("Finanzhaus")
    account = store.create_account(AccountCreate(portfolio_id=selected.portfolio_id, name="Konto", account_type="bank", iban="DE-SHOULD-NEVER-LEAVE"))
    store.create_booking(BookingCreate(account_id=account.id, property_id=selected.id,
        booking_date=date(2026, 1, 2), amount=123.45, payment_text="Exakte Einnahme"))
    _, run = start(actor)
    reports = []

    def execute(actor_id, provider, request, emit, cancelled):
        result = tool(request["_application_mcp"], "immo_report", {"definition": {
            "version": 2, "kind": "cash-v2", "property_id": selected.id,
            "as_of": "2026-01-31", "date_from": "2026-01-01", "date_to": "2026-01-31"}})
        assert result["ok"], result
        assert "DE-SHOULD-NEVER-LEAVE" not in json.dumps(result)
        reports.append(result["report"])
        store.create_booking(BookingCreate(account_id=account.id, property_id=selected.id,
            booking_date=date(2026, 1, 3), amount=1, payment_text="Neue Buchung"))
        return {"text": "Früherer geprüfter Bericht"}

    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    assert reports[0]["totals"]["income"] == "123.45"
    finished = assistant.get_run(store, actor.id, run["id"])
    assert finished["state"] == "completed" and finished["verification_status"] == "stale", finished


def test_followup_inherits_working_files_and_provider_changes_are_explicit(actor):
    chat = conversation(actor)
    attached = assistant.add_attachment(store, actor.id, chat["id"], b"Arbeitsquelle", "quelle.txt")
    first = assistant.submit(store, actor.id, chat["id"], RunCreate(**command(expected_revision=chat["revision"],
        content="Erste Frage", attachment_ids=[attached["id"]])))
    current = assistant.get_conversation(store, actor.id, chat["id"])
    with pytest.raises(HTTPException) as blocked:
        assistant.edit_conversation(store, actor.id, chat["id"], ConversationEdit(**command(expected_revision=current["revision"], provider="codex")))
    assert blocked.value.status_code == 409
    assistant.cancel(store, actor.id, first["id"], RevisionCommand(**command(expected_revision=first["revision"])))
    current = assistant.get_conversation(store, actor.id, chat["id"])
    current = assistant.edit_conversation(store, actor.id, chat["id"], ConversationEdit(**command(
        expected_revision=current["revision"], provider="codex", model="gpt-6.1-sol", effort="high")))
    second = assistant.submit(store, actor.id, chat["id"], RunCreate(**command(expected_revision=current["revision"], content="Folgefrage")))
    assert second["effective_attachment_ids"] == [attached["id"]] and second["provider"] == "codex"
    assistant.cancel(store, actor.id, second["id"], RevisionCommand(**command(expected_revision=second["revision"])))
    current = assistant.get_conversation(store, actor.id, chat["id"])
    third = assistant.submit(store, actor.id, chat["id"], RunCreate(**command(expected_revision=current["revision"],
        content="Datei abwählen", excluded_attachment_ids=[attached["id"]])))
    assert third["attachment_ids"] == []


def test_timeline_reads_real_phone_notes_with_dates_cursor_and_secret_history_filter(actor):
    selected = house("Telefonakte")
    owner = auth.register_user("timeline-owner", "timeline@example.test", "Büro", "Secret123", "eigentuemer")
    for index in range(3):
        office.create_note(store, NoteCreate(entity_type="property", entity_id=selected.id,
            base_revision=resolve_context(store, "property", selected.id, owner.id)["revision"],
            body="Heizungsbetrieb angerufen " + str(index), conversation_kind="phone",
            occurred_at=datetime(2026, 10, 3, 12, tzinfo=timezone.utc), idempotency_key=uuid4()), owner.id)
    store.add_change_history("property", selected.id, "iban", None, "DE-SENSITIVE-HISTORY", owner.id)
    _, run = start(actor, selection={"property_ids": [selected.id]}, data_scope="selected")
    seen = []

    def execute(actor_id, provider, request, emit, cancelled):
        cursor = None
        while True:
            result = tool(request["_application_mcp"], "immo_timeline", {"kind": "property", "id": selected.id,
                "date_from": "2026-10-01", "date_to": "2026-10-04", "limit": 1, "cursor": cursor})
            assert result["ok"], result
            assert "DE-SENSITIVE-HISTORY" not in json.dumps(result)
            seen.extend(result["items"])
            cursor = result["coverage"]["next_cursor"]
            if not result["coverage"]["has_more"]:
                break
        raw = tool(request["_application_mcp"], "immo_timeline", {"kind": "property", "id": selected.id})
        assert raw["ok"] and "DE-SENSITIVE-HISTORY" not in json.dumps(raw)
        return {"text": "Drei Telefonate belegt."}

    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    assert len(seen) == 3 and len({event["id"] for event in seen}) == 3
    assert all(event["title"] == "Telefonat" and event["event_sha256"] for event in seen)
    assert assistant.get_run(store, actor.id, run["id"])["state"] == "completed"


def test_global_report_is_authorized_only_and_preserves_portfolio_access_guards(actor):
    selected = house("Globalbericht")
    _, run = start(actor)
    results = []

    def execute(actor_id, provider, request, emit, cancelled):
        results.append(tool(request["_application_mcp"], "immo_report", {"definition": {
            "version": 2, "kind": "cash-v2", "as_of": "2026-01-31", "date_from": "2026-01-01"}}))
        return {"text": "Gesamtbestand geprüft."}

    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    assert results[0]["ok"], results
    assert any(source["kind"] == "portfolio" and source["id"] == selected.portfolio_id for source in results[0]["sources"])
    assert assistant.get_run(store, actor.id, run["id"])["state"] == "completed"
    auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
    with pytest.raises(HTTPException) as hidden:
        assistant.get_run(store, actor.id, run["id"])
    assert hidden.value.status_code == 404


def test_tool_budget_is_visible_and_followup_gets_fresh_budget(actor, monkeypatch):
    monkeypatch.setattr(assistant_tools, "MAX_CALLS", 2)
    selected = house("Budgethaus")
    chat, run = start(actor)
    results = []

    def execute(actor_id, provider, request, emit, cancelled):
        for _ in range(3):
            results.append(tool(request["_application_mcp"], "immo_read", {"kind": "property", "id": selected.id}))
        return {"text": "Fortsetzung benötigt eine neue Folgefrage."}

    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    assert [result["ok"] for result in results] == [True, True, False]
    assert results[-1]["error"]["code"] == "tool_budget_exceeded"
    finished = assistant.get_run(store, actor.id, run["id"])
    assert finished["tool_budget"] == {"used": 2, "limit": 2, "exhausted": True, "continuation": "followup"}
    current = assistant.get_conversation(store, actor.id, chat["id"])
    next_run = assistant.submit(store, actor.id, chat["id"], RunCreate(**command(expected_revision=current["revision"],
        content="Bitte fortsetzen", data_scope="authorized")))
    assert next_run["tool_budget"]["used"] == 0
    assert next_run["sources"] and current["context_sources"]


def test_excluded_attachment_owner_and_conversation_are_checked(actor):
    first, second = conversation(actor), conversation(actor)
    attached = assistant.add_attachment(store, actor.id, first["id"], b"Privat", "privat.txt")
    with pytest.raises(HTTPException) as wrong_conversation:
        assistant.submit(store, actor.id, second["id"], RunCreate(**command(expected_revision=second["revision"],
            content="Fremde Arbeitsdatei entfernen", excluded_attachment_ids=[attached["id"]])))
    assert wrong_conversation.value.status_code == 404


def test_late_mcp_call_after_cancel_cannot_touch_new_retry(actor):
    selected = house("Abbruchhaus")
    chat, run = start(actor)
    results, retries = [], []

    def execute(actor_id, provider, request, emit, cancelled):
        stopped = assistant.cancel(store, actor.id, run["id"], RevisionCommand(**command(expected_revision=run["revision"])))
        retries.append(assistant.retry(store, actor.id, run["id"], RevisionCommand(**command(expected_revision=stopped["revision"]))))
        results.append(tool(request["_application_mcp"], "immo_read", {"kind": "property", "id": selected.id}))
        assert cancelled()
        return {"text": "Verspätete Antwort"}

    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    assert results[0]["ok"] is False and results[0]["error"]["code"] == "source_or_run_changed"
    assert assistant.get_run(store, actor.id, run["id"])["state"] == "cancelled"
    assert assistant.get_run(store, actor.id, retries[0]["id"])["state"] == "queued"
    assert assistant.get_conversation(store, actor.id, chat["id"])["active_run_id"] == retries[0]["id"]


def test_repeated_mcp_requests_release_thread_sessions(actor):
    selected = house("Verbindungshaus")
    _, run = start(actor)
    outputs = []

    def execute(actor_id, provider, request, emit, cancelled):
        for _ in range(24):
            outputs.append(tool(request["_application_mcp"], "immo_read", {"kind": "property", "id": selected.id}))
        return {"text": "24 unabhängige Leseaufrufe ohne Poolerschöpfung."}

    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    assert len(outputs) == 24 and all(output["ok"] for output in outputs)
    assert assistant.get_run(store, actor.id, run["id"])["state"] == "completed"


def test_changed_tool_source_is_stale_and_none_followup_omits_domain_history(actor):
    selected = house("Frühere Quelle")
    chat, run = start(actor)

    def execute(actor_id, provider, request, emit, cancelled):
        assert tool(request["_application_mcp"], "immo_read", {"kind": "property", "id": selected.id})["ok"]
        store.update_property(selected.id, PropertyCreate(portfolio_id=selected.portfolio_id,
            name="Aktuelle Quelle", property_type="residential"))
        return {"text": "Historischer Betrag 999 aus früherem Aktenstand"}

    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    assert assistant.get_run(store, actor.id, run["id"])["verification_status"] == "stale"
    current = assistant.get_conversation(store, actor.id, chat["id"])
    follow = assistant.submit(store, actor.id, chat["id"], RunCreate(**command(expected_revision=current["revision"],
        content="Frage zum Verlauf", data_scope="authorized")))
    requests = []

    def answer(actor_id, provider, request, emit, cancelled):
        requests.append(request)
        return {"text": "Neue Antwort"}

    assistant_runner.run(store, follow["id"], actor.id, execute=answer)
    historical = next(item for item in requests[0]["messages"] if item["role"] == "assistant")
    assert "Historische Modellinterpretation" in historical["content"] and historical["historical_sources"]
    current = assistant.get_conversation(store, actor.id, chat["id"])
    none = assistant.submit(store, actor.id, chat["id"], RunCreate(**command(expected_revision=current["revision"],
        content="Private Folgefrage ohne Fachakten", data_scope="none", context={})))
    assistant_runner.run(store, none["id"], actor.id, execute=answer)
    assert "Historischer Betrag 999" not in json.dumps(requests[1]["messages"])
    assert any("außerhalb" in value for value in requests[1]["omissions"])
