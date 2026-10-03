# L: exact legacy schemas through actual full backup and restore

The central read-only database validator now obtains its legacy proof from the
actual native connection. Only the two complete frozen Release-126 catalogs
permit their explicitly listed later omissions. All native schema objects,
constraints, indexes and original guards must match. The connection retains one
read transaction and reproves the catalog before returning. A caller cannot
supply a fabricated proof or a broad legacy override.

The existing full encrypted backup container, actual restore, key checks,
document/file checks and signer rotation are used unchanged. The newly missing
j2 family is accepted only as wholly absent; a present partial/unprotected
family is rejected. Early registry, explicit fresh dev/test original-guard setup
and read-only production guard checks are composed for j2. Its content/receipt
database proof is the next separately planned composition packet.

The trusted profile JSON is included in setuptools and the PyInstaller data
manifest. Native wheel/frozen packaging execution remains part of release QA.

Actual synthetic evidence:

- `legacy-full-backup-composition-recheck.log`: 6 PASS, no skips, 30.39 seconds.
  Both exact catalogs carried real synthetic invoices/payment reversals/IBAN
  data from the existing complete fixture through actual backup/restore. Catalog,
  rows, original files/integration bytes and unchanged source bytes were checked.
  Both altered-index and weakened-original-trigger variants failed before an
  archive was published.
- Ruff passed for the five touched Python product/test files. Mypy passed for
  Session, RuntimeSchema, FullRecovery and the pure LegacySchemaProof module.

The first six fixture cases failed before product backup execution: replaying
live rent-source triggers while reconstructing a synthetic snapshot collided
with its saved revision rows. The fixture now defers those exact reference
triggers during initial snapshot reconstruction and restores all original DDL
before complete native catalog proof. No product guard was weakened.

No private installation was read, changed, upgraded or released. Exact legacy
recognition alone is not the upgrade service, and this is not the A–L release.
The owner will regenerate only target omissions/head after the j2 integration;
frozen historical catalogs/hashes stay unchanged. Empty revision-marker hidden
objects receive a separate strengthened recognition check from that owner.
