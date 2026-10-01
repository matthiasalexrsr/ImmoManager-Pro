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

import { annotateRevisions, conditionalHeaders, revisionOptions } from './editRevision';

const BASE = '/api/v1';

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

let refreshInFlight;

function tryRefreshToken(previousAccessToken) {
  if (!refreshInFlight) {
    const rotate = () => {
      // Another tab may already have rotated while this tab waited for the
      // same-origin lock. Never replay its consumed refresh token.
      if (getToken() && getToken() !== previousAccessToken) return true;
      return refreshTokenOnce();
    };
    const operation = Promise.resolve().then(() => typeof globalThis.navigator?.locks?.request === 'function'
      ? navigator.locks.request('immomanager-token-refresh', rotate)
      : rotate());
    refreshInFlight = operation.catch(() => false).finally(() => { refreshInFlight = null; });
  }
  return refreshInFlight;
}

async function refreshTokenOnce() {
  const refreshToken = localStorage.getItem('refresh_token');
  const previousAccessToken = getToken();
  if (!refreshToken) return false;
  try {
    const res = await fetch(`${BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (res.ok) {
      const data = await res.json();
      if (typeof data?.access_token !== 'string' || !data.access_token
          || (data.refresh_token !== undefined && (typeof data.refresh_token !== 'string' || !data.refresh_token))) return false;
      // Logout or a new login while the network request was pending wins.
      if (getToken() !== previousAccessToken || localStorage.getItem('refresh_token') !== refreshToken) return Boolean(getToken() && getToken() !== previousAccessToken);
      localStorage.setItem('access_token', data.access_token);
      if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token);
      return true;
    }
  } catch {
    console.warn('[API] Token refresh failed.');
  }
  return false;
}

// ---------------------------------------------------------------------------
// Error parsing
// ---------------------------------------------------------------------------

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
    err = new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail));
  } else {
    err = new Error('Ein Fehler ist aufgetreten');
  }
  err.statusCode = statusCode;
  err.isNetwork = false;
  err.isEditConflict = statusCode === 412;
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
  const token = getToken();
  const { signal, responseType = 'json', ...rest } = options;
  const headers = { ...(rest.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...rest.headers };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let res;
  try {
    res = await fetchWithRetry(`${BASE}${path}`, { ...rest, headers, signal });
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    // All retries exhausted — network error
    throw networkError(err);
  }

  // On 401, try refreshing the token once
  if (res.status === 401) {
    signal?.throwIfAborted();
    const refreshed = Boolean(getToken() && getToken() !== token) || await tryRefreshToken(token);
    signal?.throwIfAborted();
    if (refreshed) {
      headers['Authorization'] = `Bearer ${getToken()}`;
      try {
        res = await fetch(`${BASE}${path}`, { ...rest, headers, signal });
      } catch (err) {
        if (err.name === 'AbortError') throw err;
        throw networkError(err);
      }
    }
    if (res.status === 401) {
      // An older response must never clear a newer login from another tab.
      const attemptedToken = headers.Authorization?.slice('Bearer '.length) || null;
      if (getToken() === attemptedToken) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        window.location.href = '/login';
      }
      throw new Error('Nicht authentifiziert');
    }
  }

  if (res.status === 204) return null;
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const error = parseApiError(body, res.status);
    error.resourcePath = path.split('?')[0];
    throw error;
  }

  // Safe JSON parsing for success responses
  if (responseType === 'blob') return res.blob();
  try {
    return annotateRevisions(await res.json(), path, res.headers?.get('ETag'));
  } catch {
    console.warn('[API] Failed to parse JSON response for', path);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export const api = {
  getAll: async (path, { signal } = {}) => {
    const rows = [];
    const pageSize = 1000;
    for (let skip = 0; ; skip += pageSize) {
      const separator = path.includes('?') ? '&' : '?';
      const page = await request(`${path}${separator}skip=${skip}&limit=${pageSize}`, { signal });
      if (!Array.isArray(page)) throw new Error('Ungültige Listenantwort des Servers.');
      rows.push(...page);
      if (page.length < pageSize) return rows;
    }
  },
  get: (path, { signal } = {}) => request(path, { signal }),
  getBlob: (path, { signal } = {}) => request(path, { signal, responseType: 'blob' }),
  postForm: (path, formData, { signal } = {}) => request(path, { method: 'POST', body: formData, signal }),
  post: (path, data, { signal } = {}) => request(path, { method: 'POST', body: JSON.stringify(data), signal }),
  versionOptions: revisionOptions,
  put: (path, data, options = {}) => request(path, { method: 'PUT', body: JSON.stringify(data), signal: options.signal, headers: conditionalHeaders(path, data, options) }),
  patch: (path, data, options = {}) => request(path, { method: 'PATCH', body: JSON.stringify(data), signal: options.signal, headers: conditionalHeaders(path, data, options) }),
  del: (path, options = {}) => request(path, { method: 'DELETE', signal: options.signal, headers: conditionalHeaders(path, null, options) }),
};

export async function login(username, password, totp_code) {
  let res;
  try {
    res = await fetchWithRetry(`${BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, ...(totp_code ? { totp_code } : {}) }),
    });
  } catch (err) {
    throw networkError(err);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const error = parseApiError(body, res.status);
    error.requiresTwoFactor = res.headers?.get('X-2FA-Required') === 'true';
    throw error;
  }
  const data = await res.json();
  localStorage.setItem('access_token', data.access_token);
  localStorage.setItem('refresh_token', data.refresh_token);
  return data;
}

export const getSetupStatus = ({ signal } = {}) => api.get('/auth/setup-status', { signal });
export const setupOwner = (username, email, full_name, password) => api.post('/auth/setup', { username, email, full_name, password });

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

export async function logout() {
  const accessToken = localStorage.getItem('access_token');
  const refreshToken = localStorage.getItem('refresh_token');

  // Revoke tokens server-side before clearing local state.
  // Fire-and-forget: even if the call fails we still clear local tokens.
  if (accessToken || refreshToken) {
    try {
      await fetch(`${BASE}/auth/logout`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify({
          access_token: accessToken || undefined,
          refresh_token: refreshToken || undefined,
        }),
      });
    } catch {
      // Ignore — we still clear locally
    }
  }

  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  window.location.href = '/login';
}

export function isLoggedIn() {
  return !!getToken();
}
