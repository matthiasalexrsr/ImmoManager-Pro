"""Focused additive upgrade oracle, isolated from the application's test store."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_channel_migration_preserves_all_prior_rows_and_original_blobs(tmp_path):
    path = tmp_path / "channels-upgrade.db"
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "db" / "migrations"))
    config.attributes["database_url"] = "sqlite:///" + path.as_posix()
    script = ScriptDirectory.from_config(config)
    assert script.get_revision("e160a1b2c308").down_revision == "d73f2b9a041c"
    command.upgrade(config, "d73f2b9a041c")
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE channel_migration_oracle (id TEXT PRIMARY KEY, original BLOB, amount TEXT)")
        connection.execute(
            "INSERT INTO channel_migration_oracle VALUES (?,?,?)",
            ("original-1", b"%PDF-\x00\xffEXACT ORIGINAL", "90071992547409.91"),
        )
        connection.commit()
        tables = [
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if row[0] != "alembic_version"
        ]
        before = {name: connection.execute('SELECT * FROM "' + name + '"').fetchall() for name in tables}
    command.upgrade(config, "e160a1b2c308")
    with sqlite3.connect(path) as connection:
        after = {name: connection.execute('SELECT * FROM "' + name + '"').fetchall() for name in tables}
        assert after == before
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("e160a1b2c308",)
        required = {
            "channel_cases": {
                "entity_type",
                "entity_id",
                "source_sha256",
                "snapshot_token",
                "progress_token",
                "revision",
            },
            "channel_evidence": {"data_token", "sha256", "case_id", "sequence"},
            "channel_events": {"replay_hash", "data_token"},
            "channel_webhooks": {"raw_token", "sha256"},
        }
        for name, columns in required.items():
            assert columns <= {row[1] for row in connection.execute('PRAGMA table_info("' + name + '")')}
