"""Assistant boundary oracles. Synthetic provider only; no CLI/login/model calls."""
import hashlib
import io
import zipfile
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.assistant_models import ConversationCreate, ProposalApply, ProposalPreview, RevisionCommand, RunCreate
from backend.db.assistant_models import AssistantConversationORM as Conversation
from backend.db.assistant_models import AssistantRunORM as Run
from backend.dependencies import store
from backend.finance_models import ReportDefinition
from backend.models import AccountCreate, BookingCreate, PortfolioCreate, PropertyCreate
from backend.services import assistant, assistant_runner
from backend.services import assistant_storage as db
from backend.services.file_storage import get_file_storage
from backend.services.integrations import connection_storage as dbs
from backend.services.jobs.core import MemoryJobStore
from backend.services.portfolio_scope import require_file_access, scope_context, scope_from_user
from backend.tests.test_finance_packages_v2 import clean  # noqa: F401


@pytest.fixture(autouse=True)
def isolated_assistant(monkeypatch):
    monkeypatch.setattr(assistant, "wake", lambda *args: None)
    for name, records in store.__dict__.get("_integration_connections", {}).items():
        if name.startswith("assistant_"):
            records.clear()
    yield
    for name, records in store.__dict__.get("_integration_connections", {}).items():
        if name.startswith("assistant_"):
            records.clear()


@pytest.fixture
def actor():
    return auth.register_user("assistant-reader", "assistant@example.test", "Lesender Nutzer", "Secret123", "readonly")


def command(**values):
    return dict(idempotency_key=str(uuid4()), **values)


def conversation(actor, **kwargs):
    return assistant.create_conversation(store, actor.id, ConversationCreate(**command(**kwargs)))


def submit(actor, chat, **kwargs):
    return assistant.submit(store, actor.id, chat["id"], RunCreate(**command(expected_revision=chat["revision"], content="Bitte prüfen", **kwargs)))


def fake_execute(actor_id, provider, request, emit, cancelled):
    assert not cancelled()
    assert request["messages"][-1]["content"] == "Bitte prüfen"
    emit({"type": "delta", "text": "Geprüft "})
    emit({"type": "delta", "text": "ohne Fachänderung"})
    return {"text": "Geprüft ohne Fachänderung", "proposals": []}


def test_http_readonly_chats_do_not_grant_domain_writes(actor):
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(actor.id)})
    payload = command(title="Private Prüfung", provider="local")
    created = client.post("/api/v1/assistant/conversations", json=payload)
    assert created.status_code == 200, created.text
    chat = created.json()
    assert created.headers["cache-control"] == "private, no-store"
    assert client.post("/api/v1/assistant/conversations", json=payload).json()["id"] == chat["id"]
    assert client.post("/api/v1/properties", json={"name": "Unzulässig"}).status_code == 403
    result = client.post(f'/api/v1/assistant/conversations/{chat["id"]}/runs', json=command(
        expected_revision=chat["revision"], content="Bitte prüfen", web_research=False))
    assert result.status_code == 200, result.text
    assistant_runner.run(store, result.json()["id"], actor.id, execute=fake_execute)
    finished = client.get('/api/v1/assistant/runs/' + result.json()["id"]).json()
    assert finished["state"] == "completed" and finished["response"] == "Geprüft ohne Fachänderung"
    assert client.get(f'/api/v1/assistant/conversations/{chat["id"]}/messages').json()["items"][-1]["role"] == "assistant"


def test_run_replay_conflict_and_cancel_do_not_duplicate_messages(actor):
    chat = conversation(actor)
    payload = RunCreate(**command(expected_revision=chat["revision"], content="Bitte prüfen"))
    first = assistant.submit(store, actor.id, chat["id"], payload)
    assert assistant.submit(store, actor.id, chat["id"], payload)["id"] == first["id"]
    with pytest.raises(HTTPException) as conflict:
        assistant.submit(store, actor.id, chat["id"], payload.model_copy(update={"content": "Andere Anfrage"}))
    assert conflict.value.status_code == 409
    cancel = RevisionCommand(**command(expected_revision=first["revision"]))
    assert assistant.cancel(store, actor.id, first["id"], cancel)["state"] == "cancelled"
    assert assistant.cancel(store, actor.id, first["id"], cancel)["state"] == "cancelled"
    messages = assistant.list_records(store, actor.id, assistant.Message, conversation_id=chat["id"])
    assert len(messages["items"]) == 1


def test_owner_boundary_applies_to_conversations_runs_and_attachments(actor):
    other = auth.register_user("assistant-other", "other@example.test", "Andere Person", "Secret123", "eigentuemer")
    chat = conversation(actor)
    attachment = assistant.add_attachment(store, actor.id, chat["id"], b"Geheimer Text", "Pruefung.txt")
    run = submit(actor, chat, attachment_ids=[attachment["id"]])
    for call in (lambda: assistant.get_conversation(store, other.id, chat["id"]),
                 lambda: assistant.get_run(store, other.id, run["id"]),
                 lambda: assistant.download(store, other.id, attachment["id"])):
        with pytest.raises(HTTPException) as denied:
            call()
        assert denied.value.status_code == 404
    other_user = auth.get_user_by_id(other.id)
    assert other_user is not None
    with scope_context(scope_from_user(other_user)):
        with pytest.raises(HTTPException) as denied:
            require_file_access("assistant-private/files/test")
        assert denied.value.status_code == 404


def test_attachment_bytes_hash_and_mime_are_verified_before_provider(actor):
    chat = conversation(actor)
    attached = assistant.add_attachment(store, actor.id, chat["id"], b"Original", "Bericht.txt")
    raw, data = assistant.download(store, actor.id, attached["id"])
    assert raw == b"Original" and data["sha256"] == hashlib.sha256(raw).hexdigest()
    with pytest.raises(HTTPException):
        assistant.add_attachment(store, actor.id, chat["id"], b"Kein PDF", "fake.pdf")
    run = submit(actor, chat, attachment_ids=[attached["id"]])
    get_file_storage().delete(data["_storage_key"])
    calls = []
    assistant_runner.run(store, run["id"], actor.id, execute=lambda *args: calls.append(args))
    assert calls == [] and assistant.get_run(store, actor.id, run["id"])["state"] == "blocked"


def test_unknown_provider_result_requires_explicit_new_run(actor):
    chat = conversation(actor)
    first = submit(actor, chat)
    calls = []
    def interrupted(*args):
        calls.append(1)
        raise RuntimeError("secret text must never escape")
    assistant_runner.run(store, first["id"], actor.id, execute=interrupted)
    unknown = assistant.get_run(store, actor.id, first["id"])
    assert unknown["state"] == "unknown" and "secret" not in str(unknown)
    assistant_runner.run(store, first["id"], actor.id, execute=interrupted)
    assert len(calls) == 1
    payload = RevisionCommand(**command(expected_revision=unknown["revision"]))
    repeated = assistant.retry(store, actor.id, first["id"], payload)
    assert repeated["id"] != first["id"] and repeated["retry_of"] == first["id"]
    assert assistant.retry(store, actor.id, first["id"], payload)["id"] == repeated["id"]
    assistant_runner.run(store, repeated["id"], actor.id, execute=fake_execute)
    assert assistant.get_run(store, actor.id, repeated["id"])["state"] == "completed"


def test_recovery_never_resubmits_expired_running_inference(actor):
    chat = conversation(actor)
    run = submit(actor, chat)
    with db.work(store, actor.id, write=True) as unit:
        row = db.get(unit, Run, run["id"])
        values = dbs.values(row)
        values.update(state="running", updated_at=dbs.now() - timedelta(seconds=300))
        dbs.put(unit, Run, values)
    jobs = MemoryJobStore()
    assistant_runner.recover(jobs, store)
    assert jobs.list_runs() == []
    assert assistant.get_run(store, actor.id, run["id"])["state"] == "unknown"
    fresh = assistant.get_conversation(store, actor.id, chat["id"])
    # A terminal old wakeup does not indefinitely lock the conversation.
    assert submit(actor, fresh)["state"] == "queued"


def test_cursor_history_is_owner_bound_and_has_no_duplicates(actor):
    chats = [conversation(actor, title="Gespräch " + str(i)) for i in range(7)]
    first = assistant.list_records(store, actor.id, limit=3)
    second = assistant.list_records(store, actor.id, limit=3, cursor=first["next_cursor"])
    third = assistant.list_records(store, actor.id, limit=3, cursor=second["next_cursor"])
    assert len({item["id"] for item in first["items"] + second["items"] + third["items"]}) == len(chats)
    assert third["next_cursor"] is None
    other = auth.register_user("cursor-other", "cursor@example.test", "Andere Person", "Secret123", "readonly")
    with pytest.raises(HTTPException) as invalid:
        assistant.list_records(store, other.id, limit=3, cursor=first["next_cursor"])
    assert invalid.value.status_code == 422


def test_source_revocation_blocks_queued_and_historical_content(actor):
    portfolio = store.create_portfolio(PortfolioCreate(name="Vertraulich"))
    house = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Quellhaus", property_type="residential"))
    chat = conversation(actor)
    run = submit(actor, chat, context={"property_ids": [house.id]})
    assistant_runner.run(store, run["id"], actor.id, execute=fake_execute)
    assert assistant.get_run(store, actor.id, run["id"])["state"] == "completed"
    auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
    with pytest.raises(HTTPException) as hidden:
        assistant.get_run(store, actor.id, run["id"])
    assert hidden.value.status_code == 404
    assert assistant.list_records(store, actor.id)["items"] == []


def test_changed_source_blocks_provider_without_hiding_owned_old_title(actor):
    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    house = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
    chat = conversation(actor)
    run = submit(actor, chat, context={"property_ids": [house.id]})
    store.update_property(house.id, PropertyCreate(portfolio_id=portfolio.id, name="Neue Quelle", property_type="residential"))
    calls = []
    assistant_runner.run(store, run["id"], actor.id, execute=lambda *args: calls.append(args))
    assert calls == [] and assistant.get_run(store, actor.id, run["id"])["state"] == "blocked"


def test_cancellation_during_stream_cannot_publish_a_completed_answer(actor):
    chat = conversation(actor)
    run = submit(actor, chat)
    def interrupted(actor_id, provider, request, emit, cancelled):
        emit({"type": "delta", "text": "Unvollständig"})
        current = assistant.get_run(store, actor.id, run["id"])
        assistant.cancel(store, actor.id, run["id"], RevisionCommand(**command(expected_revision=current["revision"])))
        assert cancelled()
        return {"text": "Darf nicht als fertig erscheinen"}
    assistant_runner.run(store, run["id"], actor.id, execute=interrupted)
    final = assistant.get_run(store, actor.id, run["id"])
    assert final["state"] == "cancelled" and final["response"] == "Unvollständig"
    assert len(assistant.list_records(store, actor.id, assistant.Message, conversation_id=chat["id"])["items"]) == 1


def test_private_payload_is_encrypted_and_json_snapshot_refuses_loss(actor):
    chat = conversation(actor, title="Privater Inhalt 123")
    with db.work(store, actor.id) as unit:
        row = db.get(unit, Conversation, chat["id"])
        assert "Privater Inhalt" not in row.payload_token and row.payload_token.startswith("enc:v1:")
    from backend.services.data_snapshot import SnapshotError, _require_full_private_backup
    with pytest.raises(SnapshotError):
        _require_full_private_backup(store)


def test_local_web_research_is_rejected_before_run_creation(actor):
    chat = conversation(actor)
    with pytest.raises(HTTPException) as invalid:
        submit(actor, chat, web_research=True)
    assert invalid.value.status_code == 422
    assert assistant.list_records(store, actor.id, Run, conversation_id=chat["id"])["items"] == []


def test_http_download_is_private_and_static_path_is_never_readable(actor):
    chat = conversation(actor)
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(actor.id)})
    uploaded = client.post(f'/api/v1/assistant/conversations/{chat["id"]}/attachments',
        files={"file": ("Prüfung.txt", b"Privater Anhang", "text/plain")})
    assert uploaded.status_code == 200, uploaded.text
    identifier = uploaded.json()["id"]
    downloaded = client.get(f"/api/v1/assistant/attachments/{identifier}/download")
    assert downloaded.status_code == 200 and downloaded.content == b"Privater Anhang"
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    _, data = assistant.download(store, actor.id, identifier)
    assert client.get("/uploads/" + data["_storage_key"]).status_code == 404
    assert client.get("/api/v1/files/read", params={"file_url": data["_storage_key"]}).status_code in (404, 405)


def proposed_task(actor):
    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    house = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
    chat = conversation(actor)
    run = submit(actor, chat, context={"property_ids": [house.id]})
    def candidate(actor_id, provider, request, emit, cancelled):
        source = request["context"]["sources"][0]
        evidence = {key: source[key] for key in ("kind", "id", "revision", "sha256")}
        return {"text": "Bitte Aufgabe prüfen.", "proposals": [{"kind": "task",
            "anchor": {"kind": "property", "id": house.id}, "evidence": [evidence],
            "values": {"title": "Fenster prüfen", "property_id": house.id}}]}
    assistant_runner.run(store, run["id"], actor.id, execute=candidate)
    return assistant.get_run(store, actor.id, run["id"])["proposals"][0]


def test_proposal_handoff_is_reviewed_idempotent_and_creates_only_a_draft(actor):
    auth.update_user(actor.id, {"role": "eigentuemer"})
    proposal = proposed_task(actor)
    before = len(store.list_tasks())
    review = assistant.proposal_preview(store, actor.id, proposal["id"], ProposalPreview(expected_revision=proposal["revision"]))["review"]
    payload = ProposalApply(**command(expected_revision=proposal["revision"], review_hash=review["review_hash"]))
    applied = assistant.decide_proposal(store, actor.id, proposal["id"], payload)
    assert applied["proposal"]["state"] == "applied"
    assert applied["handoff"]["domain_writes"] is False
    assert assistant.decide_proposal(store, actor.id, proposal["id"], payload)["handoff"]["draft_id"] == applied["handoff"]["draft_id"]
    assert len(store.list_tasks()) == before
    from backend.services.workspace import list_records
    drafts = list_records(store, actor.id, "drafts")
    assert len(drafts["items"]) == 1 and drafts["items"][0]["values"]["title"] == "Fenster prüfen"


def test_readonly_model_suggestion_cannot_bypass_actual_draft_permissions(actor):
    proposal = proposed_task(actor)
    with pytest.raises(HTTPException) as denied:
        assistant.proposal_preview(store, actor.id, proposal["id"], ProposalPreview(expected_revision=proposal["revision"]))
    assert denied.value.status_code == 403


def test_draft_and_proposal_decision_roll_back_together(actor, monkeypatch):
    auth.update_user(actor.id, {"role": "eigentuemer"})
    proposal = proposed_task(actor)
    review = assistant.proposal_preview(store, actor.id, proposal["id"], ProposalPreview(expected_revision=proposal["revision"]))["review"]
    def fail(*args):
        raise RuntimeError("Synthetic failure after draft and decision")
    monkeypatch.setattr(db, "receipt", fail)
    with pytest.raises(RuntimeError):
        assistant.decide_proposal(store, actor.id, proposal["id"], ProposalApply(**command(
            expected_revision=proposal["revision"], review_hash=review["review_hash"])))
    from backend.services.workspace import list_records
    assert list_records(store, actor.id, "drafts")["items"] == []
    with db.work(store, actor.id) as unit:
        assert db.get(unit, assistant.Proposal, proposal["id"]).state == "proposed"


def test_two_simultaneous_submissions_with_one_key_create_one_run(actor):
    from concurrent.futures import ThreadPoolExecutor
    chat = conversation(actor)
    payload = RunCreate(**command(expected_revision=chat["revision"], content="Bitte prüfen"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: assistant.submit(store, actor.id, chat["id"], payload), range(2)))
    assert results[0]["id"] == results[1]["id"]
    assert len(assistant.list_records(store, actor.id, Run, conversation_id=chat["id"])["items"]) == 1


def test_repeated_infrastructure_wakeup_failures_do_not_strand_authorized_work(actor):
    chat = conversation(actor)
    run = submit(actor, chat)
    jobs = MemoryJobStore()
    for index in range(2):
        assistant_runner.recover(jobs, store)
        claimed = jobs.claim("synthetic-worker-" + str(index), (assistant_runner.KIND,))
        assert claimed is not None
        jobs.fail(claimed, "Synthetic crash before domain claim", permanent=True)
    assistant_runner.recover(jobs, store)
    claimed = jobs.claim("synthetic-recovered-worker", (assistant_runner.KIND,))
    assert claimed is not None and claimed.payload["run_id"] == run["id"]
    assistant_runner.run(store, run["id"], actor.id, execute=fake_execute)
    assert assistant.get_run(store, actor.id, run["id"])["state"] == "completed"


def test_revocation_during_inference_stops_stream_and_hides_partial_content(actor):
    portfolio = store.create_portfolio(PortfolioCreate(name="Vertraulich"))
    house = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
    chat = conversation(actor)
    run = submit(actor, chat, context={"property_ids": [house.id]})
    def revoked(actor_id, provider, request, emit, cancelled):
        emit({"type": "delta", "text": "Historische Quelldetails"})
        auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
        assert cancelled()
        emit({"type": "delta", "text": "Darf nicht herausgegeben werden"})
        raise AssertionError("Revoked stream must stop")
    assistant_runner.run(store, run["id"], actor.id, execute=revoked)
    with pytest.raises(HTTPException) as denied:
        assistant.get_run(store, actor.id, run["id"])
    assert denied.value.status_code == 404
    assert assistant_runner.metadata_rows(store, ("blocked",))[0]["id"] == run["id"]


def test_ciphertext_cannot_be_moved_to_a_conversation_with_weaker_source_guards(actor):
    original, other = conversation(actor), conversation(actor)
    run = submit(actor, original)
    assistant_runner.run(store, run["id"], actor.id, execute=fake_execute)
    with db.work(store, actor.id, write=True) as unit:
        row = db.get(unit, Run, run["id"])
        dbs.put(unit, Run, {**dbs.values(row), "conversation_id": other["id"]})
    with pytest.raises(HTTPException) as rejected:
        assistant.get_run(store, actor.id, run["id"])
    assert rejected.value.status_code == 503


def test_report_scope_cannot_expand_beyond_explicitly_selected_sources(actor):
    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    selected = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Gewählt", property_type="residential"))
    foreign = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Nicht gewählt", property_type="residential"))
    chat = conversation(actor)
    with pytest.raises(HTTPException) as denied:
        submit(actor, chat, context={"property_ids": [selected.id]}, report=ReportDefinition(
            kind="cash-v2", as_of=date(2026, 1, 31), property_id=foreign.id))
    assert denied.value.status_code == 422
    assert assistant.list_records(store, actor.id, Run, conversation_id=chat["id"])["items"] == []


@pytest.mark.parametrize("drift", [False, True])
def test_provider_receives_exact_scoped_finance_and_changed_result_is_labelled_stale(actor, drift):
    portfolio = store.create_portfolio(PortfolioCreate(name="Schweiz", currency="CHF"))
    house = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Gewählt", property_type="residential"))
    foreign = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Andere Immobilie", property_type="residential"))
    account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Bank", account_type="bank"))
    for prop, amount in ((house, 0.1), (house, 0.2), (foreign, 1000)):
        store.create_booking(BookingCreate(account_id=account.id, property_id=prop.id, booking_date=date(2026, 1, 15), amount=amount))
    chat = conversation(actor)
    run = submit(actor, chat, context={"property_ids": [house.id]}, report=ReportDefinition(
        kind="cash-v2", as_of=date(2026, 1, 31), date_from=date(2026, 1, 1), property_id=house.id))
    calls, original_hash = [], []
    def execute(actor_id, provider, request, emit, cancelled):
        calls.append(1)
        finance = request["local_analysis"]["finance"]
        assert finance["totals"]["net"] == "0.30" and finance["currency"] == "CHF"
        original_hash.append(finance["result_hash"])
        if drift:
            store.create_booking(BookingCreate(account_id=account.id, property_id=house.id,
                booking_date=date(2026, 1, 20), amount=1))
        return {"text": "Der Saldo beträgt 0,30 CHF.", "proposals": []}
    assistant_runner.run(store, run["id"], actor.id, execute=execute)
    result = assistant.get_run(store, actor.id, run["id"])
    assert calls == [1] and result["state"] == "completed"
    assert result["financial_summary"]["result_hash"] == original_hash[0]
    assert result["financial_summary"]["currency"] == "CHF" and result["financial_summary"]["as_of"] == "2026-01-31"
    assert result["sources"][0]["id"] == house.id
    assert result["verification_status"] == ("stale" if drift else "current")
    assert result["response"].startswith("Hinweis:") is drift
    message = assistant.list_records(store, actor.id, assistant.Message, conversation_id=chat["id"])["items"][-1]
    assert message["sources"] == result["sources"] and message["verification_status"] == result["verification_status"]


@pytest.mark.parametrize("code", ["authentication_required", "rate_limited", "context_too_large", "protocol_incompatible", "provider_timeout"])
def test_provider_failure_preserves_known_safe_code_without_raw_error_content(actor, code):
    from backend.services.assistant_provider_protocol import ProviderError
    chat = conversation(actor)
    run = submit(actor, chat)
    def failed(*args):
        raise ProviderError("SECRET provider input / token", code, uncertain=code == "provider_timeout")
    assistant_runner.run(store, run["id"], actor.id, execute=failed)
    result = assistant.get_run(store, actor.id, run["id"])
    assert result["error"]["code"] == code
    assert "SECRET" not in str(result) and "token" not in result["error"]["message"]
    assert result["state"] == ("unknown" if code == "provider_timeout" else "failed")


def test_history_budget_omission_is_explicit_and_full_database_history_remains(actor):
    chat = conversation(actor)
    with db.work(store, actor.id, write=True) as unit:
        for content in ("A" * 100000, "B" * 70000):
            db.put(unit, assistant.Message, {"role": "assistant", "content": content, "run_id": None}, conversation_id=chat["id"])
    run = submit(actor, chat)
    def bounded(actor_id, provider, request, emit, cancelled):
        assert request["omissions"] and len(request["messages"]) == 2
        assert sum(len(item["content"]) for item in request["messages"]) < 128000
        return {"text": "Begrenzter Verarbeitungsschritt", "proposals": []}
    assistant_runner.run(store, run["id"], actor.id, execute=bounded)
    result = assistant.get_run(store, actor.id, run["id"])
    assert result["omissions"] and result["state"] == "completed"
    assert len(assistant.list_records(store, actor.id, assistant.Message, conversation_id=chat["id"])["items"]) == 4


def test_large_stream_delta_is_split_without_silently_losing_characters(actor):
    chat = conversation(actor)
    run = submit(actor, chat)
    text = "X" * 20001
    def large(actor_id, provider, request, emit, cancelled):
        emit({"type": "delta", "text": text})
        preview = assistant.get_run(store, actor.id, run["id"])
        assert preview["response"] == text
        return {"text": text, "proposals": []}
    assistant_runner.run(store, run["id"], actor.id, execute=large)
    result = assistant.get_run(store, actor.id, run["id"])
    assert result["response"] == text
    assert "".join(event["text"] for event in result["events"] if event["type"] == "delta") == text


def test_excess_proposals_have_an_explicit_processing_limit_notice(actor):
    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    house = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
    chat = conversation(actor)
    run = submit(actor, chat, context={"property_ids": [house.id]})
    def excess(actor_id, provider, request, emit, cancelled):
        source = request["context"]["sources"][0]
        evidence = {key: source[key] for key in ("kind", "id", "revision", "sha256")}
        proposal = {"kind": "task", "anchor": {"kind": "property", "id": house.id},
                    "evidence": [evidence], "values": {"title": "Vorschlag prüfen", "property_id": house.id}}
        return {"text": "Bitte die Vorschläge prüfen.", "proposals": [proposal] * 21}
    assistant_runner.run(store, run["id"], actor.id, execute=excess)
    result = assistant.get_run(store, actor.id, run["id"])
    assert len(result["proposals"]) == 20
    assert any("1 weitere" in event.get("message", "") for event in result["events"])


def docx_bytes(text="Haupttext", *, macro=False):
    from xml.sax.saxutils import escape
    buffer = io.BytesIO()
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    relationships = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    parts = {
        "[Content_Types].xml": '''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
          <Default Extension="xml" ContentType="application/xml"/>
          <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
          <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
          <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
          <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
        </Types>''',
        "_rels/.rels": f'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
          <Relationship Id="document" Type="{relationships}/officeDocument" Target="word/document.xml"/>
        </Relationships>''',
        "word/document.xml": f'''<w:document xmlns:w="{namespace}" xmlns:r="{relationships}"><w:body>
          <w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>
          <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Tabellenbeleg</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
          <w:sectPr><w:headerReference w:type="default" r:id="header"/><w:footerReference w:type="default" r:id="footer"/></w:sectPr>
        </w:body></w:document>''',
        "word/_rels/document.xml.rels": f'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
          <Relationship Id="header" Type="{relationships}/header" Target="header1.xml"/>
          <Relationship Id="footer" Type="{relationships}/footer" Target="footer1.xml"/>
        </Relationships>''',
        "word/header1.xml": f'<w:hdr xmlns:w="{namespace}"><w:p><w:r><w:t>Kopfzeile</w:t></w:r></w:p></w:hdr>',
        "word/footer1.xml": f'<w:ftr xmlns:w="{namespace}"><w:p><w:r><w:t>Fußzeile</w:t></w:r></w:p></w:ftr>',
    }
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for name, content in parts.items():
            package.writestr(name, content)
        if macro:
            package.writestr("word/vbaProject.bin", b"synthetic macro")
    return buffer.getvalue()


def test_docx_preserves_bytes_and_extracts_tables_headers_and_footers_locally(actor):
    chat = conversation(actor)
    raw = docx_bytes()
    uploaded = assistant.add_attachment(store, actor.id, chat["id"], raw, "Beleg.docx")
    original, data = assistant.download(store, actor.id, uploaded["id"])
    assert original == raw and uploaded["sha256"] == hashlib.sha256(raw).hexdigest()
    assert all(value in data["text"] for value in ("Haupttext", "Tabellenbeleg", "Kopfzeile", "Fußzeile"))
    assert not data["text_truncated"]


def test_docx_macro_is_rejected_and_long_text_has_visible_omission():
    with pytest.raises(HTTPException) as unsafe:
        assistant.inspect_attachment(docx_bytes(macro=True), "Makro.docx")
    assert unsafe.value.status_code == 422
    data = assistant.inspect_attachment(docx_bytes("X" * 65000), "Lang.docx")
    assert len(data["text"]) == 64000 and data["text_truncated"]
    assert any("64.000" in item for item in data["omissions"])


def test_attachment_limits_follow_settings_and_are_exposed_in_capabilities(actor, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "assistant_max_attachment_bytes", 10)
    monkeypatch.setattr(settings, "assistant_request_attachment_bytes", 11)
    capabilities = assistant.capabilities(actor.id)
    assert capabilities["attachment_max_bytes"] == 10 and capabilities["request_attachment_max_bytes"] == 11
    chat = conversation(actor)
    files = [assistant.add_attachment(store, actor.id, chat["id"], b"123456", name) for name in ("a.txt", "b.txt")]
    with pytest.raises(HTTPException) as too_big:
        submit(actor, chat, attachment_ids=[item["id"] for item in files])
    assert too_big.value.status_code == 413 and "11 Byte" in str(too_big.value.detail)
    monkeypatch.setattr(settings, "assistant_max_attachment_bytes", None)
    monkeypatch.setattr(settings, "max_upload_size_bytes", 4)
    assert assistant.attachment_limit() == 4
    with pytest.raises(HTTPException) as too_big:
        assistant.inspect_attachment(b"12345", "a.txt")
    assert too_big.value.status_code == 413 and "4 Byte" in str(too_big.value.detail)


def test_invalid_local_report_definition_is_http422_before_analysis(actor):
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(actor.id)})
    response = client.post("/api/v1/assistant/context/preview", json={"selection": {},
        "report": {"kind": "unbekannt", "as_of": "kein Datum"}})
    assert response.status_code == 422


def test_private_chat_and_command_replay_work_with_no_assigned_portfolios(actor):
    auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(actor.id)})
    payload = command(title="Mein privates Gespräch")
    first = client.post("/api/v1/assistant/conversations", json=payload)
    assert first.status_code == 200, first.text
    assert client.post("/api/v1/assistant/conversations", json=payload).json()["id"] == first.json()["id"]
    run_payload = command(expected_revision=1, content="Bitte prüfen")
    url = '/api/v1/assistant/conversations/' + first.json()["id"] + '/runs'
    first_run = client.post(url, json=run_payload)
    assert first_run.status_code == 200, first_run.text
    assert client.post(url, json=run_payload).json()["id"] == first_run.json()["id"]


def test_silent_live_provider_renews_lease_through_fresh_cancellation_checks(actor, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(assistant_runner, "monotonic", lambda: clock[0])
    chat = conversation(actor)
    run = submit(actor, chat)
    def thinking(actor_id, provider, request, emit, cancelled):
        # Controlled wall-time passage, with no deltas from the provider.
        with db.work(store, actor.id, write=True) as unit:
            row = db.get(unit, Run, run["id"])
            dbs.put(unit, Run, {**dbs.values(row), "updated_at": dbs.now() - timedelta(seconds=300)})
        clock[0] = 46.0
        assert not cancelled()
        jobs = MemoryJobStore()
        assistant_runner.recover(jobs, store)
        assert assistant.get_run(store, actor.id, run["id"])["state"] == "running"
        assert jobs.list_runs() == []
        return {"text": "Nach stillem Nachdenken abgeschlossen", "proposals": []}
    assistant_runner.run(store, run["id"], actor.id, execute=thinking)
    final = assistant.get_run(store, actor.id, run["id"])
    assert final["state"] == "completed" and len(final["events"]) == 1
