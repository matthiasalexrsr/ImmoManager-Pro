"""Dedicated UUID-schema PG evidence for complete history and real time binds."""

from backend.tests.test_history_inventory import (
    test_complete_large_source_filter_summary_legacy_and_export as full_source,
)
from backend.tests.test_history_inventory import (
    test_polymorphic_portfolio_scope_and_cursor_actor_binding as scope_and_cursor,
)
from backend.tests.test_history_inventory import (
    test_ties_unicode_search_exact_fields_interval_and_cursor_binding as ties_and_filters,
)
from backend.tests.test_housing_confirmation_postgres import postgres_housing as postgres_housing


def test_postgres_complete_history_and_export(postgres_housing, monkeypatch):
    full_source(postgres_housing.store, monkeypatch)


def test_postgres_history_time_ties_and_filters(postgres_housing):
    ties_and_filters(postgres_housing.store)


def test_postgres_history_polymorphic_scope_and_cursor(postgres_housing, monkeypatch):
    scope_and_cursor(postgres_housing.store, monkeypatch)
