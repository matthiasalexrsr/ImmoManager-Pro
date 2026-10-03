# C: bounded original choices and private reviewed command drafts

Plan before code, Root `8a904f3`, 2026-10-03. The native UI assistant's
`3310dba` plan has been read, alongside actual journal routes, request types,
the shared reference cursor, encrypted form-draft service and reference UI.
Root owns these shared backend contracts. The UI assistant owns its feature
components and a separately reviewable Statements entry point.

## Original choices

Extend the existing `/api/v1/workflow-references/statements` contract, keeping
its `{items, selected, has_more, next_cursor}` response. Its query adds
`period_id` and `dispute_case_id`; exactly one selects opening or correction
choices. Existing search, selected_id, cursor, page_size and object filters
remain valid. Reject these new filters for unrelated reference kinds.

Opening selects actually finalised immutable statements in the authorised
period, with a real original hash. Correction selects finalised descendants of
the case's original statement with the same authorised party and genuine source
chain. SQL uses a recursive distinct lineage query and bounded keyset pages;
Memory uses the same eligibility semantics and a bounded selection heap.
Do not load the whole SQL history to filter a visible page.

Minimal items contain id, label, billing_period_id, contract_id, unit_id,
revision, snapshot_hash and status. Never take an original name from today's
tenant master data. Optional frozen party metadata is included only when the
Domain original contract actually proves it. A choice is selection metadata;
the exact existing statement read and Domain preview prove the actual original.

Selected records receive the same object, period, lineage and grant checks as
the page. Cursor signatures bind principal, grants, complete filters and page
budget. Fast context changes and revoked access cannot publish an old page.
The normal reference component needs no new endpoint convention.

## Private drafts

Add an explicit special policy for collection `billing/disputes`, separate from
ordinary entity-create editors. Use entity_id null and form_key
`open:<period-id>` or `event:<case-id>`. Values and original_values are limited
to scalar strings period_id, case_id, command_json, review_json. Empty
uncompleted editing values remain possible; arbitrary nested private sources,
credentials, unknown command fields and executable payloads are rejected.

The existing encryption, owner identity, grant hash, CAS revision, expiry,
configured byte budget and submission_pending protection remain authoritative.
Draft actions only save/read/discard a user's draft; they never open a case,
append an event, publish a document or update an accounting status.

On every write and restore, verify actual period/case scope, matching form_key,
statement relationship, correction lineage, existing target event and chosen
immutable original version references. Inspect both current and original draft
values. The full command and review are JSON strings so original position
indices and prepared request objects survive without a competing draft store.

A submitted draft requires a complete real command with preview_hash and
matching reviewed request. Fresh access checks must not silently rebase an
old expected revision or replace its idempotency key. A lost success response
may already have changed the case revision: authorised exact replay remains
restorable, and Domain receipt verification resolves it. Known stale state
retains the input and requires an explicit new review. Scope changes deny
private restoration; owner-bound explicit discard remains possible through the
existing policy. Successful submission and failed draft cleanup are separate
states and cannot trigger another business write.

## Focused acceptance

Use the actual migrated SQLite/PostgreSQL chain and production HTTP middleware.
Prove filters before pagination, selected records after the visible page,
cursor/filter/grant mismatch, inaccessible periods/cases, genuine correction
lineage, cycles and unknown fields. Prove encrypted draft storage, unfinished
editing, actual original attachments, independent tab CAS, grant revocation,
stale business revision and exact prepared replay after a real committed case.
The existing general editor contract and protected draft history must continue
to work. Heavy tests and browser acceptance are coordinated with the other
agents. No private source data or credentials are used as fixtures.

The future frozen-party Domain packet must be composed with these paths once
its clean source and actual native gates are delivered. This plan does not
approve an A-L release, deployment, external write or untested recovery path.
