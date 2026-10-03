# P0 server startup and PostgreSQL acceptance handoff

Base: `679c8de9a97074f513bf611f7c636d40f2002fea`.
Branch: `assist/p0-server-startup`. Date: 3 October 2026.
The plan was recorded in `P0_SERVER_STARTUP_PLAN_20261003.md` before source edits.
No live installation, business database, Root worktree or migration revision was
changed. All native database tests used disposable local files or UUID schemas.

## Result

- Production dependency initialization validates the installed Alembic head and
  registered tables/columns using reads. An incompatible, unversioned or damaged
  database fails with a maintenance instruction and is never silently stamped,
  repaired or replaced by Memory. Direct production `create_tables()` is blocked.
- Production configuration is checked before the lifespan auto-migration branch.
  `AUTO_MIGRATE=true` therefore cannot migrate and only subsequently be rejected.
- The shared container entrypoint executes its requested command without an
  implicit Alembic call. Both container smoke installers explicitly build, start
  the database, run `alembic upgrade head`, then start the application.
- Development/test additive initialization remains available. Production Windows
  startup shares the guard; README explains explicit fresh installation and the
  separate backup/copy validation required for an existing unversioned database.
- `backend/requirements-dev.txt` inherits the sole pytest pin from root
  requirements and pins QA tools, including test-only `pdfplumber==0.11.9`.
  The backend CI matrix installs this file. This is not a full transitive lock.
- Additional PostgreSQL CI groups cover the complete tenancy workflow core,
  concurrency, bounded reference lookup, persistent jobs, retained subject
  disclosure/privacy fences, actual schema migration and production startup.
  The gate requires real passing PostgreSQL identities in pytest's report;
  zero cases, skips, errors, failures and non-PostgreSQL cases cannot pass.
  The `-k postgres` selection excludes Memory/SQLite variants before execution.
- First execution of the new disclosure gate exposed a real test-isolation bug:
  its first case lacked `credit_receipts` until a later case imported the model.
  A module-local fixture now prepares the full domain for each disposable SQL
  image. Subject projections, foreign-data exclusions and hash assertions remain
  unchanged, including deliberate old/partial-schema tests.

## Executed acceptance

Shared local test interpreter was Python 3.14. Linux Python 3.11/3.12 remain CI
composition requirements; no claim that their hosted runs executed locally.

| Actual command group | Result | Evidence in workspace `work/` |
| --- | --- | --- |
| Production startup, PG runner negatives, workflow runtime, migration schema contract, server admin, outbox integration, private-server smoke sessions; strict SQL backend without PG URL | 52 passed, 5 expected PG skips; 626.00 s | `p0-server-startup-sql-composed.log` |
| PG workflow concurrency, operational jobs, two actual runtime/migration cases, native-role production startup | 10 passed, 3 deselected, zero skips; 118.23 s | `p0-server-startup-postgres-core.log` |
| PG tenancy workflow core and bounded references | 15 passed, 28 deselected, zero skips; 191.56 s | `p0-server-postgres-workflow-core.log` |
| Exact new retained-disclosure/privacy PG CI selection after fixture repair | 32 passed, 64 deselected, zero skips; 234.80 s | `p0-server-postgres-privacy-green.log` |
| Individually selected original disclosure case, Memory and SQLite | 2 passed, 1 deselected; 9.83 s | `p0-disclosure-fixture-memory-sqlite.log` |
| Canonical development requirements resolution (`pip install --dry-run`) | Exit 0, no dependency conflict | `p0-dev-requirements-dry-run.log` |

The three PG groups are separate actual executions, not a claimed single run of
the final composed CI command. The initial disclosure run was 31 passed/1 failed
before the fixture fix; it is not release evidence. The initial startup negative
tests also exposed error wrapping that masked the maintenance instruction; the
final 52-case group verifies the corrected error propagation.

Native no-DDL proof uses SQLite's actual authorizer and a PostgreSQL role without
schema DDL privileges. A real `CREATE TABLE` under that role is rejected with
SQLSTATE 42501, then a separate real app import/lifespan succeeds under the role.
The real shell entrypoint runs beside an executable migration tripwire. Empty,
wrong-revision and incomplete retained-family catalogs remain unchanged after
rejected startup. Explicit production Alembic installation is also exercised by
the outbox production subprocess fixture.

Changed-source Ruff passed; six changed production Python modules passed mypy.
Both shell files passed Bash syntax validation; `git diff --check` passed.
The existing Starlette/httpx deprecation warning remains in some test groups.

## Root composition and remaining release gates

Root's Housing package is absent from this base checkout. The committed CI
selection intentionally requires its `test_housing_confirmation_postgres.py`
and the unconditional `test_housing_confirmation_pdf_layout.py` acceptance on
the Python 3.12/SQL profile. Root must retain its account-commit fence and glyph
layout regressions when composing this package. Those tests were not executed
from this checkout; Root reported its native Housing results separately.

There is no Docker executable on this host. Full actual Linux container initial
installation, backup/resume, restore and restart remain the mandatory existing
`private-server` workflow and development `e2e-smoke` gates. Shell syntax and
entrypoint execution do not substitute for those lifecycle runs.

Root must run current-head composition validation after integrating later schema
families. The validator dynamically reads the bundled single migration head and
registered metadata; it adds no competing migration revision. Structural startup
compatibility is not a complete journal-integrity or backup verification claim.

Full backup automation and replacing the legacy scheduler tick with persistent
operational jobs are separate next packages; this change does not claim them.
