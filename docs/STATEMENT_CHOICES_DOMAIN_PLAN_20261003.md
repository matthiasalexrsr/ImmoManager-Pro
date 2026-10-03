# C: bounded original statement choices — Domain supplement

Before code, 03.10.2026, clean own checkout `assist/statement-choices` from
Root `f4c0622`. The approved Root plan `cc1a787` and actual reference query,
cursor, publication fence, dispute Work scope and frozen original contract
have been read. Only a new choice service, small shared reference extension,
focused tests and handoff are owned here; no draft/recovery/schema/UI changes.

## Actual reuse and query boundary

The existing route already uses `CheckedPublicationRoute`, no-store headers,
strict Pydantic query, a signed principal/grants/full-query/page-budget cursor,
Unicode literal casefold and bytewise descending ID. Add statements to its
kind and period_id/dispute_case_id to its query; reject either new context on
other kinds and require exactly one context for statements. Existing direction
remains protocol-only. Keep parent validation and page response unchanged.

Dispatch only the statements branch through existing `billing_disputes.work`
(read mode), which performs actual authority, scope, coherent SQL snapshots,
case/period access and exit checks. Reuse existing `_parents`, cursor and
publication fences; do not invent a second authority or cursor engine.

Opening selects immutable statements of the actual authorised immutable
period, with a stored valid original SHA-256. The choice remains metadata;
it does not replace actual original GET or exact Domain preview/hash checks.

Correction seeds the actual case statement. Use a native recursive distinct
CTE over IDs. Each traversed edge preserves contract/unit, immutable actual
statement and period, property/dates, increasing statement/period revision and
matching period source. Every node has the case's belegte original tenant when
frozen; absent legacy family uses its existing contract binding, never a new
original name. Strict revision edges and distinct recursion terminate cycles.
Only genuine descendants, excluding the original, reach the page query.
All context, party, parent and search predicates precede LIMIT/keyset paging.

SQL projects only minimal statement fields, actual period label, schema and
one concrete JSON party entry. Never select whole periods' personal families
or materialize global SQL history. Parse optional names only with the pure
frozen entry model/binding checker; no Tenant.full_name join. Selected ID uses
identical context/lineage/parents eligibility, independent of search and cursor,
matching existing pinned-choice behavior. Memory scans its existing source
mapping into a bounded heap, checking source chains directly without building
a second full history or result list.

## Acceptance and boundaries

Actual HTTP finalization and correction fixtures; filtered low-ID choices beyond
a first page, exact selected eligibility, cursor actor/query/grant changes,
inaccessible context, unknown/new filters, immutable/hash rejection, same frozen
party after a native current-contract rebind, legacy names absent, cycles and
foreign source branches. Capture actual SQL to verify recursive distinct query,
WHERE filters and LIMIT rather than a global statement list. Use current real
migration chain for SQLite/PostgreSQL after coordinated heavy slot release;
initial source/static and small Memory cases only. All fixtures synthetic.
