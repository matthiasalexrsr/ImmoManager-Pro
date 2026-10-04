"""Actual SQLite default/bound timestamp representations share one keyset."""

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import Session

from backend.db.orm_models import Base, NotificationORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.portfolio_scope import scope_context


@pytest.fixture
def summary():
    historical = os.environ.get("DASHBOARD_NOTIFICATION_BASELINE")
    if not historical:
        from backend.services.dashboard_summary import DashboardQuery, dashboard_summary

        yield lambda store, **query: dashboard_summary(store, DashboardQuery(**query))
        return
    assert historical == "e9321b3", "Only the unchanged recorded baseline is supported"
    root = Path(__file__).resolve().parents[2]
    source = subprocess.run(
        ["git", "show", historical + ":backend/services/dashboard_summary.py"],
        cwd=root, check=True, capture_output=True, text=True,
    ).stdout
    name = "backend.services._dashboard_notification_e9321b3"
    module = ModuleType(name)
    module.__package__ = "backend.services"
    sys.modules[name] = module
    try:
        exec(compile(source, str(root / "backend/services/dashboard_summary.py") + "@e9321b3", "exec"),
             module.__dict__)
        yield lambda store, **query: module.dashboard_summary(store, module.DashboardQuery(**query))
    finally:
        del sys.modules[name]


@pytest.fixture
def sqlite_store(request, tmp_path):
    # Register the actual FK target before repeated standalone create_all calls.
    from backend.db import document_version_models  # noqa: F401

    engine = create_engine("sqlite:///" + (tmp_path / "notification-timestamps.sqlite").as_posix())
    if getattr(request, "param", False):
        # An owned synthetic legacy table; never mutate shared ORM metadata.
        Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables
                                               if table.name != "notifications"])
        legacy = NotificationORM.__table__.to_metadata(MetaData())
        legacy.c.created_at.nullable = True
        legacy.create(engine)
    else:
        Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            yield SQLAlchemyStore(db)
    finally:
        engine.dispose()


def _notice(identifier, **values):
    return dict(id=identifier, notification_type="task_due", title=identifier,
                content="Synthetic cursor evidence", status="unread", **values)


def _default_rows(store, identifiers):
    # One actual SQL statement: all func.now()/CURRENT_TIMESTAMP values share
    # the same SQLite step, without sleeps or a mocked application clock.
    store.db.execute(NotificationORM.__table__.insert().values([_notice(item) for item in identifiers]))
    store.db.commit()


def _raw_times(store):
    with store.db.get_bind().connect() as connection:
        return dict(connection.exec_driver_sql(
            "SELECT id, created_at FROM notifications ORDER BY id COLLATE BINARY"
        ).all())


def _walk(store, summary, expected, limit):
    before = _raw_times(store)
    seen, cursor = [], None
    with scope_context(None):  # Internal read contract; no fabricated HTTP actor.
        for _ in range(len(expected) + 1):
            result = summary(store, preview_limit=limit, notifications_after=cursor)
            page = result["work_hints"]["notifications"]
            assert result["notification_count"] == result["unread_notifications"] == len(expected)
            assert page["total"] == len(expected)
            assert len(page["items"]) <= limit
            seen.extend(item["id"] for item in page["items"])
            if not page["has_more"]:
                assert page["next_after"] is None
                break
            assert page["items"] and page["next_after"]
            assert page["next_after"] != cursor
            cursor = page["next_after"]
        else:
            pytest.fail("Native notification keyset never terminated")
    assert _raw_times(store) == before
    assert seen == expected
    assert len(set(seen)) == len(expected)


def test_sqlite_native_current_timestamp_rows_are_all_reached(sqlite_store, summary):
    identifiers = [f"notice-{index:02d}" for index in (12, 1, 10, 0, 8, 2, 11, 3, 9, 4, 7, 5, 6)]
    _default_rows(sqlite_store, identifiers)
    raw = _raw_times(sqlite_store)
    assert len(set(raw.values())) == 1
    assert all(isinstance(value, str) and len(value) == 19 for value in raw.values())
    _walk(sqlite_store, summary, sorted(identifiers), 5)


def test_sqlite_mixed_zero_fractions_and_one_microsecond_keep_id_ties(sqlite_store, summary):
    identifiers = ["notice-é", "notice-z", "notice-m", "notice-A", "notice-d"]
    _default_rows(sqlite_store, identifiers)
    table = NotificationORM.__table__
    stamp = sqlite_store.db.execute(table.select().limit(1)).mappings().one()["created_at"]
    assert stamp.microsecond == 0
    bound = ["notice-Z", "notice-b", "notice-c", "notice-y", "notice-ä"]
    sqlite_store.db.execute(table.insert(), [_notice(item, created_at=stamp) for item in bound])
    sqlite_store.db.execute(table.insert(), [_notice("notice-0-micro", created_at=stamp + timedelta(microseconds=1))])
    sqlite_store.db.commit()
    raw = _raw_times(sqlite_store)
    assert all(len(raw[item]) == 19 for item in identifiers)
    assert all(raw[item].endswith(".000000") for item in bound)
    assert raw["notice-0-micro"].endswith(".000001")
    expected = sorted([*identifiers, *bound], key=lambda item: item.encode("utf-8")) + ["notice-0-micro"]
    _walk(sqlite_store, summary, expected, 2)


@pytest.mark.parametrize("sqlite_store", [True], indirect=True, ids=["legacy-null-schema"])
def test_sqlite_legacy_null_notification_dates_remain_last_and_reachable(sqlite_store, summary):
    _default_rows(sqlite_store, ["notice-dated-b", "notice-dated-a", "notice-dated-c"])
    null_ids = ["notice-null-é", "notice-null-z", "notice-null-A", "notice-null-ä", "notice-null-b"]
    sqlite_store.db.execute(NotificationORM.__table__.insert(),
                            [_notice(item, created_at=None) for item in null_ids])
    sqlite_store.db.commit()
    assert all(_raw_times(sqlite_store)[item] is None for item in null_ids)
    expected = ["notice-dated-a", "notice-dated-b", "notice-dated-c"] + sorted(
        null_ids, key=lambda item: item.encode("utf-8")
    )
    _walk(sqlite_store, summary, expected, 2)
