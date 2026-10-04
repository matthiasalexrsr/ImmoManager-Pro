# I/L: authenticate the actual archived connection state

Root pre-code step following the runtime composition plan, 2026-10-03.
The active connection factory remains unchanged in this step.

`full_recovery` currently checks only that integrations.json is an object.
An authenticated full container can consequently contain an encrypted envelope
that cannot be decrypted by its own archived field keys. The integration state
must be authenticated before either backup or restored installation publication.

Add a pure recovery adapter around the existing offline encrypted verifier.
Its inputs are an explicit path, archived configuration and positive caller
budgets. It never imports Settings/auth/providers/application code, acquires a
store lock, writes a state file, migrates plaintext or uses ambient field keys.
An encrypted-looking malformed file is never interpreted as legacy plaintext.
Legacy complete JSON state remains supported with an explicit legacy result:
that preserves the complete-backup-before-conversion path.

Backup binds the verifier's state SHA to the actual integrations.json record
written into the encrypted container before publication. Restore verifies the
staged entry using its archived configuration before any session invalidation,
file rebasing or target publication. Recovery metadata budgets bound a single
operation; JSON-depth policy is positive and caller-configurable without an
arbitrary upper ceiling. Existing old archives and an absent connection file's
explicit empty placeholder remain compatible.

Focused actual acceptance uses synthetic native migrated SQLite, the real
encrypted full-container writer/reader and stable archived field keys:

- genuine encrypted roundtrip preserves bytes, unknown fields and decryption
  after JWT rotation;
- wrong/missing key, malformed envelope and tampered ciphertext are refused
  before backup/restore publication; a correctly rehashed container is still
  refused if its inner connection envelope is invalid;
- changed source between verification and archive write is refused before
  publication;
- fresh-process import tripwire proves the adapter has no ambient runtime
  dependency;
- existing genuine legacy roundtrip remains supported.

Tests and implementation precede activation. Run heavy native acceptance only
after the coordinated PDF/browser slot. This step does not prove TEHA provider
writes, activate global encrypted storage or perform private conversion.
