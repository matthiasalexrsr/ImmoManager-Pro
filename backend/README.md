# ImmoManager Pro Backend

FastAPI backend for ImmoManager Pro with SQLAlchemy persistence, JWT auth, and 45+ API routers.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Start

```bash
uvicorn backend.app:app --reload
```

API docs: `http://localhost:8000/docs`

## Architecture

### Persistence

The default storage backend is **SQLAlchemy** with SQLite (dev) or PostgreSQL (production). An in-memory fallback exists for rapid prototyping and is used by the test suite's default configuration.

The store is selected at startup in `dependencies.py`:
- `SQLITE_PERSISTENT_STORE=true` (default) -> SQLAlchemyStore
- `SQLITE_PERSISTENT_STORE=false` + `ALLOW_INMEMORY_FALLBACK=true` -> InMemoryStore

### Authentication

JWT-based authentication with access/refresh token pairs. Role-based access control (admin/user). Registration rate-limited per IP. Managed via `/api/v1/auth/*` endpoints.

### Key Modules

| Module | Purpose |
|--------|---------|
| `routers/` | 45+ FastAPI router modules for all entities |
| `domain/` | Business engines: LeaseEngine, DunningEngine, InvoiceMatcher, BillingEngine, PropertyEngine |
| `services/` | Report calculations, OCR, file storage, integrations, email |
| `repositories/` | SQLAlchemy-backed CRUD (BaseRepository pattern) |
| `db/orm_models.py` | 35+ SQLAlchemy ORM models with indexes and constraints |
| `db/migrations/` | Alembic database migrations |

## Endpoints

All endpoints are prefixed with `/api/v1`. Interactive docs at `/docs`.

### Core CRUD
Each resource supports `GET` (list), `POST` (create), `GET /{id}`, `PUT /{id}`, `DELETE /{id}`:

portfolios, properties, units, tenants, contracts, accounts, bookings, receivables, invoices, maintenance, documents, tasks, calendar, categories

### Reports
- `GET /reports/summary` - Key metrics overview
- `GET /reports/finance` - Bookings by category
- `GET /reports/occupancy` - Occupancy rates
- `GET /reports/cashflow` - Income/expense/net
- `GET /reports/receivables-aging` - Open receivables by age bucket
- `GET /reports/contracts-expiring?days=90` - Expiring contracts
- `GET /reports/maintenance-costs` - Costs by category
- `GET /reports/datev-export` - DATEV Buchungsstapel CSV export
- `GET /reports/liquidity-forecast` - Multi-month balance projection
- `GET /reports/pdf/{name}` - PDF report export
- `POST /reports/bookings/import` - Bank statement CSV import

### Additional
- `POST /auth/login`, `/auth/register`, `/auth/refresh` - Authentication
- `GET /admin/*` - Admin operations, backup/restore
- `GET /diagnostics/*` - Data integrity checks
- `GET /files/*` - File upload, download, OCR
- `GET /i18n/{locale}` - Locale strings
- `GET /billing/*` - Utility billing periods and statements
- CRUD for: contacts, deposits, handover protocols, insurances, leads, listings, viewings, budgets, rent adjustments, rent charges, tax rates, escalation rules, notifications, meters

## Testing

```bash
# Default (in-memory store)
pytest backend/tests -q

# SQL store path
TEST_STORE_BACKEND=sql pytest backend/tests -q

# With coverage
pytest backend/tests -q --cov=backend --cov-report=term-missing
```

33 test files, 780+ tests, covering CRUD operations, domain engines, billing workflows, e2e flows, auth, and reports.
