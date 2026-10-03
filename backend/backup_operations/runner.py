"""One externally scheduled pass; durable resume obligations precede stopping."""

import hashlib
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from scripts.private_server_backup import _publish_new, _safe_path, private_workspace, protected_new_file

from .journal import Journal
from .plan import BackupOperationError, Installation, due_period
from .runtime import (
    configuration_identity,
    control,
    resume_owned_runtime,
    selected_runtime,
    stop_owned_runtime,
    stopped_runtime_lease,
)
from .state import _sync_directory, load_plan, passphrase, plan_lock, private_directory


def digest(path):
    path = _safe_path(path)
    before = path.stat()
    value, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            value.update(block)
            size += len(block)
        opened = os.fstat(source.fileno())
    current = path.stat()
    def identity(stat):
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
    if identity(before) != identity(opened) or identity(before) != identity(current) or size != before.st_size:
        raise BackupOperationError("backup_archive_changed")
    return {"sha256": value.hexdigest(), "size_bytes": size}


def file_identity(path):
    value = _safe_path(path).stat()
    return {"device": value.st_dev, "inode": value.st_ino}


def remember_archive(document):
    archive = Path(document["archive"])
    # encrypted_zip currently flushes; force full durable file publication here.
    with _safe_path(archive).open("r+b") as output:
        os.fsync(output.fileno())
    _sync_directory(archive.parent)
    document["digest"] = digest(archive)
    document["archive_identity"] = file_identity(archive)
    document["phase"] = "archive_published"


def _sqlite_plan(installation):
    from backend.recovery import _plan
    return _plan(SimpleNamespace(data_dir=installation.data_dir, database=None, uploads=None, integrations=None))


def _limits(plan, backend):
    from backend.services.capacity_settings import load_capacity
    if backend == "sqlite":
        from backend.services.full_recovery import RecoveryLimits
        return load_capacity(plan.capacity_file, "sqlite_recovery", RecoveryLimits)
    from scripts.private_server_backup import Limits
    return load_capacity(plan.capacity_file, "private_server_backup", Limits)


def _resume(plan, journal, run):
    document = run["document"]
    obligation = document.get("resume")
    if obligation is None:
        return
    installation = Installation.model_validate(document["installation"])
    if installation.backend == "sqlite":
        resume_owned_runtime(installation, obligation, timeout=plan.runtime_timeout_seconds)
    else:
        from .server import resume_server
        resume_server(installation, obligation, _limits(plan, installation.backend))
    document.pop("resume")
    document["phase"] = "app_resumed"
    journal.save(run)  # Success only after authenticated readiness / actual container health.


def _sqlite_backup(plan, journal, run, password, limits):
    from backend.services.full_recovery import create_full_backup
    document = run["document"]
    installation = Installation.model_validate(document["installation"])
    selected = _sqlite_plan(installation)
    record = selected_runtime(installation)
    if record.get("configuration_sha256") != configuration_identity(selected.configuration):
        raise BackupOperationError("selected_installation_configuration_mismatch")
    try:
        state = control(record)["state"]
    except BackupOperationError:
        # Native process witness + exclusive lifetime lock below must prove the
        # old process really exited, even if it crashed before writing 'stopped'.
        state = "stopped"
    if state != "stopped" and state != "ready":
        raise BackupOperationError("managed_runtime_not_ready_for_backup")
    was_running = state == "ready"
    if was_running:
        document["resume"] = record
        document["phase"] = "restart_obligation"
        journal.save(run)  # Durable obligation BEFORE first stop request.
    try:
        lease = (stop_owned_runtime if was_running else stopped_runtime_lease)(
            installation, record, timeout=plan.runtime_timeout_seconds)
        with lease:
            document["phase"] = "offline"
            journal.save(run)
            current = _sqlite_plan(installation)
            if configuration_identity(current.configuration) != record["configuration_sha256"]:
                raise BackupOperationError("selected_installation_configuration_mismatch")
            # Excludes uncoordinated SQLite writers as well. The archive service
            # reads through its own connection, including committed WAL frames.
            with closing(sqlite3.connect(current.database, timeout=plan.runtime_timeout_seconds)) as reservation:
                reservation.execute("BEGIN IMMEDIATE")
                try:
                    document["backup_report"] = create_full_backup(current, Path(document["archive"]), password,
                                                                   offline=True, limits=limits)
                    remember_archive(document)
                    journal.save(run)
                finally:
                    reservation.rollback()
    finally:
        _resume(plan, journal, run)


def isolated_probe(plan, archive, password, installation, limits, *, journal=None, run=None):
    """An actual fresh restore; no application, listener or scheduler is run."""
    if installation.backend == "private_server":
        from scripts.private_server_backup import probe_restore
        def ownership(receipt):
            if receipt is None:
                run["document"].pop("probe_ownership", None)
            else:
                run["document"]["probe_ownership"] = receipt
            journal.save(run)
        if journal is None or run is None:
            raise BackupOperationError("durable_probe_journal_required")
        return probe_restore(source=archive, compose_file=installation.compose_file, password=password, limits=limits,
                             ownership=ownership)
    from backend.services.full_recovery import _database_info, restore_full_backup
    with private_workspace() as (workspace, _):
        target = workspace / "restored"
        result = restore_full_backup(archive, target, password, limits=limits)
        database = target / "database.sqlite3"
        # The restore already checks every authenticated file, source row count,
        # schema, key-dependent values, references and session invalidation.
        info = _database_info(database, timeout_seconds=limits.timeout_seconds)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupOperationError("restored_database_integrity_failed")
        return {"kind": "sqlite", "database_tables": len(info["rows"]), "portless": True,
                "signing_key_rotated": result["signing_key_rotated"], "sessions_revoked": result["sessions_revoked"],
                "existing_installation_changed": result["existing_installation_changed"]}


def _replicate(document, journal, run):
    if not document.get("secondary"):
        return
    source, destination = Path(document["archive"]), Path(document["secondary"])
    private_directory(destination.parent)
    expected = document["digest"]
    if file_identity(source) != document["archive_identity"] or digest(source) != expected:
        raise BackupOperationError("backup_archive_changed")
    partial = document.get("replica_partial")
    if os.path.lexists(destination):
        owned = document.get("secondary_identity") or partial and partial["identity"]
        if digest(destination) != expected or file_identity(destination) != owned:
            raise BackupOperationError("secondary_archive_conflict")
        if partial:
            temporary = Path(partial["path"])
            if temporary.parent != destination.parent or not temporary.name.startswith("." + destination.name + "."):
                raise BackupOperationError("secondary_staging_identity_changed")
            if os.path.lexists(temporary):
                if file_identity(temporary) != partial["identity"]:
                    raise BackupOperationError("secondary_staging_identity_changed")
                temporary.unlink()
                _sync_directory(temporary.parent)
    else:
        if partial:
            temporary = Path(partial["path"])
            if temporary.parent != destination.parent or not temporary.name.startswith("." + destination.name + "."):
                raise BackupOperationError("secondary_staging_identity_changed")
            if os.path.lexists(temporary):
                if file_identity(temporary) != partial["identity"]:
                    raise BackupOperationError("secondary_staging_identity_changed")
                temporary.unlink()
                _sync_directory(temporary.parent)
            document.pop("replica_partial")
            journal.save(run)
        temporary = destination.with_name("." + destination.name + "." + uuid4().hex + ".partial")
        with protected_new_file(temporary) as output, _safe_path(source).open("rb") as incoming:
            # Persist this exact inode before accepting bytes. A subsequent
            # attempt may remove only that receipt, never a name-guessed file.
            document["replica_partial"] = {"path": str(temporary), "identity": file_identity(temporary)}
            journal.save(run)
            while block := incoming.read(1024 * 1024):
                output.write(block)
        if digest(temporary) != expected or digest(source) != expected:
            raise BackupOperationError("secondary_archive_verification_failed")
        _publish_new(temporary, destination)  # Never replace another archive; NTFS/exFAT supported.
        _sync_directory(destination.parent)
    document["replicated"] = True
    document["secondary_identity"] = file_identity(destination)
    document.pop("replica_partial", None)
    document["phase"] = "replicated"


def _backup(plan, journal, run):
    document = run["document"]
    installation = Installation.model_validate(document["installation"])
    password = passphrase(plan, document["key_id"])
    limits = _limits(plan, installation.backend)
    archive = Path(document["archive"])
    private_directory(archive.parent)
    if "digest" not in document:
        if archive.exists():
            # The worker may have died between exclusive publication and its
            # journal commit. Authenticate and actually restore before adoption.
            document["publication_recovery_probe"] = isolated_probe(plan, archive, password, installation, limits, journal=journal, run=run)
            remember_archive(document)
            journal.save(run)
        elif installation.backend == "sqlite":
            _sqlite_backup(plan, journal, run, password, limits)
        else:
            from .server import server_backup
            server_backup(plan, journal, run, password, limits)
    if digest(archive) != document["digest"] or file_identity(archive) != document["archive_identity"]:
        raise BackupOperationError("backup_archive_changed")
    _replicate(document, journal, run)
    document["phase"] = "complete"
    run.update(status="complete", error=None, retry_at=None)
    journal.save(run)


def _probe(plan, journal, run):
    document = run["document"]
    if "backup_id" not in document:
        latest = journal.latest("backup")
        if latest is None:
            raise BackupOperationError("complete_backup_required_for_probe")
        source = latest["document"]
        document.update(backup_id=latest["id"], archive=source["archive"], key_id=source["key_id"],
                        installation=source["installation"], digest=source["digest"])
        journal.save(run)
    archive = Path(document["archive"])
    if digest(archive) != document["digest"]:
        raise BackupOperationError("backup_archive_changed")
    installation = Installation.model_validate(document["installation"])
    document["probe_report"] = isolated_probe(plan, archive, passphrase(plan, document["key_id"]), installation,
                                                _limits(plan, installation.backend), journal=journal, run=run)
    document["phase"] = "complete"
    run.update(status="complete", error=None, retry_at=None)
    journal.save(run)


def _failure(plan, journal, run, error, now):
    if isinstance(error, BackupOperationError):
        code = error.code
    elif isinstance(error, OSError):
        code = "backup_storage_unavailable"
    elif isinstance(error, sqlite3.Error):
        code = "backup_database_unavailable"
    else:
        code = "backup_or_restore_validation_failed"  # Never log credentials or raw env/config exception text.
    run.update(status="retry", error=code, retry_at=(now + timedelta(seconds=plan.retry_seconds)).isoformat())
    run["document"]["error_class"] = type(error).__name__
    journal.save(run)


def _retention(plan, journal, now):
    last_backup, last_probe = journal.latest("backup"), journal.latest("probe")
    protected = {item["id"] for item in (last_backup,) if item is not None}
    if last_probe:
        protected.add(last_probe["document"]["backup_id"])
    for pending in journal.unfinished():
        if pending["kind"] == "probe" and "backup_id" in pending["document"]:
            protected.add(pending["document"]["backup_id"])
    cutoff = (now - timedelta(days=plan.retention_days)).isoformat()
    for run in journal.retire_candidates(cutoff, protected):
        # Only catalogue-owned exact files. No wildcards/recursive deletion.
        for name in ("archive", "secondary"):
            value = run["document"].get(name)
            if value:
                path = Path(value)
                if os.path.lexists(path):
                    if digest(path) != run["document"]["digest"]:
                        raise BackupOperationError("retention_archive_changed")
                    identity_key = "archive_identity" if name == "archive" else "secondary_identity"
                    if file_identity(path) != run["document"].get(identity_key):
                        raise BackupOperationError("retention_archive_changed")
                    path.unlink()
                    _sync_directory(path.parent)
        run["status"] = "retired"
        journal.save(run)


def run_once(directory, *, now=None, force=None):
    """Poll safely from Task Scheduler/systemd; OS lock serializes all workers."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or force not in {None, "backup", "probe"}:
        raise ValueError("Use an aware clock and backup/probe force option")
    now = now.astimezone(timezone.utc)
    directory = private_directory(Path(directory))
    with plan_lock(directory):
        plan = load_plan(directory)
        with Journal(directory) as journal:
            for pending in journal.unfinished():
                # A disabled schedule must still restore a previously stopped
                # application. Its durable obligation is never silently dropped.
                try:
                    _resume(plan, journal, pending)
                    receipt = pending["document"].get("probe_ownership")
                    if receipt:
                        from scripts.private_server_probe import cleanup_receipt
                        installation = Installation.model_validate(pending["document"]["installation"])
                        cleanup_receipt(receipt, installation.compose_file, _limits(plan, installation.backend))
                        pending["document"].pop("probe_ownership")
                        journal.save(pending)
                except Exception as error:
                    _failure(plan, journal, pending, error, now)
                    return {"state": "attention", "run_id": pending["id"], "error": pending["error"]}
            for kind in ("backup", "probe"):
                if not plan.enabled and force != kind:
                    continue
                pending = next((item for item in journal.unfinished() if item["kind"] == kind), None)
                latest = journal.latest(kind)
                period = due_period(plan, kind, now, latest["period"] if latest else None)
                if pending is None:
                    if not period and force != kind:
                        continue
                    period = period or now.isoformat()
                    pending = journal.new(plan, kind, period, now)
                elif pending["retry_at"] and now.isoformat() < pending["retry_at"] and force != kind:
                    continue
                try:
                    (_backup if kind == "backup" else _probe)(plan, journal, pending)
                except Exception as error:
                    _failure(plan, journal, pending, error, now)
                    return {"state": "attention", "run_id": pending["id"], "error": pending["error"]}
            try:
                _retention(plan, journal, now)
            except Exception as error:
                journal.metadata("retention_error", {"code": "backup_retention_failed", "error_class": type(error).__name__, "time": now.isoformat()})
                return {"state": "attention", "plan_id": str(plan.id), "error": "backup_retention_failed"}
            journal.metadata("retention_error", None)
            return {"state": "ok", "plan_id": str(plan.id)}
