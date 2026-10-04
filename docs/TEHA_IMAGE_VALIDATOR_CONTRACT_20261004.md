# TEHA selected SQLite image validator: pre-code contract

This package adds new files only. Root owns Recovery/Registry composition and
all native execution. It does not activate L2, public writes, jobs or retention.

## Actual available boundaries

`validate_history_journal(connection, image_keys, limits=..., deadline=...)`
uses the caller's connection and explicit `IBANKeyring`. `verified_artifacts`
authenticates encrypted event metadata and chunks using the real History AEAD
domain. These APIs need neither an authenticated actor nor a live factory.
They import static ORM metadata (including account event registration), so an
image boundary test is not the registration-free PureManifest gate.

`verify_document_versions(connection, deadline=...)` checks every immutable
original, its sequence, subject parents and bytes on the same connection. The
new adapter bounds image text/metadata before this API can materialize it,
including its special housing-confirmation snapshot read. These are explicit
caller resource budgets: exceeding one rejects the image; no value is trimmed,
provider field discarded, or total number of rows capped.

Do not import `recovery_history`, History Store, the provider journal reader,
receive command service, Settings, Auth or a Session/engine factory. Use the
existing image/crypto APIs directly, with an actual explicit keyring.

## Public contract

Add `validate_teha_receive_image(sqlite_connection, *, image_keys,
history_limits, image_limits, deadline)` in a new provider image module.
The caller selects and opens the image, enables `query_only`, disables
`trusted_schema`, and starts a stable read transaction. The adapter verifies
those conditions but opens no path, starts no transaction and changes no
pragma. Deadline and positive finite working-memory budgets are explicit.
Root owns the SQLite progress-handler cancellation for an individual SQL
statement; the adapter checks the same deadline between batches and rows.

An entirely absent L2 family returns an absent report without consulting keys.
A present family requires the frozen initial release layout. Validate types,
columns/nullability/PK/FKs, CHECK expressions, full unique constraints, partial
unique predicates and the four exact immutable triggers from selected-image
schema text. Never repair or adopt an isolated older L2 layout.

Scan all mappings and receipts with BINARY-ID keyset batches. SQL bounds text
before transferring it; exceeding a bound fails rather than turning an optional
oversized field into an accepted NULL. No retained-row cache or overall row cap.
Validate the complete encrypted History and generic original families first.
Then resolve every L2 reference on that same read transaction, deriving current
property/period/unit/task parents and tenant portfolio grants from the image.

Reconstruct source identity and digest from authenticated accepted arguments
and the successful terminal exchange. Keep unknown sanitized provider fields
in the source digest. Require `teha`, installation scope, successful completed
terminal outcome and exact connection namespace/operation agreement. Resolve
every original's JSON content-History link, compare opaque document identity,
content manifest, omitted-bytes marker, archived SHA and size. Use the existing
`validate_document_manifest` with the actual selected mapping and image-derived
kind-specific target binding. Check reverse original-to-receipt references too,
so orphaned TEHA originals do not escape a receipt-only scan.

The present importer only proves property associations, and document-to-unit
associations. Period/user/technical-order mappings themselves can be validated;
receipts that assert unsupported source-association rules must fail explicitly.
Task status/title remain legitimately mutable; validate current target parents
and retained external source, not invented equality with editable task text.

## Explicit remaining Root hooks

The existing OperationalJobs families contain no TEHA import lane or receipt
contract. Non-NULL L2 job/work-item references fail closed with an explicit
unsupported-binding code. Before enabling such references, Root must provide
an actual selected-image TEHA job binding validator (job actor/operation/scope,
lane/work-item/source/action/result/target), not merely an existing job ID.

The complete confirmed import/preview command is not retained. This validator
can prove hash syntax and receipt/original equality, not independently recompute
the complete command digest. Its report states that limitation. Before enabling
writes, Root must decide minimal immutable encrypted command evidence and its
image verification/retention hook. No receipt hash is a CommitAuthority.

Root calls this adapter in the existing selected-image validation transaction
before transfer/restore mutation. Root's retention/clear gate must preserve the
JSON content-History closure as well as relational FKs. Only after every family
passes may Root normalize unfinished History/Job states, using existing core
semantics; completed imports stay completed. This adapter performs no DDL, DML,
normalization, provider I/O, Session commit, auth refresh or live-data fallback.

## Source gate plan

Prepare separate new source tests: pure source reconstruction tests, then an
actual isolated SQLite image suite with real explicit-key AES-GCM History
artifacts, frozen L2 DDL/guards and original chunks. Exercise complete multi-
batch scans, wrong image/keys, missing/partial/old schema, changed CHECK/index/
guard, all mapping parents, wrong connection/source/target/original/content
bindings, chunk damage, reverse orphan closure, and closed job references.
No imports or test execution occur in this assistant slot. Root runs bounded
native gates and records results separately from this source review.
