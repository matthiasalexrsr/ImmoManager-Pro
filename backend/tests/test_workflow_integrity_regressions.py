"""Executable regressions for independent review findings, on three stores."""

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from backend.db.orm_models import MeterReadingORM
from backend.db.tenancy_workflow_models import WorkflowTemplateStepORM
from backend.models import ContractCreate, HandoverProtocolCreate, MeterReadingCreate, UnitCreate
from backend.routers.tenancy_workflows import call
from backend.services import tenancy_workflow as service
from backend.services.tenancy_workflow_types import CreateTemplateVersion, StartTenancyChange, UpdateStep
from backend.tests.test_tenancy_workflow_core import box as _box
from backend.tests.test_tenancy_workflow_core import preview_and_start, published_template

box = _box


@pytest.mark.parametrize("revoke_original_scope", [False, True])
def test_receipt_cannot_be_replayed_through_another_authorized_subject(box, revoke_original_scope):
    template = published_template(box)
    _, _, first = preview_and_start(box, template)
    old = first["steps"][0]
    command = UpdateStep(idempotency_key="private-step-replay", expected_revision=old["revision"],
        expected_change_revision=first["revision"], state="completed")
    receipt = service.update_step(box.store, first["id"], old["id"], command, "tech")
    assert receipt["id"] == old["id"]
    if revoke_original_scope:
        box.users["manager"]["portfolio_ids"].append(box.foreign_portfolio.id)
        other_template = published_template(box, property_id=box.foreign_property.id, key="other-template")
        property_id, unit_id, contract_id = box.foreign_property.id, box.foreign_unit.id, box.foreign_contract.id
    else:
        unit = box.store.create_unit(UnitCreate(property_id=box.property.id, label="Second authorized unit", unit_type="apartment"))
        contract = box.store.create_contract(ContractCreate(contract_number="SECOND-AUTHORIZED", property_id=box.property.id,
            unit_id=unit.id, tenant_id=box.previous.tenant_id, status="terminated",
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)))
        other_template = template
        property_id, unit_id, contract_id = box.property.id, unit.id, contract.id
    values = dict(property_id=property_id, unit_id=unit_id, previous_contract_id=contract_id, mode="move_out",
        move_out_handover_date=date(2026, 12, 30), move_out_template_version_id=other_template["id"])
    preview = service.preview_change(box.store, service.PreviewTenancyChange(**values), "manager")
    second = service.start_change(box.store, StartTenancyChange(**values, idempotency_key="second-change",
        expected_revision="new", preview_hash=preview["preview_hash"], source_etags=preview["source_etags"]), "manager")
    if revoke_original_scope:
        box.users["tech"]["portfolio_ids"] = [box.foreign_portfolio.id]
        with pytest.raises(HTTPException) as denial:
            call(service.get_change, box.store, first["id"], "tech")
        assert denial.value.status_code == 404
    new = second["steps"][0]
    with pytest.raises(HTTPException) as collision:
        service.update_step(box.store, second["id"], new["id"], command, "tech")
    assert collision.value.status_code == 409
    current = service.get_change(box.store, second["id"], "tech")
    assert current["steps"][0]["id"] == new["id"] and current["steps"][0]["state"] == "open"


def test_database_cannot_reparent_and_edit_a_finalized_protocol_reading(box):
    if box.db is None:
        pytest.skip("Raw database trigger only")
    payload = HandoverProtocolCreate(contract_id=box.previous.id, unit_id=box.unit.id,
        protocol_type="move_out", protocol_date=date(2026, 12, 30), status="draft")
    frozen = box.store.create_handover_protocol(payload)
    reading = box.store.create_meter_reading(MeterReadingCreate(handover_id=frozen.id, meter_type="electricity", reading_value=1))
    box.store.update_handover_protocol(frozen.id, payload.model_copy(update={"status": "finalized"}))
    mutable = box.store.create_handover_protocol(payload)
    with pytest.raises(SQLAlchemyError, match="finalized handover meter evidence is immutable"):
        with box.engine.begin() as connection:
            connection.execute(update(MeterReadingORM).where(MeterReadingORM.id == reading.id)
                .values(handover_id=mutable.id, reading_value=99))
    with box.engine.connect() as connection:
        actual = connection.execute(select(MeterReadingORM.handover_id, MeterReadingORM.reading_value)
            .where(MeterReadingORM.id == reading.id)).one()
    assert actual[0] == frozen.id and float(actual[1]) == 1.0


def test_database_cannot_move_a_draft_step_into_a_published_version(box):
    if box.db is None:
        pytest.skip("Raw database trigger only")
    published = published_template(box)
    draft = service.create_template_version(box.store, published["template_id"],
        CreateTemplateVersion(idempotency_key="draft-for-reparent", expected_revision=published["revision"],
                              based_on_version_id=published["id"]), "manager")
    row_id = draft["steps"][0]["id"]
    with pytest.raises(SQLAlchemyError, match="published tenancy workflow steps are immutable"):
        with box.engine.begin() as connection:
            connection.execute(update(WorkflowTemplateStepORM).where(WorkflowTemplateStepORM.id == row_id)
                .values(version_id=published["id"], stable_key="foreign-insertion", position=999, title="Changed immutable source"))
    with box.engine.connect() as connection:
        version = connection.scalar(select(WorkflowTemplateStepORM.version_id).where(WorkflowTemplateStepORM.id == row_id))
    assert version == draft["id"]
