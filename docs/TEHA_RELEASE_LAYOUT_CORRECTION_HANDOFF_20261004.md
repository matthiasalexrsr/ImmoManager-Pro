# TEHA initial L2 freeze and evidence correction: closed source handoff

Checkout: `work/teha-receive-domain`, branch `assist/teha-receive-domain`.
Taken over at clean `150aa6619f071c9321a8df0a3008496aea26dcd3`, without resets
or parallel editing. The pre-code plan is `210e5f9`; implementation is `b4ac130`.
The final test/document commit follows this implementation on the same branch.

Root explicitly confirmed that L2 was never delivered in Root/live126. This
follow-up freezes the final initial layout, including receipt `mapping_id`,
`mapping_sha256`, non-null mapping FK and digest constraint. The earlier source
and isolated development layout are historical predecessors, not released
schemas to silently repair. Private installation databases were untouched.

## Completed source changes

`backend/db/teha_receive_release_l2.py` owns immutable initial DDL with independent
metadata and prerequisite ID stubs. Only its two L2 tables are created/dropped;
parent tables are never created by this migration. Neither migration nor
`teha_receive_schema.py` imports runtime ORM definitions to derive historical DDL.
The reserved revision remains `l2a2b3c4d5e6`, parent `k2a2b3c4d5e6`. Upgrade
refuses every already-present L2 table before DDL. Runtime validation checks exact
columns/nullability, primary key, required uniqueness and exact RESTRICT FKs.

Absent/partial/invalid L2 in read/preview/download becomes structured 503
`teha_l2_schema_requires_maintenance`, with fixed operator guidance and
`maintenance_path=docs/TEHA_L2_MAINTENANCE_20261004.md`. The router also catches
an actual `TehaReceiveSchemaError` raised outside the read-session boundary.
No DDL or repair is attempted by these paths.

`teha-import/2` original evidence now independently binds receipt mapping
ID/digest/generation, receipt and mapping connection/portfolio, the actual
kind-specific target and fresh parent/grant context to the original local
binding. Property A cannot claim Original B merely because both share a portfolio.
Period/Unit use their actual current Property parent; User uses the actual Tenant
and portfolio grant. Technical-order mappings cannot claim document originals.
The runtime caller rereads those parents/grants before retained receipt validation.
Generic DocumentVersion authorization independently checks original parents and
all immutable chunks are verified before successful receipt download/replay.

Supported nonblank document classification strings, including unknown and long
values, round-trip without an invented enum/length cap or text trimming. The
classification is retained in the immutable TEHA extension and checked against
the archived Document snapshot. Later ordinary live recategorization preserves
the original evidence; no hardcoded `teha_document` equality remains. The current
source importer still permits only proved Property/Unit source associations;
period/user validation does not invent additional provider association rules.

The dynamic actor-only positive authority contract is removed. Every public
mapping/document/task write and `_work(write=True)` immediately returns 503
`teha_write_unit_unavailable`, before History/Auth/Fachsession/Writer/DML. Fake
actor-only modules, Notification objects, bools and missing authority cannot
unlock it. No generic Root contract/type is fabricated. The dormant independent
Session implementation must be composed with/replaced by the actual Root unit,
not enabled merely by supplying an actor validator.

## Test source and executed checks

Prepared pure test: `tests/pure/test_teha_import_evidence.py`, explicitly separate
from `backend/tests/conftest.py` and runtime services. It imports only DTOs,
pure projections/contract/manifest helpers and frozen SQLAlchemy schema types.
Native invocation, separately: `pytest --noconftest tests/pure/test_teha_import_evidence.py`.
Cases cover Property/Period/Unit/User, same-portfolio original substitution,
matching copied receipt/extension fields versus the actual mapping, namespace/
portfolio/ID/digest/generation drift, current parent drift, contradictory target
shape, unknown long classification and rejection of development manifest v1.

Prepared runtime test: `backend/tests/test_teha_runtime_boundaries.py`. Its service
import loads Auth/config/global Settings; **it is not no-runtime or pure**, with
or without `--noconftest`. Cases cover fake-module rejection at `_work` and all
three public writes, schema errors through read/preview/download, current period/
unit parents, revoked tenant grant and retained original classification plus
complete block traversal. No positive commit capability is mocked.

Updated schema/migration test: `backend/tests/test_teha_receive_persistence.py`.
New cases compare frozen DDL to current models with independent metadata, reject
already-present and old development families without repair, and update receipt
fixtures for mapping ID/digest. Existing explicit disposable PostgreSQL gate is
still opt-in via `TEST_SERVER_DATABASE_URL`, under Root slot coordination.

Removed the misleading `backend/tests/test_teha_transaction_boundaries_pure.py`
and the synthetic positive `backend/tests/test_teha_transactional_commands.py`.
Their historical sources remain in Git. The predecessor's seven-test PASS was
not no-runtime evidence; its service imports loaded Auth/Settings. Future positive
atomicity/CAS/revocation/replay tests must use Root's actual unit.

Executed in this correction: source reads, Git diff inspection and
`git diff --check` only, passing. No Python imports, tests, compiler/linter,
application, database, PostgreSQL, browser or portal process was run. No current
runtime/HTTP/schema acceptance is claimed. Commits disabled hooks for this
source-only slot; no shared configuration was changed.

## Exact Root composition links

| Root-owned boundary | Source linkage and gate |
| --- | --- |
| Model registration | `backend/db/teha_receive_models.py` exports `TEHA_RECEIVE_MODELS` and `TEHA_RECEIVE_TABLES`. Compose in the actual central registry. In this predecessor checkout the model-registration sites are `backend/db/session.py` and `backend/db/migrations/env.py`; neither is edited here. Do not use mutable ORM imports to recreate frozen migration DDL. |
| Migration chain | Compose Root K2 then this `backend/db/migrations/versions/l2a2b3c4d5e6_teha_receive_mapping_import.py`; compose Root's separate M2 afterward as applicable. K2 is reserved but its migration file is not present in this isolated checkout, so no standalone linear-head/upgrade success is claimed. Native Root gate must prove the actual composed chain and final fresh SQLite/PostgreSQL DDL. |
| Startup compatibility | `backend/db/runtime_schema.py` and `backend/db/retained_family_schema.py` remain Root-owned. Add L2 frozen layout/guard proof before any startup DDL; absence versus partial/older family must remain explicit. Do not infer final layout from the Alembic revision alone. |
| Router activation | `backend/routers/teha.py` is prepared but absent from central `backend/routing.py`. Current production routing therefore does not expose these new endpoints. Root decides activation after coherent schema/recovery proof; every write remains closed until the real unit exists. |
| Image validation | Compose the new proposal in `docs/TEHA_RECOVERY_SEMANTICS_PROPOSAL_20261004.md` with `backend/services/full_recovery.py`, `backend/services/recovery_validation.py`, and `backend/services/recovery_history.py`. Call pure manifest checks with mapping/parent context derived from the selected image, never a running store. |
| Retention / clear / transfer | `backend/services/recovery_retained.py` owns retained-family fences. Include complete L2 closure plus the immutable extension's content History run, which has no SQL FK. Guard before DML, including destructive clear and partial transfer. |
| History normalization | Existing `backend/services/integrations/history_validation.py` and `history_restore.py` remain authoritative. Validate all source/content runs first; restore only normalizes unfinished outcomes, preserves completed evidence and performs no provider I/O or automatic retry. |
| Actual write unit / jobs | Root must supply the actual Session/transaction/database/operation/target contract. Notification authority is unrelated. The existing shared job adapter remains only a later proposal; receipt job/work-item references do not claim implemented resumable receive jobs. |

Current download verification binds retained original/mapping/parents and bytes;
it does not independently re-decrypt all referenced History runs. The coherent
selected-image History/retention proof is the explicit central integration above.
The receipt also does not retain the full confirmed command/preview payload;
offline recovery can check digest syntax/equality, not independently reconstruct
the complete original request. The Recovery proposal states this limit rather
than making a positive guarantee; Root must decide any required minimal immutable
command evidence before enabling writes.

Root's next native gates are the separate pure manifest suite, explicit runtime
boundary suite, frozen-schema/parity and fresh composed migration-chain gates,
then hostile selected-image Recovery/retention cases. Root also needs composed
HTTP proof of the structured schema 503 and valid retained custom-classification
download before activating read routes. No live provider, private database or
other chat was involved in this correction.
