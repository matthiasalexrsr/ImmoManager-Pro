# G06 application integration

This package connects the reviewed lifecycle Core to ordinary domain writes and
complete recovery. It is based on Main `4e36b07`, Core prerequisite `1b30079`,
final Core `61e6c99`, independent integration probes `f4f7cfb`, and final
G43 prerequisite `eebeccf`.
The Core sources, migration `z1` (after `y1`), UI, and G43 privacy sources are
unchanged. G43 has a separate owner and must be combined before a privacy release.

## Behavior

The production router graph authenticates the lifecycle routes before ordinary
contract routes. Runtime startup and Alembic register both journal models.
Startup refuses a partial pair before `create_all` could silently repair it.
Memory declares both journals as cloned store state.

Ordinary contract PATCH now follows the validated Memory update path, preserving
original business CAS, references, dates, occupancy and payment guards. SQL
hooks run before old-value equality and acquire the same property → unit →
contract locks as reviewed confirmation, revalidating discovered parents after
waiting. Ancestor reparenting and subject deletion retain private and accepted
journals; names and other permissible metadata remain editable.

Direct monthly-charge creation and contract/month edits share the parent lock
and the known monthly service-period guard. The inclusive final month remains
valid. Receivable due dates after termination remain valid and editable. This
package creates no cash movement, payment, deposit refund or write-off.
Existing ordinary validation remains HTTP 400 with actionable text; lifecycle
command conflicts and business CAS retain their own 409/412 semantics.

Reset and partial business JSON imports reject retained lifecycle history before
preparation/DML, then recheck under the atomic maintenance barrier, including
additive merge. PostgreSQL's rare reset barrier locks parent tables before
journals; SQLite uses its native writer transaction. The Memory generation lock
aliases the shared payment RLock, avoiding an inverse pair of generation/payment
locks and serializing direct charge creation with confirmation.

Both lifecycle tables absent remains a compatible pre-z1 recovery archive;
exactly one missing refuses publication. Full backup/reference scan and offline
security validation call the pure journal verifier before session revocation.
The complete archive preserves original draft and command evidence. CLI recovery
already delegates to these shared paths and requires no duplicate CLI hook.

## Actual acceptance

The independent probes first demonstrated seven failures without these hooks.
The final focused Memory run passed 109 cases with 16 explicit skips, including
the actual SQLite variants and the additional import/reset publication barriers.
The integrated SQL regression gate passed 306 cases with 16 explicit skips,
covering lifecycle Core/probes, complete HTTP middleware, CAS, payments, bank
receipts, partial restores, monthly rent and UI/API contracts. Additional real
Memory/SQLite import checks passed 4/4: a journal published after the first cheap
check stops both merge and replacement before their apply function.

The native SQLite reset race pauses a real journal writer while reset's first
read cannot see its uncommitted draft. Reset waits for the writer, then refuses
without INSERT/UPDATE/DELETE in the reset session. Native direct-month/confirm
races produce one permitted outcome and one refusal, with no cash side effects.
Complete synthetic source-gone recovery preserves exact journal rows, final
contract end/status and obligation counts, while revoking the existing login
family. A damaged copied journal refuses both file scan and security completion
without revoking that family's session. Half-pair and legacy-absent recovery
behavior are covered separately.

The later complete application union exposed an additional authentication-store
ordering defect: a SQL user store wrote the setup marker before the lifecycle
reset barrier. Reset now obtains its serialization barrier and rechecks all
retained evidence before any form-draft/auth-marker DML. PostgreSQL takes a
read-only `auth_setup` table lock first to preserve the auth-before-parent lock
order. The actual refusal test is independently parametrized with Memory and
SQL user stores and still requires zero reset DML. Both complete targeted
Memory/SQL gates passed 240 cases with 15 explicit skips; Root's additional
shared SQL reset/restore/privacy/draft gate passed 128 with 9 explicit skips.
This correction supersedes the earlier gate's narrower auth-store coverage.

The dedicated PostgreSQL files are registered in CI and require a disposable
`TEST_SERVER_DATABASE_URL`. They upgrade an independent UUID schema through z1
and cover real concurrent writers, reset-vs-new-draft locking, preserved reset
subjects and offline journal refusal before security mutation. Local execution
explicitly skips them because no PostgreSQL service is configured; SQLite is not
presented as PostgreSQL proof. Ruff passes changed sources/tests; Mypy passes
18 runtime sources including the complete unchanged Core, plus the two final
G43 privacy runtime sources. CI includes those privacy PostgreSQL cases too.

## Owned changes

- `db/session.py`, `db/migrations/env.py`, `routing.py`: registration/preflight.
- `storage.py`, `repositories/base.py`, `repositories/finance_repo.py`,
  `repositories/sql_store.py`, `services/payment_integrity.py`,
  `services/rent_ledger.py`, `routers/rent_charges.py`: ordinary-write hooks.
- `services/data_transfer.py`, `services/full_recovery.py`,
  `services/recovery_validation.py`, `services/recovery_sessions.py`: preservation.
- Three added integration test files, CI PG/type registrations and this handoff.

No Main, preview, user database, legacy fixture schema or customer row was
modified. All source removal/corruption cases operate on owned synthetic test
fixtures or their copies.
