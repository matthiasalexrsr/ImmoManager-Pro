"""Focused checks that the scale harness rejects false success and keeps its fixture isolated."""

import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from backend.db.orm_models import Base
from tools import scale_finance_search as scale
from tools import scale_runtime as runtime


def test_independent_recipe_totals_reversals_and_tail():
    oracle = scale.Oracle(1000)
    for i in range(1000):
        oracle.add(scale.fixture_row(i, 1000))
    expected = oracle.totals["all"]
    assert expected.total == 100 * 101112
    assert expected.income == 100 * 108889
    assert expected.expense == 100 * 7777
    assert expected.categories[None] == 100 * 105556
    assert oracle.search[("tailmarker2026", None)]["first"] == ["b-0000000999"]
    assert oracle.search[("export-bucket", None)]["count"] == 11
    assert sum(v[0] - v[1] for v in expected.monthly.values()) == expected.total
    first, reversal = scale.fixture_row(0, 1000), scale.fixture_row(1, 1000)
    assert first.amount == -reversal.amount and reversal.reverses == first.id
    assert first.side == reversal.side == "income"


def test_scoped_filter_includes_property_from_unit():
    row = scale.fixture_row(0, 1000)
    assert row.property is None and row.unit == "unit-000"
    assert scale.matches(row, scale.FILTERS["property"])
    assert scale.matches(row, scale.FILTERS["unit"])
    assert not scale.matches(row, {"portfolio_id": "p-1"})
    assert not scale.matches(row, scale.FILTERS["year"])


def test_bulk_seed_preserves_independent_count_and_foreign_keys(tmp_path):
    target = tmp_path / "fixture.db"
    engine = create_engine(f"sqlite:///{target.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()
    oracle = scale.seed(target, 1000, lambda *_: None, SimpleNamespace(check=lambda: None), receivables=False)
    with closing(sqlite3.connect(target)) as db:
        assert db.execute("SELECT count(*) FROM bookings").fetchone()[0] == 1000
        assert db.execute("PRAGMA foreign_key_check").fetchone() is None
        assert db.execute("SELECT count(*) FROM receivables").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM contracts").fetchone()[0] == 300
    assert oracle.totals["all"].total == 10111200


def test_financial_oracle_refuses_wrong_category_even_when_total_matches():
    oracle = scale.Oracle(10)
    for i in range(10):
        oracle.add(scale.fixture_row(i, 10))
    expected = oracle.totals["all"]
    body = {"bookingsTotal": 1011.12, "uncategorizedTotal": 1055.56,
            "totalsByCategory": [{"categoryId": "cat-0-income", "total": 11.11},
                                 {"categoryId": "cat-0-expense", "total": -55.55}]}
    scale.Run.finance(None, body, expected)
    body["totalsByCategory"][0]["total"] = 11.12
    with pytest.raises(AssertionError, match="Category totals"):
        scale.Run.finance(None, body, expected)


def test_process_family_excludes_unrelated_children_and_samples_worker():
    assert runtime.descendants(10, [(10, 1), (11, 10), (12, 11), (40, 1)]) == {10, 11, 12}
    sample = runtime.resource_sample(os.getpid())
    assert sample["rss"] > 0 and sample["available_bytes"] > 0
    assert os.getpid() in {p["pid"] for p in sample["processes"]}


def test_guard_stops_owned_server_and_records_failure(tmp_path, monkeypatch):
    stopped = []
    server = SimpleNamespace(proc=SimpleNamespace(pid=123, poll=lambda: None),
                             stop=lambda **kw: stopped.append(kw))
    monkeypatch.setattr(runtime, "resource_sample", lambda _: {
        "processes": [{"pid": 123}], "rss": 3 * 1024**2, "private_bytes": 0,
        "cpu_seconds": 0, "available_bytes": 10 * 1024**2})
    guard = runtime.Monitor(server, tmp_path, memory_mib=2, minimum_free_mib=1)
    guard._run()
    assert stopped == [{"hard": True}]
    assert "exceeded" in (tmp_path / "guard-failure.txt").read_text()
    with pytest.raises(RuntimeError, match="exceeded"):
        guard.check()


def test_startup_failure_still_writes_failed_report_and_returns_nonzero(tmp_path, monkeypatch):
    def fail(_self):
        raise RuntimeError("deliberate startup failure")
    monkeypatch.setattr(scale.Run, "setup", fail)
    assert scale.main(["--rows", "1000", "--out", str(tmp_path)]) == 1
    report = json.loads(next(tmp_path.glob("*/report.json")).read_text())
    assert report["status"] == "failed"
    assert "deliberate startup failure" in report["error"]
    assert report["owned_processes_stopped"] is True
    assert next(tmp_path.glob("*/failure.txt")).exists()


def test_overall_deadline_does_not_reset_when_phase_changes(tmp_path, monkeypatch):
    stopped = []
    server = SimpleNamespace(proc=None, stop=lambda **kw: stopped.append(kw))
    guard = runtime.Monitor(server, tmp_path, seconds=1)
    timestamps = iter([0, 0, 2])
    monkeypatch.setattr(runtime.time, "monotonic", lambda: next(timestamps))
    guard.done = SimpleNamespace(is_set=lambda: False, wait=lambda _: setattr(guard, "phase", "seed"))
    guard._run()
    assert guard.phase == "seed"
    assert guard.failure == "Overall run exceeded 1 seconds"
    assert stopped == [{"hard": True}]


def test_server_overrides_inherited_background_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("BACKUP_SCHEDULE_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///must-not-open.db")
    server = runtime.ScaleServer(tmp_path)
    env = server.env()
    assert env["JOB_SCHEDULER_ENABLED"] == env["BACKUP_SCHEDULE_ENABLED"] == "false"
    assert env["DATABASE_URL"] == f"sqlite:///{server.db_file.as_posix()}"
    assert env["AI_ENABLED"] == "false"
    assert Path(env["TEMP"]).is_relative_to(server.dir)


def test_csv_amount_oracle_understands_and_requires_formula_escape():
    assert scale.exported_cents("'-100.29") == -10029
    assert scale.exported_cents("11.11") == 1111
    with pytest.raises(AssertionError, match="spreadsheet escaping"):
        scale.exported_cents("-100.29")


def test_cleanup_closes_http_clients_even_when_server_stop_fails():
    def fail():
        raise RuntimeError("stop failed")
    run = object.__new__(scale.Run)
    run.args = SimpleNamespace(request_seconds=1)
    run.server = SimpleNamespace(base="http://127.0.0.1:1/api/v1", stop=fail)
    run.guard = SimpleNamespace(close=lambda: None)
    run.clients = []
    _username, client = run.client("test")
    with pytest.raises(RuntimeError, match="stop failed"):
        run.finish()
    assert client.is_closed


def test_http_wall_clock_deadline_fails_even_if_transport_returns_success(tmp_path, monkeypatch):
    args = SimpleNamespace(rows=1000, out=tmp_path, request_seconds=0.01, stage_seconds=60, mixed_seconds=30,
                           memory_mib=2048, minimum_free_mib=1, no_receivables=True)
    run = scale.Run(args)
    stopped = []
    monkeypatch.setattr(run.server, "stop", lambda **kw: stopped.append(kw))

    def slow(*_args, **_kwargs):
        time.sleep(0.04)
        return SimpleNamespace(status_code=200, text="{}", json=lambda: {})

    with pytest.raises(RuntimeError, match="HTTP deadline exceeded"):
        run.call(("slow", SimpleNamespace(request=slow)), "GET", "/slow")
    assert stopped == [{"hard": True}]
    assert run.events[-1]["deadline_exceeded"] is True
    assert (run.out / "guard-failure.txt").exists()
