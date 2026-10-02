"""Actual disposable PostgreSQL and independent lifecycle/privacy writers."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import contract_lifecycle as lifecycle
from backend.services.contract_lifecycle_types import DraftCreate
from backend.services.tenant_privacy import (
    PrivacyConflict,
    anonymize_tenant_profile,
    export_tenant_metadata,
    preview_tenant_anonymization,
)
from backend.tests.test_contract_lifecycle_postgres import postgres as postgres_fixture
from backend.tests.test_tenant_lifecycle_privacy import (
    accepted,
)
from backend.tests.test_tenant_lifecycle_privacy import (
    test_actual_confirmed_evidence_and_hashes_private_work_not_materialized as check_disclosure,
)
from backend.tests.test_tenant_lifecycle_privacy import (
    test_profile_anonymization_preserves_all_lifecycle_rows_and_explicit_retention as check_retention,
)
from backend.tests.test_tenant_lifecycle_privacy import (
    test_superseded_and_current_confirmed_results_keep_original_reasons as check_supersession,
)

postgres = postgres_fixture


@pytest.fixture
def active_pg(postgres):
    postgres.users["other"] = {**postgres.users["actor"], "id": "other"}
    return postgres


def test_pg_disclosure_hashes_and_original_confirmed_download(active_pg, monkeypatch, tmp_path):
    check_disclosure(active_pg, monkeypatch)
    # Use the already created accepted record/private metadata for a fresh
    # actual download; a second command must not mutate the terminated parent.
    from backend.services.tenant_privacy import prepare_tenant_export
    compiled, _ = prepare_tenant_export(active_pg.store, active_pg.tenant.id, parent=tmp_path)
    try:
        assert compiled.path.stat().st_size == compiled.manifest["size"]
    finally:
        compiled.close()


def test_pg_profile_preserves_all_accepted_and_private_lifecycle_rows(active_pg, monkeypatch):
    check_retention(active_pg, monkeypatch)


def test_pg_supersession_keeps_original_results(active_pg):
    check_supersession(active_pg)


def test_pg_contract_writer_excludes_anonymization_without_deadlock(active_pg, monkeypatch):
    accepted(active_pg, monkeypatch)
    plan = preview_tenant_anonymization(active_pg.store, active_pg.tenant.id)
    locked, release = Event(), Event()
    def hold_contract(_connection, _cursor, statement, _parameters, _context, _many):
        if (current_thread().name.startswith("lifecycle-writer") and "FROM contracts" in statement
                and "FOR UPDATE" in statement and not locked.is_set()):
            locked.set()
            assert release.wait(15), "profile write did not return within the bounded concurrency test deadline"
    payload = DraftCreate(idempotency_key="concurrent-private",
        expected_contract_etag=lifecycle.contract_etag(active_pg.store.get_contract(active_pg.contract.id)),
        data={"operation": "termination", "termination_end_date": "2026-11-29", "reason": "PRIVATE_IN_FLIGHT_808"})
    def create_private():
        with Session(active_pg.engine) as session:
            return lifecycle.create_draft(SQLAlchemyStore(session), active_pg.contract.id, payload, "other")
    event.listen(active_pg.engine, "after_cursor_execute", hold_contract)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="lifecycle-writer") as pool:
            future = pool.submit(create_private)
            try:
                assert locked.wait(10)
                with pytest.raises(PrivacyConflict, match="gerade bearbeitet"):
                    anonymize_tenant_profile(active_pg.store, active_pg.tenant.id,
                        plan_hash=plan["plan_hash"], confirm_tenant_id=active_pg.tenant.id)
                assert not active_pg.store.get_tenant(active_pg.tenant.id).archived
            finally:
                release.set()
            assert future.result(timeout=10)["state"] == "draft"
    finally:
        release.set()
        event.remove(active_pg.engine, "after_cursor_execute", hold_contract)
    graph = export_tenant_metadata(active_pg.store, active_pg.tenant.id)
    assert graph["scope"]["private_lifecycle_drafts"]["count"] == 1
