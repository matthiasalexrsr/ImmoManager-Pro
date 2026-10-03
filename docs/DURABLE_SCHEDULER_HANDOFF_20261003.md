# Durable scheduler E handoff

Own checkout: `work/durable-scheduler`, branch `assist/durable-scheduler`.
Initial integration base: `5e636e0`. No live preview/business database modified.

## Commits and integration order

1. `0cc9590`: plan before implementation.
2. `d71204eb5259cc2433f08f9aea2135dc76d3e870`: E1 coordinator and two recurrence families; incomplete compatibility checkpoint.
3. `64732dd`: minimal runtime/recovery/privacy metadata hooks, centrally composed by Root.
4. `33f73ea`: E2, replaces the compatibility pass with all remaining durable families.
5. Domain C's actual `g2a2b3c4d5e6` predecessor must be present before h2.
6. `4e15dc4`: h2 source/progress indices and native migration tests.

f2 remains unchanged at revision `f2a2b3c4d5e6`, parent `e2a2b3c4d5e6`.
h2 is `h2a2b3c4d5e6`, parent `g2a2b3c4d5e6`. This checkout deliberately does
not invent/copy a placeholder g2. Complete migration-head/startup testing after
h2 belongs to the real Root composition. Native h2 operations were executed on
both disposable SQLite and PostgreSQL databases.

## Final behavior

An explicit active installation-wide manager/owner owns automatic generations.
The persisted generation key is reserved before job creation, and the exact
job receipt is recovered even if the process dies before attachment or software
family defaults change meanwhile. Existing frozen job parameters remain intact;
the next generation uses the new families. Status reports the attached job's
actual family set. Manual jobs are never implicitly adopted.

Automatic work uses all twelve durable families: overdue rent, overdue
receivables, approved correspondence, task recurrence, calendar recurrence,
task deadlines, maintenance deadlines, maintenance appointments, due-task
notifications, contract expiry, escalations and alert resolution. Each uses
bounded discovery/execution and the existing atomic business-effect journal.
The old automatic compatibility pass is gone. Manual legacy atomic endpoints
retain their previous explicit atomic semantics and resource checks.

Full catch-up processes the complete anchored history, independent of lookback.
Task one-open-child behavior remains unless full catch-up is explicitly chosen;
calendar schedules retain their configured full-catch-up policy. New version 3
progress can reuse an unchanged completed full-history proof. Version 2 or
non-full proofs cannot hide earlier gaps. Moved/deleted generated objects keep
immutable occurrence tombstones; late legacy children are adopted by original
date. Unchanged projections avoid new per-source work records. Escalation rules
have their own bounded target cursor, so more than 10000 targets remain resumable.

Source/notification locks and the final database-time lease/account fences
cover publication. Contract-expiry work/effect identities are included in the
existing actual-contract-subject disclosure. Scheduler metadata participates in
memory privacy snapshots, retained reset fences, and explicit offline validation
and claim invalidation. No email/external effects are introduced.

## Actual validation

Logs are sibling files under `work/`, not repository artifacts:

- `durable-scheduler-postgres-restarted.log`: E1, **4 native PG cases passed**, no skips, 60.87 s; killed subprocess at reservation, unattached creation and committed packet, independent workers, offline fence rollback.
- `durable-scheduler-e2-10k.log`: **2 passed**, 242.11 s; 10003 anchored daily occurrences from 1990 at lookback=1, plus 10003 escalation targets and 10003 task calendar effects, actual session restarts and fair other-family progress.
- `durable-scheduler-e2-long-history.log`: **3 passed**, including 35/36-year series and automatic configuration above former 3660-day/5000-item validation ceilings.
- `durable-scheduler-e2-regression.log`: **86 passed, 4 documented fixture skips**, 222.16 s; Memory/SQLite jobs, operations, coordinator and pre-h2 production startup. This is not PostgreSQL release evidence. Later focused upgrade/legacy tests cover subsequent changes.
- `durable-scheduler-e2-upgrade.log`: **4 passed**, exact old unattached receipt recovery and long-history proof reuse.
- `durable-scheduler-e2-late-legacy.log`: **2 passed**, late imported child adoption after completed-progress reuse.
- `durable-scheduler-e2-postgres-fixed.log`: **31 native PostgreSQL cases passed**, 260.16 s, strict runner confirmed no skips. Includes existing job concurrency and retained-disclosure/subject/hash cases. The previous run's single failure was a pre-job fixture that had not removed the newly referencing scheduler table; the fix removes that later table only when constructing a genuinely pre-job image. Assertions remain intact.
- `durable-scheduler-e2-final-scheduler-pg.log`: **5 native PostgreSQL cases passed**, 103.36 s, strict no-skip runner after the final upgrade-recovery change. Includes all projection families under two independent workers, restart/crash tests and actual tenant disclosure.
- `durable-scheduler-h2-native.log`: **3 passed**, 74.09 s; native SQLite/PG h2 operations and repeated full 10003-occurrence test with both new indices.
- `durable-scheduler-h2-ddl.log`: **3 passed**, 15.21 s; exact DDL/index definitions, preserved source row, native SQLite lookup plans, repeated upgrade compatibility and refusal of a malformed same-name index.
- Focused Ruff checks passed. Mypy passed for seven services and scheduler model. No Docker runtime was available or claimed.

CI's strict PostgreSQL selection now includes the scheduler file and explicit h2
PostgreSQL case. A missing service, skipped case, empty selection or a non-PG
case cannot count as PostgreSQL success.

## Test service ownership and remaining integration work

The existing synthetic cluster was recovered once after Root verified no server
remained. It listens only on `127.0.0.1:58112`; database/user `immo_ci`. Tests own
UUID schemas and never touch business data. Shared service stays running for
Root/Domain/UI. Server PID at restart was 1676; shell session 42700 remains a
service-lifetime parent because Windows Start-Process waits for descendants.
Do not terminate that session as though it were an abandoned test.

All E test command sessions are complete. Root still must compose real g2->h2,
check current recovery-family hooks against concurrent HistoryRuntime changes,
and run the integrated release gates. UI labels/status should account for all
twelve family names. E does not implement package L's encrypted full-backup
planning or isolated restore probes; those are explicitly separate next work.
