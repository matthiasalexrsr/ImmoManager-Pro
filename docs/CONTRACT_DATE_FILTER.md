# Complete date-filtered contract pages

The previous `/api/v1/contracts` date-filter path first read at most 10,000
contracts and then applied dates in Python. A valid matching contract after that
prefix silently disappeared. A synthetic 10,002-contract inventory reproduces
the loss against the old router in both Memory and SQLite: the requested one-row
page incorrectly returns an empty list.

The date-filtered path now applies portfolio visibility, property, tenant, status
and date predicates in the database before OFFSET/LIMIT. Only the requested
bounded result is converted to API models. There is no global COUNT, whole-table
materialization or inventory/year ceiling. The unchanged route's technical page
size remains 1–1,000, and later pages remain accessible through `skip`.

The existing semantics remain exact:

- `date_from`: contract start is greater than or equal to the supplied date.
- `date_to`: contract end is less than or equal to the supplied date; open-ended
  contracts are excluded when that filter is supplied.
- Other filters combine with AND; valid existing column sorts and direction are
  preserved. An unknown sort never becomes a SQL identifier or expression.
- The ordinary path without a date filter still delegates to the existing store.

The Memory adapter iterates references with the authoritative portfolio predicate.
It holds the existing reentrant payment/business write lock through visibility
checks and selection, so a concurrent deletion or portfolio move cannot produce
a mixed page or invalidate dictionary iteration. No inventory snapshot is made.
Unsorted reads retain only the requested slice; sorted reads retain the requested
prefix using top-k selection, rather than copying all matches into another list.
Like the previous API, dialect-native SQL NULL ordering and the Memory adapter's
NULL ordering remain distinct. This narrow fix does not introduce a new ID
tiebreaker or change the existing offset-paging contract.

`backend/tests/test_contract_date_filter.py` proves the actual large-inventory
failure, inclusive boundaries/null end dates, composed filters, descending sort,
offset after filtering, a hidden portfolio, unsafe sort input and ordinary
non-date paging. Its authenticated full-app HTTP checks validate date input and
fresh grant revocation using the same token. Synthetic inserts use bounded native
batches; no customer installation or source data is used.

Verification commands (set process-local store flags and remove inherited
`DATABASE_URL` so conftest owns the test database):

```powershell
python -m pytest backend/tests/test_contract_date_filter.py -q --tb=short
python -m pytest backend/tests/test_contract_date_filter.py backend/tests/test_portfolio_access_http.py backend/tests/test_invoice_list.py -q --tb=short
python -m ruff check backend/services/contract_list.py backend/routers/contracts.py backend/tests/test_contract_date_filter.py
python -m mypy --follow-imports=silent backend/services/contract_list.py
```

The shared query path is standard SQLAlchemy and has been executed on SQLite;
PostgreSQL execution is not claimed by this package. It adds no schema, settings,
startup hook, dependency or user-interface change.

Acceptance on base `65e3a80` (2026-10-02): the old router fails both large-inventory
regressions (2 failed); the corrected focused Memory run passes all 16 tests.
The combined SQL run with portfolio HTTP and invoice-list regressions passes
all 44 tests. Ruff passes for the three Python files and the service passes the
targeted mypy check. The single-query assertion is captured after fixture setup
and proves that the requested one-row page is bounded at the database boundary.

The concurrency followup adds two actual reader/writer cases: the reader pauses
inside visibility selection while a normal contract deletion or property move
attempts to acquire that shared lock. Both fail against `cded5ba`, where the
writer passes the paused reader, and pass with the lock. All 18 focused tests,
Ruff and service mypy pass after the followup; the SQL query code is unchanged.
