"""Native snapshot/dump/restore AI proof; only owned loopback QA databases."""

import os
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import Table, create_engine, text
from sqlalchemy.engine import make_url

from backend.config import settings
from backend.db import schema_state
from backend.db.orm_models import UserORM
from backend.services import assistant_backup, full_backup, secret_box
from backend.tests.test_assistant_backup import ORIGINAL, seed, vault_file


def test_native_assistant_remote_snapshot_full_backup_probe_restore(tmp_path: Path, monkeypatch):
    admin_string = os.environ.get("IMMO_TEST_POSTGRES_ADMIN_URL", "")
    if not admin_string:
        pytest.skip("Native QA server explicitly required; never simulate a PostgreSQL pass")
    admin_url = make_url(admin_string)
    if admin_url.get_backend_name() != "postgresql" or admin_url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Only the explicitly owned loopback QA PostgreSQL server is permitted")
    basename = "immoqa_pro_ai_" + uuid4().hex[:20]
    names = []
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    source = recovered = None
    try:
        source_name, target_name = basename + "_source", basename + "_target"
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{source_name}"')
        names.append(source_name)
        source_url = admin_url.set(database=source_name).render_as_string(hide_password=False)
        source = create_engine(source_url)
        schema_state.initialise_empty(source)
        home = tmp_path / "source"
        uploads = home / "uploads"
        uploads.mkdir(parents=True)
        box = secret_box.SecretBox(home / "secrets" / "keyring.json")
        with source.begin() as connection:
            connection.execute(cast(Table, UserORM.__table__).insert(), {
                "id": "staff", "username": "synthetic-ai", "email": "synthetic@example.test", "full_name": "Synthetic",
                "hashed_password": "not-a-login", "role": "eigentuemer", "is_active": True, "totp_enabled": False,
                "created_at": datetime(2026, 10, 18), "updated_at": datetime(2026, 10, 18)})
            selected = seed(connection, box, state="queued")
        vault_file(uploads, box)
        from types import SimpleNamespace
        sources = full_backup.Sources(database_url=source_url, data_dir=home, uploads_dir=uploads,
            root=home / "backups", integration_state=home / "integrations.json", key_file=box.key_file,
            env_file=home / ".env", pg_bin_dir=os.environ.get("PG_BIN_DIR", ""), probe_postgres_url=admin_string,
            passphrase="synthetic-only-backup-passphrase",
            file_storage=SimpleNamespace(get=lambda key: ORIGINAL if key == selected.key else None))
        monkeypatch.setattr(secret_box, "default_secret_box", lambda: pytest.fail("Never use a live keyring for restore"))
        saved = full_backup.create_full_backup(sources=sources)
        archive = sources.root / saved["archive"]
        probe = full_backup.restore_probe(archive, sources)
        assert probe["ok"] and not probe["warnings"]
        assert probe["checks"]["full_restore"] and probe["checks"]["attachments"]["checked"]
        assert probe["checks"]["private_connections"]["assistant"]["rows"] == 5
        assert probe["checks"]["private_connections"]["assistant"]["vaults"] == 1
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{target_name}"')
        names.append(target_name)
        target_url = admin_url.set(database=target_name).render_as_string(hide_password=False)
        monkeypatch.setattr(settings, "pg_bin_dir", sources.pg_bin_dir)
        target = tmp_path / "fresh"
        result = full_backup.restore_archive(archive, target, passphrase=sources.passphrase, pg_target_url=target_url)
        assert result["readiness"] == "data_verified"
        assert (target / "uploads" / selected.key).read_bytes() == ORIGINAL
        recovered = create_engine(target_url)
        keys = secret_box.keys_from_bytes((target / "secrets" / "keyring.json").read_bytes())
        with recovered.connect() as connection:
            assert connection.execute(text("SELECT state FROM assistant_runs")).scalar_one() == "unknown"
            result = assistant_backup.verify(connection, keys, uploads=target / "uploads")
            assert result["rows"] == 5 and result["vaults"] == 1
        with source.connect() as connection:
            assert connection.execute(text("SELECT state FROM assistant_runs")).scalar_one() == "queued"
    finally:
        if recovered is not None:
            recovered.dispose()
        if source is not None:
            source.dispose()
        for name in reversed(names):
            assert name.startswith("immoqa_pro_ai_")
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.dispose()
