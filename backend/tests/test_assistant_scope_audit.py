"""Provider-free privacy oracles for source grants and historical chat inputs."""
import json
from datetime import date
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend import auth
from backend.assistant_models import ConversationEdit, RevisionCommand, RunCreate
from backend.dependencies import store
from backend.models import AccountCreate, BookingCreate, PortfolioCreate, PropertyCreate, TaskCreate, UnitCreate
from backend.services import assistant, assistant_runner
from backend.services import assistant_storage as db
from backend.services.assistant_proposals import InvoiceValues
from backend.tests.test_assistant_tools import tool
from backend.tests.test_assistant_workspace import clean as clean  # noqa: F401
from backend.tests.test_assistant_workspace import command, conversation
from backend.tests.test_assistant_workspace import isolated_assistant as isolated_assistant  # noqa: F401


@pytest.fixture
def actor():
    return auth.register_user("scope-audit", "scope-audit@example.test", "Prüfender Nutzer", "Secret123", "readonly")


def turn(actor, chat, **values):
    current = assistant.get_conversation(store, actor.id, chat["id"])
    return assistant.submit(store, actor.id, chat["id"], RunCreate(**command(
        expected_revision=current["revision"], **values)))


@pytest.mark.parametrize("grant,allowed", [("task", False), ("unit", True), ("property", True)])
def test_selected_record_parent_metadata_cannot_authorize_unit_finance(actor, grant, allowed):
    portfolio = store.create_portfolio(PortfolioCreate(name="Ausgewählter Bereich"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="Wohnung", unit_type="apartment"))
    task = store.create_task(TaskCreate(title="Nur diese Aufgabe", property_id=prop.id, unit_id=unit.id))
    account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Bank", account_type="bank"))
    store.create_booking(BookingCreate(account_id=account.id, property_id=prop.id, unit_id=unit.id,
        booking_date=date(2026, 1, 2), amount=987.65, payment_text="Nicht gewählte Zahlung"))
    selected = {"task": task.id, "unit": unit.id, "property": prop.id}
    chat = conversation(actor, provider="codex")
    run = turn(actor, chat, content="Prüfe die Auswahl", data_scope="selected",
        context={grant + "_ids": [selected[grant]]})
    results = []

    def execute(actor_id, provider, request, emit, cancelled):
        connection = request["_application_mcp"]
        assert tool(connection, "immo_read", {"kind": "unit", "id": unit.id})["ok"]
        results.append(tool(connection, "immo_report", {"definition": {
            "version": 2, "kind": "cash-v2", "unit_id": unit.id, "as_of": "2026-01-31"}}))
        return {"text": "Auswahl geprüft."}

    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    assert results[0]["ok"] is allowed
    if allowed:
        assert results[0]["report"]["totals"]["income"] == "987.65"
    else:
        assert "987.65" not in json.dumps(results[0])


def test_removed_attachment_is_not_retransmitted_through_history(actor):
    chat = conversation(actor, provider="codex")
    attachment = assistant.add_attachment(store, actor.id, chat["id"], b"GEHEIME_DATEI_4711", "privat.txt")
    first = turn(actor, chat, content="Fasse GEHEIME_FRAGE_4711 aus der Datei zusammen", data_scope="none",
        attachment_ids=[attachment["id"]])
    assistant_runner.run(store, first["id"], actor.id,
        execute=lambda *args: {"text": "GEHEIME_DATEI_4711 ist der gelesene Inhalt."})
    second = turn(actor, chat, content="Datei entfernen, neue unabhängige Frage", data_scope="none",
        excluded_attachment_ids=[attachment["id"]])
    seen = []

    def execute(actor_id, provider, request, emit, cancelled):
        seen.append(request)
        return {"text": "Neue unabhängige Antwort."}

    assistant_runner.run(store, second["id"], actor.id, execute=execute)
    assert seen[0]["attachments"] == []
    assert "GEHEIME_DATEI_4711" not in json.dumps(seen[0]["messages"])
    assert "GEHEIME_FRAGE_4711" not in json.dumps(seen[0]["messages"])
    assert seen[0]["omissions"]
    saved = assistant.list_records(store, actor.id, assistant.Message, conversation_id=chat["id"])["items"]
    assert any("GEHEIME_DATEI_4711" in row["content"] for row in saved)


def test_source_scope_downgrade_also_omits_historical_user_prompt(actor):
    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Privates Haus", property_type="residential"))
    chat = conversation(actor, provider="codex")
    first = turn(actor, chat, content="GEHEIME_AKTENFRAGE_853 zur gewählten Immobilie", data_scope="selected",
        context={"property_ids": [prop.id]})
    assistant_runner.run(store, first["id"], actor.id, execute=lambda *args: {"text": "GEHEIME_AKTENANTWORT_853"})
    second = turn(actor, chat, content="Nun ohne Verwaltungsakten", data_scope="none")
    seen = []

    def execute(actor_id, provider, request, emit, cancelled):
        seen.append(request)
        return {"text": "Freie Antwort ohne Verwaltungsakten."}

    assistant_runner.run(store, second["id"], actor.id, execute=execute)
    sent = json.dumps(seen[0]["messages"])
    assert "GEHEIME_AKTENFRAGE_853" not in sent
    assert "GEHEIME_AKTENANTWORT_853" not in sent
    assert seen[0]["messages"][-1]["content"] == "Nun ohne Verwaltungsakten"


def legacy_run(actor, identifier):
    """An archived pre-audit run has no transitive request provenance."""
    with db.work(store, actor.id, write=True) as unit:
        row = db.owned_child(unit, assistant.Run, identifier, lock=True)
        values = db.payload(row)
        values.pop("_history_inputs", None)
        db.put(unit, assistant.Run, values, row=row)


def test_scope_history_dependencies_survive_an_unanchored_intermediate_answer(actor):
    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Quelle", property_type="residential"))
    chat = conversation(actor, provider="codex")
    first = turn(actor, chat, content="Lies diese Quelle", data_scope="selected", context={"property_ids": [prop.id]})
    assistant_runner.run(store, first["id"], actor.id, execute=lambda *args: {"text": "QUELLTEXT_637"})
    intermediate = turn(actor, chat, content="Fasse den Verlauf zusammen", data_scope="authorized", context={})

    def summarize(actor_id, provider, request, emit, cancelled):
        assert "QUELLTEXT_637" in json.dumps(request["messages"])
        return {"text": "ABGELEITETER_TEXT_637"}

    assistant_runner.run(store, intermediate["id"], actor.id, execute=summarize)
    assert assistant.get_run(store, actor.id, intermediate["id"])["sources"] == []
    final = turn(actor, chat, content="Nun ohne Akten", data_scope="none", context={})
    seen = []

    def execute(actor_id, provider, request, emit, cancelled):
        seen.append(request)
        return {"text": "Freie Antwort."}

    assistant_runner.run(store, final["id"], actor.id, execute=execute)
    assert "QUELLTEXT_637" not in json.dumps(seen[0]["messages"])
    assert "ABGELEITETER_TEXT_637" not in json.dumps(seen[0]["messages"])


def test_legacy_file_derived_answer_is_omitted_even_without_its_own_attachment(actor):
    chat = conversation(actor, provider="codex")
    attached = assistant.add_attachment(store, actor.id, chat["id"], b"ALTDATEI_937", "alt.txt")
    first = turn(actor, chat, content="Alte Dateifrage", data_scope="none", attachment_ids=[attached["id"]])
    assistant_runner.run(store, first["id"], actor.id, execute=lambda *args: {"text": "ALTDATEI_937"})
    legacy_run(actor, first["id"])
    intermediate = turn(actor, chat, content="Datei nicht mehr verwenden", data_scope="none",
        excluded_attachment_ids=[attached["id"]])
    # Simulate the pre-fix historical answer that could still repeat the old
    # file, despite having no direct attachment in its own run metadata.
    assistant_runner.run(store, intermediate["id"], actor.id,
        execute=lambda *args: {"text": "ALTE_ABGELEITETE_DATEIANTWORT_937"})
    legacy_run(actor, intermediate["id"])
    final = turn(actor, chat, content="Neue freie Frage", data_scope="none")
    seen = []

    def execute(actor_id, provider, request, emit, cancelled):
        seen.append(request)
        return {"text": "Unabhängige Antwort."}

    assistant_runner.run(store, final["id"], actor.id, execute=execute)
    sent = json.dumps(seen[0]["messages"])
    assert "ALTDATEI_937" not in sent and "ALTE_ABGELEITETE_DATEIANTWORT_937" not in sent
    assert "Neue freie Frage" in sent and seen[0]["omissions"]


@pytest.mark.parametrize("legacy", [False, True])
def test_history_keeps_permitted_working_file_and_free_conversation(actor, legacy):
    chat = conversation(actor, provider="codex")
    attached = assistant.add_attachment(store, actor.id, chat["id"], b"FREIGEGEBENE_DATEI_123", "gewaehlt.txt")
    first = turn(actor, chat, content="Erste Frage", data_scope="none", attachment_ids=[attached["id"]])
    assistant_runner.run(store, first["id"], actor.id, execute=lambda *args: {"text": "FREIGEGEBENE_DATEI_123"})
    if legacy:
        legacy_run(actor, first["id"])
    second = turn(actor, chat, content="Weiter mit derselben Datei", data_scope="none")
    seen = []

    def execute(actor_id, provider, request, emit, cancelled):
        seen.append(request)
        return {"text": "Fortsetzung."}

    assistant_runner.run(store, second["id"], actor.id, execute=execute)
    assert "FREIGEGEBENE_DATEI_123" in json.dumps(seen[0]["messages"])
    assert [item["id"] for item in seen[0]["attachments"]] == [attached["id"]]
    assert seen[0]["omissions"] == []


def test_legacy_free_chat_remains_available_without_sources_or_files(actor):
    chat = conversation(actor, provider="codex")
    first = turn(actor, chat, content="Allgemeine Frage", data_scope="none")
    assistant_runner.run(store, first["id"], actor.id, execute=lambda *args: {"text": "ALLGEMEINE_ANTWORT_321"})
    legacy_run(actor, first["id"])
    second = turn(actor, chat, content="Allgemeine Folgefrage", data_scope="none")
    seen = []

    def execute(actor_id, provider, request, emit, cancelled):
        seen.append(request)
        return {"text": "Fortsetzung."}

    assistant_runner.run(store, second["id"], actor.id, execute=execute)
    assert "ALLGEMEINE_ANTWORT_321" in json.dumps(seen[0]["messages"])
    assert seen[0]["omissions"] == []


def test_out_of_range_invoice_proposal_does_not_discard_valid_provider_answer(actor):
    chat = conversation(actor, provider="codex")
    run = turn(actor, chat, content="Lies den Beleg", data_scope="none")
    malformed: dict[str, Any] = {"kind": "invoice", "anchor": None, "evidence": [], "values": {
        "supplier": "Ungeprüfter Anbieter", "invoice_date": "2026-11-06", "net_amount": "1e30",
        "vat_rate": "19", "vat_amount": "1.9e29", "gross_amount": "1.19e30"}}
    assistant_runner.run(store, run["id"], actor.id,
        execute=lambda *args: {"text": "Die lesbare Analyse bleibt erhalten.", "proposals": [malformed]})
    result = assistant.get_run(store, actor.id, run["id"])
    assert result["state"] == "completed"
    assert result["response"] == "Die lesbare Analyse bleibt erhalten."
    assert result["proposals"] == []
    assert any("ungültiger Anlagevorschlag" in event.get("message", "") for event in result["events"])
    assert store.list_invoices() == [] and store.list_bookings() == []


@pytest.mark.parametrize("amount", ["10000000000", "1e30", "1e500", "NaN", "Infinity", "-0.01", True])
def test_invoice_proposal_amounts_follow_persisted_money_limits(amount):
    with pytest.raises(ValidationError):
        InvoiceValues.model_validate({"supplier": "Test", "invoice_date": "2026-11-06", "net_amount": amount,
            "vat_rate": "0", "vat_amount": "0", "gross_amount": amount})


def test_invoice_proposal_accepts_exact_persisted_money_boundary():
    values = InvoiceValues.model_validate({"supplier": "Test", "invoice_date": "2026-11-06",
        "net_amount": "9999999999.99", "vat_rate": "0", "vat_amount": "0", "gross_amount": "9999999999.99"})
    assert values.model_dump(mode="json")["gross_amount"] == "9999999999.99"


@pytest.mark.parametrize("legacy", [False, True])
def test_parent_reads_never_become_a_followup_selection_grant(actor, legacy):
    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="Einheit", unit_type="apartment"))
    task = store.create_task(TaskCreate(title="Nur diese Aufgabe", property_id=prop.id, unit_id=unit.id))
    chat = conversation(actor, provider="codex")
    first = turn(actor, chat, content="Lies die Stammdaten", data_scope="selected", context={"task_ids": [task.id]})

    def parent_reads(actor_id, provider, request, emit, cancelled):
        for kind, identifier in [("unit", unit.id), ("property", prop.id)]:
            assert tool(request["_application_mcp"], "immo_read", {"kind": kind, "id": identifier})["ok"]
        return {"text": "Nur die gewählte Aufgabe und ihre Eltern-Stammdaten gelesen."}

    assistant_runner.run(store, first["id"], actor.id, execute=parent_reads)
    used = assistant.get_run(store, actor.id, first["id"])["sources"]
    assert {source["id"] for source in used} == {task.id, unit.id, prop.id}
    if legacy:
        # Pre-audit versions overwrote the chosen context with every read.
        with db.work(store, actor.id, write=True) as tx:
            row = db.conversation(tx, chat["id"], lock=True)
            data = db.payload(row)
            data["context"] = {"property_ids": [prop.id], "unit_ids": [unit.id], "task_ids": [task.id]}
            data["context_sources"] = used
            db.put(tx, assistant.Conversation, data, row=row)
    current = assistant.get_conversation(store, actor.id, chat["id"])
    assert current["context"]["task_ids"] == [task.id]
    assert not current["context"].get("property_ids") and not current["context"].get("unit_ids")
    assert [source["id"] for source in current["context_sources"]] == [task.id]
    if legacy:
        edit = ConversationEdit(**command(expected_revision=current["revision"], title="Prüfung der ursprünglichen Auswahl"))
        for edited in [assistant.edit_conversation(store, actor.id, chat["id"], edit),
                       assistant.edit_conversation(store, actor.id, chat["id"], edit)]:
            assert edited["context"] == current["context"]
            assert [source["id"] for source in edited["context_sources"]] == [task.id]
    second = turn(actor, chat, content="Folgefrage mit derselben Auswahl", data_scope="selected")
    results = []

    def followup(actor_id, provider, request, emit, cancelled):
        results.append(tool(request["_application_mcp"], "immo_report", {"definition": {
            "version": 2, "kind": "cash-v2", "unit_id": unit.id, "as_of": "2026-01-31"}}))
        return {"text": "Die Folgefrage erweitert die Freigabe nicht."}

    assistant_runner.run(store, second["id"], actor.id, execute=followup)
    assert results[0]["ok"] is False


@pytest.mark.parametrize("change", ["scope", "context", "attachment"])
def test_retry_cannot_restore_a_replaced_conversation_grant(actor, change):
    from backend.services.assistant_provider_protocol import ProviderError

    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    props = [store.create_property(PropertyCreate(portfolio_id=portfolio.id, name=name, property_type="residential"))
             for name in ("Erste Quelle", "Neue Quelle")]
    chat = conversation(actor, provider="codex")
    attached = assistant.add_attachment(store, actor.id, chat["id"], b"Alte Dateifreigabe", "alt.txt")
    first = turn(actor, chat, content="Erste Frage", data_scope="authorized", context={"property_ids": [props[0].id]},
        attachment_ids=[attached["id"]])

    def fail(*args):
        raise ProviderError("Synthetic failure", "rate_limited", uncertain=False)

    assistant_runner.run(store, first["id"], actor.id, execute=fail)
    failed = assistant.get_run(store, actor.id, first["id"])
    if change == "scope":
        current = assistant.get_conversation(store, actor.id, chat["id"])
        assistant.edit_conversation(store, actor.id, chat["id"], ConversationEdit(**command(
            expected_revision=current["revision"], data_scope="none")))
    else:
        second = turn(actor, chat, content="Neue Auswahl", data_scope="authorized",
            **({"context": {"property_ids": [props[1].id]}} if change == "context" else
               {"excluded_attachment_ids": [attached["id"]]}))
        assistant_runner.run(store, second["id"], actor.id, execute=lambda *args: {"text": "Neue Auswahl verarbeitet."})
    before = assistant.list_records(store, actor.id, assistant.Run, conversation_id=chat["id"])["items"]
    with pytest.raises(HTTPException) as blocked:
        assistant.retry(store, actor.id, first["id"], RevisionCommand(**command(expected_revision=failed["revision"])))
    assert blocked.value.status_code == 409
    assert "Quellenfreigabe" in str(blocked.value.detail)
    after = assistant.list_records(store, actor.id, assistant.Run, conversation_id=chat["id"])["items"]
    assert [row["id"] for row in after] == [row["id"] for row in before]
