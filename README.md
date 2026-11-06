# ImmoManager Pro

Full-stack property management application for German real estate portfolios.

- What the current version does, and how to install and update it: [docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md) (German)
- How it is built and how to extend it: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); all documents: [docs/README.md](docs/README.md)

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2 |
| Frontend | React 19, Vite, custom i18n (de-DE / en-US / es-ES) |
| Database | SQLite (dev/test), PostgreSQL (production) |
| Auth | JWT (access + refresh tokens), role-based access control |
| CI | GitHub Actions (lint, type-check, security audit, tests, build) |

## Quick Start

### Windows 11

For a packaged installation, run `ImmoManager-Pro-<version>-Setup-x64.exe`.
The German installer installs for the current user and offers a choice between
the **standalone desktop application** and **using the app in a web browser**.
It remembers that selection for updates and adds direct Start menu entries for
both modes, plus an optional desktop shortcut. No Python, Node.js, installed
browser or WebView2 is needed for the standalone mode: its Qt/Chromium renderer
is included. The application owns and orderly stops its local server. Its
background processes do not leave terminal windows open.

Program files and `%LOCALAPPDATA%\ImmoManagerPro` are separate. Installing a new
version updates the shortcuts to its own payload directory; uninstalling retains
the user's data and backups. See [installer build instructions](packaging/installer/README.md).

For a source checkout, the starter prepares the local development prerequisites:

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
.\start.bat -Mode browser  # use the external browser explicitly
.\start.bat -Console  # explicit maintenance/development console
```

Native macOS and Linux builds use the same desktop window and the explicit
`--mode standalone|browser` choice. Platform requirements, native build targets,
personal data paths and the difference between prepared targets and actual
tested packages are documented in [Desktop platforms](docs/DESKTOP_PLATFORMS.md).
The native workflow is [Desktop packages](.github/workflows/desktop.yml). A
Windows build is not presented as an already tested macOS or Linux application.

While the program runs it makes a verified full backup every day (01:30 Europe/Berlin, or
right after the start when that slot was missed) and a monthly restore probe; see Settings →
System → "Betrieb". A full backup at any time, or nightly via Windows Task Scheduler while the
program is closed:

```powershell
.\.venv\Scripts\python.exe -m backend ops backup
.\.venv\Scripts\python.exe scripts\backup_scheduler.py schedule
```

### Prepared Baden-Württemberg demo

The installer also offers the prepared Baden-Württemberg workspace for the first
start. The two Demo Start menu entries reopen it later in the desktop or browser
mode. It contains eight properties, 46 units, 42 tenancy contracts, 1,068 bookings
and 74 PDF documents, together with invoices, meters, maintenance, billing and
other linked workspaces. The login is **`demo.bw` / `Immo-Demo-BW-2026!`**; the
demo login page can fill it with **Demozugang übernehmen**.

The demo uses its own persistent data folder and port 8766. Changes survive
restarts. The regular workspace uses its own data folder and port 8000. A source
checkout can open the demo with `start.bat -Demo`; native launch options and
platform-specific source requirements are in
[Desktop platforms](docs/DESKTOP_PLATFORMS.md). Linux ARM64 desktop source runs
require Python 3.12 or newer; its native package includes the matching runtime.

### Legacy test version (data set and tutorial)

A separate tester workspace with 15 properties, 93 units and
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
| `TRUSTED_HOSTS` | loopback and configured CORS/portal hosts | Additional exact API/LAN hostnames without scheme, port or wildcard; see [HTTP/auth boundary](docs/HTTP_AUTH_BOUNDARY.md) |
| `ALLOW_SELF_REGISTRATION` | `false` | Allow public sign-up after initial setup; further public accounts are inactive, read-only and have no portfolios until an owner activates and assigns them. The first account on a fresh install is created atomically as owner. Admin-created accounts use *Settings → Users* (or `POST /api/v1/auth/users`) |
| `DIAGNOSTICS_ALLOW_IN_PRODUCTION` | `false` | Enable developer tools (diagnostics, autotest, developer notes) in production |
| `SECURITY_HEADERS_ENABLED` | `true` | Content-Security-Policy, X-Frame-Options, Referrer-Policy, Permissions-Policy, COOP/CORP and, over HTTPS, HSTS on every response |
| `CONTENT_SECURITY_POLICY` | built in | Replaces the built-in Content-Security-Policy (only own origin, no inline script, no eval) |
| `HSTS_MAX_AGE` | `31536000` | Strict-Transport-Security over HTTPS; `0` switches it off |
| `API_DOCS_ENABLED` | on, off in production | Serves `/docs`, `/redoc` and `/openapi.json` |

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

## Messages and personal reminders

Dashboard task, contract-deadline and notice entries open their individual records. Direct links keep the selected record visible even when the surrounding list has different filters. Missing or inaccessible records show an explicit error and retry action.

Under **Einstellungen → Nachrichten / Erinnerungen**, each user can choose the default message channel, reminder channel, lead time, reminder time and quiet hours. The task and contract overviews offer **Nachricht vorbereiten** and **Erinnerung planen**; the personal inbox also offers reminder planning. Plans are private to the user and survive restarts. Their times use **Europe/Berlin**, including daylight-saving changes. ImmoManager must be running to show a due reminder; missed reminders are available when it starts again.

**WhatsApp Web** opens the actual browser login or the chosen chat with an encoded message. **E-Mail-Programm** opens an email draft. The user sends the prepared message in that application. These personal reminder channels do not send unattended messages. Configured SMTP and WhatsApp Business connections retain their existing message-outbox and approval flow under **Verbindungen und Vorgänge**.

The authenticated personal API supports `GET /api/v1/notifications/reminders`, `POST /api/v1/notifications/reminders`, and `POST /api/v1/notifications/reminders/{id}/command` for completion, cancellation and rescheduling. Commands use revisions and idempotency keys. `GET /api/v1/notifications/{id}` returns the current user's notice projection and freshly checks source access; another user's read or archive state is not reused.

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
- Security: see [SECURITY.md](SECURITY.md) (reporting a vulnerability, supported versions, what the application protects and what the operator configures) and [docs/AI_READING_SECURITY_20261025.md](docs/AI_READING_SECURITY_20261025.md).
- Schema updates are explicit: `python -m backend.upgrade` (Windows package: `ImmoManager-Pro-CLI.exe upgrade`) takes a verified full backup first, then runs the migrations. The application server initialises an empty database and refuses an existing one that is behind the Alembic head. The desktop launcher (`python -m backend`, the `.exe`, `start.bat`) and Docker entrypoint invoke the explicit upgrade step before starting the server. Databases created by older desktop versions without Alembic are adopted by that step. Customer HTTP source updates and live raw-database restore are disabled; use the installer and offline full restore into a new data directory.
- Full backups (database, uploads, configuration, keys), the monthly restore probe, the second backup target and key handling: [docs/OPERATIONS_BACKUP_SECRETS_20261008.md](docs/OPERATIONS_BACKUP_SECRETS_20261008.md).
- Reproducible installs: `pip install -r requirements.txt -c constraints.txt`, `npm ci`; Docker base images are pinned by digest.

## Releases and updates

- **Making a release:** set the version in `pyproject.toml` and update the German [release notes](docs/RELEASE_NOTES.md). CI, **Native desktop packages** and **Release hardening and persistence** must pass on exactly that commit. The native workflow tests and packages Windows x64, macOS Intel/ARM64 and Linux x64/ARM64, including the prepared demo. Manually run **Release (native desktop platforms)** on the accepted branch, select publication and the exact `v<version>` tag. The release workflow verifies all three matching run IDs, package bytes, complete runtime and worker acceptance, full Qt source sidecars and checksums before publishing. Existing releases and tags are not overwritten. A normal manual run defaults to artifacts only; an unsigned `beta.N` publication requires its explicit beta option. Customer publication additionally requires real publisher signatures and macOS notarization with acceptance of the final signed packages. Signing requirements and the full process are documented in [Commercial release](docs/COMMERCIAL_RELEASE.md).
- **Updating an installation:** Settings → System → Updates → **Jetzt prüfen** reads this repository's releases on request. First verify a full backup and the package's provenance/signature, then close the application completely. On Windows, run the new setup to update the program and its shortcuts while retaining the regular and demo workspaces. For a portable package, unpack into a new folder and start the new executable. Personal data remains outside the program directory; an explicit database upgrade takes a verified backup first. The HTTP API never replaces customer source code, including when an old `UPDATE_ALLOW_IN_PRODUCTION` flag is set. The separate source developer CLI requires explicit opt-in, a version tag and the exact expected commit; it is an offline SQLite deployment tool. See [backup and operations](docs/OPERATIONS_BACKUP_SECRETS_20261008.md) and the [HTTP/auth boundary](docs/HTTP_AUTH_BOUNDARY.md).

## License

MIT.
