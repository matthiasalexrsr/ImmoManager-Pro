# Windows starter and offline updater

The starter now hashes dependency files and the virtual interpreter version.
Every venv/pip step must succeed before an install stamp is written. Frontend
freshness uses source, public assets, lockfile, build configuration and locale
content. Builds install dev dependencies, write to an owned staging directory,
validate files and checksums, then promote the complete result. A failed npm
install/build preserves the previous UI. Fresh restarts avoid npm entirely.
`-SkipFrontendBuild` validates the existing compiled assets instead of silently
starting with a missing UI.

Updates cannot run through the live server: `/updates/check` exposes
`live_apply_supported: false`; live apply requests return an offline maintenance
reason before mutation. Stop the application first, then run from its checkout:

```powershell
.\.venv\Scripts\python.exe -m backend.maintenance --offline --data-dir "$env:LOCALAPPDATA\ImmoManagerPro" --port 8000
```

Use the actual existing data directory and server port. Optional
`--target-version 1.2.0` selects a version tag. The CLI refuses a listening port,
loads the selected installation's runtime configuration, and returns a nonzero
exit code for failure. This is an explicit offline operation; it must not be run
while another server/background writer is using that installation on another
port. No actual update or user-database operation was performed during development.

The updater uses the configured backup directory and data directory's `.updates`
folder. SQLite snapshots include committed WAL data through `sqlite3.backup`,
with integrity and checksum verification. Restore uses the same API and refuses
live restoration. Git/dependency/UI rollback reports whether recovery really
completed. Failed dependency recovery never reports startup readiness. If UI
restoration fails, its previous compiled files remain in the reported
`.updates/frontend-before-*` directory for recovery. A held update lock is never
stolen based on age alone; remove an abandoned lock only after confirming its
process has stopped.

Integration still required with the separate full-recovery service: replace the
pre-update subset JSON export with its password-encrypted database/uploads/runtime
archive and request the passphrase interactively. The present updater's JSON file
is a logical export, and its SQLite snapshot is database-only. PostgreSQL full
recovery is not supplied by this package. Connect the scheduler separately; this
package does not alter its raw-copy fallback.

Validation: 53 isolated launcher/build/updater/CLI regression cases passed;
an actual npm ci + Vite production build promoted successfully, compiled assets
validated, and the next run skipped the build using its content fingerprint.
Scoped application/repository mypy passed. No dependency, authentication,
financial/import, frontend-component or scheduler files changed.
