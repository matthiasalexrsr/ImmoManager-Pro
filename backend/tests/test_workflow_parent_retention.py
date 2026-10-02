"""Ordinary edits must not invalidate the scope parents of frozen workflows."""

import pytest
from sqlalchemy import inspect, select

from backend.db.credit_models import CreditReceiptORM  # noqa: F401
from backend.db.orm_models import Base
from backend.db.tenancy_workflow_models import TENANCY_WORKFLOW_MODELS, TenancyChangeORM, WorkflowCommandORM
from backend.models import ContractCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.services import tenancy_workflow as workflow
from backend.storage import ValidationError
from backend.tests.test_tenancy_workflow_core import box as _box
from backend.tests.test_tenancy_workflow_core import preview_and_start, published_template

box = _box


@pytest.mark.parametrize("kind", ["property", "unit", "contract"])
def test_ordinary_scope_relocation_is_refused_before_parent_changes(box, kind):
    template = published_template(box, unit_id=box.unit.id)
    _, _, change = preview_and_start(box, template)
    before = workflow.get_change(box.store, change["id"], "manager")
    if kind == "property":
        payload = PropertyCreate(**box.property.model_dump(exclude={"id", "created_at", "updated_at"}))
        payload = payload.model_copy(update={"portfolio_id": box.foreign_portfolio.id})
        identifier = box.property.id
    elif kind == "unit":
        payload = UnitCreate(**box.unit.model_dump(exclude={"id", "created_at", "updated_at"}))
        payload = payload.model_copy(update={"property_id": box.foreign_property.id})
        identifier = box.unit.id
    else:
        target_unit = box.store.create_unit(UnitCreate(property_id=box.foreign_property.id,
            label="Unoccupied relocation target", unit_type="apartment"))
        payload = ContractCreate(**box.previous.model_dump(exclude={"id", "created_at", "updated_at"}))
        payload = payload.model_copy(update={"property_id": box.foreign_property.id, "unit_id": target_unit.id})
        identifier = box.previous.id
    with pytest.raises(ValidationError, match="Mieterwechsel"):
        getattr(box.store, f"update_{kind}")(identifier, payload)
    if box.db is not None:
        box.db.rollback()
    assert box.store.get_property(box.property.id).portfolio_id == box.portfolio.id
    assert box.store.get_unit(box.unit.id).property_id == box.property.id
    assert box.store.get_contract(box.previous.id).property_id == box.property.id
    assert workflow.get_change(box.store, change["id"], "manager") == before


def test_template_only_parent_retention_and_unrelated_metadata_edit(box):
    published_template(box, unit_id=box.unit.id)
    payload = PropertyCreate(**box.property.model_dump(exclude={"id", "created_at", "updated_at"}))
    renamed = box.store.update_property(box.property.id, payload.model_copy(update={"name": "Allowed metadata correction"}))
    assert renamed.name == "Allowed metadata correction"
    with pytest.raises(ValidationError, match="Mieterwechsel"):
        box.store.update_property(box.property.id, payload.model_copy(update={"portfolio_id": box.foreign_portfolio.id}))
    if box.db is not None:
        box.db.rollback()
    with pytest.raises(ValidationError, match="Mieterwechsel"):
        box.store.delete_unit(box.unit.id)
    if box.db is not None:
        box.db.rollback()
    assert box.store.get_unit(box.unit.id).property_id == box.property.id
    foreign = PropertyCreate(**box.foreign_property.model_dump(exclude={"id", "created_at", "updated_at"}))
    assert box.store.update_property(box.foreign_property.id,
        foreign.model_copy(update={"portfolio_id": box.portfolio.id})).portfolio_id == box.portfolio.id


def test_historical_tenant_remains_referenced_after_allowed_current_party_correction(box):
    template = published_template(box)
    _, _, change = preview_and_start(box, template)
    old_tenant_id = box.previous.tenant_id
    replacement = box.store.create_tenant(TenantCreate(full_name="Corrected current party"))
    payload = ContractCreate(**box.previous.model_dump(exclude={"id", "created_at", "updated_at"}))
    corrected = box.store.update_contract(box.previous.id, payload.model_copy(update={"tenant_id": replacement.id}))
    assert corrected.tenant_id == replacement.id
    with pytest.raises(ValidationError, match="Mieterwechsel"):
        box.store.delete_tenant(old_tenant_id)
    if box.db is not None:
        box.db.rollback()
    assert box.store.get_tenant(old_tenant_id).id == old_tenant_id
    snapshot = (box.db.scalar(select(TenancyChangeORM.snapshot).where(TenancyChangeORM.id == change["id"]))
                if box.db is not None else box.store.__dict__[TenancyChangeORM.__tablename__][change["id"]].snapshot)
    assert snapshot["previous_contract"]["tenant_id"] == old_tenant_id
    assert workflow.get_change(box.store, change["id"], "manager")["snapshot_sha256"] == change["snapshot_sha256"]


@pytest.mark.parametrize("partial", [False, True])
def test_legacy_absence_remains_usable_but_partial_family_refuses_before_parent_change(box, partial):
    if box.db is None:
        pytest.skip("Schema compatibility requires an actual SQL database")
    box.db.rollback()
    family = {model.__tablename__ for model in TENANCY_WORKFLOW_MODELS}
    with box.engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in (family if not partial else {WorkflowCommandORM.__tablename__}):
                connection.exec_driver_sql('DROP TABLE "' + table.name + '"')
    names = set(inspect(box.engine).get_table_names())
    payload = PropertyCreate(**box.property.model_dump(exclude={"id", "created_at", "updated_at"}))
    payload = payload.model_copy(update={"portfolio_id": box.foreign_portfolio.id})
    if partial:
        with pytest.raises(ValidationError, match="Unvollständige Mieterwechseltabellen"):
            box.store.update_property(box.property.id, payload)
        box.db.rollback()
        assert box.store.get_property(box.property.id).portfolio_id == box.portfolio.id
    else:
        assert box.store.update_property(box.property.id, payload).portfolio_id == box.foreign_portfolio.id
    assert set(inspect(box.engine).get_table_names()) == names
