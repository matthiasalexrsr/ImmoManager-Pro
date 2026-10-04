# P1/P2 tenancy workflow backend handoff

Base: `7ccee8ca4518966d1dbb07ef625eb31d2133337a`
Branch/worktree: `assist/tenancy-workflow-core` / `work/tenancy-workflow-core`
Binding contract: `docs/TENANCY_WORKFLOW_CONTRACT_20261002.md`

This file belongs to the final branch HEAD; Root should use `git rev-parse HEAD`
when importing the package.

## Architecture and invariants

This package adds one in-process FastAPI/SQLAlchemy domain. It does not add a
second task system, finance ledger, scheduler or external transport. Existing
`Task` rows remain the executable projections. A unique
`WorkflowStepInstance.task_id` is their durable workflow origin.

Property move-in/move-out templates are versioned. An explicit unit override is
a separate versioned template with `unit_id`. Publishing freezes the version
and retires the prior published version without rewriting it. Template steps
require exactly one active task-capable user or one task-capable role and are
validated as an iterative acyclic graph.

Starting a tenancy change freezes the selected published template versions and
the exact selected contract anchors/ETags into `snapshot` +
`snapshot_sha256`. Later template edits do not rewrite an active/completed
change. A step keeps `original_due_date` separately from its current
`due_date`; reanchor changes only unfinished steps and their linked task
projection. Completed/not-applicable facts are terminal.

Every state-changing workflow command has actor-bound idempotency,
`expected_revision`, canonical request hashing and an immutable command
receipt. Step commands also CAS the parent change through
`expected_change_revision`. Replays refresh account/role/portfolio scope
before returning the saved result. SQL commands use one owned transaction;
Memory commands use an undo log under the shared reentrant write lock. SQL task
creation/update calls the no-commit BaseRepository directly, so the task,
workflow row and receipt publish or roll back together.

No workflow command creates or copies rent charges, bookings, payments,
receivables, deposits/refunds or external messages.

## Persistence / migration

Migration `b2a2b3c4d5e6_tenancy_workflows.py` follows the current
`a2a2b3c4d5e6` correspondence head and creates:

- `tenancy_workflow_templates`
- `tenancy_workflow_template_versions`
- `tenancy_workflow_template_steps`
- `tenancy_changes`
- `tenancy_workflow_step_instances`
- `tenancy_workflow_evidence_links`
- `tenancy_workflow_commands`

The schema has property/unit template identity, active previous/next-contract
uniqueness, version/step/task uniqueness, exact-one responsibility constraints,
typed evidence-shape constraints and retained/frozen guards. Published template
content, start snapshots, step graph/snapshot fields, terminal facts and command
receipts cannot be silently rewritten. Evidence may be removed only while its
step is still mutable.

The same migration closes the pre-existing evidence hole in handover data:
finalized handover protocols reject DB-level UPDATE/DELETE and their meter rows
reject INSERT/UPDATE/DELETE. Normal Memory and SQL repository paths implement
the same rule with parent-first locking; the Memory meter-create path now uses
the common write lock.

Downgrade refuses when workflow rows exist. Empty-schema downgrade is supported.

## API / DTO contract

`backend/routers/tenancy_workflows.py` implements the exact route surface from
`TENANCY_WORKFLOW_CONTRACT_20261002.md`: template list/root/version
create/edit/publish, tenancy-change list/preview/start/read/cancel,
reanchor-preview/reanchor, step mutation, task projection, evidence add/remove
and completion.

Mutation DTOs use `idempotency_key` + `expected_revision`; step commands use
`expected_change_revision`; start uses the explicit `"new"` sentinel.
Reanchor confirmation additionally carries the preview hash and source ETags.
Responses expose UUID revisions and strong workflow ETags.

List responses are `{items, next_cursor, has_more}`. Cursors are
HMAC-authenticated, expire, and bind the actor/current role+portfolio grants,
filters and requested page budget. SQL pages use keyset queries and never apply
a 100/10,000 total inventory cap. Unit template lookup returns the property's
default plus that unit's explicit override, never another property's template.
Detail step/evidence arrays are complete and have no first-100 truncation.

## Existing-domain corrections owned by this package

### Normal Task writes

A workflow-owned task cannot be changed through ordinary Task PUT/PATCH/DELETE
for title, description, assignee display, due date, status, property/unit,
recurrence or parent identity. The workflow service owns those projections via a
narrow internal context. Direct normal deletion is rejected. SQL projection
does not call the facade method that commits per task.

### Finalized handover / meter evidence

Finalized handover protocol UPDATE/DELETE is rejected. A meter cannot be added,
changed, moved or deleted after its handover is finalized. Parent handovers are
locked before meter rows; proposed parent moves lock both parents in sorted
order and re-read the meter after waiting. Failed SQL guards roll back before
raising, so SQLite does not retain a writer lock.

A linked meter row is also frozen while it is workflow evidence. Evidence
linking freshly validates exact portfolio/property/unit/contract direction and
tenant binding. Document evidence requires the exact
`document_id + document_version_id`, validates the immutable manifest and
streams verified original blocks; no file path is stored as evidence identity.

### Task date filtering

`backend/services/task_list.py` replaces the old date-filter route's
`limit=10000` prefetch. SQL applies scope, status, assignee and due-date
predicates before OFFSET/LIMIT. Memory scans the authoritative raw collection
under the common lock, calls `memory_visible`, and retains only the requested
sort prefix. A synthetic >10,000-row regression includes the only matching
record after the former boundary and requests a small page.

`operational_schedule.py` is intentionally untouched. Root separately owns the
legacy global-tick continuation problem.

## Root integration still required

By prior ownership agreement this commit does **not** register production
startup/recovery/privacy/reset/export boundaries. Root must:

1. register `backend.db.tenancy_workflow_models` with production metadata /
   migration startup and reject a partially present workflow table family before
   DML;
2. register the router under `/api/v1`;
3. add the common permission-middleware/resource-scope registration for
   `workflow-templates` and `tenancy-changes`;
4. add the family to full recovery, reset/transfer, privacy/export and retained
   evidence validation;
5. integrate Root's separate scalable `/workflow-references/{kind}` service.

Do not silently call `create_all` to repair half of this retained family.

## Gates actually run on final sources

Focused workflow + task-scale suite with the Root-provided disposable
PostgreSQL service enabled:

`pytest backend/tests/test_tenancy_workflow_core.py backend/tests/test_task_date_filter_scale.py -q -rs --tb=short`

Result: **48 passed, 2 skipped**. The two skips are only the Memory parameters of
DB-trigger-only tests; both the real SQLite and isolated PostgreSQL variants of
those trigger gates ran and passed. PostgreSQL fixtures create a fresh random
schema per test and drop it afterwards; they do not use `public`.

Selected existing Task/handover/meter/CAS regressions:

`pytest backend/tests/test_operational_schedule.py backend/tests/test_edit_concurrency.py backend/tests/test_crud_routers.py -q -k "task or handover or meter or conditional or stale_edit or deleted_lifecycle_subject or missing_proposed_parent" -rs --tb=short`

Result: **51 passed, 1 skipped, 349 deselected**, with one existing FastAPI /
Starlette deprecation warning. The one skip is the Memory parameter of an
SQL-parent-lookup-only regression.

Migration gates:

- isolated random PostgreSQL schema: complete Alembic chain upgraded to
  **b2a2b3c4d5e6 (head)**, then downgraded to **a2a2b3c4d5e6**, exit 0, schema
  dropped afterwards;
- fresh temporary SQLite database: complete chain upgraded to
  **b2a2b3c4d5e6 (head)**, then downgraded to **a2a2b3c4d5e6**, exit 0.

Static gates:

- Ruff on every changed/new Python file: passed;
- Mypy on `tenancy_workflow.py`, its DTO/model/router and task-list runtime
  modules: **Success: no issues found in 5 source files**;
- `py_compile` on the six new runtime/migration modules: passed;
- `git diff --check`: run immediately before commit.

## Explicitly not claimed

The full backend suite and browser/UI suite were not run by this package.
Production startup, routing, permission registration, privacy, reset/export and
full-recovery acceptance remain Root-owned and therefore are not claimed green
here. No dedicated two-process race test was added for workflow commands; the
PostgreSQL gates exercise the real lock/constraint/transaction paths, while
parallel multi-worker acceptance remains a Root integration gate.

No Main, Preview data, Root integration worktree, correspondence sources,
foreign UI files, provider credentials or TEHA data are modified.
