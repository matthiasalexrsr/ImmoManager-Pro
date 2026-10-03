"""Host-private durable receipts, independent of the database being backed up."""

import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from scripts.private_server_backup import _safe_path, protected_new_file

from .plan import BackupOperationError


class Journal:
    def __init__(self, directory):
        path = directory / "journal.sqlite3"
        if not path.exists():
            try:
                with protected_new_file(path):
                    pass
            except FileExistsError:
                pass
        _safe_path(path)
        self.database = sqlite3.connect(path, timeout=30)
        self.database.row_factory = sqlite3.Row
        self.database.execute("PRAGMA journal_mode=DELETE")
        self.database.execute("PRAGMA synchronous=FULL")
        self.database.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, period TEXT NOT NULL,
                created TEXT NOT NULL, updated TEXT NOT NULL, status TEXT NOT NULL,
                retry_at TEXT, error TEXT, document TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS backup_runs_status ON runs(status, created, id);
            CREATE INDEX IF NOT EXISTS backup_runs_period ON runs(kind, status, period);
            CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.database.close()

    @staticmethod
    def unpack(row):
        return {**dict(row), "document": json.loads(row["document"])} if row else None

    def new(self, plan, kind, period, now):
        run_id = str(uuid4())
        item = {"id": run_id, "kind": kind, "period": period,
                "created": now.isoformat(), "updated": now.isoformat(), "status": "pending",
                "retry_at": None, "error": None,
                "document": {"plan_id": str(plan.id), "installation": plan.installation.model_dump(mode="json"),
                             "key_id": plan.key_id, "plan_revision": plan.revision,
                             "archive": str(plan.destination / (run_id + ".immobak")),
                             "secondary": str(plan.second_destination / (run_id + ".immobak")) if plan.second_destination else None,
                             "phase": "prepared"}}
        self.save(item, new=True)
        return item

    def save(self, item, *, new=False):
        item["updated"] = datetime.now(timezone.utc).isoformat()
        values = {**item, "document": json.dumps(item["document"], sort_keys=True, separators=(",", ":"), allow_nan=False)}
        with self.database:
            if new:
                self.database.execute("""INSERT INTO runs VALUES
                    (:id,:kind,:period,:created,:updated,:status,:retry_at,:error,:document)""", values)
            elif self.database.execute("""UPDATE runs SET updated=:updated, status=:status,
                    retry_at=:retry_at, error=:error, document=:document WHERE id=:id""", values).rowcount != 1:
                raise BackupOperationError("backup_run_missing")

    def unfinished(self):
        cursor = self.database.execute("SELECT * FROM runs WHERE status NOT IN ('complete','retired') ORDER BY created,id")
        for row in cursor:
            yield self.unpack(row)

    def latest(self, kind):
        return self.unpack(self.database.execute("SELECT * FROM runs WHERE kind=? AND status='complete' ORDER BY created DESC,id DESC LIMIT 1", (kind,)).fetchone())

    def get(self, run_id):
        return self.unpack(self.database.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())

    def retained_keys(self):
        return {json.loads(row[0])["key_id"] for row in self.database.execute("SELECT document FROM runs WHERE status!='retired'")}

    def retire_candidates(self, cutoff, protected):
        for row in self.database.execute("SELECT * FROM runs WHERE kind='backup' AND status='complete' AND created<? ORDER BY created,id", (cutoff,)):
            if row["id"] not in protected:
                yield self.unpack(row)

    def recent(self, count=20):
        return [self.unpack(row) for row in self.database.execute("SELECT * FROM runs ORDER BY created DESC,id DESC LIMIT ?", (count,))]

    def metadata(self, name, value):
        with self.database:
            self.database.execute("INSERT INTO metadata VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                                  (name, json.dumps(value, separators=(",", ":"), allow_nan=False)))

    def get_metadata(self, name):
        row = self.database.execute("SELECT value FROM metadata WHERE name=?", (name,)).fetchone()
        return json.loads(row[0]) if row else None
