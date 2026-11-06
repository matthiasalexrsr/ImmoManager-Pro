"""The supported restore path closes the source and starts a separate restored profile."""
import json

from tools.xstress import core
from tools.xstress.saveload import backup_restore


def test_full_archive_restore_into_new_profile_preserves_original_and_source(tmp_path, record_testsuite_property):
    server, findings = core.Server(tmp_path), core.Findings()
    users = {}
    try:
        server.start()
        users = core.setup_users(server, findings)
        tenant = users['owner'].require_entity('POST', '/tenants', {'full_name': 'Vor Archiv gesichert'})
        backup_restore(server, users, findings)
        assert not [row for row in findings.items if row['severity'] != 'HINWEIS'], findings.items
        receipts = findings.measurements.get('offline_restore', [])
        assert len(receipts) == 1
        receipt = receipts[0]
        assert receipt['cli_exit'] == receipt['upgrade_exit'] == 0
        assert receipt['readiness'] == 'data_verified' and receipt['new_profile_http_login'] is True
        assert receipt['privacy_review_pending'] is True and receipt['source_stopped_before_restore'] is True
        assert receipt['target_was_new'] is True
        assert receipt['old_source_token_rejected'] is True
        assert type(receipt['restored_sessions_closed']) is int and receipt['restored_sessions_closed'] >= 1
        original = users['owner'].ok('GET', '/tenants/' + tenant['id'])
        assert original['full_name'] == 'Vor Archiv gesichert'
    finally:
        record_testsuite_property('offline_restore', json.dumps(findings.measurements.get('offline_restore', [])))
        server.stop()
        for client in users.values():
            client.http.close()
