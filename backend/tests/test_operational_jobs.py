"""Actual Memory/SQLite packets, interruption, fresh money and fencing."""
# ruff: noqa: F811

from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import event, insert, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from backend.db.operational_job_models import (
    OperationalJobLaneORM,
    OperationalJobORM,
    OperationalWorkItemORM,
    ensure_operational_job_schema,
)
from backend.db.orm_models import RentChargeORM
from backend.models import ContractPatch, ReceivableCreate, RentChargeCreate
from backend.services import operational_jobs as service
from backend.services.operational_job_types import JobCommand, JobContinue, JobCreate
from backend.services.operational_job_validation import (
    JobIntegrityError,
    reset_restored_job_claims,
    validate_job_journal,
)
from backend.services.operational_schedule import ensure_operational_schema
from backend.services.payments import PaymentCreate
from backend.tests.test_contract_correspondence import approved
from backend.tests.test_contract_correspondence import letter as letter
from backend.tests.test_contract_lifecycle import active as active


@pytest.fixture
def jobs(letter):
    letter.users["actor"]["portfolio_access"] = "all"
    if letter.engine:
        with letter.engine.begin() as connection:
            ensure_operational_schema(connection)
            ensure_operational_job_schema(connection)
    return letter


def payload(key="job", **changes):
    return JobCreate(idempotency_key=key, as_of=date(2026, 11, 5), **changes)


def create(box, key="job", **changes):
    return service.create_job(box.store, payload(key, **changes), "actor")


def finish(box, job, budget=7):
    for _ in range(250):
        result = service.continue_job(box.store, job["id"], JobContinue(max_items=budget), "actor")
        if not result["has_more"]:
            return result
    pytest.fail("Job did not make bounded progress")


def charges(box, count=124):
    rows = []
    for index in range(count):
        month = f"{2010 + index // 12}-{index % 12 + 1:02}"
        rows.append(box.store.create_rent_charge(RentChargeCreate(contract_id=box.contract.id, month=month,
            cold_rent=100, service_charge=20, heating_charge=0, other_charges=0, status="open")))
    return rows


def raw_lane(box, identifier):
    return box.db.get(OperationalJobLaneORM, identifier) if box.db else box.store.__dict__[OperationalJobLaneORM.__tablename__][identifier]


def expire(box, claim):
    stamp = service._clock() - timedelta(seconds=1)
    if box.db:
        box.db.execute(update(OperationalJobLaneORM).where(OperationalJobLaneORM.id == claim.lane_id).values(lease_expires_at=stamp))
        box.db.commit()
    else:
        raw_lane(box, claim.lane_id).lease_expires_at = stamp


def test_124_with_budget_seven_completes_and_letter_is_not_starved(jobs):
    rows = charges(jobs)
    letter = approved(jobs)
    for _ in range(3):
        jobs.store.create_receivable(ReceivableCreate(contract_id=jobs.contract.id, due_date=date(2026, 1, 1), amount_due=50, status="open"))
    before = [jobs.store.get_rent_charge(row.id).model_dump(mode="json") for row in rows]
    job = create(jobs)
    first = service.continue_job(jobs.store, job["id"], JobContinue(max_items=7), "actor")
    assert len(jobs.store.list_calendar_events()) == 1
    assert len(jobs.store.list_notifications()) < 124
    assert first["has_more"]
    done = finish(jobs, job)
    assert done["state"] == "completed"
    assert len(jobs.store.list_notifications()) == 127
    assert sum(lane["created"] for lane in done["lanes"]) == 128
    assert [jobs.store.get_rent_charge(row.id).model_dump(mode="json") for row in rows] == before
    assert jobs.store.list_payments() == []
    assert jobs.store.get_document(letter["document_id"])
    assert not service.continue_job(jobs.store, job["id"], JobContinue(max_items=1), "actor")["has_more"]


def test_creation_replay_and_different_payload_conflict(jobs):
    original = create(jobs)
    assert create(jobs) == original
    with pytest.raises(HTTPException) as failure:
        create(jobs, days_ahead=3)
    assert failure.value.status_code == 409


def test_prepared_list_survives_lost_worker_and_paid_source_becomes_noop(jobs):
    rows = charges(jobs, 8)
    job = create(jobs, families=("overdue_rent_charge",))
    claim = service.claim_lane(jobs.store, job["id"], "worker-a", actor_id="actor")
    service.prepare_claim(jobs.store, claim, JobContinue(max_items=7))
    items = service.item_page(jobs.store, job["id"], actor_id="actor")["items"]
    assert len(items) == 7 and {item["state"] for item in items} == {"ready"}
    paid_id = items[0]["source_id"]
    jobs.store.record_payment("rent_charge", paid_id, PaymentCreate(idempotency_key="paid-between-packets",
        amount=120, payment_date=date(2026, 10, 2)))
    expire(jobs, claim)
    replacement = service.claim_lane(jobs.store, job["id"], "worker-b", actor_id="actor")
    assert replacement.fence > claim.fence and replacement.token != claim.token
    with pytest.raises(service.ClaimLost):
        service.run_claim(jobs.store, claim, JobContinue(max_items=7))
    service.run_claim(jobs.store, replacement, JobContinue(max_items=7))
    done = finish(jobs, job)
    assert done["state"] == "completed" and len(jobs.store.list_notifications()) == len(rows) - 1
    assert sum(lane["skipped"] for lane in done["lanes"]) == 1


def test_cancel_cas_receipt_replay_fences_a_prepared_worker(jobs):
    charges(jobs, 2)
    job = create(jobs, families=("overdue_rent_charge",))
    claim = service.claim_lane(jobs.store, job["id"], "worker", actor_id="actor")
    service.prepare_claim(jobs.store, claim, JobContinue(max_items=1))
    current = service.read_job(jobs.store, job["id"], "actor")
    command = JobCommand(idempotency_key="cancel", expected_revision=current["revision"])
    cancelled = service.cancel_job(jobs.store, job["id"], command, "actor")
    assert service.cancel_job(jobs.store, job["id"], command, "actor") == cancelled
    with pytest.raises(service.ClaimLost):
        service.run_claim(jobs.store, claim, JobContinue(max_items=1))
    assert jobs.store.list_notifications() == []
    with pytest.raises(HTTPException) as failure:
        service.cancel_job(jobs.store, job["id"], command.model_copy(update={"expected_revision": current["revision"] + 1}), "actor")
    assert failure.value.status_code == 409


def test_correspondence_tombstone_and_stale_original_date_are_retained(jobs):
    approved(jobs)
    finish(jobs, create(jobs, families=("correspondence",)))
    original = jobs.store.list_calendar_events()[0]
    jobs.store._patch_entity("contract", jobs.contract.id, ContractPatch(contract_number="Synthetic changed source"))
    changed = finish(jobs, create(jobs, key="fresh", families=("correspondence",)))
    assert sum(lane["updated"] for lane in changed["lanes"]) == 1
    current = jobs.store.get_calendar_event(original.id)
    assert current.event_date == original.event_date and service.STALE_MARKER in current.description
    jobs.store.delete_calendar_event(original.id)
    finish(jobs, create(jobs, key="deleted", families=("correspondence",)))
    assert jobs.store.list_calendar_events() == []


def test_late_actor_revocation_rolls_back_packet_and_records_attention(jobs, monkeypatch):
    charges(jobs, 2)
    job = create(jobs, families=("overdue_rent_charge",))
    original = service.Unit.create
    def revoke(unit, kind, values):
        value = original(unit, kind, values)
        jobs.users["actor"]["role"] = "readonly"
        return value
    with monkeypatch.context() as patch:
        patch.setattr(service.Unit, "create", revoke)
        with pytest.raises(HTTPException):
            service.continue_job(jobs.store, job["id"], JobContinue(max_items=7), "actor")
    assert jobs.store.list_notifications() == []
    jobs.users["actor"]["role"] = "verwalter"
    current = service.read_job(jobs.store, job["id"], "actor")
    assert current["state"] == "attention" and current["lanes"][0]["last_error"] == "actor_changed"
    service.retry_lane(jobs.store, job["id"], current["lanes"][0]["id"], JobCommand(idempotency_key="fresh-role",
        expected_revision=current["revision"]), "actor")
    assert finish(jobs, job)["state"] == "completed" and len(jobs.store.list_notifications()) == 2


def test_sql_source_pages_have_limits_and_pending_caller_write_is_not_committed(jobs):
    if not jobs.db:
        pytest.skip("SQL-only query/Session boundary proof")
    charges(jobs, 9)
    observed = []
    def observe(connection, cursor, statement, parameters, context, many):
        if "FROM rent_charges" in statement and "ORDER BY rent_charges.id" in statement:
            observed.append(statement)
    event.listen(jobs.engine, "before_cursor_execute", observe)
    try:
        job = create(jobs, families=("overdue_rent_charge",))
        finish(jobs, job, budget=2)
    finally:
        event.remove(jobs.engine, "before_cursor_execute", observe)
    assert observed and all("LIMIT" in statement for statement in observed)
    pending = OperationalJobORM(id="pending-caller", actor_id="actor", create_key="caller", request_hash="0" * 64,
        scope_hash="0" * 64, parameters={}, revision=1, state="queued", turn=0, created_at=service._clock(), updated_at=service._clock())
    jobs.db.add(pending)
    service.read_job(jobs.store, job["id"], "actor")
    assert pending in jobs.db.new
    jobs.db.rollback()
    with jobs.engine.connect() as connection:
        assert connection.scalar(select(OperationalJobORM.id).where(OperationalJobORM.id == pending.id)) is None


@pytest.mark.parametrize("error_type", [ValueError, IntegrityError])
def test_invalid_source_rolls_back_only_current_packet_then_can_be_retried(jobs, monkeypatch, error_type):
    charges(jobs, 12)
    job = create(jobs, families=("overdue_rent_charge",))
    service.continue_job(jobs.store, job["id"], JobContinue(max_items=3), "actor")
    assert len(jobs.store.list_notifications()) == 3
    original = service._overdue
    invoked = 0
    def fail_after_write(unit, job, lane, item):
        nonlocal invoked
        result = original(unit, job, lane, item)
        invoked += 1
        if invoked == 2:
            if error_type is IntegrityError:
                raise IntegrityError("Synthetic permanent data violation", {}, ValueError("Private invalid row"))
            raise ValueError("Synthetic invalid source after publication")
        return result
    with monkeypatch.context() as patch:
        patch.setattr(service, "_overdue", fail_after_write)
        service.continue_job(jobs.store, job["id"], JobContinue(max_items=3), "actor")
    assert len(jobs.store.list_notifications()) == 3
    incomplete = finish(jobs, job, budget=3)
    assert incomplete["state"] == "attention" and len(jobs.store.list_notifications()) == 11
    bad = next(item for item in service.item_page(jobs.store, job["id"], actor_id="actor")["items"] if item["state"] == "attention")
    retry = JobCommand(idempotency_key="repair-source", expected_revision=incomplete["revision"])
    resumed = service.retry_item(jobs.store, job["id"], bad["id"], retry, "actor")
    assert service.retry_item(jobs.store, job["id"], bad["id"], retry, "actor") == resumed
    assert finish(jobs, job, budget=1)["state"] == "completed"
    assert len(jobs.store.list_notifications()) == 12


def test_new_freshness_job_skips_unchanged_sources_without_growing_worklist(jobs):
    charges(jobs, 14)
    first = create(jobs, families=("overdue_rent_charge",))
    finish(jobs, first)
    second = create(jobs, key="another-sweep", families=("overdue_rent_charge",))
    done = finish(jobs, second)
    assert done["state"] == "completed" and done["lanes"][0]["skipped"] == 14
    assert service.item_page(jobs.store, second["id"], actor_id="actor")["items"] == []
    assert len(jobs.store.list_notifications()) == 14


def test_staged_restore_clears_claims_and_preserves_planned_work(jobs):
    if not jobs.db:
        pytest.skip("Offline SQL restore boundary")
    charges(jobs, 8)
    job = create(jobs, families=("overdue_rent_charge",))
    old = service.claim_lane(jobs.store, job["id"], "old-worker", actor_id="actor")
    service.prepare_claim(jobs.store, old, JobContinue(max_items=3))
    with jobs.engine.begin() as connection:
        assert validate_job_journal(connection)
        assert reset_restored_job_claims(connection) == 1
        assert validate_job_journal(connection)
    with pytest.raises(service.ClaimLost):
        service.run_claim(jobs.store, old, JobContinue(max_items=3))
    assert finish(jobs, job, budget=3)["state"] == "completed"
    assert len(jobs.store.list_notifications()) == 8
    with jobs.engine.connect() as connection:
        assert validate_job_journal(connection)


def test_positive_packet_budgets_and_more_than_10000_are_supported(jobs):
    assert JobContinue(max_items=1000000).max_items == 1000000
    assert payload(lookback_days=1000000, days_ahead=1000000)
    for bad in (0, -1, True, 1.2):
        with pytest.raises(ValueError):
            JobContinue(max_items=bad)
    assert finish(jobs, create(jobs), budget=1)["state"] == "completed"


def test_sql_reaches_a_real_late_source_past_ten_thousand_paid_rows(jobs):
    if not jobs.db:
        pytest.skip("Real large SQL stock proof")
    with jobs.engine.begin() as connection:
        connection.execute(insert(RentChargeORM), [{"id": f"paid-{index:05}", "contract_id": jobs.contract.id,
            "month": f"{1000 + index // 12}-{index % 12 + 1:02}", "cold_rent": 100, "service_charge": 0,
            "heating_charge": 0, "other_charges": 0, "amount_paid": 100, "status": "paid"} for index in range(10003)])
        connection.execute(insert(RentChargeORM), {"id": "zz-late-open-source", "contract_id": jobs.contract.id,
            "month": "2026-10", "cold_rent": 100, "service_charge": 0, "heating_charge": 0,
            "other_charges": 0, "amount_paid": 0, "status": "open"})
    done = finish(jobs, create(jobs, families=("overdue_rent_charge",)), budget=1)
    assert done["state"] == "completed" and done["lanes"][0]["created"] == 1
    assert jobs.store.list_notifications()[0].entity_id == "zz-late-open-source"


def test_late_finishing_fence_rolls_back_business_effects_but_retains_plan(jobs, monkeypatch):
    charges(jobs, 2)
    job = create(jobs, families=("overdue_rent_charge",))
    claim = service.claim_lane(jobs.store, job["id"], "late-worker", actor_id="actor")
    service.prepare_claim(jobs.store, claim, JobContinue(max_items=2))
    original = service.Unit.create
    def expire_after_publication(unit, kind, values):
        target = original(unit, kind, values)
        lane = unit.row(OperationalJobLaneORM, claim.lane_id)
        unit.touch_row(lane)
        lane.lease_expires_at = service._clock() - timedelta(seconds=1)
        return target
    with monkeypatch.context() as patch:
        patch.setattr(service.Unit, "create", expire_after_publication)
        with pytest.raises(service.ClaimLost, match="finishing fence"):
            service.run_claim(jobs.store, claim, JobContinue(max_items=2))
    assert jobs.store.list_notifications() == []
    plan = service.item_page(jobs.store, job["id"], actor_id="actor")["items"]
    assert len(plan) == 2 and all(item["state"] == "ready" for item in plan)
    current = service.read_job(jobs.store, job["id"], "actor")
    assert current["lanes"][0]["created"] == 0
    expire(jobs, claim)
    assert finish(jobs, job)["state"] == "completed"
    assert len(jobs.store.list_notifications()) == 2


def test_transient_database_failure_keeps_earlier_packets_and_retries_with_backoff(jobs, monkeypatch):
    charges(jobs, 8)
    job = create(jobs, families=("overdue_rent_charge",))
    service.continue_job(jobs.store, job["id"], JobContinue(max_items=3), "actor")
    original = service._overdue
    count = 0
    def fail_second_write(unit, job, lane, item):
        nonlocal count
        result = original(unit, job, lane, item)
        count += 1
        if count == 2:
            raise OperationalError("Synthetic database failure", {}, RuntimeError("Private driver details"))
        return result
    with monkeypatch.context() as patch:
        patch.setattr(service, "_overdue", fail_second_write)
        failed = service.continue_job(jobs.store, job["id"], JobContinue(max_items=3), "actor")
    assert failed["lanes"][0]["last_error"] == "transient_database"
    assert failed["lanes"][0]["available_at"].endswith("Z")
    assert len(jobs.store.list_notifications()) == 3
    assert service.continue_job(jobs.store, job["id"], JobContinue(max_items=3), "actor") == failed
    items = service.item_page(jobs.store, job["id"], actor_id="actor")["items"]
    retried = next(item for item in items if item["error_code"] == "transient_database")
    assert retried["state"] == "ready" and retried["attempts"] == 1
    assert "Private driver details" not in str(failed) + str(items)
    stamp = service._clock() - timedelta(seconds=1)
    if jobs.db:
        jobs.db.execute(update(OperationalJobLaneORM).where(OperationalJobLaneORM.job_id == job["id"]).values(next_attempt_at=stamp))
        jobs.db.execute(update(OperationalWorkItemORM).where(OperationalWorkItemORM.id == retried["id"]).values(next_attempt_at=stamp))
        jobs.db.commit()
    else:
        raw_lane(jobs, failed["lanes"][0]["id"]).next_attempt_at = stamp
        jobs.store.__dict__[OperationalWorkItemORM.__tablename__][retried["id"]].next_attempt_at = stamp
    assert finish(jobs, job, budget=3)["state"] == "completed"
    assert len(jobs.store.list_notifications()) == 8


def test_corrupt_staged_source_binding_is_rejected_before_claim_reset(jobs):
    if not jobs.db:
        pytest.skip("Offline SQL corruption boundary")
    charges(jobs, 2)
    job = create(jobs, families=("overdue_rent_charge",))
    claim = service.claim_lane(jobs.store, job["id"], "saved-worker", actor_id="actor")
    service.prepare_claim(jobs.store, claim, JobContinue(max_items=1))
    with jobs.engine.begin() as connection:
        connection.execute(update(OperationalWorkItemORM).where(OperationalWorkItemORM.job_id == job["id"]).values(action_key="wrong-source"))
        with pytest.raises(JobIntegrityError, match="journal_invalid"):
            reset_restored_job_claims(connection)
        saved = connection.execute(select(OperationalJobLaneORM.fence, OperationalJobLaneORM.lease_token).where(OperationalJobLaneORM.id == claim.lane_id)).one()
        assert saved.fence == claim.fence and saved.lease_token == claim.token


def test_slow_first_queries_make_progress_instead_of_repeated_empty_packets(jobs, monkeypatch):
    charges(jobs, 6)
    job = create(jobs, families=("overdue_rent_charge",))
    elapsed = 0
    def slow_clock():
        nonlocal elapsed
        elapsed += 10
        return elapsed
    monkeypatch.setattr(service, "monotonic", slow_clock)
    first = service.continue_job(jobs.store, job["id"], JobContinue(max_items=7), "actor")
    assert first["lanes"][0]["scanned"] == 1
    assert first["lanes"][0]["created"] == 1
    assert finish(jobs, job)["state"] == "completed"
    assert len(jobs.store.list_notifications()) == 6


def test_long_idempotency_references_use_bounded_index_keys_and_exact_receipts(jobs):
    external = "Synthetic long reference " * 1000
    job = create(jobs, key=external)
    assert create(jobs, key=external) == job
    command = JobCommand(idempotency_key=external, expected_revision=job["revision"])
    cancelled = service.cancel_job(jobs.store, job["id"], command, "actor")
    assert service.cancel_job(jobs.store, job["id"], command, "actor") == cancelled
    if jobs.db:
        with jobs.engine.connect() as connection:
            assert len(connection.scalar(select(OperationalJobORM.create_key))) == 64
            assert len(connection.scalar(select(OperationalWorkItemORM.action_key))) == 72
            assert validate_job_journal(connection)
    else:
        assert len(next(iter(jobs.store.__dict__[OperationalJobORM.__tablename__].values())).create_key) == 64
