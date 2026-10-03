"""Native complete image checks before security changes or publication."""

import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text, update

from backend.db.billing_dispute_models import DISPUTE_TABLES, BillingDisputeEventORM
from backend.db.billing_dispute_schema import install_dispute_guards
from backend.db.orm_models import UtilityStatementORM
from backend.services.billing_dispute_database import validate_dispute_database
from backend.services.billing_dispute_validation import DisputeIntegrityError
from backend.services.data_transfer import TransferError, export_store_data
from backend.services.full_recovery import _database_info
from backend.services.recovery_archive import RecoveryError
from backend.services.recovery_retained import guard_operational_history
from backend.services.recovery_sessions import SessionRestoreError, invalidate_and_inspect
from backend.storage import ValidationError
from backend.tests.form_draft_api_support import application, migrate
from backend.tests.measurement_history_postgres_support import migrated_postgres
from backend.tests.test_billing_consumption_http import context as context_fixture
from backend.tests.test_billing_disputes import finalized, opening, preview_confirm
from backend.tests.test_measurement_history_integrity import original as archive_original

context = context_fixture
ROOT = Path(__file__).resolve().parents[2]
PURE_PROOF = '''
import importlib.abc, sqlite3, sys
from contextlib import closing
class DenyAmbient(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"backend.auth", "backend.config", "backend.dependencies", "backend.app", "backend.storage"}:
            raise AssertionError("native original proof reached ambient runtime/store")
sys.meta_path.insert(0, DenyAmbient())
from backend.services.billing_dispute_database import validate_dispute_database
from pathlib import Path
with closing(sqlite3.connect(Path(sys.argv[1]).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    assert validate_dispute_database(connection)
print("PURE_DISPUTE_ORIGINAL_PROOF")
'''


@pytest.fixture(params=["sqlite", "postgres"])
def draft_http(request, monkeypatch, tmp_path):
    if request.param == "postgres":
        with migrated_postgres(monkeypatch) as (engine, _), application(monkeypatch, engine) as active:
            yield active
        return
    url = "sqlite:///" + (tmp_path / "native-disputes.sqlite").as_posix()
    migrate(url, monkeypatch)
    engine = create_engine(url, hide_parameters=True, connect_args={"check_same_thread": False})
    try:
        with application(monkeypatch, engine) as active:
            yield active
    finally:
        engine.dispose()


@contextmanager
def privileged_edit(engine):
    """Explicit tampering solely in this fixture's owned disposable database."""
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            keys = [row[0] for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND "
                "(name LIKE 'preserve_billing_dispute_%' OR name LIKE 'preserve_dispute_case_%')")]
            for key in keys:
                connection.exec_driver_sql('DROP TRIGGER "' + key + '"')
        else:
            for name in DISPUTE_TABLES:
                connection.exec_driver_sql(f'ALTER TABLE "{name}" DISABLE TRIGGER USER')
        yield connection
        if engine.dialect.name == "sqlite":
            install_dispute_guards(connection)
        else:
            for name in DISPUTE_TABLES:
                connection.exec_driver_sql(f'ALTER TABLE "{name}" ENABLE TRIGGER USER')


def populated(context, monkeypatch, tmp_path):
    statement = finalized(context)
    version = archive_original(context, monkeypatch, tmp_path)
    draft = opening(context, statement, evidence_version_ids=[version])
    _, receipt = preview_confirm(context, draft)
    preview_confirm(context, {"expected_revision": 1, "kind": "note", "reason": "Erhaltener Prüfvermerk €",
        "observed_on": "2026-10-03", "idempotency_key": "native-second-event"}, receipt["case_id"], status=200)
    context["active"].store.db.remove()
    return statement, receipt


def test_native_sql_and_raw_sqlite_prove_originals_receipts_and_evidence_without_mutation(context, monkeypatch, tmp_path):
    populated(context, monkeypatch, tmp_path)
    engine = context["active"].engine
    with engine.connect() as connection:
        before = connection.execute(text("SELECT reason,content_hash FROM billing_dispute_events ORDER BY id")).all()
        assert validate_dispute_database(connection, deadline=time.monotonic() + 30)
        if engine.dialect.name == "sqlite":
            assert validate_dispute_database(connection.connection.driver_connection)
        assert connection.execute(text("SELECT reason,content_hash FROM billing_dispute_events ORDER BY id")).all() == before
        with pytest.raises(DisputeIntegrityError, match="Zeitbudget"):
            validate_dispute_database(connection, deadline=time.monotonic() - 1)
    if engine.dialect.name == "sqlite":
        result = subprocess.run([sys.executable, "-c", PURE_PROOF, engine.url.database], cwd=ROOT,
            capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert "PURE_DISPUTE_ORIGINAL_PROOF" in result.stdout


def test_changed_reason_with_reinstalled_native_guards_blocks_security_before_any_update(context, monkeypatch, tmp_path):
    _, receipt = populated(context, monkeypatch, tmp_path)
    engine = context["active"].engine
    with privileged_edit(engine) as connection:
        connection.execute(update(BillingDisputeEventORM).where(BillingDisputeEventORM.id == receipt["event_id"]).values(reason="privileged changed original"))
    with engine.begin() as connection:
        before = connection.execute(text("SELECT id,revoked_at FROM auth_sessions ORDER BY id")).all()
        with pytest.raises(DisputeIntegrityError):
            validate_dispute_database(connection)
        with pytest.raises(SessionRestoreError, match="restore_dispute_history_invalid"):
            invalidate_and_inspect(connection, {}, deadline=time.monotonic() + 30)
        assert connection.execute(text("SELECT id,revoked_at FROM auth_sessions ORDER BY id")).all() == before
    if engine.dialect.name == "sqlite":
        with pytest.raises(RecoveryError, match="Widerspruchsoriginale"):
            _database_info(Path(engine.url.database))


def test_unreferenced_sibling_statement_change_cannot_hide_outside_case_parent_projection(context, monkeypatch, tmp_path):
    statement, _ = populated(context, monkeypatch, tmp_path)
    engine = context["active"].engine
    with engine.begin() as connection:
        # A privileged source edit to the other tenant's row must change the
        # complete period hash even though this case references only its party.
        connection.execute(update(UtilityStatementORM).where(UtilityStatementORM.id != statement["id"],
            UtilityStatementORM.billing_period_id == statement["billing_period_id"]).values(balance=123))
    with engine.connect() as connection, pytest.raises(DisputeIntegrityError):
        validate_dispute_database(connection)


def test_business_subset_export_and_reset_preserve_retained_dispute_originals(context, monkeypatch, tmp_path):
    populated(context, monkeypatch, tmp_path)
    store = context["active"].store
    with pytest.raises(ValidationError, match="Vollständige Offline"):
        guard_operational_history(store)
    with pytest.raises(TransferError, match="Vollständige Offline"):
        export_store_data(store, "synthetic-dispute-subset")
    with pytest.raises(ValidationError, match="Vollständige Offline"):
        store.clear_all()
    store.db.remove()
    with context["active"].engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM billing_dispute_cases")) == 1
        assert connection.scalar(text("SELECT COUNT(*) FROM billing_dispute_events")) == 2


def test_wholly_absent_legacy_is_compatible_but_partial_family_is_not(tmp_path):
    with sqlite3.connect(tmp_path / "owned-empty-legacy.sqlite") as connection:
        assert validate_dispute_database(connection) is False
        connection.execute("CREATE TABLE billing_dispute_cases(id TEXT PRIMARY KEY)")
        with pytest.raises(DisputeIntegrityError):
            validate_dispute_database(connection)
