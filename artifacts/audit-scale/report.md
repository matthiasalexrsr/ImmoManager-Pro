# Scale and concurrency audit, 2026-10-07

Source audited: `eb458493370c8514c70653d0a47044333ce53a11` (`latest Claude3223a36a + partyfeature`). Product code was not edited. Probes used disposable SQLite databases below this directory and dynamically chosen localhost ports. Port 8765 and user databases were never contacted. Every probe server has exited.

## Machine and limits

- Intel Core i5-10300H, 4 physical cores / 8 logical processors.
- 24,921,792 KiB visible physical RAM (23.77 GiB); sampled free RAM 5,171,096–5,255,012 KiB (4.93–5.01 GiB).
- C: total 1,998,356,013,056 bytes; free 1,325,479,247,872 bytes at first sample.
- Python 3.12 from `../verification-venv-py312/Scripts/python.exe`.
- Fixture seeding: chunks of 2,000, committed per chunk. Single-thread seeding, 10 clients only for bounded 10-request bursts. Largest complete probe ran 32.71 seconds (see JSON elapsed values); million-row pagination probe ran 20.86 seconds.
- Windows venv launchers have a child process that runs Python. The first probe's memory counters measured only the launcher and are invalid for app memory. Use the second 100k probe (`data-20261007-113536`) and 1m probe (`data-20261007-113726`), whose counters include the complete process tree. Peak RSS below refers to the actual app worker, not launcher totals.

## Measured results

The data has 100k or 1m bookings, 12k document records, and 12k persisted task records. Bookings use amount 1 with only 1/1000 assigned to one tenant; first 10k are dated January, the rest October. Documents are metadata with synthetic file URLs, not physical PDFs. This is a storage/HTTP-scale fixture, not a realistic tenancy/financial workflow or OCR test.

| Operation | 100k fixture | 1m fixture |
|---|---:|---:|
| Seed bookings + 12k docs + 12k tasks | 1.184 s | 9.619 s |
| Date-filter page (expected >=200 matching rows) | **0 rows**, 0.267 s | **0 rows**, 0.250 s |
| Independent SQL matching date count | 90,000 | 990,000 |
| Last 10 booking rows by deep OFFSET | 0.025 s, correct IDs | 0.153 s, correct IDs |
| Tenant docs at offset 11,990 | 0.067 s, total 12,000/tail 10 | 0.055 s, total 12,000/tail 10 |
| 10 simultaneous requests, 200 booking rows each | 0.252 s overall, all 200 | 0.233 s overall, all 200 |
| Cold summary | 1.755 s, sum 100,000 | Not run |
| Global search, unique hit at booking tail | 3.024 s, correct hit | Not run |
| Dashboard with 12k docs + 12k tasks | 0.439 s | Not run |
| 10 simultaneous summaries | 2.152 s overall, all sums correct | Not run |
| Restart (including startup allocation scan) | 7.575 s | Not run |
| App worker peak RSS | 516.0 MiB | 167.1 MiB |
| Independent SQLite SUM over every booking | Not timed in this run | 0.185 s, sum 1,000,000 |

No 5xx occurred in these bounded probes. Million-row full-table report/search/restart were deliberately left for the staged run after addressing materialization, since the 100k result already consumed >500 MiB peak on this desktop. The 1m pagination result is not evidence that 1m analytics or mixed load works.

## Confirmed defects and root causes

### P1: Booking date filtering silently omits records beyond the first 10,000

`backend/routers/bookings.py:27–49` calls `_list_paginated(...skip=0, limit=10000)` and only then filters dates and slices in Python. Both fixtures returned zero filtered rows although SQL found 90,000/990,000 matches. Ordinary unfiltered deep pagination returned the final rows correctly, isolating the failure to the date-filter branch.

Fix recommendation: apply date predicates in the SQL query before OFFSET/LIMIT, alongside account/tenant/status predicates and deterministic ordering. Preserve the in-memory store contract. Do not increase the cap: remove the total cap entirely; page size can remain bounded. Add tests with at least 10,001 pre-filter records, matches at the tail, inclusive date boundaries, account/status combinations, and skip beyond 10,000; assert no missing/duplicate IDs across pages.

### P1: Cancelling a pending ThreadPoolQueue job does not cancel execution

`backend/services/task_queue.py:120–132` discards the submitted Future, and `cancel()` only changes `TaskResult.status`. The worker unconditionally changes it back to running and invokes the function.

Reproduction: occupy the sole worker with an Event, enqueue a second side-effecting job, call cancel, then release the first. Cancel returned true and status was cancelled; the second job executed and final status became completed. See `jobs-cache.json` and `probe_jobs_cache.py`. This can execute OCR/file writes that a caller believed cancelled.

Fix recommendation: keep Futures, use actual Future.cancel with a synchronized state transition, prevent the worker from executing a cancelled task, and make cancellation of already-running jobs return false. Test blocked-worker cancellation, concurrent start/cancel, unknown IDs, repeated cancel, exceptions, and successful work. Do not rely on sleeps for ordering.

### P2: Slow cached reads expire before they can be reused

`backend/concurrency.py:110–117` and `:132–138` record `time.monotonic()` before the database load/calculation, with a 5-second TTL. If work takes >5 seconds, the freshly stored cache is already expired when the next serialized caller acquires the lock.

A fake monotonic clock advancing 6 seconds during a loader proves two immediately successive same-key calls each perform the calculation. Both `whole_table()` and `one_at_a_time()` reproduce. Real 100k cold reads already take 1.8–3.0 seconds, so scaling can cross this threshold and multiply work across queued readers.

Fix recommendation: timestamp successful completion while retaining the pre-work change version; otherwise writes during work could make a stale result look current. Test immediate reuse after >TTL work, actual expiry after completion, and writes during the slow load. Keep the global serialization question separate from this correctness/performance fix.

### P2: Result cache and completed job stores retain every result indefinitely

`backend/concurrency.py:34,:138` never evicts `_results`; the TTL only controls reuse. Synthetic 12,000 distinct responses remained after aging all entries by one hour; next request left 12,001 entries. Whole-table cache keeps its previous table list until a later reload, even when expired.

`SyncQueue` and `ThreadPoolQueue` likewise never remove `_results`. 12,000 completed synthetic jobs remained in `SyncQueue`; the probe did not claim a measured leak rate or large-job throughput. A long-lived server with many uploads accumulates every job result/error. Executor worker count also does not bound the pending submission queue.

Fix recommendation: bound ephemeral caches by expiration and an explicit maximum entry/byte budget, without imposing a total dataset cap. Preserve job history durably if needed and page it; bound RAM retention independently of how many jobs may run over the application's lifetime. For backlog handling, use explicit backpressure or a durable spool, not silent job drops. Add deterministic eviction/retention tests and a >10k-job run asserting no lost IDs or incorrect cancellation.

### P2: Tenant-account reads scan the entire booking table

`backend/repositories/finance_repo.py:75–78` filters tenant_id, but `BookingORM` (`backend/db/orm_models.py:203–226`) has only account/account-date indexes. EXPLAIN reported `SCAN bookings` at 100k and 1m.

On the 1m fixture, reading the same tenant's 1,000 booking rows three times took median **0.256 s**. Adding a temporary tenant_id index changed the plan to an index search and reduced median to **0.0155 s**, with identical IDs. Index creation took 0.796 s. The diagnostic index was dropped after the experiment; no product schema changed. See `tenant-index.json`.

Fix recommendation: add a tenant_id (or measured tenant/date) index consistently in ORM schema, migrations and schema.sql. Assert upgrade and fresh-install index presence plus tenant query plan/functional parity. Benchmark representative tenant distributions rather than adding timing-sensitive CI assertions.

### Structural scale bottleneck: eager full-table materialization

`backend/repositories/base.py:_read()` calls `.all()` and constructs a Pydantic model per row. `backend/routers/reports.py:20,:40–52` loads all bookings to compute a sum; retained whole-table cache raised app RSS from ~152 MiB to ~344 MiB. Subsequent search reached ~510 MiB peak.

`backend/routers/search.py:147` loads all bookings even for one result and eagerly invokes every entity list even after its result limit is filled. Result limits do not limit DB scan/materialization. Cold 100k tail-hit search took 3.024 s (first exploratory run 3.799 s).

`backend/app.py:152–160` invokes `allocate_unassigned()` synchronously on startup; `backend/services/payment_allocations.py:68–78` loads every allocation and booking before checking whether a booking has a tenant or needs work. `_candidates()` also scans every contract on each tenant/day candidate lookup. The existing 100k restart took 7.575 s despite no real contracts and only 100 tenant-bearing payments.

Fix recommendation: use SQL aggregations for summary/finance/cashflow and DB-side search predicates with a limited result query; evaluate only types still needed. Page/stream financial export rather than caching 1m Pydantic rows. For startup allocation, query only tenant bookings without allocations and process in chunks; use indexed tenant contracts/rent-history prefetch. Retain independent financial oracle tests for null categories, signed payments, date boundaries, receivable statuses, and decimal rounding. Run mixed 10-client analytics only after replacing these eager paths or establishing a monitored memory budget.

## Existing xstress realism and gaps

Good foundations: actual uvicorn process and SQLite WAL database, distinct authenticated roles, deterministic simulated world/ledger, business timelines, write races, restart/crash tests, exported-entity digests. `Client.all()` uses real pagination without a total-row cap.

- `tools/xstress/roles.py:217–239` claims reads overlap writes, but it starts eight reader threads after every write executor has completed; there is no writer in this phase. It also uses only four shared HTTP clients, two threads per client, rather than ten independent clients.
- Default 120 units/5 years is a domain scenario, not 100k or 1m finance rows; no cardinality argument exists for finance/docs/jobs.
- No document upload/storage/OCR queue/cancellation stress exists; 12k persisted tasks are not 12k queued background jobs.
- The crash phase uses bookings with no tenant, bypassing payment allocation and its multi-commit workflow. It checks acknowledged booking retention, not atomic booking+allocation behavior.
- `invariants.py:90–101` checks the raw booking sum against the ledger but merely calls most report endpoints; it does not assert report totals against the independent sum.
- `invariants.py:132` checks only the first 60 tenant accounts after persistence operations. Export digests cover records, but accounts outside that sample lack calculation verification.
- No run manifest containing hardware, package versions, per-phase counts, RSS, CPU, database bytes, throughput, or workload blend exists. Overall max/mean endpoints are useful but do not separate cold/warm reads or write-induced cache invalidation.
- Long client timeout (180 s) and monolithic phase execution can hide repeated cache misses; interrupted runs can lose the final report. Checkpoint findings/measurements during the run.
- `tools/xstress/core.py:Server.stop(hard=True)` refers to `signal.SIGKILL`, which is absent on Windows. The existing Windows crash phase therefore raises before the intended hard termination. Use the platform-supported process kill operation and verify the actual server child exits, including this Windows venv launcher setup.

## Recommended staged campaign

1. Preserve deterministic world/ledger business simulation separately from the cardinality fixture. Add `--finance-rows`, `--document-count`, `--job-count`, `--clients 10`, fixed seed, disposable data path, per-phase timeout and memory guard. Neither guard may truncate the data or return incomplete success; report the phase as stopped/failed with actual completed counts.
2. **100k stage**: realistic distribution across accounts, tenants, categories and signed amounts, explicit rows beyond every 10k boundary, 12k real documents/12k jobs. Seed in chunks; independently verify all counts/sums with SQL/Decimal. Read filtered/unfiltered tails, ten pages/clients, tenant accounts, summary/cashflow/search. Run 10 independent authenticated clients in a defined read/write blend (e.g. six paged readers, two analytic readers, two low-rate writers) for 30 seconds. Verify writes exactly once and reports after writes without waiting for TTL.
3. **1m stage**: same deterministic dataset extended to 1m without a row cap; validate entire count/sum and samples across the dataset. Begin with pagination and DB aggregation (the audit already verified bounded pagination). Run a single cold analytics/search request under memory/RSS monitoring; only then run ten clients with a small request rate. Capture cold, warm, and dirty-cache p50/p95/max plus errors and CPU/RSS. A desktop safeguard can stop a phase near the agreed memory budget, not convert incomplete output into a passing run.
4. **Documents/jobs stage**: 12k valid small files with known bytes/digests, varied types and tenant links; verify list/detail/download and known OCR outputs where available. Enqueue 12k controllable light jobs, bound active workers, cancel selected queued jobs deterministically, verify every job's terminal state and side effects once. Then a smaller real OCR sample so model/engine cost is measured separately. Test post-restart status/history expectations.
5. **Persistence/atomicity stage**: use SQLite online backups or stopped copies of the 1m fixture, compare database counts/digests and sums; exercise acknowledged tenant payments and allocation replacements during termination. Do not hold several 1m exported JSON/Pydantic copies in RAM simultaneously. Run each phase separately with checkpoints so an interrupted run preserves evidence.

## Handoff artifacts

- `probe_scale.py`: reproducible disposable real-server cardinality probes; default 100k/full, `--rows 1000000 --paged-only` for bounded million-row probe.
- `data-20261007-113536/measurements.json`: valid 100k process-tree counters and request outcomes.
- `data-20261007-113726/measurements.json`: valid 1m pagination counters and outcomes.
- `probe_jobs_cache.py`, `jobs-cache.json`: deterministic cancellation, cache TTL, cache/job-retention reproductions.
- `probe_tenant_index.py`, `tenant-index.json`: isolated index experiment; diagnostic index removed.

No implementation was attempted. Implementation can be split into date-filter/index correctness, queue/cache lifecycle, and analytics/search/startup query work, followed by the staged campaign above.

## Implementation verification — package 1

The baseline findings above describe eb458493. Package 1 now pushes inclusive
date bounds into both stores before pagination, adds the measured tenant booking
index, starts cache TTL after computation with a pre-work write-version guard,
releases expired response/table entries on access and stale values on writes,
and uses real Future cancellation for waiting thread jobs. Response-cache variant
count is bounded independently of stored records. In-process terminal job results
have explicit one-hour retention and cleanup; this is not durable job history or
a limit on the number of jobs/records allowed over the application's lifetime.

The updated disposable `probe_scale.py --rows 1000000 --paged-only` asserts exact
filtered first/tail IDs, unfiltered tail IDs, and ten simultaneous independent
200-row client pages. `measurements-after-hardening-1m.json` records exit-success:
990,000 date matches; first filtered page 0.0337 s; filtered final ten 1.205 s;
ten-client p50 0.3656 s / p95 0.4235 s. The child OS peak RSS was 167.34 MiB and
the product tenant query selected `idx_bookings_tenant`. Source HEAD and dirty-tree
status, platform/Python/SQLite/CPU details, process-tree counters and assertions
are recorded. The probe pins all writable paths and SQL persistence, uses an
ephemeral port and terminates only its own Windows process tree. Both server
processes were verified gone after the run.

These results are pagination evidence. Full-table reports, search and startup
allocation still need separate query/aggregation work before a monitored million
row analytic campaign. Synthetic document rows are not uploaded files, and the
12,000-callable queue regressions are not real OCR throughput. Full regression
details, intermediate failures and remaining boundaries are documented in
`.superpowers/sdd/HARDENING_20261007_PLAN/scale-report.md`.
