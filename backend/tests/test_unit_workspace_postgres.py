"""The bounded unit context on an actual owned PostgreSQL schema."""

from backend.tests.test_contract_lifecycle_postgres import postgres as postgres
from backend.tests.test_unit_workspace import (
    test_independent_pages_reach_all_rows_and_reject_other_unit_cursor as insurance_pages,
)
from backend.tests.test_unit_workspace import test_late_exact_unit_contracts_do_not_use_global_lists as bounded_context


def test_postgres_unit_workspace_exact_late_context(postgres, monkeypatch):
    bounded_context(postgres.store, monkeypatch)


def test_postgres_unit_insurance_pages_and_other_unit_cursor(postgres):
    insurance_pages(postgres.store, "insurances", "insurance_cursor")
