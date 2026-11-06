"""Demo assistant requests use stored provider and current owner/source rights."""
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend import auth, demo
from backend.app import app
from backend.assistant_models import ConversationEdit, RevisionCommand, RunCreate
from backend.config import settings
from backend.dependencies import store
from backend.models import PortfolioCreate, PropertyCreate
from backend.services import assistant, assistant_runner
from backend.services import assistant_storage as db
from backend.tests.test_assistant_workspace import clean as clean  # noqa: F401
from backend.tests.test_assistant_workspace import command, conversation
from backend.tests.test_assistant_workspace import isolated_assistant as isolated_assistant  # noqa: F401


@pytest.fixture
def actor():
    return auth.register_user("demo-reader", "demo-reader@example.test", "Demoprüfung", "Secret123", "readonly")


@pytest.fixture
def demo_client(actor, monkeypatch):
    # Exercise the same central policy as the production outer demo middleware,
    # while retaining all real authentication, portfolio and DB middleware.
    monkeypatch.setattr(settings, "immo_demo", True)
    outer = FastAPI()

    @outer.middleware("http")
    async def outbound_guard(request, call_next):
        if demo.blocked_action(request.method, request.url.path):
            return JSONResponse(status_code=409, content={"code": "DEMO_EXTERNAL_ACTION_DISABLED"})
        return await call_next(request)

    outer.mount("/", app)
    return TestClient(outer, headers={"Authorization": "Bearer " + auth.create_access_token(actor.id)})


def run_payload(chat, **values):
    return command(expected_revision=chat["revision"], content="Bitte lokal prüfen", **values)


def failed_run(actor, chat):
    first = assistant.submit(store, actor.id, chat["id"], RunCreate(**run_payload(chat)))
    return assistant.cancel(store, actor.id, first["id"], RevisionCommand(**command(expected_revision=first["revision"])))


def test_demo_local_run_submit_and_retry_complete_without_provider_or_network(actor, demo_client, monkeypatch):
    portfolio = store.create_portfolio(PortfolioCreate(name="Prüfbestand"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Rosenhöfe", property_type="residential"))
    chat = conversation(actor)
    response = demo_client.post(f'/api/v1/assistant/conversations/{chat["id"]}/runs', json=run_payload(
        chat, context={"property_ids": [prop.id]}))
    assert response.status_code == 200, response.text
    first = response.json()
    cancel_response = demo_client.post(f'/api/v1/assistant/runs/{first["id"]}/cancel',
        json=command(expected_revision=first["revision"]))
    assert cancel_response.status_code == 200, cancel_response.text
    cancelled = cancel_response.json()
    retried = demo_client.post(f'/api/v1/assistant/runs/{first["id"]}/retry',
        json=command(expected_revision=cancelled["revision"]))
    assert retried.status_code == 200, retried.text
    assert retried.json()["provider"] == "local" and retried.json()["retry_of"] == first["id"]

    from backend.services import assistant_providers

    def external_adapter(*args, **kwargs):
        pytest.fail("A local demo run must not load a cloud provider adapter")

    monkeypatch.setattr(assistant_providers, "_adapter", external_adapter)
    assistant_runner.run(store, retried.json()["id"], actor.id)
    result = demo_client.get('/api/v1/assistant/runs/' + retried.json()["id"]).json()
    assert result["state"] == "completed", result
    assert result["response"] and result["sources"][0]["id"] == prop.id


@pytest.mark.parametrize("provider", ["codex", "claude"])
@pytest.mark.parametrize("operation", ["submit", "retry", "cancel"])
def test_demo_external_runs_are_denied_before_replay_or_mutation(actor, demo_client, monkeypatch, provider, operation):
    # Existing failed/replayed requests may predate the current demo session.
    monkeypatch.setattr(settings, "immo_demo", False)
    chat = conversation(actor, provider=provider)
    payload = run_payload(chat)
    first = assistant.submit(store, actor.id, chat["id"], RunCreate(**payload))
    cancelled = assistant.cancel(store, actor.id, first["id"], RevisionCommand(**command(expected_revision=first["revision"])))
    monkeypatch.setattr(settings, "immo_demo", True)
    before = assistant.list_records(store, actor.id, assistant.Run, conversation_id=chat["id"])["items"]
    if operation == "submit":
        url, request = f'/api/v1/assistant/conversations/{chat["id"]}/runs', payload
    elif operation == "retry":
        url = f'/api/v1/assistant/runs/{first["id"]}/retry'
        request = command(expected_revision=cancelled["revision"])
    else:
        url = f'/api/v1/assistant/runs/{first["id"]}/cancel'
        request = command(expected_revision=cancelled["revision"])
    response = demo_client.post(url, json=request)
    assert response.status_code == 409, response.text
    with pytest.raises(HTTPException) as denied:
        if operation == "submit":
            assistant.submit(store, actor.id, chat["id"], RunCreate(**payload))
        else:
            getattr(assistant, operation)(store, actor.id, first["id"], RevisionCommand(**request))
    assert denied.value.status_code == 409
    assert assistant.list_records(store, actor.id, assistant.Run, conversation_id=chat["id"])["items"] == before


def test_demo_retry_uses_current_stored_conversation_provider(actor, demo_client):
    chat = conversation(actor)
    old = failed_run(actor, chat)
    current = assistant.get_conversation(store, actor.id, chat["id"])
    assistant.edit_conversation(store, actor.id, chat["id"], ConversationEdit(**command(
        expected_revision=current["revision"], provider="claude")))
    response = demo_client.post(f'/api/v1/assistant/runs/{old["id"]}/retry',
        json=command(expected_revision=old["revision"]))
    assert response.status_code == 409
    assert len(assistant.list_records(store, actor.id, assistant.Run, conversation_id=chat["id"])["items"]) == 1


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_demo_retry_replay_is_also_checked_against_current_provider(actor, demo_client, provider):
    chat = conversation(actor)
    old = failed_run(actor, chat)
    payload = command(expected_revision=old["revision"])
    retry = assistant.retry(store, actor.id, old["id"], RevisionCommand(**payload))
    assistant.cancel(store, actor.id, retry["id"], RevisionCommand(**command(expected_revision=retry["revision"])))
    current = assistant.get_conversation(store, actor.id, chat["id"])
    assistant.edit_conversation(store, actor.id, chat["id"], ConversationEdit(**command(
        expected_revision=current["revision"], provider=provider)))
    response = demo_client.post(f'/api/v1/assistant/runs/{old["id"]}/retry', json=payload)
    assert response.status_code == 409, response.text
    with pytest.raises(HTTPException) as denied:
        assistant.retry(store, actor.id, old["id"], RevisionCommand(**payload))
    assert denied.value.status_code == 409
    assert len(assistant.list_records(store, actor.id, assistant.Run, conversation_id=chat["id"])["items"]) == 2


@pytest.mark.parametrize("operation", ["submit", "retry", "cancel"])
def test_demo_local_run_rejects_provider_override_in_payload(actor, demo_client, operation):
    chat = conversation(actor)
    if operation == "submit":
        url, request = f'/api/v1/assistant/conversations/{chat["id"]}/runs', run_payload(chat)
    else:
        old = failed_run(actor, chat)
        url, request = f'/api/v1/assistant/runs/{old["id"]}/{operation}', command(expected_revision=old["revision"])
    response = demo_client.post(url, json={**request, "provider": "local"})
    assert response.status_code == 422


@pytest.mark.parametrize("operation", ["submit", "retry", "cancel"])
@pytest.mark.parametrize("identity", ["anonymous", "other-owner", "missing", "malformed", "corrupt"])
def test_demo_exception_does_not_bypass_identity_or_record_validation(actor, demo_client, operation, identity):
    chat = conversation(actor)
    old = failed_run(actor, chat) if operation != "submit" else None
    identifier = old["id"] if old else chat["id"]
    acting_id = actor.id
    if identity == "anonymous":
        demo_client.headers.pop("Authorization")
    elif identity == "other-owner":
        other = auth.register_user("demo-other", "demo-other@example.test", "Anderes Konto", "Secret123", "readonly")
        acting_id = other.id
        demo_client.headers["Authorization"] = "Bearer " + auth.create_access_token(other.id)
    elif identity == "missing":
        identifier = str(uuid4())
    elif identity == "malformed":
        identifier = "not-a-valid-identifier"
    else:
        with db.work(store, actor.id, write=True) as unit:
            row = db.conversation(unit, chat["id"], lock=True)
            row.payload_token = "damaged-protected-payload"
    url = (f'/api/v1/assistant/conversations/{identifier}/runs' if operation == "submit"
           else f'/api/v1/assistant/runs/{identifier}/{operation}')
    response = demo_client.post(url, json=run_payload(chat) if old is None else command(expected_revision=old["revision"]))
    assert response.status_code in {401, 403, 404, 409, 503}, response.text
    assert response.status_code != 200
    if identity != "anonymous":
        with pytest.raises(HTTPException) as denied:
            if old is None:
                assistant.submit(store, acting_id, identifier, RunCreate(**run_payload(chat)))
            else:
                getattr(assistant, operation)(store, acting_id, identifier,
                    RevisionCommand(**command(expected_revision=old["revision"])))
        assert denied.value.status_code in {404, 503}


def test_demo_local_run_still_rechecks_selected_property_rights(actor, demo_client):
    portfolio = store.create_portfolio(PortfolioCreate(name="Nicht freigegeben"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Fremdes Haus", property_type="residential"))
    owner = auth.register_user("restricted-demo", "restricted-demo@example.test", "Begrenztes Konto", "Secret123", "readonly",
        portfolio_access="selected", portfolio_ids=[])
    chat = conversation(owner)
    demo_client.headers["Authorization"] = "Bearer " + auth.create_access_token(owner.id)
    result = demo_client.post(f'/api/v1/assistant/conversations/{chat["id"]}/runs', json=run_payload(
        chat, context={"property_ids": [prop.id]}))
    assert result.status_code == 404, result.text
    assert assistant.list_records(store, owner.id, assistant.Run, conversation_id=chat["id"])["items"] == []


@pytest.mark.parametrize("path", [
    "/api/v1/assistant/conversations/missing/runs/extra",
    "/api/v1/assistant/conversations//runs",
    "/api/v1/assistant/runs/missing/cancel",
    "/api/v1/assistant/runs/missing/findings/finding/prepare-task",
    "/api/v1/assistant/connections/codex/login",
    "/api/v1/assistant/connections/claude/probe",
    "/api/v1/assistant/proposals/missing/apply",
])
def test_demo_run_exception_does_not_expand_other_action_routes(path):
    assert demo.blocked_action("POST", path)


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_demo_assistant_reads_remain_available(method):
    assert not demo.blocked_action(method, f"/api/v1/assistant/runs/{uuid4()}")
