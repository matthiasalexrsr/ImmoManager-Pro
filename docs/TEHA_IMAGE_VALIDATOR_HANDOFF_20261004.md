# Selected-image TEHA L2 validator: source-only handoff

Base: `cc28e09` on `assist/teha-receive-domain` (Root merged that work as
`d336401`). Root deliberately keeps L2/M2 release composition proposed; this
package changes no migration, Registry, shared Recovery, Auth, Jobs, Settings,
startup or live command source. Public writes retain their unconditional 503.

## Closed source commits

- `d869f92`: pre-code contract, actual API review and explicit remaining hooks.
- `707605d`: three new validator/evidence/schema modules and two new test files.
- This handoff is a separate final documentation commit.

No Python import, test, compile/lint, server, browser, DB/PG/provider process or
private-file access occurred in this slot. Only source/Git reads, new-file edits
and hook-disabled commits were performed. `git diff --cached --check` was clean
before the implementation commit; this is a whitespace check, not a native gate.
Existing Root PASS results for the preceding TEHA package do not validate these
new files. All new native Schema/Crypto/image and composed FullRecovery gates
remain unexecuted here.

## Actual callable boundary

`backend/services/providers/teha_receive_image.py` exports:

```python
validate_teha_receive_image(
    selected_sqlite_connection,
    image_keys=explicit_iban_keyring,
    history_limits=explicit_history_limits,
    image_limits=TehaImageLimits(
        batch_size=caller_batch_size,
        row_bytes=caller_scalar_bytes,
        original_metadata_bytes=caller_original_metadata_bytes,
        schema_bytes=caller_schema_bytes,
    ),
    deadline=caller_monotonic_deadline,
)
```

Root owns image selection/opening, `query_only=ON`, `trusted_schema=OFF`, `BEGIN`
and per-statement progress-handler cancellation. The API requires a native
SQLite connection with those conditions and an actual explicit `IBANKeyring`;
it changes none of them. No Settings/environment/live-key fallback, Store,
transport, Session factory, callback proof, actor DTO or CommitAuthority is used.
The caller's connection and keys are the only image context throughout.

The report contains counts and `command_digest_reconstructed=False`, without
IDs/payloads/keys. Absent L2 is legacy-compatible before key lookup, except when
a retained original already asserts a TEHA extension whose L2 family is missing.
Present/partial/old schema, malformed evidence or unsupported populated job
links raise constant `TehaImageError.code`; Root maps that boundary to its
existing recovery rejection before any target mutation.

## What is actually verified

`teha_receive_image_schema.py` derives expectations from the frozen initial
`backend/db/teha_receive_release_l2.py`, not running ORM model evolution. It
checks types, columns/nullability/PK/FKs, exact CHECK expressions, required full
unique constraints, named index columns/uniqueness/BINARY ordering, partial
unique predicates, and the four exact immutable triggers. SQLite index counts
must match the frozen release schema, bounding metadata before schema helpers
materialize it. SQL comments/equivalent alternative constraint spellings are
not silently adopted as a release layout; an isolated variant needs explicit
maintenance. Schema differences never cause DDL/repair.

All mappings/receipts are scanned in BINARY-ID keyset batches with no total-row
cutoff. Oversized/invalid nullable text causes rejection rather than accepted
NULL. Every retained generation is checked, including predecessor generation
existence and older generations referenced by receipts. All five kinds derive
current parent/portfolio/grant context from the selected image.

The adapter invokes actual `validate_history_journal` with explicit keys/limits
and `verify_document_versions` on the same snapshot. Generic original text and
full snapshots are SQL budget-checked beforehand, including the generic housing
validator's full snapshot read. These are explicit resource budgets, not new
classification rules or limits on unknown provider values. Nothing is trimmed.
History's existing API imports static ORM metadata and account event
registration, without using live Settings/Auth/factories; its image test is
therefore separate from the registration-free pure source-reconstruction gate.

Referenced History accepted/terminal artifacts are authenticated through the
real History `verified_artifacts`/AEAD API. Namespace, installation scope,
integration, operation/arguments, successful `completed` outcome, opaque
identity and full sanitized source digest must agree. Unknown provider fields
remain in the digest. Document content-History links are resolved explicitly;
identity, result manifest, omitted-byte marker, SHA/size/media and the fully
verified original agree. Original actor/request hash/generated key and the
`teha-import/2` receipt/mapping/target/classification extension are cross-checked.
Reverse original-to-receipt closure rejects orphaned TEHA extensions. Later live
classification and mutable task title/status are not mistaken for immutable
import evidence. Task property/unit parents and actual selected mapping still
must agree.

Current source associations accept property mappings, and document-list/unit
associations. Period/user/technical-order mapping evidence itself is supported;
a receipt claiming an unimplemented association rule fails explicitly rather
than inventing a rule.

## Exact prepared native gates

Run separately in Root's announced bounded slot:

```text
python -m pytest --noconftest -q tests/pure/test_teha_image_evidence.py
python -m pytest --noconftest -q tests/image/test_teha_receive_image.py
```

The first file is pure JSON/source reconstruction. The second uses isolated
in-memory SQLite, frozen L2 DDL/guards, actual explicit-key AES-GCM History
metadata/chunks and generic immutable original bytes. Its fixture DDL/DML is
test setup only; the adapter's trace assertion permits only SELECT/PRAGMA and
asserts unchanged `total_changes` and the caller transaction staying open.

Prepared cases cover all mapping kinds/current parents, complete and damaged
later keyset batches, older retained generation, actual multi-chunk encrypted
History/originals, wrong/missing keys, source namespace/terminal/source mismatch,
receipt/mapping/original/content cross-bindings, same-portfolio wrong target,
duplicate original JSON, reverse orphan closure including missing L2 family,
changed CHECK/type/partial index/guard, resource budgets, closed actor-only key
duck types, closed populated job links, absent/partial family, legitimate later
task state and live recategorization. These are prepared assertions, not PASS
claims. Root should additionally exercise its own selected archive connection,
authorized archived keys and composed restore/transfer/retention gates.

## Registry, migration and Recovery composition

Link this API to L2 (`teha_external_mappings`, `teha_import_receipts`) in Root's
central family Registry/Recovery plan after native gates; this package does not
register a family or add a new Registry protocol. Root's proposed L2 migration
must use the frozen initial DDL/guards; no source-derived model autoupgrade or
old isolated schema reconciliation. Existing revisions remain Root-owned.

Root's `backend/services/recovery_history.py` provides actual selected-key
History validation but also imports the live History Store. The new adapter
does not import that module: it invokes the pure image APIs directly. Root can
call this adapter from its common selected-image validation transaction before
the mutation phases coordinated by `recovery_validation.py`. Do not replace
its caller connection with a second path/factory connection.

The content-History link exists in immutable JSON without a relational FK.
Root's clear/retention/partial-transfer gate must preserve it, along with all
mapping/source History runs, versions/chunks and actual parents. Successful
validation alone is not an installed retention guard. A partial selection that
would sever the closure must reject before DML; no data dropping or evidence
backfill. Only after all selected families pass may existing Root normalization
mark unfinished external outcomes uncertain/revoke leases. Completed imported
receipts remain completed. No login, provider I/O, import or automatic retry.

## Deliberately unresolved proof

The full confirmed preview/import command is not retained; neither its command
digest nor a mapping confirmation request digest can be independently
reconstructed offline from editable current local rows. Syntax and retained
receipt/original equality do not prove the original complete request. Before
write activation, Root must choose immutable encrypted command evidence with
an actual image validator/retention hook. This adapter does not mint a receipt,
an authorized actor or a write guarantee.

Existing OperationalJobs have no TEHA import family/result contract. Any
populated L2 job/work-item reference fails `TEHA_IMAGE_JOB_BINDING_UNSUPPORTED`.
An actual Root hook must prove job actor/operation/portfolio, lane/work-item
ownership, source/action/result and concrete import target from the selected
image before those references are accepted. Generic parent-ID existence or a
notification capability is insufficient. The future actual write unit still
must own the real Session/transaction/database/operation/targets through commit.

Recovery semantics remain as specified in
`docs/TEHA_RECOVERY_SEMANTICS_PROPOSAL_20261004.md` and the pre-code contract
`docs/TEHA_IMAGE_VALIDATOR_CONTRACT_20261004.md`; this package implements their
selected-image L2 read proof within the explicit unresolved boundaries above.
