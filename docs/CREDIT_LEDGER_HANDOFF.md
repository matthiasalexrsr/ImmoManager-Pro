Credit payouts and offsets
=========================

`credit_receipts` and `credit_reversals` preserve actual payout/offset evidence.
Amounts are integer-cent strings, with no invented amount or record-count cap.
Every receipt consumes exactly one posted negative BillingSettlement source.
The original settlement stays historical evidence: `credit_available` on that
row does not assert that its amount remains unspent.

Positive revision claims reserve remaining funds only within the same
`root_statement_id` chain. A selected offset can consume its own reservation.
The offset writes a real Payment and its credit receipt in one transaction.
Payout confirmation records an already completed cash or bank payment; it never
initiates a bank transfer. Bank payouts require a negative booking, the same
portfolio and matching assigned tenant/property/unit, and the booking's date.
The booking's absolute amount is a shared budget across all allocations.

POST commands retain an immutable idempotency key on identical replay. Changed
commands conflict. Full reversals are separate immutable records. Reversing the
linked Payment through the ordinary payment endpoint also reverses the credit
receipt, avoiding double release. SQL commands, payment/reversal balance changes
and billing posting serialize on Contract rows; payment/booking CAS remains in
place. Memory commands use the existing global financial RLock and rollback
both sides if a journal write fails.

Integration requirements
------------------------

Register `backend.db.credit_models` before metadata creation/autogeneration in
the application's DB bootstrap and Alembic metadata. Migration n1 follows m1.
For an existing local `create_all` database, use the explicit stopped-application
CLI in [CREDIT_SCHEMA_UPGRADE.md](CREDIT_SCHEMA_UPGRADE.md). It creates a new,
protected SQLite snapshot before DDL and rolls back a failed rebuild.
The old positive-only bookings check cannot accept negative-bank
allocations. n1 requires a stopped application and a SQLite migration connection
with FK enforcement disabled during the table rebuild. It preserves trigger
definitions and checks all foreign keys afterward. It refuses a live FK-enabled
connection before DDL, and refuses populated-journal downgrade before any drop.
Do not silently rebuild user databases during a live request.

Business-subset JSON import is explicitly refused before mutation (and checked
again under the import's financial locks) when credit receipts already exist or
incoming payments carry credit provenance. The subset does not have the complete
settlement graph. Full database/server recovery includes these registered tables.
Tenant privacy export version 2 includes the actual credit receipts, linked
payments and reversals, plus the current unspent/reserved/available summary in
one coherent snapshot. The contract settlement API exposes a separate
`credit_snapshot` marked current; it does not mix that balance into historical
rent. Journal SQL uses one reversal join rather than a query for every row.

API
---

* GET `/billing/contracts/{id}/credits`: exact decimal strings, per-source funds,
  availability and reserved claim references.
* GET `/billing/contracts/{id}/credit-receipts?offset=0&limit=50`: persisted audit
  journal, with optional nested reversal; SQL pagination has no business cap.
* POST `/billing/credit-payouts`: `source_settlement_id`, positive-cent `amount`,
  `transaction_date`, `idempotency_key`, optional `note`, `method` cash/bank,
  optional bank `booking_id`, and literal `confirmed_payment: true`.
* POST `/billing/credit-offsets`: common fields plus `target_type` and `target_id`.
* POST `/billing/credit-receipts/{id}/reversal`: `idempotency_key`, `reversal_date`,
  nonblank `reason`.

The Statements journal allows owner/manager/bookkeeping writes, preserves failed
drafts and retry keys, rechecks permissions after explicit confirmation, and shows
persisted balances/history after a successful command. No online full-backup or
bank-transfer route is introduced.

Verification
------------

`test_credit_ledger.py`, `test_credit_http.py` and `test_credit_migration.py`
exercise actual memory/SQLite stores, real posted corrections and HTTP RBAC.
`test_credit_concurrency.py` uses the existing dedicated
`TEST_SERVER_DATABASE_URL` UUID-schema fixture for independent PostgreSQL sessions;
without that dedicated URL its three gates skip. It must be included in the real
PG CI job; a local skip is not PostgreSQL execution evidence.
