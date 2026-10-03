# Tenancy workflow SQL concurrency handoff

Parent/core commit: `2cad91f1047ebc6a58f3e4a03afa9eef055d6fc1`
Branch/worktree: `assist/tenancy-workflow-core` / `work/tenancy-workflow-core`

This follow-up is test-only. It adds
`backend/tests/test_tenancy_workflow_concurrency.py` and does not change
production code, DTOs, runtime registration, recovery, privacy, Main or Preview.

## What the new gate proves

The test is parameterized over real SQLite and the disposable PostgreSQL service.
Each PostgreSQL parameter owns a fresh random
`tenancy_concurrency_<uuid>` schema, creates only inside that schema, disposes
all worker engines/sessions, and drops the schema in fixture teardown. SQLite
uses one temporary WAL database and independent pooled connections.

Concurrency is synchronized at the service's first writer boundary with
`threading.Barrier`. The hook exists only inside the test and is restored before
post-race verification. There are no sleeps or timing-window assertions. Each
race records the underlying DB connection identity and asserts two distinct
connections were actually used.

Three scenarios are covered:

1. Two independent workers submit the exact same start command and idempotency
   key. Both calls succeed with the same saved response, while the database has
   exactly one `TenancyChange` and exactly one start receipt. A subsequent
   explicit replay returns the same response without creating more rows.

2. Two independent workers use different start keys for the same active
   previous-contract role. Exactly one succeeds; the other is an HTTP 409.
   Exactly one active change and one successful start receipt remain.

3. A started change has one exact immutable document-version original linked as
   step evidence. Two independent workers submit different step command keys
   with the same step revision and the same parent-change revision. Exactly one
   completion succeeds and the other is HTTP 409. The document-version identity,
   manifest metadata, SHA-256, size, every stored original chunk, and the
   evidence-link snapshot are compared before/after and must be byte/value
   identical. Only one update-step receipt remains.

The tests intentionally do not cover or alter the separately reported
Memory receipt-path binding or meter UPDATE old-parent issue. Root owns those
production corrections and should run this test file again on the composed
source after applying them.

## Gates run on this follow-up

With
`TEST_SERVER_DATABASE_URL=postgresql://immo_ci@127.0.0.1:58112/immo_ci`:

`pytest backend/tests/test_tenancy_workflow_concurrency.py -q -rs --tb=short`

Result: **6 passed** (3 scenarios x SQLite/PostgreSQL), no skips.

Static test-file checks:

- Ruff: passed.
- `py_compile`: passed.
- `git diff --check`: passed before commit.

No production or application data is used; all fixtures are synthetic.
