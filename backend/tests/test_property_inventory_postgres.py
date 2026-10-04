"""Source-only actual PG parity; explicit target, own UUIDschema and cleanup."""

import os
from time import monotonic

import pytest
from sqlalchemy import text

from backend.db.orm_models import PortfolioORM
from backend.services import property_inventory as service
from backend.services.portfolio_scope import scope_context
from backend.tests.notification_inbox_pg_proposal_support import (
    NODE_SECONDS,
    _close,
    _engine,
    dedicated_url,
    postgres_proposal_database,
)
from backend.tests.property_inventory_support import actor, install_accounts, make_box, native_metadata
from backend.tests.test_property_inventory import (
    query,
    rent_seed,
)
from backend.tests.test_property_inventory import (
    test_contract_date_parents_fanout_and_manual_status_are_distinct as prove_contracts,
)
from backend.tests.test_property_inventory import (
    test_currency_exact_rent_and_null_cursor_parity as prove_currency,
)
from backend.tests.test_property_inventory import (
    test_known_missing_invalid_and_true_empty_rent_are_separate as prove_source_states,
)


@pytest.fixture
def property_pg_box(monkeypatch):
    # Missing/bad URL is an explicit fixture error, never a PG success/skip.
    source = dedicated_url(os.environ.get("TEST_SERVER_DATABASE_URL"))
    with postgres_proposal_database(source) as business:
        owned, box = [], None
        try:
            with business.connect() as connection:
                schema = connection.execute(text("SELECT current_schema()")).scalar_one()
            deadline = monotonic() + NODE_SECONDS
            account = _engine(source, schema, deadline)
            owned.append(account)
            sid = _engine(source, schema, deadline)
            owned.append(sid)
            native_metadata(business)
            with scope_context(None), business.begin() as connection:
                connection.execute(PortfolioORM.__table__.insert(), [
                    {"id": "eur", "name": "Synthetic Euro", "currency": "EUR"},
                    {"id": "usd", "name": "Synthetic Dollar", "currency": "USD"},
                    {"id": "unknown", "name": "Synthetic unknown", "currency": " \t\u3000"},
                ])
            accounts, tokens = install_accounts(monkeypatch, account.engine, sid_engine=sid.engine)
            box = make_box(business, accounts, tokens)
            box.account_engine = account.engine
            yield box
        finally:
            if box is not None:
                box.db.close()
            failures = []
            for native in reversed(owned):
                _close(native, failures)
                assert all(handle.closed for handle in native.handles)
            assert not failures, "Owned property PG adapters did not close"
    # Existing helper proves namespace OID/owner and drops only its own UUID.


@pytest.mark.parametrize("direction,expected", [
    ("asc", ["e-zero", "e-small", "e-tie", "e-large", "e-null", "u-zero", "u-rent", "unknown"]),
    ("desc", ["e-large", "e-tie", "e-small", "e-zero", "e-null", "u-rent", "u-zero", "unknown"]),
])
def test_postgres_currency_cents_and_null_keysets(property_pg_box, direction, expected):
    prove_currency(property_pg_box, direction, expected)


def test_postgres_actual_contract_date_and_parent_counts(property_pg_box):
    prove_contracts(property_pg_box)


def test_postgres_numeric_known_missing_invalid_and_empty(property_pg_box):
    prove_source_states(property_pg_box)


def test_postgres_actual_two_scoped_actors_and_complete_counts(property_pg_box):
    box = property_pg_box
    rent_seed(box)
    with actor(box, "reader-eur"):
        first = service.property_inventory_page(box.store, query(page_size=1))
        assert service.property_inventory_summary(box.store, query()).scope_totals.property_count == 5
        assert first.items[0].portfolio_id == "eur"
    with actor(box, "reader-usd"):
        rows = service.property_inventory_page(box.store, query()).items
        assert len(rows) == 2 and all(row.portfolio_id == "usd" for row in rows)
        assert service.property_inventory_summary(box.store, query()).matching_totals.property_count == 2
