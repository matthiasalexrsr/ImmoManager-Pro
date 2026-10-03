"""Real schema/driver proofs: production startup never repairs or migrates SQL."""

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

ROOT = Path(__file__).resolve().parents[2]

START = r'''
import os
import sqlite3
from sqlalchemy import event
from sqlalchemy.engine import Engine

ddl = []
@event.listens_for(Engine, "before_cursor_execute")
def observe(connection, cursor, statement, parameters, context, many):
    if statement.lstrip().split(None, 1)[0].upper() in {"CREATE", "ALTER", "DROP", "REINDEX"}:
        ddl.append(statement.split(None, 1)[0])

@event.listens_for(Engine, "connect")
def deny_native_sqlite_ddl(connection, record):
    if not isinstance(connection, sqlite3.Connection):
        return
    denied = {getattr(sqlite3, name) for name in (
        "SQLITE_CREATE_INDEX", "SQLITE_CREATE_TABLE", "SQLITE_CREATE_TRIGGER", "SQLITE_CREATE_VIEW",
        "SQLITE_CREATE_TEMP_INDEX", "SQLITE_CREATE_TEMP_TABLE", "SQLITE_CREATE_TEMP_TRIGGER", "SQLITE_CREATE_TEMP_VIEW",
        "SQLITE_DROP_INDEX", "SQLITE_DROP_TABLE", "SQLITE_DROP_TRIGGER", "SQLITE_DROP_VIEW",
        "SQLITE_DROP_TEMP_INDEX", "SQLITE_DROP_TEMP_TABLE", "SQLITE_DROP_TEMP_TRIGGER", "SQLITE_DROP_TEMP_VIEW",
        "SQLITE_ALTER_TABLE", "SQLITE_REINDEX")}
    def authorizer(action, *values):
        if action in denied:
            ddl.append("native_sqlite_ddl")
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    connection.set_authorizer(authorizer)

try:
    from backend.app import app
    from fastapi.testclient import TestClient
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/health").json()["database_connected"] is True
    assert not os.environ.get("EXPECT_STARTUP_FAILURE"), "incompatible startup unexpectedly succeeded"
    from backend.db.session import create_tables
    try:
        create_tables()
    except RuntimeError as error:
        assert "explicit Alembic" in str(error)
    else:
        raise AssertionError("Production create_tables was not rejected")
    print("STARTUP_OK")
except RuntimeError as error:
    assert os.environ.get("EXPECT_STARTUP_FAILURE"), str(error)
    chain = []
    current = error
    while current is not None:
        chain.append(str(current))
        current = current.__cause__
    assert os.environ["EXPECT_STARTUP_FAILURE"] in " ".join(chain), "Wrong startup rejection"
    print("EXPECTED_STARTUP_REJECTION")
finally:
    assert not ddl, "Startup attempted schema DDL"
'''


def environment(tmp_path, url):
    values = {key: value for key, value in os.environ.items()
              if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "NUMBER_OF_PROCESSORS"}}
    values.update({"PYTHONPATH": str(ROOT), "PYTHONUTF8": "1", "DATABASE_URL": url,
        "ENVIRONMENT": "production", "SQLITE_PERSISTENT_STORE": "true", "ALLOW_INMEMORY_FALLBACK": "false",
        "AUTO_MIGRATE": "false", "AUTO_SEED_DEMO_DATA": "false", "AI_ENABLED": "false",
        "OPERATIONAL_SCHEDULER_ENABLED": "false", "PLUGIN_DIRS": "[]", "LOG_LEVEL": "CRITICAL",
        "CORS_ORIGINS": '["http://127.0.0.1"]', "TRUSTED_HOSTS": '["127.0.0.1"]',
        "JWT_SECRET_KEY": "synthetic-startup-key-with-no-business-data-" + "0" * 32,
        "DATA_DIR": str(tmp_path), "UPLOADS_DIR": str(tmp_path / "uploads"),
        "BACKUP_DIR": str(tmp_path / "backups"), "INTEGRATION_STATE_FILE": str(tmp_path / "integrations.json")})
    return values


def migrate(env):
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT,
        env={**env, "ENVIRONMENT": "development"}, capture_output=True, timeout=90)
    assert result.returncode == 0, "Owned test database could not be explicitly migrated"


def start(env):
    result = subprocess.run([sys.executable, "-c", START], cwd=ROOT, env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout


def catalog(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()


@pytest.fixture
def migrated_sqlite(tmp_path):
    path = tmp_path / "production.sqlite"
    env = environment(tmp_path, "sqlite:///" + path.as_posix())
    migrate(env)
    return path, env


def test_actual_production_import_and_lifespan_succeed_when_native_driver_denies_ddl(migrated_sqlite):
    path, env = migrated_sqlite
    before = catalog(path)
    assert "STARTUP_OK" in start(env)
    assert catalog(path) == before
    # The same exact schema can restart; no migration/configuration mutation is needed.
    assert "STARTUP_OK" in start(env)


@pytest.mark.parametrize("damage", ["revision", "unversioned", "table", "column", "measurement_guard"])
def test_production_refuses_schema_damage_without_repair(migrated_sqlite, damage):
    path, env = migrated_sqlite
    with sqlite3.connect(path) as db:
        if damage == "revision":
            db.execute("UPDATE alembic_version SET version_num='not-this-release'")
        elif damage == "unversioned":
            db.execute("DROP TABLE alembic_version")
        elif damage == "table":
            db.execute("DROP TABLE operational_job_lanes")
        elif damage == "measurement_guard":
            db.execute("DROP TRIGGER preserve_measurement_facts_update")
        else:
            db.execute("ALTER TABLE users DROP COLUMN totp_secret")
    before = catalog(path)
    failure = "migration revision" if damage in {"revision", "unversioned"} else "schema is incomplete"
    if damage == "measurement_guard":
        failure = "historical source schema or original protection"
    assert "EXPECTED_STARTUP_REJECTION" in start({**env, "EXPECT_STARTUP_FAILURE": failure})
    assert catalog(path) == before


def test_empty_production_database_is_not_implicitly_installed(tmp_path):
    path = tmp_path / "empty.sqlite"
    with sqlite3.connect(path):
        pass
    env = environment(tmp_path, "sqlite:///" + path.as_posix())
    assert "EXPECTED_STARTUP_REJECTION" in start({**env, "EXPECT_STARTUP_FAILURE": "migration revision"})
    assert catalog(path) == []


def test_production_auto_migrate_rejected_before_ddl(migrated_sqlite):
    path, env = migrated_sqlite
    before = catalog(path)
    assert "EXPECTED_STARTUP_REJECTION" in start({**env, "AUTO_MIGRATE": "true", "EXPECT_STARTUP_FAILURE": "AUTO_MIGRATE is enabled"})
    assert catalog(path) == before


def test_real_entrypoint_does_not_implicitly_run_available_migration(tmp_path):
    bash = shutil.which("bash")
    if not bash and os.name == "nt":
        bundled = Path("C:/Program Files/Git/bin/bash.exe")
        bash = str(bundled) if bundled.is_file() else None
    if not bash:
        pytest.skip("POSIX shell required for the real container entrypoint test")
    # The old entrypoint would invoke this real executable and fail, before the
    # requested command. Presence of alembic.ini must not enable migrations.
    (tmp_path / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    alembic = tmp_path / "alembic"
    alembic.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
    alembic.chmod(0o700)
    result = subprocess.run([bash, str(ROOT / "docker-entrypoint.sh"), "printf", "ENTRYPOINT_OK"],
        cwd=tmp_path, env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ.get("PATH", ""),
                           "AUTO_MIGRATE": "false", "TMPDIR": ""}, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0 and result.stdout == "ENTRYPOINT_OK", result.stderr


def test_postgres_production_starts_with_native_role_without_schema_ddl_privileges(tmp_path):
    source = os.environ.get("TEST_SERVER_DATABASE_URL")
    if not source:
        pytest.skip("TEST_SERVER_DATABASE_URL disposable PostgreSQL is required")
    if make_url(source).get_backend_name() != "postgresql":
        pytest.fail("TEST_SERVER_DATABASE_URL must be PostgreSQL")
    identity = "startup_" + uuid4().hex
    admin = create_engine(source, hide_parameters=True)
    try:
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{identity}"')
            connection.exec_driver_sql(f'CREATE ROLE "{identity}" NOLOGIN')
        env = {**environment(tmp_path, source), "PGOPTIONS": "-csearch_path=" + identity}
        migrate(env)
        with admin.begin() as connection:
            connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{identity}" TO "{identity}"')
            connection.exec_driver_sql(f'GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA "{identity}" TO "{identity}"')
            connection.exec_driver_sql(f'GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA "{identity}" TO "{identity}"')
        with admin.connect() as connection:
            connection.exec_driver_sql(f'SET ROLE "{identity}"')
            with pytest.raises(DBAPIError) as denied:
                connection.exec_driver_sql(f'CREATE TABLE "{identity}".must_not_exist(id integer)')
            assert getattr(denied.value.orig, "pgcode", None) == "42501"
            connection.rollback()
        # The actual app import/lifespan runs in another process with this role.
        assert "STARTUP_OK" in start({**env, "PGOPTIONS": env["PGOPTIONS"] + " -crole=" + identity})
    finally:
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{identity}" CASCADE')
            connection.exec_driver_sql(f'DROP ROLE IF EXISTS "{identity}"')
        admin.dispose()
