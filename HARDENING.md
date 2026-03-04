# ImmoManager Pro — Software Hardening Changelog

This document tracks all hardening changes made to improve resilience, error handling,
fallback pathways, and error documentation across the application.

---

## Overview

| Area | Module | Change | Status |
|------|--------|--------|--------|
| Backend | `backend/routers/_helpers.py` | Safe pagination, date-filter guards, sort-type coercion | Done |
| Backend | `backend/storage.py` | Defensive `_get` with type checks, safe ID generation | Done |
| Backend | `backend/routers/validators.py` | Shared validation helpers (ID format, pagination bounds, date ranges) | Done |
| Backend | `backend/exceptions.py` | Extended error codes (RATE_LIMITED, TIMEOUT, SERVICE_UNAVAILABLE) | Done |
| Backend | All routers | Consistent try/except on delete (cascading-safe), list endpoint guards | Done |
| Frontend | `frontend/src/api.js` | Network retry with exponential backoff, request timeout, offline detection | Done |
| Frontend | `frontend/src/hooks/useApi.js` | Retry support, stale-while-revalidate, abort on unmount | Done |
| Frontend | `frontend/src/components/ErrorBoundary.jsx` | Recovery key, auto-retry, route-level isolation | Done |
| Frontend | `frontend/src/components/ErrorFallback.jsx` | Reusable inline error display with retry action | Done |
| Frontend | `frontend/src/pages/CrudPage.jsx` | Delete error toast, save error display, empty-state messaging | Done |
| Frontend | `frontend/src/pages/Dashboard.jsx` | Per-section error isolation, chart fallback on bad data | Done |
| Frontend | `frontend/src/pages/RentOverview.jsx` | Graceful fallback when receivables endpoint unavailable | Done |

---

## Backend Hardening Details

### 1. Shared Validation Helpers (`backend/routers/validators.py`)

New module providing reusable validation functions for router endpoints:

- **`validate_uuid(value, name)`** — Validates UUID format, raises `ValidationError` with field name
- **`validate_pagination(skip, limit)`** — Clamps skip >= 0, limit in [1, 1000], returns safe values
- **`validate_date_range(date_from, date_to)`** — Ensures date_from <= date_to when both provided
- **`validate_sort_field(sort_by, allowed_fields)`** — Rejects sort fields not in the allowed set
- **`safe_int(value, default, min_val, max_val)`** — Coerces to int with bounds and fallback

### 2. Enhanced Router Helpers (`backend/routers/_helpers.py`)

- `apply_sort()` now handles `None`, non-string, and missing-field gracefully (already existed)
- New: `apply_date_filter(items, field, date_from, date_to)` — shared date filtering with isinstance guards
- New: `safe_paginate(items, skip, limit)` — bounds-safe slicing that never raises IndexError

### 3. Extended Exception Handling (`backend/exceptions.py`)

- Added `ErrorCode.RATE_LIMITED`, `ErrorCode.TIMEOUT`, `ErrorCode.SERVICE_UNAVAILABLE`
- Added `RateLimitError` and `ServiceUnavailableError` custom exceptions
- Registered handlers that return proper status codes (429, 503)

### 4. Storage Layer Guards (`backend/storage.py`)

- `_get()` helper validates entity existence with clear error messages
- ID fields guaranteed non-empty via uuid4 fallback in `_create_entity()`
- Collection access returns empty list (never None) on missing keys

### 5. Router-Level Hardening

All CRUD routers now:
- Wrap delete operations in try/except for consistent 404 on missing entities
- Return empty lists (not errors) for list endpoints with zero results
- Use `isinstance(date_from, date)` guards for all date filter parameters
- Log unexpected errors before re-raising

---

## Frontend Hardening Details

### 6. API Client Resilience (`frontend/src/api.js`)

- **Request timeout**: 30-second timeout on all API calls via AbortController
- **Network retry**: Automatic retry (up to 2 retries) with exponential backoff for network errors and 5xx responses
- **Offline detection**: Throws descriptive "Keine Internetverbindung" error when navigator.onLine is false
- **Safe JSON parsing**: `res.json()` wrapped in catch to handle malformed responses
- **Abort cleanup**: AbortController signals properly cleaned up on timeout

### 7. Enhanced useApi Hook (`frontend/src/hooks/useApi.js`)

- **Abort on unmount**: AbortController cancels in-flight requests when component unmounts
- **Retry parameter**: `useList(path, { retries: 2 })` for configurable retry behavior
- **Error recovery**: `reload()` clears error state before re-fetching
- **Stale data preservation**: On reload, existing data stays visible while loading

### 8. ErrorBoundary Improvements (`frontend/src/components/ErrorBoundary.jsx`)

- **Recovery via key**: Accepts `resetKey` prop — changing it auto-resets the boundary
- **Error logging**: Structured console error with component stack
- **Try Again**: Reset-in-place button before full page reload
- **Timestamp**: Shows when the error occurred for support reference

### 9. Inline Error Fallback (`frontend/src/components/ErrorFallback.jsx`)

New component for page-level and section-level error display:
- Shows error message with optional retry button
- Compact variant for use inside panels/cards
- Consistent styling with the design system

### 10. CrudPage Hardening (`frontend/src/pages/CrudPage.jsx`)

- **Delete error handling**: Catches delete failures and shows inline error message
- **Save error propagation**: FormModal errors are displayed to user, not swallowed
- **Empty state**: Shows helpful message when no data exists (not just empty table)
- **Loading skeleton**: Shows structured loading state instead of plain text

### 11. Dashboard Error Isolation (`frontend/src/pages/Dashboard.jsx`)

- Each chart/panel wrapped in try/catch during data transform
- Individual chart sections show fallback on bad data instead of crashing the whole dashboard
- Network failures for individual report endpoints don't prevent other charts from loading

### 12. RentOverview Graceful Degradation

- Falls back to empty table with info message when receivables endpoint is unavailable
- Partial data (e.g., missing contracts) shows "—" placeholders instead of crashing

---

## Error Code Reference

| HTTP Status | Error Code | Description | Frontend Handling |
|-------------|-----------|-------------|-------------------|
| 400 | `VALIDATION_ERROR` | Invalid input data | Show field-level errors in form |
| 401 | `AUTH_FAILED` | Token expired/invalid | Auto-refresh, then redirect to login |
| 403 | `PERMISSION_DENIED` | Insufficient privileges | Show permission error message |
| 404 | `NOT_FOUND` | Entity does not exist | Show "not found" in context |
| 409 | `CONFLICT` | Duplicate/conflict | Show conflict message |
| 422 | `VALIDATION_ERROR` | Pydantic validation failed | Show detailed field errors |
| 429 | `RATE_LIMITED` | Too many requests | Auto-retry after delay |
| 500 | `INTERNAL_ERROR` | Unhandled server error | Show generic error, log details |
| 503 | `SERVICE_UNAVAILABLE` | Service temporarily down | Show maintenance message |

---

## Network Failure Scenarios

| Scenario | Backend Response | Frontend Behavior |
|----------|-----------------|-------------------|
| Server unreachable | No response | Retry 2x with backoff, then show offline message |
| Request timeout (>30s) | Aborted | Show timeout error, offer retry |
| 5xx server error | Error JSON | Retry 2x, then show error with request ID |
| Malformed JSON response | Parse error | Show generic error, log raw response |
| Token expired mid-request | 401 | Auto-refresh token, retry original request |
| Offline (no network) | No response | Immediate "no connection" error |

---

*Last updated: 2026-03-04*
