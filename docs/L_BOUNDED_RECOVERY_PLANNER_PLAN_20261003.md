# L: bounded explicit recovery configuration planner

Pre-code plan, 2026-10-03. Isolated checkout `work/bounded-recovery-planner`,
branch `assist/bounded-recovery-planner`, clean starting source `58aaf3e`.
Root owns integration-state maintenance composition and all central startup,
factory, schema, authentication, settings and CI changes.

## Problem and exact compatibility

The recovery selector currently parses `.env` without a byte budget and refuses
`configuration.json` above a fixed 16 MiB even when an explicit host profile
permits more. The new signature is `_plan(args, *, limits=None, deadline=None)`.
Omitted limits use the actual `RecoveryLimits()` defaults: metadata 16 MiB,
file 4 GiB, timeout 300 seconds; the effective per-configuration-file byte budget
is `min(metadata_bytes, file_bytes)`. These are adjustable resource budgets,
never maximum installation record counts. A larger valid profile permits larger
configuration files without an additional hard-coded 16 MiB ceiling. Existing
`_plan(args)` callers continue to work, now with the default bounded reads.
An omitted deadline is derived from the chosen profile and monotonic time.
An explicit finite deadline is retained; parsing never resets it.

Keep the selected installation and existing configuration precedence: parse
`.env` with `dotenv_values(stream=..., interpolate=False)` from a bounded UTF-8
stream with ordinary universal-newline semantics, then apply strict recovered
JSON via existing `_json` and `_configuration`. ExplicitSettings continues to
use only the selected stored values. No ambient settings, generated keys,
provider access, application imports, schema changes or source-file writes.

## Read and parse boundary

For each optional source, check remaining time before opening. Require a regular
local file, reject symlinks/reparse points and multiple hard links, and compare
the opened descriptor's actual identity/size/timestamps to its named source.
Reject a known oversized source before allocating/parsing. Read in bounded
chunks with at most one overflow byte; check remaining time for every chunk.
Before returning bytes compare descriptor and named-file fingerprints again,
rejecting replacement, shrinkage or growth during capture. Errors describe the
operation rather than file contents or secrets. Missing optional files retain
their existing semantics; unreadable/nonregular files do not become empty data.

Check remaining time immediately before and after each parse/validation stage
and at the completed-plan boundary. Parser calls are synchronous and bounded by
the byte profile; checks detect an overrun when the parser returns rather than
promising interruption within an individual library parser call. Root retains
the separate pre/post parse configuration fingerprint and publication-window
checks that protect its actual state-file CAS.

## Minimal composition

`_offline_backup(args, *, limits=None, deadline=None)` forwards the selected
profile/deadline to `_plan` while retaining its existing installation lease and
SQLite writer boundary. The recovery backup CLI passes its already loaded
profile and one deadline through selection and grants the actual full backup
only the remaining time. Password entry occurs before this work deadline.

Legacy service `_selected(args, root, *, limits=None, deadline=None)` forwards
these optional parameters, preserving its existing two-positional-argument API
and existing selected-database safety check. Other legacy call sites retain the
default compatible behavior. Root alone updates its maintenance `_selected`,
`_assert_binding`, `_configuration_files` and corresponding fixtures to pass its
already chosen limits/deadline.

## Focused evidence and ownership

Own new `backend/tests/test_recovery_bounded_planner.py` uses only synthetic
temporary text files and explicit Settings validation. Run it with
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and `pytest --noconftest`, importing neither
application nor backend test conftest and opening no database/server.

Cover default compatibility, dotenv quotes/newlines/duplicate-last-value and
literal interpolation, strict JSON precedence and invalid inputs, min(metadata,
file) rejection before parsing both source types, exact-budget success,
configuration above 16 MiB accepted by a larger actual profile, native file
replacement/growth during bounded capture, descriptor identity mismatch,
pre/post-parser deadline enforcement, explicit ambient isolation, absent-source
failure rather than generated keys, and optional-profile forwarding. Separate
the pure forwarding unit seam from any actual installation/SQLite/archive proof.

First commit this plan, then the two allowed product files and own tests, then
actual pure-gate evidence and API handoff. Ruff/Mypy may inspect these files.
No native integration, database, server, process-lifecycle or heavy gate starts
until Root separately coordinates a slot. No Root/Main/Preview files are edited
and only Root integrates the resulting commits.

## Scope clarification before the final caller fix

Root subsequently identified that existing legacy upgrade/status/return commands
already load their own profile and deadline but still call the optional selector
without forwarding them. Root authorized either an explicit remaining gap or the
three narrow forwarding edits. Complete the authorized path: change only those
three `_selected` call arguments, passing the already loaded limits and deadline.
Do not change their installation/SQL/archive/return implementation.

Add three own pure regression cases. Each invokes the actual corresponding legacy
command and actual selector with a tiny explicit profile, replacing only the
installation-lease boundary with a unit context seam. The actual bounded source
read must refuse before SQL, receipt or archive work; the existing SQL/application
tripwires remain active. Run just these three new cases because the previous 40
planner cases are unchanged. Record this distinction in the handoff rather than
claiming a newly executed 43-case combined run or actual legacy migration proof.
