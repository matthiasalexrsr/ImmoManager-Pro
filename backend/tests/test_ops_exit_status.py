"""Release scripts must not treat incomplete recovery as a successful CLI check."""
import json

import pytest

from backend import ops
from backend.services import full_backup


@pytest.mark.parametrize('report,expected', [
    ({'ok': True}, 0),
    ({'ok': False}, 1),
    ({'ok': True, 'second_target': {'ok': False}}, 1),
    ({'ok': True, 'second_target': {'ok': True}}, 0),
])
def test_backup_exit_status_includes_required_copy(monkeypatch, capsys, report, expected):
    monkeypatch.setattr(full_backup, 'create_full_backup', lambda trigger: report)
    assert ops.main(['backup']) == expected
    assert json.loads(capsys.readouterr().out) == report


@pytest.mark.parametrize('ready', [True, False])
def test_restore_probe_exit_status_requires_verified_data(monkeypatch, capsys, ready):
    report = {'ok': ready, 'readiness': 'data_verified' if ready else 'archive_only'}
    monkeypatch.setattr(full_backup, 'restore_probe', lambda archive, **kwargs: report)
    monkeypatch.setattr(ops, '_passphrase', lambda args, required: 'synthetic')
    assert ops.main(['probe']) == (0 if ready else 1)
    assert json.loads(capsys.readouterr().out) == report
