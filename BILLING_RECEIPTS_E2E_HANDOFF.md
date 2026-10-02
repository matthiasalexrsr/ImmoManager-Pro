# Billing regression follow-up

Branch: assist/settlements-ui-e2e. Parent: aa5f617, integrated by Root as b19ac84.
No main integration or publication. Backend, authentication, schema, dependencies
and Playwright configuration are unchanged by this patch.

The synthetic browser fixture uses the existing runner's temporary test database.
It creates 24 monthly snapshots through the actual API and records one test
receipt per snapshot. No user database or external transfer is involved.
The full receipt fixture is in frontend/e2e/billingPaidFixture.mjs.
The expected paid advances are exactly 120/60; the former unit-based estimate
produces 240/120 and demonstrably fails the updated assertions.

## Coverage
The five billing browser tests check finalization, rejection without statements,
source-preserving revisions, actual PDF revision text, available credit persistence,
idempotent posting and a three-version adjustment chain. Printed PDF revisions
1, 2 and 3 are asserted in the normal test suite, not in a separate diagnostic.
The narrow ReportLab text helper uses Node standard libraries and fails on
unsupported formats. Unit tests cover decoding and avoid mistaking metadata for
rendered PDF text. It is not a full PDF parser or a visual layout checker.
Receipt detail assertions require actual receipt IDs, cutoff amount, exclusions
and post-cutoff reversal metadata according to Root's updated API contract.

## Two application fixes found during integration
Legacy credit entries may retain an existing historical receivable reference;
this is labelled historical evidence and never provides a payment action.
A real revision-three run also exposed lost form input: a preflight response
recreated the field definitions and changed the submitted amount from700 back
to900. Statements now memoizes its field definitions and cost initial data.
Two deferred-preflight regressions reproduced this for create/edit before the fix.
The shared FormModal component was deliberately not changed.

## Verified combined runs
QA worktree ui-billing-verification uses only committed Root backend sources.
On Root28986ba (including private-file discovery ed8a0da), all9 normal browser
cases passed, without increasing timeouts or pool limits. On Rootc77fbc7, including
receipt-evidence backend848281e4, all5 billing cases passed with strict receipt ID
assertions and actual PDF text checks. Full normal run:8/9; the sole failure is
an unchanged older draft assertion requiring the entire600 EUR on tenant statements,
although vacancy allocation now reserves an owner share. The owner follow-up
will assert tenant+owner=property total600 without changing the fixture.
Combined unit suite:245/245, lint and build passed. Source-only unit suite earlier:
210/210. Counts are different bases, not additive.

Evidence: work/ui-settlements-evidence/{poolfix-full-e2e,receipts-final-e2e}.log,
receipts-final-unit-tests.json and receipts-final-lint.log. Earlier failures and
traces are archived under united-first-results; they are not hidden or counted
as passing. The form-reset baseline failed both new deferred-preflight tests.
Final sources deliberately exclude backend fixes and discovery configuration;
Root owns their commits. This patch requires the receipt-evidence backend contract.
