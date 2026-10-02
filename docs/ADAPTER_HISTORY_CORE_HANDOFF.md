# Private adapter history: package A core

Base: `af583dc097e35c886dd5cac8b7cda3f8623cecf7`. Migration
`c2a2b3c4d5e6` → `d2a2b3c4d5e6` is a single linear successor.
The complete plan is `ADAPTER_HISTORY_PLAN_20261002.md`. This first commit
contains the SQL journal, encryption, read/clear/restore APIs and tests;
the manager and HTTP integration follow separately. It makes no provider,
delivery, HTTP-byte or automatic-retry claim.

## Runtime contract (owned by the runtime integration agent)

- Register `backend.db.integration_history_models.HISTORY_MODELS` before
  metadata creation. `TABLES` is exactly the five names below.
- `backend.db.integration_history_schema.ensure_history_schema(connection)`
  is read-only and supports a real `sqlite3.Connection` or SQLAlchemy
  Connection. Entire family absent returns `False` before any key lookup;
  partial family, missing columns, PKs, uniqueness or FK contracts fail closed.
- Fresh-only startup may explicitly create these five tables and call
  `install_history_guards(connection)`. Existing installations use the actual
  Alembic migration. Ensure never creates or repairs schema.
- `history_store.configure_history(existing_session_factory, limits=...)`
  configures the existing shared database in both Memory-domain and SQL-domain
  operation. `configured_history()` returns that store; no RAM/private-DB
  fallback exists. The store closes a temporary factory Session and opens an
  independent unscoped connection against its bind.
- Settings/ENV contract: `integration_history_artifact_bytes` /
  `INTEGRATION_HISTORY_ARTIFACT_BYTES` default `16777216`;
  `integration_history_page_bytes` / `INTEGRATION_HISTORY_PAGE_BYTES` default
  `33554432`; `integration_history_timeout_seconds` /
  `INTEGRATION_HISTORY_TIMEOUT_SECONDS` default `60.0`. Pass these to
  `HistoryLimits(artifact_bytes=..., page_bytes=..., timeout_seconds=...)`.
  Bytes are positive integers; time is finite and positive. No configuration
  ceiling or total-history count limit. Individual native SQL timeouts use
  signed-32-bit milliseconds; larger overall budgets remain valid.

## Family and authenticated identity

`integration_history_heads`: per-provider commit-ordered run/event counters,
clear epoch, current count, start time. Technical counters survive reset.

`integration_runs`: immutable run identity and actor; FK `integration_id` →
Head (RESTRICT), unique `(integration_id, run_sequence)` and
`(id, integration_id)`.

`integration_run_events`: immutable states and artifact manifest; composite FK
`(run_id, integration_id)` → Run `(id, integration_id)` (RESTRICT); unique
`(run_id, event_number)` and `(integration_id, journal_sequence)`.

`integration_run_chunks`: 64 KiB plaintext chunks encrypted independently;
FK `event_id` → Event (RESTRICT), primary key `(event_id, kind, position)`.

`integration_history_clears`: immutable minimal explicit-clear audit; FK
`integration_id` → Head (RESTRICT), unique `(integration_id, clear_epoch)`.
Preserve heads and clears on business reset. Only retained runs/events/chunks
block partial transfer/reset; a clear audit is not a permanent business-reset
blocker. Normal explicit history clear verifies every candidate before DELETE,
rejects open runs, removes only telemetry and preserves minimal clear proofs.

Payload/config/response/schema chunks and private metadata use independent
AES-GCM nonce encryption, versioned `history:v1:<key-id>:` envelope and HKDF
domain `immomanager/private-integration-history/aes-gcm/v1` from stable G44
field keys, never JWT. Run AAD binds all identity fields and creation time;
Event AAD additionally binds exact run identity, state, success, journal/event
number, predecessor hash, artifact kind/byte/chunk/SHA manifest. Chunk AAD
adds artifact kind and position. Clear AAD binds actor, integration, epoch,
time and actual removed count. Ciphertext/metadata swapping fails closed.

## Recovery and reset (no callbacks, implicit keys or commits)

`history_validation.validate_history_journal(connection, configuration,
deadline=None, limits=None)` streams and verifies all rows and chunks. Use an
explicit `Mapping[str, str]` containing archived G44 key configuration or an
explicit `IBANKeyring`. A present family with `None` is rejected; no ambient
fallback. Structural native-sqlite inspection needs no keys. Read-only full
crypto proof precedes reference rebasing, auth mutation and publication.

`history_restore.mark_restored_unconfirmed(connection, configuration,
deadline=None, limits=None) -> int` first performs the complete proof, then
appends auditable `outcome_uncertain` events for accepted/started runs in the
caller-owned SQLAlchemy transaction. Repeated call returns zero; rollback
retains the original open state. No provider, auth, replay, sessionfactory,
external effect or commit. Caller guarantees offline exclusivity and supplies
the same restored budget configuration. Public details explicitly say
`outcome_unconfirmed` and `retry_automatically=False`.

Lock order is Account → optional Operational/Domain → History. Store writes
take the actual Memory-auth RLock before a short history transaction and Head
lock. No domain lock or provider I/O is held. `lock_history_fence(connection,
nowait=False) -> bool` uses the caller transaction; PG locks all five tables
SHARE ROW EXCLUSIVE (optional NOWAIT), SQLite caller already owns BEGIN
IMMEDIATE. `history_fence(nowait=False)` holds an independent connection to the
actual configured shared journal for the full Memory reset span. No second DB.

## Executed core gates

- 19 actual SQLite/PostgreSQL cases: raw ciphertext and restart, wrong key,
  205 concurrent complete records traversed without loss, frozen status cursor,
  explicit clear audit, separate processes, immutable triggers/AAD corruption,
  no partial accepted run on budget error, expired proof, caller rollback and
  idempotent restore normalization. No local PG skip.
- 2 complete real Alembic gates on SQLite and fresh random PG schema:
  upgrade → permitted empty downgrade → upgrade; retained evidence/clear audit
  downgrade refusal preserves schema, constraints, revision and values.
- Ruff and Mypy core sources; manager/HTTP compatibility and runtime/archive
  hooks remain subsequent independently verified work, not claimed here.
