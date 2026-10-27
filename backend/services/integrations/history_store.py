"""Indexed integration journal; pages and aggregates never load the whole log."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from threading import RLock


class IntegrationHistoryStore:
    def __init__(self, file_path=":memory:"):
        self._path = file_path
        self._lock = RLock()
        self._memory = sqlite3.connect(":memory:", check_same_thread=False) if file_path == ":memory:" else None

    @contextmanager
    def _connection(self):
        with self._lock:
            if self._memory is None:
                Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            connection = None
            try:
                connection = self._memory or sqlite3.connect(self._path, timeout=10)
                connection.execute("CREATE TABLE IF NOT EXISTS integration_runs (sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, integration_id TEXT NOT NULL, success INTEGER NOT NULL, record TEXT NOT NULL)")
                connection.execute("CREATE INDEX IF NOT EXISTS ix_integration_runs_page ON integration_runs(integration_id, sequence DESC)")
                yield connection
                connection.commit()
            except sqlite3.Error as exc:
                if connection is not None:
                    connection.rollback()
                raise OSError("Integrationsjournal nicht verfügbar") from exc
            finally:
                if self._memory is None and connection is not None:
                    connection.close()

    @staticmethod
    def _serialize(record):
        data = asdict(record)
        data["created_at"] = record.created_at.isoformat()
        return json.dumps(data, ensure_ascii=False)

    def append(self, record):
        with self._connection() as connection:
            connection.execute("INSERT INTO integration_runs (id, integration_id, success, record) VALUES (?, ?, ?, ?)",
                               (record.id, record.integration_id, int(record.success), self._serialize(record)))

    def finish(self, record):
        with self._connection() as connection:
            connection.execute("UPDATE integration_runs SET success=?, record=? WHERE id=?",
                               (int(record.success), self._serialize(record), record.id))

    def list(self, integration_id, *, limit=20, skip=0):
        with self._connection() as connection:
            rows = connection.execute("SELECT record FROM integration_runs WHERE integration_id=? ORDER BY sequence DESC LIMIT ? OFFSET ?",
                                      (integration_id, limit, skip)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def count(self, integration_id):
        with self._connection() as connection:
            return connection.execute("SELECT COUNT(*) FROM integration_runs WHERE integration_id=?", (integration_id,)).fetchone()[0]

    def clear(self, integration_id):
        with self._connection() as connection:
            count = connection.execute("SELECT COUNT(*) FROM integration_runs WHERE integration_id=?", (integration_id,)).fetchone()[0]
            connection.execute("DELETE FROM integration_runs WHERE integration_id=?", (integration_id,))
        return count

    def metrics(self):
        with self._connection() as connection:
            total, successful = connection.execute("SELECT COUNT(*), COALESCE(SUM(success), 0) FROM integration_runs").fetchone()
        return total, successful
