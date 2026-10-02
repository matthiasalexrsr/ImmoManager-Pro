"""Demonstration metadata never promises nonexistent original upload files."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from backend.services.full_recovery import RecoveryPlan, create_full_backup, restore_full_backup


def test_fresh_real_demo_has_recoverable_documents_and_retains_all_metadata(tmp_path):
    source = tmp_path / "demo"
    uploads = source / "uploads"
    uploads.mkdir(parents=True)
    database = source / "demo.sqlite"
    code = '''
import json
from pathlib import Path
from seed_data import seed
from backend.config import settings
seed()
values = {key.upper(): value if isinstance(value, str) else json.dumps(value)
          for key, value in settings.model_dump(mode="json").items() if value is not None}
Path(settings.data_dir, "settings.json").write_text(json.dumps(values), encoding="utf-8")
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
        cwd=Path(__file__).resolve().parents[2], env={**os.environ,
        "DATA_DIR": str(source), "UPLOADS_DIR": str(uploads), "DATABASE_URL": "sqlite:///" + database.as_posix(),
        "SQLITE_PERSISTENT_STORE": "true", "ALLOW_INMEMORY_FALLBACK": "false",
        "AUTO_SEED_DEMO_DATA": "false", "AI_ENABLED": "false", "CONTRACT_WIZARD_REQUIRED": "false"})
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as db:
        original = db.execute("SELECT title,document_type,document_date,file_url FROM documents ORDER BY id").fetchall()
    assert len(original) == 10 and all(row[3] == "" for row in original)
    values = json.loads((source / "settings.json").read_text(encoding="utf-8"))
    plan = RecoveryPlan(database, uploads, values)
    archive = tmp_path / "demo.immobak"
    password = "Synthetic-Demo-Recovery-Passphrase-2026"
    create_full_backup(plan, archive, password, offline=True)
    restored = tmp_path / "restored"
    restore_full_backup(archive, restored, password)
    with sqlite3.connect(restored / "database.sqlite3") as db:
        actual = db.execute("SELECT title,document_type,document_date,file_url FROM documents ORDER BY id").fetchall()
        assert actual == original
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
