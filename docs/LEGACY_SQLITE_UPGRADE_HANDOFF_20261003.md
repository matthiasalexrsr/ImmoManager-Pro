# L/A legacy SQLite adoption handoff

Own checkout: `work/legacy-sqlite-upgrade`, branch
`assist/legacy-sqlite-upgrade`. Root alone integrates. Original backup checkout,
private installation, main and preview remain untouched. No new migration or
second archive/encryption format is introduced.

## Sources and integration

The prior plan and first frozen proof are `94b24c6` and `e536825`, already
integrated by Root. Follow-on pure proof commits, in order:

* `f10f3a9`: refuse hidden objects on an empty version marker.
* `e88c008`: canonicalize only independent table-constraint order and validate
  the then-current J2 target; native column order, defaults, FK actions,
  uniqueness, index keys/collations/predicates and original guards stay exact.
* `7806ef0`: validate the actual K2 target, preserve combined SQL operators,
  and rebuild the old frozen original DDL natively to check reference drift.
* `d84f94d`: type annotations only.

Historical original DDL and source commit
`1910f25f12b9930ca4345f5be4212c60a1f2c89e` remain frozen. The two named complete
profiles are `release126-fresh-create-all` and
`release126-historical-receipt-checks`. Later omissions are precisely declared;
unknown mixed schemas, partial families or weakened native guards fail.

Service and command commits:

* `872e718`: isolated service/CLI, synthetic tests and operating instructions.
* `c4d5728`: separate minimal early `maintenance.py` dispatch only.
* `bac19b4`: strengthen original database/archive identity checks and explicit
  refusal diagnostics; add the identical replaced-database test.

The initial service gate was composed with Root's central `d56a31c` source in
its own checkout; the subsequent negative/crash gate includes Root's actual
whole-period party/recovery composition `e2296fe`. Own merge commits are not
integration inputs. Root owns packaged launchers, settings and CI. No central startup,
dependency or full-recovery source is changed by these commits.

## Exact interface

`backend.legacy_sqlite_upgrade.service` imports no application/settings at module
load. `installation_lease(data_dir)` obtains the same native
`.backup-runtime/installation.lock` before recovery/configuration imports.

* `upgrade(args, password, *, limits=None)` performs a real native SQLite writer
  reservation, complete profile proof, unchanged encrypted full backup and
  actual isolated restore before original DDL. It prepares expected/actual
  native schemas separately, applies the real bundled migration functions and
  checks preservation in one original DDL transaction. It records only the
  fully proven bundled head, never a guessed old revision.
* `status(args, *, limits=None)` checks the selected original file identity,
  private operation receipt, complete catalog and typed fingerprints of every
  table, distinguishing `original`, `upgraded` and `changed` at crash boundaries.
* `rollback(args, *, limits=None)` requires exact original installation/file
  identity, checked archive/snapshot and unchanged rows/files. It rebuilds the
  positively proved snapshot's exact raw original definitions and rowids in a
  native transaction. It preserves original keys, sessions, uploads and config;
  later business writes or replaced resources refuse the return.

Common arguments are `data_dir: Path`, optional `database`, `uploads`,
`integrations`, `capacity_file` and `timeout_seconds`. Upgrade additionally
requires `offline=True`, `output: Path`; status and rollback need
`operation_id: str` (canonical UUID), and rollback requires `offline=True`.
Limits reuse the central positive `RecoveryLimits`/`sqlite_recovery` capacity
policy. Passphrases are interactive CLI input, never argv or logs.

Python/source command: `python -m backend.maintenance legacy-sqlite`
followed by `inspect`, `upgrade`, `status` or `rollback`. The early dispatch
precedes updater and launcher configuration imports. Any frozen launcher
exposure belongs to Root; this packet does not add a competing launcher hook.

Private recovery receipts and the protected complete original SQLite snapshot
are retained under `.legacy-sqlite-upgrade/<operation UUID>`. Receipt durability
precedes commit. Source business review is explicitly
`legacy_business_states_preserved_require_source_review`; complete schema and
integrity validation do not invent missing historical payment/source evidence.

## Actual local evidence

All inputs, accounts, sessions, IBAN keys, uploaded bytes and retained original
PDF/chunk bytes are synthetic. Every run uses the shared project virtualenv,
is serial, and is coordinated with Root's native/browser gates.

* The actual K2 reference generator completed successfully and preserved the
  frozen historical original DDL byte-for-byte.
* Corrected marker/CLI/constraint-order minigate: **6 PASS**, 18 deselected,
  16.61 s. The initial permutation fixture rewrote native default expressions
  too; correction permutes only raw independent constraints. Product schema
  proof was not relaxed.
* Complete current proof/CLI regression on `e2296fe`: **24 PASS**, no skips or
  deselection, 85.12 s. Both complete native profiles, exact omissions, weakened
  guards/FKs/checks/indices, partial families, extras, false stamp, hidden marker
  objects, stale proofs, constraint-order permutation and the early command
  import boundary are verified. This supersedes the subset minigate for these
  functions.
* Real complete adoption/restore/rollback: **2 PASS**, 14 deselected, 44.37 s.
  Both profiles restore the encrypted complete archive portlessly before DDL,
  preserve original values/active sessions/keys/uploads/PDF chunks, satisfy the
  actual production schema checker under native `query_only`, and return to
  their exact original catalog/rows. Fresh profile also tests an approved empty
  version marker and its exact return.
* Real installation-fence/unmanaged-SQLite-writer refusal: **4 PASS**,
  14 deselected, 28.21 s. No archive is created and the original complete profile
  remains positively recognizable.
* Actual transactional abort, process-death and checked-return refusal on
  `e2296fe` composition: **12 PASS**, 6 deselected, 225.25 s. Two real child
  processes exit with `os._exit(23)` immediately after commit; durable receipts
  and exact native final values identify the committed state, and the checked
  return restores the original. Both profiles refuse later business writes,
  changed uploads, replaced snapshots and an identical replaced database file.
  The original data/file contents survive each refusal. Upgrade deadlines and
  child-process timeouts are independently 600 s in this synthetic gate.
* Ruff passes for package, tests, generator and isolated maintenance hook.
  Mypy passes for the package, generator and maintenance hook.

All 18 distinct synthetic service tests have passed across the explicitly
separated positive, concurrency and negative/crash gates; the changed return
identity checks are covered by the later crash/refusal gate. Root's final
composed legacy/full-recovery/startup/runner gate remains separate. These local results
are no claim that the entire A–L roadmap is complete. No private database has
been migrated and no scheduled service/task is registered.
