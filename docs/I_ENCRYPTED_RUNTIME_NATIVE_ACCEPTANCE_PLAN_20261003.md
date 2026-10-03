# I: genuine HTTP and recovered runtime composition — before-code plan

2026-10-03, Root product source `d019cb1`. Keep pure construction, cold CLI,
actual authenticated app and full recovered runtime evidence distinct. Use
only owned temporary SQLite installations and synthetic secrets. No preview
upgrade, real mail, portal contact, provider action or private conversion.

1. Reuse the actual `access_http[sql]` fixture with real SQL user/session stores,
   registered owner/member, normal app/middleware and actual HTTP login. Bind
   only its test-local integration manager to the configured encrypted factory
   and explicitly initialized temporary state. Preserve original unknown fields
   and masked passwords across a genuine revision-bearing PATCH. A stale second
   PATCH must return safe private/no-store 412 and leave exact ciphertext
   unchanged. Selected member reads/writes remain 403 through normal rights.
   Removing the owned state before GET/PATCH/run must yield safe 503, no new
   state and no journal/provider action. Only the provider method is replaced
   with a tripwire that fails if reached; no fake authentication or response.
   Select one SQL case, outer deadline 150 seconds.

2. Extend only the existing explicitly encrypted full-roundtrip case. Its
   legacy source fixture remains legacy for all other cases. The owned source
   is explicitly encrypted by its existing helper; create an actual full archive
   and restore into a new directory. Reopen using configured_runtime_store with
   the exact archived/rebased values, retaining unknown content, bytes and keys
   while confirming rotated JWT signing. Then run a fresh actual app/login
   child using load_recovered_environment, normal user rights and the global
   factory. Check masked actual connection-state API plus secret-dependent
   manager decrypt and existing receivable/bank/upload evidence. Do not initialize
   or overwrite restored ciphertext. Preserve wrong ambient configuration probe
   to establish archived values are used. Child 30 seconds, existing seed child
   90 seconds, total outer gate 210 seconds; no persistent server subprocess.

Use one exclusive native slot; close actual TestClients, SQL sessions and child
processes. Record actual duration/failure and commit a focused correction only
if evidence requires it. No broadened unrelated test repetition or whole-product
acceptance is implied by these two cases.

## Owned PostgreSQL follow-up

Read-only inventory found the original synthetic vendor16.15 runtime under
`C:/Users/matth/Documents/Codex/2026-10-01/wi/work/postgres-test-1615-20261002`.
The cluster has PG_VERSION16 and task-owned extraction evidence. Historical
postmaster39344/1676 no longer exist. Do not remove its stale PID file by hand.
Start only the actual vendor postmaster with explicit owned `-D cluster`,
`-h 127.0.0.1 -p 58112`; no default5432 start or Windows service change. PostgreSQL
handles its own stale state. Retain the owning process/session identity and
stop it through its own pg_ctl after the one previously infra-blocked unchanged
notification keyset case. That case owns/drops only a UUID schema in synthetic
immo_ci, leaving public and other installations untouched. Its Python gate is
bounded to 90 seconds; service startup/shutdown are separate lifecycle evidence.

The first actual SQL-auth HTTP gate on `49ce533` failed in 10.23 seconds
(13.12 outer): real login, masked GET, CAS success and native stale412 succeeded,
but the actual app's global HTTPException handler stringified our structured
detail into an INTERNAL_ERROR message. No genuine safe structured code had
reached the client. Correct only IntegrationPublicationRoute's ConfigStoreError
boundary to return the existing structured `error` envelope directly, with the
fixed actionable message/request ID and private/no-store headers. Retain the
fixed `detail` object as the explicit compatibility path for older /api/v1
consumers and isolated-router tests. Do not change unrelated global exception
semantics or weaken the genuine HTTP test. Repeat exactly this one SQL case.
