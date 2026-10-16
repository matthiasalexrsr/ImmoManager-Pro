"""Owned PostgreSQL full dump / restored private connection proof with archived keys only.

The CI native gate configures IMMO_TEST_POSTGRES_ADMIN_URL to a loopback
server. Each run creates and drops only its own random databases, and never
uses production keys, user data, or an external provider.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import Table, create_engine, select
from sqlalchemy.engine import make_url

from backend.db import schema_state
from backend.db.integration_connection_models import IntegrationConnectionORM
from backend.services import full_backup, secret_box


def test_native_private_connection_dump_restore_probe_and_fresh_target(tmp_path: Path):
    admin_url = os.environ.get("IMMO_TEST_POSTGRES_ADMIN_URL", "")
    if not admin_url:
        pytest.skip("Native QA server explicitly required; no simulated PostgreSQL pass")
    url = make_url(admin_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Only the explicitly owned loopback test PostgreSQL server is permitted")
    basename = "immoqa_pro_conn_" + uuid4().hex[:20]
    source_name, restore_name = basename + "_source", basename + "_target"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    names = []
    source_engine = restored_engine = None
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{source_name}"')
        names.append(source_name)
        source_url = url.set(database=source_name).render_as_string(hide_password=False)
        source_engine = create_engine(source_url)
        schema_state.initialise_empty(source_engine)
        home = tmp_path / "private-installation"
        (home / "uploads").mkdir(parents=True)
        (home / ".env").write_text("ENVIRONMENT=development\n", encoding="utf-8")
        box = secret_box.SecretBox(home / "secrets" / "keyring.json")
        secret_value = '{"synthetic":"nicht veröffentlichen"}'
        ident = str(uuid4())
        ciphertext = box.seal(secret_value, f"connection/{ident}/config")
        with source_engine.begin() as connection:
            connection.execute(cast(Table, IntegrationConnectionORM.__table__).insert(), {
                "id": ident, "provider_id": "contract-wizard", "name": "PG nur synthetisch",
                "enabled": False, "is_default": False, "archived": False,
                "revision": 1, "config_token": ciphertext, "secret_refs": {},
                "legacy_source_hash": None, "created_by": "synthetic-actor",
                "created_at": datetime(2026, 10, 16, 10), "updated_at": datetime(2026, 10, 16, 10),
            })
        passphrase = "synthetic-probe-phrase-only"
        sources = full_backup.Sources(
            database_url=source_url, data_dir=home, uploads_dir=home / "uploads",
            root=home / "backups" / "full",
            integration_state=home / "integrations.json", key_file=box.key_file,
            env_file=home / ".env", pg_bin_dir=os.environ.get("PG_BIN_DIR", ""),
            probe_postgres_url=admin_url, passphrase=passphrase,
        )
        event = full_backup.create_full_backup("manual", sources)
        archive = sources.root / event["archive"]
        assert full_backup.verify_archive(archive, expected_sha256=event["sha256"])["ok"]
        probe = full_backup.restore_probe(sources=sources)
        assert probe["ok"] and not probe["warnings"], probe["warnings"]
        assert probe["checks"]["full_restore"]
        assert probe["checks"]["private_connections"]["present"]
        assert probe["checks"]["private_connections"]["verified_rows"] >= 1

        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{restore_name}"')
        names.append(restore_name)
        restore_url = url.set(database=restore_name).render_as_string(hide_password=False)
        target = tmp_path / "fresh-postgres-target"
        manifest = full_backup.restore_archive(archive, target, passphrase=passphrase, pg_target_url=restore_url)
        assert manifest["dialect"] == "postgresql"
        assert "unterbrochene Vorgänge gesperrt" in " ".join(manifest["steps"])
        assert (target / "secrets" / "keyring.json").read_bytes() == box.key_file.read_bytes()
        restored_engine = create_engine(restore_url)
        with restored_engine.connect() as connection:
            row = connection.execute(select(IntegrationConnectionORM.config_token)
                                     .where(IntegrationConnectionORM.id == ident)).scalar_one()
        assert row == ciphertext
        assert secret_box.SecretBox(target / "secrets" / "keyring.json").open(
            row, f"connection/{ident}/config") == secret_value
    finally:
        if restored_engine is not None:
            restored_engine.dispose()
        if source_engine is not None:
            source_engine.dispose()
        for name in reversed(names):
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.dispose()
