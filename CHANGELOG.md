# Changelog

All notable changes to ImmoManager Pro will be documented in this file.

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
