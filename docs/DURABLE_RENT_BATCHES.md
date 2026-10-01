# Durable monthly rental generation

Large selections are processed in resumable work steps rather than rejected by
contract-count or 120-month business limits. The legacy preview/generate APIs
delegate work exceeding a technical response budget to a saved batch. That
handoff creates no rental charges. Existing small calls retain their behavior.

## Integration

Migration **q1a2b3c4d5e6**, parent **p1a2b3c4d5e6**, adds six journal/snapshot
tables and SQLite/PostgreSQL source-revision triggers. Import
`backend.db.rent_batch_models` in schema registration. For historical create-all
installations call `ensure_rent_batch_schema(connection)` explicitly during
startup; this creates additive tables/triggers and preserves reduced legacy
tables. It does not rebuild or replace business tables. Include
`rent_batches.router` **before** `rent_charges.router` under `/api/v1`.

Settings integration: `RENT_BATCH_MAX_SIZE` / `rent_batch_max_size`, default 500,
validated configuration range 25..5000. A work request accepts budgets 1 through
that configured maximum. There is no total contract, month or generated-row cap.
The UI defaults to 100 entries per step. No unattended scheduler is required.

## Workflow and guarantees

`POST /rent-charges/batches` accepts start/end month, optional explicit contract
IDs and an idempotency key. A creator/key pair is permanently unique. Reusing it
for different parameters is a recoverable conflict. The creator's exact active
role/portfolio scope is stored and checked freshly on every read and operation.
The creator alone can access a batch. A scope change requires a new preparation;
it does not silently broaden or truncate an already approved selection.

Preparation pages through contracts, then applied price rules, then the snapshot
hash. Contract identity/term, unit pricing, price-rule insert/update/delete/move
and property/portfolio changes increment durable sidecar revisions. A no-op DML
price lock does not increment them. Before sealing, revision checks and a source
completeness query reject changed preparation. `restart` explicitly discards
uncommitted snapshot rows and begins again. Sources remain unchanged.

The sealed snapshot preserves integer cents, contract terms, unit advances and
applied adjustment history. Month-start pricing follows the existing G08 rule:
latest applied adjustment effective on day one, or the earliest adjustment's
previous rent before its first effective date; otherwise the captured unit rent.
Touched months are charged fully, without automatic daily proration. The UI
shows the saved price timestamp and previews bounded pages, including existing
charges. A plan hash is a content fingerprint, not a signature.

`confirm` explicitly approves the plan hash. `advance` then plans a bounded batch,
locks only the affected contract rows on SQL, checks their still-current identity
and term, inserts charges under permanent UNIQUE(contract_id,month), records
results and updates the cursor **in the same transaction**. Existing charges,
payments, reversals and paid balances are never overwritten. A concurrent step
or stale cursor returns a concrete conflict; reload saved progress before retrying.
If a response is lost, a GET establishes whether its transaction committed.

Work cursors are versioned and purpose-separated HMAC payloads bound to the
batch, revision, state, phase and plan hash. Preview/list cursors bind their page
size and selection. Key rotation can invalidate a client token; GET returns the
current valid work cursor. Cursor errors include `clear_code` and a recovery
action. They do not delete progress or perform an automatic incorrect retry.

`pause`/`resume` preserve the current source/target position. A partially generated
plan retains its approved prices. If contract identity/term changes, prepare a
new plan for the remaining work; its uniqueness check preserves earlier charges.
`GET /rent-charges/batches` lists the creator's saved IDs in bounded pages, and
`GET /{id}` recovers progress after process/database-session restarts. Old-scope
list entries expose no old parameters or financial counts. The frontend stores
only the user's last batch ID, never credentials, and can also list server jobs.

SQL journals survive application restarts. The explicitly nonpersistent memory
backend provides a process-local reference journal and content guards; the UI
states its durability limitation. Production persistence requires SQLite or
PostgreSQL. Snapshot preparation is application-bounded; the final SQL revision
and completeness checks scan indexed source/journal rows in the database rather
than materializing the whole installation in Python.

## Reproducible checks

`python -m pytest backend/tests/test_rent_batch_planner.py
backend/tests/test_rent_batches.py backend/tests/test_rent_batches_http.py
backend/tests/test_rent_batches_postgres.py backend/tests/test_rent_ledger_queries.py`
tests actual SQL/memory progress, 501 selected contracts, 241 months, frozen
historical pricing, source deletion, invalid/stale cursors, scope changes,
explicit confirmation, new-session recovery and rollback after target inserts.
PostgreSQL tests require `TEST_SERVER_DATABASE_URL`; each owns a UUID schema and
never touches existing application schemas. No dedicated local PostgreSQL was
available during native implementation; a skipped PG gate is not a PG pass.
