# Retained tenant disclosure handoff

Base: Root `0becc28`. Isolated branch: `assist/tenant-retained-disclosure`.
The implementation plan was saved before implementation in
`TENANT_RETAINED_DISCLOSURE_PLAN.md`.

## Ownership and composed boundary

The product changes are exactly `tenant_data_graph` plus a new read-only
`tenant_retained_graph` helper and the directly related `_plan` projection in
`tenant_privacy`. No mutation, authentication, schema, router, frontend, bank or
AI implementation was changed. The existing privacy read snapshot still owns
coherent Memory detachment, SQLite BEGIN and PostgreSQL REPEATABLE READ, plus
its fresh scope checks. No helper touches auth sessions, creates schemas,
reconstructs sources, commits transactions or changes retained facts.

The seven workflow lists and three job lists participate in existing preview
counts and the canonical reviewed graph hash. Retained personal-field notices
identify the additional evidence in the preview. Wholly absent old SQL families
remain readable; incomplete table/column families fail rather than publishing a
partial result or silently repairing the schema. Scope-incomplete historical
subject records refuse disclosure with 403 without revealing hidden IDs or
payloads. The outer graph keeps a compatible schema label; the explicit retained
scope carries `tenant-retained-workflow-jobs/1` even when later existing graph
appenders choose the outer label.

## Actual subject and integrity proof

Workflow selection uses actual stored frozen previous/next contract tenant IDs,
not current contract ownership or free text. A permitted later current-party
correction does not erase the historical subject. Each selected change verifies
its snapshot SHA, location, original start receipt and complete step membership.
Used published template/version/definition facts bind the copied steps and their
dependency/anchor evidence. Task origins bind the actual source task and creation
receipt. Own evidence binds retained document-version manifests or finalized
handover/meter witnesses. Completed steps bind their actual terminal revision,
actor, timestamp and response receipt. Corrupt parents, witnesses, hashes,
unexpected response fields and incompatible completion attribution fail the
whole export.

A turnover is projected to only the matched subject direction(s). The other
contract snapshot, IDs, dates, template selection, steps and step receipts are
excluded. Historical command responses are similarly projected. Template facts
are included only for versions actually used by the historical subject.

Job selection uses exact current subject charge/receivable relationships and
approved correspondence's stored explicit tenant ID. SQL predicates and source
subqueries restrict candidates before materialization, with cursor fetch batches
of 500 rather than an arbitrary first-page cap. A 10,003-item test exercises the
real complete export in all three backends. Matching work items must prove their
lane/job/source/action affinity. Done effect references must bind the actual
occurrence/dispatch record before exporting any effect ID.

Shared jobs and lanes expose only IDs, lane family and subject-local counts.
Global parameters, authorization tokens, claim/lease state, cursors and global
counters are excluded. Only retry receipts for actual matched source work items
are included. Their request projection omits global revision data and their
receipt projection omits other lanes/counters. Job-wide commands are excluded.
Parent `subject_work_item_count` counts matched source work items; the ordinary
preview count of `operational_work_items` also includes projected retry receipts.
Actual approved correspondence calendar results include their bound review hash.

Each retained record's `source_sha256` hashes the actual complete stored source
record, including any redacted portion; it is an opaque digest, not disclosure
of that portion. `projection_sha256` hashes its exported projection, including
the source digest, before inserting the projection digest itself. The retained
scope's aggregate `projection_sha256` hashes the exported retained-family lists.
Minimal shared job/lane references are derived subject-local projections and do
not claim a hash of undisclosed global parent records. Existing canonical plan
hashing covers the final composed export.

The workflow's stored original `request_sha256` is preserved and checked for
format. Original request payloads were never stored: this implementation does
not claim to recompute or authenticate an unavailable original request SHA.
Job command request payloads do exist and their stored digest is recomputed.
Retry receipts additionally require their source item to belong to the same job
and prohibit a top-level source/lane reference on the command envelope.

## Remaining boundaries

The initial authorized `get_tenant` stays unchanged. After losing all current
contracts, a profile must still have its explicit portfolio resource grant or
be accessed by an authorized unrestricted operator. Frozen-subject selection
does not bypass that initial visibility gate or change portfolio/auth state.

The existing final graph is materialized for the composed count/hash projection;
its memory usage remains proportional to the selected subject's export size.
SQL fetch batching and complete 10,003-item tests prove no fixed prefix cap, not
a constant-memory end-to-end export pipeline or unlimited machine resources.

Job source rows do not contain a frozen historical tenant identity. A current
charge/receivable relationship cannot prove a different earlier party after a
later contract-party correction. Deleted or otherwise unbound job sources cannot
be attributed from IDs/free text. Such facts remain retained and are explicitly
outside the demonstrable subject projection; no fabricated historical binding
or complete legal-export guarantee is introduced. Root owns future persistence
of that missing historical evidence, if needed.

This adds an actual retained subject graph; it does not broaden the old base
metadata graph to publish old contract originals whose current party now differs.
Evidence links include verified source identities and digests. Original document
download/stream permissions remain with existing document services.

## Separately owned native PostgreSQL privacy write fence

The mutation implementation remains unchanged. Its actual functions are
`tenant_privacy.anonymize_tenant_profile` and `_privacy_write`; there is no new
`_anonymize_locked` helper. The profile writer currently locks `TenantORM` with
FOR UPDATE, then the *current* `ContractORM.tenant_id` rows in ID order with
PostgreSQL NOWAIT, followed by the existing wizard journal lock helper.
After a permitted current-contract tenant correction the historical workflow is
not covered by those current-contract locks. It also does not acquire the durable
operational domain lock for job mutations. Root owns the separate new write fence
and any domain/auth locking changes.

The count/hash inclusion makes a prior completed workflow mutation invalidate a
reviewed preview. It does not, by itself, prevent a PostgreSQL writer committing
after the in-transaction hash was recomputed and before the profile patch. This
is an independently reproduced open race, not a passing test result.

`backend/tests/test_tenant_retained_privacy_writefence_probe.py` is an opt-in
native counterexample with the intended assertion unchanged. It creates only a
random disposable PostgreSQL schema, starts a real historical move-out workflow,
corrects the live contract tenant, and captures a real preview. Two events pause
the actual `_plan` return inside profile confirmation, after actual hash
computation and before comparison/profile patch. A second thread performs a real
`tenancy_workflow.update_step`. Events release the profile writer after the
workflow writer returns. There are no sleeps. Native lock/statement timeouts
bound the diagnostic writer. Neither transaction nor hash is simulated.

On this unchanged mutation source the workflow writer **and** profile writer
commit, violating the desired assertion. The final observed result is 1 FAIL,
2 explicit non-PostgreSQL SKIPs, 22.97 s, in
`work/tenant-retained-privacy-fence-counterexample-final.log` (the earlier
independent reproduction was the same 1 FAIL/2 SKIP in 11.42 s). Only known
native lock/serialization errors or explicit 409 contention count as a blocked
writer; arbitrary fixture exceptions and future timeouts cannot pass the probe.
The probe is skipped by
default because Root owns the unresolved mutation correction; that default skip
is not evidence the race is fixed. Root should rerun it on the composed fence.

Reproduction (PowerShell, worktree root, bundled project Python):

```powershell
$env:TEST_SERVER_DATABASE_URL='postgresql://immo_ci@127.0.0.1:58112/immo_ci'
$env:RUN_TENANT_RETAINED_FENCE_PROBE='1'
& '../../outputs/ImmoManager-Pro/.venv/Scripts/python.exe' -m pytest `
  backend/tests/test_tenant_retained_privacy_writefence_probe.py -q --tb=short
```

## Final gates

Native PostgreSQL is the real isolated local 16.15 test service on port 58112.
Each native test fixture creates and removes its own random schema. No application
or public-schema data was used. SQLite checks use actual disposable database
files; Memory checks use actual services and domain records.

Both final composed runs cover the same final runtime and the complete selected
test set, including the existing privacy/lifecycle/correspondence and native PG
integration gates. The 66 new matrix cases comprise 65 PASS and one expected
Memory-only SQL-family-image SKIP; all 22 actual native PostgreSQL cases pass in
each composed run. The remaining skips are the three existing backend-specific
privacy exclusions and the three default-skipped native diagnostic parameters.
The observed warning is the pre-existing Starlette/httpx deprecation.

| Final gate | Actual result | Log in workspace `work/` |
| --- | --- | --- |
| Composed suite, Memory application backend + actual Memory/SQLite/PG matrix | 154 PASS, 7 expected SKIP, 570.88 s | `tenant-retained-disclosure-composed-final-memory.log` |
| Same composed suite, strict SQL application backend, fallback disabled | 154 PASS, 7 expected SKIP, 590.30 s | `tenant-retained-disclosure-composed-final-strict-sql.log` |
| Ruff, three runtime and two test files | PASS | `tenant-retained-disclosure-final-ruff.log` |
| Mypy Python 3.11, three runtime files | PASS | `tenant-retained-disclosure-final-mypy311.log` |
| Mypy Python 3.12, three runtime files | PASS | `tenant-retained-disclosure-final-mypy312.log` |
| Opt-in known native privacy race; unchanged mutation source | 1 real FAIL, 2 non-PG SKIP, 22.97 s; desired assertion catches both commits | `tenant-retained-privacy-fence-counterexample-final.log` |

Exact composed test selection:

```powershell
$env:TEST_SERVER_DATABASE_URL='postgresql://immo_ci@127.0.0.1:58112/immo_ci'
$env:TEST_STORE_BACKEND='memory' # second run: 'sql'
# Only the second run also sets ALLOW_INMEMORY_FALLBACK='false'.
Remove-Item Env:RUN_TENANT_RETAINED_FENCE_PROBE -ErrorAction SilentlyContinue
& '../../outputs/ImmoManager-Pro/.venv/Scripts/python.exe' -m pytest `
  backend/tests/test_tenant_retained_disclosure.py `
  backend/tests/test_tenant_retained_privacy_writefence_probe.py `
  backend/tests/test_tenant_privacy.py `
  backend/tests/test_tenant_lifecycle_privacy.py `
  backend/tests/test_tenant_correspondence_privacy.py `
  backend/tests/test_tenant_lifecycle_privacy_postgres.py `
  backend/tests/test_contract_lifecycle_integration_postgres.py -q --tb=short
```

The known native counterexample is deliberately separate from the passing
disclosure gate. Root must validate the combined new write fence before treating
the privacy mutation boundary as complete. No Main/Preview/server changes,
external writes, push or migrations were performed by this disclosure task.

Runtime Git blobs frozen for the final composed runs:

| File | Blob |
| --- | --- |
| `backend/services/tenant_data_graph.py` | `e5fb48fc207cb8d0ce2a9aa4b7fdbe85c7f3eb4b` |
| `backend/services/tenant_privacy.py` | `beabc3b74dc9ec6646356386fa649dfe0444fc71` |
| `backend/services/tenant_retained_graph.py` | `f0a89f41a860c809432b4afe777874c3fa5d04fd` |

The native diagnostic was rerun with its final strict error classification and
the same events/desired assertion. The final test blobs are
`b25401ebea7b70ace3873be848584d204b4635e0`
(`test_tenant_retained_disclosure.py`) and
`3ba6950e94d887e4093be096a976f5fe85a45ea0`
(`test_tenant_retained_privacy_writefence_probe.py`).
