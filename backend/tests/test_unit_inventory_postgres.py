"""Actual PostgreSQL, including the same full 10,002-row source/export gate."""

from backend.tests.test_contract_lifecycle_postgres import postgres as postgres
from backend.tests.test_unit_inventory import (
    test_duplicate_and_null_sort_values_visit_every_unit as stable_pages,
)
from backend.tests.test_unit_inventory import (
    test_late_positions_full_aggregate_and_export_without_global_lists as full_source,
)


def test_postgres_full_units_source(postgres, monkeypatch):
    full_source(postgres.store, monkeypatch)


def test_postgres_units_null_and_duplicate_sort(postgres):
    stable_pages(postgres.store, "cold_rent", "desc")
