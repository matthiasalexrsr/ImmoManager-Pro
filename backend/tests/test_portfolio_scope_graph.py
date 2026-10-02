"""Polymorphic links must preserve identity, deny cycles and use fresh scopes."""

import pytest
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from backend.db.orm_models import ContractORM, EntityPhotoORM, NotificationORM, TaskORM
from backend.models import TaskCreate
from backend.services.portfolio_scope import AccessScope, scope_context, scoped_clause
from backend.tests.test_portfolio_scope import scoped_store  # noqa: F401


def test_polymorphic_links_reject_cycles_dangling_ids_and_the_other_portfolio(scoped_store):  # noqa: F811 — pytest fixture
    store, engine, scope, portfolios, properties, *_ = scoped_store
    if not hasattr(store, "db"):
        pytest.skip("Statement-local SQL relations belong to the SQL backend")
    with scope_context(None), engine.begin() as connection:
        connection.execute(insert(EntityPhotoORM), [
            {"id": "left-photo", "entity_type": "property", "entity_id": properties[0].id, "file_url": "fixture://left"},
            {"id": "right-photo", "entity_type": "property", "entity_id": properties[1].id, "file_url": "fixture://right"},
            {"id": "cycle-photo", "entity_type": "notification", "entity_id": "cycle-notice", "file_url": "fixture://cycle"},
            {"id": "dangling-photo", "entity_type": "property", "entity_id": "missing-property", "file_url": "fixture://missing"},
        ])
        connection.execute(insert(NotificationORM), [
            {"id": "left-notice", "entity_type": "entity_photo", "entity_id": "left-photo", "notification_type": "test", "title": "Left", "content": "Synthetic"},
            {"id": "right-notice", "entity_type": "entity_photo", "entity_id": "right-photo", "notification_type": "test", "title": "Right", "content": "Synthetic"},
            {"id": "cycle-notice", "entity_type": "entity_photo", "entity_id": "cycle-photo", "notification_type": "test", "title": "Cycle", "content": "Synthetic"},
        ])
    for selected, expected_photo, expected_notice in (
        (scope, "left-photo", "left-notice"),
        (AccessScope(scope.user_id, scope.role, False, (portfolios[1].id,)), "right-photo", "right-notice"),
    ):
        with scope_context(selected), Session(engine) as independent:
            assert independent.scalars(select(EntityPhotoORM.id)).all() == [expected_photo]
            assert independent.scalars(select(NotificationORM.id)).all() == [expected_notice]
            with engine.connect() as connection:
                statement = select(NotificationORM.id).where(scoped_clause(NotificationORM))
                assert connection.scalars(statement).all() == [expected_notice]
    with scope_context(AccessScope(scope.user_id, scope.role, False, ())):
        with Session(engine) as independent:
            assert independent.scalars(select(NotificationORM.id)).all() == []


def test_scoped_sqlite_dml_counts_match_cas_targets_and_rollback_is_real(scoped_store):  # noqa: F811 — pytest fixture
    store, engine, scope, _, properties, *_, contracts = scoped_store
    if not hasattr(store, "db"):
        pytest.skip("sqlite3 CTE DML transaction handling belongs to SQL")
    with scope_context(None):
        tasks = [store.create_task(TaskCreate(title="Original", property_id=properties[index].id))
                 for index in (0, 0, 1)]
    with scope_context(scope), Session(engine) as independent:
        matched = independent.execute(update(TaskORM).where(TaskORM.id == tasks[0].id).values(title="Changed"))
        assert matched.rowcount == 1
        stale = independent.execute(update(TaskORM).where(TaskORM.id == tasks[0].id, TaskORM.title == "Original").values(title="Stale overwrite"))
        assert stale.rowcount == 0
        forbidden = independent.execute(update(TaskORM).where(TaskORM.id == tasks[2].id).values(title="Forbidden"))
        assert forbidden.rowcount == 0
        independent.rollback()
    with scope_context(None), Session(engine) as independent:
        assert independent.scalars(select(TaskORM.title).order_by(TaskORM.id)).all() == ["Original"] * 3
    with scope_context(scope), Session(engine) as independent:
        multiple = independent.execute(update(TaskORM).where(TaskORM.title == "Original").values(title="Changed"))
        assert multiple.rowcount == 2
        no_op_lock = independent.execute(update(ContractORM).where(ContractORM.id == contracts[0].id)
                                         .values(updated_at=ContractORM.updated_at))
        assert no_op_lock.rowcount == 1
        removed = independent.execute(delete(TaskORM).where(TaskORM.title == "Changed"))
        assert removed.rowcount == 2
        independent.rollback()
    with scope_context(None), Session(engine) as independent:
        assert independent.scalars(select(TaskORM.title)).all() == ["Original"] * 3
