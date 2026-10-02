# Persistent settlement summary UI

Base: cfd93df. Isolated branch assist/settlements-ui-e2e, work/statements-review.
Implements Root's GET/POST contract documented at 11:23 in AGENT_COORDINATION_UI.md.
No backend/schema/auth provider/import/dependency changes. Root integrates alone.

Statements now shows per-period booked debts, available credits, signed net totals,
per-contract status and receivable references. Credit availability explicitly does
not confirm a payout. Correction periods show the delta-chain explanation and
persistent revision number, source period and notes when present in the response.
No current open-balance or payout is inferred from historical posting totals.

New BillingSettlementSummary cancels obsolete GETs, hides stale/partial totals,
shows persistent load errors and a read-only retry. Invalid amounts, inconsistent
totals, duplicate statement IDs or kind/status mismatches fail closed. Successful
empty ledgers are distinguished from missing data. POST results report both new
receivables and credits plus existing counts; every attempt reconciles with GET,
including an incomplete/lost response. Read retries do not repeat the mutation.

43 new regressions: parser, locale rendering, stale requests/cancellation, failure
recovery and parent POST/GET integration. Entire UI suite passed 186/186 using
--maxWorkers=2; one earlier unmodified 1001-option test exceeded its 5s timeout
under default parallelism. Monetary assertions were not relaxed. Intl expected
NBSP was normalized only to match Testing Library's whitespace normalization.
Build passed. Evidence: work/ui-settlements-evidence. Final combined real-backend
verification belongs with the following E2E patch and the pending billing backend.
New translations: 26 leaves per locale, only pages.statements.settlements.
