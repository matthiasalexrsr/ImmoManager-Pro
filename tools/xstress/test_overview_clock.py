"""A historical financial cutoff must not be compared to current-only dashboards."""
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tools.xstress import invariants
from tools.xstress.core import Findings
from tools.xstress.world import build_world


@pytest.mark.parametrize('historical,api_count,wrong', [(True, 56, False), (False, 56, False), (False, 55, True)])
def test_current_dashboard_has_its_own_date_and_still_rejects_wrong_counts(monkeypatch, historical, api_count, wrong):
    today = date(2026, 11, 6)
    world = build_world(seed=20261106, units=60, years=3, today=today)
    for index, unit in enumerate(world.units):
        unit.id = f'synthetic-unit-{index}'
    assert sum(t.start <= world.end and (not t.end or t.end >= world.end) for t in world.tenancies) == 58
    assert sum(t.start <= today and (not t.end or t.end >= today) for t in world.tenancies) == 56
    findings = Findings()
    sim = SimpleNamespace(w=world, f=findings, created={id(t) for t in world.tenancies},
                          ledger=SimpleNamespace(booked_total=Decimal(0)))

    class Client:
        def all(self, path, **kwargs):
            return {'/units': world.units, '/contracts': world.tenancies, '/bookings': []}[path]

        def ok(self, method, path, **kwargs):
            return {'/dashboard/stats': {'active_contracts': api_count, 'occupied_units': api_count},
                    '/reports/occupancy': {'rentedUnits': api_count}, '/review': {'count': 0, 'items': []}}.get(path, {})

        def call(self, *args, **kwargs):
            return 200, {}

    monkeypatch.setattr(invariants, 'local_today', lambda: today)
    invariants.check_overview(sim, Client(), world.end if historical else today)
    errors = [row for row in findings.items if row['severity'] == 'FALSCH']
    assert len(errors) == (3 if wrong else 0)


def test_generated_world_uses_the_business_day_after_utc_midnight(monkeypatch):
    from backend.domain import clock

    instant = datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc)
    business = clock.local_today(instant)
    assert business == date(2027, 1, 1)
    monkeypatch.setattr(clock, 'local_today', lambda: business)
    world = build_world(seed=20261106, units=6, years=3)
    assert world.end == date(2026, 12, 31)
    assert world.start == date(2024, 1, 1)
