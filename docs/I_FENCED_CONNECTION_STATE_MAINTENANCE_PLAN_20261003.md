# I/L: fenced SQLite connection-state conversion and checked return

Root pre-code plan, 2026-10-03. The complete container already proves encrypted
connection state (nine actual native cases). The ordinary integration manager
still uses the legacy store. This packet adds the explicit maintenance boundary;
it does not yet activate the global factory or migrate any private installation.

## Exact boundary and states

Use the existing installation lifetime lease before selecting configuration or
importing Settings/recovery. Explicit offline SQLite installation only; existing
database, uploads, original configuration and integration-state paths are
selected by the reviewed recovery planner. A native `BEGIN IMMEDIATE` excludes
independent SQLite writers throughout capture, full backup, isolated restore
probe and conversion. No application, auth singleton, provider or worker starts.

Store a protected non-secret operation receipt under
`.integration-state-upgrade/<UUID>/operation.json`. It binds installation,
selected paths, explicit configuration digest, original state SHA, original
database identity and complete archive identity/SHA. It never stores credentials,
keys, provider values or plaintext original state. All reads/archives/probes use
positive configurable capacity/time limits, without arbitrary upper ceilings.

Phases: `prepared`, `backup_validated`, `conversion_prepared`, `complete`,
`return_prepared`, `returned`. Actual source state is independently classified
as exact original bytes, exact prepared encrypted bytes or changed/unproved.
Persist the actual encrypted candidate SHA before its atomic replacement under
the existing integration sidecar lock. A crash after replacement and before the
success receipt therefore has a concrete recognizable outcome; no blind nonce
retry or empty-state fallback. Status never changes the connection file.

Before conversion, create the actual complete encrypted backup and restore it
to an isolated protected workspace using the real full recovery service. Verify
the restored connection bytes equal the captured original SHA. Recheck explicit
configuration/source identities. Conversion uses SHA CAS under the existing
stable cross-process sidecar lock, validates the entire legacy state and encrypts
all unknown fields with the explicit stable field keyring. An intervening writer
conflicts before replacement. Failure before publication leaves original bytes.

Checked return requires the archive passphrase again. Authenticate the exact
bound complete archive and actually restore/prove it in an isolated workspace.
Recover exact original state bytes there; verify their SHA and legacy structure.
The selected installation/configuration must still match, and current state must
be the exact prepared encrypted version with the same authenticated payload.
Restore only the original connection file through atomic sidecar CAS. Business
database, uploads, keys, sessions and configuration are never rolled back by this
state-only return. Changed connection values reject instead of losing later
edits. An already returned exact source is recognized idempotently. Ambiguous
post-replace durability errors retain the prepared phase for explicit status.

## Concrete ownership and compatibility

- Root-owned new `backend/integration_state_upgrade/` CLI/service: conversion,
  status and checked return, lifetime fence, protected receipts, real backup and
  probe composition, fixed non-secret actionable failure codes.
- Existing encrypted store gains narrow explicit migration SHA CAS and a checked
  legacy-return method; existing config writes retain their current behavior.
  Migration's publication callback records only the candidate SHA before write.
- `scripts/integration_state_maintenance.py` remains read-only verification.
  Its former unfenced `migrate-plaintext` entry reports the concrete new fenced
  maintenance command. It must not continue providing an unbacked user-facing
  conversion. Existing low-level callers are updated to give their actual SHA.
- No DDL, new queue, generic snapshot store, runtime activation or provider I/O.
  PostgreSQL/Docker appdata composition and normal encrypted factory selection
  remain subsequent separately accepted packets.

## Required focused evidence

Actual native full backup/probe/conversion/exact checked return; unknown fields
and stable key preservation; read-only crash classification before/after atomic
replacement; independent lifetime holder refuses before configuration selection;
independent state writer conflicts after proof; changed encrypted payload refuses
return; wrong archive password/tampered archive refuses with unchanged state;
explicit selection/configuration mismatch; legacy helper refuses unsafe conversion;
missing/malformed state and wrong keys never become empty configuration. Real
subprocess crash/restart and independent file locks supplement unit fault points.
All fixtures synthetic, bounded coordinated test slots, honest separate counts.
