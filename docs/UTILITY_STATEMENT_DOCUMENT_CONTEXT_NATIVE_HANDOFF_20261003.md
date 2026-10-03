# C: actual future utility context capture and native original proof

Own isolated `work/future-document-context-native`, branch
`assist/future-document-context-native`, clean Root basis `83c86a9`.

## Small source commits

- `e562520`: exact before-code plan and Scope/explicit-actor/no-actor boundary.
- `c7db19b`: pure immutable context protection and 22 focused regressions.
- `bb877fb`: actual finalization capture, lazy native source/parent/hash adapter,
  existing complete database verifier and narrow checked-source integration.
- `2843516`: independently testable native finalization/correction/restore tests.
- `4a7a3e5`: honest initial handoff with pure/Memory proof and pending SQL gates.
- This separate evidence commit adds only the completed native SQL results.

No DDL, Auth/factory/model/router, retained registry, central recovery, CI/UI or
PDF renderer source was changed. Existing FinancialSource-v1 fields, profile,
digest algorithm and canonical settlement hash encoder stay unchanged. Future
owner JSON includes its captured context before the existing whole-period SHA.

## Actual behavior and Root-facing contracts

`billing_settlement.finalize_period(store, period_id, preflight, *,
reviewed_issuers: Mapping[str, ReviewedIssuer] | None = None,
actor_id: str | None = None)` preserves all existing three-argument callers.
The existing one-commit/Memory-undo financial operation remains the boundary.
Flow is actual financial checks -> party freeze -> transient period with the new
party JSON -> actual context capture -> unchanged canonical full-period SHA ->
existing statement/source-period/period writes. No intermediate context write.

Actual current Scope supplies the actor. An optional explicit actor must match
that Scope; without Scope it is exclusively a trusted approved internal caller
argument, not authentication. No actor plus no review preserves the existing
party-only finalization, with no context and no guessed user. Review without an
actor fails. Actual authenticated HTTP finalization now captures future object
context even though its unchanged route cannot yet supply issuer reviews:
issuer stays None and publication readiness is explicitly incomplete.

Nonempty issuer reviews on an already finalized/delivered period are refused:
they cannot retroactively fill or change its original. Existing no-review retry
returns the original unchanged. Actor disagreement is checked before this retry.
Corrections copy the actually verified prior frozen rental context/contract
number including gaps; absent prior context remains historical_object_unproved.
New issuer review belongs to the new correction only. Current owner/sender fields
never become an issuer automatically.

New operative `billing_statement_document_context_storage.py` exposes:

```python
capture_actor(actor_id: str | None = None) -> str | None
capture_finalization_context(store, period, statements, *,
    reviewed_issuers: Mapping[str, ReviewedIssuer] | None = None,
    actor_id: str | None = None) -> dict
validate_stored_document_contexts(store, period, *, statements=None,
    verified_period_hash: str | None = None) -> None
```

Only caller-owned actual store rows are used. Lookup-only parent maps cache at
most 128 identities each; SQL rows filter/stream the actual period by ID. The
32-entry hash cache calculates complete actual source-period digests, including
all siblings. Cache limits do not limit allowed identities. Frozen tenants need
only actual ID existence, not a current profile/name. `verified_period_hash` is
exclusively an internal already-computed actual SHA from the checked reader;
there is no HTTP/JSON cache parameter or source-parent acceptance.

The pure `protect_period_document_contexts(current, replacement)` is called
alongside existing party protection in settlement `_write`. Present originals
cannot be removed/replaced; absent old originals cannot be added after finality.
Root can reuse this pure function for future shared update/finalization hooks.

## Existing native recovery and source composition

`validate_statement_party_database(connection, deadline=...)` now detects party
and context families independently in the existing bounded period scan. Present
context validates actual complete SHA, coverage, party, actual parents and full
source ancestry. Context without party/null/partial/foreign/corrupt is rejected.
Absent contexts preserve valid legacy party-only/absent behavior. Context proof
already composes parties and consumes each current row stream once. All source
row generators close their actual SQL cursors.

The function preserves its return-bool and `StatementPartyIntegrityError`
boundary. Existing Root full recovery/session invalidation/offline validators
therefore compose it without registry or recovery-source edits in this packet.
The checked original source `_Reader.period` adds the same context semantics only
after actual whole-period SHA. Correction party freeze also validates present
source contexts, even when the direct caller cannot capture a new context.

To model genuine old data in test fixtures after this feature, remove both
statement_parties AND statement_document_contexts and compute the real native
SHA. Removing parties alone from a new future original is correctly an invalid
orphan context; do not weaken that check.

## Evidence to date

Pure tests: **63 PASS, 1.96 seconds, no skips**, including the previous 41 pure
context tests and 22 new immutable guard cases. `--noconftest`, plugin autoload
disabled, hard 20-second process budget; fixed fail-closed fresh import blocker
child (10 seconds), no DB/Auth/App/Store initialization.

Frozen clean HEAD `2843516`, actual Memory gate: **6 PASS, 23.39 seconds, no
skips**, hard 90-second process budget. Production router graph and actual
registered/authenticated synthetic users; no Actor/Auth-response mocks. Cases:
HTTP object capture with incomplete issuer; actual old three-argument/no-actor
compatibility; missing/foreign-actor rollback; explicit reviewed completeness
plus actual correction after changed object/unit/contract/tenant labels; genuine
legacy source retaining its object gap; rollback after context capture AND the
first actually finalized statement DML. Process closed and slot released.

Frozen clean HEAD `4a7a3e5`, actual SQLite gate: **6 PASS, 51.04 seconds, no
skips**, hard 150-second process budget including the 30-second backup child.
Cases: actual reviewed capture/correction after current parent labels changed;
genuine context-less/party-less source and actual new unproved correction;
rehashed partial context coverage AND rehashed orphan context without party;
altered unselected original source sibling; exact original SQLite backup.
Both rehashed corruption cases returned original-source HTTP 409 and passed
through the existing real `invalidate_and_inspect` failure before any session
row changed (exact before/after SQL rows compared). The actual native database
checker ran without a dispute case. Separate engine connections read the exact
whole financial SHA and frozen owner original.

The backup used `sqlite3.Connection.backup` on the actual finalized database,
then a read-only query-only transaction checked the original owner JSON exactly
against its original stored values and actual complete financial SHA after the
live property address changed. A
fresh child performed the complete native party/context proof while fixed
fail-closed import blockers rejected Auth/config/dependencies/app/Storage/
repositories/settlement/operative context capture. Child exited normally with
`PURE_NATIVE_CONTEXT_ORIGINAL`; no ambient application import was permitted.
This is an actual original database backup/reopen proof, not a newly invented
replacement dataset, and not a fullcontainer restore/publication claim.

Same frozen clean HEAD `4a7a3e5`, actual PostgreSQL gate: **4 PASS, 73.71 seconds,
no skips**, hard 120-second process budget. Cases: reviewed original plus actual
correction with independent native whole-SHA/context/original reads; genuine
legacy source with actual source-period hash; altered source sibling; rollback
after the first actually finalized statement DML. Dedicated disposable local
database on port 58112, only four own random `measurement_<UUID>` schemas from
the existing native fixture. Every fixture's successful teardown disposed its
engines and dropped only its own schema; all connection-return assertions
passed. No public data/service start/restart, private data or provider action.
Pytest and wrapper exited normally; no owned native process remains.

The completed targeted gates comprise **63 pure + 6 Memory + 6 SQLite + 4
PostgreSQL PASS**, no skips in any of these runs. This is the exact selected
coverage; other parametrized nodes in the new test file were not run as a broad
suite. Ruff of all eight changed service/test files, Mypy of the two context
services and diff-check passed. Product/tests were unchanged throughout every
native gate; only this handoff gains the later results.

## Remaining Root responsibilities and limits

Root retains actual commit-time account/token/grant authorization, explicit issuer
HTTP/UI input/review policy, shared raw/native protection and ordinary registry/
privacy composition. A trusted internal actor argument does not add those
authority guarantees by itself. Independent SQL reads and actual SQL rollback
are proved above; cross-process write/revocation races are not claimed. This
source packet does not claim a fullcontainer restore, an archived original PDF,
dispatch, or a large-stock job/ZIP memory proof.

Future archive publication must use a real coherently verified full period, its
exact selected stored context and unchanged FinancialSource-v1 before
build_archive_source/require_complete_archive_source. A complete supplied wrapper
does not replace those actual native checks. Ordinary preview PDF rendering and
legacy financial derivations remain their existing separate product path.
