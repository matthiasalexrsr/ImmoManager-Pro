"""Both real lists preserve date/ID ties and bound extra page allocation."""

import gc
import tracemalloc
from copy import deepcopy
from datetime import date, datetime
from itertools import count
from uuid import UUID

import pytest

from backend.services import contract_lifecycle as service
from backend.tests.test_contract_lifecycle import active as active
from backend.tests.test_contract_lifecycle import confirmation, create, prepare


def clock(monkeypatch):
    current = [datetime(2026, 10, 2, 12)]
    numbers = count(1)
    monkeypatch.setattr(service, "uuid4", lambda: UUID(int=next(numbers)))
    monkeypatch.setattr(service, "now", lambda: current[0])
    return current


def pages(active, *, history=False):
    before, result = None, []
    for _ in range(6):
        page = service.list_drafts(active.store, active.contract.id, "actor", history=history, limit=1, before=before)
        result.extend(page["items"])
        before = page["next_before"]
        if before is None:
            return result
    pytest.fail("A bounded fixture's cursor did not terminate")


def test_own_drafts_page_dates_then_descending_ids_without_other_actor_or_tie_duplicates(active, monkeypatch):
    current = clock(monkeypatch)
    old, _ = create(active, key="old")
    current[0] = datetime(2026, 10, 2, 12, 1)
    lower, _ = create(active, key="tie-lower")
    create(active, key="other-private", actor="other")
    higher, _ = create(active, key="tie-higher")
    current[0] = datetime(2026, 10, 2, 12, 2)
    newest, _ = create(active, key="newest")
    assert higher["created_at"] == lower["created_at"] and higher["id"] > lower["id"]
    found = pages(active)
    assert [row["id"] for row in found] == [newest["id"], higher["id"], lower["id"], old["id"]]


def test_history_page_dates_and_id_ties_preserve_original_and_current_state(active, monkeypatch):
    current = clock(monkeypatch)
    first = prepare(active, key="first", reason="First accepted end")
    service.confirm_draft(active.store, active.contract.id, first["id"], confirmation(first, "confirm-first"), "actor")
    current[0] = datetime(2026, 10, 2, 12, 1)
    second = prepare(active, key="second", reason="Second accepted end", termination_end_date="2026-11-20")
    service.confirm_draft(active.store, active.contract.id, second["id"], confirmation(second, "confirm-second"), "actor")
    third = prepare(active, key="third", reason="Third accepted end", termination_end_date="2026-11-10")
    accepted = service.confirm_draft(active.store, active.contract.id, third["id"], confirmation(third, "confirm-third"), "actor")
    current[0] = datetime(2026, 10, 2, 12, 2)
    monkeypatch.setattr(service, "today", lambda: date(2026, 11, 11))
    service.finalize_draft(active.store, active.contract.id, accepted["id"], confirmation(accepted, "finalize",
        expected_contract_etag=service.contract_etag(active.store.get_contract(active.contract.id))), "other")
    found = pages(active, history=True)
    assert [(row["operation"], row["result"]["data"]["reason"]) for row in found] == [
        ("finalize", "Third accepted end"), ("confirm", "Third accepted end"),
        ("confirm", "Second accepted end"), ("confirm", "First accepted end")]
    assert found[1]["created_at"] == found[2]["created_at"] and found[1]["id"] > found[2]["id"]
    assert [row["current_state"] for row in found] == ["completed", "completed", "superseded", "superseded"]
    assert found[1]["result"] == accepted and found[1]["result"]["state"] == "pending_effective"


def test_memory_small_page_extra_allocation_does_not_scale_with_matching_history(active):
    if active.engine:
        pytest.skip("SQL already limits rows in its query; this measures Memory page materialization")
    row, _ = create(active)
    rows = active.store.__dict__["contract_lifecycle_drafts"]
    prototype = rows[row["id"]]
    def extend(first, last):
        # Owned synthetic representations; no business mutations or user data.
        for number in range(first, last):
            item = deepcopy(prototype)
            item.id = str(UUID(int=number))
            item.create_key = "bulk-" + str(number)
            rows[item.id] = item
    def peak():
        gc.collect()
        tracemalloc.start()
        try:
            page = service.list_drafts(active.store, active.contract.id, "actor", limit=3)
            assert len(page["items"]) == 3 and page["next_before"]
            return tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
    extend(1, 101)
    small = peak()
    extend(101, 20_001)
    large = peak()
    # Covers the actual authorization/integrity/DTO path, not only a heap call.
    # Generous fixed allowance absorbs normal tracing/cache variation; a full
    # matching-row sort allocates multiple MB and fails this invariant.
    assert large <= small * 4 + 64 * 1024
