"""Real accepted lifecycle evidence and opaque private work, Memory/SQLite."""

import hashlib
import json
from datetime import date

import pytest
from sqlalchemy import event, select

from backend.db.contract_lifecycle_models import ContractLifecycleCommandORM, ContractLifecycleDraftORM
from backend.models import ContractCreate, TenantCreate
from backend.services import contract_lifecycle as lifecycle
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.tenant_data_graph import TenantExportError
from backend.services.tenant_privacy import (
    PrivacyConflict,
    anonymize_tenant_profile,
    export_tenant_metadata,
    prepare_tenant_export,
    preview_tenant_anonymization,
)
from backend.tests import test_contract_lifecycle as fixtures

active = fixtures.active


def accepted(box, monkeypatch):
    monkeypatch.setattr(lifecycle, "today", lambda: date(2027, 1, 1))
    draft, _ = fixtures.create(box, reason="Confirmed tenant management Ä €")
    review = lifecycle.review_draft(box.store, box.contract.id, draft["id"], fixtures.command(draft, "review"), "actor")
    return lifecycle.confirm_draft(box.store, box.contract.id, draft["id"], fixtures.confirmation(review), "actor")


def hash_value(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def test_actual_confirmed_evidence_and_hashes_private_work_not_materialized(active, monkeypatch):
    row = accepted(active, monkeypatch)
    private, _ = fixtures.create(active, actor="other", key="other-private", reason="PRIVATE_OTHER_REASON_827")
    statements = []
    if active.db is not None:
        def observed(_connection, _cursor, sql, _parameters, context, _many):
            if "contract_lifecycle" in sql:
                statements.append((sql, context.execution_options))
        event.listen(active.engine, "before_cursor_execute", observed)
    with scope_context(scope_from_user(active.users["actor"])):
        graph = export_tenant_metadata(active.store, active.tenant.id)
    assert graph["schema_version"] == "tenant-data-graph/5"
    assert [item["id"] for item in graph["contract_lifecycle_drafts"]] == [row["id"]]
    assert [item["operation"] for item in graph["contract_lifecycle_commands"]] == ["confirm"]
    assert graph["contract_lifecycle_commands"][0]["result"]["data"]["reason"] == row["data"]["reason"]
    assert graph["scope"]["private_lifecycle_drafts"]["count"] == 1
    assert graph["scope"]["private_lifecycle_drafts"]["contents_exported"] is False
    serialized = json.dumps(graph, ensure_ascii=False)
    assert "PRIVATE_OTHER_REASON_827" not in serialized and private["id"] not in serialized
    for collection in ("contract_lifecycle_drafts", "contract_lifecycle_commands"):
        for item in graph[collection]:
            assert item["source_sha256"] == hash_value({key: value for key, value in item.items() if key != "source_sha256"})
    expected = [graph["contract_lifecycle_drafts"], graph["contract_lifecycle_commands"], graph["scope"]["private_lifecycle_drafts"]]
    assert graph["scope"]["contract_lifecycle"]["source_sha256"] == hash_value(expected)
    if active.db is not None:
        private_selects = [sql for sql, _ in statements if sql.startswith("SELECT contract_lifecycle_drafts.id, contract_lifecycle_drafts.revision")]
        assert private_selects
        assert all(".data" not in sql and ".review," not in sql and "actor_id" not in sql for sql in private_selects)
        assert any(options.get("yield_per") == 100 for _, options in statements)


def test_profile_anonymization_preserves_all_lifecycle_rows_and_explicit_retention(active, monkeypatch):
    row = accepted(active, monkeypatch)
    fixtures.create(active, actor="other", key="private", reason="PRIVATE_RETAINED_231")
    with scope_context(scope_from_user(active.users["actor"])):
        before = export_tenant_metadata(active.store, active.tenant.id)
        plan = preview_tenant_anonymization(active.store, active.tenant.id)
        assert plan["can_anonymize"]
        assert plan["retained_personal_evidence"]["contract_lifecycle_drafts"]["count"] == 1
        assert plan["retained_personal_evidence"]["private_lifecycle_drafts"]["contents_exported"] is False
        result = anonymize_tenant_profile(active.store, active.tenant.id,
            plan_hash=plan["plan_hash"], confirm_tenant_id=active.tenant.id)
        after = export_tenant_metadata(active.store, active.tenant.id)
    assert result["status"] == "profile_anonymized" and result["lifecycle_note"]
    assert before["contract_lifecycle_drafts"] == after["contract_lifecycle_drafts"]
    assert before["contract_lifecycle_commands"] == after["contract_lifecycle_commands"]
    assert after["contract_lifecycle_drafts"][0]["id"] == row["id"]
    assert active.store.get_tenant(active.tenant.id).archived


def test_private_revision_change_invalidates_anonymization_without_disclosing_reason(active, monkeypatch):
    accepted(active, monkeypatch)
    private, _ = fixtures.create(active, actor="other", key="private", reason="INITIAL_PRIVATE_92")
    with scope_context(scope_from_user(active.users["actor"])):
        plan = preview_tenant_anonymization(active.store, active.tenant.id)
    changed = fixtures.command(private, "edit-private")
    from backend.services.contract_lifecycle_types import DraftEdit
    lifecycle.edit_draft(active.store, active.contract.id, private["id"], DraftEdit(**changed.model_dump(),
        data=fixtures.data(reason="CHANGED_PRIVATE_94")), "other")
    with scope_context(scope_from_user(active.users["actor"])):
        with pytest.raises(PrivacyConflict):
            anonymize_tenant_profile(active.store, active.tenant.id,
                plan_hash=plan["plan_hash"], confirm_tenant_id=active.tenant.id)
        graph = export_tenant_metadata(active.store, active.tenant.id)
    assert "CHANGED_PRIVATE_94" not in json.dumps(graph)
    assert active.store.get_tenant(active.tenant.id).full_name == "Synthetic tenant"


def test_complete_private_download_contains_only_confirmed_results(active, monkeypatch, tmp_path):
    row = accepted(active, monkeypatch)
    fixtures.create(active, actor="other", key="private", reason="NEVER_DOWNLOAD_PRIVATE_77")
    with scope_context(scope_from_user(active.users["actor"])):
        compiled, _ = prepare_tenant_export(active.store, active.tenant.id, parent=tmp_path)
    try:
        payload = compiled.path.read_bytes()
        result = json.loads(payload)
        assert result["contract_lifecycle_commands"][0]["result"]["data"] == row["data"]
        assert b"NEVER_DOWNLOAD_PRIVATE_77" not in payload
        assert hashlib.sha256(payload).hexdigest() == compiled.manifest["sha256"]
    finally:
        compiled.close()


@pytest.mark.parametrize("kind", ["portfolio", "actor", "missing_confirmation", "missing_creation", "foreign_result"])
def test_corrupt_journal_never_silently_filters_export(active, monkeypatch, kind):
    row = accepted(active, monkeypatch)
    if active.db is None:
        draft = active.store.__dict__["contract_lifecycle_drafts"][row["id"]]
        commands = active.store.__dict__["contract_lifecycle_commands"]
        confirm = next(item for item in commands.values() if item.operation == "confirm")
        if kind == "portfolio":
            draft.portfolio_id = "foreign-corrupt-portfolio"
        elif kind == "actor":
            confirm.actor_id = "wrong-historical-actor"
        elif kind == "foreign_result":
            confirm.result = {**confirm.result, "new_tenant": {"full_name": "FOREIGN_PERSON_884"}}
        elif kind == "missing_creation":
            original = next(item for item in commands.values() if item.operation == "create")
            del commands[original.id]
        else:
            del commands[confirm.id]
    else:
        # Controlled corruption of only a synthetic database, after removing
        # the immutable command/draft trigger for this negative fixture.
        foreign_id = next(portfolio.id for portfolio in active.store.list_portfolios() if portfolio.id != active.p.id)
        confirm_result = active.db.scalar(select(ContractLifecycleCommandORM.result).where(
            ContractLifecycleCommandORM.operation == "confirm"))
        active.db.rollback()
        with active.engine.begin() as connection:
            triggers = connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('contract_lifecycle_drafts','contract_lifecycle_commands')").fetchall()
            for name, in triggers:
                connection.exec_driver_sql('DROP TRIGGER "' + name.replace('"', '""') + '"')
            if kind == "portfolio":
                connection.execute(ContractLifecycleDraftORM.__table__.update().where(ContractLifecycleDraftORM.id == row["id"])
                    .values(portfolio_id=foreign_id))
            elif kind == "actor":
                connection.execute(ContractLifecycleCommandORM.__table__.update().where(ContractLifecycleCommandORM.operation == "confirm")
                    .values(actor_id="wrong-historical-actor"))
            elif kind == "foreign_result":
                connection.execute(ContractLifecycleCommandORM.__table__.update().where(ContractLifecycleCommandORM.operation == "confirm")
                    .values(result={**confirm_result, "new_tenant": {"full_name": "FOREIGN_PERSON_884"}}))
            else:
                operation = "create" if kind == "missing_creation" else "confirm"
                connection.execute(ContractLifecycleCommandORM.__table__.delete().where(ContractLifecycleCommandORM.operation == operation))
        active.db.rollback()
    with scope_context(scope_from_user(active.users["actor"])):
        with pytest.raises(TenantExportError):
            export_tenant_metadata(active.store, active.tenant.id)


def test_another_tenant_never_receives_same_property_lifecycle_reason(active, monkeypatch):
    accepted(active, monkeypatch)
    other = active.store.create_tenant(TenantCreate(full_name="Other unrelated tenant"))
    active.store.create_contract(ContractCreate(contract_number="Other successor unrelated tenant",
        property_id=active.property.id, unit_id=active.unit.id, tenant_id=other.id,
        start_date="2027-01-01", status="draft"))
    graph = export_tenant_metadata(active.store, other.id)
    assert not graph["contract_lifecycle_drafts"] and not graph["contract_lifecycle_commands"]
    assert "Confirmed tenant management" not in json.dumps(graph)


def test_fresh_revocation_aborts_staged_download_without_publication(active, monkeypatch, tmp_path):
    accepted(active, monkeypatch)
    from backend.services import tenant_lifecycle_graph
    original = tenant_lifecycle_graph.append_lifecycle_graph
    def revoked(store, graph):
        result = original(store, graph)
        active.users["actor"]["portfolio_ids"] = []
        return result
    monkeypatch.setattr(tenant_lifecycle_graph, "append_lifecycle_graph", revoked)
    from fastapi import HTTPException
    with scope_context(scope_from_user(active.users["actor"])):
        with pytest.raises(HTTPException) as error:
            prepare_tenant_export(active.store, active.tenant.id, parent=tmp_path)
    assert error.value.status_code == 403
    assert not list(tmp_path.rglob("tenant-export.json"))


def test_superseded_and_current_confirmed_results_keep_original_reasons(active):
    old, _ = fixtures.create(active, reason="OLD_ACCEPTED_REASON")
    reviewed = lifecycle.review_draft(active.store, active.contract.id, old["id"], fixtures.command(old, "old-review"), "actor")
    old_result = lifecycle.confirm_draft(active.store, active.contract.id, old["id"], fixtures.confirmation(reviewed, "old-confirm"), "actor")
    new, _ = fixtures.create(active, actor="other", key="replacement", reason="NEW_ACCEPTED_REASON",
                             termination_end_date="2026-11-15")
    reviewed = lifecycle.review_draft(active.store, active.contract.id, new["id"], fixtures.command(new, "new-review"), "other")
    lifecycle.confirm_draft(active.store, active.contract.id, new["id"], fixtures.confirmation(reviewed, "new-confirm"), "other")
    with scope_context(scope_from_user(active.users["actor"])):
        graph = export_tenant_metadata(active.store, active.tenant.id)
    drafts = {item["id"]: item for item in graph["contract_lifecycle_drafts"]}
    commands = {item["draft_id"]: item for item in graph["contract_lifecycle_commands"]}
    assert drafts[old["id"]]["state"] == "superseded"
    assert drafts[old["id"]]["superseded_by_draft_id"] == new["id"]
    assert commands[old["id"]]["result"] == old_result
    assert commands[new["id"]]["result"]["data"]["reason"] == "NEW_ACCEPTED_REASON"


def test_other_current_manager_finalization_has_exact_separate_actor_evidence(active, monkeypatch):
    row, _ = fixtures.create(active)
    reviewed = lifecycle.review_draft(active.store, active.contract.id, row["id"], fixtures.command(row, "review"), "actor")
    pending = lifecycle.confirm_draft(active.store, active.contract.id, row["id"], fixtures.confirmation(reviewed), "actor")
    monkeypatch.setattr(lifecycle, "today", lambda: date(2027, 1, 1))
    finalized = lifecycle.finalize_draft(active.store, active.contract.id, row["id"], fixtures.confirmation(pending, "finish",
        expected_contract_etag=lifecycle.contract_etag(active.store.get_contract(active.contract.id))), "other")
    with scope_context(scope_from_user(active.users["other"])):
        graph = export_tenant_metadata(active.store, active.tenant.id)
    command = next(item for item in graph["contract_lifecycle_commands"] if item["operation"] == "finalize")
    assert command["actor_id"] == "other" and command["result"]["actor_id"] == "actor"
    assert command["result"] == finalized


def test_renewal_snapshot_names_exact_successor_and_keeps_parent_economics_historical(active):
    draft, _ = fixtures.create(active, operation="renewal", reason="Confirmed exact successor")
    reviewed = lifecycle.review_draft(active.store, active.contract.id, draft["id"], fixtures.command(draft, "review"), "actor")
    confirmed = lifecycle.confirm_draft(active.store, active.contract.id, draft["id"], fixtures.confirmation(reviewed), "actor")
    with scope_context(scope_from_user(active.users["actor"])):
        graph = export_tenant_metadata(active.store, active.tenant.id)
    historical = graph["contract_lifecycle_drafts"][0]
    successor = next(row for row in graph["contracts"] if row["id"] == confirmed["successor_contract_id"])
    assert historical["successor_contract_id"] == successor["id"]
    assert successor["tenant_id"] == graph["tenant"]["id"]
    assert successor["deposit_amount"] is None
    assert historical["review"]["source_contract"]["deposit_amount"] == 1500
