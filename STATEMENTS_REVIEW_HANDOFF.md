# Billing statements reliability review

Date: 2026-10-01
Review branch: `assist/statements-ui-reliability`
Base: `2579326` on `codex/continue-rental-workflows`

## Scope and coordination

This review is isolated from `assist/atomic-json-restore`. No backend, database,
upload, authentication, payment-ledger, dependency, or backup code was changed.
The linked ChatGPT conversations were not readable, so coordination uses Git
worktrees and `wi/work/AGENT_COORDINATION_STATEMENTS.md`, not direct chat messages.

## Completed changes

- Render the previously invisible correction/dispute dialogs and notifications.
- Preserve entered reasons after rejected submissions; require a nonblank dispute
  reason and reuse the existing accessible form dialog.
- Fetch all eight paginated billing/reference lists instead of only 100 records.
- Display persistent load failures with retry instead of misleading empty data.
- Sum decimal-string cost values as cents, avoiding concatenation and crashes.
- Block generation/finalization until the selected period has a successful,
  well-formed preflight response; show failures and support explicit rechecking.
- Cancel obsolete loads/checks, ignore stale results, refresh after saved changes,
  and recheck preflight after editing costs.
- Prevent delayed mutation responses from navigating back to a previous period.
- Fetch newly created revisions directly by their returned ID.
- Supply missing workflow, retry, and status labels in German, English, Spanish.

## Verification

The initial nine UI regressions all failed against the unmodified page. Two more
failures were reproduced for discarded correction reasons and stale preflight
checks after cost edits before their fixes were applied.

Final frontend result: **38/38 tests pass**, including 15 new workflow tests and
three locale checks. ESLint and the production build pass. `git diff --check`
reports no whitespace errors; Git's Windows line-ending notices are informational.

From `frontend`, run:

```sh
npm test
npm run lint
npm run build
```

The headless Edge smoke uses the production bundle, actual app components and
isolated mocked API responses. It checks 1,001 decimal-string costs (10.01 total),
preflight failure/retry, correction failure/retry, encoded reasons, revision
navigation, translated labels, and the 390px mobile dialog/page layout.
There were no JavaScript runtime errors in that browser run. Synthetic requests
were intercepted before reaching a backend; no user records were created or changed.
This is not a claim of full-stack billing or backend regression coverage.

Local evidence: `wi/work/statements-evidence/` (JSON results, logs, screenshots).
Browser harness: `wi/work/browser-check/statements-smoke.mjs`; use the already
installed Playwright environment there. It starts a temporary Vite preview on
127.0.0.1:5179, runs Edge, and closes both on completion. Its argument is the
absolute path to the repository whose frontend has just been built.

## Remaining work for the coordinating agent

- Keep backup/restore changes on the other agent's independent track.
- Complete bank-booking/payment linkage and payment reversals before claiming a
  finished financial workflow; this patch does not solve ledger double-counting.
- Add real-backend browser coverage for generating, finalizing, delivering and
  revising bills; this review only runs controlled frontend browser scenarios.
- Other screens still need the same pagination, visible-error and cancellation
  review. Shared StatusBadge still falls back to raw non-payment status values.
- Consider splitting the large Statements component into workflow, loading and
  dialog modules after these behaviors are protected by the new tests.

No deployment or remote Git push is implied by this handoff.
