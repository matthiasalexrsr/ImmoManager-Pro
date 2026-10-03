# I/L: actual encrypted connection state in the complete SQLite container

Product `9fa541b`, pre-code plan
`I_ENCRYPTED_STATE_RECOVERY_ACCEPTANCE_PLAN_20261003.md`.
Actual composed source tested: `c85fc9f`, including the checked original/draft
PDF packet and DDL-free TEHA receive helpers. Schema head remains K2.

Actual isolated native gate:

`pytest backend/tests/test_integration_state_full_recovery.py backend/tests/test_full_recovery.py::test_full_roundtrip_preserves_every_table_uploads_and_configuration -q -rs --tb=short`

**9 passed in 31.76 seconds, no skips.** Eight new focused cases and one
unchanged genuine complete legacy roundtrip. No product/fixture repairs were
needed during this gate. Only synthetic data in owned temporary SQLite and
encrypted files; no private installation, live provider, server or schema was
changed. The Python process completed normally.

Evidence:

- Actual encrypted fullcontainer roundtrip retains exact connection bytes,
  all unknown private fields and working decryption with archived stable field
  keys after the real restore process rotates the JWT signer.
- Missing archived key, tampered ciphertext and malformed encrypted envelope
  reject before backup publication. Original source database/state unchanged.
- A genuinely re-encrypted complete container with correctly recomputed
  integrations.json manifest size/hash still rejects an invalid inner AEAD
  state before session DML or restored-directory publication.
- A valid source replacement between verification and actual archive writing
  rejects because the archived state SHA differs from the proved source SHA.
- Fresh native process imports the recovery adapter with Auth/config/Settings,
  application/dependencies/storage/repositories/providers/manager imports
  blocked. It proves the archived state without a sidecar, lock or mutation.
- Legacy JSON is explicitly identified and preserved without automatic
  conversion. The existing complete backup/restore test still preserves all
  tables, original uploads and stable encryption configuration.

Focused Ruff passed all three changed Python files; configured Mypy passed the
new pure recovery adapter; diff whitespace checks passed. These static checks
do not replace the native gate above.

This is the archived-state prerequisite only. The active global manager still
uses the legacy file store; a fenced conversion/checked-return path and factory
activation remain required. PostgreSQL/Docker appdata-state composition,
TEHA L2 registrations/chain/recovery, live TEHA actions and whole A–L common
release are not claimed by these nine SQLite/container cases. Recovery's
positive integration_json_depth can be configured with the capacity profile;
there is no arbitrary maximum added to that policy.
