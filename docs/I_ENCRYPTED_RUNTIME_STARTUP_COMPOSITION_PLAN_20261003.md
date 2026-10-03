# I: explicit integration bootstrap in the owned normal launcher

Before-code Root plan, 2026-10-03, clean Root `d23b840`. The factory's
independently reviewed plan is `I_ENCRYPTED_RUNTIME_FACTORY_PLAN_20261003.md`
(`2567b2f` in its separate checkout). No private installation is converted,
restarted or initialized by this packet.

## Actual boundary and intended behavior

The normal launcher acquires `ManagedRuntime` before environment preparation,
Settings, app imports, SQL and background writers. Its current `_run` prepares
stable selected-installation field keys, checks the selected DATA_DIR, then
imports the app. Today the global integration manager still auto-initializes a
plaintext file; the separate factory packet removes that behavior.

Add the explicit `--initialize-integrations` flag to this existing launcher.
After stable runtime configuration, load the actual Settings and bind their
identity to the already owned lifetime. Before app import, and only if that
flag is present, pass the full explicit Settings snapshot to
`runtime_factory.initialize_new`. The same owned lease remains held through
application lifetime. A normal restart calls no initialize or migration.

A fresh missing persistent file is atomically created encrypted. Existing valid
encrypted content is authenticated as a byte-identical no-op. Existing legacy,
damaged, wrong-key or unreadable state is never replaced. A requested init
failure stops before app/SQL/background imports and reports a fixed code plus
the factory's fixed actionable instruction, without exception values, paths,
credentials or configuration content. Preserve its actual nonzero CLI exit
status through the launcher's top-level SystemExit handling.

Ordinary startup of unrelated application modules remains available with a
missing or invalid integration file. Every actual integration read/action still
loads/authenticates the file and refuses rather than returning empty data.
Wrap ConfigStoreError in the existing IntegrationPublicationRoute so all paths,
including provider run, list/status/metrics and config writes, have one safe
503 response. Keep revision conflict at 412 with the reload instruction. Do not
map unknown outcome into confirmed failure or automatically repeat an action.

## First initialization and upgrade are separate operator choices

The explicit flag is the initialization permission. Never infer it from marker,
DB table count, process identity, demo data, file age, schema revision or a
missing file during an ordinary restart. Existing plaintext installations use
the fenced full-backup/restore-probed maintenance command. Missing existing
state calls for full recovery, not silently creating an empty replacement.

The browser runner always creates and owns a new temporary installation. Its
normal fresh-server command can explicitly include the flag after integration
of the B2 opt-in fixture commit. Restored/backup/runtime tests model their actual
state deliberately; no blanket fixture replacement or weakened legacy checks.
Direct ASGI starts never grant first-init implicitly. PostgreSQL/container first
installation and its native ownership proof remain a later deployment task.

## Focused evidence required

Independent review after the initial six real CLI cases found that externally
supplied keys bypass persist_default's normal durable-default branch. Those six
passing cases prove lifetime/import ordering, not a restart without the same
external keys. Before initialization, validate the selected active keyring and
authenticate any existing state. Then persist the entire chosen field-key/JWT
bundle atomically in the selected runtime .env, using the existing private-file
and configuration-sidecar primitives. Refuse conflicting existing values before
any publication; this first-initialization action does not rotate keys. Only
after durable publication may initialize_new publish an absent encrypted file.
Add separate real restart-without-keys cases for single-key and named-keyring
configuration, plus conflict/failure atomicity and runner environment isolation.
Browser fixtures must not inherit any field keys from the user's environment.

Keep pure factory gates distinct from native launcher/API evidence. Native cold
child probes must prove actual lifetime exclusion before Settings/state work,
new encrypted state before app import, byte-identical repeated explicit init,
normal missing/legacy refusal without new files, wrong-key refusal, actual
configuration propagation and no provider side effect after failed state load.
HTTP tests use genuine authentication and normal authorization; no invented
actor or response mocks. Full backup/reopened encrypted state with archived
field keys and rotated session signing needs a separate coordinated native
case, in addition to earlier container proofs.

Only Root owns launcher, router, runner composition and the new native evidence.
The platform agent owns manager/factory/three Settings budgets and pure tests.
One coordinated native slot is used. Small commits separate source, tests and
actual evidence. This packet neither establishes full I acceptance nor changes
the old live preview.

## Follow-up before code: stored key names

Independent read-only review of `22dacfc` found stored names were compared
case-sensitively although Settings consumes them case-insensitively. Normalize
the stored left-hand side for bundle matching, duplicate/conflict detection and
the existing normal persist_default path. Preserve the original lines on an
unchanged match. A lower/mixed-case conflict or any mixed-case duplicate must
refuse before publishing any other selected key. Add focused filesystem
regressions for exact preserved bytes, conflicting aliases and duplicate aliases;
do not rerun unrelated app/browser cases because this changes no valid canonical
configuration path. Broader .env syntax remains the existing simple KEY=VALUE
launcher contract and is not expanded implicitly in this correction.

A second review identified quote/whitespace loss for otherwise accepted external
JWT values. Use one shared simple KEY=VALUE value decoder for launcher loading
and both persistence comparisons. Remove only a matching quote pair; decode
our JSON-quoted strings without stripping literal quote characters. Serialize
strings containing quotes, backslashes, control characters or boundary spaces
as one JSON-quoted value. Preserve ordinary safe existing spelling and files;
do not expand ambient variables. Add actual loader/Settings roundtrips and one
fresh two-process launcher check comparing only signer hashes. No secret values
are emitted by its child report. NUL/CR/LF validation remains unchanged.

Further independent review found the JSON-quoted codec was insufficient for the
actual recovery dotenv parser (`#` comments/control escapes) and could reinterpret
existing simply quoted Windows paths. Before changing code again, replace new
risky-value serialization with dotenv-compatible double quotes and recognized
escape sequences, plus a fixed trailing version comment. Only that explicit
marker grants escaped decoding in the launcher/comparison helper; old quoted
paths remain literal. The marker is an ordinary dotenv comment, so the actual
interpolate=False recovery parser returns the same value without another secret
format/store. Split persisted physical records at newline only, preserving
Unicode separators inside quoted values. Extend the existing roundtrip cases to
the actual dotenv parser, add comments/control/Unicode separators and legacy
quoted-path cases, and have the cold signer child also compare the actual
recovery._plan signer hash. Do not count the earlier20 PASS as backup-codec proof.

Actual `b74c25f` focused26-case gate: 25 PASS/1 FAIL in28.75 seconds (29.81
outer). The physical-newline record split created an unnecessary leading blank
record in a newly absent configuration file; the existing two-process canonical
key-pair assertion caught it. Remove only the final split sentinel through one
physical-record helper, retaining real interior blank lines and Unicode values.
Do not loosen the assertion. Recheck that exact case and the nine actual
dotenv/loader opaque-value cases; retain the other green cases as distinct prior
evidence rather than repeat the whole native selection without a new concern.

Final independent composition review found a separate name-selection mismatch:
runtime Settings accepts lowercase stored names, while recovery._plan selects
JWT/database/uploads/integration paths before converting names. Normalize known
dotenv names case-insensitively before any path/key selection. Refuse distinct
case aliases for the same known setting, without values in the error. Preserve
historical repeated identical-name dotenv precedence and recovered strict JSON
precedence. Never rewrite source bytes or import/open app/SQL during planning.
Add actual pure planner cases for lowercase/mixed names, chosen paths, both
alias conflicts and recovered JSON overriding a lowercase dotenv source.
