"""Lifetime-fenced conversion with actual full backup/probe and checked return.

Top-level imports are deliberately limited: configuration and recovery selection
must occur inside the installation's existing native lifetime lease.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import os
import sqlite3
import tempfile
import time
from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4


class IntegrationUpgradeError(RuntimeError):
    """Non-secret actionable maintenance failure code."""


def _remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise IntegrationUpgradeError("integration_upgrade_timed_out")
    return value


def _hash(path, deadline):
    from backend.legacy_sqlite_upgrade.service import _hash_file
    from scripts.private_server_backup import _safe_path
    return _hash_file(_safe_path(path), deadline)


def _configuration_files(root, deadline):
    return {name: _hash(root / name, deadline) if (root / name).exists() else None
            for name in (".env", "configuration.json")}


def _configuration_binding(plan, configuration_files):
    from backend.services.full_recovery import _json_bytes
    return {
        "configuration_sha256": hashlib.sha256(_json_bytes(plan.configuration)).hexdigest(),
        "configuration_files": configuration_files,
        "database": str(plan.database),
        "database_identity": [plan.database.stat().st_dev, plan.database.stat().st_ino],
        "state_file": str(plan.integration_state),
    }


def _selected(args, root, deadline):
    from backend.legacy_sqlite_upgrade.service import _selected as select
    from scripts.private_server_backup import _safe_path
    before = _configuration_files(root, deadline)
    from backend.services.recovery_archive import RecoveryError
    try:
        plan = select(args, root)
    except RecoveryError:
        raise IntegrationUpgradeError("integration_upgrade_selection_invalid") from None
    if plan.integration_state is None:
        raise IntegrationUpgradeError("integration_state_missing")
    _safe_path(plan.integration_state)
    after = _configuration_files(root, deadline)
    if before != after:
        raise IntegrationUpgradeError("integration_upgrade_selection_changed")
    return plan, after


def _limits(args, supplied):
    import math

    from backend.legacy_sqlite_upgrade.service import _limits as select
    from backend.services.capacity_settings import CapacityProfileError
    from backend.services.recovery_archive import RecoveryError
    wait = getattr(args, "state_lock_timeout", 5.0)
    if type(wait) not in (int, float) or not math.isfinite(wait) or wait <= 0:
        raise IntegrationUpgradeError("invalid_lock_timeout")
    try:
        return select(args, supplied)
    except (CapacityProfileError, RecoveryError):
        raise IntegrationUpgradeError("integration_upgrade_capacity_invalid") from None


def _write(directory, receipt, limits):
    from backend.backup_operations.state import write_json
    raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    if len(raw) > limits.manifest_bytes:
        raise IntegrationUpgradeError("integration_upgrade_receipt_budget_exceeded")
    write_json(directory / "operation.json", receipt)


def _directory(root):
    from backend.backup_operations.state import private_directory
    return private_directory(root / ".integration-state-upgrade")


def _receipt(root, operation, limits):
    from backend.backup_operations.runtime import installation_identity
    from backend.backup_operations.state import read_private
    from backend.services.full_recovery import _json
    from scripts.private_server_backup import _safe_path
    try:
        if str(UUID(operation)) != operation:
            raise ValueError
        directory = _safe_path(_directory(root) / operation, directory=True)
        value = _json(read_private(directory / "operation.json", maximum=limits.manifest_bytes))
        if (value.get("version") != 1 or value.get("operation_id") != operation
                or value.get("installation") != installation_identity(root)
                or value.get("phase") not in {"prepared", "backup_validated", "conversion_prepared",
                                              "complete", "return_prepared", "returned"}):
            raise ValueError
        if not isinstance(value.get("original_sha256"), str) or len(value["original_sha256"]) != 64:
            raise ValueError
        return directory, value
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        raise IntegrationUpgradeError("integration_upgrade_receipt_invalid") from None


def _store(plan, limits, deadline, args):
    from backend.services.integrations.encrypted_config_store import build_encrypted_integration_store
    return build_encrypted_integration_store(
        str(plan.integration_state), plan.configuration,
        max_plaintext_bytes=min(limits.metadata_bytes, limits.file_bytes),
        max_json_depth=limits.integration_json_depth,
        lock_timeout=min(getattr(args, "state_lock_timeout", 5.0), _remaining(deadline)),
    )


def _state(plan, limits):
    from backend.services.recovery_integration_state import verify_archived_integration_state
    return verify_archived_integration_state(
        plan.integration_state, plan.configuration,
        max_plaintext_bytes=min(limits.metadata_bytes, limits.file_bytes),
        max_json_depth=limits.integration_json_depth,
    )


def _matched_state(plan, receipt, limits):
    proof = _state(plan, limits)
    if proof["state_revision"] == receipt["original_sha256"] and proof["legacy_requires_migration"]:
        return "original"
    if (proof["state_revision"] == receipt.get("encrypted_sha256")
            and not proof["legacy_requires_migration"]):
        return "converted"
    return "changed"


def _assert_binding(args, root, receipt, deadline):
    fresh, files = _selected(args, root, deadline)
    if _configuration_binding(fresh, files) != receipt["binding"]:
        raise IntegrationUpgradeError("integration_upgrade_selection_changed")
    return fresh


@contextmanager
def _database_lease(plan, deadline):
    # rw never creates a missing selected database. No schema or business DML.
    try:
        with closing(sqlite3.connect(
            plan.database.resolve().as_uri() + "?mode=rw", uri=True,
            timeout=min(0.2, _remaining(deadline)),
        )) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            finally:
                connection.rollback()
    except sqlite3.OperationalError:
        raise IntegrationUpgradeError("integration_upgrade_database_busy") from None


def _probe(receipt, directory, password, limits, deadline):
    from backend.services.full_recovery import restore_full_backup
    from backend.services.integrations.integration_state_offline import _read_only_bytes
    from backend.services.recovery_archive import RecoveryError
    archive = Path(receipt["archive"])
    if _hash(archive, deadline) != receipt.get("archive_identity"):
        raise IntegrationUpgradeError("integration_upgrade_archive_changed")
    with tempfile.TemporaryDirectory(prefix="probe-", dir=directory) as workspace:
        target = Path(workspace) / "restored"
        try:
            restore_full_backup(archive, target, password,
                                limits=replace(limits, timeout_seconds=_remaining(deadline)))
        except RecoveryError:
            raise IntegrationUpgradeError("integration_upgrade_archive_not_verified") from None
        raw = _read_only_bytes(target / "integrations.json", min(limits.metadata_bytes, limits.file_bytes))
        if hashlib.sha256(raw).hexdigest() != receipt["original_sha256"]:
            raise IntegrationUpgradeError("integration_upgrade_archive_source_mismatch")
        return raw


def upgrade(args, password: str, *, limits=None, _checkpoint=lambda phase: None):
    """One explicit conversion, after a complete archive was actually restored."""
    if not args.offline:
        raise IntegrationUpgradeError("integration_upgrade_offline_required")
    from backend.legacy_sqlite_upgrade.service import installation_lease
    with installation_lease(args.data_dir) as root:
        limits = _limits(args, limits)
        deadline = time.monotonic() + limits.timeout_seconds
        plan, selected_files = _selected(args, root, deadline)
        with _database_lease(plan, deadline):
            proof = _state(plan, limits)
            if not proof["legacy_requires_migration"]:
                raise IntegrationUpgradeError("integration_state_already_encrypted")
            _store(plan, limits, deadline, args)  # Explicit keys before archive work.
            from backend.backup_operations.runtime import installation_identity
            from backend.backup_operations.state import private_directory
            from backend.services.full_recovery import create_full_backup
            operation = str(uuid4())
            directory = private_directory(_directory(root) / operation)
            _checkpoint("operation_directory_created")
            receipt = {
                "version": 1, "operation_id": operation, "installation": installation_identity(root),
                "phase": "prepared", "binding": _configuration_binding(plan, selected_files),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "original_sha256": proof["state_revision"], "archive": str(args.output.absolute()),
                "backup_restore_verified": False,
            }
            _assert_binding(args, root, receipt, deadline)
            _write(directory, receipt, limits)
            _checkpoint("prepared")
            create_full_backup(plan, Path(receipt["archive"]), password, offline=True,
                               limits=replace(limits, timeout_seconds=_remaining(deadline)))
            receipt["archive_identity"] = _hash(Path(receipt["archive"]), deadline)
            _probe(receipt, directory, password, limits, deadline)
            receipt.update(phase="backup_validated", backup_restore_verified=True)
            _write(directory, receipt, limits)
            _checkpoint("backup_validated")
            _assert_binding(args, root, receipt, deadline)

            def prepared(encrypted_sha):
                _remaining(deadline)
                _assert_binding(args, root, receipt, deadline)
                receipt.update(phase="conversion_prepared", encrypted_sha256=encrypted_sha)
                _write(directory, receipt, limits)
                _checkpoint("conversion_prepared")
                _assert_binding(args, root, receipt, deadline)

            _store(plan, limits, deadline, args).migrate_legacy_plaintext(
                expected_revision=receipt["original_sha256"], before_publish=prepared,
            )
            _checkpoint("converted")
            if _matched_state(plan, receipt, limits) != "converted":
                raise IntegrationUpgradeError("integration_upgrade_state_changed")
            receipt["phase"] = "complete"
            _write(directory, receipt, limits)
            return {"operation_id": operation, "status": "complete", "backup_restore_verified": True,
                    "state_revision": receipt["encrypted_sha256"], "requires_restart": True}


def status(args, *, limits=None):
    """Classify an interrupted operation without changing the connection file."""
    from backend.legacy_sqlite_upgrade.service import installation_lease
    with installation_lease(args.data_dir) as root:
        limits = _limits(args, limits)
        deadline = time.monotonic() + limits.timeout_seconds
        _, receipt = _receipt(root, args.operation_id, limits)
        plan = _assert_binding(args, root, receipt, deadline)
        return {"operation_id": receipt["operation_id"], "recorded_phase": receipt["phase"],
                "state": _matched_state(plan, receipt, limits),
                "backup_restore_verified": receipt.get("backup_restore_verified") is True}


def operations(args, *, limits=None):
    """Bounded receipt discovery also works when success output was lost."""
    from backend.legacy_sqlite_upgrade.service import installation_lease
    from scripts.private_server_backup import _safe_path
    size, after = getattr(args, "page_size", 20), getattr(args, "after", None)
    try:
        if type(size) is not int or size < 1 or after is not None and (
            not isinstance(after, str) or str(UUID(after)) != after
        ):
            raise ValueError
    except ValueError:
        raise IntegrationUpgradeError("integration_upgrade_page_invalid") from None
    with installation_lease(args.data_dir) as root:
        limits = _limits(args, limits)
        deadline = time.monotonic() + limits.timeout_seconds
        parent = root / ".integration-state-upgrade"
        if not parent.exists():
            return {"items": [], "has_more": False, "next_after": None}
        _safe_path(parent, directory=True)

        def identities():
            with os.scandir(parent) as entries:
                for entry in entries:
                    _remaining(deadline)
                    try:
                        identity = str(UUID(entry.name))
                    except ValueError:
                        raise IntegrationUpgradeError("integration_upgrade_receipt_invalid") from None
                    if identity != entry.name or not entry.is_dir(follow_symlinks=False):
                        raise IntegrationUpgradeError("integration_upgrade_receipt_invalid")
                    if after is None or identity > after:
                        yield identity

        selected = heapq.nsmallest(size + 1, identities())
        items = []
        for identity in selected[:size]:
            if not (parent / identity / "operation.json").exists():
                _safe_path(parent / identity, directory=True)
                items.append({"operation_id": identity, "recorded_phase": "initialization_incomplete",
                              "created_at": None, "backup_restore_verified": False})
                continue
            _, receipt = _receipt(root, identity, limits)
            items.append({"operation_id": identity, "recorded_phase": receipt["phase"],
                          "created_at": receipt.get("created_at"),
                          "backup_restore_verified": receipt.get("backup_restore_verified") is True})
        more = len(selected) > size
        return {"items": items, "has_more": more, "next_after": items[-1]["operation_id"] if more else None}


def rollback(args, password: str, *, limits=None, _checkpoint=lambda phase: None):
    """Return exact archived connection bytes; never rewind the business database."""
    if not args.offline:
        raise IntegrationUpgradeError("integration_upgrade_offline_required")
    from backend.legacy_sqlite_upgrade.service import installation_lease
    with installation_lease(args.data_dir) as root:
        limits = _limits(args, limits)
        deadline = time.monotonic() + limits.timeout_seconds
        directory, receipt = _receipt(root, args.operation_id, limits)
        plan = _assert_binding(args, root, receipt, deadline)
        if receipt.get("backup_restore_verified") is not True:
            raise IntegrationUpgradeError("integration_upgrade_backup_not_verified")
        with _database_lease(plan, deadline):
            actual = _matched_state(plan, receipt, limits)
            if actual not in {"original", "converted"}:
                raise IntegrationUpgradeError("integration_upgrade_return_refused_after_changes")
            original = _probe(receipt, directory, password, limits, deadline)
            if actual == "original":
                def verified(_sha):
                    _remaining(deadline)
                    _assert_binding(args, root, receipt, deadline)
                    receipt["phase"] = "returned"
                    _write(directory, receipt, limits)
                _store(plan, limits, deadline, args).verify_legacy_revision(
                    expected_revision=receipt["original_sha256"], before_verified=verified,
                )
                return {"operation_id": receipt["operation_id"], "status": "original_verified"}
            _assert_binding(args, root, receipt, deadline)

            def prepared(original_sha):
                _remaining(deadline)
                if original_sha != receipt["original_sha256"]:
                    raise IntegrationUpgradeError("integration_upgrade_archive_source_mismatch")
                _assert_binding(args, root, receipt, deadline)
                receipt["phase"] = "return_prepared"
                _write(directory, receipt, limits)
                _checkpoint("return_prepared")
                _assert_binding(args, root, receipt, deadline)

            _store(plan, limits, deadline, args).restore_legacy_plaintext(
                original, expected_revision=receipt["encrypted_sha256"], before_publish=prepared,
            )
            _checkpoint("returned")
            if _matched_state(plan, receipt, limits) != "original":
                raise IntegrationUpgradeError("integration_upgrade_state_changed")
            receipt["phase"] = "returned"
            _write(directory, receipt, limits)
            return {"operation_id": receipt["operation_id"], "status": "returned",
                    "connection_state_only": True, "requires_restart": True}
