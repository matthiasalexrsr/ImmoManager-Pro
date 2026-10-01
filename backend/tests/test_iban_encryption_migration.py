"""Real m1 schema operations do not erase old plaintext or ciphertext."""

from importlib import import_module

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

migration = import_module("backend.db.migrations.versions.m1a2b3c4d5e6_stable_account_encryption")


def test_upgrade_leaves_legacy_values_and_supports_empty_down_up(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "schema.db").as_posix())
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE accounts (id VARCHAR PRIMARY KEY, iban VARCHAR(64))"))
            connection.execute(text("INSERT INTO accounts VALUES ('legacy', 'synthetic-plain')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                assert connection.execute(text("SELECT id, iban, iban_fingerprint FROM accounts")).one() == (
                    "legacy",
                    "synthetic-plain",
                    None,
                )
                assert (
                    str(next(c for c in inspect(connection).get_columns("accounts") if c["name"] == "iban")["type"])
                    == "TEXT"
                )
                plan = connection.execute(
                    text(
                        "EXPLAIN QUERY PLAN SELECT 1 FROM accounts WHERE iban IS NOT NULL "
                        "AND iban != '' AND iban_fingerprint IS NULL LIMIT 1"
                    )
                ).fetchall()
                assert any("ix_accounts_iban_unindexed" in row[3] for row in plan), plan
                migration.downgrade()
                assert "ix_accounts_iban_unindexed" not in {
                    index["name"] for index in inspect(connection).get_indexes("accounts")
                }
                migration.upgrade()
            assert connection.execute(text("SELECT id, iban, iban_fingerprint FROM accounts")).one() == (
                "legacy",
                "synthetic-plain",
                None,
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("iban,fingerprint", [("enc:v1:old:synthetic", None), ("plain", "a" * 64)])
def test_downgrade_guard_runs_before_any_drop(iban, fingerprint, tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "guard.db").as_posix())
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE accounts (id VARCHAR PRIMARY KEY, iban TEXT)"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            connection.execute(
                text("INSERT INTO accounts VALUES ('proof', :iban, :fingerprint)"),
                dict(iban=iban, fingerprint=fingerprint),
            )
            before_schema = connection.execute(text("SELECT name, sql FROM sqlite_master ORDER BY name")).fetchall()
            with (
                Operations.context(MigrationContext.configure(connection)),
                pytest.raises(RuntimeError, match="downgrade refused"),
            ):
                migration.downgrade()
            assert (
                connection.execute(text("SELECT name, sql FROM sqlite_master ORDER BY name")).fetchall()
                == before_schema
            )
            assert connection.execute(text("SELECT * FROM accounts")).one() == ("proof", iban, fingerprint)
    finally:
        engine.dispose()
