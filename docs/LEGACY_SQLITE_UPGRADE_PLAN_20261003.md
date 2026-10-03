# L/A: explicit adoption of unversioned legacy SQLite installations

Recorded before source edits. Own checkout `work/legacy-sqlite-upgrade`, branch
`assist/legacy-sqlite-upgrade`, starting point `3e15341`, fast-forwarded to the
clean composed Root source `838089a` before implementation. The accepted A–L
roadmap and full-backup plan remain authoritative. Root owns app startup,
dependencies, runtime schema checking, recovery, settings and CI. No private
installation, preview, existing database or existing key is a test input.

## Findings and boundaries

Release 126 (`1910f25`) registered its metadata and applied additive compatibility
DDL through `backend.db.session.create_tables`, without an Alembic revision.
The initial migration creates already existing core tables. Running it against
such an installation collides; guessing a historical revision would hide
missing constraints and guards. The existing invoice/credit offline upgrades
are deliberately narrow and do not resolve whole-installation adoption.

Current full recovery requires later measurement-binding columns and scheduler
tables that a complete older installation legitimately lacks. Root will accept
only a positive internal legacy-schema proof for these specific omissions.
There will be no second archive/encryption format and no broad legacy bypass.
Normal restore rotates its signer and revokes sessions; an immediate checked
upgrade rollback must preserve the selected installation's original identity.

## Packet 1: reproducible, complete read-only recognition

1. Produce frozen reference catalogs from repository-owned Release-126 source
   in isolated synthetic directories, using generated synthetic keys and no
   provider execution. Include the actual fresh `create_all` path and a known
   historical core/additive path if it passes the complete compatibility
   requirements. Record the exact source commit, build recipe and catalog hash.
2. Recognition reads SQLite in read-only mode. It compares every application
   table, ordered column definition/default/nullability, primary key, native FK
   including delete actions, unique/check constraints, index order/collation/
   expressions/partial predicates, views and original retention triggers against
   a complete frozen profile. Missing/partial families, weakened guards, extra
   unknown schema or a populated version marker are refused. No table-count or
   approximate name-set inference is used. SQL normalization preserves literals.
3. Expose `prove_legacy_schema(connection: sqlite3.Connection)` returning a
   frozen `LegacySchemaProof` only on complete positive comparison. It contains
   `profile_id`, `source_commit`, `schema_sha256`, `missing_tables` and
   `missing_columns`. `permits_missing(table, missing_columns)` accepts only the
   exact declared later omissions. A supplied proof is never trusted without
   checking its catalog hash against the actual connection being examined.
4. Root integrates that internal proof into its existing database/archive
   validation. The complete unchanged legacy image passes the normal encrypted
   container, file/key/reference and actual isolated restore validations. Unknown
   legacy schemas remain actionable failures. Proof modules import no app,
   configuration singleton, dependencies or provider.

## Packet 2: explicit offline upgrade with a checked return path

1. An independently importable maintenance service/CLI selects only the explicit
   installation and its persisted configuration. Before imports that could
   write, it obtains the exact same `.backup-runtime/installation.lock` kernel
   lease used by managed startup and full-backup operations. It never stops or
   adopts a guessed PID. `--offline` is required; a live lease/writer refuses.
2. Under an actual SQLite write reservation, verify identity/integrity/FKs,
   prove the full legacy catalog, and capture typed row fingerprints for every
   original column/table plus installation files/configuration fingerprints.
   Create and validate the unchanged encrypted complete archive before any
   original schema mutation. Exercise restoration in an owned portless private
   directory; restored signer changes affect that copy only.
3. Prepare the same explicit upgrade on an isolated SQLite snapshot first.
   Apply supported narrow financial reconciliation only when the exact profile
   requires it, then the bundled real post-z1 migration functions in dependency
   order. No migration source or revision is introduced or edited. A synthetic
   empty copy of the approved legacy DDL supplies the expected complete final
   catalog, so proof includes guards and constraints rather than only columns.
4. Check all old typed column values, originals and original constraints/indexes/
   triggers, with only already documented financial-check replacements allowed.
   New historical measurement bindings remain NULL; no evidence is invented.
   Record schema/integrity/file validation separately from business review:
   inherited business states are preserved and explicitly marked as requiring
   review where their source evidence is absent.
5. Only after staging proof succeeds, run the same changes in a single native
   SQLite DDL transaction on the selected original. Write the sole bundled head
   only after the complete final catalog and preservation checks succeed; this
   records a proven completed adoption and does not claim that old migrations
   ran historically. Commit only after durable private recovery metadata exists.
6. Retain the complete archive and unchanged original snapshot with an operation
   UUID and durable phase/identity receipts. Abort rolls back all original DDL.
   Status resolves crash boundaries by comparing original/proven-final states;
   ambiguous states refuse automatic correction. No normal startup repairs them.
7. A separate explicit rollback accepts only that operation's exact installation,
   verified archive/snapshot and unchanged post-upgrade rows/files. It refuses
   subsequent business writes or replaced resources instead of discarding them.
   It preserves original keys, session rows, uploads, settings and original
   unversioned schema, and verifies the restored state before reporting success.

## Packet 3: CLI integration and evidence

The new CLI supports read-only inspection/status, explicit upgrade, and explicit
checked rollback. Passphrases are interactive, never command-line arguments or
logs. Capacity/deadline settings are positive explicit policies. Errors are fixed
actionable codes with no SQL parameters, private paths or credentials in logs.
The smallest `maintenance.py` dispatch hook is an expressly separate commit;
existing update behavior stays under Root's composition ownership.

All tests use synthetic source profiles, rows, encryption keys, sessions and
uploads. Focussed native gates cover complete recognition and weakened guards,
partial families, wrong revision, backup/restore before DDL, exact original value
and file preservation, concurrent startup/writer refusal, injected transaction
failure, process death at durable boundaries, rollback success and refusal after
new writes. Existing narrow upgrade, maintenance, full recovery and read-only
startup tests run only in the coordinated test slot. PostgreSQL is out of scope
for this SQLite adoption service; no new schema revision is reserved or created.

Root alone integrates changes and runs central composition/CI. A successful
synthetic local gate never authorizes migration of the user's private database.
