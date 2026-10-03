"""Explicit PostgreSQL proof of legacy maintenance date-filter completeness."""

from backend.tests.test_contract_lifecycle_postgres import postgres as postgres
from backend.tests.test_maintenance_date_filter import (
    test_finds_late_case_without_global_lists_or_ten_thousand_cutoff as late_case,
)
from backend.tests.test_maintenance_date_filter import (
    test_offset_scope_and_deterministic_null_ties as stable_scope,
)


def test_postgres_maintenance_after_old_cap(postgres, monkeypatch):
    late_case(postgres.store, monkeypatch)


def test_postgres_maintenance_scope_sort_and_offset(postgres, monkeypatch):
    stable_scope(postgres.store, monkeypatch)
