# Reviewed bank allocation (G10.2)

A persisted bank booking can suggest open monthly rent charges, other rental
receivables, or supplier invoices. Importing a file and loading suggestions never
creates a payment. The operator chooses a target and an exact positive cent
amount, then confirms explicitly. No external banking service is needed.

## Review and confirmation

`GET /api/v1/bookings/{id}/suggestions` accepts `kind` (`rent_charge`,
`receivable`, `invoice`), optional literal `search`, `page_size`, and a signed
`cursor`. The typed envelope contains `items`, `next_cursor`, `has_more`,
`available_cents`, and `ambiguous`. Explanation codes distinguish a reference
contained in the bank text, an exact remaining amount, compatible portfolio and
property, and a partial payment. Equal ranks require the operator to choose;
the ranking is evidence to review, never proof of the payer's intent.

SQL joins and filters the actual targets before `LIMIT page_size + 1`, with no
global count or per-candidate lookups. Page size is a transfer buffer governed by
`BOOKING_PAGE_MAX_SIZE`; it does not limit portfolios, years or total matches.
Memory uses the same ordering and a bounded heap. Date/id keysets keep all later
pages reachable. A changed filter or source requires a new review.

`POST /api/v1/bookings/{id}/matching` accepts `review_token`, `amount` (a decimal
string with exact cents), `idempotency_key`, and optional `note`. The signed,
versioned review expires after one hour and binds the source, current account
and its canonical IBAN hash, target financial state, parent portfolio, and
principal's grants. Tokens contain hashes rather than raw bank identifiers.
Current authorization, account and target are checked again under the existing
payment serialization locks. SQL publishes target balance, bank allocation and
the central receipt in one transaction. A replay returns the same receipt only
for the same command. Stale or expired reviews provide a recoverable error code;
the client reloads suggestions and asks the operator to review again.

## One cash source and one receipt ledger

Rental payments consume positive bank bookings. Invoice payments consume
negative bank bookings but retain the central receipt's positive amount
convention. Invoice payment dates equal the actual linked bank booking date.
Both invoice payments and existing credit payouts consume the same
`abs(booking.amount) - allocated_amount` budget. Neither a receipt nor its
reversal creates another bank booking or a second tax cash movement.

Invoice `amount_paid` is read-only and changes through receipts and reversals.
The original receipt and its separate reversal remain in history. Paid balances,
parent deletion guards, restoration and cash budgets include this third target
type. Existing rent and receivable clients retain their endpoints and payloads.
Invoices expose `/{id}/payments` and the existing nested reversal pattern.
Metadata edits remain possible; manual paid-status edits contradicting the
receipt ledger return a conflict. Explicit historical paid invoices retain their
old balance during upgrade without inventing bank receipts.

Ordinary `POST /invoices` accepts the unpaid initial states `open`, `overdue`,
and `cancelled`. Requesting `paid` or `partial` returns a recoverable
`409 INVOICE_PAYMENT_REQUIRED` before creating any row; unknown initial states
return `422 INVOICE_STATUS_INVALID`. This restriction concerns new HTTP records;
explicit historical transfer and existing legacy balances remain unchanged.
The invoice page distinguishes stored paid totals, which may include carried-over
balances, from the receipts actually shown in its history. An empty history never
fabricates evidence for an existing legacy paid status.

The legacy `/invoices/{id}/match` endpoint returns 410 with a concrete new review
endpoint and `/bookings` navigation. Its old global FIFO preview ignored cash
already consumed and current account ownership. The pure domain FIFO helper
remains available for existing non-persistent analysis.

Supplier invoices are outside the current tenant metadata-export graph. Unrelated
invoice receipts are excluded rather than leaked into tenant exports. A bank
source explicitly assigned to the tenant with invoice evidence fails closed with
an explicit unsupported-scope reason until a broader tenant export is reviewed.

## Operator workflow

On **Bookings**, choose **Review allocation** for a persisted bank movement.
Positive movements offer rent charges or receivables; negative movements offer
invoices. Suggestions explain their evidence and show remaining target and bank
amounts. No radio option is selected automatically. Search and later suggestion
pages remain read-only until an authorized operator chooses a target, enters
an exact cent amount and explicitly confirms.

On **Invoices**, **Choose outgoing bank booking** opens the actual booking view
with that invoice's identifier as the candidate search. It does not mark the
invoice paid. Invoice rows and totals display central receipt balances and
remaining amounts, including partial payments. The receipted status is read-only
in the metadata editor. Existing historical paid balances remain visible.

**Payment receipts and reversals** reads `GET /bookings/{id}/allocations` or
`GET /invoices/{id}/payments?page_size=25` in bounded signed pages. The older
invoice endpoint without `page_size` retains its list shape. A moved, hidden
bank parent makes a visible invoice history fail explicitly instead of looking
empty or complete. Receipt timestamp ties use bytewise IDs; SQLite's whole-second
and fractional timestamp spellings are normalized before keyset comparisons.
Credit payouts are documented separately in the credit journal and consume
the same displayed bank budget.

An authorized operator can reverse a selected receipt with a reason and date,
then confirm. Cancellation creates nothing. Mutation controls are locked during
confirmation; permission changes invalidate pending commands. Network retries
retain the exact idempotency key and form. Malformed responses do not count as
successful writes or discard the command. Stale reviews require explicit reload
and renewed selection. Readonly accounts can inspect both evidence and history.

## Schema and application integration

Revision `w1a2b3c4d5e6` follows `v1a2b3c4d5e6`. It adds invoice balances and the
nullable invoice foreign key to the existing payment table, preserving exactly
one target and positive receipt amounts. SQLite offline table rebuilding holds
and restores existing trigger definitions in its DDL transaction; backfill must
not activate independent business triggers. Invoice receipt/reversal update
guards preserve history. Downgrade refuses while any invoice receipt exists,
including reversed receipts. Stop the installation and create a verified full
recovery archive before the documented offline migration.

Application registration belongs to the integration package: mount
`backend.routers.bank_matching.router` before the generic booking ID router;
call `ensure_invoice_payment_columns(connection)` for additive historical SQLite
read compatibility, and `ensure_invoice_payment_immutability(connection)` after
tables exist. Compatibility does not rebuild live tables; invoice recording on
an old two-target constraint returns actionable upgrade guidance. Complete
offline recovery archives retain the schema, receipt IDs, reversals and balances.

The full SQLite recovery reader also accepts the supported pre-w1 absence of
`invoices.amount_paid` and `payments.invoice_id`, so the verified full archive
can be created before upgrading. Other missing columns, incomplete tables and
invalid foreign keys still abort. A real downgrade to v1 followed by encrypted
backup/restore preserves rent receipts, reversals and original upload bytes.

## Verification

The focused tests use actual Memory and independent SQLite stores, authenticated
HTTP requests, stale-source rejection, role/grant revocation, exact partial
amounts, credit payout collision/release, cash-source non-duplication, SQL
identity-cache refresh, parallel confirmation, direct receipt restore,
immutability, actual Alembic upgrades/downgrades with sentinel triggers, and a
source-gone full recovery. Dedicated PostgreSQL tests use the existing isolated
UUID-schema fixture when `TEST_SERVER_DATABASE_URL` is supplied; an absent URL
is an explicit skip, never a local PostgreSQL pass. Invoice list regression also
proves a dated match remains reachable beyond 10,000 historical invoices.
