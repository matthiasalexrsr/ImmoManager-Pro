"""Actual archive operations must leave health and scoped UI reads responsive."""
import json

from tools.xstress import core
from tools.xstress.saveload import bulk_operation


def test_real_bulk_operations_keep_health_and_task_reads_usable(tmp_path, record_testsuite_property):
    server, findings = core.Server(tmp_path), core.Findings()
    users = {}
    try:
        server.start()
        users = core.setup_users(server, findings)
        for path in ['/admin/operations/backup', '/admin/operations/restore-probe']:
            result = bulk_operation(users['owner'], findings, path, 'Archiv-Responsivitätsprobe')
            assert result and (result.get('ok') if path.endswith('restore-probe') else True)
        measurements = findings.measurements['bulk_responsiveness']
        assert len(measurements) == 2
        for measurement in measurements:
            assert all(measurement['overlap_by_path'].values()), measurement
            assert measurement['overlapping_reader_calls'] >= 2
            assert all(row['status'] == 200 and row['seconds'] <= 2
                       for row in measurement['reader_calls']), measurement
        assert not [row for row in findings.items if row['severity'] != 'HINWEIS'], findings.items
    finally:
        record_testsuite_property('bulk_responsiveness',
                                  json.dumps(findings.measurements.get('bulk_responsiveness', [])))
        server.stop()
        for client in users.values():
            client.http.close()
