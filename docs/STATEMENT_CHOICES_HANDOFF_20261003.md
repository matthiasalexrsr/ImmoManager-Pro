# C: bounded StatementChoices backend contract

Own checkout `work/statement-choices`, branch `assist/statement-choices`, clean
base Root `f4c0622`. Before-code supplement `2c6e15f` follows approved Root
plan `cc1a787`. No draft/recovery/registry/root/schema/UI/CI edits. Native SQL
snapshot/authority work and signed reference cursor/search stay shared.

## Exact UI contract

Existing `GET /api/v1/workflow-references/statements`; response unchanged:
`{items, selected, has_more, next_cursor}`. Exactly one required context:

- Opening: `period_id=<actual immutable period>`.
- Correction: `dispute_case_id=<actual individual-statement case>`.

Existing `search`, `selected_id`, `cursor`, `page_size`, `portfolio_id`,
`property_id`, `unit_id`, `contract_id` remain supported. Both contexts together,
neither context, unknown fields, contexts on other kinds and protocol-only
`direction` on statements are 422. Inaccessible context is 404. Draft/review
period is 409. A property review case has no individual correction and is 422.

Items/selected always contain only `id`, `label`, `billing_period_id`,
`contract_id`, `unit_id`, `revision`, `snapshot_hash`, `status`. Optional
`party_binding="frozen_at_statement_finalization"` and `tenant_name` appear
only when the actual pure frozen party entry proves that concrete statement.
Neither field appears for legacy originals with no party proof. Never show
current Tenant.full_name as original. Labels use period label/revision and the
frozen name when present; legacy uses an explicit unit reference.

`selected` uses the same context, original eligibility, party, object and grant
rules as page items. Matching existing shared-reference semantics, pinned
selection is independent of search/cursor and may be outside the page. Cursor
binds exact actor/grants, complete query including selected and context, and
page budget. On context/search/budget/filter/selected/grant/principal change,
drop the old cursor; a mismatch is 422. Normal private no-store and publication
fences remain the existing route's contract.

A choice is minimal selection metadata. After selection read the exact existing
`GET /api/v1/billing/statements/<id>` and use its actual revision/hash for the
Domain preview. Choices never replace real original/hash validation, never
submit a command or claim that current metadata proves original bytes.

## Native eligibility and bounded behavior

Opening filters actual immutable statements of the authorised immutable period
with a real stored SHA-256 shape. Correction seeds the actual case original and
uses native recursive UNION DISTINCT over IDs. Each edge is the actual source
statement and source period, same contract/unit/property/dates, increasing
statement revision, immutable period/statement and matching period revision.
Frozen subject is the case tenant_id; absent legacy proof uses only its retained
contract binding and never an invented name. Original statement itself,
unrelated contracts/units/periods, drafted revisions and disconnected/cyclic
branches do not become selectable. Pure frozen source ID matches the actual
statement source ID.

All source/context/subject/object/search predicates run in SQL before bytewise
keyset order and LIMIT(page_size+1). Selected uses the same native query with
ID and LIMIT(1). Native page SQL projects minimal columns, schema and one
concrete party entry; the common Work resolver reads its own context period.
No whole-history SQL list or global RAM original scan; Memory iterates its
existing source map into a bounded heap and checks parents directly.

Existing `billing_disputes.work` owns authority, coherent native snapshots,
actual period/case scope and exit fences. Existing shared `_parents`,
UnicodeCasefold/literal search, cursor and CheckedPublicationRoute remain
unchanged. Two new query identifiers join the existing strict identifier
validators. The only shared service changes are the additional kind/fields,
context rejection and a small dispatch branch.

## Evidence and composition

Actual migrated production-route HTTP fixtures use real finalization and two
real correction revisions; all data synthetic. The correction test prohibits
`SQLAlchemyStore.list_utility_statements` class-wide and captures actual native
recursive DISTINCT/LIMIT SQL. Other cases prove filters before a one-item page,
pinned selection beyond page, current-name changes and frozen Unicode literal
search, cursor parameter/principal/grant mismatch, hidden context, strict
filters, invalid original hash shape, legacy names absent and independent
native source-cycle exclusion.

Product source/test commit: `7ed9100`, only new own ChoiceService (204 lines),
shared reference extension (14 lines) and focused tests (191 lines).

- Four actual Memory cases passed in focused runs. Early failures were only
  fixture argument duplication and retaining a generated pre-finalization
  model; both fixed using actual HTTP original read, then exact failed cases
  passed (opening 8.08 s, legacy/cycle 10.26 s).
- Four actual migrated SQLite HTTP cases: 4 PASS, no skips, 37.81 s.
- Shared SQLite/PostgreSQL CTE/Nullsafe-party/source/regexp/limit compilation
  green; this is static evidence, not native PostgreSQL acceptance.
- Ruff touched files and Mypy both source services green.
- Actual native PostgreSQL acceptance remains pending its coordinated slot.

Root and UI assistant were immediately informed after the clean contractcommit,
including exact query/response/selected/cursor and legacy/frozen metadata rules.
Root owns any central composition and private draft integration. No new
migration is needed; no backend release/full A–L claim is made here.
