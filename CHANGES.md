# ImmoManager Pro — Change Log & Hardening Documentation

## 2026-03-04: Implementation Plan Fixes (Phase 1-6)

### Phase 1: Navigation & Contracts
- Added `CategoryIcon` and `DepositIcon` SVG components to `Icons.jsx`
- Added Categories and Deposits entries to sidebar navigation in `Layout.jsx`
- Fixed Contracts.jsx: replaced 3 silent `.catch(() => [])` with logged warnings
- Added missing `index_rent` and `service_charge_settlement` fields to Contracts form

### Phase 2: FormModal & CrudPage Bug Fixes
- **FormModal**: Fixed empty number fields sending `0` instead of `null` — now properly returns `null` for empty optional number fields
- **CrudPage**: Added try-catch to `handleDelete` with dismissible error banner — delete errors are now visible to users

### Phase 3: Backend MeterReading Endpoints
- Added `update_meter_reading()` method to `SQLAlchemyStore`
- Added `PUT /{protocol_id}/meter-readings/{reading_id}` endpoint for full updates
- Added `PATCH /{protocol_id}/meter-readings/{reading_id}` endpoint for partial updates
- Imported `MeterReadingPatch` model in handover protocols router

### Phase 4: Missing Frontend Fields
- Added `features` field to Units.jsx form (Ausstattung)
- Added required `label` field to Statements.jsx billing period form
- Fixed 4 silent catches in Statements.jsx with logged warnings

### Phase 5-6: SearchBar, Login & Auth Safety
- Expanded SearchBar `ENTITY_ROUTES` with 6 additional entity types (account, booking, maintenance, document, contact, portfolio)
- Added password complexity hint on Login registration form
- Wrapped auth preferences GET endpoint in try-except with fallback to defaults

---

## 2026-03-04: Software Hardening & Error Resilience

### Summary

Comprehensive hardening of both backend and frontend to add fallback pathways,
structured error handling, and extensive error documentation. Zero silent
failures — every error is now logged with context for debugging.

---

### Backend Changes

#### New: `backend/error_helpers.py` — Supporting Logic Module

| Export                   | Purpose                                                      |
|--------------------------|--------------------------------------------------------------|
| `ERROR_CATALOG`          | Complete error code documentation (code, description, HTTP status, recovery advice) |
| `DatabaseOperationError` | Typed exception for database failures with operation context  |
| `safe_db_operation()`    | Decorator wrapping functions with SQLAlchemy error handling   |
| `safe_parse_decimal()`   | Converts any value to `Decimal` safely, with fallback        |
| `safe_get_related()`     | Fetches related entities returning `None` instead of raising  |

**Error Codes Documented:**
- `NOT_FOUND` (404) — Resource not found
- `VALIDATION_ERROR` (400/422) — Input validation failed
- `AUTH_FAILED` (401) — Authentication failed
- `PERMISSION_DENIED` (403) — Insufficient role
- `CONFLICT` (409) — Duplicate key / data conflict
- `RATE_LIMITED` (429) — Too many requests
- `DB_ERROR` (500) — Database operation failed
- `INTERNAL_ERROR` (500) — Unexpected server error

#### Updated: `backend/repositories/base.py` — Database Layer Hardening

- All CRUD methods (`list_all`, `get`, `create`, `update`, `patch`, `delete`,
  `filter_by`) now wrapped with `@safe_db_operation`
- SQLAlchemy `IntegrityError` → logged + `DatabaseOperationError` with
  user-friendly message about duplicate entries / invalid references
- SQLAlchemy `OperationalError` → logged + message about DB connection
- Generic `SQLAlchemyError` → logged + generic DB error
- `_to_pydantic()` failures are now logged with model name context
- `_orm_to_dict()` failures are logged before re-raising

#### Updated: `backend/exceptions.py` — Global Exception Handlers

- Added `DB_ERROR` and `RATE_LIMITED` to `ErrorCode` enum
- New handler for `DatabaseOperationError` → returns 500 with `DB_ERROR` code
- Added handler for HTTP 429 → `RATE_LIMITED` code
- Improved docstring documenting the full exception hierarchy

#### Updated: `backend/dependencies.py` — Initialization Fallbacks

- SQL backend initialization wrapped in `try/except` with fallback to
  `InMemoryStore` — app always starts even if DB is unreachable
- `cleanup_session()` now catches exceptions during session removal
- `get_db()` now catches and logs exceptions, calls `rollback()` before re-raising
- All fallback paths logged with context for debugging

#### Updated: `backend/app.py` — Middleware Hardening

- `AuditMiddleware.dispatch()`: `log_action()` wrapped in `try/except` —
  audit failures no longer crash the request (logged as warning)

#### Updated: `backend/routers/billing.py` — Business Logic Hardening

- Unit cache population: replaced silent `except: pass` with logged warning
  identifying which unit/contract failed — missing units are now traceable

#### Updated: `seed_data.py` — Seed Script Fixes

- Demo password changed from `demo123` to `Demo1234` (meets password policy:
  min 8 chars + uppercase)
- Error handling now distinguishes "user exists" (409) from password policy
  failure, showing actual error message instead of misleading "existiert bereits"

---

### Frontend Changes

#### Updated: `frontend/src/api.js` — API Client Hardening

- **Retry logic**: Network errors (`TypeError: Failed to fetch`) are retried
  up to 2 times with exponential backoff (1s, 2s)
- **Network error distinction**: New `networkError()` creates errors with
  `.isNetwork = true`, `.code = 'NETWORK_ERROR'`, and German user message
- **Structured errors**: `parseApiError()` now attaches `.statusCode` and
  `.isNetwork` to all error objects
- **Token refresh logging**: Refresh failures now logged to console instead
  of silently swallowed
- **Safe JSON parsing**: Success response JSON parse failure returns `null`
  with console warning instead of crashing
- **Login/register**: Use `fetchWithRetry()` for network resilience

#### Updated: `frontend/src/hooks/useApi.js` — Hook Hardening

- **Unmount safety**: `mountedRef` prevents `setState` after component unmount
- **Cancellation**: Each effect returns cleanup that sets `cancelled = true`
- **Array safety**: `useList` validates response is array, falls back to `[]`

#### Updated: Silent Catch Blocks — 16 Files Fixed

Every `catch(() => {})` and `catch { /* ignore */ }` replaced with
`catch(err => console.warn(...))` with context tag:

| File                           | What was silent                          |
|--------------------------------|------------------------------------------|
| `PreferencesContext.jsx`       | Preference load/save (4 instances)        |
| `Dashboard.jsx`                | All 16 API calls (→ `safeFetch` helper)  |
| `NotificationBell.jsx`         | Notification fetch, mark-read (3)         |
| `Units.jsx`                    | Properties dropdown load                  |
| `Properties.jsx`               | Portfolios dropdown load                  |
| `Maintenance.jsx`              | Properties dropdown load                  |
| `Bookings.jsx`                 | Accounts dropdown load                    |
| `Accounts.jsx`                 | Portfolios dropdown load                  |
| `Meters.jsx`                   | Meter data load                           |
| `Messages.jsx`                 | Notifications load + mark-read            |
| `i18n.jsx`                     | Locale file fetch                         |

#### Updated: `frontend/src/pages/Login.jsx`

- Password `minLength` updated from 6 to 8 to match backend policy

#### Updated: `frontend/src/index.css` — Modal Scroll Fix

- Added `.modal > form` flex rules so form-based modals scroll properly
  when content exceeds viewport height

---

### Architecture Notes

**Error Flow (Backend):**
```
Router endpoint
  → calls store/repository method
    → @safe_db_operation catches SQLAlchemy errors
      → raises DatabaseOperationError
        → global exception handler returns { error: { code: "DB_ERROR", ... } }
```

**Error Flow (Frontend):**
```
Component calls api.get/post/...
  → fetchWithRetry: retries network errors 2x
    → request(): handles 401 refresh, parses errors
      → on failure: Error with .code, .isNetwork, .statusCode, .requestId
        → useList/useDetail: sets error state (safe on unmount)
          → Component renders error message
```

**Fallback Strategy:**
- Backend: SQL init fails → InMemoryStore (app still starts)
- Backend: Audit log fails → warning logged, request completes
- Backend: Related entity fetch fails → `safe_get_related` returns None
- Frontend: Network error → retry 2x, then show German network error message
- Frontend: Dropdown data fails → empty dropdown, warning in console
- Frontend: Dashboard data fails → section shows "no data" fallback
