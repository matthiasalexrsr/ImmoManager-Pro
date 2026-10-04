# Native PG16 inbox guard cases: contract before source

Scope is one new native test file plus this plan/handoff. No product, existing
test, fixture helper, shared validator, registry, recovery or migration changes.
Root source basis is 1fce39f (adapter integrated through d9fbe5b). Own sources
are prepared on b0aaa23; they must be executed in Root after cherry-pick, using
Root's actual central helper with its native address and savepoint fixes.
No imports, tests, SQL, app or server processes are started here.

Use only `postgres_proposal_database(TEST_SERVER_DATABASE_URL)` from
`backend.tests.notification_inbox_pg_proposal_support`. It owns dedicated URL
validation before every connect, random UUID business schema, pg_catalog admin,
bounded connect/pool/SQL/lock/30-second node budget and unconditional handle,
pool/schema cleanup. Reuse that helper without a replacement or mutation.
The 1fce39f RollbackToSavepointClause exception is needed when testing native
expected constraint failures; it prevents extra fixture SQL inside a failed
savepoint before PostgreSQL's genuine rollback restores the transaction.

Every test starts in its own UUID schema, creates minimal synthetic users and
notifications parents and runs the **real reserved M2 Operations.upgrade** from
the proposals directory. It does not activate the global L2/M2 migration chain.
One valid personal read row provides actual native data. Empty synthetic parent
IDs are deliberately legal only in this disposable fixture so the two positive
blank-ID probes cannot be mistaken for foreign-key rejection.

## Exactly nine prepared native nodes

1. `test_native_m2_operations_guard_is_active_and_readonly_proof_passes`:
   real Operations M2 revision/down_revision and actual native adapter acceptance;
   two real blank-ID inserts fail inside genuine savepoints with SQLSTATE 23514
   and exact ck_notification_read_identity. Valid row/transaction survives.
2. `test_native_missing_identity_check_refuses_without_repair`:
   drop only that constraint; native adapter returns fixed guard_missing.
3. `test_native_changed_check_semantics_refuse[or]`: real OR guard refuses.
4. `test_native_changed_check_semantics_refuse[other-field]`: real guard uses
   read_at instead of notification_id; actual conkey/native binding refuses.
5. `test_native_not_valid_identity_check_refuses`: same canonical native
   expression but actual convalidated false; fixed guard_invalid.
6. `test_native_own_schema_same_named_length_cannot_replace_builtin_proof`:
   create length(text) in the **own UUID schema**, explicitly reference it in
   the CHECK, verify its actual pg_proc OID occurs in native conbin, and show a
   blank actor can pass that weakened guard. Native proof must refuse it.
   No function/operator/system catalog in pg_catalog is modified.
7. `test_native_same_named_view_is_not_the_selected_base_relation`: rename
   the real table inside the own schema and create a same-named view; actual
   visible kind/identity differs and native proof refuses catalog_invalid.
8. `test_native_wrong_selected_schema_cannot_borrow_visible_business_table`:
   select pg_catalog before the own UUID schema using SET LOCAL search_path;
   the actual valid table is still visible but selected schema is wrong and
   native proof refuses. Only native catalogs are read in pg_catalog.
9. `test_native_connection_temp_shadow_cannot_borrow_main_guard`: connection-
   local TEMP table masks the valid UUID-schema table; verify actual OID
   mismatch, require catalog_invalid, and drop TEMP on commit/connection cleanup.

Fixture DDL/DML establishes explicit counterexamples before the proof. During
each adapter call capture the real SQLAlchemy Connection statements: SELECTs
only, unchanged current transaction object, unchanged relevant native catalog
and data fingerprint before/after, same selected schema/OIDs. The central helper
sets timeouts through its independent DBAPI cursor; those owned fixture settings
are not counted as validator schema mutations. The positive adapter proof runs
also in an actual READ ONLY transaction after fixture setup commits. No fake
Connection, parsed DTO capability, bool/lambda fence or provider action is used.

Root runs the exact new file under source freeze, serially with an explicit
outer budget (suggestion hard120, helper nodes30 + cleanup8). Failures and skips
must be reported separately. Missing/invalid dedicated URL is a setup failure,
never a skip counted as evidence. Actual server must identify itself as PG16;
no monkeypatch of version or false claim of native PG17/other-ABI refusal.
Unknown server versions remain an honestly documented unsupported boundary.

Shared validator wiring, startup, full recovery, active schemahead, Sid/account/
parent commit authority and any mark-read action remain outside these tests.
