# Complete global search

The current search scans every entity list, stops after ten matches per kind,
and silently converts optional-domain failures to missing results. Contact and
lead fields also do not match their actual models.

Implement a bounded, scope-bound keyword page in a dedicated read service.
Stable order is existing entity priority then bytewise identifier descending;
signed cursors bind query, page size, user, role and current portfolio grants.
Query actual database projections with a limit and scoped clauses; Memory uses
a bounded heap. No stock-level cap, no catch-and-empty on broken sources.
Shared Unicode casefold and literal LIKE escaping keep stores consistent.
Fields use the actual address_line, full_name and contact component names.

Keep the legacy response's query/count/results/semantic keys. Cursor pages add
has_more/next_after; keyword pages are the complete navigable source. Optional
semantic suggestions are a separate explicitly bounded recommendation mode,
not a substitute for complete pages. Existing legacy semantic scope checks stay
valid during migration.

The search control must expose next/previous pages, immediately clear stale
actor/scope/query data, preserve a failed page for retry, and keep keyboard
navigation consistent with rendered options. UI/API tests include >10,000
matches, actual Unicode/literal wildcards, current grant revocation, cursor
tampering and injected source failures. No new database migration is needed.
