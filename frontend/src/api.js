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
const tokenStorage = localStorage;

// ---------------------------------------------------------------------------
// Token helpers
// ---------------------------------------------------------------------------

function getToken() {
  return tokenStorage.getItem('access_token');
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
let tokenDatabase;
let pendingRotation;
let authCommand = 0;

function coordinationError() {
  return Object.assign(new Error('Die Anmeldung konnte im Browser nicht synchronisiert werden. Bitte erneut versuchen.'),
    { code: 'SESSION_COORDINATION_UNAVAILABLE', isNetwork: true });
}

function tokenLock(operation) {
  return Promise.resolve().then(() => typeof globalThis.navigator?.locks?.request === 'function'
    ? navigator.locks.request('immomanager-token-refresh', operation) : operation());
}

function sessionDatabase() {
  if (typeof globalThis.indexedDB?.open !== 'function') return Promise.resolve(null);
  if (!tokenDatabase) {
    tokenDatabase = new Promise((resolve, reject) => {
      let rejected = false;
      const opening = indexedDB.open('immomanager-auth', 1);
      opening.onupgradeneeded = () => opening.result.createObjectStore('session');
      opening.onerror = opening.onblocked = () => { rejected = true; reject(coordinationError()); };
      opening.onsuccess = () => {
        const db = opening.result;
        if (rejected) { db.close(); return; }
        db.onversionchange = () => { db.close(); tokenDatabase = null; };
        resolve(db);
      };
    }).catch(() => { tokenDatabase = null; throw coordinationError(); });
  }
  return tokenDatabase;
}

async function storedPair(value, write = false, predicate) {
  const db = await sessionDatabase();
  if (!db) return undefined;
  return new Promise((resolve, reject) => {
    const transaction = db.transaction('session', write ? 'readwrite' : 'readonly');
    const store = transaction.objectStore('session');
    const operation = write && !predicate ? store.put(value, 'current') : store.get('current');
    let result;
    let changed = false;
    operation.onsuccess = () => {
      result = operation.result;
      if (write && predicate && predicate(result)) {
        try { store.put(value, 'current'); changed = true; }
        catch { transaction.abort(); reject(coordinationError()); }
      }
    };
    transaction.oncomplete = () => resolve(predicate ? changed : write ? value : result);
    transaction.onabort = transaction.onerror = () => reject(coordinationError());
  }).catch(() => { throw coordinationError(); });
}

function localPair(value) {
  if (value === null) {
    tokenStorage.removeItem('access_token'); tokenStorage.removeItem('refresh_token');
  } else {
    tokenStorage.setItem('access_token', value.access_token);
    if (value.refresh_token) tokenStorage.setItem('refresh_token', value.refresh_token);
  }
}

function validPair(value) {
  return value && typeof value.access_token === 'string' && value.access_token
    && typeof value.refresh_token === 'string' && value.refresh_token;
}

function sessionIdentity(token) {
  if (!token) return null;
  try {
    const payload = token.split('.')[1].replaceAll('-', '+').replaceAll('_', '/');
    const claims = JSON.parse(atob(payload));
    // Change detection only. Authorization still requires a fresh /auth/me.
    return typeof claims.sub === 'string' ? JSON.stringify([claims.sub, claims.sid || null]) : token;
  } catch { return token; }
}

function notifySessionChange() {
  window.dispatchEvent?.(new Event('immomanager-session-change'));
}

export function watchSessionChange(onChange) {
  let identity = sessionIdentity(getToken());
  let active = true;
  const listener = async event => {
    if (!active) return;
    if (event.type === 'storage' && ((event.storageArea && event.storageArea !== tokenStorage)
      || (event.key !== null && !['access_token', 'refresh_token'].includes(event.key)))) return;
    // Explicit logout must hide private state without waiting behind a pending
    // network refresh. Other events synchronize the committed pair first.
    if (event.type === 'storage' && (event.key === null || (event.key === 'access_token' && event.newValue === null))) {
      localPair(null);
      if (active && identity !== null) { identity = null; onChange(); }
      return;
    }
    try {
      await tokenLock(async () => {
        if (!active) return;
        const latest = await storedPair();
        if (!active) return;
        if (latest === null) localPair(null);
        else if (latest !== undefined) {
          if (!validPair(latest)) throw coordinationError();
          if (!latest.rotating && latest.refresh_token !== tokenStorage.getItem('refresh_token')) localPair(latest);
        }
        const next = sessionIdentity(getToken());
        if (next !== identity) { identity = next; onChange(); }
      });
    } catch {
      // A changed actor with unreadable coordination state must not retain the
      // preceding actor's private UI; the login screen can retry safely.
      if (active) onChange(true);
    }
  };
  window.addEventListener('storage', listener);
  window.addEventListener('immomanager-session-change', listener);
  return () => {
    active = false;
    window.removeEventListener('storage', listener);
    window.removeEventListener('immomanager-session-change', listener);
  };
}

function samePair(a, b) {
  return a === b || (a && b && a.access_token === b.access_token
    && a.refresh_token === b.refresh_token && a.rotating === b.rotating);
}

async function publishRotation(rotation) {
  const committed = await storedPair(rotation.pair, true, current => current?.rotating === rotation.id);
  // Login/logout may have replaced the intent in browsers without Web Locks.
  if (committed === false) {
    const current = await storedPair();
    pendingRotation = null;
    if (!getToken()) return false;
    if (validPair(current) && !current.rotating) { localPair(current); return true; }
    if (current === null) { localPair(null); return false; }
    throw coordinationError();
  }
  pendingRotation = null;
  // Logout clears the local pair immediately, before waiting for the lock.
  if (getToken() !== rotation.previousAccess || tokenStorage.getItem('refresh_token') !== rotation.previousRefresh) {
    return Boolean(getToken() && getToken() !== rotation.previousAccess);
  }
  localPair(rotation.pair);
  return true;
}

async function invalidateCurrentToken(attemptedToken) {
  if (typeof globalThis.indexedDB?.open !== 'function') {
    if (getToken() !== attemptedToken) return false;
    localPair(null); return true;
  }
  return tokenLock(async () => {
    if (!getToken()) return false;
    const latest = await storedPair();
    if (latest && !validPair(latest)) throw coordinationError();
    if (latest && latest.access_token !== attemptedToken) { localPair(latest); return false; }
    if (getToken() !== attemptedToken) return false;
    await storedPair(null, true);
    localPair(null); return true;
  });
}

function tryRefreshToken(previousAccessToken) {
  if (!refreshInFlight) {
    const rotate = async () => {
      // Another tab may already have rotated while this tab waited for the
      // same-origin lock. Never replay its consumed refresh token.
      if (getToken() && getToken() !== previousAccessToken) return true;
      if (!getToken()) return false;
      // Cross-renderer Local Storage visibility is not a synchronization
      // primitive. Read the committed pair before choosing a refresh token.
      const latest = await storedPair();
      if (latest === null) { localPair(null); return false; }
      if (latest !== undefined) {
        if (!validPair(latest)) throw coordinationError();
        if (!getToken()) return false;
        if (latest.rotating) {
          if (pendingRotation?.id === latest.rotating) return publishRotation(pendingRotation);
          throw Object.assign(coordinationError(), {
            code: 'SESSION_REFRESH_UNCERTAIN',
            message: 'Die letzte Anmeldeverlängerung ist noch nicht bestätigt. Bitte im ursprünglichen Tab erneut versuchen oder neu anmelden.',
          });
        }
        if (latest.refresh_token !== tokenStorage.getItem('refresh_token')) {
          localPair(latest);
          if (latest.access_token !== previousAccessToken) return true;
        }
      }
      return refreshTokenOnce(latest);
    };
    refreshInFlight = tokenLock(rotate).catch(error => {
      if (typeof globalThis.indexedDB?.open === 'function') throw error.code?.startsWith('SESSION_') ? error : coordinationError();
      if (error.code === 'SESSION_COORDINATION_UNAVAILABLE') throw error;
      return false;
    }).finally(() => { refreshInFlight = null; });
  }
  return refreshInFlight;
}

async function refreshTokenOnce(latest) {
  const refreshToken = tokenStorage.getItem('refresh_token');
  const previousAccessToken = getToken();
  if (!refreshToken) return false;
  const durable = typeof globalThis.indexedDB?.open === 'function';
  const rotationId = durable ? crypto.randomUUID() : undefined;
  if (durable) {
    // Persist intent before sending a one-use credential. A lost response or
    // failed pair commit must never cause another tab to replay this token.
    const claimed = await storedPair({ access_token: previousAccessToken, refresh_token: refreshToken, rotating: rotationId },
      true, current => samePair(current, latest));
    if (!claimed) throw coordinationError();
    if (getToken() !== previousAccessToken || tokenStorage.getItem('refresh_token') !== refreshToken) return false;
  }
  try {
    const res = await fetch(`${BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (res.ok) {
      const data = await res.json();
      if (typeof data?.access_token !== 'string' || !data.access_token
          || (durable && data.refresh_token === undefined)
          || (data.refresh_token !== undefined && (typeof data.refresh_token !== 'string' || !data.refresh_token))) return false;
      // Logout or a new login while the network request was pending wins.
      if (getToken() !== previousAccessToken || tokenStorage.getItem('refresh_token') !== refreshToken) return Boolean(getToken() && getToken() !== previousAccessToken);
      // Commit the complete pair before releasing the same-origin lock.
      if (durable) {
        pendingRotation = { id: rotationId, pair: { access_token: data.access_token, refresh_token: data.refresh_token || refreshToken },
          previousAccess: previousAccessToken, previousRefresh: refreshToken };
        return await publishRotation(pendingRotation);
      }
      localPair(data); return true;
    }
  } catch (error) {
    if (durable) throw error.code?.startsWith('SESSION_') ? error : coordinationError();
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
      if (await invalidateCurrentToken(attemptedToken)) {
        window.location.href = '/login';
      }
      throw Object.assign(new Error('Nicht authentifiziert'), { statusCode: 401, code: 'AUTH_REQUIRED' });
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
    const body = await res.json();
    if (path === '/auth/me' && headers.Authorization !== (getToken() ? `Bearer ${getToken()}` : undefined)) {
      throw Object.assign(new Error('Die Anmeldung wurde inzwischen geändert. Bitte erneut prüfen.'), { code: 'AUTH_SESSION_CHANGED' });
    }
    return annotateRevisions(body, path, res.headers?.get('ETag'));
  } catch (error) {
    if (error.code === 'AUTH_SESSION_CHANGED') throw error;
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
  const command = ++authCommand;
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
  await tokenLock(async () => {
    if (command !== authCommand) throw Object.assign(new Error('Die Anmeldung wurde inzwischen beendet.'), { code: 'AUTH_LOGIN_SUPERSEDED' });
    await storedPair({ access_token: data.access_token, refresh_token: data.refresh_token }, true);
    if (command !== authCommand) return;
    pendingRotation = null;
    localPair(data);
  });
  notifySessionChange();
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
  ++authCommand;
  const previousAccess = getToken();
  const previousRefresh = tokenStorage.getItem('refresh_token');
  localPair(null);
  await tokenLock(async () => {
    let latest;
    try { latest = await storedPair(); } catch { /* Still revoke the locally known family. */ }
    const accessToken = latest?.access_token || previousAccess;
    const refreshToken = latest?.refresh_token || previousRefresh;
    if (accessToken || refreshToken) {
      try {
        await fetch(`${BASE}/auth/logout`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
          },
          body: JSON.stringify({ access_token: accessToken || undefined, refresh_token: refreshToken || undefined }),
        });
      } catch { /* Local logout remains effective if the network is unavailable. */ }
    }
    pendingRotation = null;
    try { await storedPair(null, true); }
    finally { localPair(null); notifySessionChange(); window.location.href = '/login'; }
  });
}

export function isLoggedIn() {
  return !!getToken();
}
