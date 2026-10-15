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

Defaults are 30 seconds per HTTP operation, 600 seconds for the entire run, 2 GiB
maximum combined app-process RSS/private memory and at least 1 GiB system memory
remaining. The `--stage-seconds` flag is the overall deadline, including startup,
fixture generation and every phase; it never resets at phase boundaries.
Flags expose each bound. Resource sampling occurs every 250 ms and
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

## Recorded runs, 2026-10-13

These are actual local SQLite runs on Windows with 8 logical CPUs and SQLite
3.53.1. Every run included 72,000 receivables and 240 months. Evidence directories
below are relative to `artifacts/scale-finance-search/`; each retains its original
`report.json`, `requests.jsonl`, resource samples and fixture. The two original
baselines were preserved. All four runs recorded unchanged relevant source hashes
between startup and completion.

| Bookings | Code | Evidence directory | Result | HTTP requests | Writes acknowledged / verified | Peak app RSS MiB |
| ---: | --- | --- | --- | ---: | --- | ---: |
| 100,000 | Baseline | `rows-100000-pwx4zpi9` | Passed | 1,225 | 40 / 40 | 327.91 |
| 100,000 | Native ASCII lower | `rows-100000-ncftvroe` | Passed | 1,722 | 40 / 40 | 326.36 |
| 1,000,000 | Baseline | `rows-1000000-vyv5yfnk` | Failed: search HTTP deadline | 333 | 20 / verification not reached | 327.84 |
| 1,000,000 | Native ASCII lower | `rows-1000000-km9ecxc7` | Passed | 204 | 40 / 40 | 327.91 |

The optimized runs used a configured 60-second mixed window and completed their
in-flight operations after 62.06 and 62.49 seconds. The 100k baseline mixed phase
lasted 63.42 seconds. The 1m baseline was stopped after 30.02 seconds of mixed
load by the unchanged 30-second search request guard; its configured mixed window
was not recorded, so it is not a matched-duration throughput comparison. It had
eight failed HTTP operations when the guard stopped its server. The optimized
runs had no HTTP errors, reached ten simultaneous requests and verified every
acknowledged write, including immediately refreshed aggregate results. Both
optimized reports confirm owned-process cleanup.

The following maxima are seconds, grouped by actual route in `requests.jsonl`,
not by the combined finance/cashflow phase. The single-user phases exercised the
same filters and repeated reads in every run.

| Bookings / code | Single finance max | Single cashflow max | Single search max | Mixed search requests / p95 / max | Mixed cashflow requests / p95 / max |
| --- | ---: | ---: | ---: | --- | --- |
| 100k baseline | 0.326 | 0.289 | 0.263 | 48 / 7.418 / 8.007 | 1,057 / 0.257 / 0.792 |
| 100k optimized | 0.214 | 0.311 | 0.201 | 451 / 0.661 / 0.951 | 1,151 / 0.215 / 0.756 |
| 1m baseline, interrupted | 2.222 | 3.607 | 3.475 | 6 / 30.010 / 30.010, includes errors | 231 / 1.818 / 2.898, includes errors |
| 1m optimized | 2.068 | 2.861 | 1.489 | 52 / 6.288 / 6.496 | 32 / 9.119 / 9.176 |

The optimized 1m run verified complete selected exports of 10,310 owner-visible
and 3,437 restricted-user hits. Its whole run lasted 186.50 seconds, including
fixture generation, with peak private memory of 301.67 MiB. Mixed booking-write
latency peaked at 0.359 seconds.

The search change avoids Python callbacks for ASCII text using a short-circuiting
SQLite `CASE`; Unicode text keeps the previous Python lowercase semantics.
Regression tests count callbacks across 10,000 ASCII rows and compare SQL versus
memory matching, counts, pages and exports for Unicode, literal `%`, `_`,
backslash and newline queries. PostgreSQL retains its existing database `lower`.
The fixture's booking text is mostly ASCII (the Unicode marker occurs roughly
once per 997 rows), so these timings do not establish Unicode-heavy performance.
Substring search still scans matching tables. The 1m mixed reads still took up
to 6.50 seconds for search and 9.18 seconds for cashflow; passing the guards is
not evidence of consistently low interactive latency or additional user capacity.

An earlier optimized 100k pilot, `rows-100000-0iisstwt`, also passed with a shorter
30-second mixed window; it is excluded from the main comparison above.

### Follow-up: date index, isolated caches and atomic booking writes

On commit `8c9686cd`, `rows-1000000-v1v0dtl1` passed with unchanged relevant source
fingerprints, ten simultaneous requests and a configured 60-second mixed window
(62.77 seconds including completion of outstanding operations). All 40 acknowledged
writes were verified; 91 read/write overlap events and zero HTTP failures. Full
selected exports retained 10,310 owner-visible and 3,437 restricted hits. Peak app
RSS 328.36 MiB; private memory 302.24 MiB. Owned processes stopped successfully.

Compared with `rows-1000000-km9ecxc7`, on the same workload:

| Route | Previous mixed requests / p95 / max | Follow-up mixed requests / p95 / max |
| --- | --- | --- |
| Search | 52 / 6.288 / 6.496 s | 64 / 4.905 / 5.149 s |
| Cashflow | 32 / 9.119 / 9.176 s | 903 / 0.768 / 1.448 s |
| Booking writes | 40 / 0.169 / 0.359 s | 40 / 0.325 / 0.563 s |

This is a substantial improvement for repeated historical cashflow under load,
not a uniform speedup. Single-user finance maximum rose from 2.068 to 2.174 s and
cashflow from 2.861 to 3.499 s. The whole run including creation of the indexed
fixture took 221.42 seconds instead of 186.50. Search remains a substring scan and
still reaches approximately five seconds under this mixed load.

The follow-up code includes a booking-date index, cache hits before the global
compute lock, database/transaction/mutation-safe cache boundaries, and one atomic
booking/allocation commit. Therefore this combined run does not isolate how much
each change contributes. The source fingerprint now also covers ORM/schema,
booking writer, memory scope guard and spreadsheet-export helpers. The previously
documented functional/system exclusions remain in force. Raw route comparison:
`artifacts/performance-20261013/scale-comparison.json`.
