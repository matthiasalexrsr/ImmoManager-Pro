# Changelog

All notable changes to ImmoManager Pro will be documented in this file.

## Unreleased — 2026-10-08

- **Explicit upgrade, no hidden schema change.** The normal start initialises an empty database (schema plus Alembic stamp) and refuses every other database that is not at the Alembic head, with the command to run; the in-memory fallback never hides this. `python -m backend.upgrade` (Windows package: `ImmoManager-Pro.exe upgrade`; `--check`, `--no-backup`) takes a verified full backup first and then migrates, including the adoption of unversioned desktop databases. The desktop launcher (`python -m backend`, `.exe`, `start.bat`, Windows service), the Docker entrypoint, `scripts/update.sh` and the in-app updater run this step; `AUTO_MIGRATE` is ignored. A binary restore of an older `.db` backup is upgraded explicitly after its safety copy (newer or foreign databases are refused before anything is replaced); the table-by-table `ensure_*` patches are gone.
- **Integration secrets encrypted at rest** (AES-256-GCM, key id in every value, field-bound): key file `<DATA_DIR>/secrets/keyring.json` (owner-only, created on first use) or `SECRET_KEYS`; existing plaintext values are encrypted on the first load without loss; a missing key locks changes with a clear message instead of resetting; the API only ever shows `***`; `python -m backend.ops rotate-key` rotates and re-seals.
- **Full backups**: one ZIP archive with the database (SQLite online backup; PostgreSQL `pg_dump` from one exported snapshot, refused clearly without `pg_dump`), all uploads, integration settings and journal, `.env` and the key file (optionally sealed with `BACKUP_PASSPHRASE`), a manifest with SHA-256 per file, row counts and app/Alembic versions, and a `.sha256` file. Daily at 01:30 and a monthly isolated restore probe on the 1st at 03:30 (Europe/Berlin) as durable jobs; retention 14 daily / 6 monthly / 3 pre-upgrade; optional verified copy to `BACKUP_SECOND_TARGET`; CLI `python -m backend.ops backup|verify|probe|restore|status`; restore only into a new directory. Operations overview `GET /api/v1/admin/operations` (installation scope only) and a "Betrieb" panel under Settings → System (de/en/es).
- **Reproducible dependencies**: `constraints.txt` pins the whole Python dependency tree (`pip install -r requirements.txt -c constraints.txt`), `cryptography` and `psycopg2-binary` pinned exactly, CI tools pinned; Docker base images pinned by tag and digest, `postgresql-client-16` in the app image, data volume `/app/data`; install scripts use `npm ci`.
- **Upgrade notes for operators**: Windows/desktop: nothing to do, the launcher upgrades with a backup before the start (watch the console once). Docker: rebuild the image; the entrypoint upgrades, data now persists in the `appdata` volume (uploads stayed in the container before). Source/server installations: stop, update, `pip install -r requirements.txt -c constraints.txt`, `python -m backend.upgrade`, start. Back up `secrets/keyring.json` (it is in every full backup; with a passphrase keep the passphrase separately). See [operations, backup and secrets](docs/OPERATIONS_BACKUP_SECRETS_20261008.md).
- Utility statements (migration `c3e8a1f5d9b7` after `b8e3d5f7a2c4`): a consumption key counts one medium in one unit of measure; meters in another unit are converted only by an exact factor once the key names its billing unit (MWh → kWh), otherwise the statement is refused with a clear message (gas m³ → kWh, heat cost allocator units). A replaced meter counts until its removal date and its successor from its installation date (final + initial reading). Contracts get dated occupants and the person key shares by person-days; advances follow every change of the rent history, a change mid-month by days. Statements show these sections.
- Issued statements never change: every status from finalized on (also disputed) refuses regeneration and edits, the status changes only through the workflow, the shown document and PDF are frozen at finalization (byte-identical PDFs), the stores refuse content changes, and snapshot imports are checked against the finalized version. Objections are recorded with date and reason; a correction is a new version that names the version it corrects, marks it as corrected when finalized and bills only the difference. See [the billing regression](docs/BILLING_REGRESSION_20261008.md).

## Unreleased — 2026-10-07

- Calculate money in exact cents everywhere (half-up rounding of each stored amount, Decimal sums, JSON numbers as before) and give every finance report the same filters: period, portfolio, property and unit. Keep three views apart: the cash view (payments in the period, a row for every month including months without bookings), the new period result `/reports/period-result` (rent due from the contracts' rent history plus other income minus costs; tenant payments are not counted again) and the forecast (rent the contracts will owe plus averages over complete months, months without bookings included; the starting balance no longer contains future bookings). Bookings are summed in the database (integer cents on SQLite and PostgreSQL, through the request's portfolio boundary). Book reversals (Storno) linked to their original (migration `f3b9c1d7e2a5` after `c3e8a1f5d9b7`, `POST /bookings/{id}/reverse`, "Stornieren" in the booking view): reports net them on the original's side, so a returned rent debit lowers income instead of counting as income and expense; reversals follow the original's contract allocation, and a reversed booking cannot be deleted or reassigned alone. Tenant accounts and contract settlements no longer count payments after their reference date, overpayments stay the contract's credit, and the account page shows exact totals from the server. See [finance precision](docs/FINANCE_PRECISION_20261008.md).
- Run recurring-task generation and escalation as durable installation jobs (migration `b8e3d5f7a2c4` after `a7c2e9f4b1d3`): leased runs with fencing tokens, chunked checkpoints that resume after a restart, safe claiming by several workers (PostgreSQL `SKIP LOCKED`, SQLite conditional update), retries with backoff, and an occurrence ledger that dedupes per series, rule version and Berlin calendar date, also for the manual endpoint across processes. Daily slots are DST-correct; missed task occurrences are caught up in bounded chunks (default: only the newest becomes a task, `RECURRING_CATCH_UP=all` creates each). Jobs run without an account and never cross the portfolio boundary. See [durable jobs](docs/DURABLE_JOBS_20261007.md).
- Limit what each account sees to its portfolios: owners assign all or selected portfolios in Settings → Users; lists, direct IDs, counts and reports, files, search and writes follow the assignment at once, also for tokens already issued, and a withdrawal stops a running write before its commit. Existing accounts keep seeing everything; new accounts see nothing until assigned. Installation administration needs all portfolios. Shared result caches are now separated by access. See [portfolio access](docs/PORTFOLIO_ACCESS_20261007.md).
- Issue the Wohnungsgeberbestätigung from each contract row and each contract card in the party record: suggested but never pre-filled move-in date and residents, a reviewed PDF preview in the dialog, three explicit confirmations, release as an immutable original, retry of the exact command after a lost answer, and corrections as new originals. The document list and party record refresh after a release and name the type in plain words.
- Store generated originals immutably (migration `e5f1a7c3b9d2` after `d7a2f9c4e681`): version manifests and 64 KiB blocks, verified on every read; database triggers refuse changes; a destructive downgrade is refused. Snapshots (format 3) carry the originals; imports, restores and SQLite backups are proven before they are applied. See [the integration status](docs/WGB_CONSOLIDATION_20261007.md#umsetzungsstand-im-aktiven-zweig).
- Rebuild navigation, the dashboard and portfolio/party lists around a calmer workspace with clear actions, compact summaries and accessible controls; preserve existing domain workflows.
- Render PDF pages locally with PDF.js, page navigation, zoom, text access and clear recovery states; bundle workers, fonts and other resources without a CDN.
- Require active sessions for upload/PDF/OCR access, coordinate protected file loading and confirmed logout, and preserve retryable sessions after temporary network failures. Object-level read permissions remain a separate gap.
- Connect property and unit dossiers with direct navigation and document previews; distinguish loading errors from empty records and label master-data rents as planned rents.
- Open review items at the exact booking, preserve the review return path, show receipts in the shared viewer, and prevent stale save responses from closing a newly opened editing form.
- Search in the database instead of loading every record: each type is matched with escaped, case-insensitive substring search, shows its exact total and pages on with stable cursors ("Load more" in the global search); all hits of one type export as CSV (`/search/export`). Totals, pages and exports stay within the account's portfolios. See [global search](docs/GLOBAL_SEARCH_20261007.md).
- Fix contact/name/company and property address/postal-code search against the actual models.
- Record authenticated vermieter1 and native WISO sample observations, distinguish observed features from unverified workflows, and prioritize further improvements in [the competitive review](docs/COMPETITIVE_REVIEW_20261007.md).
- Remove date-filter truncation on large lists; improve booking indexes, cache expiry and pending-job cancellation.
- Add reliable task completion/reopening, recurrence validation and explicit conflict/retry handling; retain archived parties in historical contracts.
- Add configurable SMTP with a non-sending connection check, validated integration actions, atomic configuration persistence and a durable paginated execution journal.
- Correct legacy PostgreSQL floating monetary columns through migration `d7a2f9c4e681`; preserve existing values and document the non-destructive downgrade behavior.
- Harden isolated Windows stress testing and verify million-row pagination, ten-user writes, local SMTP and narrow-screen behavior. See [hardening validation and remaining limits](docs/HARDENING_20261007_VALIDATION.md).
- Open a tenant information card from names throughout the tenant, contract, unit and financial views, with contacts, current/historical contracts, individual rents and direct account/edit/document actions.
- View, search, filter, preview and download each tenant's documents, including historical contracts and direct tenant assignments before a contract exists. Add single or multiple files directly to a tenant.
- Export the complete filtered tenant document list, independently of the visible page. Keep uploads and pending responses associated with their original tenant when navigating.
- Preserve form edits while asynchronous choices refresh, refresh archived-tenant choices after changes, and improve narrow-screen controls and modal keyboard navigation.
- Add migration `6e2f8a4c9b71`, API/regression coverage and a repeatable browser acceptance script. See [implementation and validation notes](PARTY_WORKSPACE.md).

## [1.2.0] - 2026-02-11

### Added
- **Centralized Configuration**: New `backend/config.py` using pydantic-settings for all env vars
- **Structured Logging**: JSON and text log formatters with request correlation IDs
- **Global Error Handling**: Standardized error responses with error codes across all endpoints
- **Frontend Error Boundary**: React error boundary catches render crashes with German error page
- **Toast Notifications**: Non-blocking toast system for success/error/info/warning messages
- **Dark Theme**: Full dark mode with theme toggle in sidebar
- **i18n Framework**: Custom i18n provider with locale switching (DE/EN/ES)
- **Spanish Locale**: Complete Spanish translation of all 200+ UI strings
- **English Locale**: Complete English translation as fallback locale
- **Locale Switcher**: DE/EN/ES buttons in sidebar footer
- **Global Search**: Search across properties, tenants, units, contracts, tasks, invoices (Ctrl+K)
- **Notification Bell**: Real-time notification dropdown with unread count badge
- **Plugin System**: Abstract plugin base class, discovery, event bus (pub/sub)
- **User Preferences**: Theme, locale, sidebar state, items per page persisted to DB
- **Admin API**: Version info, backup/restore, integrity check, export/import, bulk delete
- **Database Constraints**: CHECK constraints, composite indexes, unique constraints on ORM models
- **Auto-Migration**: Optional Alembic auto-upgrade on startup
- **Token Refresh**: Automatic JWT token refresh on 401 responses
- **Update Script**: `scripts/update.sh` for one-command updates

### Changed
- `api.js` now parses standardized error response format
- Layout component uses i18n translation keys instead of hardcoded strings
- Sidebar supports collapsed state with icon-only navigation

## [1.1.0] - 2026-02-10

### Added
- React + Vite frontend with 12 CRUD pages, dashboard, and auth
- CLI launcher and seed script
- Docker and CI/CD support

## [1.0.0] - 2026-02-09

### Added
- Initial release with 24 CRUD routers, domain engines, reports
- JWT authentication with RBAC (5 roles)
- SQLAlchemy 2.0 ORM with repository pattern
- 503 tests passing
