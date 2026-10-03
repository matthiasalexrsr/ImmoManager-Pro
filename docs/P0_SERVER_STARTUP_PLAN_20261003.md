# P0: predictable server startup and release gates

Base: `679c8de9a97074f513bf611f7c636d40f2002fea`, 3 October 2026.
This plan is recorded before source changes. Scope is normal production startup,
explicit first installation, the conflicting development dependency entrypoint,
and PostgreSQL gates for already integrated features. No new migration family,
integration-history implementation, backup automation, or live installation change.

## Decisions

1. The container entrypoint prepares its temporary directory and executes the
   requested command. It never implicitly runs Alembic. Fresh private-server
   installation explicitly starts the database, builds the app, runs `alembic
   upgrade head` once, then starts the app. The smoke workflow and operator guide
   use that same sequence. Restoration starts the already restored schema.
   The development Compose smoke also explicitly installs before launch. The
   Windows guide distinguishes fresh installation from existing unversioned data;
   the production desktop launcher shares the same no-DDL startup rule.
2. Production dependency initialization performs read-only schema validation:
   the installed Alembic revision must equal the bundled migration head and all
   registered application tables/columns must exist. Missing, older, newer,
   unversioned, or incomplete schemas fail with actionable fixed diagnostics;
   the process neither stamps nor repairs them. The metadata includes all current
   retained workflow, job, document, financial and authentication families. This
   startup check is a structural compatibility check, not a backup/integrity proof.
3. Production rejects direct use of the development `create_tables` helper.
   Development and existing test fixtures keep their explicit legacy additive
   initialization behavior. Production configuration is validated before the
   lifespan auto-migration branch; unsafe `AUTO_MIGRATE=true` cannot execute DDL
   and only then discover that production disallows it.
4. `backend/requirements-dev.txt` inherits its pytest version from the root
   application requirements instead of declaring the contradictory second exact
   version. CI consumes this development entrypoint; its QA tools are pinned to
   the versions verified in the shared test runtime. Root additionally requested
   `pdfplumber==0.11.9` and a mandatory Python 3.12/SQL PDF layout gate; this remains
   outside production dependencies. Root's housing commit supplies that test.
   Full transitive dependency locking belongs to a separate follow-up.
5. Add actual PostgreSQL release selections for workflow concurrency, operational
   jobs/runtime, retained tenant disclosure/privacy fences and the new startup
   proof. A small reusable gate verifies actual passing PostgreSQL cases from
   pytest's report; missing collection, skipped-only PG execution or test failures
   fail the gate. Pure Memory/SQLite variant skips remain honest and allowed.
   Root's housing package additionally supplies the mandatory PostgreSQL housing
   permission/commit tests. Those sources are absent from this base checkout;
   their execution is an explicit Root composition requirement.

## Required evidence

- Fresh Alembic SQLite schema can import and run the actual production app under
  a native SQLite authorizer that denies DDL; schema catalog remains unchanged.
- Empty, wrong-revision, and damaged retained-family schemas refuse startup
  without repairing catalog objects; a malformed production configuration cannot
  cause auto-migration before rejection.
- A real PostgreSQL schema migrated in an exclusive disposable schema starts
  the production app with a role that has ordinary table access but no schema DDL
  privileges; startup must not attempt CREATE/ALTER/DROP or seed schema state.
- The real container entrypoint with default settings executes its command
  without invoking migration. Installation remains explicit in the real Linux
  container smoke gate; local Docker availability determines whether that full
  gate can also run here, never a substitute success claim.
- Existing startup-family, migration/schema, production-config, server-admin,
  private-server smoke and affected privacy/workflow/job regression tests remain
  applicable. Run focused checks first and report exact sources/results.

## Publication

Commit only this isolated worktree. Handoff includes files/behavior changed,
actual checks, environment skips and upgrade instructions. Root composes this
with other feature packages and performs final current-head release validation.
