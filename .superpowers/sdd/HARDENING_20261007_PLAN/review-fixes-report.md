# Review fixes — 7 October 2026

Addressed the two P2 findings and the smaller task recovery issue in
`review-report.md`. Production changes are limited to `Contracts.jsx`,
`Tasks.jsx`, and integration `validation.py`; no migrations or live preview
data were changed.

- Contracts now uses the established `tenants_all` cache and invalidates that
  same key after contract mutations. The new navigation regression uses the
  real DataStoreProvider, Tenants, Contracts, DataTable, and FormModal. It fixes
  the cache clock inside the TTL, performs each tenant mutation through the
  tenant form/action, and returns to Contracts. Creation updates options,
  renaming updates labels, and archiving removes the new-contract option while
  retaining the historical contract's named party and archived edit option.
- Empty strings count as absent only for string fields. Boolean, integer,
  number, object, and array fields now report the incorrect type. Regressions
  cover rejected saves without persisted/live changes, malformed loaded
  configuration blocking SMTP execution and configured status, and optional
  object/required array action validation before provider invocation. Optional
  text clearing, explicit null removal/default restoration, and masked SMTP
  secret roundtrips remain supported.
- A task quick-action 409 now exposes an explicit “Aufgaben neu laden” control.
  A successful read clears that conflict without resubmitting the write. List
  refresh leaves modal state untouched. Stateful API regressions show a later
  deliberate retry uses the fetched revision, and a form opened while the
  rejected request was pending keeps both its draft and original revision.

## Verification

Before production edits, the new tests reproduced five frontend failures
(create/rename/archive cache staleness and two missing conflict refresh paths)
and ten backend failures (eight config-save/load cases and two action-schema
cases). The optional text/null/secret compatibility case already passed.

Final targeted checks:

- `npm test -- src/test/ContractsTenantCache.test.jsx src/test/TaskContractHardening.test.jsx src/test/FormModal.test.jsx --reporter=dot`:
  **21 passed** across three files.
- `python -m pytest backend/tests/test_integrations_hardening.py backend/tests/test_integrations_api_hardening.py backend/tests/test_integration_manager.py backend/tests/test_integration_providers.py backend/tests/test_integrations_router.py -q`:
  **59 passed**, one existing Starlette/httpx deprecation warning.
- `npx eslint src/pages/Tasks.jsx src/pages/Contracts.jsx src/test/ContractsTenantCache.test.jsx src/test/TaskContractHardening.test.jsx`:
  **exit 0**, no diagnostics.
- `git diff --check`: **exit 0**; Git emits only local LF/CRLF conversion notices.

Python used the shared verification Python 3.12 environment, with a new
`%TEMP%/wi-review-fixes-*` directory per command for DATA_DIR, DATABASE_URL,
INTEGRATION_STATE_FILE, and pytest cache. SMTP was synthetic; no connections or
messages left the process. Frontend API responses were synthetic. Full suite,
build, independent review, and native browser verification belong to the parent
integrator after the remaining parallel packages land.
