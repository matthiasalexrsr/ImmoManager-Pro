"""Independent parent-guard regressions, using per-test synthetic stores only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from backend.db.credit_models import CreditReceiptORM  # noqa: F401
from backend.db.orm_models import PropertyORM
from backend.db.tenancy_workflow_models import WorkflowTemplateORM
from backend.models import ContractPatch, PropertyCreate, PropertyPatch, TenantCreate, UnitPatch
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.storage import ValidationError
from backend.tests.test_tenancy_workflow_core import box as box
from backend.tests.test_tenancy_workflow_core import preview_and_start, published_template


def test_public_patch_preserves_frozen_locations_and_permits_current_party_correction(box):
    template = published_template(box, unit_id=box.unit.id)
    preview_and_start(box, template)
    for kind, identifier, payload in (
        ("property", box.property.id, PropertyPatch(portfolio_id=box.foreign_portfolio.id)),
        ("unit", box.unit.id, UnitPatch(property_id=box.foreign_property.id)),
        ("contract", box.previous.id, ContractPatch(property_id=box.foreign_property.id, unit_id=box.foreign_unit.id)),
    ):
        with pytest.raises(ValidationError, match="Mieterwechsel"):
            box.store._patch_entity(kind, identifier, payload)
        if box.db:
            box.db.rollback()
    replacement = box.store.create_tenant(TenantCreate(full_name="Correctable current tenant"))
    assert box.store._patch_entity("contract", box.previous.id, ContractPatch(tenant_id=replacement.id)).tenant_id == replacement.id
    with pytest.raises(ValidationError, match="Mieterwechsel"):
        box.store.delete_tenant(box.previous.tenant_id)
    if box.db:
        box.db.rollback()


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("operation", ["put", "patch", "delete"])
def test_pending_workflow_row_is_rejected_without_any_sql_dml(box, autoflush, operation):
    if box.db is None:
        pytest.skip("SQL pending-state/statement-order probe")
    box.db.rollback()
    box.db.autoflush = autoflush
    pending = WorkflowTemplateORM(id=str(uuid4()), portfolio_id=box.portfolio.id, property_id=box.property.id,
        unit_id=box.unit.id, direction="move_in", created_by="manager", created_at=datetime.now(timezone.utc))
    box.db.add(pending)
    statements = []
    def observed(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(statement.split("VALUES", 1)[0])
    event.listen(box.engine, "before_cursor_execute", observed)
    try:
        with pytest.raises(ValidationError, match="Mieterwechsel"):
            if operation == "put":
                payload = PropertyCreate(**box.property.model_dump(exclude={"id", "created_at", "updated_at"}))
                box.store.update_property(box.property.id, payload.model_copy(update={"portfolio_id": box.foreign_portfolio.id}))
            elif operation == "patch":
                box.store._patch_entity("property", box.property.id, PropertyPatch(portfolio_id=box.foreign_portfolio.id))
            else:
                box.store.delete_property(box.property.id)
        assert statements == [], {"autoflush": autoflush, "operation": operation, "dml": statements}
        assert pending in box.db.new
        assert box.db.autoflush is autoflush
        assert box.db.in_transaction()
        assert box.db.connection().execute(select(WorkflowTemplateORM.id)).all() == []
    finally:
        box.db.rollback()
        event.remove(box.engine, "before_cursor_execute", observed)


def test_scope_denial_preserves_subject_without_disclosing_hidden_workflow(box):
    from backend.storage import NotFoundError
    template = published_template(box, unit_id=box.unit.id)
    preview_and_start(box, template)
    with scope_context(scope_from_user(box.users["foreign-manager"])):
        with pytest.raises(NotFoundError):
            box.store._patch_entity("property", box.property.id, PropertyPatch(portfolio_id=box.foreign_portfolio.id))
    if box.db:
        box.db.rollback()
    assert box.store.get_property(box.property.id).portfolio_id == box.portfolio.id


def test_postgres_parent_lock_waits_for_new_reference_then_refuses_without_parent_update(box):
    if box.db is None or box.engine.dialect.name != "postgresql":
        pytest.skip("Actual independent PostgreSQL sessions/parent lock probe")
    box.db.rollback()
    waiting = Event()
    with Session(box.engine, autoflush=False) as creator:
        creator.scalar(select(PropertyORM.id).where(PropertyORM.id == box.property.id).with_for_update())
        creator.add(WorkflowTemplateORM(id=str(uuid4()), portfolio_id=box.portfolio.id,
            property_id=box.property.id, unit_id=box.unit.id, direction="move_in",
            created_by="manager", created_at=datetime.now(timezone.utc)))
        creator.flush()
        def observed(_connection, _cursor, statement, _parameters, _context, _many):
            if "properties" in statement and "FOR UPDATE" in statement:
                waiting.set()
        def relocate():
            with Session(box.engine, autoflush=False) as db:
                store = SQLAlchemyStore(db)
                payload = PropertyCreate(**box.property.model_dump(exclude={"id", "created_at", "updated_at"}))
                try:
                    store.update_property(box.property.id, payload.model_copy(update={"portfolio_id": box.foreign_portfolio.id}))
                except ValidationError as error:
                    db.rollback()
                    return str(error)
                return "incorrectly relocated"
        event.listen(box.engine, "before_cursor_execute", observed)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(relocate)
                try:
                    assert waiting.wait(10)
                    assert not future.done()
                finally:
                    creator.commit()
                assert "Mieterwechsel" in future.result(timeout=10)
        finally:
            event.remove(box.engine, "before_cursor_execute", observed)
    assert box.store.get_property(box.property.id).portfolio_id == box.portfolio.id
