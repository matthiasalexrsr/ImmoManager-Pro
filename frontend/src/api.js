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

import { workspaceOwner } from './utils/workspaceIdentity';

const BASE = import.meta.env.VITE_API_URL || '/api/v1';
// The server keeps this app's refresh token in an HttpOnly cookie for the auth endpoints and leaves it out of
// every response body, so script in the page cannot read it. A token still in localStorage comes from an older
// version (or an older server) and is used once more, then the cookie takes over.
const COOKIE_TRANSPORT = { 'X-Token-Transport': 'cookie' };
let refreshInFlight = null;
let logoutInFlight = null;
let logoutRequested = false;
let sessionGeneration = 0;
let sessionChanged = false;
let validatedOwner = null;

// This only checks browser-session coherence. The server verifies JWT signatures.
function tokenOwner(token) {
  if (!token) return null;
  const parts = token.split('.');
  if (parts.length !== 3) return undefined; // Opaque credentials are checked by the server.
  try {
    const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
    return typeof payload.sub === 'string' ? payload.sub : null;
  } catch { return null; }
}

function changedSessionError() {
  return Object.assign(new Error('Die Sitzung wurde in einem anderen Fenster geändert. Bitte warten Sie auf die erneute Anmeldung.'), { code: 'SESSION_CHANGED' });
}

function invalidateExternalSession() {
  if (sessionChanged) return;
  sessionChanged = true;
  validatedOwner = null;
  logoutRequested = false;
  sessionGeneration += 1;
  // Invalidate old writers immediately; never revoke the other tab's tokens.
  window.dispatchEvent(new CustomEvent('workspace-logout', { detail: { external: true } }));
}

function checkSession() {
  const expected = workspaceOwner();
  const actual = tokenOwner(getToken());
  if (expected && actual !== undefined && actual !== expected) invalidateExternalSession();
}

function requireCurrentSession(generation, owner, bootstrap = false) {
  // An already-invalidated operation must not invalidate a newly verified user.
  if (logoutRequested || generation !== sessionGeneration) {
    throw Object.assign(new Error('Die Sitzung wurde beendet oder geändert.'), { code: 'SESSION_CHANGED' });
  }
  const actual = tokenOwner(getToken());
  if (owner != null && actual !== undefined && actual !== owner) {
    invalidateExternalSession();
    throw changedSessionError();
  }
  if (sessionChanged && validatedOwner && workspaceOwner() === validatedOwner) sessionChanged = false;
  if (sessionChanged && !bootstrap) throw changedSessionError();
}

function captureSession() {
  checkSession();
  const generation = sessionGeneration;
  const owner = workspaceOwner() || tokenOwner(getToken());
  const current = () => requireCurrentSession(generation, owner);
  current();
  return current;
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

async function fetchWithRetry(url, options, retriesLeft = MAX_RETRIES, beforeAttempt = () => {}) {
  beforeAttempt();
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
      return fetchWithRetry(url, options, retriesLeft - 1, beforeAttempt);
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Token refresh
// ---------------------------------------------------------------------------

function storeRefreshToken(token) {
  if (token) localStorage.setItem('refresh_token', token);       // an older server still answers with the token
  else localStorage.removeItem('refresh_token');
}

function tryRefreshToken(owner) {
  if (logoutRequested) return Promise.resolve(false);
  if (refreshInFlight) return refreshInFlight;
  const refreshToken = localStorage.getItem('refresh_token');
  if (!refreshToken && !getToken()) return Promise.resolve(false);   // never signed in here, or signed out
  const refreshOwner = tokenOwner(refreshToken);
  if (refreshToken && owner != null && refreshOwner !== undefined && refreshOwner !== owner) {
    invalidateExternalSession();
    return Promise.reject(changedSessionError());
  }
  const accessBefore = getToken();
  refreshInFlight = (async () => {
    const send = () => fetch(`${BASE}/auth/refresh`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...COOKIE_TRANSPORT },
      body: JSON.stringify(refreshToken ? { refresh_token: refreshToken } : {}),
    });
    let res;
    try {
      res = await send();
      if ((res.status === 401 || res.status === 403) && !refreshToken) {
        // Another window may just have renewed the session and rotated the cookie: use its access token, or
        // try once more with the cookie the browser now holds.
        if (getToken() && getToken() !== accessBefore) return true;
        await new Promise(resolve => setTimeout(resolve, 300));
        if (getToken() && getToken() !== accessBefore) return true;
        res = await send();
      }
    } catch (err) {
      throw networkError(err);
    }
    if (res.status === 401 || res.status === 403) return false;
    if (!res.ok) throw parseApiError(await res.json().catch(() => ({})), res.status);
    const data = await res.json();
    if (!data.access_token) throw new Error('Die Sitzung konnte nicht erneuert werden. Bitte erneut versuchen.');
    const actual = tokenOwner(getToken());
    const renewed = tokenOwner(data.access_token);
    if (owner != null && ((actual !== undefined && actual !== owner) || (renewed !== undefined && renewed !== owner))) {
      invalidateExternalSession();
      throw changedSessionError();
    }
    if (refreshToken && localStorage.getItem('refresh_token') !== refreshToken) return false;
    // Logout waits for this result, then revokes these newest tokens.
    localStorage.setItem('access_token', data.access_token);
    storeRefreshToken(data.refresh_token);
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
    // Preserve FastAPI's field paths for the shared form, without changing error text.
    if (Array.isArray(body.detail)) err.details = body.detail;
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
  checkSession();
  const bootstrap = path === '/auth/me' && options.sessionBootstrap === true;
  const generation = sessionGeneration;
  const token = getToken();
  const owner = bootstrap ? tokenOwner(token) : workspaceOwner() || tokenOwner(token);
  const current = () => requireCurrentSession(generation, owner, bootstrap);
  current();
  const { signal, responseType, sessionBootstrap: _sessionBootstrap, ...rest } = options;
  // multipart bodies (file uploads) set their own boundary
  const isForm = typeof FormData !== 'undefined' && rest.body instanceof FormData;
  const headers = isForm ? { ...rest.headers } : { 'Content-Type': 'application/json', ...rest.headers };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let res;
  try {
    res = await fetchWithRetry(`${BASE}${path}`, { credentials: 'include', ...rest, headers, signal }, MAX_RETRIES, current);
  } catch (err) {
    if (err.name === 'AbortError' || err.code === 'SESSION_CHANGED') throw err;
    // All retries exhausted — network error
    throw networkError(err);
  }

  // On 401, try refreshing the token once
  current();
  if (res.status === 401) {
    const refreshed = getToken() && getToken() !== token ? true : await tryRefreshToken(owner);
    current();
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    if (refreshed) {
      headers['Authorization'] = `Bearer ${getToken()}`;
      try {
        res = await fetch(`${BASE}${path}`, { credentials: 'include', ...rest, signal, headers });
      } catch (err) {
        if (err.name === 'AbortError') throw err;
        throw networkError(err);
      }
    }
    current();
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
    current();
    throw parseApiError(body, res.status);
  }

  if (responseType === 'blob' || responseType === 'file') {
    // Generated or protected files (PDF): the same session checks as JSON, also after reading.
    const blob = await res.blob();
    current();
    return responseType === 'blob' ? blob : { blob, headers: res.headers };
  }

  // Safe JSON parsing for success responses
  let data;
  try {
    data = await res.json();
  } catch {
    console.warn('[API] Failed to parse JSON response for', path);
    return null;
  }
  current();
  if (bootstrap && data?.id) {
    if (owner != null && data.id !== owner) {
      invalidateExternalSession();
      throw changedSessionError();
    }
    validatedOwner = data.id;
  }
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
  const current = captureSession();
  const rows = [];
  const seen = new Set();
  for (let page = 0; page < LIST_MAX_PAGES; page += 1) {
    current();
    const data = await request(pagePath(path, page * LIST_PAGE_SIZE), { signal });
    current();
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
  checkSession,
  captureSession,
  get: (path, { signal, sessionBootstrap = false } = {}) => request(path, { signal, sessionBootstrap }),
  list: (path, { signal } = {}) => requestList(path, { signal }),
  post: (path, data, { signal } = {}) => request(path, { method: 'POST', body: JSON.stringify(data), signal }),
  put: (path, data, { signal } = {}) => request(path, { method: 'PUT', body: JSON.stringify(data), signal }),
  patch: (path, data, { signal } = {}) => request(path, { method: 'PATCH', body: JSON.stringify(data), signal }),
  del: (path, { signal, data } = {}) => request(path, { method: 'DELETE', signal,
    ...(data === undefined ? {} : { body: JSON.stringify(data) }) }),
  getBlob: (path, { signal } = {}) => request(path, { signal, responseType: 'blob' }),
  postBlob: (path, data, { signal } = {}) => request(path, {
    method: 'POST', body: JSON.stringify(data), signal, responseType: 'blob',
  }),
  /** a file with its response headers (name, notes such as X-Print-Skipped): { blob, headers } */
  getFile: (path, { signal } = {}) => request(path, { signal, responseType: 'file' }),
  postFile: (path, data, { signal } = {}) => request(path, {
    method: 'POST', body: JSON.stringify(data), signal, responseType: 'file',
  }),
  /** multipart upload (FormData) with the same session, refresh and logout handling as JSON */
  upload: (path, formData, { signal, idempotencyKey } = {}) => request(path, { method: 'POST', body: formData, signal,
    ...(idempotencyKey ? { headers: { 'Idempotency-Key': idempotencyKey } } : {}) }),
};

export async function login(username, password, totpCode) {
  if (logoutInFlight) await logoutInFlight;
  if (refreshInFlight) await refreshInFlight;
  let res;
  try {
    res = await fetchWithRetry(`${BASE}/auth/login`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...COOKIE_TRANSPORT },
      body: JSON.stringify({ username, password, ...(totpCode ? { totp_code: totpCode } : {}) }),
    });
  } catch (err) {
    throw networkError(err);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const error = parseApiError(body, res.status);
    if (res.headers.get('X-2FA-Required') === 'true') error.requiresTotp = true;
    throw error;
  }
  const data = await res.json();
  localStorage.setItem('access_token', data.access_token);
  storeRefreshToken(data.refresh_token);
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
  try { captureSession(); } catch (error) { return Promise.reject(error); }
  const departingOwner = workspaceOwner() || tokenOwner(getToken());
  const ownerChanged = () => {
    const actual = tokenOwner(getToken());
    return departingOwner != null && actual !== undefined && actual !== departingOwner;
  };
  logoutRequested = true;
  sessionGeneration += 1;
  logoutInFlight = (async () => {
    try {
      // A temporary refresh failure must not prevent an explicit logout.
      if (refreshInFlight) await refreshInFlight.catch(() => {});
      if (ownerChanged()) { checkSession(); logoutRequested = false; return; }
      const accessToken = localStorage.getItem('access_token');
      const refreshToken = localStorage.getItem('refresh_token');
      // Always call the server: an HttpOnly upload cookie can outlive local storage.
      const response = await fetch(`${BASE}/auth/logout`, {
        method: 'POST', credentials: 'include',
        headers: {
          'Content-Type': 'application/json', ...COOKIE_TRANSPORT,
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify({
          access_token: accessToken || undefined,
          refresh_token: refreshToken || undefined,
        }),
      });
      if (!response.ok) throw new Error('Die Abmeldung wurde vom Server nicht bestätigt. Bitte erneut versuchen.');
      if (ownerChanged()) { checkSession(); logoutRequested = false; return; }
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      window.dispatchEvent(new Event('workspace-logout'));
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
