# Database snapshot scheduler handoff

`scripts/backup_scheduler.py` creates **DATABASE-ONLY** snapshots. They contain
all SQLite tables, including authentication records. The `.db` file is not
encrypted. Attachments/uploads and external runtime configuration (`.env`, JWT
key and integration configuration) are excluded. These files are not a full
installation recovery archive.

Select the existing installation explicitly, including paths with spaces:

```powershell
.\.venv\Scripts\python.exe scripts\backup_scheduler.py info --data-dir 'C:\path with spaces\ImmoManagerPro'
.\.venv\Scripts\python.exe scripts\backup_scheduler.py run --data-dir 'C:\path with spaces\ImmoManagerPro' --timeout 300
.\.venv\Scripts\python.exe scripts\backup_scheduler.py cleanup --data-dir 'C:\path with spaces\ImmoManagerPro'
.\.venv\Scripts\python.exe scripts\backup_scheduler.py schedule --data-dir 'C:\path with spaces\ImmoManagerPro'
.\.venv\Scripts\python.exe scripts\backup_scheduler.py unschedule
```

With `--data-dir`, that installation's `.env` selects `DATABASE_URL` and
`BACKUP_DIR`; foreign ambient values are ignored. Relative paths are anchored to
the selected data directory. Missing databases, server databases, in-memory
SQLite and SQLite URI options fail. No alternate database or unauthenticated API
backup is attempted. Without `--data-dir`, the existing `DATA_DIR` and other
ambient settings remain supported; a scheduled command is refused if those
settings cannot be reproduced from the captured data directory and its `.env`.

SQLite's backup API includes committed WAL transactions and excludes open
transactions. It runs with a progress deadline, validates integrity and converts
the output to standalone DELETE journaling. A private file in the destination
directory is published atomically as
`database_snapshot_YYYYMMDD_HHMMSS_UUID.db` through a no-overwrite hard link.
The filesystem must support hard links, as NTFS does. Failure leaves existing
snapshots intact and removes the invocation's temporary files. A failed run,
cleanup or Windows task command returns a nonzero exit code. Task output and
configured database URLs are not echoed on errors, avoiding credential leaks.

Cleanup retains the last 30 days by file modification time and deletes only
regular files matching the exact new snapshot name or the legacy
`backup_YYYYMMDD_HHMMSS.db` name. It skips symbolic links/reparse points, unrelated
files, full recovery archives and the configured active database. Temporary files
from other invocations are not retention targets.

The daily Windows task runs at 02:00 and captures the project virtualenv Python
(or the running interpreter when no project virtualenv exists), absolute script
path, explicit data directory and timeout with Windows argument quoting. Task
registration/deletion is checked and bounded; no task was registered during
verification.

`info` also shows the full archive command provided by `backend.recovery`:

```powershell
.\.venv\Scripts\python.exe -m backend.recovery backup --offline --data-dir 'C:\path with spaces\ImmoManagerPro' --output 'C:\backup\full-recovery.immo'
```

Run that command from the project directory after stopping the application; the
recovery CLI prompts for the encryption password. Full recovery is a separate
service; the scheduler does not claim its database snapshots can replace it.

Verification uses only private synthetic files. Regression tests exercise actual
WAL snapshots and an exclusive-writer timeout, partial/corrupt/integrity failures,
publication collision/failure cleanup, owned retention with a real symlink,
explicit `.env` selection, actual CLI execution and mocked Windows task results.
