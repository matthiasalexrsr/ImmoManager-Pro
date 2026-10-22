"""One "today" for the whole program: the installation's calendar date in Europe/Berlin."""

import ast
from datetime import date, datetime, timezone
from pathlib import Path

from backend.domain.clock import local_today
from backend.services.jobs import schedule

BACKEND = Path(__file__).resolve().parents[1]


def _calendar_reads(tree: ast.AST) -> list[int]:
    """Lines that take today's date from the server's zone or from UTC instead of local_today()."""
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        func = node.func
        # date.today(), datetime.today()
        if func.attr == "today" and isinstance(func.value, ast.Name) and func.value.id in {"date", "datetime"}:
            lines.append(node.lineno)
        # datetime.now(...).date()
        if (func.attr == "date" and isinstance(func.value, ast.Call) and isinstance(func.value.func, ast.Attribute)
                and func.value.func.attr == "now"):
            lines.append(node.lineno)
    return lines


def test_no_module_takes_today_from_the_server_zone():
    """Regression: 31 modules took date.today(); in the Docker image (UTC) the previous day lasted until
    1 or 2 a.m., so due dates, reminders and dunning were seen up to two hours late."""
    offenders = []
    for path in BACKEND.rglob("*.py"):
        if path.name == "clock.py":
            continue
        for line in _calendar_reads(ast.parse(path.read_text(encoding="utf-8-sig"))):
            offenders.append(f"{path.relative_to(BACKEND.parent)}:{line}")
    assert not offenders, "use backend.domain.clock.local_today(): " + ", ".join(sorted(offenders))


def test_today_is_the_date_in_berlin_also_around_midnight_utc():
    assert local_today(datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc)) == date(2027, 1, 1)
    assert local_today(datetime(2026, 7, 31, 22, 30)) == date(2026, 8, 1)          # naive means UTC
    assert local_today(datetime(2026, 7, 31, 21, 59)) == date(2026, 7, 31)


def test_the_scheduler_uses_the_same_today():
    assert schedule.local_today is local_today
