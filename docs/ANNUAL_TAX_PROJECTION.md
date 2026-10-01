# Reviewed annual cash preparation

The annual workspace prepares recorded cash by portfolio, calendar year, property and **user-reviewed** form line. It does not calculate tax liability, depreciation, ownership shares or a VAT breakdown. The historical G35 plan mentioned tax preparation, while the existing TaxRate/VAT models did not implement an income-tax engine. This package supplies the explicit cash classification and its evidence rather than inventing those rules.

The supplied WISO Hausverwalter 365 handbook identifies the tax-export workflow and allocation-account/form-line assignment. An actual synthetic producer export from version 21.02.1530 for 2026 was subsequently observed. That proves what the producer wrote for that fixture; it does not prove that this application's files are accepted by WISO. This package exports **manufacturer-neutral CSV/JSON**, not vendor XML. A separately tested adapter can later consume reviewed snapshots once differential fixtures establish the field mapping.

## Cash and classification

Only `Booking` entries with status `confirmed`, in the selected calendar year and on/before the explicitly selected cutoff, supply cash. All statuses and later-in-year entries remain in the retained source file with their classification state. Unconfirmed entries require an explicit review reason before release. A year without any confirmed cash requires an explicit empty-year review. The cutoff cannot precede the year or lie in the future. A cutoff before December 31 is clearly a partial-year snapshot.

Receivables, monthly rent charges, payment receipts, invoice totals, bank opening balances and allocation reversals are **not** added as another cash movement. A journal reversal changes an allocation, not the underlying bank amount. Actual negative cash is classified as a refund/correction. The optional original booking ID records an earlier confirmed opposite-signed source from the same portfolio; its cash fields and revision are copied into the evidence.

Profile rules match an explicit `(account_id, category_id)` pair. A null category matches only uncategorized bookings. Each rule requires a reviewed income/expense form line or an explicit exclusion type and explanation. Nothing is inferred from category names or a guessed tax form. An included amount requires an explicit property. Shared cash can be split into signed cent amounts with individual property/classification/reason fields; their sum and signs must preserve the original booking exactly. A reviewed private/principal portion can be explicitly excluded. Interest/principal and ownership percentages are never guessed.

Income retains the cash sign. Expense equals the **negative** cash sign, so an actual positive supplier refund reduces expense. Excluded cash remains signed evidence. Internal transfers require a distinct bank account in the same portfolio, equal opposite confirmed cash, unique pairing, and explicit transfer exclusion on both sides. A cross-portfolio transfer must be reviewed separately; this package does not claim a hidden counter-booking as verified evidence.

All amounts are finite, nonzero, cent-exact decimal cash within the existing booking model's range. Summation uses Python integers; API totals and split amounts are signed integer **strings**. The UI parses decimal input and formats totals through `BigInt`, including aggregates above JavaScript's safe integer range.

The check is:

`cash_cents = income_cents - expense_cents + excluded_cash_cents + unclassified_cash_cents`

Unclassified sources block saving even when their signed net is zero. Invalid cash disables the complete-total indicators; partially classified figures are explicitly provisional. The UI displays up to 20 examples; this is not a source/export limit. SQL cash iteration and persisted source insertion use buffers of 1,000 with no total record cap.

## Versions and evidence

Profiles are immutable. A new reviewed profile optionally links its predecessor. Preflight is read-only and returns a SHA-256 `preview_hash` over the reviewed profile, complete ordered source file, request, totals, groups and review issues. Saving recompiles the cash snapshot and checks the hash; changed sources require a fresh review. Generated timestamps and retry keys do not affect that review hash.

There is one root snapshot per portfolio/year and at most one successor per snapshot. Database uniqueness and the Memory mutation lock prevent concurrent duplicate roots/forks. A new annual revision replaces its predecessor, retains its reason, and displays cent deltas. Revisions must **never be added together** as separate income. Idempotent retries return the original saved response, including after later live-booking changes; changed payloads with the same key fail.

The profile, manifest and each source JSON record retain hashes. Sources copy booking IDs, recorded signed amounts, dates/status/revision, account/category/property labels, receipt reference, explicit splits/reasons, and any counter/original evidence. Historical sources deliberately do not have a live-booking FK: later editing or deleting an erroneous unallocated booking must not erase the original reviewed evidence. The snapshot and its sources stay bound to their original portfolio. Saved responses include the retained `review_request`; reading rechecks it against the original preview hash. Preparing a revision restores these reviewed splits and reasons, including after reloading the page, instead of silently reverting to profile defaults.

Saving the manifest and **all** source buffers is one SQL transaction; any failure rolls back the whole projection. A completed ZIP is built privately before download headers, validates the entire retained source stream/hash/count/totals, and contains `manifest.json`, `sources.jsonl`, `cash-evidence.csv` and `tax-lines.csv`. Money columns contain integer cents; text CSV cells receive the existing spreadsheet-formula protection. A corrupt/missing source fails closed. Disconnect/permission-revocation cleanup uses the existing private-download response.

## Scope and roles

Options, profiles, projections, direct IDs and downloads enforce portfolio access. Cash SQL uses explicit `scoped_clause` predicates even on its independent repeatable-read connection. Authorized accounts with hidden cross-portfolio booking references block preflight without exposing the hidden data or falsely declaring a complete tax report. Memory follows the same visibility boundary. Captured grants are refreshed before buffers/publication/download. A changed or disabled principal terminates the request.

Owner, Manager and Accounting may review/save. Technician and ReadOnly can view authorized saved evidence but cannot create profiles, preflight or projections. No tenant-portal account or global-access capability is introduced.

## API and integration

Router `backend.routers.annual_tax.router` uses prefix `/reports/annual-tax`, mounted under `/api/v1` with `require_auth` like other reports. All POST routes independently require Owner/Manager/Accounting.

| Method/path | Request/result |
| --- | --- |
| GET `/options?portfolio_id=…` | `{accounts,categories,properties}` of `{id,name}`; no IBAN/secret fields |
| GET `/profiles?portfolio_id=…&tax_year=…&offset=0&limit=100` | `{total,items}` immutable profile versions |
| GET `/profiles/{id}` | Authorized immutable profile, including historical versions outside the current list page |
| POST `/profiles` | Reviewed `AnnualTaxProfileCreate`, actor-scoped `idempotency_key`; 201 profile `{id,spec,sha256,…}` |
| POST `/preflight` | `{profile_version_id,as_of,overrides,pending_review_reason,empty_cash_review_reason}`; manifest with `ready`, `preview_hash`, source/issue counts, groups and totals |
| GET `/projections?portfolio_id=…&tax_year=…&offset=0&limit=100` | `{total,items}` saved annual revisions |
| GET `/projections/{id}` | Immutable saved manifest with ID, actor, previous ID, revision number/deltas and retained `review_request` |
| POST `/projections` | Preflight request plus `preview_hash`, `idempotency_key`, optional `previous_projection_id` + required `revision_reason`; 201 saved manifest |
| GET `/projections/{id}/download` | Complete private ZIP, content SHA/size headers |

Classification is `income`, `expense` or `excluded`. `exclusion_kind` is `internal_transfer`, `deposit`, `loan_principal`, `personal` or `other`, required only for `excluded`. Included parts require `property_id` and reviewed `form_line`; every part needs `reason` and signed `amount_cents`. An override adds `booking_id`, `reason`, `parts`, and optional `correction_of_booking_id` / `transfer_counter_booking_id`.

Runtime integration included in this package:

- Import `backend.db.tax_models` in runtime/migration metadata registration. Fresh migration and legacy `create_all` startup add all three tables while preserving existing cash. Migration is `s1a2b3c4d5e6` after `r1a2b3c4d5e6`.
- Register the authenticated router, lazy `AnnualTaxPage`, route `/annual-tax`, and finance navigation label `finance.tax`.
- Reject business-JSON source imports; check existing tax profiles, projections and sources before destructive replacement/reset. SQL checks run before any DML; Memory checks run inside its mutation lock. A retained profile alone already prevents an ordinary reset. The error directs the operator to complete database backup and separate restoration.
- Complete native database backup/recovery retains these registered tables. Historical sources must not be regenerated from today's cash. This package does not run a production migration or remove user evidence.

The migration adds three tables without modifying existing cash. Its downgrade checks **all three** for evidence before any DDL, refuses a populated downgrade, and points to verified full-backup restoration. Empty downgrade→upgrade is supported.

## Verification

Focused tests cover Memory and real SQLite raw cash, signed refunds, explicit splits/exclusions, transfer pairing, pending/empty-year review, no duplicate obligations/receipts/invoices, immutable history after live edits/deletion, stale preview rejection, revision/fork protection, source corruption, second-chunk atomic rollback, actual authenticated finance roles/direct-ID/reference/download scopes, old-token revocation across two HTTP sessions, independent concurrent writers, and the full fresh Alembic chain plus downgrade guards. An additional native PostgreSQL case owns a UUID schema and activates with the existing dedicated `TEST_SERVER_DATABASE_URL`; absence is reported as an explicit skip.

Frontend regression tests exercise source errors/retry/stale aborts, three locales, role revocation, idempotent draft preservation, fractional-cent rejection, signed split payloads, blocked/partial totals, confirmation invalidation, source conflicts, restored revision splits and exact `BigInt` display. The native SQLite/Edge workflow creates real accounts/categories/properties/cash, maps income and expense through the UI, resolves a missing property by splitting every cent, confirms an immutable snapshot, reloads and verifies its downloaded source ZIP, then retains the original while saving revision two for an actual refund. Additional native ReadOnly/Technician cases verify authorized downloads, hidden financial commands, server-side POST rejection and immediate download revocation for the old token. Browser requests use the real application and isolated temporary SQL database; no API response interception is used.

A separate complete-recovery regression saves an actual reviewed tax snapshot, creates an encrypted native backup, removes the owned synthetic source installation, and restores into a separate directory. A new process reads the retained profile/manifest/request/source hash and builds the original source ZIP under the recovered configuration, despite an incorrect ambient database/JWT configuration. This does not modify a user installation.
