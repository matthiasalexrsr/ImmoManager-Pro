# C: pure future utility document context packet

Own `work/statement-choices` / `assist/statement-choices`. Architecture plan
`6ea4b04` accepted by Root; its explicit before-code interfaces are `3fa092f`.
This packet changes only two NEW pure services and one NEW synthetic test file.
No Finalize/Guard/Recovery/Archive/Privacy/HTTP/UI/shared/registry/settings/CI or
migration source was edited. `l2` remains TEHA. FinancialSource-v1 is unchanged.

## Exact commits and acceptance

- `3fa092f`: assigned pure interfaces/dataflow before code.
- `dcc1679`: pure contexts/capture/family proof and archive-source wrapper.
- `ae3aaea`: 41 pure snapshot/correction/negative/import regressions.
- This separate handoff commit adds no product code.

Final frozen-source gate: **41 PASS in 1.22s, no skips**. It ran with
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `--noconftest`, a hard 20-second main process
budget and a fresh fail-closed import-blocker child bounded to 10 seconds. No
Auth/App/Store/native DB/server/browser initialization. An earlier 35-case source
passed in 1.39s; then actual parent lookup-ID checks and the oldest context-less
source corruption regression were added, followed by the complete final gate.
Final Ruff of all three files, Mypy of the two services and diff-check passed.

These are pure supplied-snapshot/caller-contract proofs. They are **not** actual
finalization, SQLite/PG races, staged/fullcontainer restore, archive publication,
actual issuer UI review or large-stock acceptance. Root owns and coordinates
those composition proofs. No native/Python/server/browser process remains.

## Exact new contracts

`billing_statement_document_contexts.py` exports:

- `PostalIdentity`, `ReviewedIssuer`, `RentalObject`,
  `StatementDocumentContext`, `StatementDocumentContexts`;
- `DocumentContextIntegrityError`;
- `document_context_family(period)`;
- `capture_document_contexts(period, statements, *, parents, reviewed_issuers,
  actor_id, captured_at, verified_period_hashes=None,
  statements_for_period=None)`;
- `validate_period_document_contexts(period, statements, *, parents,
  verified_period_hashes=None, statements_for_period=None)`;
- `validate_document_context_snapshot(*, parents)`.

Family key `statement_document_contexts` lives in a NEW owner JSON COPY, schema
`utility-statement-document-contexts/1`, keyed by the exact actual Statement IDs.
It records exact Statement/period/revision/domain parents and dates, existing
Party-v1 digest, rental object postal/name/unit/floor fields, frozen contract
number, explicit reviewed issuer, capture time/actor, object-binding mode and
actual source Statement/snapshot/context SHA. Missing optional values are null,
not later defaults. Family absence is permitted; present null/malformed/partial
coverage is corruption. Existing Party-v1 fields/schema are unchanged.

`ReviewedIssuer` has identity(name/address_line/postal_code/city/country), role
`landlord|representative`, optional landlord identity, and `confirmed` as strict
boolean true. False, numeric 1, unknown subjects or reviewed issuer without a
captured actor fail. A landlord issuer is its own identity, with landlord=null.
A representative without named landlord remains explicitly incomplete; no
authorization/signature/relationship is inferred from these strings.

## Actual Root finalization composition

Root retains one actual finalization/authority/lock/undo transaction. Conceptual
order, with no intermediate party/context writes:

```python
party_owner = existing_party_freeze(store, actual_period, actual_statements)
transient = actual_period.model_copy(update={"owner_cost_share": party_owner})
owner = capture_document_contexts(
    transient, actual_statements,
    parents=actual_locked_parent_maps,
    reviewed_issuers=actual_explicit_reviews_by_statement_id,
    actor_id=actual_actor_id,
    captured_at=server_capture_time,
    verified_period_hashes=internal_actual_source_hash_map,
    statements_for_period=actual_source_period_row_reader,
)
digest = existing_snapshot_hash(actual_statements, owner)
# Root finalizes Statements and period(owner JSON) atomically as already owned.
```

`capture_document_contexts` itself performs no store access, write, lock,
authorization, hash finalization or receipt. It returns a new deep-copied owner
JSON, preserving all unrelated owner data. It accepts draft/review only, exact
unhashed draft/review Statements, a complete transient Party-v1 family and no
preexisting context family. Any finalized old period, including one with no
context, is refused. The caller must supply actual snapshots, not HTTP parent
JSON, a client hash cache or fictional historical capture time.

Parent maps contain actual raw typed dictionaries for properties, units,
contracts, tenants, portfolios, billing_periods and utility_statements. Lookup
IDs and returned row.id must match; property/unit/contract/portfolio bindings
must match the actual frozen party. Tenant map may supply ID-only existence;
no present tenant profile is required by these helpers. Root supplies already
authenticated reviews and current locked object parents at future finalization.
Absent reviews produce issuer=None, allowing explicit incomplete financial
finalization with no new mandatory finalize request. They never use
Portfolio.owner_name or any contractwizard row as an automatic billing issuer.

For initial finalization the helper captures only supplied actual Property/
Unit/Contract fields. `object_binding=current_parents_at_initial_finalization`
states this capture time, not the old accounting year's identity.
Corrections verify the actual prior complete financial period and context family
recursively. They copy the prior object/designation INCLUDING missing fields,
and record its exact source-context SHA, while issuer comes from the new explicit
review only. Prior context absent -> `historical_object_unproved`, null object/
contract number, null context SHA. Present prior context with unproved object
retains the gap and a real context SHA. Current renamed/addressed parents never
fill either gap. Original issuer/context remains unchanged.

## Pure/natively streamed validators and Root guards

Default snapshot validation calculates unchanged settlement hashes from complete
supplied rows for each affected period. It composes the existing party validator,
actual parent references, dates/revisions/source relationships and context-copy
proof; cycles, duplicates, missing/foreign family entries and corruption fail.
Even source periods with no context family still get complete actual financial
hash checks, including older siblings across multiple correction steps.

For Root-native/offline composition, `verified_period_hashes` is an INTERNAL
mapping from actual affected period ID to its actually streamed complete SHA.
It may be Root's lazy Mapping backed by its actual coherent DB hash helper.
Every needed current/source ID must resolve; missing/invalid results fail.
`statements_for_period(period_id)` supplies an actual fresh one-pass row iterable
for referenced source periods. Current rows are supplied directly by the caller.
Each period is consumed once per verifier; source period result reuse is confined
to that coherent call. A native parent map need not expose `.values()` or the
global dataset. This is never external cache/proof acceptance.

Root must compose this pure validator into every relevant native source/restore
period path, also without a dispute/archive. Root's current party-native reader
and actual full-period hash are the intended sources. Root installs its real
immutable write/finalization guards: an old context can neither be replaced nor
removed, and old absent context cannot be added after finalization. This package
deliberately does not add operational/native guard DML or migration changes.

## Unchanged financial source, separate archive wrapper

`utility_statement_archive_source.py` exports `UtilityStatementArchiveSource`,
`build_archive_source(financial_source, document_context)`,
`validate_archive_source(value)` and `require_complete_archive_source(value)`.
Schema `utility-statement-archive-source/1` embeds the exact unchanged checked
FinancialSource-v1 DTO, optional selected context, context digest, sorted exact
missing_fields, derived completeness and archive-source digest. It revalidates
financial/context models, binds exact selected Statement/parents/dates/party,
and rejects fabricated completeness or foreign contexts even after rehash.

Country/floor/property display name are explicitly optional. This profile's
complete original needs frozen recipient name/street/postal/city, frozen rental
street/postal/city/unit label, contract number, explicit issuer name/street/
postal/city and, for a representative, named landlord postal identity. These
are concrete product completeness rules, not legal validity assertions.
Missing context yields `unproved`; context with missing fields yields
`incomplete`; otherwise `complete`. `require_complete_archive_source` rejects
only publication readiness, naming exact missing fields. Checked old financial
PDF, draft PDF and incomplete financial finalization remain available.

The wrapper alone proves typed self-consistency, NOT membership in the actual
stored complete period. Root must first prove actual whole hash/context coverage/
source ancestry with the family validator and its real DB snapshot, then select
the actual entry and build the wrapper. Keep preview-v1 API/render/profile bytes
unchanged. Typed Archive/Actor/Idempotency/Privacy/Recovery/HTTP/UI integration,
explicit archive renderer and actual archive bytes remain separate Root work.

## Remaining evidence and local artifacts

Only prior synthetic `tmp/` PDF QA output remains untracked in this checkout.
Its recursive deletion was previously rejected by automatic approval review as
`blocked by policy`; no workaround/retry or source deletion was attempted.
All context product/plan/test/handoff sources are individually committed.
