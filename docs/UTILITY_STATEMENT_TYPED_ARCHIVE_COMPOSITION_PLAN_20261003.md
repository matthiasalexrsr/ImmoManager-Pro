# C follow-up: typed utility PDF originals in the existing document archive

Plan before archive product code, 03.10.2026. Own checkout
`work/statement-choices`, source/renderer packet through `42ca0a8`, enriched by
Root `ff4b1a5`. Root owns shared document services, files, native recovery,
registries, jobs, settings, CI and migrations. This document edits none of them.
No archived-original, recovery or large-stock acceptance is claimed by this plan.

## Proven starting point and concrete remaining gap

`utility_statement_original_source.py` now proves an actual selected immutable
Statement, the entire actual affected period hash, complete frozen party family
and every actual source period. Its strict selected DTO/digest is independent of
today's tenant profile/unit label. Legacy party absence remains explicit.
`utility_statement_pdf.py` produces a checked deterministic derivation, or the
separate watermarked draft derivation. PDF/source GET and ZIP write no Document,
version, receipt, status or delivery event. These APIs remain usable as delivered.

The source/draft handoff records real focused Memory/SQLite/PG and multipage
Unicode proof. It does not prove archival replay or large bundled output.
`prepare_period_zip` still holds the complete ZIP in BytesIO. `_Reader.verified`
memoizes actual affected periods in a read snapshot, and period party owner JSON
is still an affected-period object. Neither is a measured large-stock/job bound.

Actual `document_versions.publish_generated_original` already calls
`persist_version_bytes` in the caller's transaction, with one immutable
DocumentVersion and <=65536-byte chunks. Manifest rows already have tenant,
source parents, actor, request SHA, idempotency, metadata JSON, content SHA/size
and the existing unique keys. Reuse these tables and existing original download;
no second PDF archive, receipt ledger or ad hoc queue is proposed.

There are two real incompatibilities requiring narrowly typed Root composition:

1. `_document` and `_authorized_version` derive/check the current contract tenant;
   the native document verifier and privacy journal require the same equality.
   A correctly frozen utility-original party can differ after a current contract
   rebind. An exact proved subtype must supply that historical subject.
2. Generated publication fixes the manifest idempotency key to
   `generated-<document.id>`. That convention alone cannot simultaneously enforce
   one original per Statement and independent actor/client-command idempotency.
   The existing unique `(actor_id,idempotency_key)` can enforce the latter when
   Root derives the utility-specific manifest key from validated subtype data.

## Actual snapshot audit and additive future document context

Root's integration at `5dc35ef` identified a prerequisite beyond tenant proof:
the current PDF uses unit/contract UUIDs and lacks proved rental-object postal
address/unit designation and issuer/landlord data. Actual own-source audit:

- `PartyIdentity` contains only tenant full_name/address_line/postal_code/city/
  country. `StatementParty` contains stable parents/capture/source references,
  not Property postal identity, Unit.label, contract_number or issuer fields.
- `billing_settlement.calculation_hash` includes financial/allocation/contract/
  unit quantity inputs and historical measurement content hashes. Its hash is
  not a retained document address/name snapshot. `freeze` adds only parties to
  existing owner JSON before the unchanged complete settlement digest.
- `Property` has current address_line/postal_code/city/country/name; `Unit` has
  current label/floor. `Portfolio.owner_name` is an optional current name and
  has no issuer postal-address field. No complete billing issuer can be inferred.
- Contractwizard's checked review captures whole property/unit/portfolio and
  explicit landlord_name/landlord_address. Those fields belong to that reviewed
  contract publication; the latest committed/signed draft is merely a possible
  specifically referenced suggestion for a future billing review. It proves
  neither a missing historical billing snapshot nor that the issuer stayed the
  same. Correspondence context similarly captures names for its own letter.
- Historical measurement facts retain measurement/occupancy/allocation sources,
  with no billing issuer or rental-object postal/display snapshot contract.

Before publishing a sendable first utility original, plan a separate future-
finalization context packet, after Root assigns its Settlement/Source/UI hooks.
Use an additive sibling `statement_document_contexts` inside existing hashed
`BillingPeriod.owner_cost_share`, schema
`utility-statement-document-contexts/1`, rather than modifying strict existing
`utility-statement-parties/1` entries or adding columns. Each actual Statement
has exactly one typed context entry; complete coverage (including empty periods)
and actual parents/source references are validated like the party family.

Proposed strict selected `StatementDocumentContext` fields:

- actual Statement/period/revision/portfolio/property/unit/contract IDs;
- frozen period start/end and optional period title, frozen contract_number;
- rental_object: actual captured Property postal fields, optional property name,
  Unit.label and optional floor, with explicit per-field absence/completeness;
- issuer: explicitly reviewed name and postal identity/address, optionally
  separately identified landlord/representative when the issuer differs;
- provenance: actual captured_at/by, capture basis, reviewed-source references/
  digests and explicit issuer confirmation; optional exact previous Statement/
  snapshot/context digest for a correction.

At an initial future finalization, lock/re-read actual Property/Unit/Contract/
Portfolio and verify reviewed source etags. Freeze their provided object fields
and contract number at this real finalization, not at the old accounting year.
Issuer inputs are explicit future reviewed data; owner_name or a verified exact
contractwizard review can be a labelled suggestion, never an automatic complete
issuer/address. Include these entries before `snapshot_hash(statements, owner)`
in the same existing finalization transaction. SHA canonical bytes stay the
existing algorithm; adding an owner key changes only new original content.

All actual finalization routes must pass the same capture/guard hook. Financial
generation/review still works when document fields are missing; proposed
preflight reports exactly which fields make an original incomplete. Whether
finalization without a complete issuer review remains an explicitly incomplete
financial finalization is a Root-coordinated API/UI policy; no silent default
completeness or breaking mandatory request is introduced by this plan.

For corrections with a proved prior document context, carry the original rental
object/contract designation from that actual context, bound to its source SHA;
do not substitute today's renamed unit or address. Capture consciously reviewed
issuer data for the new correction's publication as such, preserving the prior
issuer forever. If the source had no object context, keep historical object
fields unproved. Newly reviewed present-time issuer/object evidence cannot fill
that historical gap or claim an old capture time. An actual historical evidence
adoption path would require its own explicit reviewed provenance, not backfill.

No update/backfill of finalized old owner JSON, parties or stored PDFs is
allowed. Add pure period-wide context-family validation usable even without
disputes/archives, plus Root native streaming/full-original hooks before restore
DML. Present malformed/partial contexts are corruption, not legacy absence.
The write guard protects both old and new families against post-final overwrite.

Keep the delivered financial selected-source v1 and preview API unchanged.
Propose a separate strict `UtilityStatementArchiveSource` wrapper with schema
`utility-statement-archive-source/1`, exact `financial_source` v1 DTO, selected
`document_context`, context digest/completeness and `archive_source_digest`.
It binds both independent contracts. The operative reader proves the context is
the actual selected entry in the actual complete hashed owner family, with exact
parents/dates/source chain; no client context JSON or recomputed hash is proof.
Archive render/review/metadata include this wrapper. Profile-specific
completeness includes the actual frozen recipient postal fields as well; a
PartyIdentity with absent fields cannot be completed from today's Tenant. The
exact reviewed minimum for profile1 is a product contract agreed with Root, not
a claimed legal requirement. Legacy or old party-only
rows remain `document_context_unproved` and are unsuitable for the planned
complete original publication, while their checked read-only PDF remains valid.

## Precise first publication contract

Proposed own new files, only after ownership/basis confirmation:
`utility_statement_originals.py` for review/confirmed publication/replay and
`utility_statement_original_validation.py` for pure strict archive DTOs and
manifest validation. Existing source and renderer get only explicit typed reuse.
Root supplies the shared hooks listed below. No new DDL is expected for this
first synchronous archive packet; any actual DDL need is coordinated first.
`l2` remains reserved for TEHA.

The first typed publisher requires selected-source
`party_binding=frozen_at_statement_finalization`, its actual StatementParty and
the newly proved complete document context described above. Frozen party alone
does not make today's address-less preview a complete sendable original.
Selected legacy `historical_party_unproved` remains available as the delivered
read-only financial source/PDF; it must not acquire today's contract tenant.
This narrows the earlier tentative property/unit-only legacy archive proposal:
an unproved historical financial archive subject needs a separately agreed Root
privacy/recovery policy before implementation, rather than silently becoming a
tenant original. Proved selected corrections may retain explicitly unproved
older chain entries; all their actual financial source hashes still get checked.

Independent source/content identifiers remain explicit:

- existing `statement.snapshot_hash`: canonical complete settlement period SHA;
- `source.source_digest`: exact existing selected-source DTO SHA, including its
  source DTO profile and actual source chain;
- `archive_source_digest`: exact financial-source plus newly proved selected
  document-context wrapper SHA;
- archived `pdf_sha256`: exact prepared/stored PDF bytes under the new archive
  render profile, never inferred from the other hashes.

Keep `UtilityStatementOriginalSource` schema/profile/bytes unchanged. Its
`utility-statement-pdf-preview/1` literal is the existing source DTO contract.
Introduce the separately reviewed renderer profile
`utility-statement-pdf-original/1` in the archive review, consuming that exact
verified financial source and complete archive-source/context wrapper. The
profile uses the same proven financial layout/fonts, the frozen object postal
identity/unit designation/contract number and explicitly captured issuer,
with neutral document heading/footer instead of the current preview wording.
It claims neither a signature nor delivery, and never includes a wall-clock
archive time in deterministic PDF bytes. Before confirmation it is only the
prepared PDF intended for archival; the receipt/manifest proves actual storage.
This explicit profile requires its own real render/Unicode/page proof.

Proposed strict `UtilityOriginalPreviewRequest` fields:

- `statement_id`, `expected_revision` (positive strict integer);
- `expected_snapshot_hash`, `expected_source_digest` (64 lowercase hex);
- `expected_document_context_digest`, `expected_archive_source_digest`;
- `archive_render_profile` (the exact supported literal);
- optional `correction_of` with exact prior `document_id` and `version_id`.

All IDs/hash expectations refer to a real freshly loaded authorized source.
They are optimistic expectations, not accepted cached source proof. No raw
client-original JSON, arbitrary tenant binding or client period-hash cache is
accepted. `correction_of`, when present, must be the actual immediately referenced
prior Statement's typed archived original, matching actual contract/unit/dates,
earlier revision and frozen party. An earlier Statement need not already have a
PDF archive for a valid finalized correction to acquire its own first original.

Preview returns exact archive-source wrapper, archive render profile, PDF SHA/size,
optional validated correction reference, current actor/grant review binding and
`review_hash`. The SHA covers this canonical strict review. Actor/grant binding
is server-derived from the actual authority machinery and recalculated at
commit; repeating a supplied binding never authorizes anything by itself.

`UtilityOriginalPublishRequest` adds `review_hash`, `expected_pdf_sha256`,
`idempotency_key` and strict `confirmed_original=true`. The route/path Statement
is also in the canonical request SHA, as are every request field and actor.
Draft DTO/profile, stale source/party/revision/profile/review or missing explicit
confirmation conflict. Publication is local archival only, with no delivery flag.

The proposed response receipt contains `document_id`, `version_id`, Statement/
period/revision references, snapshot/source/PDF SHA, render profile, actual
archive time, stored size and existing immutable version download URL. It states
`archived_original`; it states no signature/transmission. Replays return this
stored receipt and stored content identity, without invoking today's renderer.

## Exact immutable metadata and identity/idempotency

Document type is `utility_statement_original`. Base Document fields keep their
existing types and actual property/unit/contract IDs. Its virtual URL is
`/uploads/utility-statement-originals/<document_id>.pdf`; Root files integration
resolves verified existing chunks, never a mutable loose PDF file.

One extra metadata key `utility_statement_original` contains a strict object:

- `schema_version=utility-statement-pdf-original/1`;
- exact review object/hash, archive-source wrapper and archive render profile;
- actor/client key, canonical request SHA and confirmed-original marker;
- PDF SHA/size and optional strictly validated correction reference.

The pure validator rejects missing/extra/malformed subtype fields, mismatched
Document/manifest IDs or URL, source/party/parent identities, wrong operation/
number/predecessor/restored-from, actor/key/request/review/content digest or size.
Raw archived subtype metadata protects the original even if current editable
Document.document_type is later changed. A type label alone proves nothing.
Absent expected subtype data is corruption, not permission to use generic rules.

Proposed deterministic Document ID:
`uuid5(NAMESPACE_URL, "immo-manager:utility-statement-original:v1:" + statement_id)`.
The actual globally unique Statement ID therefore anchors one first original
across actors/client keys/profiles, using the existing Document primary key.
The first stored render profile remains that original's profile. A later profile
does not silently replace it; a future explicit additional-publication policy
would need separate linked immutable evidence. New actual settlement revisions
have distinct Statement IDs and their own original Documents.

For this subtype only, Root derives the manifest key
`utility-original:` + SHA256(UTF8(client idempotency key)). It fits the existing
100-character field and `(actor_id,idempotency_key)` unique constraint. Existing
generated callers keep their `generated-<docid>` convention. No generic exposed
override or relaxed claim check is introduced.

Publication first looks up the actual actor/key claim under scope. Same exact
request returns the verified stored original receipt/bytes after actual source,
manifest/chunk and current authorization checks; no rerender/profile upgrade.
Changed Statement/review/content under the same key returns conflict. Another
key/actor for an already archived Statement returns an authorized existing-
original conflict/reference, never a new fabricated replay receipt. Native
Document PK and actor/key uniqueness resolve independent-connection races;
uniqueness errors are handled after rollback in a fresh authorized snapshot.

The two-actor behavior is deliberately distinct from replay:

| Actual competing command | Result after winner commit |
| --- | --- |
| Same actor, same key, same exact request | Existing verified receipt; no new Document/manifest/chunks. |
| Same actor/key, another Statement or changed review | Actor-key conflict, even when the second Statement has no archive. |
| Different actor or different key, same Statement | One Statement Document; loser gets authorized already-archived conflict/reference, no second command receipt. |
| Different actors, same key string, different Statements | Independent actor namespaces; each valid original may commit. |

Native tests must count actual manifests/Documents/chunks through independent
connections after both actor orders, not only assert response status. No command
row is invented for the unsuccessful second actor; the immutable winning row
remains its actual actor/request evidence.

## One actual transaction, actual source proof through commit

Use the existing actor/native account fences, authoritative Work boundary and
Memory undo. Do not nest `document_versions.work` or call a facade that commits
the newly created Document independently. The compound caller owns one Session,
Document insert, first manifest/chunks, receipt result and rollback.

Acquire existing domain locks in coordinated order: actual account/grants, frozen
tenant and location/contract parents, actual billing source/root-period locks,
then deterministic Document subject. Re-read current original rows/parents under
the owned transaction. Verify every affected period and complete party family,
old source hashes and selected source digest using actual DB rows. Render the
reviewed archive profile, match expected review/PDF bytes and fresh actor/grants
before actual commit. Root determines the concrete shared lock order; no second
private fence or permissive checked flag replaces it. Memory snapshots must cover
new Document and both version tables, with error/revocation undo.

The archive tenant is exactly selected StatementParty.tenant_id. Actual frozen
tenant/property/unit/contract/source references must still exist and belong to
the allowed portfolio. Current contract location/portfolio still must match;
only its tenant equality gets the proved subtype alternative. Today's profile
name/address never enters the immutable source or historical comparison.

Generic upload/restore into this original is blocked when either current typed
Document identity or raw existing archived subtype identifies it. A real
correction publishes a new Statement's Document and optionally links the proven
prior original; original bytes/metadata/source references remain unchanged.

## Root-owned shared composition, supplied pure hooks

| Actual change point | Required precise behavior / owner |
| --- | --- |
| `document_versions.validate_manifest` | Root dispatches exact utility pure subtype validator alongside existing housing proof; generic fields/identities stay enforced. |
| `_document`, `_authorized_version`, `publish_generated_original` | Root's narrowly typed, actually verified subject path derives frozen tenant and internal claim key; no caller-supplied bypass boolean or free tenant override. |
| `document_versions.publish` and protected-document edits | Root extends immutable generated-original protection to the validated utility subtype/raw archived marker; ordinary upload/restore behavior stays. |
| `tenant_document_versions.append_document_versions`, tenant graph/privacy hooks | Root includes the actual frozen tenant's typed evidence after current contract rebind; exclude it from the replacement tenant. Scope completeness and full original byte verification remain. |
| `document_version_validation._verify_document_versions` | Root native staged verifier proves typed source against actual period/Statement/party/source parents before permitting frozen-tenant alternative. No global current-tenant equality removal. |
| Root native billing party/dispute source helpers | Reuse actual streamed full-period/source hashes and targeted actual parents. Only internal actual-native results may be memoized; supplied metadata digest alone is insufficient. |
| `/files` virtual resolver and source routers | Root coordinates actual actor-bound immutable download/publication routes and CheckedPublicationRoute; own publisher supplies precise API DTOs/service functions. |
| central startup/reset/recovery/registry | Root composes pure validation before any restore/reset DML and existing foreign-key/immutable guards; own packet edits none. |

Proposed own pure `validate_utility_original_snapshot(row, metadata)` returns
typed source/subject/claim information after exact standalone self-consistency.
It imports no auth/config/dependencies/app/storage/repositories or operative
publisher/renderer. Root's native helper separately proves that selected JSON
matches actual immutable Statement data, complete affected period SHA, exact
frozen party family and all source-chain hashes in the same staged snapshot.
The two checks compose; recomputed forged metadata/source/review hashes cannot
legalize another party or altered unselected sibling. Native chunk verification
continues streaming the actual bytes and matching the original manifest SHA.

## B/L follow-up: large bundled output through existing jobs and temporary files

The present synchronous individual PDF/source/draft APIs stay available. A
separate large-bundle command is proposed; neither this plan nor first archive
publication claims the existing in-memory ZIP meets large-stock budgets.

Extend the existing operational-job core by explicit strict families/adapters,
not by disguising billing work as `correspondence` or introducing another queue:

- `utility_pdf_bundle`: read-only bundle over a server-validated period/selection,
  with expected original-source membership hash/count, actual actor/grant scope,
  mode/profile and stable upper keyset bound. Archived-mode items point to actual
  verified DocumentVersion IDs; derived-mode items retain only strict immutable
  source/PDF identities and are regenerated from actual verified sources.
- A later `utility_original_archive` family requires its own explicit reviewed
  whole-selection confirmation and item-level original receipts. Download/export
  permission or a read-only PDF preview never implies bulk archival consent.

Root owns `operational_job_types.JobCreate`/Family/FAMILIES, adapter dispatch,
typed family parameters/results, state/counters and `operational_job_validation`.
Existing JobCreate currently forbids these parameters/families, and its staged
validator requires matching family/result semantics. They must be composed
together with backward-compatible existing job semantics, not patched by a
private publisher. Existing job/lane/item JSON and keys appear sufficient; if
new DDL becomes necessary, Root assigns its revision before implementation.

Native eligibility/authorization filters precede keyset paging. A packet has a
positive page/time budget and actual stable cursor/upper bound, with no global
history materialization or silent total-job cap. Existing lane lease/fence and
actor/grant checks apply before effects/checkpoint commit. Each persisted item
has bounded source/receipt identity, not all PDF bytes in result JSON. Crashes
after an archive effect but before a packet response recover its existing exact
receipt; one worker cannot advance another worker's expired/fenced claim.

Build bundles in existing protected private workspaces/temporary files. Stream
verified <=65536-byte archived chunks or one checked derived PDF into ZIP entries;
never hold all PDFs or the full ZIP in RAM. Final close/size/SHA/entry completeness
precedes release. On process loss rebuild the temporary ZIP from durable ordered
item identities; do not trust/append an incomplete prior ZIP as a completed
artifact. Archive originals remain in existing chunks, and temporary bundle
files are disposable derivatives. Publication refreshes authority before
response start and disposes abandoned private output using the established
export lifecycle. A stored path or old client hash never authorizes download.

This still needs explicit time/memory/source-verification proof. Full affected
period hashing, complete owner-family JSON, long correction chains and a single
very large Statement can dominate a packet. Do not persist an unverified hash
cache or skip sibling validation to manufacture positive progress. Root must
choose and test a coherent resumable verification strategy/budgets before calling
large jobs bounded; source corruption/revision changes across packets invalidate
the selection and require review/attention. Existing read-only API stays while
that later work is implemented and measured.

## Separate implementation and actual acceptance sequence

1. Agree exact shared subject/claim hooks and ownership on the current Root base;
   implement the additive future finalization context before own pure typed
   archive DTO/validator and explicit archive render profile.
   Preserve delivered preview/draft schemas, modes and APIs.
2. Implement one caller-owned confirmed transaction/replay and precise Root
   typed document read/privacy/native recovery composition. Do not expose a
   successful archive route while its original/restore subject proof is missing.
3. Run coordinated synthetic focused Memory, independent SQLite and actual
   PostgreSQL gates, then archive render/Unicode multipage PNG QA:
   actual complete context review/finalization -> tenant profile/object postal/
   unit-label/issuer/contract-party change; two actual corrections preserving
   source object and old issuer; context-less old party-only/legacy refusal plus
   unchanged read-only preview; missing source context explicitly unproved;
   draft refusal; no Document on read/review; same-key lost-response replay;
   changed-key payload conflict; different actors/keys racing one subject;
   actor/key racing different Statements; current source/sibling/party corruption
   even after forged rehash; grant/token/source loss through real commit;
   failed insertion/render rollback with no orphan Document/chunks;
   ordinary upload/restore cannot overwrite original; exact frozen privacy
   inclusion/exclusion after contract rebind; exact stored PDF SHA/bytes through
   full backup/restore and fresh pure-import blockers before staged DML.
4. Separately compose strict operational jobs, temporary bundle lifecycle and
   negative crash/resume/fence/source-change proofs. Measure large stock on
   documented hardware, beginning with the roadmap's 100,000 financial rows and
   then 1,000,000/20-year/ten-user target. Record actual memory/time/SQL behavior;
   the seven focused source/draft PG passes prove none of these large-stock claims.

No native/browser/visual process was started for this plan. Source/renderer
product acceptance and this unimplemented archive/jobs proposal remain distinct.

## Assigned pure future-context packet: interfaces before code

Root accepted the architecture and assigned only these new own sources:

- `backend/services/billing_statement_document_contexts.py`: strict
  PostalIdentity/ReviewedIssuer/StatementDocumentContext/StatementDocumentContexts,
  pure capture/correction and complete-family snapshot validation;
- `backend/services/utility_statement_archive_source.py`: strict archive-source
  wrapper/completeness and pure binding to unchanged FinancialSource-v1;
- `backend/tests/test_billing_statement_document_contexts.py`: synthetic pure
  positive/negative family/correction/import regression, no operative fixture.

Exact proposed exported helper signatures:

```python
document_context_family(period) -> StatementDocumentContexts | None
capture_document_contexts(period, statements, *, parents, reviewed_issuers,
                          actor_id, captured_at, verified_period_hashes=None,
                          statements_for_period=None) -> dict
validate_period_document_contexts(period, statements, *, parents,
                                 verified_period_hashes=None,
                                 statements_for_period=None) -> None
validate_document_context_snapshot(*, parents) -> None
build_archive_source(financial_source, document_context) -> UtilityStatementArchiveSource
validate_archive_source(value) -> UtilityStatementArchiveSource
require_complete_archive_source(value) -> UtilityStatementArchiveSource
```

Capture returns a NEW owner JSON copy containing the context family; it performs
no write/finalize/authorization. It accepts only actual draft/review periods and
matching unhashed draft/review Statements, no existing context family. Root
first supplies its newly captured existing Party-v1 family in that draft owner
JSON, then calls capture, then hashes/finalizes all originals atomically. Actual
referenced parents are supplied by Root's locked snapshot, with identity/location
checks in the helper. Never call it on a finalized old period to fill omissions.

`reviewed_issuers` is an internal mapping by actual Statement ID, containing
strict explicit issuer name/postal identity, role landlord/representative,
optional independently named landlord, and strict true confirmation. Unknown
Statement keys or unconfirmed values fail. Absent review means issuer=None and
explicit incompleteness, not a fallback to Portfolio or prior issuer. A provided
review needs the actual nonempty captured actor; Root authenticates the human
review and supplies server capture time, never a client historical timestamp.
Postal completeness for this first product profile means nonempty name/street/
postal-code/city, rental street/postal-code/city/unit designation and contract
number, and the existing frozen recipient postal fields. Country/floor/property
display name remain explicitly optional. Representative issuer additionally
needs the named landlord postal identity; no authority/signature is inferred.

Each context records exact parents/period dates/revision, Party-v1 digest,
object/contract designation, explicit issuer or null, capture actor/time, source
Statement/snapshot/context digest and object-binding mode. Initial capture reads
current supplied object/contract parents. Correction proves the complete prior
actual source period/family; copies only its object/designation, including missing
values, or uses historical_object_unproved/null when context is absent. Current
renamed/addressed object cannot fill any correction gap. Issuer belongs only to
the explicit review of the new finalization. Entries contain no mutable success
or completeness flag that could legalize missing fields.

The validator composes existing pure parties, exact unchanged settlement hashes
and recursive actual prior contexts, checks all coverage and source relations,
and rejects cycles, duplicate/missing/foreign entries or recomputed digest with
wrong source/object. Default pure snapshots derive hashes from complete supplied
rows. `verified_period_hashes` and `statements_for_period` are INTERNAL Root-native
hooks only: the former holds actual streamed complete-period SHA results, the
latter supplies actual rows for targeted source periods. They are never HTTP/
JSON request fields. Native paths consume period iterables once without global
RAM history; a missing explicit native hash is an error. Parent maps may be
targeted/lazy. Root's verifier owns coherent DB snapshot and actual cache origin.

ArchiveSource schema remains `utility-statement-archive-source/1`; fields are
exact FinancialSource-v1, optional selected context, context digest, explicit
missing-fields tuple/list, derived completeness and archive-source digest. Pure
model validation proves exact selected Statement/parents/dates/party binding,
context digest and financial source digest. It is no substitute for actual
native whole-family/source proof. A missing context is valid explicit unproved
state; `require_complete_archive_source` alone refuses complete publication.
Root leaves incomplete financial finalization allowed without changing existing
finalize request requirements. Actual Finalize/Guard/Recovery/Archive/Privacy/
HTTP/UI/shared code and migrations stay outside this own packet.

Heavy/native tests wait for the Root Finance/B1 slot. Static checks may run while
other agents own the native slot; results are recorded separately from later
actual operative finalization/native integration proof, which Root owns.
