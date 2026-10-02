"""Actual CLI entrypoints use protected files and never print secret inputs."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from backend.tests.test_account_encryption import INDEX, KEY, LEGACY, payload
from backend.tests.test_account_encryption import account_database as shared_account_database
from backend.tests.test_iban_rotation import backup_database, rotation_keyring
from scripts.private_server_backup import protected_new_file

ROOT = Path(__file__).resolve().parents[2]
account_database = shared_account_database


def protected(path, values):
    with protected_new_file(path) as target:
        target.write(json.dumps(values).encode())
    return path


def cli(arguments, *, stdin=None, environment=None):
    return subprocess.run(
        [sys.executable, "-m", "backend.iban_maintenance", *map(str, arguments)],
        cwd=ROOT,
        env={**os.environ, "PYTHONUTF8": "1", **(environment or {})},
        input=stdin,
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )


def test_create_keyring_retains_keys_and_never_echoes_protected_stdin(tmp_path):
    first = tmp_path / "first.json"
    result = cli(["create-keyring", "--output", first, "--legacy-secret-stdin"], stdin=LEGACY + "\n")
    assert result.returncode == 0, result.stderr + result.stdout
    values = json.loads(first.read_text())
    second = tmp_path / "second.json"
    rotated = cli(["create-keyring", "--output", second, "--existing-config", first, "--key-id", "new"])
    assert rotated.returncode == 0, rotated.stderr + rotated.stdout
    keys = json.loads(json.loads(second.read_text())["ENCRYPTION_KEYRING"])
    assert set(keys) == {"default", "new"}
    assert keys["default"] == json.loads(values["ENCRYPTION_KEYRING"])["default"]
    assert json.loads(second.read_text())["ENCRYPTION_INDEX_KEY"] == values["ENCRYPTION_INDEX_KEY"]
    for secret in [LEGACY, values["ENCRYPTION_INDEX_KEY"], *keys.values()]:
        assert secret not in result.stdout + result.stderr + rotated.stdout + rotated.stderr
    before = first.read_bytes()
    rejected = cli(["create-keyring", "--output", first])
    assert rejected.returncode == 1 and first.read_bytes() == before


def test_invalid_command_does_not_echo_a_pasted_secret(tmp_path):
    result = cli(["create-keyring", "--output", tmp_path / "never.json", "--secret", LEGACY])
    assert result.returncode == 2 and LEGACY not in result.stdout + result.stderr
    assert not (tmp_path / "never.json").exists()


def test_explicit_selected_config_and_dry_run_do_not_use_foreign_environment(account_database, tmp_path):
    from sqlalchemy.orm import Session

    from backend.repositories.sql_store import SQLAlchemyStore

    engine, portfolio = account_database
    with Session(engine) as session:
        SQLAlchemyStore(session).create_account(payload(portfolio))
    values = dict(DATABASE_URL=str(engine.url), ENCRYPTION_KEY=KEY, ENCRYPTION_INDEX_KEY=INDEX, JWT_SECRET_KEY=LEGACY)
    source = protected(tmp_path / "selected.json", values)
    with sqlite3.connect(engine.url.database) as db:
        before = db.execute("SELECT * FROM accounts").fetchall()
    hostile = dict(
        DATABASE_URL="sqlite:///" + (tmp_path / "foreign-never-created.db").as_posix(),
        ENCRYPTION_KEY="invalid-foreign-secret",
    )
    result = cli(["status", "--config", source], environment=hostile)
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["encrypted_by_key_id"] == {"default": 1}
    ring = rotation_keyring()
    future = protected(
        tmp_path / "future.json",
        dict(
            ENCRYPTION_KEY="",
            ENCRYPTION_KEYRING=json.dumps(dict(ring.keys)),
            ENCRYPTION_ACTIVE_KEY_ID=ring.active_key_id,
            ENCRYPTION_INDEX_KEY=ring.index_key,
            ENCRYPTION_LEGACY_JWT_KEYS=json.dumps(ring.legacy_jwt_keys),
        ),
    )
    dry = cli(
        ["rotate", "--config", source, "--key-config", future, "--dry-run", "--chunk-size", "1"], environment=hostile
    )
    assert dry.returncode == 0 and json.loads(dry.stdout)["would_change"] == 1, dry.stderr + dry.stdout
    with sqlite3.connect(engine.url.database) as db:
        assert db.execute("SELECT * FROM accounts").fetchall() == before
    assert not (tmp_path / "foreign-never-created.db").exists()


def test_real_separately_restored_proof_then_offline_rotation(account_database, tmp_path):
    from sqlalchemy.orm import Session

    from backend.repositories.sql_store import SQLAlchemyStore

    engine, portfolio = account_database
    with Session(engine) as session:
        SQLAlchemyStore(session).create_account(payload(portfolio))
    backup = backup_database(engine, tmp_path / "restored-complete.db")
    values = dict(DATABASE_URL=str(backup.url), ENCRYPTION_KEY=KEY, ENCRYPTION_INDEX_KEY=INDEX, JWT_SECRET_KEY=LEGACY)
    backup_config = protected(tmp_path / "backup.json", values)
    backup.dispose()
    proof = tmp_path / "proof.json"
    result = cli(["backup-proof", "--config", backup_config, "--output", proof])
    assert result.returncode == 0, result.stderr + result.stdout
    source = protected(tmp_path / "source.json", {**values, "DATABASE_URL": str(engine.url)})
    key_config = tmp_path / "rotation.json"
    created = cli(["create-keyring", "--existing-config", source, "--output", key_config, "--key-id", "second"])
    assert created.returncode == 0, created.stdout + created.stderr
    rotated = cli(["rotate", "--config", source, "--key-config", key_config, "--backup-proof", proof, "--offline"])
    assert rotated.returncode == 0, rotated.stdout + rotated.stderr
    with sqlite3.connect(engine.url.database) as db:
        assert db.execute("SELECT iban FROM accounts").fetchone()[0].startswith("enc:v1:second:")
    values = json.loads(key_config.read_text())
    for secret in [KEY, INDEX, LEGACY, *json.loads(values["ENCRYPTION_KEYRING"]).values()]:
        assert secret not in rotated.stdout + rotated.stderr
