"""Full backup, restore probe, restore and explicit upgrade against a real PostgreSQL server.

Opt in with IMMO_TEST_POSTGRES_ADMIN_URL (see test_document_versions_postgres.py); needs
pg_dump/pg_restore of the server's major version (PATH or PG_BIN_DIR).
"""

import json
import os
import shutil
import zipfile
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from test_document_versions_postgres import postgres  # noqa: F401  (fixture: own database per test)

from backend.config import settings
from backend.db import schema_state
from backend.services import full_backup
from backend.services.full_backup import Sources

OLD_REVISION = "a7c2e9f4b1d3"


@pytest.fixture
def pg_tools():
    if not (shutil.which("pg_dump", path=os.getenv("PG_BIN_DIR") or None) or shutil.which("pg_dump")):
        pytest.skip("pg_dump not installed")
    return os.getenv("PG_BIN_DIR", "")


def _url(engine) -> str:
    return engine.url.render_as_string(hide_password=False)


def _sources(tmp_path, url, pg_bin_dir, probe_url=""):
    (tmp_path / "uploads").mkdir(exist_ok=True)
    (tmp_path / "uploads" / "a.pdf").write_bytes(b"%PDF-1.4 pg")
    return Sources(database_url=url, data_dir=tmp_path, uploads_dir=tmp_path / "uploads", root=tmp_path / "full",
                   integration_state=tmp_path / "integrations.json", key_file=tmp_path / "keyring.json",
                   env_file=tmp_path / ".env", pg_bin_dir=pg_bin_dir, probe_postgres_url=probe_url)


def _seed(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO portfolios (id, name, currency, timezone, status, created_at, updated_at) "
                             "VALUES ('pf1', 'Nord', 'EUR', 'Europe/Berlin', 'active', now(), now()), "
                             "('pf2', 'Süd', 'EUR', 'Europe/Berlin', 'active', now(), now())")


def _probe_databases(admin_url) -> list[str]:
    admin = sa.create_engine(admin_url)
    try:
        with admin.connect() as conn:
            return [row[0] for row in conn.execute(
                sa.text("SELECT datname FROM pg_database WHERE datname LIKE :pattern"),
                {"pattern": "immo_restore_probe_%"})]
    finally:
        admin.dispose()


def test_postgres_full_backup_probe_and_restore(postgres, pg_tools, tmp_path, monkeypatch):  # noqa: F811
    engine, _config = postgres
    _seed(engine)
    admin_url = os.environ["IMMO_TEST_POSTGRES_ADMIN_URL"]
    sources = _sources(tmp_path, _url(engine), pg_tools, probe_url=admin_url)

    event = full_backup.create_full_backup("manual", sources)
    archive = sources.root / event["archive"]
    with zipfile.ZipFile(archive) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["database"]["dialect"] == "postgresql" and manifest["database"]["path"] == "database/postgres.dump"
    assert manifest["database"]["row_counts"]["portfolios"] == 2
    assert manifest["database"]["revision"] == schema_state.head_revision()
    assert full_backup.verify_archive(archive)["ok"]

    probe = full_backup.restore_probe(sources=sources)
    assert probe["checks"]["full_restore"] is True and probe["checks"]["row_counts_match"]
    assert probe["warnings"] == []
    assert _probe_databases(admin_url) == []                 # the probe database is dropped again

    target_name = f"immoqa_restore_{uuid4().hex}"
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    target_url = sa.engine.make_url(admin_url).set(database=target_name).render_as_string(hide_password=False)
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE "{target_name}"')
        monkeypatch.setattr(settings, "pg_bin_dir", pg_tools)
        result = full_backup.restore_archive(archive, tmp_path / "restored", pg_target_url=target_url)
        assert (tmp_path / "restored" / "postgres.dump").is_file() and (tmp_path / "restored" / "uploads" / "a.pdf").is_file()
        assert any("eingespielt" in step for step in result["steps"])
        assert schema_state.inspect_url(target_url).state == schema_state.CURRENT
        restored = sa.create_engine(target_url)
        with restored.connect() as conn:
            assert conn.exec_driver_sql("SELECT count(*) FROM portfolios").scalar() == 2
        restored.dispose()
        with pytest.raises(full_backup.BackupError, match="nicht leer"):
            full_backup.restore_archive(archive, tmp_path / "again", pg_target_url=target_url)
    finally:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{target_name}" WITH (FORCE)')
        admin.dispose()


def test_postgres_probe_without_a_probe_server_checks_the_dump_only(postgres, pg_tools, tmp_path):  # noqa: F811
    engine, _config = postgres
    sources = _sources(tmp_path, _url(engine), pg_tools)
    full_backup.create_full_backup("manual", sources)
    probe = full_backup.restore_probe(sources=sources)
    assert probe["checks"]["full_restore"] is False and probe["checks"]["dump_entries"] > 0
    assert any("RESTORE_PROBE_POSTGRES_URL" in warning for warning in probe["warnings"])


def test_postgres_start_refuses_and_the_explicit_upgrade_backs_up_first(postgres, pg_tools, tmp_path,  # noqa: F811
                                                                        monkeypatch):
    from backend.upgrade import EXIT_OK, upgrade

    engine, config = postgres
    command.downgrade(config, OLD_REVISION)
    _seed(engine)
    with pytest.raises(schema_state.SchemaUpgradeRequired):
        schema_state.ensure_current(engine)
    assert schema_state.inspect_engine(engine).revision == OLD_REVISION
    for name, value in {"database_url": _url(engine), "data_dir": str(tmp_path), "backup_dir": str(tmp_path / "b"),
                        "uploads_dir": str(tmp_path / "uploads"), "pg_bin_dir": pg_tools,
                        "integration_state_file": str(tmp_path / "integrations.json"),
                        "secret_key_file": str(tmp_path / "keyring.json")}.items():
        monkeypatch.setattr(settings, name, value)
    assert upgrade(out=lambda line: None) == EXIT_OK
    assert schema_state.inspect_engine(engine).state == schema_state.CURRENT
    archives = full_backup.list_archives(tmp_path / "b" / "full")
    assert [a.trigger for a in archives] == ["pre-upgrade"]
    with zipfile.ZipFile(archives[0].path) as zf:
        assert json.loads(zf.read("manifest.json"))["database"]["revision"] == OLD_REVISION
