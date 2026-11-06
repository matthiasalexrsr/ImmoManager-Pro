"""Bulk archive work must not hide slow interactive requests or change timeouts."""
import json
import time
from types import SimpleNamespace

import pytest

from tools.xstress import core


@pytest.mark.parametrize('method,path,elapsed,slow,budget', [
    ('GET', '/tasks', 2.4, True, 2),
    ('POST', '/tasks', 2.4, True, 2),
    ('POST', '/admin/operations/restore-probe', 2.4, False, 30),
    ('POST', '/admin/operations/backup', 2.4, False, 30),
    ('POST', '/admin/operations/restore-probe', 30.1, True, 30),
    ('POST', '/admin/operations/backup', 30.1, True, 30),
    ('GET', '/admin/operations/restore-probe', 2.4, True, 2),
    ('POST', '/admin/operations/restore-probe-extra', 2.4, True, 2),
    ('POST', '/admin/backup', 2.4, True, 2),
])
def test_only_named_bulk_operations_receive_their_budget(monkeypatch, tmp_path, method, path, elapsed, slow, budget):
    client = object.__new__(core.Client)
    client.server, client.username, client.token = SimpleNamespace(base='http://127.0.0.1:18001/api/v1'), 'synthetic', 'synthetic'
    client.f = core.Findings()
    client.f.request_log = tmp_path / 'requests.jsonl'
    response = SimpleNamespace(status_code=200, headers={}, content=b'{}', text='{}', json=lambda: {})
    client.http = SimpleNamespace(request=lambda *args, **kwargs: response)
    readings = iter([0, elapsed])
    actual_clock = time.perf_counter
    monkeypatch.setattr(core, 'time', SimpleNamespace(perf_counter=lambda: next(readings)))
    assert client.call(method, path)[0] == 200
    assert bool([f for f in client.f.items if f['severity'] == 'LANGSAM']) is slow
    recorded = json.loads(client.f.request_log.read_text(encoding='utf-8'))
    assert recorded['seconds'] == elapsed and recorded['budget_seconds'] == budget
    assert time.perf_counter is actual_clock


def test_bulk_budget_does_not_change_the_actual_hard_http_timeout(monkeypatch):
    monkeypatch.setattr(core.Client, 'login', lambda *args: None)
    client = core.Client(SimpleNamespace(base='http://127.0.0.1:18001/api/v1'), core.Findings(), 'synthetic')
    try:
        assert client.http.timeout.read == 180 and client.http.timeout.write == 180
    finally:
        client.http.close()


def test_financial_report_keeps_actual_nearest_rank_percentiles(tmp_path):
    findings = core.Findings()
    findings.timings = [('GET', '/tasks', n/1000) for n in range(1, 101)]
    core.write_report(findings, tmp_path, {'seed': 1, 'units': 60, 'years': 3})
    metadata = json.loads((tmp_path / 'metadata.json').read_text(encoding='utf-8'))
    measured = metadata['latency_by_endpoint']['GET /tasks']
    assert measured == {'count': 100, 'p50_seconds': .05, 'p95_seconds': .095, 'max_seconds': .1}
    report = (tmp_path / 'report.md').read_text(encoding='utf-8')
    assert '| Aufruf | p50 s | p95 s | max s |' in report
