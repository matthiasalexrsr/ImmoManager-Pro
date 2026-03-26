# ImmoManager Pro – Codebase Evaluation & Implementation Plan

> **Note (2026-03):** This document is an archived evaluation from an earlier stage of development. The codebase has since undergone significant changes: SQLAlchemy persistence is now the default backend, 35+ routers exist (up from 17), 33 test files with 780+ tests are in place, JWT auth with RBAC is implemented, full i18n coverage spans 3 locales, and many of the issues and implementation items listed below have been addressed. Refer to `README.md` and `backend/README.md` for the current architecture.

---

## 1. Current State Summary

| Layer | Files | Status |
|-------|-------|--------|
| **Models** (`models.py`) | 16 Pydantic models | Solid, consistent pattern |
| **Storage** (`storage.py`) | 1 InMemoryStore class, 693 lines | Complete CRUD for all entities |
| **Routers** (17 files) | 91+ endpoint functions | Full CRUD for all entities + domain endpoints |
| **Domain Engines** (3 files) | LeaseEngine, DunningEngine, InvoiceMatcher | Well-tested, production-quality logic |
| **Tests** (8 files) | 56 test cases | Domain engines well-covered; routers mostly untested |
| **DB Schema** (`db/schema.sql`) | 13 tables | PostgreSQL schema – not connected to app |
| **i18n** | German locale (de-DE) | Complete UI string catalog |

---

## 2. Bugs & Issues Found

### 2.1 Confirmed Bug

| # | File | Line | Severity | Description |
|---|------|------|----------|-------------|
| B1 | `tests/test_i18n_router.py` | 26 | Low | `Path("i18n") in path.parts` compares a `Path` object against strings in the tuple. Should be `"i18n" in path.parts`. |

### 2.2 Potential Runtime Errors

| # | File | Line | Severity | Description |
|---|------|------|----------|-------------|
| B2 | `routers/contracts.py` | 66 | Medium | `_build_charge_and_payments` uses `store.units.get(contract.unit_id)` which returns `None` if the unit was deleted. Accessing `.cold_rent` on `None` would crash. Should raise 400/404 if unit not found. |
| B3 | `routers/listings.py` | 48 | Medium | `GET /listings/photos` is registered *after* `GET /listings/{listing_id}`. FastAPI tries `{listing_id}="photos"` first, which will 404 from the store before reaching the photos endpoint. The `/photos` route should be registered before the `/{listing_id}` route, or use a separate sub-router. |
| B4 | `storage.py` | 317 | Low | `units[data.unit_id].property_id != data.property_id` check in `create_contract` could be wrong if unit is reassigned. No deep impact with in-memory store. |

### 2.3 Design Smells

| # | File | Description |
|---|------|-------------|
| D1 | `routers/portfolios.py:7` | Global singleton `store = InMemoryStore()` means all tests share state. Tests must manually clear collections – fragile and order-dependent. Should use FastAPI dependency injection. |
| D2 | All routers | No API versioning prefix (`/api/v1/`). The architecture plan calls for it. |
| D3 | All list endpoints | No pagination, filtering, or sorting. Every list endpoint returns the full dataset. |
| D4 | `models.py` | Uses `*Create` models for both create and update. There are no `*Update` (PATCH) models with optional fields, so updates require re-sending all fields (PUT-only). |
| D5 | `storage.py` | Cascade deletes (e.g., `delete_property`) iterate over *all* bookings, invoices, etc. O(n) per entity type – fine for small datasets but won't scale. |
| D6 | `models.py` | Money fields use `float` (e.g., `cold_rent: Optional[float]`). Floating-point arithmetic causes rounding errors in financial calculations. Should use `Decimal` or `int` (cents). |
| D7 | `db/schema.sql` | Schema exists but is not used. No SQLAlchemy models, no Alembic migrations, no database connection. App is fully in-memory. |
| D8 | Reports router | `date.today()` is called at runtime with no way to inject a test date (except `as_of` on the new settlement/dunning endpoints). Makes date-sensitive reports hard to test. |

---

## 3. Test Coverage Analysis

### What's tested well
- **LeaseEngine**: 14 tests covering receivables generation, balance, FIFO allocation, settlement, aging, dashboard, dunning campaign
- **DunningEngine**: 7 tests covering all dunning levels, batch, campaign, custom policy, validation
- **InvoiceMatcher**: 3 tests covering full match, partial match, negative input validation
- **Domain endpoints**: 12 tests covering settlement, dunning, invoice matching via router functions
- **Reports**: 7 tests covering all 7 report endpoints
- **Storage**: 7 tests covering creation validation, cascading deletes, listing flow

### What's NOT tested (50 untested endpoint functions)

| Router | Endpoints | Tests |
|--------|-----------|-------|
| portfolios | 5 (list, create, get, update, delete) | 0 |
| properties | 5 | 0 |
| units | 5 | 0 |
| tenants | 5 | 0 |
| contracts | 5 CRUD | 0 |
| accounts | 5 | 0 |
| bookings | 5 | 0 |
| receivables | 5 | 0 |
| invoices | 5 CRUD | 0 |
| maintenance | 5 | 0 |
| documents | 5 | 0 |
| tasks | 5 | 0 |
| calendar | 5 | 0 |
| categories | 5 | 0 |
| listings | 9 (listing + photo CRUD) | 0 |
| i18n | 2 (manifest + locale) | 3 (1 failing) |

### Critical missing test scenarios
- No tests for update/delete error handling in any CRUD router
- No tests for cascading deletes via router (only tested at storage level)
- No integration tests using FastAPI `TestClient` (all tests call Python functions directly)
- No tests for concurrent access / shared state conflicts

---

## 4. Schema vs. Code Alignment

The SQL schema (`db/schema.sql`) and Pydantic models (`models.py`) are well-aligned, with these differences:

| Difference | Schema | Code |
|-----------|--------|------|
| `created_at` / `updated_at` | Present in all tables | Missing from all Pydantic models |
| `last_synced_at` | In `accounts` table | Missing from `Account` model |
| `appointment_at` type | `timestamptz` in schema | `date` in model (should be `datetime`) |
| `event_time` type | `time` in schema | `str` in model |
| Listings/Photos tables | Missing from schema | Present in code |
| Money fields | `numeric(14,2)` in schema | `float` in models |

---

## 5. Implementation Plan

### Phase 1: Foundations & Bug Fixes (quick wins)

**1.1 Fix known bugs**
- [ ] Fix `test_i18n_dir_is_repo_root`: change `Path("i18n")` to `"i18n"`
- [ ] Add null-check in `_build_charge_and_payments` for missing unit
- [ ] Fix listings route ordering (photos before `{listing_id}`)

**1.2 Add `created_at` / `updated_at` to all models**
- [ ] Add `created_at: datetime` and `updated_at: datetime` fields to all entity models
- [ ] Set defaults in storage on create, update `updated_at` on updates
- [ ] Aligns code with existing DB schema

**1.3 Add `listings` and `listing_photos` tables to schema**
- [ ] Add SQL for `listings` and `listing_photos` tables in `db/schema.sql`

**1.4 Fix float-based money fields**
- [ ] Change `cold_rent`, `service_charge_advance`, `heating_advance`, `amount`, `deposit_amount`, etc. from `float` to `Decimal` in models
- [ ] Or keep as `float` in the API layer but document the limitation

### Phase 2: API Quality & Testing

**2.1 Pagination, filtering, sorting for all list endpoints**
- [ ] Add `skip: int = 0, limit: int = 100` query params to all `GET /` list endpoints
- [ ] Add optional filter params per entity (e.g., `?portfolio_id=`, `?status=`, `?property_id=`)
- [ ] Add `sort_by` query param with direction

**2.2 API versioning**
- [ ] Prefix all routes with `/api/v1`
- [ ] Update `app.py` to mount routers under version prefix

**2.3 Dependency injection for store**
- [ ] Replace global `store` singleton with FastAPI `Depends()` injection
- [ ] Enables clean test isolation without manual `.clear()` calls

**2.4 Comprehensive router tests**
- [ ] Add tests for all 50 untested CRUD endpoint functions
- [ ] Add `TestClient`-based integration tests (HTTP-level testing)
- [ ] Add error-case tests (404, 400 for all routers)
- [ ] Goal: >80% line coverage

**2.5 PATCH (partial update) endpoints**
- [ ] Create `*Update` Pydantic models with all-optional fields
- [ ] Add `PATCH /{entity_id}` endpoints alongside existing `PUT`

### Phase 3: Missing Domain Modules

**3.1 Leads & Viewings (Interessenten/Besichtigungen)**
- [ ] Add `Lead` and `ViewingAppointment` models to `models.py`
- [ ] Add storage methods for CRUD
- [ ] Add `leads.py` and `viewings.py` routers
- [ ] Register in `app.py`
- [ ] Add schema tables
- Complexity: Easy

**3.2 Billing Periods & Utility Statements (Betriebskostenabrechnung)**
- [ ] Add `BillingPeriod`, `AllocationKey`, `UtilityStatement` models
- [ ] Add storage CRUD
- [ ] Add `billing.py` router with:
  - CRUD for billing periods and allocation keys
  - `POST /billing-periods/{id}/generate` to create utility statements
- [ ] Add domain engine `BillingEngine` for cost allocation
- Complexity: Hard (core business logic)

**3.3 Deposits (Kautionsverwaltung)**
- [ ] Add `Deposit` model (amount, status, held_date, return_date, deductions)
- [ ] Add CRUD router
- [ ] Link to contracts
- Complexity: Easy

**3.4 Notifications (Benachrichtigungen)**
- [ ] Add `Notification` model (user, type, content, status, read_at)
- [ ] Add `NotificationTemplate` model
- [ ] Add router for list/mark-read/delete
- [ ] Add event triggers (overdue payment, contract expiry, task due)
- Complexity: Medium

### Phase 4: Database Persistence

**4.1 SQLAlchemy models**
- [ ] Create `backend/db/orm_models.py` with SQLAlchemy 2.0 declarative models
- [ ] Map to existing `db/schema.sql` tables
- [ ] Add Alembic for migrations

**4.2 Repository pattern**
- [ ] Create `backend/repositories/` with one repository per entity
- [ ] Replace `InMemoryStore` methods with repository calls
- [ ] Keep `InMemoryStore` as a test double

**4.3 Database session management**
- [ ] Add `backend/db/session.py` with connection pooling
- [ ] Use FastAPI `Depends()` for session lifecycle
- [ ] Support PostgreSQL (prod) and SQLite (dev/test)

### Phase 5: Security & Operations

**5.1 Authentication**
- [ ] Add `User` model with hashed password
- [ ] Add JWT-based auth (login, refresh, logout)
- [ ] Add auth middleware / `Depends(current_user)`

**5.2 RBAC (Role-Based Access Control)**
- [ ] Add `Role` and `Permission` models
- [ ] Define roles: Eigentümer, Verwalter, Buchhaltung, Techniker, Nur Lesen
- [ ] Add permission checks to all endpoints

**5.3 Audit logging**
- [ ] Add `AuditLog` model (user, action, entity, entity_id, timestamp, diff)
- [ ] Add middleware or decorator to log write operations

**5.4 Docker deployment**
- [ ] Add `Dockerfile` and `docker-compose.yml`
- [ ] Add `.env.example` with configuration template
- [ ] Add `requirements.txt` or `pyproject.toml`

**5.5 CI/CD**
- [ ] Add GitHub Actions workflow: lint (ruff), test (pytest), type-check (mypy)
- [ ] Enforce minimum test coverage

### Phase 6: Advanced Features

**6.1 CSV/PDF export for reports**
- [ ] Add `?format=csv` and `?format=pdf` query params to report endpoints
- [ ] Use `csv` stdlib for CSV, `weasyprint` or `reportlab` for PDF

**6.2 DATEV export**
- [ ] Add `/reports/datev-export` endpoint
- [ ] Generate DATEV-compliant CSV for German tax accounting

**6.3 Bank statement import**
- [ ] Add `POST /bookings/import` for CSV/MT940 import
- [ ] Add matching rules to auto-categorize imported transactions

**6.4 Recurring tasks**
- [ ] Add `recurrence_rule` field to Task model (iCal RRULE format)
- [ ] Add scheduler to auto-create task instances

---

## 6. Priority Matrix

| Priority | Item | Impact | Effort |
|----------|------|--------|--------|
| **P0** | Fix bugs (B1-B3) | High | Small |
| **P0** | Add `requirements.txt` / `pyproject.toml` | High | Small |
| **P1** | Pagination & filtering | High | Medium |
| **P1** | Router test coverage | High | Medium |
| **P1** | Dependency injection for store | Medium | Medium |
| **P1** | API versioning (`/api/v1/`) | Medium | Small |
| **P2** | Leads & Viewings | Medium | Small |
| **P2** | Deposits module | Medium | Small |
| **P2** | Billing periods / utility statements | High | Large |
| **P2** | SQLAlchemy + Alembic | High | Large |
| **P3** | Authentication + RBAC | Critical for prod | Large |
| **P3** | Docker + CI/CD | High for prod | Medium |
| **P3** | Notifications | Medium | Medium |
| **P4** | CSV/PDF export | Medium | Medium |
| **P4** | DATEV export | Medium for German market | Medium |
| **P4** | Bank import | Medium | Large |
| **P4** | Audit logging | Medium for compliance | Medium |

---

## 7. Quick Reference: File Map

```
ImmoManager-Pro/
├── ARCHITEKTURPLAN.md          # Full architecture plan (German)
├── PLAN.md                     # i18n implementation plan (German)
├── EVALUATION.md               # This file
├── .gitignore
├── db/
│   └── schema.sql              # PostgreSQL schema (13 tables, not connected)
├── i18n/
│   ├── manifest.json           # Locale registry
│   ├── de-DE.json              # German UI strings (~850 keys)
│   └── README.md               # i18n documentation
└── backend/
    ├── app.py                  # FastAPI app + router registration
    ├── models.py               # 16 Pydantic model pairs (Create + Entity)
    ├── storage.py              # InMemoryStore (all CRUD logic)
    ├── domain/
    │   ├── lease_engine.py     # Rent settlement, FIFO allocation, aging
    │   ├── dunning_engine.py   # Dunning levels, campaigns, fees
    │   └── invoice_matching.py # Invoice-to-booking FIFO matching
    ├── routers/                # 17 FastAPI routers
    │   ├── portfolios.py       # (also holds global store instance)
    │   ├── properties.py
    │   ├── units.py
    │   ├── tenants.py
    │   ├── contracts.py        # + settlement & dunning endpoints
    │   ├── accounts.py
    │   ├── bookings.py
    │   ├── receivables.py
    │   ├── invoices.py         # + invoice matching endpoint
    │   ├── maintenance.py
    │   ├── documents.py
    │   ├── tasks.py
    │   ├── calendar.py
    │   ├── listings.py         # + listing photos sub-routes
    │   ├── categories.py
    │   ├── reports.py          # 7 report endpoints
    │   └── i18n.py             # Locale file serving
    └── tests/                  # 8 test files, 56 tests
        ├── conftest.py
        ├── test_store.py
        ├── test_lease_engine.py
        ├── test_dunning_engine.py
        ├── test_invoice_matching.py
        ├── test_domain_endpoints.py
        ├── test_reports_router.py
        └── test_i18n_router.py
```
