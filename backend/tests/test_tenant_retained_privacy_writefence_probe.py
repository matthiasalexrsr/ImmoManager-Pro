"""Opt-in native counterexample for Root's separately owned privacy write fence.

RUN_TENANT_RETAINED_FENCE_PROBE=1 intentionally exposes the unfixed source race.
The desired-behavior assertion must fail on 0becc28; no assertion is weakened.
"""
# ruff: noqa: F811

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from backend import auth
from backend.models import ContractPatch, TenantCreate
from backend.services import tenancy_workflow as workflow
from backend.services import tenant_privacy
from backend.services.tenancy_workflow_types import UpdateStep
from backend.tests.test_operational_recovery_guards import complete_domain_test_schema
from backend.tests.test_tenancy_workflow_core import box as box
from backend.tests.test_tenancy_workflow_core import preview_and_start, published_template


@pytest.mark.skipif(os.getenv("RUN_TENANT_RETAINED_FENCE_PROBE") != "1", reason="Opt-in known native PG write-fence counterexample; Root owns the fix")
def test_pg_profile_confirmation_cannot_commit_after_unreviewed_historical_workflow_writer(box, monkeypatch):
    if box.engine is None or box.engine.dialect.name != "postgresql":
        pytest.skip("Actual PostgreSQL counterexample; no simulated SQLite/Memory lock claim")
    complete_domain_test_schema(box)
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    template = published_template(box)
    _, _, change = preview_and_start(box, template)
    corrected = box.store.create_tenant(TenantCreate(full_name="Current corrected synthetic party"))
    box.store._patch_entity("contract", box.previous.id, ContractPatch(tenant_id=corrected.id))
    plan = tenant_privacy.preview_tenant_anonymization(box.store, box.previous.tenant_id)
    paused, resume = Event(), Event()
    original_plan = tenant_privacy._plan

    def pause_after_actual_hash(graph):
        result = original_plan(graph)
        if current_thread().name.startswith("profile-confirmation"):
            paused.set()
            assert resume.wait(15), "Diagnostic controller did not release the profile writer"
        return result

    def bounded_native_writer(connection):
        if current_thread().name.startswith("retained-workflow-writer"):
            connection.exec_driver_sql("SET LOCAL lock_timeout='2s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")

    monkeypatch.setattr(tenant_privacy, "_plan", pause_after_actual_hash)
    event.listen(box.engine, "begin", bounded_native_writer)
    item = change["steps"][0]

    def confirm():
        return tenant_privacy.anonymize_tenant_profile(box.store, box.previous.tenant_id,
            plan_hash=plan["plan_hash"], confirm_tenant_id=box.previous.tenant_id)

    def update():
        return workflow.update_step(box.store, change["id"], item["id"], UpdateStep(idempotency_key="unreviewed-during-profile",
            expected_revision=item["revision"], expected_change_revision=change["revision"], state="in_progress"), "tech")

    writer_committed = profile_committed = False
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="profile-confirmation") as profile_pool:
            confirmation = profile_pool.submit(confirm)
            try:
                assert paused.wait(10), "Profile writer did not reach the actual recomputed hash barrier"
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="retained-workflow-writer") as writer_pool:
                    mutation = writer_pool.submit(update)
                    try:
                        writer_committed = mutation.result(timeout=8)["state"] == "in_progress"
                    except OperationalError as error:
                        assert getattr(error.orig, "sqlstate", getattr(error.orig, "pgcode", None)) in {"55P03", "40001", "40P01"}
                        # Only native concurrency refusal counts as a blocked
                        # writer; fixture errors/timeouts must fail the probe.
                        writer_committed = False
                    except HTTPException as error:
                        assert error.status_code == 409
                        writer_committed = False
            finally:
                resume.set()
            try:
                profile_committed = confirmation.result(timeout=10)["status"] == "profile_anonymized"
            except tenant_privacy.PrivacyConflict:
                profile_committed = False
    finally:
        resume.set()
        event.remove(box.engine, "begin", bounded_native_writer)
    assert not (writer_committed and profile_committed), (
        "Unsafe native PG confirmation: a historical workflow command committed after the actual reviewed hash; "
        "the profile was nevertheless anonymized without a new preview"
    )
