"""Stress harness must measure expected failures and shutdowns honestly."""
import importlib
import os
from types import SimpleNamespace

import pytest

from scripts.release_stress import Fixture, Metrics, percentiles, serve, source_eligible, wait_port_closed


def test_port_probe_waits_for_actual_closed_socket_after_owned_crash():
    readings = iter([False, False, True])
    sleeps: list[float] = []
    assert wait_port_closed(18001, probe=lambda: next(readings), clock=lambda: 0, sleep=sleeps.append)
    assert sleeps == [.02, .02]


def test_persistently_open_port_cannot_be_counted_as_cleanup_success():
    clock = iter([0, 0, 4])
    assert not wait_port_closed(18001, probe=lambda: False, clock=lambda: next(clock), sleep=lambda _: None)


def test_metrics_do_not_count_expected_refusals_as_successful_requests():
    metrics = Metrics()
    metrics.record('scope', 404, .02, True)
    metrics.record('scope', 500, .2, False, 'synthetic failure')
    result = metrics.summary()['scope']
    assert result['statuses'] == {'404': 1, '500': 1}
    assert result['unexpected'] == 1 and len(metrics.findings) == 1


def test_percentiles_use_observed_nearest_rank_values_and_keep_maximum():
    values = [n / 1000 for n in range(1, 101)]
    result = percentiles(values)
    assert result == {'count': 100, 'p50_ms': 50, 'p95_ms': 95, 'max_ms': 100}
    assert percentiles([])['p95_ms'] is None


def test_source_gate_never_accepts_changed_or_unclean_sources():
    clean = {'head': 'commit', 'base_tree': 'tree', 'clean': True, 'files': {'auth.py': 'original'}}
    assert source_eligible(clean, clean.copy(), True)
    assert not source_eligible(clean, clean.copy(), False)
    assert not source_eligible(clean, {**clean, 'head': 'later'}, True)
    assert not source_eligible(clean, {**clean, 'files': {'auth.py': 'changed'}}, True)
    assert not source_eligible(clean, {**clean, 'clean': False}, True)
    assert not source_eligible({**clean, 'clean': False}, clean, True)


@pytest.mark.parametrize('module_name', ['scripts.release_stress', 'scripts.release_stress_ai_corpus'])
def test_cli_never_reuses_or_changes_existing_evidence(tmp_path, module_name):
    evidence = tmp_path / 'report.json'
    evidence.write_bytes(b'original retained evidence')
    cli = importlib.import_module(module_name)
    with pytest.raises(SystemExit) as error:
        cli.main(['--output', str(tmp_path)])
    assert error.value.code == 2
    assert evidence.read_bytes() == b'original retained evidence'
    assert sorted(path.name for path in tmp_path.iterdir()) == ['report.json']


def test_own_load_generator_memory_counts_toward_resource_budget(tmp_path, monkeypatch):
    import psutil

    args = SimpleNamespace(max_rss_mb=256, max_disk_mb=64, max_cpu_seconds=30, max_seconds=60)
    fixture = Fixture(tmp_path, args, Metrics())
    fixture.proc = SimpleNamespace(pid=999999)
    stopped = []
    child = SimpleNamespace(pid=999999, create_time=lambda: 1, memory_info=lambda: SimpleNamespace(rss=1024**2),
                            cpu_times=lambda: SimpleNamespace(user=0, system=0))
    parent = SimpleNamespace(pid=os.getpid(), create_time=lambda: 1, children=lambda recursive: [child],
                             memory_info=lambda: SimpleNamespace(rss=300*1024**2),
                             cpu_times=lambda: SimpleNamespace(user=0, system=0))

    def own_process(pid):
        assert pid == os.getpid(), 'The load generator, not only the child server, must be budgeted'
        return parent

    def stop(hard):
        stopped.append(hard)
        fixture.stop_monitor.set()

    monkeypatch.setattr(psutil, 'Process', own_process)
    monkeypatch.setattr(fixture, 'stop', stop)
    fixture.monitor()
    assert fixture.limit_hit.is_set() and stopped == [True]
    assert fixture.samples[0]['rss_bytes'] == 301*1024**2


def test_unreadable_owned_resource_cannot_silently_disable_the_budget(tmp_path, monkeypatch):
    import psutil

    args = SimpleNamespace(max_rss_mb=256, max_disk_mb=64, max_cpu_seconds=30, max_seconds=60)
    fixture = Fixture(tmp_path, args, Metrics())
    fixture.proc = SimpleNamespace(pid=999999)
    stopped = []

    def denied(pid):
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr(psutil, 'Process', denied)
    monkeypatch.setattr(fixture, 'stop', lambda hard: stopped.append(hard))
    fixture.monitor()
    assert fixture.limit_hit.is_set() and fixture.monitor_error == 'AccessDenied'
    assert stopped == [True]


def test_internal_server_cannot_bind_the_existing_live_application_port(tmp_path):
    with pytest.raises(RuntimeError, match='other than the live application port'):
        serve(tmp_path, 8765)
