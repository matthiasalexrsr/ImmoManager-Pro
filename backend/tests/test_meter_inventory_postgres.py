"""Same meter projections and original history on an actual isolated PostgreSQL schema."""

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from backend.repositories.sql_store import SQLAlchemyStore
from backend.tests.measurement_history_postgres_support import migrated_postgres
from backend.tests.test_meter_inventory import (
    test_bounded_sql_never_autoflush_or_load_all_history as bounded_sql,
)
from backend.tests.test_meter_inventory import (
    test_complete_late_inventory_summary_and_csv as complete,
)
from backend.tests.test_meter_inventory import (
    test_duplicate_and_null_keysets as stable,
)
from backend.tests.test_meter_inventory import (
    test_independent_latest_reading_change_aborts_export as changed_export,
)
from backend.tests.test_meter_inventory import (
    test_latest_tie_and_bounded_long_original_history as history,
)
from backend.tests.test_meter_inventory import (
    test_scope_detail_history_summary_export_and_revoke as access,
)


@pytest.fixture
def postgres(monkeypatch):
    # This slice needs the actual composed e2 unit column and j2/k2 guards.
    # Each case owns one disposable schema and seeds its own authorized rows.
    with migrated_postgres(monkeypatch) as (engine, _config):
        with Session(engine) as db:
            yield SimpleNamespace(store=SQLAlchemyStore(db), engine=engine, db=db)


def test_postgres_complete_meter_source(postgres, monkeypatch):
    complete(postgres.store, monkeypatch)


def test_postgres_meter_null_and_tied_order(postgres):
    stable(postgres.store, "last_reading_date", "desc")


def test_postgres_long_meter_original_history(postgres, monkeypatch):
    history(postgres.store, monkeypatch)


def test_postgres_bounded_reads_no_autoflush(postgres):
    bounded_sql(postgres.store)


def test_postgres_meter_access_and_revocation(postgres, monkeypatch):
    access(postgres.store, monkeypatch)


def test_postgres_latest_reading_change_stops_export(postgres):
    changed_export(postgres.store)
