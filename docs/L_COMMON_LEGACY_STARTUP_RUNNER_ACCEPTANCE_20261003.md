# L/A common legacy, full-recovery, startup and runner acceptance

Exact tested own source: `348e1d159d104a134366315bfdeda111111937c8`, branch
`assist/legacy-sqlite-upgrade`, checkout `work/legacy-sqlite-upgrade`. This merges
the requested clean Root `d40ea9c` into the previously completed legacy package
and whole-period party/recovery composition. Root alone integrates. No tested
source changed during either run. No fixture or product correction was needed.

Roadmap, legacy backup-proof composition plan, startup composition plan and
backup automation handoff were inspected before selecting exact nodes. This
gate does not repeat the separate legacy-upgrade service suite.

Only fresh owned synthetic databases, keys, file bytes and process handles were
used. Production startup here means the actual app import/lifespan under
production settings against an owned test database with disabled providers and
workers; no user's product installation or private database was started.
Backup runner uses an isolated synthetic app shim with real Uvicorn and a real
SQLite writer. No task/service or real Docker project was registered.

## Shared runtime and exact commands

Interpreter for both serial runs:
`C:/Users/matth/Documents/Codex/2026-10-01/wi/outputs/ImmoManager-Pro/.venv/Scripts/python.exe`.
Working directory:
`C:/Users/matth/Documents/Codex/2026-10-01/wi/work/legacy-sqlite-upgrade`.

```powershell
& 'C:/Users/matth/Documents/Codex/2026-10-01/wi/outputs/ImmoManager-Pro/.venv/Scripts/python.exe' -m pytest backend/tests/test_legacy_full_backup_composition.py backend/tests/test_production_startup.py::test_actual_production_import_and_lifespan_succeed_when_native_driver_denies_ddl backend/tests/test_full_backup_startup_composition.py::test_native_central_import_is_fenced_before_settings_sql_logs_and_workers backend/tests/test_full_backup_startup_composition.py::test_manual_offline_backup_refuses_held_lifetime_before_plan_and_sql -q --no-cov --tb=short
```

Result: **10 PASS**, no skips/deselection, **87.16 seconds**.
The preceding exact collection reported ten nodes; no additional tests were
selected by substring matching.

```powershell
& 'C:/Users/matth/Documents/Codex/2026-10-01/wi/outputs/ImmoManager-Pro/.venv/Scripts/python.exe' -m pytest backend/tests/test_full_backup_operations.py::test_real_backup_resume_replica_monthly_portless_restore_and_copy_retry backend/tests/test_full_backup_operations.py::test_killed_offline_worker_durable_resume_even_when_plan_is_disabled backend/tests/test_full_backup_server_contract.py -q --no-cov --tb=short
```

Result: **5 PASS**, no skips/deselection, **67.77 seconds**. Two are actual
synthetic Uvicorn/SQLite runner tests; three are explicitly FakeDocker contracts,
not evidence of an actual Docker daemon deployment.

## Exact passed NodeIDs and their implications

| NodeID | Actual proof |
|---|---|
| `backend/tests/test_legacy_full_backup_composition.py::test_actual_full_backup_restore_preserves_exact_proven_legacy_catalog_and_rows[release126-fresh-create-all]` | Actual encrypted full-container restore; positive complete native old profile; source bytes unchanged; reversal/upload/integration bytes preserved; restored signer rotated. |
| `backend/tests/test_legacy_full_backup_composition.py::test_actual_full_backup_restore_preserves_exact_proven_legacy_catalog_and_rows[release126-historical-receipt-checks]` | Same actual container/restore proof for the exact historical financial-check profile. |
| `backend/tests/test_legacy_full_backup_composition.py::test_changed_legacy_catalog_cannot_use_missing_column_exception[release126-fresh-create-all-guard]` | Weakened original guard refuses before archive publication; source bytes survive. |
| `backend/tests/test_legacy_full_backup_composition.py::test_changed_legacy_catalog_cannot_use_missing_column_exception[release126-fresh-create-all-index]` | Changed native index cannot borrow the narrow positive-proof exception. |
| `backend/tests/test_legacy_full_backup_composition.py::test_changed_legacy_catalog_cannot_use_missing_column_exception[release126-historical-receipt-checks-guard]` | Same guard refusal for the historical financial-check profile. |
| `backend/tests/test_legacy_full_backup_composition.py::test_changed_legacy_catalog_cannot_use_missing_column_exception[release126-historical-receipt-checks-index]` | Same index refusal for that profile. |
| `backend/tests/test_production_startup.py::test_actual_production_import_and_lifespan_succeed_when_native_driver_denies_ddl` | Actual app imports and lifespan twice with native SQLite authorizer refusing schema DDL; observed DDL remains empty and original catalog unchanged; production create_tables is refused. |
| `backend/tests/test_full_backup_startup_composition.py::test_native_central_import_is_fenced_before_settings_sql_logs_and_workers[backend.app]` | Actual module import under another held kernel lease refuses before settings/auth/SQL/log/worker imports or source writes. |
| `backend/tests/test_full_backup_startup_composition.py::test_native_central_import_is_fenced_before_settings_sql_logs_and_workers[backend.dependencies]` | Same real early import boundary through direct dependencies import. |
| `backend/tests/test_full_backup_startup_composition.py::test_manual_offline_backup_refuses_held_lifetime_before_plan_and_sql` | Real installation lease prevents manual backup selection/SQL while a supported lifetime owns it; source bytes unchanged. |
| `backend/tests/test_full_backup_operations.py::test_real_backup_resume_replica_monthly_portless_restore_and_copy_retry` | Real Uvicorn writer is stopped before the existing full archive; original instance resumes; failed replica retries without another shutdown; actual monthly portless restore and later explicit byte/row restore succeed; missing key prevents downtime. |
| `backend/tests/test_full_backup_operations.py::test_killed_offline_worker_durable_resume_even_when_plan_is_disabled` | Actual child exits via os._exit(19) after durable exact resume obligation and stopped source; later worker restarts that owned installation despite disabled plan and records the discharged obligation. |
| `backend/tests/test_full_backup_server_contract.py::test_lifecycle_receipt_precedes_stop_and_remains_until_verified_resume` | FakeDocker contract: durable lifecycle preparation precedes stop; receipt contains exact simulated container identity and remains through verified simulated resume; real encrypted package verifies. |
| `backend/tests/test_full_backup_server_contract.py::test_failed_durable_prepare_does_not_stop_or_resume_original` | FakeDocker contract: failure to persist obligation prevents simulated original stop. |
| `backend/tests/test_full_backup_server_contract.py::test_probe_profile_has_only_private_volumes_internal_network_and_fresh_credentials` | Derived profile contract: fresh credentials and ownership labels, internal network, disabled provider/scheduler, no published ports or original secrets. |

## Boundaries

These are **15 distinct passed cases**: the first gate has ten real native/
container cases and the second has two real runner cases plus three Docker
contracts, for **twelve real cases plus three contracts**. No case is added
twice to the total.

No PostgreSQL case or real Docker lifecycle was selected in these commands.
Root's previously separate PostgreSQL proof is not relabeled as this run.
Actual Docker deployment, large-stock performance and the entire A–L roadmap
remain separate acceptance scopes. This proves the stated functions on the
exact tested source, not delivery or automatic activation in a private install.

All owned test lifetimes completed their cleanup. Heavy slot was explicitly
returned to Root after both runs; no test process remains running.
