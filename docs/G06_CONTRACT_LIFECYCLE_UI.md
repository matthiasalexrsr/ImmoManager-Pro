# G06 Contract lifecycle UI handoff

Native completion base: `37dcc662c62bfee8f4544140a8507dd7720a7a5e`.

The nine started UI files were copied once from the stalled assistant's separate
`contract-lifecycle-ui` checkout. SHA256 before/after reading and in the copy
matched for every file; the receipt is local `artifacts/ui-input-snapshot.json`.
The original checkout has not been edited or subsequently synchronized.

Owned UI files:

- `frontend/src/components/ContractLifecycle.jsx`
- `frontend/src/components/ContractLifecycle.css`
- `frontend/src/pages/Contracts.jsx` (one additive row action/dialog hook only)
- `frontend/src/test/ContractLifecycle.test.jsx`
- `frontend/src/test/ContractsLifecycle.test.jsx`
- additive `contractLifecycle` namespaces in DE/EN/ES locale JSON.

No backend, auth, schema, preview or Main files are part of this UI package.

## API contract used

The component follows the native contract documented in the sibling
`contract-lifecycle` worktree:

- source: `GET /contracts/{id}` with a strong response ETag;
- own drafts: `GET .../lifecycle/drafts?limit=25&before=...`;
- immutable confirmed/finalized history:
  `GET .../lifecycle/history?limit=25&before=...`;
- create/edit/review/confirm/finalize use the documented lifecycle endpoints and
  command DTOs.

Every new write command first obtains the current source contract and its strong
ETag. Draft revision and review hash remain bound to the selected lifecycle
record.

An unknown/lost response is different: the UI retains the exact original
path/payload object, including its idempotency key, source ETag, draft revision
and review hash. The explicit retry button resends that exact command and does
not fetch/substitute a newer source ETag. HTTP 409/412 instead disables exact
retry and requires explicit reload/re-review.

## Privacy, grants and concurrency

The component is keyed by contract ID plus actor ID, role, write permissions and
portfolio grants. A principal/grant/contract change therefore remounts the
workflow and drops private draft/history/retry state. Active requests are
aborted on teardown; late responses cannot update the old component.

Writes use the existing `useWriteAccess('/contracts')` grant. A preparation
lock covers source refresh and confirmation prompts; the request lock covers the
actual command. Access is checked before preparing a write, after deliberate
confirmation and after the response before accepting a mutation result.

Returned DTOs are validated for contract/property/unit/tenant binding, actor
binding for private drafts, expected lifecycle state/data/review structure,
bounded review samples and review hash shape. A malformed or foreign success is
not shown as success and may only be retried with the exact stored command.

## Workflow semantics

Renewal requires a reason, new number and start date. A missing successor end is
sent as `null` only after the user deliberately checks the open-ended option.

Termination requires a reason and inclusive confirmed end date. Review displays
the source/proposed facts, rent-charge/receivable counts, due-after-end and
rent-period warnings and bounded samples. It states that existing financial
records remain unchanged and that no automatic notice/delivery/legal guarantee
is made.

Confirm requires both the UI review checkbox and the normal confirm dialog.
The checkbox is controlled by the exact draft ID, revision and review hash;
selection, editing, reloading and command results clear consent. Changed inputs
remain editable on conflict reload and must be saved/reviewed before confirming.
Strong source-ETag changes also require a new review. DTO/data comparisons use
field values, independent of Python/JSON property order.
Renewal results show the successor contract ID. A future termination remains
`pending_effective`; the history view offers a separate manual finalize action
only after reloading the current draft/source immediately before the command.
An authorized user may finalize another creator's accepted termination without
changing the recorded creator. A termination already completed during confirm
legitimately has no later `finalized_contract_etag`.

HTTP 5xx, network failure and malformed successful responses preserve an exact
command retry and freeze all other mutations. A known conflict requires reload;
401/403/404 discard protected draft/review data. Responses are additionally bound
to the exact command's target draft, operation, data and reviewed hash.

## Pending-termination correction / supersede

The UI already consumes these additive native fields when supplied:

- `superseded_by_draft_id`
- `supersedes_draft_id`
- history `current_state`

A reviewed correction displays the immutable `review.supersedes` ID, end date
and review-hash binding, even when the optional predecessor read is unavailable.
The native service selects that predecessor during review; the UI sends the
ordinary explicit confirm DTO, with no invented supersede input.

A superseded record shows the successor reference and has no finalize action.
History `result` stays unchanged; today's `current_state` and relationship
metadata are separate. After every successful command, including exact replay,
the UI reloads the current draft and shows history so an old pending result does
not reopen a superseded/completed action.

`finalized_contract_etag` is treated as nullable evidence of the later manual
finalization; the original `applied_contract_etag` is not replaced by the UI.

## Accessibility and responsive scope

The lifecycle dialog uses a modal focus boundary with forward/reverse focus
sentinels, Escape close while idle and opener-focus restoration. When a list
refresh replaced the original row action, restoration resolves the current
action by exact contract ID. Controls have a
44px minimum target. Reachable controls are recomputed dynamically, excluding
disabled fieldsets, hidden ancestors and negative tabindex. Busy preparation and
sending block duplicate submission and all dialog-close paths. The workflow's
overlay sits below the existing explicit confirmation dialog.
CSS is scoped to `.contract-lifecycle*` and collapses to
single-column layouts at 480px, with a full-height 360px treatment.

## Deliberately unchanged

The existing Contracts CRUD/CAS behavior remains in place. The known contracts
100-row/list error-swallowing/server-pagination backlog is not addressed here
and is not replaced with a frontend get-all workaround.

Native focused UI verification: 35 meaningful cases, including exact 500/502/503
retries, real API field ordering, dirty-input/review consent, conflict reload,
foreign-creator finalize, immutable supersession replay, nullable finalization
ETag, subject mismatch rejection, stale actor requests, server revocation,
StrictMode, duplicate submission, keyboard focus, readonly and DE/EN/ES.

Final complete Vitest: 864/864 in 69 files with two workers. ESLint passed with
no warnings; the production build passed. The additional refreshed-opener
regression failed before its narrow correction and passes on this final source.
Root owns the real SQL/Edge E2E file and runs it on the
combined backend/G43/recovery integration, including actual 320/360 geometry;
unit tests do not establish browser layout geometry.
