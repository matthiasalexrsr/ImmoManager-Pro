# Complete backup automation: implementation and integration handoff

Own checkout `work/full-backup-automation`, base `0b87634`. No live data, preview,
existing backup, Windows task or Docker project was changed during development.
This package has no application-database migration. Its private SQLite journal
is separate from the installation being backed up.

## Implemented behavior

`python -m backend.backup_operations` is an external controller. Its default
plan makes an encrypted complete backup daily at 02:15 and performs an actual
isolated restore monthly at 03:30 in Europe/Berlin. The host scheduler polls every
15 minutes; calendar decisions use the plan's timezone. A DST fold cannot repeat
a completed period; a missing local wall-clock time runs at the next valid
opportunity. Missed periods create one current image, not historical snapshots.

Plans have an immutable UUID/installation binding, optimistic revisions, private
key-file references, primary/optional second destination, retention policy,
capacity profile and retry cadence. A kernel-owned file lock serializes workers.
The private durable journal records the phase, error code, retry time and exact
restart or probe-cleanup obligation. `status` reports the safe summary and never
returns runtime control tokens, environment values or passphrases.

Before stopping a managed SQLite application, the runner commits its exact
instance, launch/configuration identity and process creation witness. It requests
authenticated local shutdown, waits on the original native process object, then
acquires the installation lifetime lease and a SQLite `BEGIN IMMEDIATE` write
reservation. Only then does it call the existing complete archive service with
`offline=True`. The original process cannot be replaced by a guessed PID or
force-killed. A direct unmanaged ASGI process is fenced and blocks publication;
it does not gain a guessed control interface.

The archive contains every database table, uploads, runtime configuration and
integration state. The existing recovery service validates actual database,
immutable evidence, files, references and encryption keys. Archives and replicas
are flushed and published exclusively, without replacing an existing file.
An interrupted publication is adopted only after authentication and actual
isolated restore. A failed replica is retried using the existing archive without
another source shutdown. Retention handles only recorded exact regular-file
identities and authenticated bytes. It protects the latest complete backup,
latest successfully restored archive and archives used by pending probes.
Cleanup failure remains visible without changing a good archive's result.

A persisted restart obligation is discharged before new work, even when the plan
has since been disabled. Missing/unreadable keys fail before new downtime.
Readiness and the saved configuration/host/port must match before restart is
declared successful. No raw configuration or subprocess exception is logged.

## Required Root startup composition

`backend/__main__.py` already enters `ManagedRuntime` before runtime configuration
or application imports. The final separate hook dispatches
`ImmoManager.exe --backup-operations ...` before GUI configuration, log creation
and app-port binding. Source distributions use `python -m backend.backup_operations`.

Root must compose the central ASGI module as follows **before enabling automatic
publication in a real installation**. This checkout intentionally leaves
`backend/app.py` and `backend/recovery.py` to their existing Root owner.

Before the first relative `auth`, `config`, `dependencies`, routing or plugin
import in `backend/app.py`, acquire the pure import fence:

```python
from .backup_operations.runtime import application_import_fence, application_startup_fence

_application_import_lease = application_import_fence()
```

`application_import_fence(*, data_dir=None, database_url=None)` reads the same
case-insensitive ambient environment and current `.env` without constructing the
configuration singleton. Source default data selection is the repository root;
frozen default selection matches the per-user data directory. PostgreSQL returns
`None`. A managed launcher reuses its already acquired runtime lease. Direct
SQLite imports acquire the kernel lease and retain it for the process lifetime,
including import-only starts. Do not close/release that receipt after import.

Wrap the existing async lifespan, including all startup validation, background
workers and their complete shutdown, in `application_startup_fence(settings)`.
For example, preserve the existing implementation as `_application_lifespan`:

```python
@asynccontextmanager
async def lifespan(app):
    with application_startup_fence(settings):
        async with _application_lifespan(app):
            yield
```

The wrapper validates that imported settings select the fenced installation. The
existing managed runtime or direct import fence remains its owner. A lifespan-only
lock is insufficient: dependencies can already initialize writers during import.
Root should test the actual central module under an offline lease and assert no
configuration/database/log/background writer is reached.

For `backend.recovery run`, enter `ManagedRuntime(args.data_dir, app_root=the
selected source/executable root, host="127.0.0.1", port=args.port)` **before**
`load_recovered_environment` or application imports. After the recovered settings
are selected, call `runtime.bind_configuration(settings)` and `runtime.run(app)`.
The returned lifespan must remain inside that context until every worker stops.
This makes recovery-run a genuinely controlled launch path. Arbitrary direct ASGI
starts remain excluded rather than silently adopted by the backup controller.

## Private-server path and isolation

The existing private-server `backup` and normal `restore` behavior is preserved.
An optional `lifecycle(stage, receipt)` callback provides `prepared`, `offline`,
`published`, `resumed`. `prepared` commits exact daemon container IDs/creation
identities and original Compose/environment fingerprints before the first stop.
The callback may fail to persist; then no stop is issued. A resume obligation is
cleared only after actual `up --wait` application health and running verification.
Recovery refuses changed profiles, environments or replaced original containers.

Automated server archives add a backward-compatible authenticated source table
inventory (all row counts and a schema fingerprint). Older four-member archives
remain readable. No application schema or source business record is changed.

`probe_restore` is a distinct portless path. It authenticates the archived original
Compose hash before deriving a private profile. A fresh UUID project and ownership
token label its guard, containers, volumes, network and image. The profile has no
published ports, external/bind volumes, source origin or original PostgreSQL/JWT
credentials; its network is internal. Its app entrypoint is `/bin/false`; only
explicit `tar` and offline Python commands run. Schedulers/plugins/AI are disabled.

The probe actually restores the dump and app data, uses the existing immutable
evidence/key/session validation, compares all source row counts/schema and every
extracted file's bytes, then removes only inspected token-owned objects. The
cleanup receipt is persisted before resource creation and survives worker death.
A later run first inspects/cleans that exact project. Foreign resources prevent
cleanup; the original project is never used as a cleanup target. Normal restore
still starts its requested new application with its original behavior.

## Evidence and remaining gates

- First native focused run: 9 passed / 35.73 seconds. Two new E2E setup errors
  were the test shim's missing source search path; fixed before the native recheck.
- Two actual SQLite/Uvicorn E2E cases: 2 passed / 66.13 seconds. They cover complete
  domain/archive/upload restore, stop-before-publication, authenticated resume,
  monthly portless exercise, missing key before downtime, replica error/retry
  without another stop, and `os._exit(19)` after durable stop followed by restart
  even under a disabled plan.
- CLI/native-runtime/legacy-server/contracts regression: 94 passed / 167 seconds,
  no skips. No task was registered. Docker contract tests are deliberately labeled
  as contracts and do not prove a daemon lifecycle.
- Latest early launcher/direct-import-fence/CLI checks: 4 passed / 6.13 seconds.
  The native Windows Task Scheduler parsed the generated XML into an unregistered
  task definition successfully. Script execution policy was left unchanged.
- Final replica recovery uses a persisted exact staging-file identity. The real
  archive/replica/resume/restore recheck passed / 28.90 seconds; owned-retention and
  foreign-staging replacement refusal passed 2 cases / 5.92 seconds. A replacement
  file survives unchanged. Static compilation, import sorting and source whitespace
  validation pass.
- `scripts/private_server_smoke.py`, already invoked by the required private-server
  CI job, now performs the actual portless UUID-project exercise while the source
  application remains running, verifies inventory/files/session behavior, and
  checks the owned probe containers are removed.

This host has no Docker CLI/daemon, so the expanded real Docker CI smoke has **not
run locally**. An exact integrated Root startup/recovery gate and a successful
real Docker CI run remain required for deployment. The package must not be called
an already deployed or fully composed L completion until those gates succeed.

## Operator commands

All selections below are absolute examples. Use the installation's executable
root, data directory and interpreter; keep the key separate from archive storage.
No schedule is registered by `init` or `run`.

```powershell
python -m backend.backup_operations key-new --key-file 'C:\PrivateBackup\full-key.txt'
python -m backend.backup_operations init --plan-dir 'C:\PrivateBackup\plan' --app-root 'C:\ImmoManagerSource' --python 'C:\ImmoManagerSource\.venv\Scripts\python.exe' --data-dir 'C:\PrivateData\ImmoManagerPro' --destination 'D:\EncryptedBackups' --second-destination 'E:\EncryptedBackups' --key-file 'C:\PrivateBackup\full-key.txt'
python -m backend.backup_operations run --plan-dir 'C:\PrivateBackup\plan' --force backup
python -m backend.backup_operations run --plan-dir 'C:\PrivateBackup\plan' --force probe
python -m backend.backup_operations status --plan-dir 'C:\PrivateBackup\plan'
python -m backend.backup_operations schedule --plan-dir 'C:\PrivateBackup\plan'
python -m backend.backup_operations unschedule --plan-dir 'C:\PrivateBackup\plan'
```

For a frozen installation use `ImmoManager.exe --backup-operations` in place of
`python -m backend.backup_operations`, `--packaged`, and `--python` pointing to
that exact executable. Frozen restart launches that executable directly.

Windows task registration uses an installation-UUID task name, properly quoted
arguments and the captured working directory. It runs under the current signed-in
user without requesting/storing a Windows password. This profile runs while that
user is signed in; an unattended service account is a separate deployment choice
requiring its own private-file access. It does not change other installations'
tasks. For Linux, `timer-files --output /absolute/new-private-directory` writes
reviewable per-plan `.service`/`.timer` files without installing them. Install the
files in that same user's systemd user unit directory and enable the generated
timer. A poll's exit code is nonzero when work/resume/cleanup requires attention.

Use `init --backend private_server --project EXISTING --compose-file ABSOLUTE
--env-file ABSOLUTE` in place of `--data-dir` for a selected private server.
`--capacity-file`, `--retention-days`, timezone and the second destination are
configurable at init. To change a saved plan, provide its full private JSON
definition with unchanged UUID/installation, revision incremented by one and
`configure --definition FILE --expected-revision OLD_REVISION`. Disable scheduling
with `enabled:false`; persisted resume/cleanup obligations still run. Keep all
existing key IDs/references when rotating to a new key, so retained archives and
pending restore probes remain recoverable. Do not remove lock files or reset the
journal to recover a failed operation; correct the fixed reported error and run
again. Keep the private plan/journal/key files protected and separately backed up.
