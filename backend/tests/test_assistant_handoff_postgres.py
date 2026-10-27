"""An independent writer cannot move a form-selected unit during final save."""
from types import SimpleNamespace

from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend import auth
from backend.db.orm_models import UnitORM
from backend.models import PortfolioCreate, PropertyCreate, UnitCreate
from backend.repositories import SQLAlchemyStore
from backend.services import assistant, assistant_handoff
from backend.services.portable_runtime import inventory
from backend.tests import test_assistant_handoff as helpers
from backend.tests.test_assistant_handoff import prepared, save
from backend.tests.test_document_versions_postgres import postgres as postgres  # noqa: F401


def test_postgres_backup_inventory_binds_virtual_archive_prefix(postgres):
    engine, _ = postgres
    with engine.connect() as connection:
        references, keys = inventory(connection)
    assert references == set() and keys == set()


def test_human_selected_unit_cannot_move_between_validation_and_insert(postgres, monkeypatch, request):
    engine, _ = postgres
    store = SQLAlchemyStore(Session(engine))
    request.addfinalizer(store.db.close)
    monkeypatch.setattr(helpers, 'store', store)
    monkeypatch.setattr(assistant, 'wake', lambda *args: None)
    owner = auth.register_user('assistant-race', 'race@example.test', 'Race', 'Secret123', 'eigentuemer')
    portfolio = store.create_portfolio(PortfolioCreate(name='Race'))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name='Original', property_type='residential'))
    foreign = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name='Other', property_type='residential'))
    location = store.create_unit(UnitCreate(property_id=prop.id, label='Left', unit_type='apartment'))
    estate = SimpleNamespace(user=owner, prop=prop, foreign=foreign, unit=location)
    proposal, values, _ = prepared(estate, free=True)
    values = {**values, 'property_id': estate.prop.id, 'unit_id': estate.unit.id}
    original = assistant_handoff._insert
    attempted = []

    def competing_write(unit, collection, model, orm):
        if collection == 'tasks':
            try:
                with unit.db.get_bind().begin() as connection:
                    connection.exec_driver_sql("SET LOCAL lock_timeout='250ms'")
                    connection.execute(update(UnitORM).where(UnitORM.id == estate.unit.id).values(property_id=estate.foreign.id))
                attempted.append('moved')
            except DBAPIError as error:
                if getattr(error.orig, 'pgcode', None) != '55P03':
                    raise
                attempted.append('locked')
        return original(unit, collection, model, orm)

    monkeypatch.setattr(assistant_handoff, '_insert', competing_write)
    result, _ = save(estate, proposal, values)
    created = store.get_task(result['record']['id'])
    with store.db.get_bind().connect() as connection:
        current_property = connection.scalar(select(UnitORM.property_id).where(UnitORM.id == estate.unit.id))
    assert attempted == ['locked']
    assert created.property_id == current_property == estate.prop.id
