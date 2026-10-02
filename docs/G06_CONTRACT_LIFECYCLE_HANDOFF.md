# G06 native backend handoff

Ownership: this package adds its own service/types/validator/router/ORM module,
z1 migration and focused tests. No Main, Preview, frontend, existing financial,
document or recovery sources were changed. Root/browser_ci owns those integration
hooks; release_audit owns the tenant-privacy extension. The separate existing
y1 prerequisite commit is an unchanged copy of Root's already released migration;
do not cherry-pick it again into Root.

## Registration and persistence

- Import `backend.db.contract_lifecycle_models` before metadata/create_all and in
  Alembic env. `LIFECYCLE_MODELS` contains `ContractLifecycleDraftORM` and
  `ContractLifecycleCommandORM`.
- Tables/Memory collections: `contract_lifecycle_drafts`,
  `contract_lifecycle_commands`. Initialize empty dicts and preserve them across
  relevant Memory clone/disposal paths; existing service lazily creates them.
- Include `backend.routers.contract_lifecycle.router` under `/api/v1`.
- Migration `z1a2b3c4d5e6` follows `y1a2b3c4d5e6`. Bootstrap helper
  `ensure_contract_lifecycle_schema(connection)` rejects partial pairs/missing
  columns, installs the immutable SQLite/PostgreSQL journal guards, and is
  repeatable. It never fabricates historical rows.
- Requests/results, reviews, reasons and subject IDs contain personal data.
  They must not be included in a generic business JSON subset or logged.

## Transaction and ordinary CRUD hooks

The service uses a separate owned SQL Session/transaction, SQLite BEGIN IMMEDIATE
or PostgreSQL row locks, and the existing location→unit→contract lock ordering.
It calls the existing no-commit BaseRepository writes; it preserves occupancy,
financial receipts and CAS. Memory uses the existing global RLock and an undo log
of touched rows, not a full collection copy. Fresh actor/portfolio rights are
checked before use and before commit. No automatic timer, delivery, payment,
refund or legal-validity claim is introduced.

Required hooks (all in the same actual transaction/RLock as the ordinary write):

- `guard_contract_mutation(store, contract_id, changes)` **before** the ordinary
  BaseRepository contract update's old-value equality decision. It acquires the
  same parent/location lock and re-reads the current contract. Do not only check
  changed fields against an ORM instance read before waiting for that lock.
  Both declared end/status and party identity fields matter. An accepted current
  termination freezes its evidenced end/status against ordinary PATCH/PUT.
  Other permissible metadata/economic corrections keep existing guards. Only
  this service sets its exact-parent private context for its own reviewed
  confirm/finalize writes; that context does not allow party changes.
- Memory `ContractPatch` must dispatch to the existing validated
  `update_contract` path under RLock/CAS; raw `model_copy` is not sufficient.
  Preserve ordinary reference/date/status/occupancy validation.
- `guard_delete_link(store, entity_type, id)` before parent/successor contract,
  tenant, unit, property or portfolio delete/cascade/reparent. Subject bindings
  are retained even for private drafts. For ancestor mutations lock old/new
  locations and affected contracts before the guard, in normal lock order.
- `guard_known_rent_period(store, contract_id, month)` while holding the same
  parent lock as lifecycle confirm, for direct RentCharge creation and
  contract/month identity edits. It guards a known monthly service period after
  a confirmed end. Existing central finance/occupancy guards remain required.
  Never apply this to Receivable due dates: later damages/settlements are valid
  obligations and remain unchanged, merely shown as review warnings.
- `guard_destructive_reset(store)` before any reset or partial-JSON restore DML,
  with the existing global/transactional reset barrier and a serial recheck.
  Never erase journals or live subjects with a generic subset import. For rare
  PostgreSQL reset/import barriers keep location→contract→journal order rather
  than taking journals first and inverting command locks.

The service's raw Core queries return only Boolean integrity results beneath an
already freshly authorized exact contract. They reject hidden inconsistent
portfolio/subject/command/supersession rows rather than silently exporting a
filtered partial history; no foreign IDs, reasons or JSON are retrieved.

## Immutable confirmation and explicit supersession

API/schema are in `G06_CONTRACT_LIFECYCLE_API.md`. Renewal creates a distinct
same-party successor with explicit new number/dates; parent history is retained
and no economic fields are copied. A finite inclusive parent end is required.

Future termination leaves the contract active through its inclusive end. Manual
finalize is allowed only on a later server UTC date with current parent CAS;
another currently authorized member may finalize a prior member's confirmation.
`applied_contract_etag` remains the original accepted outcome;
`finalized_contract_etag` records a later actual completion.

An explicit earlier reviewed termination may supersede an existing pending
termination. Both pointers and prior ID/end/review hash are bound atomically.
The old data/review/commands stay unchanged, while its state becomes superseded.
History's `current_state` and pointers are separate from immutable `result`.
Old identical confirm replay still returns its original pending result and has
no new effect. Old finalize refuses with a successor hint. Earlier dates strictly
decrease, providing bounded acyclicity verification without a global history set.
Same-date replacements and already completed terminations are refused; corrected
metadata remains possible under current ordinary guards.

## Full recovery and privacy integration

Call `backend.services.contract_lifecycle_validation.validate_lifecycle_journal`
with the native sqlite3 or offline SQLAlchemy Connection **before** any restored
session invalidation or target publication. Both tables absent is a compatible
pre-z1 archive (`False`); partial pair fails. It streams records, closes cursors,
checks subject bindings, typed source/review/request/result hashes, exact create /
confirm / finalize counts, successor identity, current accepted end/status and
supersession reciprocity/strict direction. It makes no mutations. Valid later
metadata or successor-contract lifecycle changes do not rewrite old snapshots.

Pure APIs, both raising `JournalValidationError(ValueError)`:

- `validate_draft_evidence(row) -> None`
- `validate_command_evidence(command, draft) -> None`
- `validate_supersession_evidence(row, previous) -> None`

`FINAL` includes confirmed/pending_effective/completed/superseded. Historical
command results are independently validated snapshots, so an originally pending
result remains valid against today's superseded parent. A stale private review
can refer to a predecessor subsequently superseded elsewhere; it remains an open
draft, not a reciprocal accepted edge. G43 should export confirmed evidence only
through the exact tenant/contract/portfolio chain, including both pointers; other
actors' open reasons/reviews remain private and are represented by opaque
counts/digests. Keep the retained-scope manifest explicit. Do not claim generic
tenant anonymization covers this evidence until the separate privacy hooks pass.

## Executable gates

Focused files: `test_contract_lifecycle.py`,
`test_contract_lifecycle_http_schema.py`, `test_contract_lifecycle_validation.py`,
`test_contract_lifecycle_postgres.py`. These use only owned synthetic fixtures.
The PostgreSQL file requires `TEST_SERVER_DATABASE_URL` and creates/drops a fresh
UUID schema, upgrades the actual Alembic chain and uses independent Sessions;
without that dedicated service it explicitly skips and supplies no PG proof.
Root must run its added ordinary-CRUD/restore/privacy integration gates and full
application suites after combining these hooks.

Final native gate:68 passed/10 explicit skips (8 PostgreSQL without a dedicated
URL,2 SQL-only cases on the Memory fixture). The final run also executes the
real SQLite variants, actual JWT/scope HTTP, fresh full Alembic chain,
supersession/parallel/replay/late-rollback and copied-database verification after
deleting the owned source file. Ruff passes all added sources/tests; scoped
Mypy passes all5 runtime sources. The broader existing wizard/rent-adjustment/
billing regression run passed124 cases/8 skips; its one additional Source-Gone
test initially exposed an unclosed sqlite3 test handle on Windows. Explicit
closing fixed that fixture; the corrected Source-Gone case then passed2/2 and
the final complete native gate above passed. No product guard was weakened.

Separate paging followup: Memory own-draft and command-history pages use bounded
Top-k selection (`limit+1`) before DTO materialization, preserving descending
timestamp/ID and existing opaque cursors. Memory still scans the transient
collection; SQL remains a scoped bounded query. Five real Memory/SQLite paging
cases pass; one SQL variant explicitly skips the Memory-allocation measurement.
The allocation invariant was also run against the unchanged61e6c99 function and
failed as expected:1,616,984 bytes for20,000 matching entries versus14,415 for100.
The fixed function passes the same small-page bound. Ruff and scoped Mypy pass.
