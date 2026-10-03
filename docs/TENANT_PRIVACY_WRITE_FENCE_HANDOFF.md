# Tenant profile confirmation write fence

## Plan before implementation

Base: `f244389a4097a96548efa6fbcdf36706a7d3e53e`. Ownership is one new
fence helper, the `anonymize_tenant_profile` write boundary, synthetic tests and
this handoff. The disclosure graph, `_plan`, coherent repeatable-read preview
and export snapshots, original evidence and allowed profile fields stay intact.

The existing workflow writer locks Account, Property, Unit, Contract, Change,
Step. Job/calendar writers lock Account, the operational singleton/state, then
domain objects. A historical change can still freeze a tenant after an allowed
correction of the current contract's tenant. Locking only current tenant
contracts therefore cannot protect the reviewed subject facts.

1. Before domain locks, acquire the existing Account and Operational fences in
   that order. PostgreSQL row locks use NOWAIT. Do not bootstrap tables or seed
   missing singleton rows from this sensitive operation.
2. Validate whole workflow, operational and job table families. Completely
   absent legacy families are supported; partial families fail before any
   profile mutation. A present but unused carrier table may still be empty;
   its missing singleton is protected by a table lock, never repaired here.
3. Select only IDs from current tenant contracts and exact frozen previous/next
   contract tenant bindings. Lock related Property, Unit and Contract parents
   in stable order, then Tenant and relevant Change rows; avoid child-first
   locking. Consume SQL results incrementally. Scope contradictions fail closed.
4. Memory confirmation holds Account, operational state, then the existing
   domain/staged-copy boundary. These are the same locks as actual Memory
   workflow/job writers; contention fails clearly without profile changes.
5. Recompute the existing graph/hash while fences remain held through the
   existing atomic publication. Add no transaction commit, rollback, schema
   repair, field expansion or evidence rewriting.
6. Prove contention with actual independent PostgreSQL sessions and event
   barriers, including the unchanged historical-party counterexample. Test
   SQLAuth and MemoryAuth variants, job writers, absent/partial families,
   stale plans and unchanged original evidence. No sleeps count as lock proof.

## Final boundaries and integration

`backend/services/tenant_privacy_fence.py` supplies:

- `memory_account_fence(store, *, sqlite_staged=False)`: Memory takes Account,
  operational state and domain RLocks without waiting. PostgreSQL with Memory
  auth keeps the Account mutex across publication. SQLAuth uses the existing
  database management carrier inside the SQL transaction.
- `lock_subject_write_fence(staged, tenant_id)`: joins the existing transaction;
  checks whole SQL operational (5), job (3) and workflow (7) families; takes
  PostgreSQL Account then Operational NOWAIT locks, fresh rights, Property,
  Unit, Contract, Tenant and Change NOWAIT locks. Parent IDs come from current
  tenant contracts and exact immutable `snapshot.previous_contract.tenant_id`
  / `snapshot.next_contract.tenant_id` bindings. Only IDs/Boolean scope checks
  cross the driver, consumed in bounded cursor batches. No name matching.

Empty, complete PostgreSQL carrier tables use `SHARE ROW EXCLUSIVE NOWAIT` on
the specific technical table instead of inserting a singleton. Entire absent
legacy families are accepted. A partial family or jobs without their operative
carrier is rejected before profile DML. Memory work-item dictionaries are lazy
data, not SQL schema: a valid queued job need not have work items yet.

SQLite retains the existing whole-database `BEGIN IMMEDIATE`/busy budget. Its
Memory-auth mutex is deliberately acquired **after** that file write fence, so
a prior SQL writer can finish its native auth recheck/commit. The mutex is added
to an outer `ExitStack` and held until `_privacy_write` has actually published,
not merely until the inner profile body returns. SQLite busy/locked errors map
to the same retryable `PrivacyConflict`. No global timeout/event changes.

The only additional shared-code change expressly authorized by Root is
`_memory_state` normalization of Schedule/Occurrence/Dispatch/Tick ORM state.
A real unchanged `tx.schedule` previously produced a false concurrency conflict;
it now preserves its exact state. An actual intervening recurrence edit still
conflicts and remains in the live store instead of being overwritten.

Merge this confirmation boundary with the separately owned retained-disclosure
graph/`_plan` union. This package intentionally does not claim that those new
retained collections are already included by the old graph on its base.
Keep `ExitStack` outside `_privacy_write`, including delayed SQLite resources.
No startup, auth, workflow/job writer, recovery, schema, frontend, migration,
original-file or receipt changes. No extra transaction commit/rollback.

## Evidence and final gate

The unchanged native counterexample's source/copy SHA256 is
`c1a9633093b1aadb6e9644fd1d7f0d26a075535210c5e88a058bc70be107a12c`.
It originally failed on the disclosure branch; it now passes against this fence.
Native PG tests use only UUID-owned schemas on the supplied disposable service.
Enable with `TEST_SERVER_DATABASE_URL` and
`RUN_TENANT_RETAINED_FENCE_PROBE=1`; PostgreSQL is not simulated by SQLite.

Important actual barriers:

- `test_pg_actual_old_party_step_writer_refuses_profile_before_any_dml`
- `test_pg_actual_job_writer_refuses_profile_before_any_dml`
- `test_pg_fence_held_through_actual_hash_prevents_late_carrier_publication`
- `test_pg_actual_job_cannot_publish_after_confirmed_hash_barrier`
- the unchanged `test_pg_profile_confirmation_cannot_commit_after_unreviewed_historical_workflow_writer`
- `test_sqlite_memory_auth_allows_existing_writer_to_finish_before_confirmation`
- `test_sqlite_memory_account_fence_is_held_until_actual_outer_publication`

SQLAuth/MemoryAuth use native account stores and rechecks. Busy cases observe
zero tenant UPDATE/DELETE statements. After-hash MemoryAuth tests observe an
actual failed mutex acquisition before the native reader, release the controller
only for final publication, and verify the allowed later job sees the committed
anonymized profile. Native SQLAuth cases observe PostgreSQL `55P03`. A future
timeout or sleep is never counted as proof of a fence.

Pre-final existing privacy regression gate: **148 passed, 7 explicit skips**
(profile, credit, wizard, document versions, lifecycle, correspondence), after
normalization and before the separately targeted SQLite entry improvement.
Final exact-source SQL-process gate: **67 passed, 43 explicit skips** using
`test_tenant_privacy_write_fence.py`, the unchanged opt-in counterexample,
`test_tenant_privacy.py` and `test_tenant_credit_privacy.py`, with the actual PG
URL configured. Skips are fixture-specific non-PG/non-Memory/non-SQLite cases,
not an unavailable PG service. Both SQLite ordering/outer-publication cases and
the real lazy queued-Memory-job preservation case pass. Ruff, scoped Mypy on
both product sources and `git diff --check` pass.

Exact product/test file SHA256 (LF working-tree bytes):

- `tenant_privacy.py`: `368c75239debf3f9e9971f4f76d11adbcc32282506893749e903ab304b698c01`
- `tenant_privacy_fence.py`: `fde04d9820b7051b7651ec3b6f713ebfcb95a2fe1fa941534b9109d6607e1c7e`
- `test_tenant_privacy_write_fence.py`: `608ccf0a29697940cd4c6932b8e69c40519b011b633417d4aa5730c6de32f99e`

Unchanged function-source SHA256, verified against base with UTF-8 AST source
segments: `_read_snapshot` `d939cd7b1eee6cc3c9b71e8ad1e65749bda37f4891c81236281c7811efd214c8`;
`_plan` `954bb7d17c068a477a89ab57066226ccaf93a544fc3253f4b204de4eba8c02ba`;
`_scoped_graph` `1a162613790f0284dc7d138d5fef348709e6e24d532fcc15bfd07c74145889e3`;
`_memory_privacy_lock` `62123380403550582e49ebb65558033a2dec00257b55d82be24f378570298367`;
`_privacy_write` `8c196a9a3beadecc837600717fcaabf415ec3640be1df062fb6e9ff8da07086a`.
