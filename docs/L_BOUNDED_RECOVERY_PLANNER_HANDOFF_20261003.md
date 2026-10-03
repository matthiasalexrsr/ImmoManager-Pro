# L: bounded explicit recovery planner handoff

Clean isolated checkout `work/bounded-recovery-planner`, branch
`assist/bounded-recovery-planner`, starting Root source `58aaf3e`.

Commits, in order:

- `262dff4`: pre-code profile, compatibility and test plan.
- `ea8f96f`: bounded planner, optional composition and own pure tests.
- `a6cc541`: actual Windows stat-API timestamp correction and one regression.
- This document records evidence; it changes no product source.

Only product edits are `backend/recovery.py` and the optional forwarding
signature/body of `backend/legacy_sqlite_upgrade/service.py::_selected`.
Root's integration-state maintenance service, startup/factory/schema/auth,
settings, CI and all original/private installations remain untouched.

## Exact APIs and profile behavior

```python
_plan(args, *, limits: RecoveryLimits | None = None, deadline: float | None = None)
_offline_backup(args, *, limits: RecoveryLimits | None = None,
                deadline: float | None = None)
legacy_sqlite_upgrade.service._selected(args, root, *, limits=None, deadline=None)
```

Without explicit limits the actual `RecoveryLimits()` defaults apply: 16 MiB
metadata, 4 GiB file, 300 seconds. Both optional `.env` and `configuration.json`
sources have `min(metadata_bytes, file_bytes)` as their per-file byte budget.
Higher positive profiles are supported without a further fixed 16 MiB ceiling.
The deadline is monotonic, finite and either preserved from the caller or derived
once at planner entry. Checks run before source work, during each bounded read,
before/after dotenv and strict JSON parsing/validation, around ExplicitSettings
construction and at the completed-plan boundary.

The helper `_configuration_bytes(path, maximum, deadline)` returns captured bytes
or `None` only for an initially absent optional file. It checks a regular
single-link file, actual opened descriptor versus named identity, size and mtime;
reads in at most 1 MiB chunks with at most one overflow byte; and validates both
descriptor and name again. Oversized, changed, nonregular or unreadable sources
raise fixed RecoveryError text without configuration values. No source file is
written and no database is opened by selection.

The bounded UTF-8 TextIOWrapper retains ordinary file universal-newline behavior;
`dotenv_values(stream=..., interpolate=False)` retains quoting, duplicate-key
last-value and literal `${...}` behavior. Existing `_json`/`_configuration` retain
strict JSON validation and precedence over dotenv values. ExplicitSettings
continues to use only stored selected-installation values; no ambient secret,
database URL or field key enters the plan.

Recovery backup CLI now passes its already loaded profile and one deadline through
the fenced selector, then gives actual full-backup creation only the remaining
time. Existing installation lease and SQLite writer code remain structurally in
place. Optional legacy selector calls without keywords retain default behavior;
existing legacy upgrade/status/return caller bodies were not expanded in this
narrow packet.

Root integration must forward its chosen profile/deadline through every fresh
maintenance selection, including publication callbacks:

```python
plan = legacy_select(args, root, limits=limits, deadline=deadline)
```

Root owns the accompanying `_selected`, `_assert_binding`, `_configuration_files`
and wrapper-fixture signature edits. Its pre-parse fingerprint reads must also
respect the selected source-byte budget before reading oversized files; merely
passing the budget after an earlier full-file hash is insufficient for the stated
all-reads profile boundary. Keep the existing parse-before/after and publication
freshness checks. Root may separately choose to forward already loaded profiles
from older legacy command callers; the new optional selector API supports that.

## Actual verification and corrected first result

Interpreter for every run:
`C:/Users/matth/Documents/Codex/2026-10-01/wi/outputs/ImmoManager-Pro/.venv/Scripts/python.exe`.

First pure run on `ea8f96f`: **35 passed, 4 failed, 1.89 s**, exit 1. The four
failures exposed a product error comparing Windows lstat ctime directly to fstat
ctime. A separate synthetic local-file observation reproduced differing ctime
values while dev/ino/size/mtime and repeated named lstat stayed identical. The
fix compares native dev/ino/size/mtime across APIs and retains ctime checks
separately within lstat-before/after and fstat-before/after. It adds no tolerance,
retry, fake stat or weakened file identity check. One real portable file test
gives creation/modification different timestamps and proves normal readability.

On frozen corrected product/test source `a6cc541`, the actual command was:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& 'C:/Users/matth/Documents/Codex/2026-10-01/wi/outputs/ImmoManager-Pro/.venv/Scripts/python.exe' -m pytest --noconftest backend/tests/test_recovery_bounded_planner.py -q
```

**40 passed, 3.30 s, exit 0, no skips**. This includes actual >16 MiB JSON accepted
by a 17 MiB profile after default rejection, both min-profile bounds and exact
boundaries, dotenv/JSON compatibility and strict failures, ambient isolation,
actual source replacement/growth/shrink/same-size rewrite, substituted native
file descriptor, nonregular/hardlinked sources, finite/pre-expired deadlines,
actual synchronous parser overrun checks and optional profile forwarding.
Ruff and Mypy then passed all three changed Python files, both exit 0.
All own execution sessions finished normally.

## Acceptance limits

These are pure planner/file tests with no backend conftest/plugin autoload,
application/config/dependency/DB-session imports, SQL connection, native child,
installation lease, provider, server, archive or actual restore. Test tripwires
refuse SQL and application imports. The legacy and recovery-CLI forwarding seams
are unit evidence, not installation-fence or full-container evidence.

Parsing is synchronous and byte-bounded; an after-parser deadline check detects
an overrun after return, without pretending to interrupt a library parser midway.
Root's fresh configuration fingerprint checks remain necessary across selection
and state publication. The existing SQLite writer wait is not refactored here.
Actual central maintenance/full-container/legacy recovery integration checks
remain separately coordinated Root gates. This packet does not claim overall
L or A–L completion.
