# ImmoManager Pro

Full-stack property management application for German real estate portfolios.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2 |
| Frontend | React 19, Vite, custom i18n (de-DE / en-US / es-ES) |
| Database | SQLite (verified local release); PostgreSQL adapter |
| Auth | JWT (access + refresh tokens), role-based access control |
| CI | GitHub Actions (lint, type-check, security audit, tests, build) |

## Quick Start

### Windows 11

Double-click `start.bat` or run:

```powershell
.\start.bat
```

The starter checks Python 3.11+, creates `.venv` when needed, verifies backend dependencies, and builds the frontend when its source or configuration changes. A valid unchanged installation can restart offline. Failed builds preserve the previous compiled frontend. It generates a persistent local secret and stores runtime data under `%LOCALAPPDATA%\ImmoManagerPro` by default:

- SQLite database: `%LOCALAPPDATA%\ImmoManagerPro\immo_manager.db`
- Uploads: `%LOCALAPPDATA%\ImmoManagerPro\uploads`
- Backups: `%LOCALAPPDATA%\ImmoManagerPro\backups`
- Logs: `%LOCALAPPDATA%\ImmoManagerPro\logs`

On a new installation, open the local login page and create your owner account.
This one-time setup is available only on localhost. Further accounts require owner
approval through the administration API; public registration closes permanently.
Authenticator enrollment and login codes are available in personal settings.
This release serves one private installation whose approved users share its
portfolios. See [the access model and offline recovery](docs/ACCESS_MODEL.md).

Useful variants:

```powershell
.\start.bat -Port 9000
.\start.bat -Seed
.\start.bat -DataDir D:\ImmoManagerProData
```

`-Seed` creates synthetic demo data and a demo account. Use a separate data folder
for demonstrations. Start without `-Seed` for your own installation.

Updates run with the application stopped. The settings page checks for updates
and displays maintenance instructions; it does not migrate a live database:

```powershell
.\.venv\Scripts\python.exe -m backend.maintenance --offline --data-dir "$env:LOCALAPPDATA\ImmoManagerPro" --port 8000
```

Use the actual data directory and port. See [Windows runtime and recovery behavior](WINDOWS_RUNTIME_HANDOFF.md).

Create a complete encrypted local recovery archive with the application and
background writers stopped. The passphrase is requested interactively:

```powershell
.\.venv\Scripts\python.exe -m backend.recovery backup --offline --data-dir "$env:LOCALAPPDATA\ImmoManagerPro" --output "D:\Private Backups\ImmoManager.immobak"
.\.venv\Scripts\python.exe -m backend.recovery restore --archive "D:\Private Backups\ImmoManager.immobak" --destination "D:\Recovered ImmoManager"
.\.venv\Scripts\python.exe -m backend.recovery run --data-dir "D:\Recovered ImmoManager" --port 8000
```

The archive contains every SQLite table, local uploads, users, two-factor state,
configuration and integration state. Restore requires a new directory and never
replaces the existing installation. See [the recovery instructions](docs/RECOVERY.md),
including legacy upload locations and external documents.

The scheduler creates **database-only** SQLite snapshots. These contain all tables
but omit uploaded files and external configuration/secrets:

```powershell
.\.venv\Scripts\python.exe scripts\backup_scheduler.py run --data-dir "$env:LOCALAPPDATA\ImmoManagerPro"
.\.venv\Scripts\python.exe scripts\backup_scheduler.py schedule --data-dir "$env:LOCALAPPDATA\ImmoManagerPro"
```

JSON backup/export in settings covers a defined business-data subset. Use the
encrypted offline archive for full local recovery.

### Development

```bash
# Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app:app --reload

# Frontend
cd frontend && npm ci && npm run dev
```

The app is available at `http://localhost:5173` (frontend) and `http://localhost:8000/docs` (API docs).

## Project Structure

```
backend/
  app.py              # FastAPI application entrypoint
  config.py           # Settings via pydantic-settings
  dependencies.py     # Store / DB session injection
  models.py           # Pydantic request/response models
  storage.py          # In-memory store (dev/test fallback)
  db/
    orm_models.py     # SQLAlchemy ORM models
    session.py        # DB engine & session factory
    migrations/       # Alembic migrations
  routers/            # ~45 API router modules
  domain/             # Business engines (lease, dunning, billing)
  repositories/       # SQLAlchemy-backed persistence
  services/           # Report calculations, OCR, integrations
frontend/
  src/
    App.jsx           # Route definitions, auth guard
    api.js            # API client with token management
    i18n.jsx          # i18n provider (useTranslation hook)
    pages/            # ~40 lazy-loaded page components
    components/       # Shared UI components
i18n/                 # Locale files (de-DE, en-US, es-ES)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./immo_manager.db` | Database connection string |
| `DATA_DIR` | project root, `%LOCALAPPDATA%\ImmoManagerPro` for Windows starter/.exe | Persistent runtime directory |
| `UPLOADS_DIR` | `<DATA_DIR>/uploads` | Uploaded document/photo storage |
| `BACKUP_DIR` | `<DATA_DIR>/backups` | Backup storage |
| `SQLITE_PERSISTENT_STORE` | `true` | Use SQLAlchemy persistence for SQLite |
| `ALLOW_INMEMORY_FALLBACK` | `false` | Fall back to in-memory store on DB failure |
| `JWT_SECRET_KEY` | `dev-secret-key-change-in-production` | Secret key for JWT token signing; must be overridden in production |
| `ENVIRONMENT` | `development` | `development` or `production` |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Allowed CORS origins |

## Testing

The current implementation assessment and prioritized remaining work are in
[DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md). Historical audit documents are
planning inputs, not a current checklist of missing features.

## Recording payments

Open **Finanzen → Mietübersicht**, select rent charges or receivables, and use
**Zahlung erfassen**. Enter the amount, date and an optional note. Each payment
creates a persistent receipt and reduces the allocated outstanding balance.
Partial payments, duplicate-request protection and payment history are supported.
By default the table shows outstanding items; turn off **Nur offene Posten** to
inspect completed items. Totals refer to the selected ledger.

Use **Bankbuchung zuordnen** to allocate an existing positive bank transaction.
Its remaining budget is shared across all linked items. Allocation changes the
outstanding obligation and preserves the original bank transaction in cash flow.
Payment history supports dated reversals with a reason and retained counter-receipt.
Manual payments represent receipts without a bank link; enter each receipt once.

**Finanzen → Sollstellungen → Monate erzeugen** previews active contracts and
creates one stored price snapshot per contract/month, with duplicate protection.
The current policy charges the full agreed month even when the tenancy covers only
part of it; the preview identifies these months for review. Older unbooked months
use current prices and must be reviewed before confirmation.

Utility billing uses paid monthly advances. Finalized statements retain their
values and PDF revisions; corrections post only the difference from the previous
booked chain. Credits are recorded as available; refund reconciliation is a
separate workflow.
Vacancy and non-recoverable costs are shown as owner shares. Missing person or
consumption data for vacancy blocks the affected calculation.

SQLite installations automatically receive the additive payment schema upgrade
on startup. For databases managed by Alembic, run `alembic upgrade head` before
starting the updated application.

## Validation commands

```bash
# Run all backend tests (in-memory store)
pytest backend/tests -q

# Run against SQL store
TEST_STORE_BACKEND=sql pytest backend/tests -q

# Backend lint + scoped type-check
ruff check backend scripts/backup_scheduler.py
# The complete required type-check scope is in .github/workflows/ci.yml.
mypy backend/app.py backend/domain backend/repositories backend/plugins --ignore-missing-imports

# Frontend lint + tests + build
cd frontend && npm ci && npm run lint && npm run test && npm run build
npm run test:e2e
npm run test:e2e -- --fresh-install

# Release smoke
bash scripts/e2e_smoke.sh
python -m py_compile immomanager.spec
```

## API Overview

All endpoints are under `/api/v1`. Full interactive docs at `/docs`.

**Core entities:** portfolios, properties, units, tenants, contracts, accounts, bookings, receivables, invoices, maintenance, documents, tasks, calendar, categories

**Financial:** reports (summary, finance, occupancy, cashflow, receivables-aging, contracts-expiring, maintenance-costs, DATEV export, liquidity forecast), billing, rent charges, rent adjustments, budgets, deposits, tax rates

**Operations:** auth, admin, audit, diagnostics, files (upload/OCR), notifications, notification templates, escalation rules, contacts, insurances, leads, viewings, handover protocols, listings, integrations, meters, search, data exchange, `/health` readiness including contract-wizard status

## Deployment

- Docker and Docker Compose run the FastAPI app under `/api/v1`, serve the built SPA, and include the Mietvertrag-Wizard assets.
- Local Windows builds use the PyInstaller spec and SQLite by default.
- WhatsApp, postal dispatch and external portals are explicitly marked as planned;
  they require a provider implementation and credentials before operational use.
- Production mode (`ENVIRONMENT=production`) fails startup for unsafe defaults such as wildcard CORS, demo seeding, in-memory fallback, or default JWT secrets.

The independent private-server image (`Dockerfile.server` and
`compose.private-server.yml`) installs free local `poppler-utils`, Tesseract,
German/English language data and Pillow. It recognizes scanned PDFs and
PNG/JPEG/TIFF/BMP/WebP locally, without external OCR credentials. The development
`Dockerfile` uses a prebuilt frontend and does not install native OCR tools.

For a desktop installation, install optional Pillow in the application's own
virtual environment (`python -m pip install '.[ocr]'`) and provide local native
Poppler/Tesseract binaries plus `deu`/`eng` language files. The starter persists
OCR settings in `%LOCALAPPDATA%\ImmoManagerPro\.env` (or the selected data
directory). Configure `OCR_PDFINFO_PATH`, `OCR_PDFTOTEXT_PATH`,
`OCR_PDFTOPPM_PATH`, `OCR_TESSERACT_PATH` and `OCR_TESSDATA_PATH` there; blank
tool paths use PATH, and a blank tessdata path uses Tesseract's installed default.
Use native executables rather than Windows batch wrappers, then restart.
`OCR_LANGUAGES` and the time/pixel/page/RAM/temp/text budgets are also preserved
by full local and private-server backups. OCR binaries and language data are
external dependencies: after moving a backup to another host, reinstall them
and adjust paths if necessary. Uploads remain intact when OCR is unavailable.

See [the bounded scanned-PDF contract](docs/SCANNED_PDF_OCR.md) and
[image OCR and recoverable uploads](docs/IMAGE_OCR.md). The independent Linux
CI OCR job requires actual Poppler/Tesseract with `deu+eng`, original hash
checks and process cleanup; missing tools, test failure or skips block that job
and deployment readiness. A passing Windows test does not certify the Linux
job or a newly built desktop executable.

## License

MIT.
