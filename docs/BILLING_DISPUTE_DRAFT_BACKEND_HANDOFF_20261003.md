# C: actual encrypted dispute drafts and original replay

Root source after `e2a29de`, 2026-10-03. Pre-code contract was committed in
`cc1a787`; shared pending/error-status correction is `d40ea9c`. Native UI's
read-only contract review found no substantive envelope mismatch.

## Product contract

The actual `/api/v1/auth/users/me/form-drafts` endpoint accepts an explicit
special policy, collection `billing/disputes`, entity_id null, form_key
`open:<period-id>` / `event:<case-id>`. Four strict scalar strings in both
values and original_values: period_id, case_id, command_json, review_json.
No generic journal CRUD permission, second draft table, sidecar or localStorage.

The common core still owns authenticated encryption, actual principal/grant
hash, expiring lifetime, byte budget and tab CAS. No new schema/migration.
Its new special branch bypasses generic entity-create reference checks because
a saved command draft does not create a journal case. Explicit validation in
`billing_dispute_drafts.py` checks current authorised period/case, form binding,
actual immutable statement/original hash, original position indices, event
target, genuine correction lineage and actual immutable document manifests.
Unknown command keys, duplicate JSON keys, nonfinite JSON, unsupported field
types and forged review/binding are rejected with a fixed draft error.

Editing supports unselected originals and blank reasons/dates. The real
OpenDispute default expected_case_revision=0 is accepted without rewriting
the input JSON. Reviewed/pending envelopes require a complete real command
and exactly matching actual preview, including immutable original identity,
request, manifests and streamed file bytes. Both envelope snapshots are
independently checked; a permissible current selection cannot smuggle an old
foreign reference in original_values.

An append review's original head is reconstructed from the real, streamed
event chain up to its saved expected revision. Existing native preview hashing
and date/JSON encoding are reused. A later real successful event/state change
therefore does not erase or rebase a lost-response command. UUID, expected
revision, original JSON strings and review survive unchanged. Actual Domain
receipt replay resolves the outcome. Draft validation calls only read helpers;
it never invokes open_case/append_event or changes accounting/delivery state.

Owner-bound CAS discard remains the common core path and does not decrypt old
scope-bound data. The executed scope test proves discard after portfolio
replacement while the account retains a write role and another portfolio.
The extra case of complete grant removal/readonly discard is not proved by
this source packet and is recorded for a separate focused core correction.

Follow-up: `PRIVATE_DRAFT_OWNER_EXPIRY_ACCEPTANCE_20261003.md` records the
separate actually executed complete grant/readonly discard and deferred pending
expiry correction. The preceding five-family results belong to the original
special-policy source, not a retroactive claim of those new cases.

## Actual executed gates

`backend/tests/test_billing_dispute_drafts.py`, each profile selected separately:

- Memory: **5 passed**, 28.94 s; 10 other profile nodes deselected.
- Migrated SQLite: **5 passed**, 45.14 s; 10 other profile nodes deselected.
- Real PostgreSQL: **5 passed**, 56.54 s; 10 other profile nodes deselected,
  no skips. Explicit dedicated TEST_SERVER_DATABASE_URL and owned UUID schemas.

Five families per actual profile: unfinished encrypted autosave without case
creation; actual archived evidence and exact pending open/append replay after
real committed success/state change; tab CAS plus changed grants/owner discard;
unknown/duplicate/forged/original-reference/other-party evidence negatives;
actual event identity and genuine later correction lineage even before review.

SQLite/PostgreSQL use the actual Alembic chain through k2, production router
graph, authenticated JWTs, request-session/scope middleware and real repository.
No fake draft/preview/receipt endpoint, private data or provider connection.
Both native runs use the same frozen source. Logs are outside the repository:
`work/root-dispute-drafts-sqlite.log`, `work/root-dispute-drafts-postgres.log`.

Common ordinary draft regression: three selected existing tests, each
Memory/SQL, **6 passed**, 18.72 s, no skips. Existing incomplete values,
old business revision and denied generic statement editor still behave correctly.
Ruff: new special service/common service/test file passed. Mypy: both product
service files passed. Initial Memory gate found omission of the real zero
revision default and a test attempting a new write without the current tab CAS;
the source default and test CAS were corrected before the final five-profile
gates. No integrity rule was weakened and no mocked success replaced a failure.

## Outstanding composition

Native UI/Statements entry wiring and real Browser acceptance follow this
backend proof. Whole-product A-L release, private installation upgrade,
large-history performance, external TEHA/WISO validation and full release
requalification remain outstanding. The running Release126 was not replaced.
