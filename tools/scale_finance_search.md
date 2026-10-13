# Finance and search scale benchmark

Run from the repository root with the application's Python environment:

```text
python -m tools.scale_finance_search --rows 100000 --mixed-seconds 60
python -m tools.scale_finance_search --rows 1000000 --mixed-seconds 60
python -m pytest tools/scale_finance_search_test.py -q
```

Run the 100k stage first. Review its errors, memory and latency before running 1m.
Each invocation creates a new synthetic SQLite fixture below the ignored
`artifacts/scale-finance-search` directory. It never reuses an existing database,
contacts the installed app, or sends external messages. Every writable setting,
including temporary files, is pinned to that fixture. AI, plugins and both
background schedulers are disabled. The app runs on its own dynamically selected
loopback port in an owned process group; Windows launcher children are included.

The source HEAD, dirty paths and relevant source hashes are recorded at both ends.
Existing host workload is not controlled: timings describe this workstation and
this run, not a general capacity promise. The benchmark uses the product code at
server startup. A changed hash between start and end is explicitly reported.

## Fixture and assertions

- 240 months, January 2006 through December 2025; 3 portfolios, 6 accounts,
  30 properties, 300 units, tenants, contracts and rent histories.
- The requested booking count, with income, expense, uncategorized amounts,
  unit-only property attribution, tenant payments and paired reversals.
- 72,000 receivables, with open, partial, overdue, paid and cancelled statuses,
  plus credits. `--no-receivables` isolates booking/search pressure and records
  that exclusion in the report.
- Generation-time integer-cent sums, category/month/account totals and search
  ID digests. The oracle does not call product calculations or retain all rows.
  A separate SQLite count/sum and foreign-key check verify the seed itself.
- Finance and cashflow for all records, a year, a portfolio, a property and a
  unit; repeated reads; a restricted user's totals; two account balances;
  summary/aging for all records, a year and a unit.
- Exact search counts and first pages for common, absent, unique-tail, Unicode,
  literal wildcard and export terms; subsequent keyset pages; a restricted user;
  overview tail hit; complete selected search exports checked row by row and
  by ordered ID digest. At 1m, the export term matches more than 10,000 bookings.
- First and last filtered booking pages compared with independent SQL.
- Ten separately created, authenticated users: four keyword-search readers,
  four historical-cashflow readers and two writers. Four readers have restricted
  portfolio access. Up to 20 writes per writer are spread over the load window.
  Actual concurrent reads/writes are counted. Every acknowledged write is checked
  for exact persisted contents and uniqueness; subsequent full cashflow and
  finance totals are checked immediately, without waiting for a cache expiry.

This is a cardinality benchmark, **not** twenty years of simulated business
workflows. It does not measure period-result or forecast calculations, DATEV,
restart/allocation recovery, backup/restore, physical documents/OCR, PostgreSQL,
or browser rendering. These exclusions are also stored in `report.json`.

## Bounds and evidence

Defaults are 30 seconds per HTTP operation, 600 seconds for the stage, 2 GiB
maximum combined app-process RSS/private memory and at least 1 GiB system memory
remaining. Flags expose each bound. Resource sampling occurs every 250 ms and
includes the app worker, not just its Python launcher. A guard stop is failure;
partial work is never converted into success. CPU values in raw samples are
cumulative process counters; phase records also carry sampled CPU deltas.

`report.json` is atomically checkpointed after each phase, including failures.
`requests.jsonl` keeps every completed request's timing/status and
`resources.jsonl` keeps the sampled process counters. `failure.txt` and
`guard-failure.txt` explain interruptions. CSV files and the synthetic database
remain available for investigation. No bearer tokens or passwords are included
in the request or report output. Exit code 0 requires every executed oracle and
cleanup to succeed; any error returns 1.
