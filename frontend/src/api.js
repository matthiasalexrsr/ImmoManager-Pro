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

const BASE = '/api/v1';

// ---------------------------------------------------------------------------
// Token helpers
// ---------------------------------------------------------------------------

function getToken() {
  return localStorage.getItem('access_token');
}

// ---------------------------------------------------------------------------
// Retry helper — retries on network errors only (not HTTP errors)
// ---------------------------------------------------------------------------

const MAX_RETRIES = 2;
const RETRY_DELAYS = [1000, 2000]; // ms

async function fetchWithRetry(url, options, retriesLeft = MAX_RETRIES) {
  try {
    return await fetch(url, options);
  } catch (err) {
    // Don't retry aborted requests
    if (err.name === 'AbortError') throw err;
    // Only retry on network errors (TypeError: Failed to fetch)
    if (retriesLeft > 0 && err instanceof TypeError) {
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

async function tryRefreshToken() {
  const refreshToken = localStorage.getItem('refresh_token');
  if (!refreshToken) return false;
  try {
    const res = await fetch(`${BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (res.ok) {
      const data = await res.json();
      localStorage.setItem('access_token', data.access_token);
      if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token);
      return true;
    }
  } catch (err) {
    console.warn('[API] Token refresh failed:', err.message);
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
  const { signal, ...rest } = options;
  const headers = { 'Content-Type': 'application/json', ...rest.headers };
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
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      headers['Authorization'] = `Bearer ${getToken()}`;
      try {
        res = await fetch(`${BASE}${path}`, { ...options, headers });
      } catch (err) {
        throw networkError(err);
      }
    }
    if (res.status === 401) {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      window.location.href = '/login';
      throw new Error('Nicht authentifiziert');
    }
  }

  if (res.status === 204) return null;
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw parseApiError(body, res.status);
  }

  // Safe JSON parsing for success responses
  try {
    return await res.json();
  } catch {
    console.warn('[API] Failed to parse JSON response for', path);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export const api = {
  get: (path, { signal } = {}) => request(path, { signal }),
  post: (path, data, { signal } = {}) => request(path, { method: 'POST', body: JSON.stringify(data), signal }),
  put: (path, data, { signal } = {}) => request(path, { method: 'PUT', body: JSON.stringify(data), signal }),
  patch: (path, data, { signal } = {}) => request(path, { method: 'PATCH', body: JSON.stringify(data), signal }),
  del: (path, { signal } = {}) => request(path, { method: 'DELETE', signal }),
};

export async function login(username, password) {
  let res;
  try {
    res = await fetchWithRetry(`${BASE}/auth/login`, {
      method: 'POST',
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
  return data;
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
