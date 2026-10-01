# RentCharges translations and receipt-managed Receivables

Base: 4766fb582c3e45268783ab35793bd87535b38a57.
Isolated branch: assist/finance-controls-i18n; worktree: work/statements-review.
Root alone integrates/publishes; no main-worktree changes or backend writes.

## Changes
RentCharges: table heading, create/edit titles, eight column captions and five
form captions translated in de-DE/en-US/es-ES. Existing monthly generator source,
request parameters, callbacks, date defaults and receipt-backed edit values are
unchanged. No changes to RentGenerationModal or its five existing tests.
Receivables: readonly users see balances and a rent-overview link but no create,
edit or delete actions. Downgrading access closes the editor and cancels a pending
confirmed delete. Status and amount_paid are not editable form fields. New claims
start open; edits explicitly preserve the existing status and statement_id, while
only contract, amount, due date and description are accepted from form values.
Payments/reversals are directed to the receipt-based rent overview, not fabricated
by status changes. Backend validation remains authoritative for financial edits.

## Verification
16 new tests; 14 reproduced defects on the base and 2 already passed.
Final entire frontend suite: 159/159 passed. ESLint and production build passed;
git diff --check passed. No backend, auth provider, shared FormModal, API client,
Monthly component, dependency, import/recovery or CI changes.
Tests use actual I18nProvider/FormModal in all three locales, preserve existing
paid/partial/overdue/cancelled/open statuses, and cover error retention and readonly.
New namespace leaves: pages.rentCharges (16), pages.receivables (3), per locale.
Evidence: work/ui-controls-evidence/{baseline,tests}.json, lint.log, build.log.
