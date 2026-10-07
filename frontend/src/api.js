/**
 * API client for ImmoManager Pro.
 *
 * Features:
 *   - Automatic JWT token management (access + refresh)
 *   - Retry logic for transient network failures (up to 2 retries)
 *   - Structured error parsing with code, message, details, requestId
 *   - Network vs server error distinction
 *   - Safe JSON parsing with fallbacks
 */

const BASE = import.meta.env.VITE_API_URL || '/api/v1';
let refreshInFlight = null;
let logoutInFlight = null;
let logoutRequested = false;
let sessionGeneration = 0;

function requireCurrentSession(generation) {
  if (logoutRequested || generation !== sessionGeneration) throw new Error('Die Sitzung wurde beendet oder geändert.');
}

// ---------------------------------------------------------------------------
// Token helpers
// ---------------------------------------------------------------------------

function getToken() {
  return localStorage.getItem('access_token');
}

// ---------------------------------------------------------------------------
// Retry helper — retries safe methods on network errors only (not HTTP errors)
// ---------------------------------------------------------------------------

const MAX_RETRIES = 2;
const RETRY_DELAYS = [1000, 2000]; // ms

async function fetchWithRetry(url, options, retriesLeft = MAX_RETRIES) {
  try {
    return await fetch(url, options);
  } catch (err) {
    // Don't retry aborted requests
    if (err.name === 'AbortError') throw err;
    // Only retry safe (idempotent) methods on network errors
    const method = (options?.method || 'GET').toUpperCase();
    const isSafe = method === 'GET' || method === 'HEAD' || method === 'OPTIONS';
    if (isSafe && retriesLeft > 0 && err instanceof TypeError) {
      const delay = RETRY_DELAYS[MAX_RETRIES - retriesLeft] || 1000;
      console.warn(`[API] Network error, retrying in ${delay}ms (${retriesLeft} left):`, err.message);
      await new Promise(r => setTimeout(r, delay));
      return fetchWithRetry(url, options, retriesLeft - 1);
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Token refresh
// ---------------------------------------------------------------------------

function tryRefreshToken() {
  if (logoutRequested) return Promise.resolve(false);
  if (refreshInFlight) return refreshInFlight;
  const refreshToken = localStorage.getItem('refresh_token');
  if (!refreshToken) return Promise.resolve(false);
  refreshInFlight = (async () => {
    let res;
    try {
      res = await fetch(`${BASE}/auth/refresh`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch (err) {
      throw networkError(err);
    }
    if (res.status === 401 || res.status === 403) return false;
    if (!res.ok) throw parseApiError(await res.json().catch(() => ({})), res.status);
    const data = await res.json();
    if (!data.access_token) throw new Error('Die Sitzung konnte nicht erneuert werden. Bitte erneut versuchen.');
    if (localStorage.getItem('refresh_token') !== refreshToken) return false;
    // Logout waits for this result, then revokes these newest tokens.
    localStorage.setItem('access_token', data.access_token);
    if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token);
    return true;
  })().finally(() => { refreshInFlight = null; });
  return refreshInFlight;
}

// ---------------------------------------------------------------------------
// Error parsing
// ---------------------------------------------------------------------------

/**
 * FastAPI validation errors are a list of {loc, msg}: show the messages, not the JSON.
 */
function validationMessage(detail) {
  const messages = Array.isArray(detail)
    ? detail.map(item => String(item?.msg ?? '').replace(/^Value error, /, '')).filter(Boolean)
    : [];
  return messages.length ? messages.join('; ') : JSON.stringify(detail);
}

/**
 * Parse standardized error response from backend.
 * Expected format: { error: { code, message, details, request_id } }
 *
 * Returns an Error object enriched with .code, .details, .requestId, .isNetwork
 */
function parseApiError(body, statusCode) {
  let err;
  if (body?.error?.message) {
    err = new Error(body.error.message);
    err.code = body.error.code;
    err.details = body.error.details;
    err.requestId = body.error.request_id;
  } else if (body?.detail) {
    err = new Error(typeof body.detail === 'string' ? body.detail : validationMessage(body.detail));
  } else {
    err = new Error('Ein Fehler ist aufgetreten');
  }
  err.statusCode = statusCode;
  err.isNetwork = false;
  return err;
}

/**
 * Create a network error with the isNetwork flag set.
 */
function networkError(originalError) {
  const err = new Error(
    'Verbindung zum Server fehlgeschlagen. Bitte prüfen Sie Ihre Internetverbindung.'
  );
  err.code = 'NETWORK_ERROR';
  err.isNetwork = true;
  err.originalError = originalError;
  return err;
}

// ---------------------------------------------------------------------------
// Core request function
// ---------------------------------------------------------------------------

async function request(path, options = {}) {
  const generation = sessionGeneration;
  requireCurrentSession(generation);
  const token = getToken();
  const { signal, ...rest } = options;
  const headers = { 'Content-Type': 'application/json', ...rest.headers };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let res;
  try {
    res = await fetchWithRetry(`${BASE}${path}`, { credentials: 'include', ...rest, headers, signal });
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    // All retries exhausted — network error
    throw networkError(err);
  }

  // On 401, try refreshing the token once
  requireCurrentSession(generation);
  if (res.status === 401) {
    const refreshed = getToken() && getToken() !== token ? true : await tryRefreshToken();
    requireCurrentSession(generation);
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    if (refreshed) {
      headers['Authorization'] = `Bearer ${getToken()}`;
      try {
        res = await fetch(`${BASE}${path}`, { credentials: 'include', ...options, headers });
      } catch (err) {
        if (err.name === 'AbortError') throw err;
        throw networkError(err);
      }
    }
    requireCurrentSession(generation);
    if (res.status === 401) {
      await logout();
      // Never redirect from the login page to itself: that reloads it forever.
      if (window.location.pathname !== '/login') window.location.href = '/login';
      throw new Error('Nicht authentifiziert');
    }
  }

  if (res.status === 204) return null;
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw parseApiError(body, res.status);
  }

  // Safe JSON parsing for success responses
  let data;
  try {
    data = await res.json();
  } catch {
    console.warn('[API] Failed to parse JSON response for', path);
    return null;
  }
  requireCurrentSession(generation);
  return data;
}

// ---------------------------------------------------------------------------
// Complete lists — list endpoints return at most `limit` rows (default 100)
// ---------------------------------------------------------------------------

const LIST_PAGE_SIZE = 1000; // the largest page the server accepts
const LIST_MAX_PAGES = 500;

function pagePath(path, skip) {
  const [base, query = ''] = path.split('?');
  const params = new URLSearchParams(query);
  params.set('skip', String(skip));
  params.set('limit', String(LIST_PAGE_SIZE));
  return `${base}?${params}`;
}

/**
 * Load every row of a collection, page by page, until a short page arrives.
 * Rows already seen (same id) end the loop, so an endpoint that ignores
 * skip cannot make it spin.
 */
async function requestList(path, { signal } = {}) {
  const rows = [];
  const seen = new Set();
  for (let page = 0; page < LIST_MAX_PAGES; page += 1) {
    const data = await request(pagePath(path, page * LIST_PAGE_SIZE), { signal });
    if (!Array.isArray(data)) return page === 0 ? data : rows;
    let added = 0;
    for (const row of data) {
      if (row?.id != null) {
        if (seen.has(row.id)) continue;
        seen.add(row.id);
      }
      rows.push(row);
      added += 1;
    }
    if (data.length < LIST_PAGE_SIZE || added === 0) break;
  }
  return rows;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export const api = {
  get: (path, { signal } = {}) => request(path, { signal }),
  list: (path, { signal } = {}) => requestList(path, { signal }),
  post: (path, data, { signal } = {}) => request(path, { method: 'POST', body: JSON.stringify(data), signal }),
  put: (path, data, { signal } = {}) => request(path, { method: 'PUT', body: JSON.stringify(data), signal }),
  patch: (path, data, { signal } = {}) => request(path, { method: 'PATCH', body: JSON.stringify(data), signal }),
  del: (path, { signal } = {}) => request(path, { method: 'DELETE', signal }),
};

export async function login(username, password) {
  if (logoutInFlight) await logoutInFlight;
  if (refreshInFlight) await refreshInFlight;
  let res;
  try {
    res = await fetchWithRetry(`${BASE}/auth/login`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
  } catch (err) {
    throw networkError(err);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw parseApiError(body, res.status);
  }
  const data = await res.json();
  localStorage.setItem('access_token', data.access_token);
  localStorage.setItem('refresh_token', data.refresh_token);
  logoutRequested = false;
  sessionGeneration += 1;
  return data;
}

export async function getRegistrationStatus() {
  try {
    const res = await fetch(`${BASE}/auth/registration-status`);
    if (!res.ok) return { open: false, initial_setup: false };
    return await res.json();
  } catch {
    return { open: false, initial_setup: false };
  }
}

export async function register(username, email, full_name, password) {
  let res;
  try {
    res = await fetchWithRetry(`${BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, full_name, password }),
    });
  } catch (err) {
    throw networkError(err);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw parseApiError(body, res.status);
  }
  return res.json();
}

export function logout() {
  if (logoutInFlight) return logoutInFlight;
  logoutRequested = true;
  sessionGeneration += 1;
  logoutInFlight = (async () => {
    try {
      // A temporary refresh failure must not prevent an explicit logout.
      if (refreshInFlight) await refreshInFlight.catch(() => {});
      const accessToken = localStorage.getItem('access_token');
      const refreshToken = localStorage.getItem('refresh_token');
      // Always call the server: an HttpOnly upload cookie can outlive local storage.
      const response = await fetch(`${BASE}/auth/logout`, {
        method: 'POST', credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify({
          access_token: accessToken || undefined,
          refresh_token: refreshToken || undefined,
        }),
      });
      if (!response.ok) throw new Error('Die Abmeldung wurde vom Server nicht bestätigt. Bitte erneut versuchen.');
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    } catch (error) {
      logoutRequested = false;
      throw new Error('Die Abmeldung ist fehlgeschlagen. Ihre Sitzung bleibt bestehen. Bitte erneut versuchen.', { cause: error });
    }
  })().finally(() => { logoutInFlight = null; });
  return logoutInFlight;
}

export function isLoggedIn() {
  return !!getToken();
}
