# Package 1: pagination, cache and queue hardening

Implemented against the shared `codex/party-document-workspace-20261007` checkout.
The million-row probe recorded HEAD `e25587a0b02550c9d8158fdf06914155e7603493`
with uncommitted package changes; it therefore describes that working tree, not
an unmodified historical commit.

## Behavior and limits

- `BaseRepository.list_paginated()` and both stores accept additive
  `range_filters={field: (lower, upper)}`. Bounds are inclusive, `None` is
  unbounded, and bounded conditions exclude SQL NULL / Python None. Predicates
  run before ordering, offset and limit. Existing positional arguments remain
  compatible. Booking, contract, invoice and maintenance routers use the normal
  requested page size; the tasks router is owned by package 2.
- Contract date semantics are preserved: `start_date >= date_from` and
  `end_date <= date_to`. Existing stable tie ordering remains unchanged.
- ORM and SQL schema have `idx_bookings_tenant`; additive revision
  `8c4d2e6f1a93` follows `6e2f8a4c9b71`. Upgrade adopts an already-created index;
  downgrade removes only this index. Existing document-downgrade regression now
  checks the document revision where destructive downgrade refuses, allowing
  later additive revisions to have already been downgraded.
- Cache age starts after successful work, but retains the pre-work data version.
  A write during calculation prevents that result being cached. A separate
  reentrant state lock lets invalidation finish while calculation is blocked.
  Writes clear stale response references, table changes clear affected table
  references, and every cache access releases expired entries in both caches.
  Response variants are limited to 256 ephemeral entries; this is not a limit on
  records in the database. Evicted variants are recomputed.
- Thread queue cancellation uses the submitted Future under a lock. A successful
  cancellation guarantees the waiting callable will not execute; cancelling work
  that has started returns false. Completed Futures are removed promptly.
- In-process job results expire one hour after terminal completion by default.
  `result_retention_seconds` can be configured on SyncQueue / ThreadPoolQueue;
  `None` explicitly opts into indefinite retention. `cleanup_results()` is public
  and queue operations also clean expired terminal statuses. Running and pending
  jobs never expire. The cleanup uses completion-order deadlines rather than
  scanning all jobs on every lookup. A completed result can become unavailable
  after retention; this cache is not durable job history. Business records are
  unchanged, there is no lifetime job count cap, and no submitted work is silently
  dropped. The executor submission backlog still needs separate backpressure or
  durable spool design if deployments require it.
- No cache byte budget or guarantee for million-row full-table analytics is made.
  Full-table report/search/startup allocation paths remain eager and were outside
  this package's implementation. Idle expired entries are released on the next
  operation (or explicit job cleanup), not by a background expiry thread.

## Red / green evidence

Verification Python:
`C:/Users/matth/Documents/Codex/2026-10-01/wi/work/verification-venv-py312/Scripts/python.exe`.
All test commands set outer `TEST_STORE_BACKEND=memory`; dedicated SQL fixtures
create their own databases. DATA_DIR, DATABASE_URL, uploads, backups, integration
state and logging were assigned disposable paths for final verification.

Initial command: `python -m pytest backend/tests/test_hardening_scale.py -q --tb=short`.
It reproduced empty date-filter tail pages in both stores, missing range API,
tenant query SCAN, duplicate immediate slow-cache computations, retained 12,000
cache keys and execution after accepted queued cancellation. Initial fixture
problems (duplicate contract numbers and patching a not-yet-imported clock) were
corrected and the relevant tests rerun red before implementation.

First green: the same command reported **28 passed in 6.13 s**. Further tests
cover migration upgrade/downgrade with row preservation, actual concurrent write
invalidation, 12,000 completed jobs per queue backend with every recent ID checked,
terminal retention, pending/running retention exclusion, failure status and 500
start/cancel races. These are light synthetic callables, not real OCR throughput.

Expanded command:
`python -m pytest backend/tests/test_hardening_scale.py backend/tests/test_sql_store.py backend/tests/test_migrations.py backend/tests/test_stress_findings.py backend/tests/test_services_and_security.py -q --tb=short`.
It reported **206 passed, 3 failed**. The failures were
`test_document_tenant_downgrade_refuses_to_lose_associations` (head expectation
updated here) and `TestEmailService.test_send_email_not_configured_does_not_raise`
/ `test_send_email_with_body_text` (package 3 updated their old SMTP-success
expectations). The latter were coordination findings, not suppressed failures.

A bare `python -m pytest -q --tb=short` was started, reached beyond 52% without
printing failures, then intentionally stopped at the integrator's request because
another agent was already running the same full suite. Only the identified owned
pytest process tree was terminated. This is not a full-suite pass. The integrator
owns final merged-suite verification and independent review.

Final focused command:
`python -m pytest backend/tests/test_hardening_scale.py backend/tests/test_migrations.py backend/tests/test_task_hardening.py -q --tb=short`.
It reported **73 passed, 9 deprecation warnings in 29.91 s**. Warnings concern
Starlette's httpx TestClient and Python 3.12's default sqlite datetime adapter.
Commit identity is reported in the handoff.

## Million-row real-server probe

Command: `python artifacts/audit-scale/probe_scale.py --rows 1000000 --paged-only`.
Result: exit 0, `assertions_passed=true`. Stable evidence is
`artifacts/audit-scale/measurements-after-hardening-1m.json`; original run directory
is `artifacts/audit-scale/data-20261007-115339-ac1821ec/`.

Windows 11 build 26200, Python 3.12.15, SQLite 3.53.1, 8 logical CPUs, Intel family
6/model 165. Timing is client wall time via perf_counter; Windows process counters
capture both the venv launcher and actual Python child. Memory is sampled after
each operation, with the child's OS peak working-set counter also retained. These
are a single local desktop run, not CI latency thresholds or sustained load SLA.

The server used an ephemeral free port and a unique disposable directory. Its
environment pins SQL persistence despite inherited memory-test settings, disables
demo data/AI, and pins uploads/backups/integration state/logs. On Windows the probe
stops only its own Popen tree. Both recorded PIDs were verified gone afterward.
No port 8765 service or installed EXE was touched. Seeding was chunked synthetic
SQLite writes; documents were metadata rows with nonexistent synthetic URLs, not
12,000 real uploaded files. Tasks were synthetic rows, not queue work.

| Probe | Outcome | Wall time |
|---|---|---:|
| Seed | 1,000,000 bookings + 12,000 document rows + 12,000 task rows | 13.381 s |
| SQL oracle | booking sum 1,000,000; date-match count 990,000 | 0.290 s sum |
| First filtered page | exact IDs 10,000–10,199, 200 rows | 0.0337 s |
| Filtered final page | exact last ten IDs, filtered offset 989,990 | 1.205 s |
| Unfiltered final page | exact last ten IDs, offset 999,990 | 0.2498 s |
| Tenant document tail | 10 rows, total 12,000, no more pages | 0.1230 s |
| Ten independent simultaneous readers | all HTTP 200, 200 rows each, exact IDs | 0.7470 s batch |

Ten-reader sample p50 **0.3656 s**, nearest-rank p95/max **0.4235 s** (10 samples).
Maximum sampled process-tree RSS **175,276,032 bytes / 167.16 MiB**; child OS peak
RSS **175,468,544 bytes / 167.34 MiB**. DB size **269,737,984 bytes**. Tenant lookup
plan is `SEARCH bookings USING INDEX idx_bookings_tenant (tenant_id=?)`.

The prior isolated index experiment measured 1,000 rows per tenant among one
million bookings: median 0.256 s scan versus 0.0155 s indexed, identical IDs.
This run confirms product index selection; it does not reassert that timing ratio.
Pagination with deep OFFSET still scans skipped rows (filtered tail 1.205 s).
The test covers ten simultaneous bounded reads; it does not cover PostgreSQL,
multiple writers, full analytics/search on one million rows, real document bytes,
durable job replay, actual OCR, or twenty-year unattended operation.

## Shared-file coordination

The package 1 commit includes package 2's task validation hunks in shared
`backend/storage.py` and `backend/repositories/sql_store.py` as requested by the
integrator. Package 2's dedicated router, recurrence service and UI files remain
its own commit. Its 30 backend regression cases were reported passing, and the
final focused command includes `backend/tests/test_task_hardening.py`.
