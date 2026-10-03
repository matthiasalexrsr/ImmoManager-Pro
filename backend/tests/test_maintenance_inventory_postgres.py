"""Real PostgreSQL parity for maintenance operational sources."""

from backend.tests.test_contract_lifecycle_postgres import postgres as postgres
from backend.tests.test_inventory_export_consistency import (
    test_sql_concurrent_source_change_aborts_complete_export as changed_export,
)
from backend.tests.test_maintenance_inventory import (
    test_cursor_null_ties_dates_and_zero_cost_are_stable as stable_cursor,
)
from backend.tests.test_maintenance_inventory import (
    test_full_operational_source_search_summary_export as full_source,
)
from backend.tests.test_maintenance_inventory import (
    test_operational_filters_count_missing_values_and_explicit_day as filters,
)


def test_postgres_full_maintenance_source(postgres, monkeypatch):
    full_source(postgres.store, monkeypatch)


def test_postgres_maintenance_stable_cursor(postgres):
    stable_cursor(postgres.store, "estimated_cost", "asc")


def test_postgres_maintenance_filters(postgres):
    filters(postgres.store)


def test_postgres_maintenance_export_change(postgres):
    changed_export(postgres.store, "maintenance")
