"""Whole native originals with no case, fresh import denial and security barriers."""

import sqlite3
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import text, update

from backend.db.orm_models import BillingPeriodORM
from backend.services.billing_statement_parties import KEY, StatementPartyIntegrityError
from backend.services.billing_statement_party_database import validate_statement_party_database
from backend.services.data_transfer import TransferError, export_store_data
from backend.services.full_recovery import _database_info
from backend.services.recovery_archive import RecoveryError
from backend.services.recovery_retained import guard_operational_history
from backend.services.recovery_sessions import SessionRestoreError, invalidate_and_inspect
from backend.storage import ValidationError
from backend.tests.test_billing_consumption_http import context as context
from backend.tests.test_billing_dispute_database import draft_http as draft_http
from backend.tests.test_billing_disputes import finalized

ROOT = Path(__file__).resolve().parents[2]
PURE_PROOF = '''
import importlib.abc, sqlite3, sys
from contextlib import closing
from pathlib import Path
class Reject(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = ("backend.auth", "backend.config", "backend.dependencies", "backend.app", "backend.storage",
            "backend.repositories", "backend.services.billing_settlement", "backend.services.billing_statement_party_storage")
        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
            raise AssertionError("native whole-party proof reached ambient runtime")
sys.meta_path.insert(0, Reject())
from backend.services.billing_statement_party_database import validate_statement_party_database
with closing(sqlite3.connect(Path(sys.argv[1]).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    assert validate_statement_party_database(connection)
print("PURE_WHOLE_PARTY_ORIGINAL_PROOF")
'''


def original(context):
    statement = finalized(context)
    active = context["active"]
    period = active.client.get("/api/v1/billing/periods/" + statement["billing_period_id"], headers=context["headers"]).json()
    active.store.db.remove()
    return statement, period


def test_whole_original_without_case_survives_current_identity_changes_native_and_pure(context):
    statement, period = original(context)
    context["patch"]("/tenants/" + context["leases"][0]["tenant_id"], {"full_name": "Today's later identity"})
    active = context["active"]
    active.store.db.remove()
    with active.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM billing_dispute_cases")) == 0
        assert validate_statement_party_database(connection, deadline=time.monotonic() + 30)
        if active.engine.dialect.name == "sqlite":
            assert validate_statement_party_database(connection.connection.driver_connection)
        with pytest.raises(StatementPartyIntegrityError):
            validate_statement_party_database(connection, deadline=time.monotonic() - 1)
    fresh = active.client.get("/api/v1/billing/periods/" + statement["billing_period_id"], headers=context["headers"])
    assert fresh.json()["owner_cost_share"] == period["owner_cost_share"]
    if active.engine.dialect.name == "sqlite":
        result = subprocess.run([sys.executable, "-c", PURE_PROOF, active.engine.url.database], cwd=ROOT,
            capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert "PURE_WHOLE_PARTY_ORIGINAL_PROOF" in result.stdout


def test_damaged_party_original_without_case_blocks_before_session_or_archive_changes(context):
    _, period = original(context)
    changed = deepcopy(period["owner_cost_share"])
    next(iter(changed[KEY]["statements"].values()))["identity"]["full_name"] = "Changed native original"
    active = context["active"]
    with active.engine.begin() as connection:
        connection.execute(update(BillingPeriodORM).where(BillingPeriodORM.id == period["id"]).values(owner_cost_share=changed))
    with active.engine.begin() as connection:
        before = connection.execute(text("SELECT id,revoked_at FROM auth_sessions ORDER BY id")).all()
        with pytest.raises(StatementPartyIntegrityError):
            validate_statement_party_database(connection)
        with pytest.raises(SessionRestoreError, match="restore_statement_party_original_invalid"):
            invalidate_and_inspect(connection, {}, deadline=time.monotonic() + 30)
        assert connection.execute(text("SELECT id,revoked_at FROM auth_sessions ORDER BY id")).all() == before
    if active.engine.dialect.name == "sqlite":
        with pytest.raises(RecoveryError, match="Originalparteien"):
            _database_info(Path(active.engine.url.database))


def test_no_case_does_not_allow_business_subset_to_drop_party_originals(context):
    original(context)
    active = context["active"]
    with pytest.raises(ValidationError, match="Vollständige Offline"):
        guard_operational_history(active.store)
    with pytest.raises(TransferError, match="Vollständige Offline"):
        export_store_data(active.store, "synthetic-party-subset")
    with pytest.raises(ValidationError, match="Vollständige Offline"):
        active.store.clear_all()
    active.store.db.remove()
    with active.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM utility_statements")) == 2
        assert validate_statement_party_database(connection)


def test_absent_old_tables_are_compatible_partial_tables_are_not(tmp_path):
    with sqlite3.connect(tmp_path / "owned-empty.sqlite") as connection:
        assert validate_statement_party_database(connection) is False
        connection.execute("CREATE TABLE billing_periods(id TEXT PRIMARY KEY, owner_cost_share JSON)")
        with pytest.raises(StatementPartyIntegrityError):
            validate_statement_party_database(connection)
