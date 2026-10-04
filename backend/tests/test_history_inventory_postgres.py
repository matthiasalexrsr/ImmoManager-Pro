"""Dedicated UUID-schema PG evidence for complete history and real time binds."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from backend.db.orm_models import ChangeHistoryORM
from backend.services.history_inventory import HistoryInventoryQuery, history_inventory_summary
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


def test_postgres_actual_repository_writer_keeps_utc_under_two_session_zones(postgres_housing):
    store = postgres_housing.store
    for zone in ("Europe/Berlin", "America/New_York"):
        store.db.execute(text("SET TIME ZONE '" + zone + "'"))
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        actual = store.add_change_history("property", postgres_housing.property.id, zone, "before", "after")
        after = datetime.now(timezone.utc).replace(tzinfo=None)
        raw = store.db.scalar(select(ChangeHistoryORM.__table__.c.changed_at).where(ChangeHistoryORM.id == actual.id))
        assert raw.tzinfo is None and before <= raw <= after
        result = history_inventory_summary(store, HistoryInventoryQuery(entity_id=postgres_housing.property.id, field_name=zone,
            changed_from=before - timedelta(milliseconds=1), changed_before=after + timedelta(milliseconds=1)))
        assert result["total"] == 1
