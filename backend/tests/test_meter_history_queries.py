"""A single history reads only its meter, with the existing portfolio boundary."""

from datetime import date, datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import scoped_session, sessionmaker

from backend import db as _db  # noqa: F401 (register portfolio graph tables)
from backend.db.orm_models import Base, StandaloneMeterReadingORM
from backend.models import MeterCreate, PortfolioCreate, PropertyCreate, StandaloneMeterReading, UnitCreate
from backend.repositories import SQLAlchemyStore
from backend.services import meter_history
from backend.services.portfolio_scope import AccessScope, scope_context
from backend.storage import InMemoryStore, NotFoundError


@pytest.fixture(params=["memory", "sql"])
def source(request, tmp_path):
    engine = None
    registry = None
    store: InMemoryStore | SQLAlchemyStore
    if request.param == "sql":
        engine = sa.create_engine(f"sqlite:///{tmp_path / 'meter-history.db'}")
        Base.metadata.create_all(engine)
        registry = scoped_session(sessionmaker(bind=engine, autoflush=False))
        store = SQLAlchemyStore(registry)  # type: ignore[arg-type]
    else:
        store = InMemoryStore()
    yield store
    if registry is not None:
        registry.remove()
    if engine is not None:
        engine.dispose()


def estate(source):
    north = source.create_portfolio(PortfolioCreate(name="Nord"))
    south = source.create_portfolio(PortfolioCreate(name="Süd"))
    meters = []
    for label, portfolio in (("Selected", north), ("Other visible", north), ("Foreign", south)):
        house = source.create_property(PropertyCreate(name=label, property_type="residential", portfolio_id=portfolio.id))
        unit = source.create_unit(UnitCreate(property_id=house.id, label=label, unit_type="residential", area_sqm=60))
        meters.append(source.create_meter(MeterCreate(unit_id=unit.id, meter_type="electricity", serial_number=label)))
    return north, south, meters


def put_readings(source, rows):
    if hasattr(source, "db"):
        source.db.add_all(StandaloneMeterReadingORM(**row.model_dump()) for row in rows)
        source.db.commit()
    else:
        source.standalone_meter_readings.update({row.id: row for row in rows})


def test_one_meter_history_preserves_order_and_current_scope_without_global_read(source, monkeypatch):
    north, south, (selected, other, foreign) = estate(source)
    early = datetime(2026, 10, 1, tzinfo=timezone.utc)
    later = datetime(2026, 10, 2, tzinfo=timezone.utc)
    rows = [StandaloneMeterReading(id=identifier, meter_id=meter, reading_date=day, value=value,
            created_at=stamp, notes=note) for identifier, meter, day, stamp, value, note in (
        ("z-last", selected.id, date(2026, 1, 1), later, 220, "Last"),
        ("other-visible", other.id, date(2026, 1, 1), early, 500, "OTHER-METER-PRIVATE"),
        ("b-middle", selected.id, date(2026, 1, 1), early, 150, "Middle B"),
        ("foreign", foreign.id, date(2026, 1, 1), early, 999, "FOREIGN-PORTFOLIO-PRIVATE"),
        ("a-start", selected.id, date(2000, 1, 1), later, 100, "Twenty-year history"),
        ("a-middle", selected.id, date(2026, 1, 1), early, 140, "Middle A"),
    )]
    put_readings(source, rows)
    monkeypatch.setattr(source, "list_standalone_meter_readings", lambda: pytest.fail("History must not materialize all meters' readings"))

    with scope_context(AccessScope("north-reader", "verwalter", False, (north.id,))):
        result = meter_history.history(source, selected.id)
        assert [row["id"] for row in result["readings"]] == ["a-start", "a-middle", "b-middle", "z-last"]
        assert [row["consumption"] for row in result["readings"]] == [None, 40, 10, 70]
        assert "OTHER-METER-PRIVATE" not in str(result)
        assert "FOREIGN-PORTFOLIO-PRIVATE" not in str(result)
        # The filtered repository/collection enforces scope even without the
        # public service's initial authorized get_meter call.
        assert meter_history._readings(source, foreign.id) == []
        with pytest.raises(NotFoundError):
            meter_history.history(source, foreign.id)
    with scope_context(AccessScope("revoked-reader", "verwalter", False, ())):
        assert meter_history._readings(source, selected.id) == []
        with pytest.raises(NotFoundError):
            meter_history.history(source, selected.id)
    with scope_context(AccessScope("south-reader", "verwalter", False, (south.id,))):
        assert [row.id for row in meter_history._readings(source, foreign.id)] == ["foreign"]


def test_sql_repository_applies_meter_predicate_before_materializing_rows(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'filtered.db'}")
    Base.metadata.create_all(engine)
    registry = scoped_session(sessionmaker(bind=engine, autoflush=False))
    source = SQLAlchemyStore(registry)  # type: ignore[arg-type]
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "FROM standalone_meter_readings" in statement:
            statements.append((statement, parameters))

    try:
        north, _, (selected, other, _) = estate(source)
        put_readings(source, [StandaloneMeterReading(id=identifier, meter_id=meter, reading_date=date(2026, 1, 1), value=123)
                              for identifier, meter in (("selected", selected.id), ("other", other.id))])
        monkeypatch.setattr(source, "list_standalone_meter_readings", lambda: pytest.fail("No global readings list"))
        sa.event.listen(engine, "before_cursor_execute", capture)
        with scope_context(AccessScope("north-reader", "verwalter", False, (north.id,))):
            assert [row.id for row in meter_history._readings(source, selected.id)] == ["selected"]
        assert len(statements) == 1
        sql, parameters = statements[0]
        assert "standalone_meter_readings.meter_id =" in sql
        assert selected.id in parameters
        assert north.id in parameters  # The existing Session still installs the portfolio predicate.
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)
        registry.remove()
        engine.dispose()
