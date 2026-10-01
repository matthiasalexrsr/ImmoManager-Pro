# Browser workflow tests

These tests build the production frontend and start the actual FastAPI app with
demo data in a fresh temporary SQLite database. They interact with rendered forms
and assert the resulting API records after reloading. Requests are not mocked.
The runner checks that the server is using `SQLAlchemyStore`, stops its server at
the end, and removes only its own temporary data directory. Existing databases,
uploads and preview servers are not used.

From the repository root, install the backend and frontend dependencies:

```sh
python -m pip install -r requirements.txt
npm ci --prefix frontend
cd frontend
npx playwright install chromium
npm run test:e2e
npm run test:e2e -- --fresh-install
```

If the repository has a `.venv`, its Python executable is used automatically.
Otherwise the runner uses `python` from `PATH`. `IMMO_E2E_PYTHON` can select an
explicit Python executable. On Windows an existing Edge installation can be used
without downloading Chromium:

```powershell
$env:IMMO_E2E_CHANNEL = 'msedge'
$env:IMMO_E2E_PYTHON = 'C:\path\to\project\.venv\Scripts\python.exe'
npm run test:e2e
```

The default suite checks UI login, seeded property/contract relationships, a partial rent
payment and its persisted history and balance, plus a billing draft that moves
from blocked preflight to generated and persisted individual statements. Both
workflows check a 390-pixel mobile viewport and uncaught browser errors. Each run
starts with fresh demo data, so repeated execution does not change user data.

Normal suites use `demoFixtures.mjs` to persist German, light-theme, expanded
navigation prerequisites for the shared demo account before each UI login, then
wait for account preferences to load. This preserves genuine preference tests
without leaking their chosen language into later suites. The fresh-install
suite deliberately does not use this demo fixture. Monthly-generation tests
read every API page before selecting an unused month and explicitly fill both
month fields; earlier billing scenarios can leave more than 100 rent charges.

`--fresh-install` starts an empty database without demo users and runs the initial
owner and authenticator workflow. It verifies the local owner form, closed second
setup and public registration, authenticator enrollment, challenged login,
disable/persistence, rejected passwords/codes with successful retries, mobile
width and browser errors. Its report and logs live in
the `auth/` subfolders, so both runs remain available in CI artifacts.

A second serial first-install test then logs in as that owner and creates its
portfolio, property, unit, tenant, contract and bank account through the real API.
It books the September 2026 monthly rent of 750 EUR from a rendered preview,
verifies that repeating generation creates no duplicate, records a 100 EUR
manual receipt, allocates a 200 EUR bank booking, reverses that allocation with
a date and reason, and pays the remaining 650 EUR. Persisted receipts, released
bank allocation, historical rental account snapshots, open-item reporting,
summary/aging reports and dunning must agree at each stage. An unbooked October
stays a preview and creates no debt or dunning. The original bank income remains
in cashflow. The paid rent
and reversal history survive reload and fit a 390-pixel mobile viewport without
uncaught JavaScript errors. Run the entire fresh-install suite so owner setup
precedes this dependent workflow.

Playwright options can be forwarded, for example
`npm run test:e2e -- --grep "partial rent"`. Results are written to
`frontend/playwright-report/` and `frontend/test-results/`; failures include traces,
screenshots and the backend log. GitHub Actions installs pinned Chromium with its
Linux dependencies, runs both workflows, uploads these artifacts and includes the
browser job in the deployment gate.

The private-file workflow uploads genuine PNG/PDF documents through the UI,
opens the native PDF viewer, rejects active content disguised as a PDF, and
checks unit photos/documents after reload and fresh login as an approved reader.
Its browser requests use authenticated downloads and Blob URLs. The default
`chromium` channel uses Playwright's full Chromium with new headless mode so the
native PDF plug-in is available, as described in the
[browser documentation](https://playwright.dev/docs/browsers#chromium-new-headless-mode).

`navigation.pw.mjs` checks the sidebar's principal work areas, active route links
and breadcrumb return navigation in German, English and Spanish. Route selection
uses stable hrefs rather than translated menu labels. It checks actual API search
results for a seeded property with Ctrl+K, arrows and Enter on desktop and mobile,
plus Escape and a genuine empty search. The collapsed desktop sidebar retains
accessible route names and tooltips and supports navigation before expansion.
Its account preference must persist on the server and survive reload.
At 390 and 320 pixels the closed menu must
stay out of keyboard focus, the open menu must receive and contain focus, and
Escape, backdrop click and route selection must close it. Escape/backdrop dismissal
must return focus to the menu button. Document width and uncaught browser errors
are checked throughout. Three attached screenshots provide a desktop and two mobile
reference for visual review without prescribing pixels, colours or wording.

Run only these navigation checks with the same isolated SQL runner:

```sh
npm run test:e2e -- navigation.pw.mjs
```

`generation-form.pw.mjs` checks the real monthly-rent preview inside its form.
Search with Enter, column selection and CSV export each have an independent test.
Every interaction must leave the SQL charge list unchanged and send no generation
POST. The CSV must contain the previewed contract and month. Only activating the
explicit booking button may submit the preview hash and create one unpaid charge;
the amount and single record must persist after reload. An unused month is picked
from an actual seeded lease, so the tests need no additional business fixtures.

```sh
npm run test:e2e -- generation-form.pw.mjs
```

See the [Playwright configuration documentation](https://playwright.dev/docs/test-configuration)
and [Microsoft Edge documentation](https://learn.microsoft.com/en-us/microsoft-edge/playwright/)
for browser configuration details.

`operational.pw.mjs` exercises a real January-31 task series through the manual
operations form, completes the February child through its normal edit form,
checks March-31 generation and verifies repeat/reload persistence. Its second
case configures a calendar plan through the UI and checks its clamped dates and
deduplication. The task view is also checked at 390 pixels with an attached
screenshot. Both use the shared German demo fixture and check uncaught page errors.

```sh
npm run test:e2e -- operational.pw.mjs
```

Before backend startup the runner applies `alembic upgrade head` to its own
new temporary database. Automatic operational and backup workers are explicitly
disabled for these deterministic manual workflows. The runner neither migrates
nor changes any configured user database or uploads directory.

`bookings-scale.pw.mjs` creates 64 synthetic ledger rows through the genuine
authenticated API and traverses three server pages using their returned cursors.
It checks complete filtered CSV downloads, spreadsheet formula escaping,
bounded editor lookups, lookup Enter without implicit writes, an actual
`If-Match` edit and persistence after reload. The direct CSV case writes into
an actual browser OPFS `FileSystemWritableFileStream`: only the interactive file
chooser is substituted, while HTTP, database reads and streaming stay real.
Desktop, 390/320-pixel layouts and the mobile editor are inspected with attached
screenshots and the shared uncaught-error guard.

```sh
npm run test:e2e -- bookings-scale.pw.mjs
```
