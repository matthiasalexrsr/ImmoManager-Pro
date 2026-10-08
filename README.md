# ImmoManager Pro

Full-stack property management application for German real estate portfolios.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2 |
| Frontend | React 18, Vite, custom i18n (de-DE / en-US / es-ES) |
| Database | SQLite (dev/test), PostgreSQL (production) |
| Auth | JWT (access + refresh tokens), role-based access control |
| CI | GitHub Actions (lint, type-check, security audit, tests, build) |

## Quick Start

### Windows 11

Double-click `start.bat` or run:

```powershell
.\start.bat
```

The starter checks Python 3.11+, creates `.venv` when needed, installs the backend, builds the frontend when `frontend/dist` is missing, generates a persistent local secret, and stores runtime data under `%LOCALAPPDATA%\ImmoManagerPro` by default:

- SQLite database: `%LOCALAPPDATA%\ImmoManagerPro\immo_manager.db`
- Uploads: `%LOCALAPPDATA%\ImmoManagerPro\uploads`
- Backups: `%LOCALAPPDATA%\ImmoManagerPro\backups`
- Logs: `%LOCALAPPDATA%\ImmoManagerPro\logs`

Useful variants:

```powershell
.\start.bat -Port 9000
.\start.bat -Seed
.\start.bat -DataDir D:\ImmoManagerProData
```

While the program runs it makes a verified full backup every day (01:30 Europe/Berlin, or
right after the start when that slot was missed) and a monthly restore probe; see Settings →
System → "Betrieb". A full backup at any time, or nightly via Windows Task Scheduler while the
program is closed:

```powershell
.\.venv\Scripts\python.exe -m backend ops backup
.\.venv\Scripts\python.exe scripts\backup_scheduler.py schedule
```

### Test version (data set and tutorial)

A version for testers with a realistic, fictitious data set: 15 properties, 93 units and
three years of history, built through the app's API on the first start
(`backend/testversion`). Master logins: `linda_reiser@web.de` and `mat.thias@online.de`,
plus four staff users for the roles; start password `Immo-Test-2026`. A guided tour
(question mark in the top bar) shows the main functions.

```bash
python -m backend --testversion            # own data folder, data set on the first start
```

The Windows package (`ImmoManager-Pro.exe` with `.env` and instructions, as ZIP) is built by
the workflow "Testversion (Windows)": change `packaging/testversion/VERSION` or start it by
hand; the ZIP is attached to the run as an artifact.

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
| `JWT_SECRET_KEY` | `dev-secret-key-change-in-production` | Secret key for JWT token signing; must be overridden in production (startup fails on the default); use at least 32 random characters (shorter ones are reported at startup). Changing it signs all users out |
| `ENVIRONMENT` | `development` | `development` or `production` |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Allowed CORS origins |
| `ALLOW_SELF_REGISTRATION` | `false` | Allow public sign-up after initial setup; self-registered accounts are always read-only. The first account on a fresh install is always created as owner, further accounts are created by an admin under *Settings → Users* (or `POST /api/v1/auth/users`) |
| `DIAGNOSTICS_ALLOW_IN_PRODUCTION` | `false` | Enable developer tools (diagnostics, autotest, developer notes) in production |

## Testing

```bash
# Install runtime + dev dependencies first
pip install -r backend/requirements-dev.txt mypy

# Run all backend tests (in-memory store)
pytest backend/tests -q

# Run against SQL store
TEST_STORE_BACKEND=sql pytest backend/tests -q

# Backend lint + type-check
ruff check backend
mypy backend

# Frontend lint + tests + build
cd frontend && npm ci && npm run lint && npm run test && npm run build

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
- External portal integrations are modeled through adapter interfaces/placeholders until real credentials are provided.
- Production mode (`ENVIRONMENT=production`) fails startup for unsafe defaults such as wildcard CORS, demo seeding, in-memory fallback, or default JWT secrets.
- Schema updates are explicit: `python -m backend.upgrade` (Windows package: `ImmoManager-Pro.exe upgrade`) takes a verified full backup first, then runs the migrations. The normal start never changes an existing schema: it initialises an empty database and refuses one that is behind the Alembic head. The desktop launcher (`python -m backend`, the `.exe`, `start.bat`), the Docker entrypoint, `scripts/update.sh` and the in-app updater run the explicit step for you. Databases created by older desktop versions without Alembic are adopted by that step.
- Full backups (database, uploads, configuration, keys), the monthly restore probe, the second backup target and key handling: [docs/OPERATIONS_BACKUP_SECRETS_20261008.md](docs/OPERATIONS_BACKUP_SECRETS_20261008.md).
- Reproducible installs: `pip install -r requirements.txt -c constraints.txt`, `npm ci`; Docker base images are pinned by digest.

## License

MIT.
