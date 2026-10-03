"""Actual fenced maintenance on synthetic complete native installations."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from backend.integration_state_upgrade import service
from backend.services.integrations.config_store import ConfigStoreError
from backend.services.integrations.encrypted_config_store import build_encrypted_integration_store
from backend.tests.test_full_recovery import PASSPHRASE, ROOT
from backend.tests.test_full_recovery import plan as plan
from backend.tests.test_full_recovery import runtime_template as runtime_template


def arguments(plan, tmp_path):
    return SimpleNamespace(data_dir=plan.database.parent, database=plan.database,
        uploads=plan.uploads, integrations=plan.integration_state, capacity_file=None,
        timeout_seconds=120, offline=True, output=tmp_path / "state-conversion.immobak")


def operation(args):
    directories = list((args.data_dir / ".integration-state-upgrade").iterdir())
    assert len(directories) == 1
    args.operation_id = directories[0].name
    return json.loads((directories[0] / "operation.json").read_bytes())


def cli(args, command, extra=(), passwords=()):
    # Windows getpass uses a console instead of redirected stdin. Substitute
    # only password entry in this child; real parser, service and I/O remain.
    script = """
import sys
from backend.integration_state_upgrade import __main__ as entry
entry.getpass.getpass=lambda prompt: sys.stdin.readline().rstrip('\\n')
raise SystemExit(entry.main(sys.argv[1:]))
"""
    result = subprocess.run([sys.executable, "-c", script, command,
        "--data-dir", str(args.data_dir), *extra], cwd=ROOT,
        input="".join(value + "\n" for value in passwords), capture_output=True,
        text=True, encoding="utf-8", timeout=90)
    for secret in (*passwords, "synthetic-integration-secret", "SYNTHETIC_NEW_SECRET_KEEP"):
        assert secret not in result.stdout and secret not in result.stderr
    assert not result.stderr, result.stderr
    return result.returncode, json.loads(result.stdout)


def test_actual_complete_probe_conversion_and_exact_return_keep_later_business_data(plan, tmp_path):
    args = arguments(plan, tmp_path)
    original = plan.integration_state.read_bytes()
    result = service.upgrade(args, PASSPHRASE)
    args.operation_id = result["operation_id"]
    receipt = operation(args)
    assert result["backup_restore_verified"] is True
    assert receipt["phase"] == "complete"
    assert receipt["encrypted_sha256"] == hashlib.sha256(plan.integration_state.read_bytes()).hexdigest()
    assert b"synthetic-integration-secret" not in plan.integration_state.read_bytes()
    assert "synthetic-integration-secret" not in repr(receipt)
    assert service.status(args)["state"] == "converted"
    assert service.operations(args)["items"][0]["operation_id"] == args.operation_id
    assert build_encrypted_integration_store(str(plan.integration_state), plan.configuration).load()["config"]["email"]["smtp_password"] == "synthetic-integration-secret"
    with sqlite3.connect(plan.database) as connection:
        connection.execute("UPDATE portfolios SET name='New business data after conversion'")
    assert service.rollback(args, PASSPHRASE)["status"] == "returned"
    assert plan.integration_state.read_bytes() == original
    with sqlite3.connect(plan.database) as connection:
        assert connection.execute("SELECT name FROM portfolios").fetchone()[0] == "New business data after conversion"
    assert service.status(args)["state"] == "original"
    assert service.rollback(args, PASSPHRASE)["status"] == "original_verified"


def test_independent_state_writer_after_actual_probe_conflicts_before_replacement(plan, tmp_path):
    args = arguments(plan, tmp_path)
    changed = None

    def checkpoint(phase):
        nonlocal changed
        if phase != "backup_validated":
            return
        script = """
import sys
from backend.services.integrations.config_store import JsonFileIntegrationConfigStore
store = JsonFileIntegrationConfigStore(sys.argv[1])
def change(state):
    state['config']['email']['unknown_extension'] = {'retained': 'independent writer'}
    return state
store.update(change)
"""
        result = subprocess.run([sys.executable, "-c", script, str(plan.integration_state)],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        changed = plan.integration_state.read_bytes()

    with pytest.raises(ConfigStoreError, match="state_revision_conflict"):
        service.upgrade(args, PASSPHRASE, _checkpoint=checkpoint)
    assert changed is not None and plan.integration_state.read_bytes() == changed
    receipt = operation(args)
    assert receipt["phase"] == "backup_validated"
    assert "encrypted_sha256" not in receipt
    assert service.status(args)["state"] == "changed"


@pytest.mark.parametrize("crash_phase, expected_state", [
    ("conversion_prepared", "original"), ("converted", "converted"),
])
def test_native_process_termination_classifies_exact_publication_then_checked_return(
    plan, tmp_path, crash_phase, expected_state,
):
    args = arguments(plan, tmp_path)
    original = plan.integration_state.read_bytes()
    script = """
import os, sys
from pathlib import Path
from types import SimpleNamespace
from backend.integration_state_upgrade.service import upgrade
root, archive, phase = sys.argv[1:]
args=SimpleNamespace(data_dir=Path(root),database=None,uploads=None,integrations=None,
    capacity_file=None,timeout_seconds=90,offline=True,output=Path(archive))
def checkpoint(actual):
    if actual == phase:
        os._exit(39)
upgrade(args,'synthetic-backup-passphrase-2026',_checkpoint=checkpoint)
"""
    result = subprocess.run([sys.executable, "-c", script, str(args.data_dir), str(args.output), crash_phase],
                            cwd=ROOT, capture_output=True, text=True, timeout=100)
    assert result.returncode == 39, result.stderr
    receipt = operation(args)
    assert receipt["phase"] == "conversion_prepared"
    assert service.operations(args)["items"][0]["recorded_phase"] == "conversion_prepared"
    before = plan.integration_state.read_bytes()
    assert service.status(args)["state"] == expected_state
    assert plan.integration_state.read_bytes() == before
    assert service.rollback(args, PASSPHRASE)["status"] in {"returned", "original_verified"}
    assert plan.integration_state.read_bytes() == original


def test_new_encrypted_connection_values_refuse_return_without_restoring_archive(plan, tmp_path, monkeypatch):
    args = arguments(plan, tmp_path)
    args.operation_id = service.upgrade(args, PASSPHRASE)["operation_id"]
    store = build_encrypted_integration_store(str(plan.integration_state), plan.configuration)

    def changed(state):
        state["config"]["email"]["smtp_password"] = "SYNTHETIC_NEW_SECRET_KEEP"
        return state

    store.update(changed)
    before = plan.integration_state.read_bytes()
    monkeypatch.setattr(service, "_probe", lambda *_: pytest.fail("changed state must reject before archive work"))
    with pytest.raises(service.IntegrationUpgradeError, match="return_refused_after_changes"):
        service.rollback(args, PASSPHRASE)
    assert plan.integration_state.read_bytes() == before
    assert store.load()["config"]["email"]["smtp_password"] == "SYNTHETIC_NEW_SECRET_KEEP"


@pytest.mark.parametrize("crash_phase, expected_state", [
    ("return_prepared", "converted"), ("returned", "original"),
])
def test_native_return_termination_has_a_checked_idempotent_outcome(plan, tmp_path, crash_phase, expected_state):
    args = arguments(plan, tmp_path)
    original = plan.integration_state.read_bytes()
    args.operation_id = service.upgrade(args, PASSPHRASE)["operation_id"]
    script = """
import os, sys
from pathlib import Path
from types import SimpleNamespace
from backend.integration_state_upgrade.service import rollback
root, operation, phase=sys.argv[1:]
args=SimpleNamespace(data_dir=Path(root),database=None,uploads=None,integrations=None,
    capacity_file=None,timeout_seconds=90,offline=True,operation_id=operation)
def checkpoint(actual):
    if actual == phase:
        os._exit(39)
rollback(args,'synthetic-backup-passphrase-2026',_checkpoint=checkpoint)
"""
    result = subprocess.run([sys.executable, "-c", script, str(args.data_dir), args.operation_id, crash_phase],
                            cwd=ROOT, capture_output=True, text=True, timeout=100)
    assert result.returncode == 39, result.stderr
    assert operation(args)["phase"] == "return_prepared"
    assert service.status(args)["state"] == expected_state
    assert service.rollback(args, PASSPHRASE)["status"] in {"returned", "original_verified"}
    assert plan.integration_state.read_bytes() == original


@pytest.mark.parametrize("fault", ["password", "archive"])
def test_wrong_passphrase_or_changed_archive_cannot_return_connection_state(plan, tmp_path, fault):
    args = arguments(plan, tmp_path)
    args.operation_id = service.upgrade(args, PASSPHRASE)["operation_id"]
    before = plan.integration_state.read_bytes()
    password = PASSPHRASE
    if fault == "archive":
        raw = bytearray(args.output.read_bytes())
        raw[len(raw) // 2] ^= 1
        args.output.write_bytes(raw)
        expected = service.IntegrationUpgradeError
    else:
        password = "wrong-synthetic-password"
        expected = service.IntegrationUpgradeError
    with pytest.raises(expected):
        service.rollback(args, password)
    assert plan.integration_state.read_bytes() == before
    assert operation(args)["phase"] == "complete"


def test_changed_explicit_configuration_refuses_before_connection_write(plan, tmp_path):
    args = arguments(plan, tmp_path)
    args.operation_id = service.upgrade(args, PASSPHRASE)["operation_id"]
    before = plan.integration_state.read_bytes()
    with (args.data_dir / ".env").open("a", encoding="utf-8") as target:
        target.write("\nUNKNOWN_SYNTHETIC_SOURCE=changed\n")
    with pytest.raises(service.IntegrationUpgradeError, match="selection_changed"):
        service.rollback(args, PASSPHRASE)
    assert plan.integration_state.read_bytes() == before


def test_independent_lifetime_holder_refuses_before_selection_or_backup(plan, tmp_path, monkeypatch):
    args = arguments(plan, tmp_path)
    script = """
import sys
from pathlib import Path
from backend.legacy_sqlite_upgrade.service import installation_lease
with installation_lease(Path(sys.argv[1])):
    print('ready', flush=True)
    sys.stdin.buffer.read(1)
"""
    process = subprocess.Popen([sys.executable, "-c", script, str(args.data_dir)],
                               cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdout.readline().strip() == b"ready"
        monkeypatch.setattr(service, "_selected", lambda *_: pytest.fail("selection before lifetime ownership"))
        from backend.backup_operations.plan import BackupOperationError
        for action in (lambda: service.upgrade(args, PASSPHRASE), lambda: service.status(args),
                       lambda: service.rollback(args, PASSPHRASE)):
            with pytest.raises(BackupOperationError, match="installation_busy"):
                action()
        assert not args.output.exists()
        assert not (args.data_dir / ".integration-state-upgrade").exists()
    finally:
        output, errors = process.communicate(input=b"x", timeout=15)
        assert process.returncode == 0, errors.decode()


def test_source_compare_and_prepublication_receipt_failure_leave_exact_plaintext(plan):
    path = plan.integration_state
    original = path.read_bytes()
    store = build_encrypted_integration_store(str(path), plan.configuration)
    with pytest.raises(ConfigStoreError, match="state_revision_conflict"):
        store.migrate_legacy_plaintext(expected_revision="0" * 64)
    assert path.read_bytes() == original

    def refused(_sha):
        raise OSError("SYNTHETIC_RECEIPT_FAILURE")

    with pytest.raises(ConfigStoreError, match="state_io_failed"):
        store.migrate_legacy_plaintext(expected_revision=hashlib.sha256(original).hexdigest(), before_publish=refused)
    assert path.read_bytes() == original


def test_configuration_change_during_actual_selection_is_not_bound_to_cached_keys(plan, tmp_path, monkeypatch):
    from backend.legacy_sqlite_upgrade import service as legacy
    args = arguments(plan, tmp_path)
    select = legacy._selected
    original = plan.integration_state.read_bytes()

    def changed_selection(*values, **options):
        result = select(*values, **options)
        with (args.data_dir / ".env").open("a", encoding="utf-8") as target:
            target.write("\nUNKNOWN_SELECTION_CHANGE=true\n")
        return result

    monkeypatch.setattr(legacy, "_selected", changed_selection)
    with pytest.raises(service.IntegrationUpgradeError, match="selection_changed"):
        service.upgrade(args, PASSPHRASE)
    assert plan.integration_state.read_bytes() == original
    assert not args.output.exists()


@pytest.mark.parametrize("direction", ["convert", "return"])
def test_configuration_change_in_sidecar_publication_window_cannot_replace_state(plan, tmp_path, direction):
    args = arguments(plan, tmp_path)
    if direction == "return":
        args.operation_id = service.upgrade(args, PASSPHRASE)["operation_id"]
    before = plan.integration_state.read_bytes()

    def checkpoint(phase):
        if phase == ("conversion_prepared" if direction == "convert" else "return_prepared"):
            with (args.data_dir / ".env").open("a", encoding="utf-8") as target:
                target.write("\nUNKNOWN_PUBLICATION_CHANGE=true\n")

    with pytest.raises(service.IntegrationUpgradeError, match="selection_changed"):
        action = service.upgrade if direction == "convert" else service.rollback
        action(args, PASSPHRASE, _checkpoint=checkpoint)
    assert plan.integration_state.read_bytes() == before


@pytest.mark.parametrize("fault", ["state", "configuration"])
def test_original_noop_return_rechecks_after_actual_restore_probe(plan, tmp_path, monkeypatch, fault):
    from backend.services.integrations.config_store import JsonFileIntegrationConfigStore
    args = arguments(plan, tmp_path)
    args.operation_id = service.upgrade(args, PASSPHRASE)["operation_id"]
    service.rollback(args, PASSPHRASE)
    probe = service._probe
    changed = None

    def raced_probe(*values):
        nonlocal changed
        result = probe(*values)
        if fault == "state":
            store = JsonFileIntegrationConfigStore(str(plan.integration_state))
            store.update(lambda state: {**state, "new_after_probe": "keep"})
        else:
            with (args.data_dir / ".env").open("a", encoding="utf-8") as target:
                target.write("\nUNKNOWN_NOOP_CHANGE=true\n")
        changed = plan.integration_state.read_bytes()
        return result

    monkeypatch.setattr(service, "_probe", raced_probe)
    expected = ConfigStoreError if fault == "state" else service.IntegrationUpgradeError
    with pytest.raises(expected):
        service.rollback(args, PASSPHRASE)
    assert changed is not None and plan.integration_state.read_bytes() == changed


def test_native_crash_before_first_receipt_does_not_block_operation_discovery(plan, tmp_path):
    args = arguments(plan, tmp_path)
    original = plan.integration_state.read_bytes()
    script = """
import os,sys
from pathlib import Path
from types import SimpleNamespace
from backend.integration_state_upgrade.service import upgrade
args=SimpleNamespace(data_dir=Path(sys.argv[1]),database=None,uploads=None,integrations=None,
    capacity_file=None,timeout_seconds=60,offline=True,output=Path(sys.argv[2]))
def checkpoint(phase):
    if phase == 'operation_directory_created':
        os._exit(39)
upgrade(args,'synthetic-backup-passphrase-2026',_checkpoint=checkpoint)
"""
    result = subprocess.run([sys.executable, "-c", script, str(args.data_dir), str(args.output)],
                            cwd=ROOT, capture_output=True, text=True, timeout=70)
    assert result.returncode == 39, result.stderr
    first = service.operations(args)
    assert first["items"][0]["recorded_phase"] == "initialization_incomplete"
    assert plan.integration_state.read_bytes() == original and not args.output.exists()
    complete = service.upgrade(args, PASSPHRASE)
    args.page_size = 1
    args.after = None
    rows = []
    while True:
        page = service.operations(args)
        rows.extend(page["items"])
        if not page["has_more"]:
            break
        args.after = page["next_after"]
    assert len(rows) == 2 and {row["recorded_phase"] for row in rows} == {"initialization_incomplete", "complete"}
    assert any(row["operation_id"] == complete["operation_id"] for row in rows)


def test_sidecar_wait_uses_actual_remaining_operation_budget(plan, tmp_path):
    args = arguments(plan, tmp_path)
    script = """
import sys
from backend.services.integrations.config_store import JsonFileIntegrationConfigStore
with JsonFileIntegrationConfigStore(sys.argv[1])._locked():
    print('ready',flush=True)
    sys.stdin.buffer.read(1)
"""
    process = subprocess.Popen([sys.executable, "-c", script, str(plan.integration_state)],
                               cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    original = plan.integration_state.read_bytes()
    try:
        assert process.stdout.readline().strip() == b"ready"
        from backend.services.full_recovery import RecoveryLimits
        started = time.monotonic()
        store = service._store(plan, RecoveryLimits(), started + 0.15, args)
        assert 0 < store._timeout <= 0.15
        with pytest.raises(ConfigStoreError, match="state_busy"):
            store.migrate_legacy_plaintext(expected_revision=hashlib.sha256(original).hexdigest())
        assert time.monotonic() - started < 1
        assert plan.integration_state.read_bytes() == original
    finally:
        _, errors = process.communicate(input=b"x", timeout=15)
        assert process.returncode == 0, errors.decode()


def test_actual_cli_reports_convert_discovery_wrong_password_and_checked_return(plan, tmp_path):
    args = arguments(plan, tmp_path)
    original = plan.integration_state.read_bytes()
    code, result = cli(args, "convert", ("--output", str(args.output), "--offline"), (PASSPHRASE, PASSPHRASE))
    assert code == 0 and result["backup_restore_verified"] is True
    operation_id = result["operation_id"]
    converted = plan.integration_state.read_bytes()
    code, listing = cli(args, "list", ("--page-size", "1"))
    assert code == 0 and listing["items"][0]["operation_id"] == operation_id
    code, proof = cli(args, "status", ("--operation-id", operation_id))
    assert code == 0 and proof["state"] == "converted"
    return_args = ("--operation-id", operation_id, "--offline")
    code, failure = cli(args, "rollback", return_args, ("synthetic-wrong-password",))
    assert code == 2 and failure["error"] == "integration_upgrade_archive_not_verified"
    assert failure["message"] and failure["operations_command"]
    assert plan.integration_state.read_bytes() == converted
    code, proof = cli(args, "rollback", return_args, (PASSPHRASE,))
    assert code == 0 and proof["status"] == "returned" and proof["connection_state_only"] is True
    assert plan.integration_state.read_bytes() == original
    code, proof = cli(args, "rollback", return_args, (PASSPHRASE,))
    assert code == 0 and proof["status"] == "original_verified"


def test_conversion_recomputes_lock_budget_after_actual_backup_and_probe(plan, tmp_path, monkeypatch):
    args = arguments(plan, tmp_path)
    args.timeout_seconds = 10
    build = service._store
    stores, deadlines, holder = [], [], None
    original = plan.integration_state.read_bytes()

    def observed_store(*values):
        store = build(*values)
        stores.append(store._timeout)
        deadlines.append(values[2])
        return store

    monkeypatch.setattr(service, "_store", observed_store)
    script = """
import sys
from backend.services.integrations.config_store import JsonFileIntegrationConfigStore
with JsonFileIntegrationConfigStore(sys.argv[1])._locked():
    print('ready',flush=True)
    sys.stdin.buffer.read(1)
"""

    def checkpoint(phase):
        nonlocal holder
        if phase != "backup_validated":
            return
        holder = subprocess.Popen([sys.executable, "-c", script, str(plan.integration_state)],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert holder.stdout.readline().strip() == b"ready"
        remaining = deadlines[0] - time.monotonic()
        assert remaining > 0.4, "native backup/probe must complete before this bounded fault window"
        time.sleep(remaining - 0.35)

    try:
        with pytest.raises(ConfigStoreError, match="state_busy"):
            service.upgrade(args, PASSPHRASE, _checkpoint=checkpoint)
        assert len(stores) == 2 and stores[0] > 1 and 0 < stores[1] < 0.4
        assert time.monotonic() < deadlines[0] + 0.75
        assert plan.integration_state.read_bytes() == original
        assert operation(args)["phase"] == "backup_validated"
    finally:
        if holder is not None:
            _, errors = holder.communicate(input=b"x", timeout=15)
            assert holder.returncode == 0, errors.decode()


def test_independent_native_sqlite_writer_refuses_maintenance_before_archive(plan, tmp_path):
    args = arguments(plan, tmp_path)
    original = plan.integration_state.read_bytes()
    script = """
import sqlite3,sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).resolve().as_uri()+'?mode=rw',uri=True,timeout=.05) as db:
    db.execute('BEGIN IMMEDIATE')
    print('ready',flush=True)
    sys.stdin.buffer.read(1)
    db.rollback()
"""
    holder = subprocess.Popen([sys.executable, "-c", script, str(plan.database)],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert holder.stdout.readline().strip() == b"ready"
        with pytest.raises(service.IntegrationUpgradeError, match="database_busy"):
            service.upgrade(args, PASSPHRASE)
        assert plan.integration_state.read_bytes() == original and not args.output.exists()
        assert not (args.data_dir / ".integration-state-upgrade").exists()
    finally:
        _, errors = holder.communicate(input=b"x", timeout=15)
        assert holder.returncode == 0, errors.decode()


def test_native_sqlite_writer_is_excluded_through_actual_backup_probe_and_publication(plan, tmp_path, monkeypatch):
    args = arguments(plan, tmp_path)
    probe = service._probe
    blocked = []
    script = """
import sqlite3,sys
from pathlib import Path
try:
    with sqlite3.connect(Path(sys.argv[1]).resolve().as_uri()+'?mode=rw',uri=True,timeout=.05) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE portfolios SET name='Independent writer after maintenance'")
    print('written')
except sqlite3.OperationalError as error:
    if error.sqlite_errorcode not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
        raise
    print('writer-blocked')
"""

    def writer():
        result = subprocess.run([sys.executable, "-c", script, str(plan.database)],
            cwd=ROOT, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def observed_probe(*values):
        blocked.append(writer())
        result = probe(*values)
        blocked.append(writer())
        return result

    def checkpoint(phase):
        if phase in {"prepared", "conversion_prepared"}:
            blocked.append(writer())

    monkeypatch.setattr(service, "_probe", observed_probe)
    result = service.upgrade(args, PASSPHRASE, _checkpoint=checkpoint)
    assert result["backup_restore_verified"] is True and blocked == ["writer-blocked"] * 4
    assert writer() == "written"
    with sqlite3.connect(plan.database) as db:
        assert db.execute("SELECT name FROM portfolios").fetchone()[0] == "Independent writer after maintenance"


@pytest.mark.parametrize("name", [".env", "configuration.json"])
def test_selected_configuration_budget_is_applied_before_planner_parse(plan, tmp_path, name):
    from backend.services.full_recovery import RecoveryLimits
    args = arguments(plan, tmp_path)
    if name == "configuration.json":
        (args.data_dir / name).write_text(json.dumps(plan.configuration), encoding="utf-8")
        (args.data_dir / ".env").write_bytes(b"")
    original = plan.integration_state.read_bytes()
    with pytest.raises(service.IntegrationUpgradeError, match="configuration_budget_exceeded"):
        service.upgrade(args, PASSPHRASE, limits=RecoveryLimits(metadata_bytes=128))
    assert plan.integration_state.read_bytes() == original and not args.output.exists()
    assert not (args.data_dir / ".integration-state-upgrade").exists()


def test_larger_explicit_configuration_profile_reaches_real_planner_and_fresh_binding(plan, tmp_path):
    from backend.legacy_sqlite_upgrade.service import installation_lease
    from backend.services.full_recovery import RecoveryLimits
    args = arguments(plan, tmp_path)
    path = args.data_dir / "configuration.json"
    path.write_bytes(b" " * (16 * 1024**2 + 1) + json.dumps(plan.configuration).encode())
    limits = RecoveryLimits(metadata_bytes=20 * 1024**2)
    deadline = time.monotonic() + 20
    with installation_lease(args.data_dir) as root:
        selected, files = service._selected(args, root, deadline, limits)
        receipt = {"binding": service._configuration_binding(selected, files)}
        fresh = service._assert_binding(args, root, receipt, deadline, limits)
    assert files["configuration.json"]["size"] > 16 * 1024**2
    assert fresh.configuration == selected.configuration and selected.database == plan.database


@pytest.mark.parametrize("fault, expected", [
    ("password", "integration_upgrade_passphrases_differ"),
    ("lock", "invalid_lock_timeout"),
    ("budget", "integration_upgrade_capacity_invalid"),
])
def test_actual_cli_actionable_input_errors_keep_exact_source(plan, tmp_path, fault, expected):
    args = arguments(plan, tmp_path)
    original = plan.integration_state.read_bytes()
    extra = ("--output", str(args.output), "--offline")
    passwords = (PASSPHRASE, "synthetic-mismatching-password") if fault == "password" else (PASSPHRASE, PASSPHRASE)
    if fault != "password":
        extra += ("--state-lock-timeout" if fault == "lock" else "--timeout-seconds", "nan")
    code, result = cli(args, "convert", extra, passwords)
    assert code == 2 and result["error"] == expected and result["message"]
    assert plan.integration_state.read_bytes() == original and not args.output.exists()
    assert not (args.data_dir / ".integration-state-upgrade").exists()
