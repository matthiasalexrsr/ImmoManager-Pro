"""Actual independent SQLite/PostgreSQL writers and calculation publication."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier, Event

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import billing
from backend.services import measurement_history as history
from backend.services.measurement_history_types import MeasurementCommand
from backend.tests.test_measurement_history_http import (
    context as context_fixture,
)
from backend.tests.test_measurement_history_http import (
    draft_http as draft_http_fixture,
)
from backend.tests.test_measurement_history_http import (
    fixture_history,
    source_rows,
)

context = context_fixture
draft_http = draft_http_fixture


def write(context, body):
    active = context["active"]
    if active.engine is None:
        return history.confirm(active.store, context["homes"][0]["id"], body, active.owner.id)
    with Session(active.engine) as session:
        return history.confirm(SQLAlchemyStore(session), context["homes"][0]["id"], body, active.owner.id)


def corrected(context, changes, receipts, *, value, key):
    fix = deepcopy(changes[0][2])
    fix.update(predecessor_id=receipts[0]["fact_ids"][2], reason="Confirmed concurrent original")
    fix["data"]["value"] = str(value)
    return MeasurementCommand(expected_revision=1, idempotency_key=key, changes=[fix])


def test_independent_writers_one_revision_wins_and_loser_has_no_partial_facts(context):
    _key, changes, receipts = fixture_history(context)
    barrier = Barrier(2)
    def compete(number):
        body = corrected(context, changes, receipts, value=120 + number, key=f"compete-{number}")
        barrier.wait(timeout=15)
        try:
            return write(context, body)
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, (1, 2)))
    assert len([item for item in results if isinstance(item, dict)]) == 1
    assert results.count(409) == 1
    assert source_rows(context, context["homes"][0])["revision"] == 2


def test_independent_source_write_cannot_publish_between_calculation_and_billing_commit(context, monkeypatch):
    _key, changes, receipts = fixture_history(context)
    calculated, release, attempted = Event(), Event(), Event()
    original = billing._historical_basis
    def hold(*args, **kwargs):
        result = original(*args, **kwargs)
        if not calculated.is_set():
            calculated.set()
            assert release.wait(15), "Source writer did not reach publication gate"
        return result
    monkeypatch.setattr(billing, "_historical_basis", hold)
    def source_writer():
        attempted.set()
        return write(context, corrected(context, changes, receipts, value=130, key="while-calculating"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        generation = pool.submit(context["generate"])
        assert calculated.wait(15)
        writer = pool.submit(source_writer)
        try:
            assert attempted.wait(5)
            assert not writer.done()
        finally:
            release.set()
        result = generation.result(timeout=20)
        assert result.status_code == 201, result.text
        assert {row["total_cost"] for row in result.json()} == {50}
        assert writer.result(timeout=20)["revision"] == 2
    active = context["active"]
    response = active.client.post(f"/api/v1/billing/periods/{context['period']['id']}/finalize", headers=context["headers"])
    assert response.status_code == 409, response.text


def test_native_sqlite_busy_writer_returns_a_retryable_conflict_without_partial_revision(context):
    active = context["active"]
    if active.engine is None or active.engine.dialect.name != "sqlite":
        pytest.skip("SQLite native file-writer contention gate")
    _key, changes, receipts = fixture_history(context)
    body = corrected(context, changes, receipts, value=130, key="busy-retry")
    with active.engine.connect() as other:
        other.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            with pytest.raises(HTTPException) as caught:
                write(context, body)
            assert caught.value.status_code == 409
            assert "erneut" in str(caught.value.detail)
        finally:
            other.rollback()
    assert source_rows(context, context["homes"][0])["revision"] == 1
    assert write(context, body)["revision"] == 2
