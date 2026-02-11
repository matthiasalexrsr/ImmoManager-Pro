# ImmoManager Pro – Comprehensive Implementation Plan

## Scope

This plan covers eight feature areas, organized into four implementation phases:

1. **Updateability** – Version management, auto-migration, self-update
2. **Plugin Support** – Extension architecture, dynamic router loading, hooks
3. **Advanced Error Logging & Handling** – Structured logging, global handlers, error tracking
4. **Spanish Language Support** – i18n framework integration, locale management
5. **Interface Customization** – Theming, layout preferences, user settings
6. **Database Integrity** – Constraints, referential checks, backup/restore
7. **Data Persistence** – Session reliability, auto-save, export/import
8. **Practical Features** – Search, notifications, dashboard widgets, bulk operations

---

## Phase 1: Foundation (Error Handling, Logging, Config, DB Integrity)

These are infrastructure concerns that every subsequent feature depends on.

### 1.1 Centralized Configuration Module

**Problem:** Config is scattered across files using raw `os.getenv()` calls with no validation.

**Plan:**
- Create `backend/config.py` using `pydantic-settings.BaseSettings`
- Consolidate all environment variables into one typed, validated Settings class:
  ```
  class Settings(BaseSettings):
      database_url: str = "sqlite:///./immo_manager.db"
      jwt_secret_key: str  # no default → forces production config
      access_token_expire_minutes: int = 30
      refresh_token_expire_days: int = 7
      cors_origins: list[str] = ["http://localhost:3000"]
      log_level: str = "INFO"
      log_format: str = "json"  # "json" or "text"
      log_file: str | None = None
      app_version: str  # read from pyproject.toml
      default_locale: str = "de-DE"
      plugin_dirs: list[str] = []
      model_config = SettingsConfigDict(env_file=".env")
  ```
- Replace all inline `os.getenv()` calls with `settings.xxx`
- Add `GET /api/v1/config/public` endpoint for frontend-safe config (version, locale, features)

**Files:** `backend/config.py` (new), `backend/app.py`, `backend/auth.py`, `backend/db/session.py`, `backend/dependencies.py`

### 1.2 Structured Logging

**Problem:** Only 2 logger calls exist. No structured logging, no log files, no request correlation.

**Plan:**
- Create `backend/logging_config.py`:
  - Configure Python `logging` with JSON formatter (for production) and colored text formatter (for dev)
  - Log levels controlled by `settings.log_level`
  - Optional file handler via `settings.log_file`
  - Add `RequestContextFilter` that injects `request_id`, `user_id`, `method`, `path` into every log record
- Add `RequestIDMiddleware` to `app.py`:
  - Generates UUID per request, stores in `request.state.request_id`
  - Adds `X-Request-ID` response header
  - Logs request start/end with timing
- Add module-level loggers to all routers and domain engines:
  - `logger = logging.getLogger(__name__)`
  - Log at DEBUG for operations, WARNING for recoverable issues, ERROR for failures
- Log rotation: use `RotatingFileHandler` (10MB, 5 backups) when `log_file` is set

**Files:** `backend/logging_config.py` (new), `backend/app.py` (middleware), all routers (add loggers)

### 1.3 Global Error Handling

**Problem:** No `@app.exception_handler()`, no error codes, inconsistent error formats, no frontend error boundary.

**Plan:**

**Backend:**
- Create `backend/exceptions.py`:
  - Define error code enum: `ErrorCode.NOT_FOUND`, `VALIDATION_ERROR`, `AUTH_FAILED`, `PERMISSION_DENIED`, `CONFLICT`, `INTERNAL_ERROR`
  - Standardize error response schema:
    ```json
    {
      "error": {
        "code": "VALIDATION_ERROR",
        "message": "Enddatum muss nach Startdatum liegen",
        "details": [{"field": "end_date", "message": "..."}],
        "request_id": "abc-123"
      }
    }
    ```
- Register global exception handlers in `app.py`:
  - `NotFoundError` → 404 with `NOT_FOUND` code
  - `ValidationError` → 400/422 with `VALIDATION_ERROR` code + field details
  - `UnauthorizedError` → 401 with `AUTH_FAILED` code
  - `Exception` → 500 with `INTERNAL_ERROR` code, log full traceback, sanitize response
- Remove try/except blocks from individual router endpoints (handled globally)
- Add `@app.on_event("startup")` health checks (DB connectivity, migration status)

**Frontend:**
- Create `frontend/src/components/ErrorBoundary.jsx`:
  - React Error Boundary catches render crashes
  - Shows user-friendly German error page with reload button
- Update `api.js` error handling:
  - Parse standardized error response format
  - Extract `error.code`, `error.message`, `error.details`
  - Show field-level validation errors in forms
- Add toast notification system for transient errors

**Files:** `backend/exceptions.py` (new), `backend/app.py`, all routers (simplify), `frontend/src/components/ErrorBoundary.jsx` (new), `frontend/src/api.js`

### 1.4 Database Integrity Enhancements

**Problem:** No CHECK constraints, no unique constraints beyond PKs, no backup/restore, limited FK enforcement.

**Plan:**
- **ORM Constraints** (`backend/db/orm_models.py`):
  - Add `UniqueConstraint` where needed:
    - `ContractORM`: unique `contract_number`
    - `UserORM`: unique `username`, unique `email`
    - `AccountORM`: unique `iban` (when not NULL)
  - Add `CheckConstraint` for business rules:
    - `BookingORM`: `amount != 0`
    - `UnitORM`: `area_sqm > 0` (when not NULL)
    - `ContractORM`: `end_date > start_date` (when both set)
  - Add composite indexes for common queries:
    - `(property_id, status)` on units
    - `(account_id, booking_date)` on bookings
    - `(tenant_id, status)` on contracts

- **Migration** (`alembic/`):
  - Generate new migration for constraint additions
  - Add data validation script that runs pre-migration to flag violations

- **Backup/Restore** (`backend/routers/admin.py` new):
  - `POST /api/v1/admin/backup` → Creates timestamped SQLite dump or pg_dump
  - `POST /api/v1/admin/restore` → Restores from backup file (admin-only)
  - `GET /api/v1/admin/backups` → Lists available backups
  - Automatic daily backup via optional cron/scheduler

- **Integrity Check Endpoint**:
  - `GET /api/v1/admin/integrity-check` → Runs foreign key checks, orphan detection, constraint validation
  - Returns report of any data inconsistencies

**Files:** `backend/db/orm_models.py`, new migration, `backend/routers/admin.py` (new)

---

## Phase 2: Internationalization & Interface Customization

### 2.1 i18n Framework Integration

**Problem:** Backend i18n API exists with `de-DE.json`, but frontend has all strings hardcoded.

**Plan:**

**Backend:**
- Add `es-ES.json` locale file with full Spanish translations (copy structure from `de-DE.json`)
- Add `en-US.json` as fallback/base locale
- Extend `i18n/manifest.json` with new locales
- Add locale-aware error messages:
  - Validation errors return message keys (e.g., `"validation.end_date_before_start"`)
  - Frontend resolves keys to localized strings
- Add `Accept-Language` header support in middleware:
  - Detect preferred locale from request
  - Store in `request.state.locale`
  - Used by error messages and server-rendered content

**Frontend:**
- Install `react-i18next` + `i18next` + `i18next-http-backend`
- Create `frontend/src/i18n.js` configuration:
  - Load translations from `/i18n/{locale}` API endpoint
  - Fallback chain: `es-ES` → `de-DE` → `en-US`
  - Lazy loading per locale
- Create `useTranslation()` hook wrapper for convenience
- Replace all hardcoded strings in components:
  - `Layout.jsx`: Navigation labels
  - `Login.jsx`: Form labels, buttons, messages
  - `Dashboard.jsx`: Stat labels, panel titles
  - `CrudPage.jsx`: "Neu", "Bearbeiten", "Löschen", "Suche..."
  - `FormModal.jsx`: "Speichern", "Abbrechen", field labels
  - `DataTable.jsx`: "Keine Einträge", search placeholder
  - All entity pages: Column headers, form field labels, select options
- Date/number formatting via `Intl.DateTimeFormat` and `Intl.NumberFormat` with locale
- Add locale switcher component in sidebar footer

**Locale Files Structure:**
```
i18n/
  manifest.json          # lists available locales
  de-DE.json            # German (existing, expand)
  es-ES.json            # Spanish (new)
  en-US.json            # English fallback (new)
```

**Files:** `frontend/src/i18n.js` (new), `i18n/es-ES.json` (new), `i18n/en-US.json` (new), all frontend components

### 2.2 Spanish Language Support

**Implementation:** Part of 2.1 above. Specific tasks:
- Translate all ~200 i18n keys from `de-DE.json` to Spanish
- Include Spanish date/currency formatting (dd/mm/yyyy, €/currency)
- Test all pages with `es-ES` locale active
- Verify form validation messages in Spanish
- Ensure special characters (ñ, á, é, í, ó, ú, ¿, ¡) render correctly

### 2.3 Interface Customization

**Problem:** Single fixed theme, no user preferences, no layout options.

**Plan:**

**Backend – User Preferences:**
- Add `UserPreferencesORM` model:
  ```
  user_id: str (FK → users.id)
  theme: str = "light"         # "light", "dark", "system"
  locale: str = "de-DE"        # user's preferred language
  sidebar_collapsed: bool = False
  dashboard_layout: JSON = {}  # widget order/visibility
  items_per_page: int = 25
  date_format: str = "DD.MM.YYYY"
  currency: str = "EUR"
  ```
- Add `GET/PUT /api/v1/users/me/preferences` endpoint
- Include preferences in login response token payload or separate call

**Frontend – Theme System:**
- Extend CSS custom properties for dark theme:
  ```css
  [data-theme="dark"] {
    --color-bg: #0f172a;
    --color-surface: #1e293b;
    --color-text: #e2e8f0;
    --color-border: #334155;
    /* ... */
  }
  ```
- Create `frontend/src/contexts/PreferencesContext.jsx`:
  - React Context providing user preferences
  - Persists to backend on change, localStorage as cache
  - Applies `data-theme` attribute to `<html>`
- Theme toggle in sidebar footer (sun/moon icon)
- Sidebar collapse toggle (hamburger icon)
- Dashboard widget customization:
  - Drag-and-drop widget reordering (optional, could use simple toggle)
  - Show/hide specific stat cards
  - Save layout to preferences

**Files:** `backend/db/orm_models.py` (UserPreferencesORM), `backend/routers/users.py` (preferences endpoints), `frontend/src/contexts/PreferencesContext.jsx` (new), `frontend/src/index.css` (dark theme), `frontend/src/components/Layout.jsx` (theme toggle)

---

## Phase 3: Plugin Architecture & Updateability

### 3.1 Plugin System

**Problem:** All routers are statically imported. No way to add functionality without modifying core code.

**Plan:**

**Plugin Discovery & Loading:**
- Create `backend/plugins/` package:
  - `__init__.py`: Plugin manager
  - `base.py`: Abstract `Plugin` class
  ```python
  class Plugin(ABC):
      name: str
      version: str
      description: str

      @abstractmethod
      def register_routes(self, app: FastAPI, prefix: str) -> None: ...

      def on_startup(self) -> None: ...
      def on_shutdown(self) -> None: ...
      def get_migrations_dir(self) -> Path | None: ...
      def get_locale_dir(self) -> Path | None: ...
  ```

**Plugin Structure (convention):**
```
plugins/
  my_plugin/
    __init__.py          # exports Plugin subclass
    plugin.py            # Plugin implementation
    routers/             # FastAPI routers
    models.py            # Pydantic models
    orm_models.py        # SQLAlchemy models (optional)
    migrations/          # Alembic migrations (optional)
    i18n/                # Locale files (optional)
    frontend/            # React components (optional, advanced)
```

**Plugin Manager:**
- Scan `settings.plugin_dirs` for Python packages with `Plugin` subclass
- Validate plugin compatibility (required API version)
- Register plugin routes under `/api/v1/plugins/{plugin_name}/`
- Run plugin migrations separately
- Merge plugin locale files into i18n manifest

**Event Bus (for plugin communication):**
- Create `backend/events.py`:
  - Simple pub/sub event system
  - Events: `entity.created`, `entity.updated`, `entity.deleted`, `auth.login`, `auth.logout`
  - Plugins subscribe to events and react
  - Synchronous dispatch (async optional later)

**Built-in Hook Points:**
- Pre/post create, update, delete hooks on store operations
- Middleware hooks for request/response processing
- Dashboard widget registration for plugins

**Plugin API:**
- `GET /api/v1/plugins` → List installed plugins
- `POST /api/v1/plugins/{name}/enable` → Enable plugin
- `POST /api/v1/plugins/{name}/disable` → Disable plugin

**Files:** `backend/plugins/` (new package), `backend/events.py` (new), `backend/app.py` (dynamic loading), `backend/config.py` (plugin_dirs)

### 3.2 Updateability

**Problem:** No version endpoint, version mismatch between pyproject.toml and app.py, no auto-migration, no update strategy.

**Plan:**

**Version Management:**
- Single source of truth: read version from `pyproject.toml` at startup
- Sync FastAPI `app.version` with package version
- Add `GET /api/v1/version` endpoint:
  ```json
  {
    "version": "1.1.0",
    "api_version": "v1",
    "python_version": "3.11.x",
    "database": "sqlite",
    "plugins": [{"name": "...", "version": "..."}],
    "migrations_current": true
  }
  ```

**Auto-Migration on Startup:**
- In `backend/app.py` startup event:
  - Check if pending Alembic migrations exist
  - If `AUTO_MIGRATE=true` (env var), run `alembic upgrade head` automatically
  - If not, log a warning with instructions
  - Run plugin migrations after core migrations
- Add migration status to health endpoint:
  ```json
  {"status": "ok", "migrations_pending": 0}
  ```

**Database Schema Versioning:**
- Store app version in DB metadata table: `schema_version`
- On startup, compare app version with DB version
- If mismatch: warn or auto-migrate

**Update Script** (`scripts/update.sh`):
```bash
#!/bin/bash
# 1. Pull latest code
# 2. Install/update dependencies
# 3. Build frontend
# 4. Run migrations
# 5. Restart server
```

**Changelog:**
- Maintain `CHANGELOG.md` with semantic versioning
- Auto-generate from git tags/commits (optional)

**Files:** `backend/app.py` (startup migration), `scripts/update.sh` (new), `CHANGELOG.md` (new), version endpoint in `backend/routers/admin.py`

---

## Phase 4: Data Persistence & Practical Features

### 4.1 Data Persistence Enhancements

**Problem:** InMemoryStore loses data on restart. SQLite default works but no backup strategy. No import/export.

**Plan:**

**Default to SQLite Persistence:**
- Change `dependencies.py` to always use SQLAlchemy store (even without `DATABASE_URL`)
- Default `DATABASE_URL = "sqlite:///./immo_manager.db"` (already in session.py)
- Run auto-migration on first startup to create tables
- Remove InMemoryStore from production path (keep for tests only)

**Data Export/Import:**
- `GET /api/v1/admin/export` → Full database export as JSON
  - Includes all entities with relationships
  - Preserves IDs for re-import
  - Streaming response for large datasets
- `POST /api/v1/admin/import` → Import from JSON export
  - Validates schema before import
  - Option: merge or replace
  - Transaction-based: all-or-nothing
- CSV export per entity (already partially exists in reports)

**Auto-Save / Draft Support:**
- Frontend: Debounced auto-save for form data to `localStorage`
- On page reload: restore unsaved form data with "Entwurf wiederherstellen?" prompt
- Backend: Optional `status: "draft"` for entities that support it

**Session Reliability:**
- Frontend: Token refresh before expiry (background timer)
- Offline detection: Queue failed API calls, retry when back online
- Optimistic updates: Update UI immediately, reconcile with server response

**Files:** `backend/dependencies.py`, `backend/routers/admin.py` (export/import), frontend components (auto-save)

### 4.2 Practical Features

**Global Search:**
- `GET /api/v1/search?q=Kastanienallee` endpoint
- Searches across: properties (name, street, city), tenants (name, email), contracts (number), units (label)
- Returns unified results with entity type, id, display text, relevance
- Frontend: Search bar in top of sidebar or header
  - Keyboard shortcut: Ctrl+K
  - Dropdown results with entity type icons
  - Navigate to entity on selection

**Enhanced Notifications:**
- Expand notification system with scheduled checks:
  - Contract expiry warnings (30/60/90 days before end_date)
  - Overdue invoice alerts
  - Maintenance case reminders
  - Task due date notifications
- `GET /api/v1/notifications/unread/count` for badge in sidebar
- Frontend: Notification bell icon with unread count badge
- Mark as read/dismiss functionality

**Bulk Operations:**
- Frontend: Multi-select checkboxes in DataTable
- Bulk delete with confirmation
- Bulk status update (e.g., mark multiple invoices as paid)
- Backend: `POST /api/v1/{entity}/bulk-delete` with list of IDs
- Backend: `PATCH /api/v1/{entity}/bulk-update` with list of IDs + patch data

**Dashboard Widgets:**
- Occupancy trend chart (last 12 months)
- Revenue summary (monthly income vs expenses)
- Upcoming contract expirations
- Maintenance case status breakdown (pie chart)
- Frontend: Use lightweight chart library (Chart.js or recharts)

**Files:** `backend/routers/search.py` (new), `backend/routers/admin.py` (bulk ops), `frontend/src/components/SearchBar.jsx` (new), `frontend/src/components/NotificationBell.jsx` (new)

---

## Implementation Order & Dependencies

```
Phase 1 (Foundation)           Phase 2 (i18n & UI)
├── 1.1 Config Module          ├── 2.1 i18n Framework ←── depends on 1.1
├── 1.2 Structured Logging     ├── 2.2 Spanish Locale ←── depends on 2.1
├── 1.3 Global Error Handling  └── 2.3 Interface Customization
└── 1.4 DB Integrity

Phase 3 (Extensibility)        Phase 4 (Polish)
├── 3.1 Plugin System ←─────── depends on 1.1, 1.2, 1.3
└── 3.2 Updateability ←─────── depends on 1.1, 1.4
                                ├── 4.1 Data Persistence ←── depends on 1.4
                                └── 4.2 Practical Features
```

**Recommended execution order:**
1. **1.1** Config → **1.2** Logging → **1.3** Error Handling → **1.4** DB Integrity
2. **2.1** i18n → **2.2** Spanish → **2.3** Customization
3. **3.2** Updateability → **3.1** Plugin System
4. **4.1** Persistence → **4.2** Practical Features

---

## Estimated Scope per Phase

| Phase | New Files | Modified Files | New Dependencies |
|-------|-----------|----------------|------------------|
| 1 | 4 | ~30 | pydantic-settings, python-json-logger |
| 2 | 6+ | ~20 | react-i18next, i18next, i18next-http-backend |
| 3 | 8+ | ~5 | (none) |
| 4 | 4+ | ~10 | recharts (optional) |

---

## Risk Mitigation

- **Breaking changes**: All new features are additive. Existing API endpoints unchanged.
- **Migration safety**: New Alembic migrations are additive (ADD COLUMN, ADD CONSTRAINT). No destructive schema changes.
- **Plugin isolation**: Plugins run in separate route namespaces. A broken plugin cannot crash core.
- **i18n fallback**: Missing translations fall back to German (`de-DE`), then English (`en-US`). No blank strings.
- **Test coverage**: Each phase includes tests. Current 503 tests remain passing throughout.

---

## Success Criteria

- [ ] All config via `.env` with validation; app refuses to start with missing required config
- [ ] JSON-structured logs with request correlation, optional file output
- [ ] Standardized error responses with error codes across all endpoints
- [ ] Full Spanish locale with all ~200+ UI strings translated
- [ ] Dark mode toggle, locale switcher, persistent user preferences
- [ ] DB constraints prevent invalid data at the database level
- [ ] Backup/restore via admin API
- [ ] Plugin system loads external plugins from configured directories
- [ ] Auto-migration on startup with version tracking
- [ ] Global search across all entities with keyboard shortcut
- [ ] 550+ tests passing (50+ new tests for new features)
