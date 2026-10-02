"""P1/P2 tenancy workflow core gates: Memory, SQLite and isolated PostgreSQL."""

import os
from datetime import date
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import create_engine, delete, event, insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend import auth
from backend.db.document_version_models import DocumentVersionORM  # noqa: F401
from backend.db.orm_models import Base, HandoverProtocolORM, MeterReadingORM
from backend.db.tenancy_workflow_models import (
    TenancyChangeORM,
    WorkflowCommandORM,
    WorkflowEvidenceLinkORM,
    WorkflowStepInstanceORM,
    WorkflowTemplateStepORM,
    WorkflowTemplateVersionORM,
)
from backend.models import (
    ContractCreate,
    DocumentCreate,
    HandoverProtocolCreate,
    HandoverProtocolPatch,
    MeterReadingCreate,
    MeterReadingPatch,
    PortfolioCreate,
    PropertyCreate,
    TaskCreate,
    TaskPatch,
    TenantCreate,
    UnitCreate,
)
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import document_versions
from backend.services import tenancy_workflow as workflow
from backend.services.tenancy_workflow_types import (
    AddEvidence,
    CompleteTenancyChange,
    CreateStepTask,
    CreateTemplate,
    CreateTemplateVersion,
    EvidenceInput,
    PublishTemplateVersion,
    ReanchorPreview,
    ReanchorTenancyChange,
    StartTenancyChange,
    TemplateStepInput,
    UpdateStep,
    UpdateTemplateVersion,
)
from backend.storage import InMemoryStore, NotFoundError, ValidationError


@pytest.fixture(params=["memory", "sqlite", "postgres"])
def box(request, tmp_path, monkeypatch):
    engine = db = admin = None
    schema = None
    if request.param == "sqlite":
        engine = create_engine(
            "sqlite:///" + (tmp_path / "workflow.db").as_posix(),
            connect_args={"check_same_thread": False, "timeout": 20},
        )

        @event.listens_for(engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")

        Base.metadata.create_all(engine)
        migration = import_module(
            "backend.db.migrations.versions.b2a2b3c4d5e6_tenancy_workflows"
        )
        with engine.begin() as connection:
            migration.install_guards(connection)
        db = Session(engine)
        store = SQLAlchemyStore(db)
    elif request.param == "postgres":
        source = os.getenv("TEST_SERVER_DATABASE_URL")
        if not source:
            pytest.skip("TEST_SERVER_DATABASE_URL disposable PostgreSQL is not configured")
        url = make_url(source)
        if url.get_backend_name() != "postgresql":
            pytest.fail("TEST_SERVER_DATABASE_URL must reference PostgreSQL")
        schema = "tenancy_workflow_" + uuid4().hex
        admin = create_engine(url, hide_parameters=True, pool_pre_ping=True)
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        scoped = url.update_query_dict({"options": "-csearch_path=" + schema})
        engine = create_engine(scoped, hide_parameters=True, pool_pre_ping=True)
        Base.metadata.create_all(engine)
        migration = import_module(
            "backend.db.migrations.versions.b2a2b3c4d5e6_tenancy_workflows"
        )
        with engine.begin() as connection:
            migration.install_guards(connection)
        db = Session(engine)
        store = SQLAlchemyStore(db)
    else:
        store = InMemoryStore()

    portfolio = store.create_portfolio(PortfolioCreate(name="Workflow A"))
    foreign_portfolio = store.create_portfolio(PortfolioCreate(name="Workflow B"))
    prop = store.create_property(
        PropertyCreate(
            portfolio_id=portfolio.id,
            name="Property A",
            property_type="residential",
        )
    )
    unit = store.create_unit(
        UnitCreate(property_id=prop.id, label="A", unit_type="apartment")
    )
    tenant_old = store.create_tenant(TenantCreate(full_name="Old synthetic tenant"))
    tenant_new = store.create_tenant(TenantCreate(full_name="New synthetic tenant"))
    previous = store.create_contract(
        ContractCreate(
            contract_number="OLD-1",
            property_id=prop.id,
            unit_id=unit.id,
            tenant_id=tenant_old.id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status="terminated",
        )
    )
    following = store.create_contract(
        ContractCreate(
            contract_number="NEW-1",
            property_id=prop.id,
            unit_id=unit.id,
            tenant_id=tenant_new.id,
            start_date=date(2027, 1, 1),
            status="active",
        )
    )

    foreign_prop = store.create_property(
        PropertyCreate(
            portfolio_id=foreign_portfolio.id,
            name="Foreign property",
            property_type="residential",
        )
    )
    foreign_unit = store.create_unit(
        UnitCreate(property_id=foreign_prop.id, label="F", unit_type="apartment")
    )
    foreign_tenant = store.create_tenant(TenantCreate(full_name="Foreign tenant"))
    foreign_contract = store.create_contract(
        ContractCreate(
            contract_number="FOREIGN-1",
            property_id=foreign_prop.id,
            unit_id=foreign_unit.id,
            tenant_id=foreign_tenant.id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status="terminated",
        )
    )

    users = {
        "manager": {
            "id": "manager",
            "full_name": "Manager",
            "role": "verwalter",
            "is_active": True,
            "portfolio_access": "selected",
            "portfolio_ids": [portfolio.id],
        },
        "tech": {
            "id": "tech",
            "full_name": "Technik",
            "role": "techniker",
            "is_active": True,
            "portfolio_access": "selected",
            "portfolio_ids": [portfolio.id],
        },
        "foreign-manager": {
            "id": "foreign-manager",
            "full_name": "Foreign manager",
            "role": "verwalter",
            "is_active": True,
            "portfolio_access": "selected",
            "portfolio_ids": [foreign_portfolio.id],
        },
        "readonly": {
            "id": "readonly",
            "full_name": "Reader",
            "role": "readonly",
            "is_active": True,
            "portfolio_access": "selected",
            "portfolio_ids": [portfolio.id],
        },
    }
    monkeypatch.setattr(auth, "get_user_by_id", lambda identifier: users.get(identifier))
    yield SimpleNamespace(
        store=store,
        engine=engine,
        db=db,
        users=users,
        portfolio=portfolio,
        property=prop,
        unit=unit,
        previous=previous,
        following=following,
        foreign_portfolio=foreign_portfolio,
        foreign_property=foreign_prop,
        foreign_unit=foreign_unit,
        foreign_contract=foreign_contract,
    )
    if db is not None:
        db.close()
        engine.dispose()
    if admin is not None and schema is not None:
        try:
            with admin.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        finally:
            admin.dispose()


def step(
    key,
    position,
    *,
    title=None,
    depends=(),
    anchor="move_out_handover",
    evidence="none",
    requirement="required",
    role="techniker",
):
    return TemplateStepInput(
        stable_key=key,
        position=position,
        title=title or key,
        description="Synthetic workflow step",
        default_requirement=requirement,
        anchor=anchor,
        offset_days=-7 if position == 0 else 0,
        assignee_role=role,
        depends_on_step_keys=list(depends),
        evidence_requirement=evidence,
    )


def published_template(box, *, property_id=None, unit_id=None, direction="move_out", steps=None, key="template"):
    draft = workflow.create_template(
        box.store,
        CreateTemplate(
            idempotency_key=key,
            expected_revision="new",
            property_id=property_id or box.property.id,
            unit_id=unit_id,
            direction=direction,
            steps=steps or [step("prepare", 0)],
        ),
        "manager" if (property_id or box.property.id) == box.property.id else "foreign-manager",
    )
    actor = "manager" if draft["portfolio_id"] == box.portfolio.id else "foreign-manager"
    return workflow.publish_template_version(
        box.store,
        draft["id"],
        PublishTemplateVersion(
            idempotency_key=key + "-publish",
            expected_revision=draft["revision"],
        ),
        actor,
    )


def preview_and_start(box, template, *, key="change", mode="move_out", previous=None, following=None,
                      move_out=date(2026, 12, 30), move_in=None):
    previous = box.previous if previous is None and mode != "move_in" else previous
    following = box.following if following is None and mode != "move_out" else following
    values = dict(
        property_id=box.property.id,
        unit_id=box.unit.id,
        previous_contract_id=previous.id if previous else None,
        next_contract_id=following.id if following else None,
        mode=mode,
        move_out_handover_date=move_out,
        move_in_handover_date=move_in,
        move_out_template_version_id=template["id"] if mode != "move_in" else None,
        move_in_template_version_id=template["id"] if mode == "move_in" else None,
    )
    preview = workflow.preview_change(
        box.store, workflow.PreviewTenancyChange(**values), "manager"
    )
    payload = StartTenancyChange(
        **values,
        idempotency_key=key,
        expected_revision="new",
        preview_hash=preview["preview_hash"],
        source_etags=preview["source_etags"],
    )
    return preview, payload, workflow.start_change(box.store, payload, "manager")


def current_step(box, change_id, key):
    change = workflow.get_change(box.store, change_id, "manager")
    return change, next(item for item in change["steps"] if item["template_step_key"] == key)


def test_template_dag_versioning_and_frozen_started_snapshot(box):
    with pytest.raises(ValidationError, match="Zyklus"):
        workflow.create_template(
            box.store,
            CreateTemplate(
                idempotency_key="cycle",
                expected_revision="new",
                property_id=box.property.id,
                direction="move_out",
                steps=[
                    step("a", 0, depends=("b",)),
                    step("b", 1, depends=("a",)),
                ],
            ),
            "manager",
        )

    published = published_template(
        box,
        steps=[step("prepare", 0, title="Property-specific original")],
    )
    preview, start_payload, change = preview_and_start(box, published)
    assert preview["affected_steps"][0]["due_date"] == "2026-12-23"
    assert change["steps"][0]["title_snapshot"] == "Property-specific original"
    assert change["snapshot_sha256"] == preview["snapshot_sha256"]
    assert workflow.start_change(box.store, start_payload, "manager") == change

    draft2 = workflow.create_template_version(
        box.store,
        published["template_id"],
        CreateTemplateVersion(
            idempotency_key="version-2",
            expected_revision=published["revision"],
            based_on_version_id=published["id"],
        ),
        "manager",
    )
    changed = workflow.update_template_version(
        box.store,
        draft2["id"],
        UpdateTemplateVersion(
            idempotency_key="version-2-edit",
            expected_revision=draft2["revision"],
            steps=[step("prepare", 0, title="Changed future version")],
        ),
        "manager",
    )
    workflow.publish_template_version(
        box.store,
        changed["id"],
        PublishTemplateVersion(
            idempotency_key="version-2-publish",
            expected_revision=changed["revision"],
        ),
        "manager",
    )
    frozen = workflow.get_change(box.store, change["id"], "manager")
    assert frozen["steps"][0]["title_snapshot"] == "Property-specific original"
    assert frozen["snapshot_sha256"] == change["snapshot_sha256"]


def test_property_specific_templates_and_unit_override_are_distinct(box):
    first = published_template(box, steps=[step("a", 0, title="Object A")], key="object-a")
    override = published_template(
        box,
        unit_id=box.unit.id,
        steps=[step("b", 0, title="Unit override")],
        key="unit-a",
    )
    foreign = published_template(
        box,
        property_id=box.foreign_property.id,
        steps=[step("f", 0, title="Foreign object")],
        key="foreign",
    )
    assert (first["property_id"], first["unit_id"]) == (box.property.id, None)
    assert override["unit_id"] == box.unit.id
    assert foreign["property_id"] == box.foreign_property.id
    inherited = workflow.list_templates(
        box.store, "manager", unit_id=box.unit.id, direction="move_out", limit=10
    )
    assert {item["id"] for item in inherited["items"]} == {first["id"], override["id"]}
    page = workflow.list_templates(box.store, "manager", property_id=box.property.id, limit=1)
    assert len(page["items"]) == 1 and page["has_more"]
    page2 = workflow.list_templates(
        box.store, "manager", property_id=box.property.id, limit=1, after=page["next_cursor"]
    )
    assert len(page2["items"]) == 1 and not page2["has_more"]
    assert {page["items"][0]["id"], page2["items"][0]["id"]} == {first["id"], override["id"]}


def test_active_contract_role_is_unique_and_idempotency_mismatch_conflicts(box):
    template = published_template(box)
    _, payload, first = preview_and_start(box, template, key="stable-start")
    assert workflow.start_change(box.store, payload, "manager") == first
    with pytest.raises(HTTPException) as duplicate:
        preview_and_start(box, template, key="different-start")
    assert duplicate.value.status_code == 409

    changed_request = payload.model_copy(update={"preview_hash": "0" * 64})
    with pytest.raises(HTTPException) as mismatch:
        workflow.start_change(box.store, changed_request, "manager")
    assert mismatch.value.status_code == 409


def test_dependency_task_origin_normal_task_writes_and_atomic_rollback(box, monkeypatch):
    template = published_template(
        box,
        steps=[
            step("prepare", 0),
            step("handover", 1, depends=("prepare",)),
        ],
    )
    _, _, change = preview_and_start(box, template)
    prepare = next(item for item in change["steps"] if item["template_step_key"] == "prepare")
    handover = next(item for item in change["steps"] if item["template_step_key"] == "handover")
    assert handover["state"] == "blocked" and handover["blocked_by_step_ids"] == [prepare["id"]]
    assert not handover["actions"]["link_task"]

    with pytest.raises(HTTPException, match="Vorgänger"):
        workflow.create_step_task(
            box.store,
            change["id"],
            handover["id"],
            CreateStepTask(
                idempotency_key="blocked-task",
                expected_revision=handover["revision"],
                expected_change_revision=change["revision"],
            ),
            "tech",
        )

    before_tasks = len(box.store.list_tasks())
    original_save = workflow._save_command

    def fail_receipt(*args, **kwargs):
        raise RuntimeError("synthetic receipt failure")

    monkeypatch.setattr(workflow, "_save_command", fail_receipt)
    with pytest.raises(RuntimeError, match="receipt"):
        workflow.create_step_task(
            box.store,
            change["id"],
            prepare["id"],
            CreateStepTask(
                idempotency_key="rolled-back-task",
                expected_revision=prepare["revision"],
                expected_change_revision=change["revision"],
            ),
            "tech",
        )
    monkeypatch.setattr(workflow, "_save_command", original_save)
    assert len(box.store.list_tasks()) == before_tasks
    current, prepare = current_step(box, change["id"], "prepare")
    assert prepare["task_id"] is None

    projected = workflow.create_step_task(
        box.store,
        change["id"],
        prepare["id"],
        CreateStepTask(
            idempotency_key="real-task",
            expected_revision=prepare["revision"],
            expected_change_revision=current["revision"],
        ),
        "tech",
    )
    task = box.store.get_task(projected["task_id"])
    assert (task.property_id, task.unit_id, task.due_date) == (
        box.property.id,
        box.unit.id,
        date(2026, 12, 23),
    )
    with pytest.raises(ValidationError, match="Mieterwechselakte"):
        box.store.update_task(
            task.id,
            TaskCreate(**{
                **task.model_dump(include=set(TaskCreate.model_fields)),
                "due_date": date(2030, 1, 1),
            }),
        )
    with pytest.raises(ValidationError, match="Mieterwechselakte"):
        box.store._patch_entity("task", task.id, TaskPatch(title="Forbidden direct patch"))
    with pytest.raises(ValidationError, match="Mieterwechselakte"):
        box.store.delete_task(task.id)

    current, prepare = current_step(box, change["id"], "prepare")
    workflow.update_step(
        box.store,
        change["id"],
        prepare["id"],
        UpdateStep(
            idempotency_key="complete-prepare",
            expected_revision=prepare["revision"],
            expected_change_revision=current["revision"],
            state="completed",
        ),
        "tech",
    )
    current, handover = current_step(box, change["id"], "handover")
    assert handover["state"] == "open" and handover["blocked_by_step_ids"] == []
    assert box.store.get_task(task.id).status == "completed"


def test_finalized_handover_and_meter_are_immutable_and_valid_evidence(box):
    template = published_template(
        box,
        steps=[step("meter", 0, evidence="meter_reading")],
    )
    _, _, change = preview_and_start(box, template)
    workflow_step = change["steps"][0]

    protocol = box.store.create_handover_protocol(
        HandoverProtocolCreate(
            contract_id=box.previous.id,
            unit_id=box.unit.id,
            protocol_type="move_out",
            protocol_date=date(2026, 12, 30),
            status="draft",
        )
    )
    reading = box.store.create_meter_reading(
        MeterReadingCreate(
            handover_id=protocol.id,
            meter_type="electricity",
            meter_number="SYN-1",
            reading_value=123.45,
            unit="kWh",
        )
    )
    finalized = box.store.update_handover_protocol(
        protocol.id,
        HandoverProtocolCreate(
            **{
                **protocol.model_dump(include=set(HandoverProtocolCreate.model_fields)),
                "status": "finalized",
            }
        ),
    )
    assert finalized.status == "finalized"

    with pytest.raises(ValidationError, match="finalisiert"):
        box.store.update_handover_protocol(
            protocol.id,
            HandoverProtocolCreate(
                **{
                    **finalized.model_dump(include=set(HandoverProtocolCreate.model_fields)),
                    "notes": "forbidden later edit",
                }
            ),
        )
    with pytest.raises(ValidationError, match="finalisiert"):
        box.store._patch_entity(
            "handover_protocol",
            protocol.id,
            HandoverProtocolPatch(notes="Forbidden direct patch"),
        )
    with pytest.raises(ValidationError, match="finalisiert"):
        box.store.create_meter_reading(
            MeterReadingCreate(
                handover_id=protocol.id,
                meter_type="water",
                reading_value=1,
                unit="m³",
            )
        )
    with pytest.raises(ValidationError, match="finalisierten"):
        box.store._patch_entity(
            "meter_reading",
            reading.id,
            MeterReadingPatch(reading_value=998),
        )
    with pytest.raises(ValidationError, match="finalisierten"):
        box.store.update_meter_reading(
            reading.id,
            MeterReadingCreate(
                **{
                    **reading.model_dump(include=set(MeterReadingCreate.model_fields)),
                    "reading_value": 999,
                }
            ),
        )
    with pytest.raises(ValidationError, match="finalisierten"):
        box.store.delete_meter_reading(reading.id)
    with pytest.raises(ValidationError, match="finalisiert"):
        box.store.delete_handover_protocol(protocol.id)

    linked = workflow.add_evidence(
        box.store,
        change["id"],
        workflow_step["id"],
        AddEvidence(
            idempotency_key="meter-evidence",
            expected_revision=workflow_step["revision"],
            expected_change_revision=change["revision"],
            evidence=EvidenceInput(kind="meter_reading", meter_reading_id=reading.id),
        ),
        "tech",
    )
    assert linked["evidence_links"][0]["kind"] == "meter_reading"
    assert len(linked["evidence_links"][0]["snapshot_sha256"]) == 64

    current = workflow.get_change(box.store, change["id"], "manager")
    workflow.update_step(
        box.store,
        current["id"],
        linked["id"],
        UpdateStep(
            idempotency_key="complete-meter",
            expected_revision=linked["revision"],
            expected_change_revision=current["revision"],
            state="completed",
        ),
        "tech",
    )
    current = workflow.get_change(box.store, change["id"], "manager")
    done = workflow.complete_change(
        box.store,
        current["id"],
        CompleteTenancyChange(idempotency_key="complete-change", expected_revision=current["revision"]),
        "manager",
    )
    assert done["state"] == "completed"


def test_required_evidence_and_explicit_not_applicable(box):
    template = published_template(
        box,
        steps=[step("protocol", 0, evidence="handover_protocol")],
    )
    _, _, change = preview_and_start(box, template)
    item = change["steps"][0]
    with pytest.raises(HTTPException, match="Originalbeleg"):
        workflow.update_step(
            box.store,
            change["id"],
            item["id"],
            UpdateStep(
                idempotency_key="missing-evidence",
                expected_revision=item["revision"],
                expected_change_revision=change["revision"],
                state="completed",
            ),
            "tech",
        )

    with pytest.raises(PydanticValidationError):
        UpdateStep(
            idempotency_key="bad-na",
            expected_revision=item["revision"],
            expected_change_revision=change["revision"],
            state="not_applicable",
            not_applicable_reason="   ",
        )

    exempt = workflow.update_step(
        box.store,
        change["id"],
        item["id"],
        UpdateStep(
            idempotency_key="conscious-na",
            expected_revision=item["revision"],
            expected_change_revision=change["revision"],
            state="not_applicable",
            not_applicable_reason="Synthetic explicitly reviewed exception",
        ),
        "tech",
    )
    assert exempt["requirement"] == "required"
    assert exempt["state"] == "not_applicable"
    current = workflow.get_change(box.store, change["id"], "manager")
    assert workflow.complete_change(
        box.store,
        change["id"],
        CompleteTenancyChange(idempotency_key="complete-na", expected_revision=current["revision"]),
        "manager",
    )["state"] == "completed"


def test_reanchor_binds_source_etags_preserves_completed_original_and_updates_open_task(box):
    template = published_template(
        box,
        steps=[
            step("done", 0),
            step("open", 1),
        ],
    )
    _, _, change = preview_and_start(box, template)
    done = next(item for item in change["steps"] if item["template_step_key"] == "done")
    open_step = next(item for item in change["steps"] if item["template_step_key"] == "open")

    workflow.update_step(
        box.store,
        change["id"],
        done["id"],
        UpdateStep(
            idempotency_key="done-before-reanchor",
            expected_revision=done["revision"],
            expected_change_revision=change["revision"],
            state="completed",
        ),
        "tech",
    )
    current, open_step = current_step(box, change["id"], "open")
    projected = workflow.create_step_task(
        box.store,
        change["id"],
        open_step["id"],
        CreateStepTask(
            idempotency_key="open-task",
            expected_revision=open_step["revision"],
            expected_change_revision=current["revision"],
        ),
        "tech",
    )
    current = workflow.get_change(box.store, change["id"], "manager")
    preview = workflow.reanchor_preview(
        box.store,
        change["id"],
        ReanchorPreview(
            expected_revision=current["revision"],
            move_out_handover_date=date(2026, 12, 31),
        ),
        "manager",
    )
    assert preview["source_etags"]["previous_contract"] == workflow._contract_etag(
        box.store.get_contract(box.previous.id)
    )
    reanchored = workflow.reanchor_change(
        box.store,
        change["id"],
        ReanchorTenancyChange(
            idempotency_key="reanchor",
            expected_revision=current["revision"],
            move_out_handover_date=date(2026, 12, 31),
            preview_hash=preview["preview_hash"],
            source_etags=preview["source_etags"],
        ),
        "manager",
    )
    done_after = next(item for item in reanchored["steps"] if item["template_step_key"] == "done")
    open_after = next(item for item in reanchored["steps"] if item["template_step_key"] == "open")
    assert (done_after["original_due_date"], done_after["due_date"]) == ("2026-12-23", "2026-12-23")
    assert open_after["original_due_date"] == "2026-12-30"
    assert open_after["due_date"] == "2026-12-31"
    assert box.store.get_task(projected["task_id"]).due_date == date(2026, 12, 31)


def test_technician_can_only_execute_responsible_steps_and_cannot_configure(box):
    template = published_template(box)
    _, _, change = preview_and_start(box, template)
    item = change["steps"][0]
    with pytest.raises(HTTPException) as denied:
        workflow.create_template(
            box.store,
            CreateTemplate(
                idempotency_key="tech-template",
                expected_revision="new",
                property_id=box.property.id,
                direction="move_out",
                steps=[step("x", 0)],
            ),
            "tech",
        )
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as readonly:
        workflow.update_step(
            box.store,
            change["id"],
            item["id"],
            UpdateStep(
                idempotency_key="reader-step",
                expected_revision=item["revision"],
                expected_change_revision=change["revision"],
                state="completed",
            ),
            "readonly",
        )
    assert readonly.value.status_code in {403, 404}

    completed = workflow.update_step(
        box.store,
        change["id"],
        item["id"],
        UpdateStep(
            idempotency_key="tech-step",
            expected_revision=item["revision"],
            expected_change_revision=change["revision"],
            state="completed",
        ),
        "tech",
    )
    assert completed["state"] == "completed"


def test_workflow_commands_do_not_create_financial_rows(box):
    def counts():
        return (
            len(box.store.list_rent_charges()),
            len(box.store.list_payments()),
            len(box.store.list_deposits()),
        )

    before = counts()
    template = published_template(box)
    _, _, change = preview_and_start(box, template)
    item = change["steps"][0]
    task = workflow.create_step_task(
        box.store,
        change["id"],
        item["id"],
        CreateStepTask(
            idempotency_key="finance-free-task",
            expected_revision=item["revision"],
            expected_change_revision=change["revision"],
        ),
        "tech",
    )
    current = workflow.get_change(box.store, change["id"], "manager")
    item = next(value for value in current["steps"] if value["id"] == item["id"])
    workflow.update_step(
        box.store,
        change["id"],
        item["id"],
        UpdateStep(
            idempotency_key="finance-free-done",
            expected_revision=item["revision"],
            expected_change_revision=current["revision"],
            state="completed",
        ),
        "tech",
    )
    current = workflow.get_change(box.store, change["id"], "manager")
    workflow.complete_change(
        box.store,
        change["id"],
        CompleteTenancyChange(
            idempotency_key="finance-free-complete",
            expected_revision=current["revision"],
        ),
        "manager",
    )
    assert box.store.get_task(task["task_id"]).status == "completed"
    assert counts() == before


def test_document_original_link_uses_exact_version_identity_without_path_in_response(box):
    template = published_template(
        box,
        steps=[step("document", 0, evidence="document_original")],
    )
    _, _, change = preview_and_start(box, template)
    item = change["steps"][0]
    document = box.store.create_document(
        DocumentCreate(
            property_id=box.property.id,
            unit_id=box.unit.id,
            contract_id=box.previous.id,
            title="Synthetic original",
            document_type="handover_attachment",
            document_date=date(2026, 12, 30),
            file_url="/uploads/synthetic-workflow-original.pdf",
        )
    )
    content = b"%PDF-1.4\nsynthetic original\n%%EOF\n"
    with document_versions.work(box.store, "manager", write=True) as (active, db, _):
        actual, binding = document_versions._document(active, db, document.id, lock=True)
        version = document_versions.publish_generated_original(
            active,
            db,
            actual,
            binding,
            "manager",
            content,
            "a" * 64,
        )

    linked = workflow.add_evidence(
        box.store,
        change["id"],
        item["id"],
        AddEvidence(
            idempotency_key="document-evidence",
            expected_revision=item["revision"],
            expected_change_revision=change["revision"],
            evidence=EvidenceInput(
                kind="document_version",
                document_id=document.id,
                document_version_id=version.id,
            ),
        ),
        "tech",
    )
    evidence = linked["evidence_links"][0]
    assert evidence["document_id"] == document.id
    assert evidence["document_version_id"] == version.id
    assert "file_url" not in evidence and "filename" not in evidence
    assert len(evidence["snapshot_sha256"]) == 64


def test_scope_bound_lists_and_cursors_never_expose_foreign_portfolio(box):
    local = published_template(box, key="local-scope")
    foreign = published_template(
        box,
        property_id=box.foreign_property.id,
        steps=[step("foreign", 0)],
        key="foreign-scope",
    )
    page = workflow.list_templates(box.store, "manager", limit=10)
    assert {row["id"] for row in page["items"]} == {local["id"]}
    with pytest.raises((HTTPException, NotFoundError)) as hidden:
        workflow.get_template_version(box.store, foreign["id"], "manager")
    if isinstance(hidden.value, HTTPException):
        assert hidden.value.status_code == 404

    # A cursor is tied to actor/scope, filters and the requested technical page budget.
    unit_override = published_template(
        box,
        unit_id=box.unit.id,
        steps=[step("unit", 0)],
        key="scope-unit",
    )
    first = workflow.list_templates(box.store, "manager", limit=1)
    assert first["has_more"] and first["next_cursor"]
    with pytest.raises(HTTPException) as tampered_filter:
        workflow.list_templates(
            box.store,
            "manager",
            direction="move_in",
            limit=1,
            after=first["next_cursor"],
        )
    assert tampered_filter.value.status_code == 422
    assert unit_override["id"] in {
        row["id"]
        for row in workflow.list_templates(box.store, "manager", limit=10)["items"]
    }


def test_database_guards_freeze_published_and_started_originals(box):
    if not box.db:
        pytest.skip("database trigger gate")
    published = published_template(box, key="trigger-template")
    _, _, change = preview_and_start(box, published, key="trigger-change")
    step_row = box.db.scalar(
        select(WorkflowTemplateStepORM).where(
            WorkflowTemplateStepORM.version_id == published["id"]
        )
    )
    assert step_row is not None
    with pytest.raises(SQLAlchemyError):
        box.db.execute(
            update(WorkflowTemplateStepORM)
            .where(WorkflowTemplateStepORM.id == step_row.id)
            .values(title="mutated published text")
        )
        box.db.commit()
    box.db.rollback()
    with pytest.raises(SQLAlchemyError):
        box.db.execute(
            update(WorkflowTemplateVersionORM)
            .where(WorkflowTemplateVersionORM.id == published["id"])
            .values(state="draft")
        )
        box.db.commit()
    box.db.rollback()

    change_row = box.db.get(TenancyChangeORM, change["id"])
    assert change_row is not None
    with pytest.raises(SQLAlchemyError):
        box.db.execute(
            update(TenancyChangeORM)
            .where(TenancyChangeORM.id == change["id"])
            .values(snapshot_sha256="0" * 64)
        )
        box.db.commit()
    box.db.rollback()

    instance = box.db.get(WorkflowStepInstanceORM, change["steps"][0]["id"])
    assert instance is not None
    with pytest.raises(SQLAlchemyError):
        box.db.execute(
            update(WorkflowStepInstanceORM)
            .where(WorkflowStepInstanceORM.id == instance.id)
            .values(title_snapshot="mutated frozen title")
        )
        box.db.commit()
    box.db.rollback()

    command = box.db.scalar(
        select(WorkflowCommandORM).where(
            WorkflowCommandORM.subject_id == change["id"]
        )
    )
    assert command is not None
    with pytest.raises(SQLAlchemyError):
        box.db.execute(
            update(WorkflowCommandORM)
            .where(WorkflowCommandORM.id == command.id)
            .values(request_sha256="0" * 64)
        )
        box.db.commit()
    box.db.rollback()


def test_database_guards_protect_finalized_handover_meter_and_completed_evidence(box):
    if not box.db:
        pytest.skip("database retained-evidence trigger gate")

    template = published_template(
        box,
        steps=[step("meter-final", 0, evidence="meter_reading")],
        key="final-trigger-template",
    )
    _, _, change = preview_and_start(box, template, key="final-trigger-change")
    step_item = change["steps"][0]
    protocol = box.store.create_handover_protocol(
        HandoverProtocolCreate(
            contract_id=box.previous.id,
            unit_id=box.unit.id,
            protocol_type="move_out",
            protocol_date=date(2026, 12, 30),
            status="draft",
        )
    )
    reading = box.store.create_meter_reading(
        MeterReadingCreate(
            handover_id=protocol.id,
            meter_type="electricity",
            reading_value=42,
            unit="kWh",
        )
    )
    box.store.update_handover_protocol(
        protocol.id,
        HandoverProtocolCreate(
            **{
                **protocol.model_dump(include=set(HandoverProtocolCreate.model_fields)),
                "status": "finalized",
            }
        ),
    )

    for statement in (
        update(HandoverProtocolORM)
        .where(HandoverProtocolORM.id == protocol.id)
        .values(notes="direct sql mutation"),
        update(MeterReadingORM)
        .where(MeterReadingORM.id == reading.id)
        .values(reading_value=43),
        delete(MeterReadingORM).where(MeterReadingORM.id == reading.id),
        delete(HandoverProtocolORM).where(HandoverProtocolORM.id == protocol.id),
    ):
        with pytest.raises(SQLAlchemyError):
            box.db.execute(statement)
            box.db.commit()
        box.db.rollback()

    with pytest.raises(SQLAlchemyError):
        box.db.execute(
            insert(MeterReadingORM).values(
                id="post-final-reading",
                handover_id=protocol.id,
                meter_type="water",
                reading_value=1,
                unit="m3",
            )
        )
        box.db.commit()
    box.db.rollback()

    linked = workflow.add_evidence(
        box.store,
        change["id"],
        step_item["id"],
        AddEvidence(
            idempotency_key="trigger-meter-link",
            expected_revision=step_item["revision"],
            expected_change_revision=change["revision"],
            evidence=EvidenceInput(kind="meter_reading", meter_reading_id=reading.id),
        ),
        "tech",
    )
    current = workflow.get_change(box.store, change["id"], "manager")
    workflow.update_step(
        box.store,
        change["id"],
        step_item["id"],
        UpdateStep(
            idempotency_key="trigger-meter-complete",
            expected_revision=linked["revision"],
            expected_change_revision=current["revision"],
            state="completed",
        ),
        "tech",
    )
    evidence_id = linked["evidence_links"][0]["id"]
    with pytest.raises(SQLAlchemyError):
        box.db.execute(
            delete(WorkflowEvidenceLinkORM).where(WorkflowEvidenceLinkORM.id == evidence_id)
        )
        box.db.commit()
    box.db.rollback()


def test_router_surface_matches_binding_contract():
    from backend.routers.tenancy_workflows import router

    actual = {
        (method, route.path)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }
    expected = {
        ("GET", "/workflow-templates"),
        ("POST", "/workflow-templates"),
        ("GET", "/workflow-templates/{template_id}"),
        ("GET", "/workflow-templates/{template_id}/versions"),
        ("POST", "/workflow-templates/{template_id}/versions"),
        ("GET", "/workflow-template-versions/{version_id}"),
        ("PUT", "/workflow-template-versions/{version_id}"),
        ("POST", "/workflow-template-versions/{version_id}/publish"),
        ("GET", "/tenancy-changes"),
        ("POST", "/tenancy-changes/preview"),
        ("POST", "/tenancy-changes"),
        ("GET", "/tenancy-changes/{change_id}"),
        ("PATCH", "/tenancy-changes/{change_id}"),
        ("POST", "/tenancy-changes/{change_id}/reanchor-preview"),
        ("POST", "/tenancy-changes/{change_id}/reanchor"),
        ("PATCH", "/tenancy-changes/{change_id}/steps/{step_id}"),
        ("POST", "/tenancy-changes/{change_id}/steps/{step_id}/task"),
        ("POST", "/tenancy-changes/{change_id}/steps/{step_id}/evidence"),
        ("DELETE", "/tenancy-changes/{change_id}/steps/{step_id}/evidence/{link_id}"),
        ("POST", "/tenancy-changes/{change_id}/complete"),
    }
    assert actual == expected


def test_template_step_requires_exactly_one_responsibility_identity():
    with pytest.raises(PydanticValidationError):
        TemplateStepInput(
            stable_key="unassigned",
            position=0,
            title="Unassigned",
            default_requirement="required",
            anchor="move_out_handover",
            offset_days=0,
        )
    with pytest.raises(PydanticValidationError):
        TemplateStepInput(
            stable_key="double",
            position=0,
            title="Double",
            default_requirement="required",
            anchor="move_out_handover",
            offset_days=0,
            assignee_user_id="user",
            assignee_role="techniker",
        )
