# Private draft owner discard, uncertain expiry and native source negatives

Plans before code: f5ab8bd and 89a9e3c. Special journal-draft prerequisite is
79ea761. Product scope is the common form_drafts service; no migration.

An active authenticated owner can explicitly CAS-discard its own ciphertext
after complete portfolio removal or a readonly change. Fresh owner/principal
checks and the account-management lock remain; another principal or stale CAS
cannot discard it. Read/write still require the original domain grants.
Discard runs before automatic expiry and does not depend on any old key or
decryption. Existing owner/entity/form identity derivation is unchanged.

Automatic expiry now authenticates the pending flag before erasing old work.
Ordinary abandoned edits retain their existing expiration. Uncertain submitted
commands remain protected until explicit resolution/discard, with optional
expiry_deferred=true in the read envelope. Inputs, original JSON, UUID,
preview and expected revision are unchanged. Corrupt ciphertext/missing key
produces the existing recoverable error and retains the row, not a fake empty
draft. Private restoration still checks current unchanged scope and all real
domain references. No new metadata/persistence field, sidecar or job.

## Actual focused gates

One serial actual application run selected owner-only revocation, real pending
open/append replay plus expired-pending retention, damaged-expired ciphertext,
and the existing ordinary-expiration regression: **14 passed** as part of the
18-node command, 156.81 s, no skips. Memory, actual migrated SQLite and dedicated
actual PostgreSQL are represented; ordinary expiry is existing Memory/SQL.
The other four new native counterexamples failed in fixture setup because the
rehash helper omitted its required explicit deadline keyword. The verifier
had not yet been called for those scenarios. Only that fixture argument was
corrected; product source and integrity rules were unchanged.

Separate focused recheck of those four SQLite/PostgreSQL counterexamples:
**4 passed**, 35.87 s, no skips, seven unrelated nodes deselected:

- Remove a sibling party from a two-statement original and recompute the actual
  whole-period SHA in every statement. Native semantic proof still rejects
  the incomplete party family before any restored session mutation.
- Create a genuine new correction from an explicit legacy original using the
  real generation/finalisation API, then damage the other legacy source
  statement without changing the selected source ID/SHA. Complete native
  source-period hashing rejects it before session mutation.

The four source counterexamples exercise the existing e2296fe native
whole-party verifier and restore barrier. No new party verifier behavior was
required. SQL fixtures use real migrations/native statements; no fake hash
service, drop/reinstalled guards or modelcreate_all replacement.

External logs: work/root-draft-owner-expiry-native-originals.log and
work/root-party-native-counterexamples.log. These are source tranche proofs,
not full A-L release/private deployment/large-stock performance claims.
Ruff on common service, special policy and both test files passed; Mypy on
both product services passed before native execution.
