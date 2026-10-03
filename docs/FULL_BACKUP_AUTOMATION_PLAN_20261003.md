# L: automatic complete backups and isolated restore exercises

Plan recorded before source edits. Base `0b8763434f8fc9c0f93953ed8e9408f915d5f5eb`.
Own checkout `work/full-backup-automation`, branch `assist/full-backup-automation`.
Root owns current app startup/settings/HistoryRuntime and central recovery hooks.
Neither a live installation nor a private database is part of testing.

## Actual reusable components and gaps

- `backend/services/full_recovery.py:create_full_backup` already encrypts SQLite,
  uploads, runtime configuration and integration state; verifies database, file
  references, encryption keys and source fingerprints. `offline=True` is only a
  caller assertion. An automatic caller needs a real managed process stop and
  a writer/startup fence before it may assert this.
- `restore_full_backup` restores to a new directory, verifies the actual image,
  rebases file paths and invalidates restored security/job claims. It does not
  start a server and is suitable for a genuinely isolated SQLite exercise.
- `backend/recovery.py:_plan` reads the selected installation's exact persisted
  configuration without needing its web server. Reuse that selection logic;
  no process-wide application settings or guessed fallback database.
- `scripts/private_server_backup.py:backup` stops the app, waits for PostgreSQL
  clients, exports database and app volume, authenticates the complete archive,
  then restarts the app in finally. A killed runner loses the restart obligation.
- That module's `restore` always starts the restored app using the original
  port/origin after its security step. A concurrent probe must have a separate
  explicitly portless path and must never reach that app-start operation.
- `scripts/backup_scheduler.py` schedules unencrypted database-only snapshots
  with a global Windows task name. Keep those truthful existing semantics;
  expose complete-backup automation as an independently named capability.

## Ownership and implementation packets

1. New pure backup-plan/schedule types, private atomic plan/run files and OS file
   locks. No application database migration or secrets in plan/status output.
2. New managed SQLite runtime/control module and external runner. A separate,
   reviewable startup hook is supplied to Root; existing arbitrary processes are
   never killed/adopted by PID guess or an OFFLINE flag. A managed process must
   acknowledge its exact installation/run identity, drain its server/background
   workers, and release its lifetime lock. The runner then acquires that lock
   and a SQLite write reservation for the archive interval. All supported
   launch paths must use the same startup fence before publication is enabled.
3. Reuse actual encrypted full-backup functions. Add small lifecycle callbacks
   to the Docker backup path separately so restart obligation is durable before
   stopping the app and is cleared only after verified restart. After a runner
   crash the next invocation first discharges that exact obligation.
4. Add isolated SQLite and Docker/PostgreSQL restore probes. Keep existing
   ordinary restore semantics unchanged. Docker restore internals may be
   factored in a separate patch, but central recovery/session/history validation
   remains owned by Root and the existing backend assistant.
5. CLI/task/service deployment integration, capacity and retention controls,
   concrete operating instructions, focused native tests and mandatory real
   Docker lifecycle CI. No mocked Docker result qualifies as deployment proof.

## Persisted plan and run contract

- One immutable UUID installation/plan identity; absolute selected paths and
  an explicit backend (`sqlite` or `private_server`). Bind startup/compose
  identity to that installation. Updating a plan uses its current revision;
  two runners never execute the same plan concurrently.
- Defaults: one complete backup daily; one restore exercise monthly. Timezone
  and local run time are explicit. A DST fold cannot duplicate a period; a
  missing local time runs at the first later opportunity. A missed day causes
  one current complete backup, not invented historical snapshots.
- Primary destination is required; second destination is optional. Retention,
  archive/metadata/file/time budgets and retry cadence are configurable positive
  policies. No total-data or lifetime-record cap is introduced.
- Plans contain secret references only. Passphrases enter through an interactive
  prompt/stdin or a verified private file, never argv, environment dumps, status
  JSON or journal errors. Older key references remain usable while an archive
  protected by that key is retained. Missing/unreadable keys fail before downtime.
- An OS-owned lock, not a PID age, owns an invocation. Each run has atomic state:
  prepared -> restart_obligation -> offline -> archive_published -> app_resumed
  -> replicated -> complete. The exact restart obligation is persisted before
  stop, including whether the app was actually running. Archive success and app
  restart success are distinct facts; a restart failure cannot be green.
- Failed work records a fixed actionable code and retains the original error
  class privately without credentials. Retrying is a normal supported action;
  no manual deletion of locks, guessed process adoption or reset of receipts.
- Publish archives/replicas exclusively after verification and a complete fsync.
  A failed secondary copy is visible and repeatable without another source
  shutdown. Never overwrite an existing archive or claim a replica exists until
  its authenticated bytes/checksum match the published primary.
- Retention only handles this plan's recorded regular files and exact ownership
  identity. Protect the latest complete backup and latest successfully restored
  archive. Do not follow links/reparse points or clean unrelated files. Cleanup
  failure does not retroactively invalidate a good archive, but remains visible.

## Restore isolation and failure recovery

SQLite probes restore into a new private owned workspace, open and inspect the
actual restored database, verify declared files and retained/security state,
record the result, then remove only that exact owned workspace. No web app,
network connector, email worker or original path is activated.

Docker probes use a fresh UUID project, its own guard/container/volumes and an
internal network. Validate the archived original Compose fingerprint before
deriving a private probe profile. The derived profile has no published ports,
no original origin and no external/shared volumes; only database and explicit
offline maintenance commands run. Application scheduler/adapters never start.
Restore database and files, perform the actual retained/security validation and
record evidence before destroying only the exact owned probe resources.
An interrupted/failed probe has durable ownership metadata so cleanup/retry can
be performed without touching the original project. A failed validation never
qualifies an archive as restore-tested.

## Required evidence

- Real native OS lock contention and killed worker recovery, including the
  stop-before-journal/stop-after-journal boundaries and verified restart after an
  archive/space/key error. Foreign/mismatched processes are refused.
- A real synthetic SQLite application/writer is stopped, an encrypted complete
  archive is created, the app is restarted, and a new directory is restored.
  Assertions cover uploads, domain data, auth/signing/key behavior and no server
  listener created by the restore exercise. Active concurrent writers/startups
  cannot cross the offline publication interval.
- Actual private-file permissions on Windows; passphrases absent from argv,
  journal/status and logs. Wrong/missing key, corrupted/truncated archive,
  interrupted publication/replication and missing destination remain retryable.
- Schedule/DST/restart catch-up, two plans/installations without task-name
  collision, replica verification and retention preserving the latest restored
  archive. Cleanup refuses foreign links and replacement ownership.
- Native PostgreSQL validation uses only UUID synthetic schemas on the shared
  test service. Full portless Docker/volume lifecycle is additionally mandatory
  in CI with an actual daemon; this machine currently has no Docker CLI, so no
  local Docker success will be claimed.
- Root composition runs existing full-recovery/HistoryRuntime suites and exact
  startup hooks. Business data, live preview and existing backups stay untouched.
