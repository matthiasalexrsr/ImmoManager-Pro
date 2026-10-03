# TEHA transactional mapping/import commands – handoff 2026-10-03

Worktree: `work/teha-receive-domain`, branch `assist/teha-receive-domain`.

This handoff belongs to the follow-up source package after:

- `8c85fb4` – DDL-free TEHA receive domain
- `2ce5e86` – L2 mapping/import-receipt persistence
- `3be51c7` – transactional mapping/import plan
- `8015fe5` / `45824f6` – receipt/mapping evidence tightening
- `503854a` – connection namespace bound into journaled TEHA reads

## Scope of this follow-up

The prepared transactional source now has local command implementations for:

- append-only mapping confirmation with History/source hash + opaque identity verification,
  mapping generation CAS and current local target/portfolio checks;
- local import preview with mapping generation and target revision binding;
- local PDF import into the existing Document + DocumentVersion original family;
- local technical-order import as an existing open Task plus immutable L2 receipt;
- replay/conflict checks bound to actor, idempotency key, source/content hashes,
  mapping generation and current local target state;
- download verification through the existing immutable DocumentVersion bytes.

No second queue, history, document store, finance booking or provider-write path was added.
Raw/unknown TEHA fields remain in the encrypted IntegrationHistory artifact only.
Relational L2 identity values remain limited to the allow-listed opaque identity components.

## Mandatory Root CommitAuthority boundary

The earlier addendum wording has been corrected.

Management serialization, `require_fresh_request_authority`, fresh user/role checks,
and a final SID/permission recheck are **supplemental fences only**. They are not called
a commit guarantee.

Every mapping/import write enters `_work(..., write=True)`. Before a Session bind,
writer acquisition or any DML, it requires the exact Root-owned contract:

- module: `backend.services.commit_authority`
- type: `CommitAuthority`
- validator: `validate_commit_authority(authority, actor_id)`
- valid result contract: validator returns `None`; denial raises its own typed error

The implementation accepts only that exact type and exact validator function. Bool,
lambda, duck-typed objects and a truthy validator return are rejected.

**Current HTTP write routes deliberately pass no authority.** Therefore until Root
implements and injects the actual CommitAuthority, these operations fail with HTTP 503
before DB/session/writer/DML:

- `PUT /integrations/teha/mappings/{kind}/{external_key}`
- `POST /integrations/teha/imports/document`
- `POST /integrations/teha/imports/technical-order`

Read-only source/preview functionality does not require commit authority.

The authority is checked a second time immediately before the outer commit after the
fresh scope/user/request-authority checks. That second validation supplements rather
than replaces the first pre-DML gate.

## Journal/source namespace

`JournaledTehaReader` now requires a stable opaque `connection_key`; accepted
history artifacts include it. `history_exchange(..., expected_connection_key=...)`
fails closed when source/content evidence belongs to another encrypted connection
namespace. This prevents same-looking provider IDs from being mixed across separate
TEHA connections.

## Router contract

`backend/routers/teha.py` adds the local endpoints listed above plus:

- `POST /integrations/teha/imports/preview`
- `GET /integrations/teha/imports/{receipt_id}/document`

The router continues using `WorkflowAuthorityRoute` and the installation-admin
boundary. It performs no provider write. Document upload bytes are bounded by the
existing `max_upload_size_bytes`.

## Source-only gates run in this finalization round

Per Root instruction, no application server, DB, PostgreSQL, browser or portal process
was started in this round.

Executed pure/static gates only:

1. `pytest backend/tests/test_teha_transaction_boundaries_pure.py -q -rs --tb=short`
   -> **7 passed**.

   Includes the new proof that a write `_work` without Root CommitAuthority returns
   HTTP 503 before `store.db.get_bind()`, before the request-authority fallback and
   before the write body can execute.

2. Connection-namespace source checks:
   - Ruff on `teha_journal_reader.py` + its prepared tests: **passed**.
   - Mypy `teha_journal_reader.py`: **no issues**.
   - `py_compile`: **passed**.
   - `git diff --check`: **passed**.

3. Transactional source checks:
   - Ruff on command/router/pure/prepared transactional test files: **passed**.
   - Mypy on `teha_receive_commands.py` and `routers/teha.py`: **no issues**.
   - `py_compile`: **passed**.
   - `git diff --check`: **passed**.

The prepared DB/atomicity suite `backend/tests/test_teha_transactional_commands.py`
is committed as reviewable test source but was **not executed in this round** because
Root explicitly requested no App/DB/PG processes. Root owns the independent composed
runtime/DB/PG acceptance.

## Exact remaining Root integration

1. Provide the real typed `backend.services.commit_authority` contract and inject a
   valid authority into the three write commands. Until then writes remain intentionally
   unavailable with 503.
2. Keep Root's existing central registration/recovery/startup/settings/connection-store
   ownership for the L2 family; this package does not duplicate those files.
3. If resumable OperationalJobs integration is desired, add only the previously proposed
   `teha_receive` family adapter (`upper/discover/apply`) in the shared job core after
   central review. No shared job-core edit is present here.
4. Run the committed transactional DB suite on the fully composed Root source, including
   the actual CommitAuthority implementation. PostgreSQL/browser/portal gates were not
   claimed here.
5. Provider writes remain a separate future acceptance package requiring real external
   result evidence; no automatic email, provider mutation or blind replay is present.

No Root/Main/Preview files, live provider credentials, private portal values or real
tenant/provider data were used in this finalization.
