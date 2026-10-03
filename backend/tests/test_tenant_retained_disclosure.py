"""Real retained subject disclosure, including native PostgreSQL parity."""
# ruff: noqa: F811

import json
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import insert, text

from backend.db.operational_job_models import OperationalWorkItemORM
from backend.db.orm_models import RentChargeORM
from backend.models import ContractCreate, ContractPatch, RentChargeCreate, TenantCreate
from backend.services import operational_jobs as jobs
from backend.services import tenancy_workflow as workflow
from backend.services.operational_job_types import JobCommand, JobContinue, JobCreate
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.tenancy_workflow_types import PreviewTenancyChange, StartTenancyChange
from backend.services.tenancy_workflow_validation import _digest
from backend.services.tenant_privacy import export_tenant_metadata, preview_tenant_anonymization
from backend.tests.test_operational_recovery_guards import complete_domain_test_schema
from backend.tests.test_tenancy_workflow_core import box as box
from backend.tests.test_tenancy_workflow_core import preview_and_start, published_template, step


@pytest.fixture(autouse=True)
def complete_disclosure_schema(box):
    # Disclosure traverses the full financial domain. Register it before every
    # test so individually selected PostgreSQL cases cannot depend on imports
    # performed by an earlier test (notably credit_receipts).
    if box.engine is not None:
        complete_domain_test_schema(box)


def turnover(box):
    out = published_template(box, steps=[step("own-out", 0, title="OWN OUT TASK", anchor="previous_contract_end")])
    incoming = published_template(box, key="incoming", direction="move_in",
        steps=[step("foreign-in", 0, title="FOREIGN IN TASK PRIVATE", anchor="next_contract_start")])
    values = dict(property_id=box.property.id, unit_id=box.unit.id, previous_contract_id=box.previous.id,
                  next_contract_id=box.following.id, mode="turnover", move_out_handover_date=date(2026, 12, 31),
                  move_in_handover_date=date(2027, 1, 1), move_out_template_version_id=out["id"], move_in_template_version_id=incoming["id"])
    preview = workflow.preview_change(box.store, PreviewTenancyChange(**values), "manager")
    return workflow.start_change(box.store, StartTenancyChange(**values, idempotency_key="turnover",
        expected_revision="new", preview_hash=preview["preview_hash"], source_etags=preview["source_etags"]), "manager")


def test_turnover_projects_only_actual_historical_subject_direction_and_hashes(box):
    change = turnover(box)
    graph = export_tenant_metadata(box.store, box.previous.tenant_id)
    values = {name: rows for name, rows in graph.items() if name.startswith("tenancy_")}
    encoded = json.dumps(values)
    assert "OWN OUT TASK" in encoded and "FOREIGN IN TASK PRIVATE" not in encoded
    assert box.following.tenant_id not in encoded and box.following.id not in encoded
    assert len(graph["tenancy_changes"]) == 1
    assert {row["direction"] for row in graph["tenancy_workflow_step_instances"]} == {"move_out"}
    retained = graph["tenancy_changes"][0]
    assert retained["snapshot_sha256"] == change["snapshot_sha256"]
    proof = retained.pop("projection_sha256")
    assert proof == _digest(retained)
    assert retained["source_sha256"] != proof
    plan = preview_tenant_anonymization(box.store, box.previous.tenant_id)
    assert plan["retained_collections"]["tenancy_changes"] == 1
    assert plan["retained_personal_evidence"]["tenancy_changes"]["count"] == 1


def test_frozen_party_survives_supported_later_tenant_correction(box):
    if box.engine is not None:
        complete_domain_test_schema(box)
    change = turnover(box)
    corrected = box.store.create_tenant(TenantCreate(full_name="LATER CURRENT FOREIGN PARTY"))
    box.store._patch_entity("contract", box.previous.id, ContractPatch(tenant_id=corrected.id))
    graph = export_tenant_metadata(box.store, box.previous.tenant_id)
    assert graph["contracts"] == []
    assert graph["tenancy_changes"][0]["id"] == change["id"]
    assert graph["tenancy_changes"][0]["snapshot"]["previous_contract"]["tenant_id"] == box.previous.tenant_id
    assert "LATER CURRENT FOREIGN PARTY" not in json.dumps(graph)
    assert corrected.id not in json.dumps(graph)


def test_shared_job_exposes_only_owned_work_items_and_subject_local_counts(box):
    if box.engine is not None:
        complete_domain_test_schema(box)
    own = box.store.create_rent_charge(RentChargeCreate(contract_id=box.previous.id, month="2026-09", cold_rent=100))
    foreign = box.store.create_rent_charge(RentChargeCreate(contract_id=box.foreign_contract.id, month="2026-09", cold_rent=999))
    box.users["manager"]["portfolio_access"] = "all"
    job = jobs.create_job(box.store, JobCreate(idempotency_key="shared", as_of="2026-11-05", families=["overdue_rent_charge"]), "manager")
    claim = jobs.claim_lane(box.store, job["id"], "synthetic-worker", actor_id="manager")
    jobs.prepare_claim(box.store, claim, JobContinue(max_items=7))
    graph = export_tenant_metadata(box.store, box.previous.tenant_id)
    assert [row["source_id"] for row in graph["operational_work_items"]] == [own.id]
    assert graph["operational_jobs"] == [{"id": job["id"], "subject_work_item_count": 1}]
    assert graph["operational_job_lanes"][0]["subject_work_item_count"] == 1
    encoded = json.dumps({name: rows for name, rows in graph.items() if name.startswith("operational_")})
    assert foreign.id not in encoded and "lease_token" not in encoded and "parameters" not in encoded
    assert "scanned" not in encoded and "scope_hash" not in encoded


def test_real_evidence_link_binding_survives_disclosure(box):
    from backend.tests import test_tenancy_workflow_core as core
    core.test_finalized_handover_and_meter_are_immutable_and_valid_evidence(box)
    graph = export_tenant_metadata(box.store, box.previous.tenant_id)
    assert len(graph["tenancy_workflow_evidence_links"]) == 1
    assert graph["tenancy_workflow_evidence_links"][0]["kind"] == "meter_reading"


def test_manipulated_retained_parent_is_not_silently_filtered(box):
    change = turnover(box)
    own_step = next(row for row in change["steps"] if row["direction"] == "move_out")
    if box.engine is None:
        box.store.__dict__["tenancy_workflow_step_instances"][own_step["id"]].portfolio_id = box.foreign_portfolio.id
    else:
        box.db.rollback()
        with box.engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.exec_driver_sql("SET LOCAL session_replication_role=replica")
            else:
                for name in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='tenancy_workflow_step_instances'").scalars().all():
                    connection.exec_driver_sql('DROP TRIGGER "' + name + '"')
            connection.execute(text("UPDATE tenancy_workflow_step_instances SET portfolio_id=:portfolio WHERE id=:id"),
                               {"portfolio": box.foreign_portfolio.id, "id": own_step["id"]})
    from backend.services.tenant_data_graph import TenantExportError
    with pytest.raises(TenantExportError):
        export_tenant_metadata(box.store, box.previous.tenant_id)


def test_rights_revocation_during_snapshot_never_returns_retained_graph(box, monkeypatch):
    turnover(box)
    from backend.services import tenant_retained_graph as retained
    original = retained._jobs

    def revoked(store, graph):
        original(store, graph)
        box.users["manager"]["portfolio_ids"] = []

    monkeypatch.setattr(retained, "_jobs", revoked)
    with scope_context(scope_from_user(box.users["manager"])):
        with pytest.raises(HTTPException) as error:
            export_tenant_metadata(box.store, box.previous.tenant_id)
    assert error.value.status_code == 403


def test_workflow_mutation_changes_reviewed_hash_and_preserves_history(box):
    template = published_template(box)
    _, _, change = preview_and_start(box, template)
    plan = preview_tenant_anonymization(box.store, box.previous.tenant_id)
    item = change["steps"][0]
    from backend.services.tenancy_workflow_types import UpdateStep
    workflow.update_step(box.store, change["id"], item["id"], UpdateStep(idempotency_key="later-step",
        expected_revision=item["revision"], expected_change_revision=change["revision"], state="in_progress"), "tech")
    fresh = preview_tenant_anonymization(box.store, box.previous.tenant_id)
    assert fresh["plan_hash"] != plan["plan_hash"]
    from backend.services.tenant_privacy import PrivacyConflict, anonymize_tenant_profile
    with pytest.raises(PrivacyConflict):
        anonymize_tenant_profile(box.store, box.previous.tenant_id, plan_hash=plan["plan_hash"], confirm_tenant_id=box.previous.tenant_id)
    assert not box.store.get_tenant(box.previous.tenant_id).archived


def test_coherent_snapshot_retains_original_facts_when_writer_commits_between_families(box, monkeypatch):
    template = published_template(box)
    _, _, change = preview_and_start(box, template)
    from backend.services import tenant_retained_graph as retained
    from backend.services.tenancy_workflow_types import UpdateStep
    original = retained._jobs
    item = change["steps"][0]

    def writer(store, graph):
        workflow.update_step(box.store, change["id"], item["id"], UpdateStep(idempotency_key="during-export",
            expected_revision=item["revision"], expected_change_revision=change["revision"], state="in_progress"), "tech")
        original(store, graph)

    monkeypatch.setattr(retained, "_jobs", writer)
    graph = export_tenant_metadata(box.store, box.previous.tenant_id)
    assert graph["tenancy_workflow_step_instances"][0]["state"] == "open"
    assert workflow.get_change(box.store, change["id"], "manager")["steps"][0]["state"] == "in_progress"
    assert len(graph["tenancy_workflow_commands"]) == 3


def test_more_than_ten_thousand_actual_subject_items_have_no_prefix_cap_or_global_parent_projection(box):
    if box.engine is not None:
        complete_domain_test_schema(box)
    base = box.store.create_rent_charge(RentChargeCreate(contract_id=box.previous.id, month="2026-09", cold_rent=100))
    box.users["manager"]["portfolio_access"] = "all"
    job = jobs.create_job(box.store, JobCreate(idempotency_key="large-subject", as_of="2026-11-05", families=["overdue_rent_charge"]), "manager")
    lane_id = job["lanes"][0]["id"]
    charges, items = [], []
    for index in range(10003):
        source_id = "large-source-" + str(index).zfill(5)
        charge = base.model_copy(update={"id": source_id, "month": f"{3000 + index // 12}-{index % 12 + 1:02}"})
        charges.append({column.name: getattr(charge, column.name) for column in RentChargeORM.__table__.columns})
        items.append(dict(id=str(uuid4()), job_id=job["id"], lane_id=lane_id, kind="source", action_key="overdue_rent_charge:" + source_id,
                          source_id=source_id, planned_revision=_digest(charge.model_dump(mode="json")), state="ready", revision=1,
                          attempts=0, next_attempt_at=None, error_code=None, result={}, created_at=jobs._clock()))
    if box.engine is not None:
        box.db.rollback()
        with box.engine.begin() as connection:
            connection.execute(insert(RentChargeORM), charges)
            connection.execute(insert(OperationalWorkItemORM), items)
    else:
        box.store.__dict__["rent_charges"].update({row["id"]: base.model_copy(update=row) for row in charges})
        box.store.__dict__.setdefault("operational_work_items", {}).update({row["id"]: OperationalWorkItemORM(**row) for row in items})
    graph = export_tenant_metadata(box.store, box.previous.tenant_id)
    assert len(graph["operational_work_items"]) == 10003
    assert {row["source_id"] for row in graph["operational_work_items"]} == {row["source_id"] for row in items}
    assert graph["operational_jobs"][0]["subject_work_item_count"] == 10003


@pytest.mark.parametrize("corrupt", [False, True])
def test_actual_done_job_effect_is_bound_and_foreign_effect_replacement_is_rejected(box, corrupt):
    if box.engine is not None:
        complete_domain_test_schema(box)
    box.store.create_rent_charge(RentChargeCreate(contract_id=box.previous.id, month="2026-09", cold_rent=100))
    box.users["manager"]["portfolio_access"] = "all"
    job = jobs.create_job(box.store, JobCreate(idempotency_key="done-subject", as_of="2026-11-05", families=["overdue_rent_charge"]), "manager")
    jobs.continue_job(box.store, job["id"], JobContinue(max_items=7), "manager")
    if corrupt:
        if box.engine is None:
            row = next(iter(box.store.__dict__["operational_work_items"].values()))
            row.result = row.result | {"target_id": "foreign-private-target"}
        else:
            box.db.rollback()
            with box.engine.begin() as connection:
                raw = connection.execute(text("SELECT id,result FROM operational_work_items WHERE job_id=:id"), {"id": job["id"]}).one()
                result = json.loads(raw.result) if isinstance(raw.result, str) else raw.result
                result["target_id"] = "foreign-private-target"
                connection.execute(text("UPDATE operational_work_items SET result=:result WHERE id=:id"), {"result": json.dumps(result), "id": raw.id})
        from backend.services.tenant_data_graph import TenantExportError
        with pytest.raises(TenantExportError):
            export_tenant_metadata(box.store, box.previous.tenant_id)
    else:
        graph = export_tenant_metadata(box.store, box.previous.tenant_id)
        assert graph["operational_work_items"][0]["state"] == "done"
        assert graph["operational_work_items"][0]["result"]["target_id"] is not None


def test_stored_retry_receipt_is_subject_projected_without_global_revision_or_lanes(box):
    if box.engine is not None:
        complete_domain_test_schema(box)
    box.store.create_rent_charge(RentChargeCreate(contract_id=box.previous.id, month="2026-09", cold_rent=100))
    box.users["manager"]["portfolio_access"] = "all"
    job = jobs.create_job(box.store, JobCreate(idempotency_key="retry-subject", as_of="2026-11-05", families=["overdue_rent_charge"]), "manager")
    claim = jobs.claim_lane(box.store, job["id"], "failed-worker", actor_id="manager")
    jobs.prepare_claim(box.store, claim, JobContinue(max_items=7))
    item = jobs.item_page(box.store, job["id"], actor_id="manager")["items"][0]
    if box.engine is None:
        box.store.__dict__["operational_work_items"][item["id"]].state = "attention"
    else:
        box.db.rollback()
        with box.engine.begin() as connection:
            connection.execute(text("UPDATE operational_work_items SET state='attention' WHERE id=:id"), {"id": item["id"]})
    current = jobs.read_job(box.store, job["id"], "manager")
    jobs.retry_item(box.store, job["id"], item["id"], JobCommand(idempotency_key="retry-own-item", expected_revision=current["revision"]), "manager")
    graph = export_tenant_metadata(box.store, box.previous.tenant_id)
    receipt = next(row for row in graph["operational_work_items"] if row["kind"] == "command")
    assert receipt["result"]["request"] == {"operation": "retry", "source_id": item["id"]}
    assert receipt["result"]["receipt"] == {"id": job["id"]}
    assert "expected_revision" not in json.dumps(receipt)


def test_hidden_historical_portfolio_requires_complete_scope_without_disclosing_hidden_values(box):
    source = box.store.create_contract(ContractCreate(contract_number="OTHER PORTFOLIO SUBJECT", property_id=box.foreign_property.id,
        unit_id=box.foreign_unit.id, tenant_id=box.previous.tenant_id, start_date=date(2020, 1, 1), end_date=date(2020, 12, 31), status="terminated"))
    template = published_template(box, property_id=box.foreign_property.id, key="hidden-subject-template",
                                  steps=[step("hidden", 0, title="HIDDEN SUBJECT TITLE", anchor="previous_contract_end")])
    values = dict(property_id=box.foreign_property.id, unit_id=box.foreign_unit.id, previous_contract_id=source.id,
                  mode="move_out", move_out_template_version_id=template["id"])
    preview = workflow.preview_change(box.store, PreviewTenancyChange(**values), "foreign-manager")
    hidden = workflow.start_change(box.store, StartTenancyChange(**values, idempotency_key="hidden-subject-start", expected_revision="new",
        preview_hash=preview["preview_hash"], source_etags=preview["source_etags"]), "foreign-manager")
    with scope_context(scope_from_user(box.users["manager"])):
        with pytest.raises(HTTPException) as error:
            export_tenant_metadata(box.store, box.previous.tenant_id)
    assert error.value.status_code == 403
    assert hidden["id"] not in str(error.value.detail) and "HIDDEN SUBJECT TITLE" not in str(error.value.detail)


@pytest.mark.parametrize("corruption", ["snapshot_digest", "foreign_response", "terminal_actor"])
def test_corrupt_retained_hash_receipt_or_terminal_actor_never_publishes_partial_facts(box, corruption):
    from backend.db.tenancy_workflow_models import TenancyChangeORM, WorkflowCommandORM, WorkflowStepInstanceORM
    from backend.services.tenancy_workflow_types import UpdateStep
    from backend.services.tenant_data_graph import TenantExportError

    change = turnover(box)
    item = next(row for row in change["steps"] if row["direction"] == "move_out")
    if corruption == "snapshot_digest":
        model, identifier, values = TenancyChangeORM, change["id"], {"snapshot_sha256": "a" * 64}
    elif corruption == "terminal_actor":
        workflow.update_step(box.store, change["id"], item["id"], UpdateStep(idempotency_key="terminal-subject",
            expected_revision=item["revision"], expected_change_revision=change["revision"], state="completed"), "tech")
        model, identifier, values = WorkflowStepInstanceORM, item["id"], {"completed_by": "foreign-manager"}
    else:
        if box.engine is None:
            receipt = next(row for row in box.store.__dict__["tenancy_workflow_commands"].values()
                           if row.operation == "start_tenancy_change")
        else:
            receipt = box.db.query(WorkflowCommandORM).filter_by(operation="start_tenancy_change").one()
        response = json.loads(json.dumps(receipt.response))
        response["foreign_private_blob"] = {"tenant": box.following.tenant_id, "text": "FOREIGN PRIVATE RECEIPT"}
        model, identifier, values = WorkflowCommandORM, receipt.id, {"response": response}
    if box.engine is None:
        row = box.store.__dict__[model.__tablename__][identifier]
        for field, value in values.items():
            setattr(row, field, value)
    else:
        box.db.rollback()
        with box.engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.exec_driver_sql("SET LOCAL session_replication_role=replica")
            else:
                for name in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='" + model.__tablename__ + "'").scalars().all():
                    connection.exec_driver_sql('DROP TRIGGER "' + name + '"')
            connection.execute(model.__table__.update().where(model.id == identifier).values(**values))
    with pytest.raises(TenantExportError):
        export_tenant_metadata(box.store, box.previous.tenant_id)


@pytest.mark.parametrize("partial", [False, True])
def test_actual_old_sql_images_allow_wholly_absent_families_but_refuse_partial_family(box, partial):
    from backend.db.operational_scheduler_models import OperationalSchedulerORM
    from backend.db.orm_models import Base
    from backend.db.tenancy_workflow_models import WorkflowCommandORM
    from backend.services.tenant_data_graph import TenantExportError
    from backend.services.tenant_retained_graph import JOBS, WORKFLOW

    if box.engine is None:
        if partial:
            pytest.skip("Memory has lazy collections, not persistent table-family images")
    else:
        box.db.rollback()
        tables = [WorkflowCommandORM.__table__] if partial else [model.__table__ for model in (WORKFLOW | JOBS).values()]
        if not partial:
            # A pre-job image predates its referencing automatic coordinator too.
            tables.append(OperationalSchedulerORM.__table__)
        Base.metadata.drop_all(box.engine, tables=tables)
    if partial:
        with pytest.raises(TenantExportError):
            export_tenant_metadata(box.store, box.previous.tenant_id)
    else:
        graph = export_tenant_metadata(box.store, box.previous.tenant_id)
        assert all(graph[name] == [] for name in WORKFLOW | JOBS)
        assert graph["tenant"]["id"] == box.previous.tenant_id


@pytest.mark.parametrize("corrupt", [False, True])
def test_actual_correspondence_calendar_job_discloses_approved_hash_and_rejects_unbound_effect(box, corrupt):
    from backend.services.tenant_data_graph import TenantExportError
    from backend.tests.test_contract_correspondence import approved

    if box.engine is not None:
        complete_domain_test_schema(box)
    box.users["actor"] = box.users["manager"] | {"id": "actor", "portfolio_access": "all"}
    published = approved(SimpleNamespace(store=box.store, contract=box.previous))
    job = jobs.create_job(box.store, JobCreate(idempotency_key="actual-approved-calendar", as_of="2026-11-05",
        families=["correspondence"]), "actor")
    done = jobs.continue_job(box.store, job["id"], JobContinue(max_items=7), "actor")
    assert done["state"] == "completed" and len(box.store.list_calendar_events()) == 1
    if corrupt:
        if box.engine is None:
            row = next(iter(box.store.__dict__["operational_work_items"].values()))
            row.result = {key: value for key, value in row.result.items() if key != "effect_key"}
        else:
            box.db.rollback()
            with box.engine.begin() as connection:
                raw = connection.execute(OperationalWorkItemORM.__table__.select().where(OperationalWorkItemORM.job_id == job["id"])).mappings().one()
                result = {key: value for key, value in raw["result"].items() if key != "effect_key"}
                connection.execute(OperationalWorkItemORM.__table__.update().where(OperationalWorkItemORM.id == raw["id"]).values(result=result))
        with pytest.raises(TenantExportError):
            export_tenant_metadata(box.store, box.previous.tenant_id)
    else:
        graph = export_tenant_metadata(box.store, box.previous.tenant_id)
        item = graph["operational_work_items"][0]
        assert item["state"] == "done" and item["source_id"] == published["id"]
        assert item["result"]["review_hash"] == published["review_hash"]
        assert item["result"]["target_id"] == box.store.list_calendar_events()[0].id


@pytest.mark.parametrize("corruption", ["foreign_top_source", "other_job_item"])
def test_retry_receipt_cannot_publish_foreign_top_reference_or_cross_job_assignment(box, corruption):
    from backend.services.tenant_data_graph import TenantExportError

    if box.engine is not None:
        complete_domain_test_schema(box)
    box.store.create_rent_charge(RentChargeCreate(contract_id=box.previous.id, month="2026-09", cold_rent=100))
    box.users["manager"]["portfolio_access"] = "all"
    job_items = []
    for key in ("first", "second"):
        job = jobs.create_job(box.store, JobCreate(idempotency_key="parent-" + key, as_of="2026-11-05", families=["overdue_rent_charge"]), "manager")
        claim = jobs.claim_lane(box.store, job["id"], "worker-" + key, actor_id="manager")
        jobs.prepare_claim(box.store, claim, JobContinue(max_items=7))
        item = jobs.item_page(box.store, job["id"], actor_id="manager")["items"][0]
        job_items.append((job, item))
    job, item = job_items[0]
    if box.engine is None:
        box.store.__dict__["operational_work_items"][item["id"]].state = "attention"
    else:
        box.db.rollback()
        with box.engine.begin() as connection:
            connection.execute(OperationalWorkItemORM.__table__.update().where(OperationalWorkItemORM.id == item["id"]).values(state="attention"))
    current = jobs.read_job(box.store, job["id"], "manager")
    jobs.retry_item(box.store, job["id"], item["id"], JobCommand(idempotency_key="corrupt-retry-origin", expected_revision=current["revision"]), "manager")
    if box.engine is None:
        receipt = next(row for row in box.store.__dict__["operational_work_items"].values() if row.kind == "command")
        source = {column.name: getattr(receipt, column.name) for column in OperationalWorkItemORM.__table__.columns}
    else:
        box.db.rollback()
        with box.engine.connect() as connection:
            source = dict(connection.execute(OperationalWorkItemORM.__table__.select().where(OperationalWorkItemORM.kind == "command")).mappings().one())
    if corruption == "foreign_top_source":
        values = {"source_id": "FOREIGN PRIVATE SOURCE ID"}
    else:
        result = json.loads(json.dumps(source["result"]))
        result["request"]["source_id"] = job_items[1][1]["id"]
        result["request_hash"] = _digest(result["request"])
        values = {"result": result}
    if box.engine is None:
        for field, value in values.items():
            setattr(receipt, field, value)
    else:
        with box.engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.exec_driver_sql("SET LOCAL session_replication_role=replica")
            else:
                connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_operational_command_update")
            connection.execute(OperationalWorkItemORM.__table__.update().where(OperationalWorkItemORM.id == source["id"]).values(**values))
    with pytest.raises(TenantExportError):
        export_tenant_metadata(box.store, box.previous.tenant_id)
