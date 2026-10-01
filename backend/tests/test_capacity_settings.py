"""Capacity overrides reach both offline commands before they change data."""
import json
import sys

import pytest

from backend.services.capacity_settings import CapacityProfileError, load_capacity
from backend.services.full_recovery import RecoveryLimits
from scripts import private_server_backup


def test_large_installation_profile_has_no_fixed_size_or_record_ceiling(tmp_path):
    profile = tmp_path / "capacity.json"
    profile.write_text(json.dumps({"version": 1,
        "sqlite_recovery": {"total_bytes": 4 * 1024**4, "file_bytes": 1024**4, "files": 10_000_000},
        "private_server_backup": {"package_bytes": 8 * 1024**4, "dump_bytes": 2 * 1024**4,
                                  "expanded_data_bytes": 4 * 1024**4, "entries": 10_000_000,
                                  "timeout_seconds": 86400}}), encoding="utf-8")
    local = load_capacity(profile, "sqlite_recovery", RecoveryLimits)
    server = load_capacity(profile, "private_server_backup", private_server_backup.Limits,
                           overrides={"timeout_seconds": 90000})
    assert local.total_bytes == 4 * 1024**4 and local.files == 10_000_000
    assert server.dump_bytes == 2 * 1024**4 and server.entries == 10_000_000
    assert server.timeout_seconds == 90000
    assert local.compression_ratio == RecoveryLimits().compression_ratio


@pytest.mark.parametrize("raw", [
    '{"version":1,"version":1}', '{"version":true}', '{"version":2}',
    '{"version":1,"unknown":{}}', '{"version":1,"sqlite_recovery":[]}',
    '{"version":1,"sqlite_recovery":{"files":true}}',
    '{"version":1,"sqlite_recovery":{"files":1.5}}',
    '{"version":1,"sqlite_recovery":{"total_bytes":0}}',
    '{"version":1,"sqlite_recovery":{"file_bytes":-1}}',
    '{"version":1,"sqlite_recovery":{"files":"1000000"}}',
    '{"version":1,"sqlite_recovery":{"timeout_seconds":Infinity}}',
    '{"version":1,"sqlite_recovery":{"files":10,"files":20}}',
    '{"version":1,"sqlite_recovery":{"typo":10}}',
])
def test_invalid_capacity_requires_actionable_repair(tmp_path, raw):
    profile = tmp_path / "capacity.json"
    profile.write_text(raw, encoding="utf-8")
    with pytest.raises(CapacityProfileError):
        load_capacity(profile, "sqlite_recovery", RecoveryLimits)


def test_private_cli_rejects_profile_before_password_or_docker(tmp_path, monkeypatch, capsys):
    profile = tmp_path / "capacity.json"
    profile.write_text('{"version":1,"private_server_backup":{"entries":0}}', encoding="utf-8")
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid capacity must not prompt for secrets or invoke Docker")
    monkeypatch.setattr(private_server_backup, "_read_password", unexpected)
    monkeypatch.setattr(private_server_backup, "backup", unexpected)
    assert private_server_backup.main(["backup", "--project", "synthetic-capacity", "--destination",
                                       str(tmp_path / "backup.immobak"), "--capacity-file", str(profile)]) == 1
    assert "Kapazität" in capsys.readouterr().err
    assert not (tmp_path / "backup.immobak").exists()


def test_sqlite_cli_rejects_profile_before_password_or_database(tmp_path, monkeypatch, capsys):
    from backend import recovery
    profile = tmp_path / "capacity.json"
    profile.write_text('{"version":1,"sqlite_recovery":{"files":0}}', encoding="utf-8")
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid capacity must not prompt for secrets or open the database")
    monkeypatch.setattr(recovery.getpass, "getpass", unexpected)
    monkeypatch.setattr(recovery, "create_full_backup", unexpected)
    monkeypatch.setattr(sys, "argv", ["recovery", "backup", "--offline", "--data-dir", str(tmp_path),
                                     "--output", str(tmp_path / "backup.immobak"), "--capacity-file", str(profile)])
    with pytest.raises(SystemExit) as caught:
        recovery.main()
    assert caught.value.code == 2 and "Kapazität" in capsys.readouterr().err
    assert not (tmp_path / "backup.immobak").exists()
