# Saved owner share UI and final combined verification

Follows 7d2c28f on assist/settlements-ui-e2e, isolated work/statements-review.
Root owns integration/publication. No backend, roles, auth, FormModal, Monthly
function, dependencies, recovery code, runner or Playwright configuration changes.

BillingOwnerShare loads the saved period through GET /billing/periods/{id} and
refetches after generation changes the statement IDs. It separately displays
owner total, recoverable vacancy costs, non-recoverable costs, full property
costs, tenant-allocated costs, vacant unit days and owner line items. It offers
no mutation or payment control and explicitly excludes these amounts from tenant
receivables/credits. Null means not calculated, not zero. Failed/inconsistent GETs
show a recoverable error. Totals/line items are checked for cent-level conservation;
the UI does not calculate allocation or modify the backend result.

17 new labels per de-DE/en-US/es-ES, confined to pages.statements.ownerShare.
25 additional tests cover rendering in all locales, schema validation, cancellation,
read retry and the real Statements integration GET following successful generation.

The original seeded draft browser fixture is unchanged. Its old assertion assigned
all600 EUR to tenants; the new contract requires the persisted tenant cost total
plus owner share to equal property600. Only this assertion was updated, not the
units/contracts/costs or allocation assumptions. Native vacancy cases remain with
the backend agent. All5 receipt/revision browser cases also assert the owner panel.

## Final result
Verified in separate work/ui-billing-verification on committed Root c77fbc7,
including billing848281e4, session lifecycle28986ba and private-files ed8a0da.
Normal real-browser suite:9/9 passed (2.9 minutes test-suite duration).
Combined frontend suite:270/270 passed; own source-base suite:235/235 passed.
ESLint, production build and git diff --check passed. No timeout or pool limits
were raised. Backend and discovery configuration have no local QA diff.
Mobile390px screenshots were inspected; the page remains within the viewport.
Downloaded PDF revision3 was independently rendered and visually checked.

Evidence: work/ui-settlements-evidence/owner-final-e2e.log,
owner-final-combined-units.json, owner-final-combined-lint.log and frozen-final-results/.
Earlier red runs are retained separately: the missing receipt accounting, form
reset, expired draft expectation and pre-fix connection pool exhaustion were not
hidden. The final evidence uses the actual committed fixes and full normal suite.
