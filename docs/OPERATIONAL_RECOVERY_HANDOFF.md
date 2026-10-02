# Operational / tenancy workflow offline recovery handoff

Branch `assist/operational-recovery-guards`, based on
`c27ebf28af266d9f02dbe0abb65b25675d20591b`. The previous phase-one branch and
`assist/operational-jobs-core-phase1-45026b5` remain intact. This package changes
only the assigned recovery/transfer/privacy services, the two explicitly
delegated `clear_all` hooks, focused tests, and documentation. It changes no live
authentication, request authority, router, session/schema registration, migration,
frontend, Main/Preview build, server process, or legacy scheduler behavior.

## Implemented boundaries

- `tenancy_workflow_validation.validate_workflow_journal(connection, deadline=...)`
  is pure offline SELECT/inspection. It accepts a completely absent seven-table
  family, rejects partial families and even empty incomplete columns, validates
  scope parents, template/version identities, typed step definitions and iterative
  DAGs, published/retired snapshots against immutable publication receipts,
  canonical frozen start SHA/contract anchors, exact step membership/dependencies,
  original and reanchored dates, task origin/projection, terminal facts and actors,
  required witnesses, finalized handover/meter snapshots, exact archived document
  originals, operation/subject/portfolio receipts, and immutable response bindings.
  Earlier mutable states/revisions/frists need not equal current rows. A supported
  later ContractPatch party correction preserves the historical start proof.
  Historical deleted/deactivated actor authorization is never queried.
- Global row iterators fetch in batches; per-aggregate template/step/DAG collections
  remain complete. There is no total 100/10,000-row truncation. Existing caller
  deadlines remain explicit, and timeout rejects without publishing a partial
  image. No Store, create_all, live auth, caller commit or schema repair appears in
  the pure validator.
- The three-table job family now verifies required columns even when empty.
  `full_recovery._database_info`, `recovery_validation._scan`, and
  `recovery_sessions.invalidate_and_inspect` validate both families before any
  file-rebase/security DML. The full metadata loop omits only entirely absent old
  families; partial families are never repaired implicitly.
- Claim invalidation calls the existing `reset_restored_job_claims` only after all
  offline journal/original/encryption/private-draft checks pass. It stays in the
  same caller-owned transaction as session revocation and signing-configuration
  publication. An old restored worker loses its lease/fence; a fresh authorized
  worker resumes the retained worklist. Later session/configuration failure rolls
  claims back too. The security result protocol remains its original two fields.
- Generic business-JSON export, merge/replace import, and direct Memory/SQL reset
  refuse existing facts from either family and direct callers to full offline
  recovery. They never silently omit or delete retained facts. SQL checks pending
  ORM new/dirty/deleted rows under no_autoflush and committed existence via LIMIT 1,
  then rechecks after writer serialization. PostgreSQL takes account first and
  domain parents before workflow/job children; EXCLUSIVE NOWAIT in a Connection
  savepoint converts a busy writer to a recoverable ValidationError while keeping
  the caller's outer transaction usable. The actual paused first-template race
  with SQL storage and Memory authentication proves zero reset DML.
- Privacy Memory staging serializes the new ORM facts by column values. An
  unchanged staged copy succeeds, and a real concurrent value change still
  conflicts. All workflow/job history remains retained.

## Validation on this package

Interpreter: `outputs/ImmoManager-Pro/.venv/Scripts/python.exe` from the workspace.
Actual PostgreSQL 16.15 service: `127.0.0.1:58112`, synthetic `immo_ci` only; every
test owns its random schema and never uses public/application data.

| Gate | Actual result | Log in workspace `work/` |
| --- | --- | --- |
| Both new test modules, Memory/SQLite plus configured native PostgreSQL | 51 PASS, 50 expected fixture/platform SKIP, 217.92 s | `operational-recovery-final-new-families.log` |
| Independent native PG selection | 11 PASS, 2 expected non-PG variants of the named PG race SKIP, 85 deselected, 56.44 s | `operational-recovery-final-native-postgres.log` |
| Native race plus ordinary historical contract correction, run independently | 3 PASS, 3 expected unsupported-backend SKIP, 15.35 s | `operational-recovery-final-races-confirmed.log` |
| Existing recovery/session/correspondence/lifecycle/transfer/privacy plus phase-one jobs/HTTP/migration/PG, default Memory application backend | 183 PASS, 6 expected SKIP, 1 known base-branch migration FAIL, 313.29 s | `operational-recovery-final-regressions.log` |
| Existing recovery/session/correspondence/lifecycle/transfer/privacy with TEST_STORE_BACKEND=sql and fallback disabled | 133 PASS, 2 expected SKIP, 1 known base startup-registration FAIL, 255.84 s | `operational-recovery-final-strict-sql.log` |
| Ruff, all 10 owned runtime + 2 test files | PASS | `operational-recovery-final-ruff.log` |
| Mypy 3.11 and 3.12, all 10 owned runtime files | Both PASS | `operational-recovery-final-mypy311.log`, `operational-recovery-final-mypy312.log` |

The sole broad default-backend failure is
`test_operational_jobs_migration.test_actual_migration_and_nonempty_downgrade_guard`:
base c27 has independent b2/c2 Alembic heads and `upgrade head` refuses. Root owns
and has already integrated the linear a2 -> b2 -> c2 chain on its later source.
No assertion, migration, budget, or runtime behavior is changed here to hide it.
Root must rerun actual composed migrations after cherry-pick.

The strict-SQL failure is `test_tenant_privacy.test_http_export_preview_confirmation_permissions_and_error_statuses`
at its initial `store.clear_all()`: base c27 creates the global test schema before
the newly registered workflow metadata is imported and DELETE subsequently sees
missing `tenancy_workflow_evidence_links`. Root owns and has already added both
families' startup registration on its later source. This package does not hide
the failure with schema repair or skip missing tables during generic reset.
The isolated new-family fixtures create their whole disposable schema explicitly
and prove the actual SQL/PG retention guards. Root must rerun the composed
strict-SQL test, preserving its later runtime registrations.

The new native SQLite cases use real service-created histories and disposable
copied images with deliberately disabled immutability triggers for corruption.
They cover whole pre-family images, each partial family, empty bad columns,
snapshot/hash manipulation, parent swaps, original dates, task projection,
command subjects, seven malformed immutable start-response/actor variants,
evidence hash/parent/shape, archived original bytes, and terminal facts. Invalid
images remain byte-for-byte unchanged before security publication.

The encrypted full-archive roundtrip retains exact rows in all seven workflow
tables, including retired template publication, completed and open/cancelled
tasks, reanchoring and three witness kinds. It retains planned job items, releases
restored claims, rejects the original worker fence, and resumes eight overdue
sources over a positive budget of seven. Separate later session/signing failures
prove full caller-owned claim rollback.

The existing reviewer performed source-only review in
`work/operational-recovery-independent-review.md`; the three initial P1/P1/P2
findings were corrected and rechecked. Native execution evidence comes from this
author's logs, not from an invented independently run test. The final race also
adds explicit before_cursor_execute DML capture after the review's earlier note.

## Exact remaining integration / assurance limits

1. Workflow commands retain `request_sha256` without the original request. Its
   format and available immutable response/source facts are checked, but an
   original request hash cannot be reconstructed. Hashes and authenticated outer
   archives do not invent a complete historical event log.
2. `tenant_data_graph` still has no workflow/job subject-disclosure projection.
   Frozen tenancy snapshots can retain tenant names and historical command
   responses. This package preserves these facts during profile anonymization;
   it does not claim that the existing scoped export/count/hash includes them.
   Root must extend the coherent subject graph and reviewed retained-fact counts
   before declaring the new families fully covered by the privacy UI/export.
3. On base c27 normal Property.portfolio_id / Unit.property_id mutation guards
   consult lifecycle/correspondence but do not consult workflow templates/changes.
   b2 freezes workflow rows but lacks inverse live scope-parent guards. This is a
   static integration candidate, not an executed new parent-move repro here.
   Root owns ordinary mutation/scope/schema policy. It must protect these live
   scope parents or explicitly define supported historical relocation semantics;
   the offline validator intentionally requires a coherent live scope chain.
4. Production startup registrations, migration rechain/shared b2 guards, authority
   hooks and composed runtime routing remain Root's responsibility. Completely
   old offline images are accepted without fabricating new schema; subsequent
   explicit runtime migrations remain necessary before using new features.
5. This is offline retention/recovery integration for the two implemented jobs
   and workflow core. It does not replace the remaining legacy all-or-nothing
   scheduler lanes or introduce unrelated P1 phases/UI behavior.

Cherry-pick the single final commit onto Root; compare precisely the two small
`clear_all` additions because Root has later independent Store and schema changes.
Preserve Root's newer token/runtime/guard/migration edits.
