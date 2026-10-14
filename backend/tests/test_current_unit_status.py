"""Units, dashboard and occupancy report take a unit's status from its contracts."""

from datetime import date

import pytest

from backend.dependencies import store
from backend.models import ContractCreate, PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.routers import reports, units
from backend.routers.dashboard import get_dashboard_stats
from backend.services.data_snapshot import clear_business_data


@pytest.fixture(autouse=True)
def _clean():
    clear_business_data(store)
    yield
    clear_business_data(store)


def _list(status=None):
    return units.list_units(skip=0, limit=100, property_id=None, status_filter=status, sort_by=None, sort_order="asc")


def test_units_dashboard_and_report_follow_the_contracts():
    """Regression: a move-in or move-out left the stored status, and every count with it, stale."""
    pf = store.create_portfolio(PortfolioCreate(name="P"))
    prop = store.create_property(PropertyCreate(portfolio_id=pf.id, name="Haus", property_type="residential"))

    def unit(label, stored):
        return store.create_unit(UnitCreate(property_id=prop.id, label=label, unit_type="Wohnung", status=stored))

    def lease(unit_, number, start, end=None, status="active"):
        tenant = store.create_tenant(TenantCreate(full_name=f"Mieter {number}"))
        store.create_contract(ContractCreate(
            contract_number=number, property_id=prop.id, unit_id=unit_.id, tenant_id=tenant.id,
            start_date=start, end_date=end, status=status))

    moved_in, moved_out = unit("WE 01", "vacant"), unit("WE 02", "occupied")
    unit("WE 03", "occupied")  # no contracts: the owner lives there
    unit("WE 04", "reserved")
    lease(moved_in, "V-1", date(2020, 1, 1))
    lease(moved_out, "V-2", date(2018, 1, 1), date(2021, 6, 30), status="terminated")

    assert {u.label: u.status for u in _list()} == {
        "WE 01": "occupied", "WE 02": "vacant", "WE 03": "occupied", "WE 04": "reserved"}
    assert sorted(u.label for u in _list("occupied")) == ["WE 01", "WE 03"]
    assert units.get_unit(moved_out.id).status == "vacant"

    stats = get_dashboard_stats()
    assert (stats["occupied_units"], stats["vacant_units"], stats["reserved_units"]) == (2, 1, 1)
    report = reports.get_occupancy_report(format=None)
    assert (report["totalUnits"], report["rentedUnits"]) == (4, 2)
