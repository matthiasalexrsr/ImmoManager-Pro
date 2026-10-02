# G06 tenant disclosure and retained lifecycle evidence

This package extends G43 on Main `4e36b07` with lifecycle Types `1b30079`,
final Core `61e6c99`, and application hooks `cdde351`. The privacy product change
is `eebeccf`; the separate recovery test uses the actual application union.
No lifecycle Core, ordinary storage guard, recovery implementation, UI, Main,
preview, runtime configuration, or customer database is changed by this package.

## Disclosure and retention

The graph includes `contract_lifecycle_drafts` for accepted states, including
superseded history, and `contract_lifecycle_commands` for the corresponding
confirm/finalize receipts. Each record has a canonical `source_sha256` and
`scope.contract_lifecycle.source_sha256` covers the full lifecycle disclosure,
including the opaque private-work summary. Original command results remain
historical: a formerly pending confirmation retains that result after a later
accepted supersession. Current draft state and supersession links are separate.

Selection requires the exact currently authorized tenant, contract, property,
unit and portfolio graph. Shared typed validators check accepted evidence and
supersession relationships. An existence-only raw SQL guard detects hidden or
inconsistent bindings for this already authorized subject before reading JSON.
Historical review/result fields are validated rather than copying unexpected
foreign-subject JSON. Actor IDs remain audit identifiers; no unrelated user
profile is fetched or inferred from free text.

Open private work and earlier create/edit/review result payloads are excluded.
`scope.private_lifecycle_drafts` contains only a count, opaque revision digest,
and `contents_exported=false`. Its SQL projection reads ID/revision/updated-at,
not reason, actor, review or command JSON. All journal projections are limited
to the selected tenant graph and fetched in batches of 100; no installation-wide
JSON preload is used. Large completed JSON downloads continue to use the
existing private staged file and verify fresh authorization before publication.

Profile anonymization retains the accepted journal and private work. Its plan
hash includes the opaque private revision digest, so a changed private draft
invalidates a previously reviewed plan without exposing the author's contents.
The API adds `lifecycle_note` and explicit `retained_personal_evidence` entries.
The UI integration should display this note and readable labels for both new
collections. Retained reasons and historical snapshots still contain personal
data; this is a profile-only operation, not journal erasure or a legal compliance
claim.

For PostgreSQL anonymization, contract locks use NOWAIT after the existing tenant
lock. Native lock contention returns a recoverable `PrivacyConflict` and rolls
back before profile mutation, avoiding a tenant/contract lock inversion with
concurrent lifecycle creation. Memory snapshots compare declared lifecycle
columns, including both draft and command state, under the existing lock.

## Actual checks

Before hook integration, the complete focused disclosure/retention regression
suite passed 141 cases with 11 explicit skips in each Memory and SQL mode.
Ruff passes all changed sources/tests; Mypy passes the two privacy runtime sources.
After the actual application hooks were combined, the final shared suite passed
145 cases with 11 explicit skips in each Memory and SQL mode, Exit 0. This includes
the new source-gone disclosure test and the independent lifecycle recovery cases
for unchanged original journals, damaged evidence before family revocation, and
legacy-absent versus partial-table-pair handling. No privacy product correction
was needed after the hooks were integrated.

The additional source-gone case uses actual HTTP login, lifecycle creation,
review and confirmation, followed by an encrypted complete backup. It removes
only its resolved synthetic source directory, restores into a new destination,
loads recovered configuration before application imports, and logs in afresh.
It verifies old access rejection, unchanged original confirmation replays,
supersession history, exact record/aggregate/download hashes, opaque private
work, and profile anonymization with unchanged lifecycle receipts, the post-end
receivable, and bank/payment counts. The restored application is a real SQLite
installation even when the surrounding test gate selects Memory mode.

Four additional cases require a disposable PostgreSQL service. They create an
independent UUID schema through the real z1 migration, use native connections,
and test disclosure, retention, supersession and concurrent contract/profile
writers. They are registered in the application's PostgreSQL CI gate. Local
execution skips them explicitly because `TEST_SERVER_DATABASE_URL` is absent;
the SQLite tests are not presented as PostgreSQL proof.

## Owned files

- `services/tenant_lifecycle_graph.py`: bounded, exact-subject journal disclosure.
- `services/tenant_privacy.py`: graph/snapshot/retention and conflict integration.
- Three `test_tenant_lifecycle_privacy*` test files: Memory, SQLite, PostgreSQL
  and real encrypted complete recovery.

The Core migration and application hooks must be integrated alongside this
package. No duplicate migration, compatibility bypass, automatic cash movement,
automatic termination, or customer-data migration is introduced here.
