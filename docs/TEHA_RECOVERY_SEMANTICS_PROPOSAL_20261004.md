# TEHA recovery and retention: concrete Root integration proposal

This is a reviewed source proposal, not an implemented shared Recovery adapter.
No shared Recovery, Registry, Auth, Jobs, Startup or Settings file is changed.
Current public writes remain 503 because the actual Root transaction unit is
absent. No positive write, restore or retained-family acceptance is claimed.

## Validate the selected image before target mutation

Use only the explicitly selected backup/image connection and its authorized
keyring. Never fill a gap from the running installation, `configured_history()`,
the request store or a live provider. Validate the existing generic History,
DocumentVersion/chunk and OperationalJobs families with Root's image validators
before evaluating L2 references. A validator performs no DDL, DML or provider I/O.

An absent L2 family remains legacy-compatible. One table, an older isolated
development layout, nullable/missing mapping evidence, or an inconsistent family
fails before restore/transfer mutation. The frozen initial release layout is
the baseline; the runtime helper checks exact columns/nullability, primary keys,
required uniqueness and exact RESTRICT FKs. Root's image gate must additionally
verify the release CHECKs, partial unique predicates and immutable guards, not
infer schema equality from the revision label or a successful ORM query.
Existing L2 layouts are never silently reconciled by this reserved revision.

Scan every retained mapping/receipt with bounded keyset batches; a batch size
controls working memory, never an arbitrary total-row cutoff. Validate all rows
and all referenced original bytes before target mutation. A single invalid row
invalidates the selected TEHA evidence set; it is not skipped or repaired.

## Mapping, source and local target proof

For every mapping, validate the exact allow-listed opaque identity shape/hash,
kind, positive generation, confirmed state and exactly one corresponding target.
Recompute `mapping_reference()` and its digest. Retained generations are append
only; later generations do not replace the generation referenced by a receipt.
Check unique namespace/kind/identity/generation and source History references.

Read current target parents and tenant grants from the same image: property has
the recorded portfolio; period and unit have their actual current property and
that property's portfolio; user means an existing tenant with the recorded
portfolio grant; technical-order target has an existing property and, if set,
an existing unit belonging to it. Reconstruct the five-field
`mapping_target_binding` context from these rows. Do not copy that context from
the original manifest or accept a matching portfolio as proof of a target ID.
Generic document validation independently verifies the original's actual
property/unit/contract/tenant parents and archived version binding.

Decode each referenced History run from this image using Root's canonical
encrypted History validator. Require the `teha` integration, installation scope,
successful terminal `completed` outcome, correct connection namespace and the
recorded operation/arguments. Reconstruct the opaque source identity and complete
sanitized JSON hash; unknown provider fields remain part of that hash. A matching
hash of a different provider operation or connection is insufficient. No raw
provider payload is copied into relational L2 fields or public diagnostics.

## Receipt and original proof

For each receipt, require imported state and its source-kind-specific target
shape. Resolve exactly its `mapping_id`, generation and digest; require receipt,
mapping and original portfolio/connection agreement. Validate actor/command-key
uniqueness, exact source/content dedup and the retained command digest's syntax
and cross-reference equality. This is
evidence validation; it does not grant an authenticated actor permission to write.

For a document, use the recorded document/version IDs and generic original
identity/sequence/manifest checks. A TEHA publication is an initial
`archive_original` version; generic version history rules remain authoritative.
Then call `validate_document_manifest(..., mapping=..., mapping_target_binding=...)`
with image-derived target context. Require `teha-import/2`, receipt fields,
kind-specific original target and the classification recorded in the immutable
Document snapshot. Ordinary later live recategorization does not rewrite that
original classification. A `teha-import/1` development manifest requires explicit
offline maintenance, not auto-upgrading missing evidence.

The extension's `content_history_run_id` is not a relational FK. Resolve it
explicitly: successful `read_document`, exact connection/opaque reference,
`TehaDocumentContent` SHA/size and the sanitized omitted-bytes marker must agree.
Verify every original chunk, position, byte count and aggregate SHA against that
manifest. Download/replay uses the retained original; it never re-downloads a
provider PDF to repair missing chunks or invent an archived import receipt.

For a task, resolve the actual recorded task, its current property/unit parents
and the selected mapping context from the image. Match the successful technical
source identity/SHA and receipt's exact mapping reference. Preserve legitimate
later local task state; a provider status does not auto-complete or reopen it.
There are no finance target writes. The present importer only accepts source
associations proved for property (and documents for unit); period/user original
validation does not invent new provider association rules.

The present receipt does not retain the complete confirmed command/preview
payload. Offline recovery cannot independently recompute that request digest
from editable live Document/Task fields. Runtime replay recomputes it from the
submitted command; original-manifest equality only proves the archived digest
agrees with the receipt. Before writes are activated, Root must decide the
minimal immutable/encrypted command evidence required for independent recovery;
this proposal does not mislabel hash syntax or matching copied fields as proof
of the complete original request.

## Retention, clear and restore normalization

Retain the complete closure: referenced mapping generations, mapping and receipt
source History runs, original extension content History runs, document versions
and chunks, target parents and any actually populated job/work-item references.
RESTRICT FKs protect direct references; the content-History reference needs an
explicit retained-family guard because it is in the immutable JSON manifest.
Block clear/partial transfer before DML when it would sever that closure.
Never drop L2 or backfill evidence merely to make a partial transfer pass.

Apply Root's existing History/Job recovery normalization only to unfinished
outcomes after the whole image passes validation. Keep completed runs and
immutable imported receipts complete; mark an interrupted external outcome
uncertain according to the existing core, never `completed` or auto-retried.
Restore performs no login, provider read/write, email or business import.
Current receipt job/work-item columns remain null in prepared standalone imports;
they do not claim durable queued work or resumable inbox bytes. A journaled PDF
hash before local publication is not itself durable unreviewed PDF storage.

The future actual Root unit must own the real Session, transaction, database,
operation and concrete targets through commit. Replacing the unconditional gate
with an actor-only validator around the service's independent Session is
insufficient. Positive atomicity/CAS/idempotency/revocation tests belong only to
that real composed implementation in Root's announced native slot.
