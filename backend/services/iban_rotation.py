"""Backup-gated, streamed, atomic IBAN migration and encryption key rotation.

No current or old keys are removed. A crash rolls back the entire job; status
after restart is computed from actual committed rows, not a stale job flag.
"""

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import inspect, text

from .iban_encryption import IBANEncryptionError, IBANKeyring
from .iban_schema import lock_account_writes


def _columns(connection):
    return {column["name"] for column in inspect(connection).get_columns("accounts")}


def _rows(connection, *, chunks=500):
    fingerprint = "iban_fingerprint" if "iban_fingerprint" in _columns(connection) else "NULL"
    result = connection.execute(
        text(
            f"SELECT CAST(id AS TEXT), iban, {fingerprint} AS iban_fingerprint FROM accounts ORDER BY id"
        ).execution_options(stream_results=True)
    )
    try:
        while rows := result.fetchmany(chunks):
            yield rows
    finally:
        result.close()


def account_state_fingerprint(connection) -> str:
    digest = hashlib.sha256()
    for chunk in _rows(connection):
        for row in chunk:
            data = json.dumps(tuple(row), separators=(",", ":"), ensure_ascii=True).encode("ascii")
            digest.update(len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def database_identity(connection) -> str:
    """Non-secret identity detects accidental use of the live DB as its backup."""
    if connection.dialect.name == "sqlite":
        identity = tuple(connection.exec_driver_sql("PRAGMA database_list").first())
        if not identity[2]:
            raise IBANEncryptionError("ENCRYPTION_BACKUP_DATABASE_NOT_PERSISTENT")
    elif connection.dialect.name == "postgresql":
        identity = tuple(
            connection.execute(
                text("SELECT current_database(), current_schema(), inet_server_addr()::text, inet_server_port()")
            ).first()
        )
    else:
        raise IBANEncryptionError("ENCRYPTION_DATABASE_UNSUPPORTED")
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


@dataclass(frozen=True)
class VerifiedAccountBackup:
    account_state_sha256: str
    source_identity_sha256: str
    verified_at: str
    format: str = "immomanager-account-backup-proof-v1"

    def as_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        try:
            proof = cls(**value)
            datetime.fromisoformat(proof.verified_at)
            if proof.format != "immomanager-account-backup-proof-v1":
                raise ValueError()
            if any(
                len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
                for digest in (proof.account_state_sha256, proof.source_identity_sha256)
            ):
                raise ValueError()
            return proof
        except (ValueError, TypeError):
            raise IBANEncryptionError("ENCRYPTION_BACKUP_PROOF_INVALID") from None


def _read_snapshot(connection):
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")


def inspect_account_encryption(connection, ring: IBANKeyring, *, chunks=500):
    """Actual encrypted/plaintext counts. Authenticity failures abort the result."""
    total = empty = plain = legacy = unindexed = 0
    versions: Counter[str] = Counter()
    for chunk in _rows(connection, chunks=chunks):
        for _, stored, fingerprint in chunk:
            total += 1
            if not stored:
                empty += 1
                continue
            value = ring.decrypt(stored)
            if stored.startswith("enc:v1:"):
                versions[stored.split(":", 3)[2]] += 1
            elif stored.startswith("enc:"):
                legacy += 1
            else:
                plain += 1
            if fingerprint is None:
                unindexed += 1
            elif ring.fingerprint(value) != fingerprint:
                raise IBANEncryptionError("ENCRYPTION_INDEX_KEY_MISMATCH")
    return dict(
        accounts=total,
        empty=empty,
        plaintext=plain,
        legacy_jwt_encrypted=legacy,
        encrypted_by_key_id=dict(sorted(versions.items())),
        unindexed=unindexed,
        active_key_id=ring.active_key_id,
        verified=True,
        changed=False,
    )


def create_backup_proof(engine, ring: IBANKeyring) -> VerifiedAccountBackup:
    """Use an independently restored complete DB, never the live installation.

    The operator first restores/tests their normal complete backup. This checks
    its real schema, SQLite integrity, all account ciphertexts and snapshot.
    It does not purport to authenticate arbitrary external archive formats.
    """
    from ..db.auth_models import AuthSetupORM  # noqa: F401
    from ..db.orm_models import Base

    with engine.connect() as connection:
        _read_snapshot(connection)
        actual = inspect(connection)
        tables = set(actual.get_table_names())
        for table in Base.metadata.sorted_tables:
            if table.name not in tables:
                raise IBANEncryptionError("ENCRYPTION_BACKUP_SCHEMA_INCOMPLETE")
            names = {column["name"] for column in actual.get_columns(table.name)}
            expected = set(table.columns.keys())
            if table.name == "accounts":
                expected.discard("iban_fingerprint")  # A full pre-encryption backup is supported.
            if not expected.issubset(names):
                raise IBANEncryptionError("ENCRYPTION_BACKUP_SCHEMA_INCOMPLETE")
        if connection.dialect.name == "sqlite":
            if (
                connection.exec_driver_sql("PRAGMA integrity_check").fetchall() != [("ok",)]
                or connection.exec_driver_sql("PRAGMA foreign_key_check").first()
            ):
                raise IBANEncryptionError("ENCRYPTION_BACKUP_DATABASE_INVALID")
        inspect_account_encryption(connection, ring)
        return VerifiedAccountBackup(
            account_state_fingerprint(connection), database_identity(connection), datetime.now(timezone.utc).isoformat()
        )


def rotate_account_ibans(
    engine,
    ring: IBANKeyring,
    proof: VerifiedAccountBackup | None,
    *,
    offline=False,
    dry_run=False,
    chunks=500,
    after_chunk=None,
):
    """Prepare/validate every row before updating; one transaction for the job.

    The temporary unique index proves canonical duplicates without retaining
    all accounts in Python. `after_chunk` is an observability/test callback;
    exceptions (including interruption) roll back the entire transaction.
    """
    if not offline and not dry_run:
        raise IBANEncryptionError("ENCRYPTION_OFFLINE_REQUIRED")
    if type(chunks) is not int or chunks <= 0:
        raise ValueError("chunks must be positive")
    if not ring.active_key_id or not ring.index_key:
        raise IBANEncryptionError("ENCRYPTION_KEY_MISSING")
    table = "iban_rotation_" + uuid4().hex
    with engine.begin() as connection:
        lock_account_writes(connection)
        if "iban_fingerprint" not in _columns(connection):
            raise IBANEncryptionError("ENCRYPTION_SCHEMA_MIGRATION_REQUIRED")
        source_hash = account_state_fingerprint(connection)
        identity = database_identity(connection)
        if not dry_run:
            if not isinstance(proof, VerifiedAccountBackup):
                raise IBANEncryptionError("ENCRYPTION_VERIFIED_BACKUP_REQUIRED")
            if proof.source_identity_sha256 == identity:
                raise IBANEncryptionError("ENCRYPTION_BACKUP_IS_LIVE_DATABASE")
            if proof.account_state_sha256 != source_hash:
                raise IBANEncryptionError("ENCRYPTION_BACKUP_SNAPSHOT_MISMATCH")
        connection.exec_driver_sql(
            f"CREATE TEMPORARY TABLE {table} (id VARCHAR PRIMARY KEY, iban TEXT, fingerprint VARCHAR(64) UNIQUE)"
        )
        changed = processed = 0
        try:
            # Keyset pages avoid keeping a PostgreSQL server-side cursor open
            # while issuing inserts/updates through the same connection.
            last = ""
            while True:
                rows = connection.execute(
                    text(
                        "SELECT CAST(id AS TEXT), iban, iban_fingerprint FROM accounts WHERE CAST(id AS TEXT) > :last ORDER BY id LIMIT :size"
                    ),
                    dict(last=last, size=chunks),
                ).fetchall()
                if not rows:
                    break
                staged = []
                for account_id, stored, old_index in rows:
                    plain = ring.decrypt(stored)
                    fingerprint = ring.fingerprint(plain)
                    if old_index is not None and old_index != fingerprint:
                        raise IBANEncryptionError("ENCRYPTION_INDEX_KEY_MISMATCH")
                    encrypted = ring.encrypt(plain) if plain and plain.strip() else None
                    changed += int(encrypted != stored or fingerprint != old_index)
                    staged.append(dict(id=account_id, iban=encrypted, fingerprint=fingerprint))
                from sqlalchemy.exc import IntegrityError

                try:
                    connection.execute(
                        text(f"INSERT INTO {table} (id, iban, fingerprint) VALUES (:id, :iban, :fingerprint)"), staged
                    )
                except IntegrityError:
                    raise IBANEncryptionError("ENCRYPTION_DUPLICATE_IBAN") from None
                last = rows[-1][0]
                processed += len(rows)
                if after_chunk:
                    after_chunk(processed)
            if not dry_run:
                # Copy only IBAN storage fields: balances, history and edit
                # revisions are unchanged by a purely cryptographic operation.
                connection.execute(
                    text(
                        f"UPDATE accounts SET iban = (SELECT iban FROM {table} WHERE id = CAST(accounts.id AS TEXT)), "
                        f"iban_fingerprint = (SELECT fingerprint FROM {table} WHERE id = CAST(accounts.id AS TEXT))"
                    )
                )
                for chunk in _rows(connection, chunks=chunks):
                    for _, stored, fingerprint in chunk:
                        plain = ring.decrypt(stored)
                        if ring.fingerprint(plain) != fingerprint or (
                            stored and not stored.startswith(f"enc:v1:{ring.active_key_id}:")
                        ):
                            raise IBANEncryptionError("ENCRYPTION_ROTATION_VERIFICATION_FAILED")
            return dict(
                accounts=processed,
                would_change=changed,
                changed=not dry_run,
                updated=changed if not dry_run else 0,
                active_key_id=ring.active_key_id,
                verified=True,
                atomic=True,
                backup_verified=not dry_run,
                retain_old_keys=True,
                restart_required=not dry_run,
            )
        finally:
            # Temporary table belongs to this exact call; no persistent job
            # table or partially migrated restart state is ever published.
            if connection.in_transaction():
                try:
                    connection.exec_driver_sql(f"DROP TABLE {table}")
                except Exception:
                    pass  # PostgreSQL failed transaction drops it on rollback.
