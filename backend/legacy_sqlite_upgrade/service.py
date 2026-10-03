"""Audited offline adoption and checked transactional rollback.

The installation kernel lease surrounds configuration selection, archive/probe,
native SQLite DDL and recovery metadata. Application startup never calls this.
"""

import hashlib
import json
import sqlite3
import tempfile
import time
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

from .schema import LegacySchemaError, catalog, catalog_hash, profiles, prove_legacy_schema, quoted


class LegacyUpgradeError(RuntimeError):
    """Actionable non-secret operation failure code."""


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LegacyUpgradeError("legacy_operation_timed_out")
    return remaining


def _hash_file(path, deadline):
    from backend.services.full_recovery import _safe_stat
    before = _safe_stat(path)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            _remaining(deadline)
            digest.update(block)
    after = _safe_stat(path)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise LegacyUpgradeError("legacy_installation_files_changed")
    return {"identity": [before.st_dev, before.st_ino], "size": before.st_size, "sha256": digest.hexdigest()}


def _file_state(plan, data_dir, limits, deadline):
    from backend.services.full_recovery import _tree
    files, directories = _tree(plan.uploads, limits, deadline=deadline)
    result = {"upload_directories": directories,
              "uploads": {name: _hash_file(plan.uploads / name, deadline) for name in files}}
    extras = {"runtime": plan.runtime_env, "integrations": plan.integration_state,
              "configuration": data_dir / "configuration.json"}
    result["installation"] = {name: _hash_file(path, deadline) if path is not None and path.exists() else None
                              for name, path in extras.items()}
    return result


def _row_state(connection, deadline):
    from backend.invoice_schema_upgrade import _capture
    return {table: {"columns": list(original.columns), "rows": list(original.rows)}
            for table, original in _capture(connection, deadline).items()}


def _validate(connection):
    if (connection.exec_driver_sql("PRAGMA integrity_check").all() != [("ok",)]
            or connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None):
        raise LegacyUpgradeError("legacy_database_inconsistent")


def _native(connection):
    return connection.connection.driver_connection


def _pipeline(connection, profile, deadline):
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    from backend.invoice_schema_upgrade import _upgrade
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    if heads != [profiles()[profile]["validated_target_head"]]:
        raise LegacyUpgradeError("legacy_target_requires_reference_validation")
    _upgrade(connection, deadline)
    with Operations.context(MigrationContext.configure(connection)):
        for revision in reversed(list(scripts.iterate_revisions(heads[0], "z1a2b3c4d5e6"))):
            _remaining(deadline)
            revision.module.upgrade()
    return scripts, heads[0]


def _check_preservation(connection, originals, old_triggers, deadline):
    from backend.invoice_schema_upgrade import _preserved
    _preserved(connection, originals, deadline)
    current = {name: sql for name, sql in connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger'")}
    if any(current.get(name) != sql for name, sql in old_triggers.items()):
        raise LegacyUpgradeError("legacy_original_guards_changed")


def _stage(snapshot, destination, profile, deadline, *, expected_only=False):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from backend.invoice_schema_upgrade import _capture
    from scripts.private_server_backup import protected_new_file
    with protected_new_file(destination):
        pass
    with closing(sqlite3.connect(destination)) as target:
        if expected_only:
            for sql in profiles()[profile]["ddl"]:
                target.execute(sql)
            target.commit()
        else:
            with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as source:
                source.backup(target, pages=256, progress=lambda *_: _remaining(deadline))
    engine = create_engine("sqlite:///" + destination.as_posix(), poolclass=NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.rollback()
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            _native(connection).set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            originals = _capture(connection, deadline)
            triggers = {name: sql for name, sql in connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger'")}
            scripts, head = _pipeline(connection, profile, deadline)
            _check_preservation(connection, originals, triggers, deadline)
            _validate(connection)
            value = catalog(_native(connection))
            from alembic.migration import MigrationContext
            MigrationContext.configure(connection).stamp(scripts, head)
            connection.commit()
            return value, head, _row_state(connection, deadline)
    finally:
        engine.dispose()


@contextmanager
def installation_lease(data_dir: Path):
    # This runs before recovery._plan/settings imports. No generated configuration
    # or application singleton can cross the native ownership boundary.
    from backend.backup_operations.runtime import runtime_directory
    from backend.backup_operations.state import FileLease, private_directory
    from scripts.private_server_backup import _safe_path
    root = _safe_path(data_dir.absolute(), directory=True)
    directory = private_directory(runtime_directory(root))
    with FileLease(directory / "installation.lock"):
        yield root


def _receipt_directory(root):
    from backend.backup_operations.state import private_directory
    return private_directory(root / ".legacy-sqlite-upgrade")


def _receipt(root, operation, *, maximum_metadata):
    from backend.backup_operations.state import read_private
    from backend.services.full_recovery import _json
    try:
        identity = str(UUID(operation))
        if identity != operation:
            raise ValueError
        directory = _receipt_directory(root) / identity
        from scripts.private_server_backup import _safe_path
        _safe_path(directory, directory=True)
        value = _json(read_private(directory / "operation.json", maximum=maximum_metadata))
        from backend.backup_operations.runtime import installation_identity
        if value["operation_id"] != operation or value["installation"] != installation_identity(root):
            raise ValueError
        return directory, value
    except (ValueError, OSError, KeyError, TypeError):
        raise LegacyUpgradeError("legacy_operation_receipt_invalid") from None


def _write(directory, value, *, maximum_metadata):
    from backend.backup_operations.state import write_json
    if len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")) > maximum_metadata:
        raise LegacyUpgradeError("legacy_operation_metadata_budget_exceeded")
    write_json(directory / "operation.json", value)


def _selected(args, root):
    from backend.recovery import _plan
    from scripts.private_server_backup import _safe_path
    args.data_dir = root
    plan = _plan(args)
    _safe_path(plan.database)
    return plan


def _limits(args, supplied):
    from backend.services.capacity_settings import load_capacity
    from backend.services.full_recovery import RecoveryLimits
    return supplied or load_capacity(getattr(args, "capacity_file", None), "sqlite_recovery", RecoveryLimits,
        overrides={"timeout_seconds": args.timeout_seconds} if getattr(args, "timeout_seconds", None) is not None else None)


def upgrade(args, password: str, *, limits=None, _checkpoint=lambda phase: None) -> dict:
    if not args.offline:
        raise LegacyUpgradeError("legacy_offline_required")
    with installation_lease(args.data_dir) as root:
        limits = _limits(args, limits)
        deadline = time.monotonic() + limits.timeout_seconds
        plan = _selected(args, root)
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool

        from backend.backup_operations.runtime import installation_identity
        from backend.backup_operations.state import private_directory
        from backend.invoice_schema_upgrade import _capture
        from backend.services.full_recovery import create_full_backup, restore_full_backup
        from scripts.private_server_backup import protected_new_file
        engine = create_engine("sqlite:///" + plan.database.as_posix(), poolclass=NullPool, hide_parameters=True,
                               connect_args={"timeout": min(0.2, _remaining(deadline))})
        directory, receipt = None, None
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                connection.rollback()
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                _native(connection).set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                proof = prove_legacy_schema(_native(connection))
                _validate(connection)
                pages = connection.exec_driver_sql("PRAGMA page_count").scalar_one()
                page_size = connection.exec_driver_sql("PRAGMA page_size").scalar_one()
                if pages * page_size > min(limits.file_bytes, limits.total_bytes):
                    raise LegacyUpgradeError("legacy_database_budget_exceeded")
                originals = _capture(connection, deadline)
                triggers = {name: sql for name, sql in connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger'")}
                original_rows = _row_state(connection, deadline)
                operation = str(uuid4())
                directory = private_directory(_receipt_directory(root) / operation)
                snapshot = directory / "original.sqlite"
                with protected_new_file(snapshot):
                    pass
                with closing(sqlite3.connect(plan.database.as_uri() + "?mode=ro", uri=True)) as source:
                    with closing(sqlite3.connect(snapshot)) as target:
                        source.backup(target, pages=256, progress=lambda *_: _remaining(deadline))
                receipt = {"version": 1, "operation_id": operation, "installation": installation_identity(root),
                    "database": str(plan.database), "database_identity": [plan.database.stat().st_dev, plan.database.stat().st_ino],
                    "phase": "prepared", "profile_id": proof.profile_id, "original_catalog": proof.schema_sha256,
                    "original_rows": original_rows, "snapshot": _hash_file(snapshot, deadline),
                    "files": _file_state(plan, root, limits, deadline), "archive": str(args.output.absolute()),
                    "review_status": "legacy_business_states_preserved_require_source_review",
                    "validation": {"legacy_schema": "complete_frozen_profile_verified", "native_integrity_foreign_keys": "verified",
                                   "original_business_values": "preserved", "inherited_business_evidence": "requires_source_review"}}
                _write(directory, receipt, maximum_metadata=limits.manifest_bytes)
                _checkpoint("prepared")
                create_full_backup(plan, args.output, password, offline=True,
                                   limits=replace(limits, timeout_seconds=_remaining(deadline)))
                receipt["archive_identity"] = _hash_file(args.output, deadline)
                with tempfile.TemporaryDirectory(prefix="probe-", dir=directory) as workspace:
                    restore_full_backup(args.output, Path(workspace) / "restored", password,
                                        limits=replace(limits, timeout_seconds=_remaining(deadline)))
                receipt["phase"] = "backup_validated"
                _write(directory, receipt, maximum_metadata=limits.manifest_bytes)
                _checkpoint("backup_validated")
                with tempfile.TemporaryDirectory(prefix="stage-", dir=directory) as workspace:
                    expected, head, _ = _stage(snapshot, Path(workspace) / "reference.sqlite", proof.profile_id,
                                               deadline, expected_only=True)
                    actual, actual_head, final_rows = _stage(snapshot, Path(workspace) / "prepared.sqlite", proof.profile_id, deadline)
                    if actual != expected or actual_head != head:
                        raise LegacyUpgradeError("legacy_prepared_schema_mismatch")
                if _file_state(plan, root, limits, deadline) != receipt["files"]:
                    raise LegacyUpgradeError("legacy_installation_files_changed")
                proof.verify(_native(connection))
                scripts, applied_head = _pipeline(connection, proof.profile_id, deadline)
                if applied_head != head or catalog(_native(connection)) != expected:
                    raise LegacyUpgradeError("legacy_final_schema_mismatch")
                _check_preservation(connection, originals, triggers, deadline)
                _validate(connection)
                from alembic.migration import MigrationContext
                MigrationContext.configure(connection).stamp(scripts, head)
                if _row_state(connection, deadline) != final_rows:
                    raise LegacyUpgradeError("legacy_final_rows_mismatch")
                if ([plan.database.stat().st_dev, plan.database.stat().st_ino] != receipt["database_identity"]
                        or _hash_file(snapshot, deadline) != receipt["snapshot"]
                        or _hash_file(args.output, deadline) != receipt["archive_identity"]
                        or _file_state(plan, root, limits, deadline) != receipt["files"]):
                    raise LegacyUpgradeError("legacy_return_resources_changed")
                receipt.update(phase="transaction_prepared", target_head=head,
                               final_catalog=catalog_hash(expected), final_rows=final_rows)
                _write(directory, receipt, maximum_metadata=limits.manifest_bytes)
                _checkpoint("transaction_prepared")
                connection.commit()
                _checkpoint("committed")
                receipt["phase"] = "complete"
                _write(directory, receipt, maximum_metadata=limits.manifest_bytes)
                return {"operation_id": operation, "status": "complete", "backup_restore_verified": True,
                        "target_head": head, "review_status": receipt["review_status"], "original_keys_sessions_uploads_preserved": True}
        except Exception as error:
            native_error = getattr(error, "orig", error)
            sqlite_code = getattr(native_error, "sqlite_errorcode", 0) & 0xFF
            failure_code = "legacy_database_busy" if sqlite_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} else "legacy_upgrade_aborted"
            if receipt is not None and receipt["phase"] != "transaction_prepared":
                receipt.update(phase="aborted", error_code=error.args[0] if isinstance(error, (LegacyUpgradeError, LegacySchemaError)) else failure_code)
                _write(directory, receipt, maximum_metadata=limits.manifest_bytes)
            if isinstance(error, (LegacyUpgradeError, LegacySchemaError)):
                raise
            raise LegacyUpgradeError(failure_code) from None
        finally:
            engine.dispose()


def _matched_state(connection, receipt, deadline):
    value, rows = catalog_hash(catalog(_native(connection))), _row_state(connection, deadline)
    if value == receipt["original_catalog"] and rows == receipt["original_rows"]:
        return "original"
    if value == receipt.get("final_catalog") and rows == receipt.get("final_rows"):
        return "upgraded"
    return "changed"


def status(args, *, limits=None):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    with installation_lease(args.data_dir) as root:
        limits = _limits(args, limits)
        deadline = time.monotonic() + limits.timeout_seconds
        plan = _selected(args, root)
        _, receipt = _receipt(root, args.operation_id, maximum_metadata=limits.manifest_bytes)
        if (str(plan.database) != receipt["database"] or
                [plan.database.stat().st_dev, plan.database.stat().st_ino] != receipt["database_identity"]):
            raise LegacyUpgradeError("legacy_selected_database_changed")
        engine = create_engine("sqlite:///" + plan.database.as_posix(), poolclass=NullPool, hide_parameters=True)
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("PRAGMA query_only=ON")
                state = _matched_state(connection, receipt, deadline)
        finally:
            engine.dispose()
        return {"operation_id": receipt["operation_id"], "recorded_phase": receipt["phase"], "database_state": state,
                "installation_files_unchanged": _file_state(plan, root, limits, deadline) == receipt["files"],
                "review_status": receipt["review_status"]}


def rollback(args, *, limits=None, _checkpoint=lambda phase: None):
    if not args.offline:
        raise LegacyUpgradeError("legacy_offline_required")
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    with installation_lease(args.data_dir) as root:
        limits = _limits(args, limits)
        deadline = time.monotonic() + limits.timeout_seconds
        plan = _selected(args, root)
        directory, receipt = _receipt(root, args.operation_id, maximum_metadata=limits.manifest_bytes)
        snapshot = directory / "original.sqlite"
        if (str(plan.database) != receipt["database"] or
                [plan.database.stat().st_dev, plan.database.stat().st_ino] != receipt["database_identity"]):
            raise LegacyUpgradeError("legacy_selected_database_changed")
        if (_hash_file(snapshot, deadline) != receipt["snapshot"] or
                _hash_file(Path(receipt["archive"]), deadline) != receipt.get("archive_identity")):
            raise LegacyUpgradeError("legacy_return_resources_changed")
        if _file_state(plan, root, limits, deadline) != receipt["files"]:
            raise LegacyUpgradeError("legacy_installation_files_changed")
        engine = create_engine("sqlite:///" + plan.database.as_posix(), poolclass=NullPool, hide_parameters=True,
                               connect_args={"timeout": min(0.2, _remaining(deadline))})
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                connection.rollback()
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                _native(connection).set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                state = _matched_state(connection, receipt, deadline)
                if state == "original":
                    return {"operation_id": receipt["operation_id"], "status": "original_verified"}
                if state != "upgraded":
                    raise LegacyUpgradeError("legacy_rollback_refused_after_changes")
                receipt["phase"] = "rollback_prepared"
                _write(directory, receipt, maximum_metadata=limits.manifest_bytes)
                _checkpoint("rollback_prepared")
                with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as original:
                    prove_legacy_schema(original)
                    # Restore the proven snapshot's exact original definitions,
                    # including an approved empty version marker. Frozen profile
                    # DDL establishes compatibility, not the original spelling.
                    definitions = original.execute(
                        "SELECT type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL "
                        "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 WHEN 'view' THEN 2 ELSE 3 END,name"
                    ).fetchall()
                    for kind in ("trigger", "view", "table"):
                        names = connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type=? AND name NOT LIKE 'sqlite_%'", (kind,)).all()
                        for (name,) in names:
                            connection.exec_driver_sql(f"DROP {kind.upper()} {quoted(name)}")
                    for kind, sql in definitions:
                        if kind in {"table", "index"}:
                            connection.exec_driver_sql(sql)
                    for (table,) in original.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                        columns = [row[1] for row in original.execute(f"PRAGMA table_info({quoted(table)})")]
                        fields = ",".join(["rowid"] + [quoted(name) for name in columns])
                        reader = original.execute(f"SELECT {fields} FROM {quoted(table)}")
                        insert = f"INSERT INTO {quoted(table)}({fields}) VALUES ({','.join('?' for _ in range(len(columns) + 1))})"
                        while rows := reader.fetchmany(256):
                            _remaining(deadline)
                            connection.exec_driver_sql(insert, rows)
                    for kind, sql in definitions:
                        if kind not in {"table", "index"}:
                            connection.exec_driver_sql(sql)
                _validate(connection)
                if _matched_state(connection, receipt, deadline) != "original":
                    raise LegacyUpgradeError("legacy_rollback_validation_failed")
                if (_hash_file(snapshot, deadline) != receipt["snapshot"]
                        or _hash_file(Path(receipt["archive"]), deadline) != receipt["archive_identity"]
                        or _file_state(plan, root, limits, deadline) != receipt["files"]):
                    raise LegacyUpgradeError("legacy_return_resources_changed")
                _checkpoint("rollback_transaction_prepared")
                connection.commit()
                receipt["phase"] = "rolled_back"
                _write(directory, receipt, maximum_metadata=limits.manifest_bytes)
                return {"operation_id": receipt["operation_id"], "status": "rolled_back", "original_keys_sessions_uploads_preserved": True}
        finally:
            engine.dispose()


def normalized_kind(sql):
    return sql.split()[1].lower()
