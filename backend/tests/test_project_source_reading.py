"""Known project references must remain bounded without unrelated entity families."""
import pytest
from sqlalchemy import event

from backend.dependencies import store
from backend.models import ChangeHistoryEntry, EntityPhoto, MaintenanceCaseCreate, PortfolioCreate, PropertyCreate
from backend.services.maintenance_projects import read_project, work
from backend.services.maintenance_rows import Rows
from backend.services.portfolio_scope import AccessScope, scope_context
from backend.storage import NotFoundError
from backend.tests.test_finance_packages_v2 import clean  # noqa: F401
from backend.tests.test_finance_packages_v2 import estate as _estate_fixture  # noqa: F401


@pytest.fixture(name="estate")
def project_estate(request):
    return request.getfixturevalue("_estate_fixture")


@pytest.mark.parametrize("table", ["change_history", "entity_photos"])
def test_project_reference_reads_retain_type_parent_and_portfolio_guards(estate, table):
    other = store.create_portfolio(PortfolioCreate(name="Privater Fremdbestand"))
    hidden_house = store.create_property(PropertyCreate(portfolio_id=other.id, name="Verborgen", property_type="residential"))
    cases = [store.create_maintenance_case(MaintenanceCaseCreate(property_id=house, title="Fall"))
             for house in (estate[1].id, hidden_house.id)]
    with work(store, None, ()) as unit:
        rows = Rows.of(unit)
        for index, case in enumerate(cases):
            row: ChangeHistoryEntry | EntityPhoto
            if table == "change_history":
                row = ChangeHistoryEntry(id=f"source-{index}", entity_type="maintenance", entity_id=case.id,
                                         field_name="status", old_value="open", new_value="in_progress")
            else:
                row = EntityPhoto(id=f"source-{index}", entity_type="maintenance", entity_id=case.id,
                                  file_url=f"uploads/source-{index}.jpg", caption="Belegfoto")
            rows.add(table, row)
        rows.add(table, row.model_copy(update={"id": "other-entity-type", "entity_type": "property", "entity_id": cases[0].id}))
    statements = []
    engine = store.db.get_bind() if hasattr(store, "db") else None

    def observed(_connection, _cursor, statement, _parameters, _context, _many):
        if f"FROM {table}" in statement:
            statements.append(statement)

    if engine is not None:
        event.listen(engine, "before_cursor_execute", observed)
    try:
        with scope_context(AccessScope("source-reader", "verwalter", False, (estate[0].id,))):
            rows = Rows.reading(store)
            assert [item.id for item in rows.find_case_entities(table, cases[0].id)] == ["source-0"]
            with pytest.raises(NotFoundError):
                rows.find_case_entities(table, cases[1].id)
            projection = read_project(store, cases[0].id, {"role": "verwalter"})
            assert [item["id"] for item in projection["history" if table == "change_history" else "photos"]] == ["source-0"]
            with pytest.raises(NotFoundError):
                read_project(store, cases[1].id, {"role": "verwalter"})
        if engine is not None:
            assert statements
            # A known maintenance parent must not compile every unrelated polymorphic
            # hierarchy. This is a query-complexity regression, not a wall-clock test.
            assert max(map(len, statements)) < 20_000
    finally:
        if engine is not None:
            event.remove(engine, "before_cursor_execute", observed)


def test_case_reference_shortcut_cannot_be_used_for_independent_financial_sources(estate):
    case = store.create_maintenance_case(MaintenanceCaseCreate(property_id=estate[1].id, title="Fall"))
    with pytest.raises(ValueError):
        Rows.reading(store).find_case_entities("invoices", case.id)
