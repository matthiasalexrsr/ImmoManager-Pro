# Native PG16 guard test source handoff (unexecuted)

Precode plan: 58f7545. Only new test and documentation files. Source expects
Root's centrally integrated adapter d9fbe5b and central fixture **1fce39f or
later**, including real target-address validation and genuine savepoint rollback.
Neither helper nor any shared product file was changed. Own old helper source
is intentionally not used for an execution claim; run after integration in Root.
No Python/import/lint/test/SQL/server/app process ran here. Git source/whitespace
checks do not establish a passing test result.

Exact prepared nodes in `backend/tests/test_notification_inbox_pg16_check_native.py`:

```text
test_native_m2_operations_guard_is_active_and_readonly_proof_passes
test_native_missing_identity_check_refuses_without_repair
test_native_changed_check_semantics_refuse[or]
test_native_changed_check_semantics_refuse[other-field]
test_native_not_valid_identity_check_refuses
test_native_own_schema_same_named_length_cannot_replace_builtin_proof
test_native_same_named_view_is_not_the_selected_base_relation
test_native_wrong_selected_schema_cannot_borrow_visible_business_table
test_native_connection_temp_shadow_cannot_borrow_main_guard
```

Suggested Root command, serially under its actual native slot/source freeze and
hard120 outer wrapper (central helper: each node30, separate cleanup8):

```powershell
$env:TEST_SERVER_DATABASE_URL = 'postgresql://immo_ci@127.0.0.1:58112/immo_ci'
& 'C:/Users/matth/Documents/Codex/2026-10-01/wi/outputs/ImmoManager-Pro/.venv/Scripts/python.exe' -m pytest --noconftest -q backend/tests/test_notification_inbox_pg16_check_native.py
```

Only the central helper opens native connections/owns UUID schemas and cleanup.
No fallback URL, skip, version stub or alternative engine exists in this file.
It asserts the actual server identifies PG16; other versions remain an
unexecuted unsupported boundary. The positive case runs actual proposal
Operations.upgrade (M2 down L2), then genuine READ ONLY validation and two actual
savepoint-protected blank-ID inserts, checking SQLSTATE 23514 and the real
constraint name. Synthetic blank parent IDs isolate CHECK from FK rejection.

Counterexamples use only the owning UUID schema and the owning connection's
TEMP table. The same-named function belongs to that UUID schema and is
explicitly referenced: native pg_proc OID must appear in the real stored tree,
and its weakened guard actually accepts a blank actor. This setup assertion is
not a substitute for the adapter's full AST/catalog proof. No pg_catalog object
is created, modified or replaced. The wrong-schema case only selects pg_catalog
before the own schema and still resolves the valid visible business relation.

Each adapter call captures SELECT-only actual Connection statements and compares
relevant catalog/data/context fingerprints before/after, retaining the same
active transaction object. Root's helper independently sets its fixture-owned
timeouts; those DBAPI statements are not validator DDL/DML. Owned data captures
cover only one or two known synthetic read rows, never a production stock.

After these actual results, Root still owns shared validator wiring and its
composite proof/HTTP/recovery rechecks. This file proves no global migration
activation, cold startup, Auth/Sid commit lifetime or enabled mark-read action.
