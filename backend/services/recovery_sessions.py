"""Offline restore boundary; ordinary application startup never calls this."""

import json
import secrets
import time
from collections.abc import Mapping
from pathlib import Path


class SessionRestoreError(RuntimeError):
    """Safe diagnostics without credentials, tokens or database parameters."""


def rotated_configuration(values: Mapping[str, str], *, legacy_iban_present: bool = False) -> dict[str, str]:
    result = dict(values)
    original = result.get("JWT_SECRET_KEY")
    if not isinstance(original, str) or not original:
        raise SessionRestoreError("restore_signing_key_missing: ursprüngliche Schlüsselkonfiguration erforderlich")
    try:
        legacy = json.loads(result.get("ENCRYPTION_LEGACY_JWT_KEYS") or "[]")
    except (ValueError, TypeError):
        raise SessionRestoreError("restore_legacy_keyring_invalid: Schlüsselkonfiguration prüfen") from None
    if not isinstance(legacy, list) or any(not isinstance(key, str) or not key for key in legacy):
        raise SessionRestoreError("restore_legacy_keyring_invalid: Schlüsselkonfiguration prüfen")
    if legacy_iban_present and original not in legacy:
        result["ENCRYPTION_LEGACY_JWT_KEYS"] = json.dumps([*legacy, original], separators=(",", ":"))
    result["JWT_SECRET_KEY"] = secrets.token_hex(48)
    return result


def _remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise SessionRestoreError("restore_security_timeout: Wiederherstellung nicht freigegeben")
    return value


def invalidate_and_inspect(connection, original_configuration, *, deadline):
    """Caller owns an offline transaction; rollback covers every family update."""
    from sqlalchemy import inspect

    from ..db.session_models import invalidate_restored_sessions
    from .iban_encryption import keyring_from_configuration

    _remaining(deadline)
    tables = set(inspect(connection).get_table_names())
    security_tables = tables & {"auth_sessions", "auth_refresh_tokens"}
    if security_tables and len(security_tables) != 2:
        raise SessionRestoreError("restore_session_schema_incomplete: kompatible vollständige Sicherung erforderlich")
    # Validate every immutable original before revoking one family or creating
    # a new signing configuration. Both missing legacy tables remain compatible.
    from .measurement_history_database import validate_measurement_database
    from .measurement_history_validation import MeasurementIntegrityError
    try:
        validate_measurement_database(connection, deadline=deadline)
    except MeasurementIntegrityError:
        raise SessionRestoreError("restore_measurement_history_invalid: vollständige unveränderte Sicherung verwenden; Sicherheitsabschluss nicht ausgeführt") from None
    from .operational_job_validation import JobIntegrityError, reset_restored_job_claims, validate_job_journal
    from .operational_scheduler_validation import reset_scheduler_claims, validate_scheduler
    from .tenancy_workflow_validation import WorkflowIntegrityError, validate_workflow_journal
    try:
        validate_workflow_journal(connection, deadline=deadline)
    except WorkflowIntegrityError:
        raise SessionRestoreError("restore_tenancy_workflow_invalid: vollständige unveränderte Sicherung verwenden; Sicherheitsabschluss nicht ausgeführt") from None
    try:
        validate_job_journal(connection, deadline=deadline)
        validate_scheduler(connection, deadline=deadline)
    except JobIntegrityError:
        raise SessionRestoreError("restore_operational_jobs_invalid: vollständige unveränderte Sicherung verwenden; Sicherheitsabschluss nicht ausgeführt") from None
    from .contract_correspondence_validation import EvidenceError, validate_correspondence_journal
    try:
        validate_correspondence_journal(connection, deadline=deadline)
    except EvidenceError:
        raise SessionRestoreError("restore_contract_correspondence_invalid: vollständige unveränderte Sicherung mit Originalen verwenden; Sicherheitsabschluss nicht ausgeführt") from None
    from .contract_lifecycle_validation import JournalValidationError, validate_lifecycle_journal
    from .document_version_validation import verify_document_versions
    from .recovery_archive import RecoveryError
    try:
        validate_lifecycle_journal(connection)
    except JournalValidationError:
        raise SessionRestoreError("restore_contract_lifecycle_invalid: vollständige unveränderte Sicherung verwenden; Sicherheitsabschluss nicht ausgeführt") from None
    try:
        verify_document_versions(connection, deadline=deadline)
    except RecoveryError:
        raise SessionRestoreError("restore_document_versions_invalid: unveränderte vollständige Sicherung verwenden; Sicherheitsabschluss nicht ausgeführt") from None
    from .integrations.history_types import HistoryError
    from .recovery_history import normalize_restored_history, validate_configured_history
    try:
        validate_configured_history(connection, original_configuration, deadline=deadline)
    except (HistoryError, ValueError):
        raise SessionRestoreError("restore_integration_history_invalid: unveränderte vollständige Sicherung und gesicherte Schlüssel-/Budgetkonfiguration verwenden; Sicherheitsabschluss nicht ausgeführt") from None
    legacy = False
    if "accounts" in tables:
        keyring = None
        rows = connection.execution_options(stream_results=True).exec_driver_sql(
            "SELECT iban FROM accounts WHERE iban IS NOT NULL")
        try:
            while batch := rows.fetchmany(1000):
                for (value,) in batch:
                    _remaining(deadline)
                    if isinstance(value, str) and value.startswith("enc:"):
                        if keyring is None:
                            keyring = keyring_from_configuration(original_configuration)
                        keyring.decrypt(value)
                        legacy = legacy or not value.startswith("enc:v")
        finally:
            rows.close()
        # PostgreSQL named cursors must not apply to the following UPDATE.
        connection.execution_options(stream_results=False)
    if "form_drafts" in tables:
        # Verify with the archive's actual key map before changing any family.
        # One corrupt or oversized envelope rolls back the entire offline step.
        from .form_draft_crypto import ciphertext_budget, decrypt
        ring = keyring_from_configuration(original_configuration)
        budget = ciphertext_budget(original_configuration)
        rows = connection.execution_options(stream_results=True).exec_driver_sql(
            "SELECT id, CASE WHEN length(payload) <= " + str(budget) + " THEN payload ELSE NULL END FROM form_drafts")
        try:
            while batch := rows.fetchmany(1):
                for identifier, payload in batch:
                    _remaining(deadline)
                    if not isinstance(payload, str):
                        raise SessionRestoreError("restore_draft_payload_invalid: vollständige Sicherung und Budgets prüfen")
                    value = json.loads(decrypt(payload, identifier.encode("ascii"), ring))
                    if not isinstance(value, dict) or not isinstance(value.get("values"), dict):
                        raise SessionRestoreError("restore_draft_payload_invalid: vollständige Sicherung prüfen")
        finally:
            rows.close()
            connection.execution_options(stream_results=False)
    # All families have passed read-only proof. Claim reset and session revocation
    # share this outer offline transaction, including every later caller failure.
    normalize_restored_history(connection, original_configuration, deadline=deadline)
    reset_restored_job_claims(connection, deadline=deadline)
    reset_scheduler_claims(connection, deadline=deadline)
    count = invalidate_restored_sessions(connection) if security_tables else 0
    if type(count) is not int or count < 0:
        raise SessionRestoreError("restore_session_count_invalid: Sicherheitsabschluss nicht bestätigt")
    _remaining(deadline)
    return {"revoked_session_count": count, "legacy_iban_present": legacy}


def secure_sqlite_restore(database: Path, original_configuration, *, deadline):
    """Mutate only the caller's staged copy, with a fresh independent connection."""
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL

    engine = create_engine(URL.create("sqlite", database=str(database)),
        connect_args={"timeout": _remaining(deadline)})
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                report = invalidate_and_inspect(connection, original_configuration, deadline=deadline)
                values = rotated_configuration(original_configuration, legacy_iban_present=report["legacy_iban_present"])
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return values, report
    except SessionRestoreError:
        raise
    except Exception:
        raise SessionRestoreError("restore_session_security_failed: Wiederherstellung nicht freigegeben") from None
    finally:
        engine.dispose()
