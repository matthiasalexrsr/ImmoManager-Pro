"""Migration/rotation uses real backups, independent connections and rollback."""

import json
import multiprocessing
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from backend.models import AccountPatch
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import iban_rotation
from backend.services.iban_encryption import IBANEncryptionError, IBANKeyring, current_keyring
from backend.services.iban_rotation import (
    VerifiedAccountBackup,
    create_backup_proof,
    inspect_account_encryption,
    rotate_account_ibans,
)
from backend.tests.test_account_encryption import (
    IBAN,
    INDEX,
    KEY,
    LEGACY,
    OTHER,
    configure,
    legacy_cipher,
    payload,
)
from backend.tests.test_account_encryption import account_database as shared_account_database

account_database = shared_account_database


def backup_database(engine, path):
    with sqlite3.connect(engine.url.database) as source, sqlite3.connect(path) as backup:
        source.backup(backup)
    return create_engine("sqlite:///" + path.as_posix(), hide_parameters=True)


def rows(engine):
    with engine.connect() as connection:
        return connection.execute(text("SELECT * FROM accounts ORDER BY id")).fetchall()


def rotation_keyring():
    return IBANKeyring("new", {"default": KEY, "new": OTHER}, (LEGACY,), INDEX)


def _rotate_process(url, proof, ready, start, results):
    engine = create_engine(url, connect_args={"timeout": 20}, hide_parameters=True)
    try:
        ready.put(True)
        if not start.wait(timeout=20):
            raise RuntimeError("Synthetic process-start timeout")
        try:
            result = rotate_account_ibans(
                engine, rotation_keyring(), VerifiedAccountBackup.from_dict(proof), offline=True, chunks=1
            )
            results.put(("committed", result["updated"]))
        except IBANEncryptionError as exc:
            results.put(("refused", exc.code))
    finally:
        engine.dispose()


def seed_mixed(engine, portfolio):
    with Session(engine) as session:
        SQLAlchemyStore(session).create_account(payload(portfolio))
        SQLAlchemyStore(session).create_account(payload(portfolio, "FR" + "2" * 20))
    with engine.begin() as connection:
        for identity, iban in (("plain", "GB" + "3" * 20), ("legacy", legacy_cipher("NL" + "4" * 20)), ("empty", None)):
            connection.execute(
                text(
                    "INSERT INTO accounts (id, portfolio_id, name, account_type, iban, opening_balance, balance, created_at, updated_at) VALUES (:id, :p, :id, 'checking', :iban, 123.45, 321.09, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                dict(id=identity, p=portfolio, iban=iban),
            )


def test_streamed_preview_and_backup_gated_rotation_preserve_other_columns(account_database, tmp_path):
    engine, portfolio = account_database
    seed_mixed(engine, portfolio)
    before = rows(engine)
    ring = rotation_keyring()
    with engine.connect() as connection:
        status = inspect_account_encryption(connection, ring, chunks=1)
    assert (
        status["plaintext"] == 1
        and status["legacy_jwt_encrypted"] == 1
        and status["encrypted_by_key_id"] == {"default": 2}
    )
    preview = rotate_account_ibans(engine, ring, None, dry_run=True, chunks=1)
    assert preview["would_change"] == 4 and preview["updated"] == 0
    assert rows(engine) == before
    backup = backup_database(engine, tmp_path / "separately-restored-full.db")
    try:
        proof = create_backup_proof(backup, ring)
        result = rotate_account_ibans(engine, ring, proof, offline=True, chunks=1)
    finally:
        backup.dispose()
    assert result["updated"] == 4 and result["atomic"] and result["retain_old_keys"]
    after = rows(engine)
    names = [
        column.name
        for column in __import__("backend.db.orm_models", fromlist=["AccountORM"]).AccountORM.__table__.columns
    ]
    changed = {names.index("iban"), names.index("iban_fingerprint")}
    for original, updated in zip(before, after):
        assert all(left == right for index, (left, right) in enumerate(zip(original, updated)) if index not in changed)
    with engine.connect() as connection:
        status = inspect_account_encryption(connection, ring, chunks=1)
    assert status["plaintext"] == status["legacy_jwt_encrypted"] == status["unindexed"] == 0
    assert status["encrypted_by_key_id"] == {"new": 4}


@pytest.mark.parametrize(
    "failure", ["no-proof", "not-offline", "same-database", "stale-backup", "wrong-key", "wrong-index"]
)
def test_preconditions_never_change_committed_data(failure, account_database, tmp_path):
    engine, portfolio = account_database
    with Session(engine) as session:
        account = SQLAlchemyStore(session).create_account(payload(portfolio))
    backup = backup_database(engine, tmp_path / "restored.db")
    ring = rotation_keyring()
    proof = create_backup_proof(backup, ring)
    backup.dispose()
    if failure == "same-database":
        proof = create_backup_proof(engine, ring)
    if failure == "stale-backup":
        with Session(engine) as session:
            SQLAlchemyStore(session)._patch_entity("account", account.id, AccountPatch(iban="DE" + "5" * 20))
    if failure == "wrong-key":
        ring = IBANKeyring("new", {"default": OTHER, "new": OTHER}, (LEGACY,), INDEX)
    if failure == "wrong-index":
        ring = IBANKeyring("new", {"default": KEY, "new": OTHER}, (LEGACY,), OTHER)
    before = rows(engine)
    with pytest.raises(IBANEncryptionError):
        rotate_account_ibans(
            engine, ring, None if failure == "no-proof" else proof, offline=failure != "not-offline", chunks=1
        )
    assert rows(engine) == before


def test_canonical_duplicates_in_legacy_data_refuse_before_any_accounts_update(account_database, tmp_path):
    engine, portfolio = account_database
    with engine.begin() as connection:
        for identity, iban in (("one", IBAN), ("two", "de89 3704 0044 0532 0130 00")):
            connection.execute(
                text(
                    "INSERT INTO accounts (id, portfolio_id, name, account_type, iban, opening_balance, balance, created_at, updated_at) VALUES (:id, :p, :id, 'checking', :iban, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                dict(id=identity, p=portfolio, iban=iban),
            )
    before = rows(engine)
    backup = backup_database(engine, tmp_path / "restored.db")
    proof = create_backup_proof(backup, rotation_keyring())
    backup.dispose()
    with pytest.raises(IBANEncryptionError, match="ENCRYPTION_DUPLICATE_IBAN"):
        rotate_account_ibans(engine, rotation_keyring(), proof, offline=True, chunks=1)
    assert rows(engine) == before


def test_failure_after_the_real_update_rolls_back_every_ciphertext(account_database, tmp_path, monkeypatch):
    engine, portfolio = account_database
    seed_mixed(engine, portfolio)
    backup = backup_database(engine, tmp_path / "restored.db")
    proof = create_backup_proof(backup, rotation_keyring())
    backup.dispose()
    before = rows(engine)
    executed = []
    prepared = Event()
    original = iban_rotation._rows

    @event.listens_for(engine, "before_cursor_execute")
    def observed(connection, cursor, statement, *args):
        if statement.startswith("UPDATE accounts SET"):
            executed.append(statement)

    def broken(connection, **kwargs):
        if prepared.is_set():
            raise RuntimeError("Synthetic verification/disk failure after update")
        yield from original(connection, **kwargs)

    monkeypatch.setattr(iban_rotation, "_rows", broken)
    with pytest.raises(RuntimeError, match="after update"):
        rotate_account_ibans(
            engine,
            rotation_keyring(),
            proof,
            offline=True,
            chunks=1,
            after_chunk=lambda count: prepared.set() if count == 5 else None,
        )
    assert len(executed) == 1 and rows(engine) == before
    with engine.connect() as connection:
        assert not connection.execute(
            text("SELECT name FROM sqlite_temp_master WHERE name LIKE 'iban_rotation_%'")
        ).fetchall()


def test_account_write_waits_for_rotation_then_preserves_the_new_version(account_database, tmp_path, monkeypatch):
    engine, portfolio = account_database
    with Session(engine) as session:
        original = SQLAlchemyStore(session).create_account(payload(portfolio))
    backup = backup_database(engine, tmp_path / "restored.db")
    proof = create_backup_proof(backup, rotation_keyring())
    backup.dispose()
    configure(monkeypatch, key="", keyring=json.dumps({"default": KEY, "new": OTHER}), active="new")
    prepared = Event()
    release = Event()
    writing = Event()

    def pause(count):
        prepared.set()
        assert release.wait(timeout=10)

    def write():
        writing.set()
        with Session(engine) as session:
            return SQLAlchemyStore(session).create_account(payload(portfolio, "DE" + "6" * 20)).id

    with ThreadPoolExecutor(2) as pool:
        rotation = pool.submit(rotate_account_ibans, engine, rotation_keyring(), proof, offline=True, after_chunk=pause)
        assert prepared.wait(timeout=10)
        writer = pool.submit(write)
        assert writing.wait(timeout=10)
        assert not writer.done()
        release.set()
        assert rotation.result(timeout=15)["updated"] == 1
        assert writer.result(timeout=15) != original.id
    with engine.connect() as connection:
        assert inspect_account_encryption(connection, current_keyring())["encrypted_by_key_id"] == {"new": 2}


def test_independent_processes_cannot_publish_a_partial_or_second_rotation(account_database, tmp_path):
    engine, portfolio = account_database
    seed_mixed(engine, portfolio)
    backup = backup_database(engine, tmp_path / "restored-process.db")
    proof = create_backup_proof(backup, rotation_keyring())
    backup.dispose()
    context = multiprocessing.get_context("spawn")
    ready, results, start = context.Queue(), context.Queue(), context.Event()
    processes = [
        context.Process(target=_rotate_process, args=(str(engine.url), proof.as_dict(), ready, start, results))
        for _ in range(2)
    ]
    try:
        for process in processes:
            process.start()
        assert ready.get(timeout=20) and ready.get(timeout=20)
        start.set()
        outcomes = [results.get(timeout=30) for _ in processes]
        assert sorted(outcomes) == [("committed", 4), ("refused", "ENCRYPTION_BACKUP_SNAPSHOT_MISMATCH")]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
        ready.close()
        results.close()
    with engine.connect() as connection:
        assert inspect_account_encryption(connection, rotation_keyring())["encrypted_by_key_id"] == {"new": 4}
