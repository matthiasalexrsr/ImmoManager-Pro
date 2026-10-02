"""Pure tests, no SQL/network/durable writes."""
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime

import pytest

from backend.services.rent_batch_planner import (
    LAST_MONTH,
    Contract,
    Cursor,
    Plan,
    PlanError,
    contract_snapshot_hash,
    load_cursor,
    month_index,
    month_text,
    plan_tick,
)


def setup(rows, start="2024-01", end="2024-12", cutoff=None, **filters):
    rows = tuple(rows)
    p = Plan(start, end, cutoff or end, contract_snapshot_hash(iter(rows)), **filters)
    def source(digest, key, inclusive):
        assert digest == p.snapshot_hash
        return (r for r in rows if key is None or r.id > key or (inclusive and r.id == key))
    return p, source


def tick(p, source, cursor=None, done=(), size=3):
    return plan_tick(p, cursor or Cursor(p.fingerprint), source,
                     lambda cid, m: (cid, m) in done, batch_size=size)


def test_601_contracts_26_years_serialized_resume():
    def row(i):
        return Contract(f"{i:06d}", date(2000, 1, 1))
    digest = contract_snapshot_hash(row(i) for i in range(601))
    p = Plan("2000-01", "2025-12", "2025-12", digest)
    def source(h, key, inclusive):
        assert h == digest
        start = int(key) + (not inclusive) if key is not None else 0
        return (row(i) for i in range(start, 601))
    cursor, count, last = Cursor(p.fingerprint), 0, None
    while not cursor.done:
        size = 31 if count % 2 else 127
        b = tick(p, source, cursor, size=size)
        assert b.contracts_read <= size and b.examined <= size
        assert b.expected_cursor == cursor
        for t in b.targets:
            assert last is None or last < t.key
            last, count = t.key, count + 1
        cursor = load_cursor(p, b.next_cursor.dump())
    assert count == 601 * 26 * 12
    assert last == ("000600", "2025-12")


def test_failure_and_unacknowledged_targets_do_not_lose_work():
    p, source = setup([Contract("a", date(2024, 1, 1))], end="2024-04")
    saved = Cursor(p.fingerprint)
    raw = saved.dump()
    def failing(cid, month):
        if month == "2024-02":
            raise RuntimeError("precommit")
        return False
    with pytest.raises(RuntimeError):
        plan_tick(p, saved, source, failing, batch_size=3)
    assert saved.dump() == raw
    b = tick(p, source, saved)
    assert b == tick(p, source, load_cursor(p, raw))
    with pytest.raises(FrozenInstanceError):
        saved.month = "2024-03"
    done = {b.targets[0].key}
    retry = tick(p, source, saved, done)
    assert [t.month for t in retry.targets] == ["2024-02", "2024-03"]
    done.update(t.key for t in retry.targets)
    rest = tick(p, source, load_cursor(p, retry.next_cursor.dump()), done, size=1)
    assert [t.month for t in rest.targets] == ["2024-04"]


def test_existing_holes_same_cutoff_and_two_part_identity():
    p, source = setup([Contract("a", date(2024, 1, 1))], end="2024-04")
    done = {("a", "2024-01"), ("a", "2024-03"), ("b", "2024-02")}
    b = tick(p, source, done=done, size=4)
    assert [t.month for t in b.targets] == ["2024-02", "2024-04"]
    assert b.existing == 2 and b.examined == 4
    assert b == tick(p, source, done=done, size=4)
    done.update(t.key for t in b.targets)
    assert tick(p, source, done=done, size=4).targets == ()


@pytest.mark.parametrize("filtered", [False, True])
def test_bounded_empty_ticks_close_the_iterator(filtered):
    reads, probes = [], []
    p = Plan("2024-01", "2024-12", "2024-12", "a" * 64)
    def source(*_):
        try:
            for i in range(10**9):
                reads.append(i)
                yield Contract(str(i), date(2024, 1, 1),
                               status="draft" if filtered else "active")
        finally:
            reads.append("closed")
    def completed(cid, month):
        probes.append((cid, month))
        return True
    b = plan_tick(p, Cursor(p.fingerprint), source, completed, batch_size=2)
    assert len(reads) <= 3 and reads[-1] == "closed"
    assert len(probes) <= 2 and b.targets == ()
    assert not b.next_cursor.done and b.next_cursor != b.expected_cursor


def test_inclusive_dates_and_cutoff_keep_full_month_policy():
    p, source = setup([
        Contract("a", date(2024, 1, 31), date(2024, 3, 1)),
        Contract("b", date(2024, 2, 29), date(2024, 2, 29)),
        Contract("c", date(2024, 3, 1)),
    ], cutoff="2024-02")
    b = tick(p, source, size=20)
    assert [(t.key, t.partial_month) for t in b.targets] == [
        (("a", "2024-01"), True), (("a", "2024-02"), False),
        (("b", "2024-02"), True)]
    assert b.next_cursor.done


def test_entire_valid_calendar_streams_without_month_ceiling():
    p, source = setup([Contract("a", date.min)], start="0001-01", end="9999-12")
    cursor, count = Cursor(p.fingerprint), 0
    while not cursor.done:
        b = plan_tick(p, cursor, source, lambda *_: True, batch_size=8192)
        assert b.targets == ()
        count += b.examined
        cursor = load_cursor(p, b.next_cursor.dump())
    assert count == 9999 * 12


def test_final_month_empty_cutoff_and_completed_job():
    p, source = setup([Contract("a", date.max, date.max)],
                      start="9999-12", end="9999-12")
    b = tick(p, source, size=1)
    assert [t.key for t in b.targets] == [("a", "9999-12")]
    end = tick(p, source, b.next_cursor)
    assert end.next_cursor.done
    def forbidden(*_):
        raise AssertionError("unexpected read")
    assert tick(p, forbidden, end.next_cursor).next_cursor == end.next_cursor
    assert tick(replace(p, cutoff_month="9999-11"), forbidden).next_cursor.done
    assert month_text(LAST_MONTH) == "9999-12"
    assert month_text(month_index("0001-01")) == "0001-01"


@pytest.mark.parametrize("month", [
    "", "2024-1", "2024-00", "2024-13", "0000-01", "10000-01", "2024-01\n", None,
])
def test_invalid_month(month):
    with pytest.raises(PlanError):
        month_index(month)


@pytest.mark.parametrize("changes", [
    {"start_date": "2024-01-01"}, {"start_date": datetime(2024, 1, 1)},
    {"end_date": date(2023, 1, 1)}, {"end_date": datetime(2024, 1, 1)},
    {"status": "unknown"}, {"id": " "},
])
def test_invalid_contract(changes):
    with pytest.raises(PlanError):
        replace(Contract("a", date(2024, 1, 1)), **changes)


def test_filter_snapshot_and_canonicalization_binding():
    p, source = setup([Contract("a", date(2024, 1, 1), property_id="p")])
    c = tick(p, source, size=1).next_cursor
    for other in (replace(p, cutoff_month="2024-11"), replace(p, property_id="p"),
                  replace(p, snapshot_hash="b" * 64), replace(p, statuses=("draft",))):
        with pytest.raises(PlanError):
            load_cursor(other, c.dump())
    assert replace(p, statuses=("draft", "active", "active")).fingerprint == (
        replace(p, statuses=("active", "draft")).fingerprint)
    assert tick(replace(p, property_id="other"), source).targets == ()
    with pytest.raises(PlanError):
        load_cursor(p, c.dump().replace('"version":1', '"version":2'))


def test_resume_missing_changed_or_unordered_source_fails():
    row = Contract("a", date(2024, 1, 1))
    p, source = setup([row])
    c = tick(p, source, size=1).next_cursor
    for rows in ([], [replace(row, start_date=date(2024, 1, 2))], [replace(row, id="b")]):
        with pytest.raises(PlanError):
            tick(p, lambda *_: iter(rows), c)
    with pytest.raises(PlanError):
        contract_snapshot_hash([row, row])
    with pytest.raises(PlanError):
        tick(p, lambda *_: iter([replace(row, id="b"), row]), size=50)


@pytest.mark.parametrize("size", [0, -1, True, 1.5])
def test_invalid_batch_size(size):
    p, source = setup([])
    with pytest.raises(PlanError):
        tick(p, source, size=size)


def test_probe_types_and_ranges_fail_closed():
    p, source = setup([Contract("a", date(2024, 1, 1))])
    with pytest.raises(PlanError):
        plan_tick(p, Cursor(p.fingerprint), source, lambda *_: None, batch_size=1)
    with pytest.raises(PlanError):
        replace(p, end_month="2023-12")
    with pytest.raises(PlanError):
        month_text(LAST_MONTH + 1)
