# E: restart-persistent automatic operations

Base: `5e636e0357a2cae6f338ba98e3a11485846ec722`.
Branch: `assist/durable-scheduler`; recorded before source edits.
Allocated migration: `f2a2b3c4d5e6`, parent `e2a2b3c4d5e6`.
Root owns subsequent `g2` and central recovery/runtime composition.

## Scope and ownership

Own the scheduler coordinator, its small persistent state model, f2 migration,
bounded task/calendar recurrence adapters, and focused native tests. Extend the
existing operational job service/types/validator only where these adapters need
it. Preserve existing job receipts and source effects. Do not modify integration
history, its manager, the live preview, or another checkout. Runtime registration
and recovery hooks are supplied separately for Root composition.

## Decisions

1. Automatic work requires an explicit active installation-wide manager/owner.
   A missing or revoked actor blocks work with a fixed diagnostic; no implicit
   privileged actor. Capture and revalidate the same role/portfolio fingerprint
   used by jobs. No interactive access token is stored in a scheduled job.
2. One scheduler state row binds actor/configuration/scope, generation, immutable
   generation idempotency key, job pointer, next due time and a leased coordinator
   fence. Reserve the generation before creating its job. Crash between job
   creation and attachment replays that exact creation key. Only the pointer's
   job is resumed; arbitrary/manual jobs are never adopted.
3. Coordinator transactions stay short. Business packets use existing job lane
   leases and final database-time fences. A stale coordinator cannot attach a
   different job or mark a later generation complete. Pending work survives
   restarts; attention/cancelled work remains visible and never counts as success.
4. Add durable task and calendar recurrence families to the three existing money
   and correspondence families. Source discovery uses bounded keyset pages.
   An individual historic series advances its own stored occurrence index in
   bounded packets; more than 10,000 due dates is work to resume, never a global
   overflow or a reason to discard earlier packets. Existing occurrence keys
   remain tombstones when a generated task/event is moved or deleted.
5. Preserve anchor clamping, task COUNT child semantics, one-open-child behavior
   unless full catch-up is explicit, and configured calendar full-catch-up policy.
   Revalidate a source before each publication. Invalid sources need attention;
   another family still progresses. Memory support is compatibility/testing only;
   persistent progress claims apply to SQLite/PostgreSQL.
6. Existing manual atomic tick APIs remain truthful atomic operations. Their
   auxiliary families (deadline projections, due-task/contract alerts, escalation
   and alert resolution) must be mapped explicitly during integration: either a
   bounded durable adapter or a separately identified compatibility pass. They
   must never be reported as durable progress merely because the worker ran.
7. Status reports persistent generation/job state separately from whether this
   process's worker thread runs. No total records cap; packet/time/lease limits
   constrain one transaction and permit continuation.

## Acceptance and integration gates

- Actual SQL schema and app startup remain explicit/no-DDL. f2 is additive and
  refuses downgrade if persistent coordination evidence would be erased.
- Native SQLite restart and independent-process races publish each effect once.
  Kill after reserved generation, after job creation/before attachment, and after
  committed packet; resume without adopting a manual job or replacing evidence.
- A real series with over 10,000 missing dates progresses across packets and
  restarts; later sources/families remain reachable, with bounded queries and no
  whole-table materialization in SQL adapters.
- Actual PostgreSQL concurrent workers and expired fences use UUID test schemas;
  actor revocation/configuration change stops further writes before publication.
- Old job validation/disclosure/recovery behavior remains valid. New recurrence
  progress and scheduler claims are validated/reset by explicit offline hooks;
  Root integrates the minimal central hook patch before final release evidence.
- No Docker/backup success is inferred. Full backup scheduling and isolated,
  portless restore probes are separate package L after E.

## E2 refinement and central schema allocation

E1 is an integration checkpoint only. E2 replaces its explicitly separate
compatibility pass with seven bounded job families: task deadline, maintenance
deadline, maintenance appointment, due-task notification, contract expiry,
escalation and alert resolution. A rule has its own resumable target cursor, so
one large escalation cannot monopolize the other job lanes. Ordinary source rows
are locked and re-read before their effect; an alert resolution also locks its
underlying source and notification. Contract-expiry execution evidence belongs
to its actual contract subject in retained disclosure.

Full catch-up means the complete anchored history, independently of lookback.
New semantics version 3 is distinct from the initial version 2 recurrence
checkpoint. A finished, revision-identical full-history work item may seed the
next occurrence index. Version 2 proofs and non-full proofs cannot hide an older
gap. Unchanged projections avoid another retained work row; finished series
avoid rescanning old occurrences. Synthetic acceptance includes 35/36-year
series and 10003 daily occurrences with lookback=1.

The centrally integrated f2 is now fixed. Root allocated follow-up index revision
`h2a2b3c4d5e6`, parent `g2a2b3c4d5e6`, separately from E2 behavior. It indexes the
completed recurrence source/revision lookup; E2 remains correct without it.
The g2 predecessor is owned by Domain C, so the complete migration-head gate is
a Root composition gate. No placeholder predecessor is created here.
