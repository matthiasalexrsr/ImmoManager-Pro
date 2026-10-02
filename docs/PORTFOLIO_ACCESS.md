# Portfolio access

Roles grant actions; portfolio assignments independently delimit business data.
An owner can give an account `all` access or `selected` access with an explicit
list of portfolio IDs. A new HTTP-created account defaults to `selected` with
an empty list. Owners always have all access so setup and recovery remain usable.
The additive `o1a2b3c4d5e6` migration follows `n1a2b3c4d5e6` and records existing
accounts as `all / legacy_all`; it does not silently revoke historical access.

Authenticated requests read the active account and assignments from the server,
not from JWT claims. The same old token therefore observes changed assignments
on its next request. Lists, counts, direct IDs and native ORM financial sessions
use the same SQL predicates. Writes check all foreign and polymorphic references.
Memory collections implement the same boundary. An inaccessible ID is absent,
and a proposed cross-portfolio reference is rejected. A tenant linked to several
portfolios can be read through an accessible contract, but modifying its shared
profile requires access to every linked portfolio.

Existing unlinked business records are installation data. A selected account's
new unlinked records receive explicit resource bindings in the insertion
transaction. Private uploads are bound as drafts; once attached, their current
document/photo/reading determines access, including OCR sidecars. A cached
semantic search hit is checked against the current boundary before returning it.

Installation administration, complete import/export, privacy exports, plugins,
integrations, diagnostics, logs, updates and operational batch/schedule journals
require all access. Selected accounts retain ordinary scoped task/calendar CRUD;
the existing operational journal format has no per-portfolio snapshot. This is
an explicit denial, not a partially filtered journal presented as complete.
Global tax rates, notification templates and escalation rule definitions are
readable, while changing these installation definitions requires all access.

## Installation integration

Register `PortfolioScopeMiddleware` from `backend.services.portfolio_http` after
`RBACWriteGuardMiddleware` and before `ConcurrencyMiddleware` in `app.py`.
The outer `DBSessionMiddleware` still owns request session cleanup. Within the
startup schema transaction, after users/business tables exist, call
`ensure_portfolio_access_schema(connection, bootstrap_legacy=False)` from
`backend.services.portfolio_scope`. This additive create_all compatibility hook
records legacy accounts only when explicitly passed `bootstrap_legacy=True`
after detecting the previously absent access table before create_all. Ordinary
startup preserves missing access rows as restricted. A missing
access row created after startup fails closed as unassigned.

The account API adds `portfolio_access`, `portfolio_ids` and the read-only
`portfolio_access_origin`. PATCH supplies mode and IDs together. Only owners can
create accounts or modify assignments. Existing manager contact/activation
permissions remain available with all access. Assignments use indexed FK tables;
user listing loads users/access/grants in three queries rather than per-account
queries. Full database backups include all four new tables.

## Explicit SQL connections and streams

`current_scope()` captures the immutable request `AccessScope`; internal setup,
installation workers and backups use `None`. `scoped_clause(ModelOrTable,
scope=captured)` returns a SQL predicate or `None` for internal/all access.
Session ORM reads and simple Core joins receive predicates automatically.
Independent engine connections and custom nested Core selects must explicitly
apply the predicate; they are not database row-level security.

Use `scope_context(captured)` around memory/ORM stream work and call
`refresh_scope(captured)` before each output chunk and before publishing a
completed export. Any role, activation or assignment change raises 403; the
stream terminates instead of reporting a partial export as complete. Booking
query/lookup/legacy/export, DATEV and persisted rent-batch integrations must use
this explicit contract in their owned source files before release acceptance.

A downgrade refuses before any DDL if restricted accounts, user grants, resource
bindings or upload bindings exist. Restoring a verified complete backup remains
the supported way to recover an earlier application without widening access.
