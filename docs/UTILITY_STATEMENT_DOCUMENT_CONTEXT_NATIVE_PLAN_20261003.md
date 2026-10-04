# C: native future utility document context integration

Before-code plan, based on clean Root `83c86a9`, in isolated
`work/future-document-context-native` / `assist/future-document-context-native`.
The existing pure context package and FinancialSource-v1 are already integrated
in that base. This plan precedes all product changes in this checkout.

## Observed paths and assigned ownership

There is one actual `billing_settlement.finalize_period(store, period_id,
preflight)` called by `routers/billing.py:617`. Existing direct router calls
also reach that service. The service owns `atomic_billing`, financial preflight,
complete statement/calculation checks, party freeze, the existing canonical
`snapshot_hash(statements, owner)`, statement finalization, correction source
status and final period write. SQL has one commit/rollback; Memory has financial
undo. No other public storage finalizer was found.

`atomic_billing` already takes the measurement property lock before root-period
and contract locks. Ordinary native property/unit/contract/portfolio writers use
that property lock; SQLite already owns its writer and Memory its financial
lock. Capture will use actual re-read parents within this operation, not add a
second transaction or invent a different lock order. Direct raw SQL is not an
authorized production capture path.

`billing_statement_party_database.validate_statement_party_database` already
serves full recovery, recovery sessions and recovery validation. It currently
proves only party families, including whole source-period hashes. The existing
`utility_statement_original_source._Reader.period` proves full affected-period
SHA and parties. Root explicitly authorizes a narrow additional context check
there; FinancialSource-v1 models/schema/rendering remain identical.

Owned edits: the three assigned settlement/party storage/party database files,
our existing pure `billing_statement_document_contexts.py`, our own original
source reader, one new operative service, new tests and these docs. No DDL,
factory, Auth, model, router, retained registry, central recovery, CI or UI edits.
`l2` remains TEHA. Root retains those authority/publication/composition hooks.

## Exact optional finalization boundary

```python
finalize_period(store, period_id, preflight, *,
    reviewed_issuers: Mapping[str, ReviewedIssuer] | None = None,
    actor_id: str | None = None) -> BillingPeriod
```

The old three arguments remain accepted without new required data. Resolve the
capture actor from the actual current Scope; an explicitly supplied internal
actor must match it when Scope exists. Without Scope, an explicit nonblank actor
is a trusted caller-approved service argument, not an HTTP credential or proof
of authority. Root will obtain it from actual native authorization. This
package neither overrides Auth nor invents system users.

Precise compatibility branch: no current Scope and no explicit actor, with no
issuer review, retains the existing party-only financial finalization. It
creates **no document context** and remains publication-unproved. Any explicit
issuer review without a capture actor fails before finalization. With an actual
Scope actor or caller-approved explicit actor, new finalization captures the
object context. Missing reviews become `issuer=None`, so financial finalization
is permitted but complete original publication is not. No current portfolio
owner/contract-wizard sender becomes an implicit reviewed issuer.

Already finalized/delivered legacy calls retain their unchanged return value;
nonempty issuer reviews cannot be used to add/replace an existing original via
this retry path. A new review requires a new actual correction/finalization.
The caller-owned future HTTP command/idempotency contract remains Root work.

`billing_statement_party_storage.freeze` gains only an optional internal
`actor_id` keyword, preserving its current Scope-derived behavior. The resolved
actor is shared by party and context capture. Capture time is server UTC now.

## New operative adapter and exact data flow

New `backend/services/billing_statement_document_context_storage.py`:

```python
capture_actor(actor_id: str | None = None) -> str | None
capture_finalization_context(store, period, statements, *,
    reviewed_issuers: Mapping[str, ReviewedIssuer] | None,
    actor_id: str | None) -> dict
validate_stored_document_contexts(store, period, *, statements=None,
    verified_period_hash: str | None = None) -> None
```

The adapter has targeted lazy actual parent maps for properties, units,
contracts, tenants, portfolios, periods and statements; bounded lookup caches
are a performance aid, not an identity limit. Tenant lookup for frozen originals
is actual ID existence only. Source statements/periods are actual rows, not
request JSON. SQL statement iterables filter the exact period and stream by ID;
no global SQL history list is loaded. Internal lazy hash maps calculate unchanged
`statement_snapshot_hash` over every actual sibling in each affected period.
No external cache/hash input is exposed by these service methods.
The optional verified hash is exclusively an internal already-computed actual
whole-period SHA from our original reader; it is never a request field/cache.

Actual finalization order:

1. Keep all existing financial locks/checks and actual actor resolution.
2. Freeze parties into a new owner JSON copy, without writing it.
3. Construct a transient period carrying that party owner JSON.
4. If an actor is available, use the existing pure `capture_document_contexts`
   with actual lazy parent/source/hash readers and explicit reviewed issuers.
   Otherwise keep the precise compatible party-only branch above.
5. Calculate the **unchanged** `snapshot_hash(statements, owner)` once.
6. Perform the existing statement/source-period/period writes atomically. No
   intermediate owner/context update or separate commit is introduced.

Capture for initial future finalization reads current actual object fields only
at this real capture event. Correction capture verifies complete actual prior
financial periods recursively. It copies preceding frozen object/address/unit/
contract-number fields, including gaps; its issuer comes only from this new
explicit review. Prior context absent means `historical_object_unproved` and no
current names/address repair. Existing original JSON is not modified/backfilled.

## Pure protection and existing native semantic proof

Add `protect_period_document_contexts(current, replacement)` to our pure context
module. A present old family may neither disappear nor differ. An absent old
family can be added only by draft/review -> finalized, never to an old final
period. Malformed present families fail closed. Call it alongside party
protection in the existing internal settlement `_write`; Root may reuse this
exact pure guard for future shared/native update composition.

Extend the **existing** party database verifier rather than add a parallel
recovery registry. For each bounded actual period page, detect party and context
families independently. A present context without party is invalid. A context
family runs `validate_period_document_contexts` using the actual streamed SHA,
targeted actual parents and actual source-period readers; that validator already
composes party validation, so each current statement stream is consumed once.
Party-only legacy uses the existing party checker unchanged. Context-less
legacy remains valid/absent. Context failures are normalized to the existing
`StatementPartyIntegrityError` so current recovery adapters fail before DML.
Native return bool continues to report whether any original family was found.

Our original source `_Reader.period` performs the same additional context proof
after computing its actual whole financial SHA. It must avoid recursive parent
lookup entering its own in-progress period: use actual row lookup plus a native
source-period hash reader for context recursion. No new FinancialSource DTO
fields, source digest bytes, PDF text, render profile or archive claim.

## Root API/authority/archive hooks, deliberately unimplemented

Future Root finalize input may add optional statement-ID-keyed `ReviewedIssuer`
DTOs (strict true confirmation, landlord/representative and optional named
landlord postal identity). Validate actual statement membership; never accept
parent JSON, captured timestamps or internal source hash maps over HTTP. Current
HTTP still takes only a period ID, but its actual Scope supplies the actor and
therefore captures future object contexts with an incomplete issuer.

Root owns commit-time native account/token/grant fencing, optional issuer review
UI, ordinary shared update/reset protection, explicit archive renderer/publisher
and typed Original/privacy registry. No publication flag is inferred here.
Only an actual fully checked period -> selected frozen context -> existing
`build_archive_source` / `require_complete_archive_source` may establish that
planned archive profile's completeness. Existing normal preview PDFs stay intact.

Legacy test fixtures that remove only `statement_parties` from a **newly captured**
period will now intentionally be invalid if they leave its context behind. To
model genuine pre-context history, such fixtures must remove both additive
families before recomputing their actual financial SHA. Existing negative tests
must not be weakened to accept an orphan context.

## Evidence and gate plan

Before native slot approval: only pure guard/caller-contract tests with
`--noconftest`, fixed fail-closed ambient import blockers, one bounded process;
static compilation/Ruff/diff checks. Source is frozen throughout each gate.

New native tests, run only in Root-coordinated slots: actual normal HTTP and
direct three-argument finalization compatibility; approved-actor explicit issuer
capture; independent SQL reads of whole hash and exact context; subsequent real
property/unit/contract/tenant edits preserving originals; actual correction from
proved and genuine legacy sources; malformed/null/partial/foreign families even
after rehash; changed source siblings; native no-case validation and exact SQLite
backup/read-only reopen; rollback after context capture and internal immutable
guard; dedicated PG own UUID schemas and no skip-as-green. No Auth monkeypatch,
provider/private-data/portal/server/browser test introduced by this packet.

Final handoff will distinguish source/statics/pure proofs from actual Memory,
SQLite/PG finalization and recovery proof. No large ZIP/archive publication or
whole-dataset acceptance is claimed by these targeted changes.
