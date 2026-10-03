# L: central startup and full-backup composition

Implemented against Root `4ef814c`, following the committed startup plan.
The private Release-126 preview and database were not used or changed.

The app and direct dependencies now acquire the shared pure SQLite import
fence before settings, auth, SQL, logging or workers can initialize. Direct
ASGI retains its native installation lease for the process lifetime. The
existing lifespan runs under the matching configuration fence; managed
launchers retain ownership until the entire lifespan and process have ended.

`backend.recovery run` now uses the same authenticated managed runtime as the
normal launcher, before loading recovered settings. Manual offline backup
takes that installation lease before planning and holds a real SQLite write
reservation throughout archiving. A missing database is never created by this
command. Active installation/writer errors identify the recoverable next step.
The runtime control directory is ephemeral private state and is ignored by Git.

## Actual evidence

- `full-backup-startup-composed-recheck.log`: all four native central-entry
  cases passed, 30.37 seconds. Includes actual separate-process app/dependencies
  imports rejected before settings/SQL/logging, held-installation manual backup
  refusal with unchanged database bytes, and a real restored complete
  installation serving health then stopping by authenticated process identity.
  Its port, kernel lease, native FK check and original upload bytes are verified.
- `full-backup-startup-cleanup-recheck.log`: the real restored runtime case
  passed again, 21.40 seconds, after strengthening failed-test cleanup to stop
  the authenticated child interpreter before considering its own launcher.
- Ruff passed for all six touched product/test files; Mypy passed for the
  maintenance entrypoint and pure application boundary.

The initial run had two passing import cases and two fixture failures: an
ephemeral copied control directory had a different Windows ACL, and a Windows
venv launcher PID was incorrectly equated with its child interpreter PID.
The fixture now excludes ephemeral runtime state and verifies the recorded
native process birth identity. These failed attempts are not success evidence.
A subsequent ownership check found no remaining synthetic recovery-run process.

## Remaining common gates

Existing automatic-runner, interruption/replica/restore suites must still be
composed with newer journal/schema packets on Root. A real PostgreSQL Docker
restore probe remains unexecuted on this host, which has no Docker daemon.
Direct ASGI is safely excluded from offline backup but has no invented control
channel. No automatic policy was installed for the user's private installation.
Common A–L release, large-history performance and controlled rollout remain open.
