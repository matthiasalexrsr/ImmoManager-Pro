"""Actual additive platform migration, independent of metadata create_all."""

from alembic import command
from sqlalchemy import create_engine, inspect, text

from backend.db.schema_state import alembic_config


def test_platform_upgrade_preserves_existing_rows_and_declares_all_owned_tables(tmp_path):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    command.upgrade(alembic_config(url), "d73f2b9a041c")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO login_attempts(id,username,attempted_at,success) VALUES ('kept','synthetic','2026-01-01',0)"
            )
        )
        before = list(conn.execute(text("SELECT * FROM login_attempts")))
    engine.dispose()
    command.upgrade(alembic_config(url), "e160a1b2c314")
    engine = create_engine(url)
    with engine.connect() as conn:
        assert list(conn.execute(text("SELECT * FROM login_attempts"))) == before
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "e160a1b2c314"
        assert {"registration_quotas", "plugin_installations", "storage_bindings"}.issubset(
            inspect(conn).get_table_names()
        )
        assert {column["name"] for column in inspect(conn).get_columns("storage_bindings")} == {
            "storage_key",
            "bucket",
            "endpoint_hash",
            "sha256",
            "size_bytes",
            "deleted",
        }
    engine.dispose()
