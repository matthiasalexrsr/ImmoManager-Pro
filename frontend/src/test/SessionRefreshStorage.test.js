import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const pair = (name) => ({ access_token: `${name}-access`, refresh_token: `${name}-refresh` });
const ok = (value) => ({ ok: true, status: 200, json: async () => value });
const denied = () => ({ ok: false, status: 401 });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const storage = (value = pair('expired')) => {
  const values = new Map(Object.entries(value));
  return { getItem: key => values.get(key) ?? null, setItem: (key, item) => values.set(key, item), removeItem: key => values.delete(key) };
};
const jwtPair = (actor, family, revision = 1) => ({
  access_token: `header.${btoa(JSON.stringify({ sub: actor, sid: family, iat: revision }))}.signature`,
  refresh_token: `${actor}-${family}-refresh-${revision}`,
});

// Two renderer stores deliberately do not observe each other's writes. The
// IndexedDB double commits transactions independently of local renderer caches.
function database(initial) {
  let record = initial;
  let tail = Promise.resolve();
  const state = { failCommit: false, committed: () => record };
  state.open = () => {
    const opening = {};
    opening.result = {
      close: vi.fn(), createObjectStore: vi.fn(),
      transaction: (_name, mode) => {
        const tx = {};
        const operations = [];
        let aborted = false;
        tx.abort = () => { aborted = true; };
        tx.objectStore = () => ({
          get: () => { const op = {}; operations.push({ op, get: true }); return op; },
          put: value => {
            if (state.throwPut) throw new Error('Synthetic storage quota failure');
            const op = {}; operations.push({ op, value }); return op;
          },
        });
        const run = async () => {
          let changed;
          for (const operation of operations) {
            await Promise.resolve();
            operation.op.result = operation.get ? record : 'current';
            if (!operation.get) changed = operation.value;
            operation.op.onsuccess?.();
          }
          if (aborted || (mode === 'readwrite' && state.failCommit)) { tx.onabort?.(); return; }
          if (operations.some(item => !item.get)) record = changed;
          tx.oncomplete?.();
        };
        tail = tail.then(run);
        return tx;
      },
    };
    queueMicrotask(() => opening.onsuccess?.());
    return opening;
  };
  return state;
}

let db;
let fetchMock;
let stores;

async function tab(index) {
  vi.resetModules();
  vi.stubGlobal('localStorage', stores[index]);
  return import('../api.js');
}

beforeEach(() => {
  db = database(pair('expired'));
  stores = [storage(), storage()];
  let tail = Promise.resolve();
  vi.stubGlobal('navigator', { locks: { request: (_name, action) => {
    const result = tail.then(action); tail = result.catch(() => {}); return result;
  } } });
  vi.stubGlobal('indexedDB', db);
  vi.stubGlobal('window', { location: { href: '/settings' } });
  fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

it('never replays a consumed refresh token from a stale renderer cache', async () => {
  let rotations = 0;
  fetchMock.mockImplementation(async (url, options) => {
    if (url.endsWith('/auth/refresh')) {
      rotations++;
      // A repeated old token really revokes the whole synthetic family.
      return rotations === 1 ? ok(pair('rotated')) : denied();
    }
    return options.headers.Authorization === 'Bearer rotated-access' && rotations === 1 ? ok({ id: 'owner' }) : denied();
  });
  const first = await tab(0); const second = await tab(1);
  const results = await Promise.all([first.api.get('/auth/me'), second.api.get('/auth/me')]);
  expect(results).toEqual([{ id: 'owner' }, { id: 'owner' }]);
  expect(rotations).toBe(1);
  expect(stores.map(store => store.getItem('refresh_token'))).toEqual(['rotated-refresh', 'rotated-refresh']);
});

it('uses the request-time refresh snapshot when renderer keys propagate out of step', async () => {
  let rotations = 0;
  fetchMock.mockImplementation(async (url, options) => {
    if (url.endsWith('/auth/refresh')) {
      rotations++;
      if (rotations === 1) {
        // Chromium may expose the new refresh key in another renderer before
        // that renderer observes the matching access-key write.
        stores[1].setItem('refresh_token', 'rotated-refresh');
        return ok(pair('rotated'));
      }
      return denied();
    }
    return options.headers.Authorization === 'Bearer rotated-access' ? ok({ id: 'owner' }) : denied();
  });
  const first = await tab(0); const second = await tab(1);
  const results = await Promise.all([first.api.get('/auth/me'), second.api.get('/auth/me')]);
  expect(results).toEqual([{ id: 'owner' }, { id: 'owner' }]);
  expect(rotations).toBe(1);
  expect(stores.map(store => store.getItem('access_token'))).toEqual(['rotated-access', 'rotated-access']);
});

it('keeps a failed pair commit retryable without resending the one-use token', async () => {
  let rotations = 0;
  fetchMock.mockImplementation(async (url, options) => {
    if (url.endsWith('/auth/refresh')) { rotations++; db.failCommit = true; return ok(pair('rotated')); }
    return options.headers.Authorization === 'Bearer rotated-access' ? ok({ id: 'owner' }) : denied();
  });
  const first = await tab(0); const second = await tab(1);
  await expect(first.api.get('/auth/me')).rejects.toMatchObject({ code: 'SESSION_COORDINATION_UNAVAILABLE' });
  expect(db.committed().rotating).toEqual(expect.any(String));
  db.failCommit = false;
  await expect(second.api.get('/auth/me')).rejects.toMatchObject({ code: 'SESSION_REFRESH_UNCERTAIN' });
  expect(stores[1].getItem('refresh_token')).toBe('expired-refresh');
  expect(window.location.href).toBe('/settings');
  await expect(first.api.get('/auth/me')).resolves.toEqual({ id: 'owner' });
  await expect(second.api.get('/auth/me')).resolves.toEqual({ id: 'owner' });
  expect(rotations).toBe(1);
  expect(db.committed()).toEqual(pair('rotated'));
});

it('does not replay an uncertain refresh after a lost network response', async () => {
  fetchMock.mockImplementation(async url => {
    if (url.endsWith('/auth/refresh')) throw new TypeError('Synthetic lost response');
    return denied();
  });
  const first = await tab(0); const second = await tab(1);
  await expect(first.api.get('/auth/me')).rejects.toMatchObject({ code: 'SESSION_COORDINATION_UNAVAILABLE' });
  await expect(second.api.get('/auth/me')).rejects.toMatchObject({ code: 'SESSION_REFRESH_UNCERTAIN' });
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/auth/refresh'))).toHaveLength(1);
  expect(window.location.href).toBe('/settings');
});

it('logout immediately clears a pending refresh and its durable tombstone rejects a stale tab', async () => {
  const reply = deferred();
  fetchMock.mockImplementation(async url => url.endsWith('/auth/refresh') ? reply.promise : url.endsWith('/auth/logout') ? ok({}) : denied());
  const first = await tab(0); const second = await tab(1);
  const request = first.api.get('/auth/me');
  const failure = expect(request).rejects.toMatchObject({ code: 'AUTH_REQUIRED' });
  await vi.waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/auth/refresh'))).toHaveLength(1));
  const ending = first.logout();
  expect(stores[0].getItem('access_token')).toBeNull();
  reply.resolve(ok(pair('rotated')));
  await Promise.all([failure, ending]);
  await expect(second.api.get('/auth/me')).rejects.toMatchObject({ code: 'AUTH_REQUIRED' });
  expect(db.committed()).toBeNull();
  expect(stores.map(store => store.getItem('access_token'))).toEqual([null, null]);
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/auth/refresh'))).toHaveLength(1);
});

it('a new login supersedes an uncertain rotation for both renderer caches', async () => {
  fetchMock.mockImplementation(async (url, options) => {
    if (url.endsWith('/auth/refresh')) throw new TypeError('Synthetic lost response');
    if (url.endsWith('/auth/login')) return ok(pair('new-owner'));
    return options.headers.Authorization === 'Bearer new-owner-access' ? ok({ id: 'new-owner' }) : denied();
  });
  const first = await tab(0); const second = await tab(1);
  await expect(first.api.get('/auth/me')).rejects.toMatchObject({ code: 'SESSION_COORDINATION_UNAVAILABLE' });
  await second.login('new-owner', 'SyntheticPassword1', '123456');
  await expect(first.api.get('/auth/me')).resolves.toEqual({ id: 'new-owner' });
  expect(db.committed()).toEqual(pair('new-owner'));
  expect(JSON.parse(fetchMock.mock.calls.find(([url]) => url.endsWith('/auth/login'))[1].body).totp_code).toBe('123456');
});

it('a late previous-user 401 cannot erase the newly committed login', async () => {
  const late = deferred();
  let reads = 0;
  fetchMock.mockImplementation(async (url, options) => {
    if (url.endsWith('/auth/refresh')) return ok(pair('rotated'));
    if (url.endsWith('/auth/login')) return ok(pair('new-owner'));
    if (options.headers.Authorization === 'Bearer new-owner-access') return ok({ id: 'new-owner' });
    return ++reads === 1 ? denied() : late.promise;
  });
  const first = await tab(0); const second = await tab(1);
  const request = first.api.get('/auth/me');
  const failure = expect(request).rejects.toMatchObject({ code: 'AUTH_REQUIRED' });
  await vi.waitFor(() => expect(reads).toBe(2));
  await second.login('new-owner', 'SyntheticPassword1');
  late.resolve(denied()); await failure;
  expect(window.location.href).toBe('/settings');
  expect(stores[0].getItem('access_token')).toBe('new-owner-access');
  expect(db.committed()).toEqual(pair('new-owner'));
});

it('does not rotate or erase tokens when browser database access is unavailable', async () => {
  vi.stubGlobal('indexedDB', { open: () => { throw new Error('Synthetic storage restriction'); } });
  fetchMock.mockResolvedValue(denied());
  const first = await tab(0);
  await expect(first.api.get('/auth/me')).rejects.toMatchObject({ code: 'SESSION_COORDINATION_UNAVAILABLE' });
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(stores[0].getItem('refresh_token')).toBe('expired-refresh');
  expect(window.location.href).toBe('/settings');
});

it('reports a synchronous rotation-intent quota error without sending or consuming the token', async () => {
  db.throwPut = true;
  fetchMock.mockResolvedValue(denied());
  const first = await tab(0);
  await expect(first.api.get('/auth/me')).rejects.toMatchObject({ code: 'SESSION_COORDINATION_UNAVAILABLE' });
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(db.committed()).toEqual(pair('expired'));
  expect(stores[0].getItem('refresh_token')).toBe('expired-refresh');
});

it('explicit access-token invalidation with unchanged refresh still performs a real refresh', async () => {
  stores[0].setItem('access_token', 'expired-access.invalid');
  fetchMock.mockImplementation(async (url, options) => url.endsWith('/auth/refresh') ? ok(pair('rotated'))
    : options.headers.Authorization === 'Bearer rotated-access' ? ok({ id: 'owner' }) : denied());
  const first = await tab(0);
  await expect(first.api.get('/auth/me')).resolves.toEqual({ id: 'owner' });
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/auth/refresh'))).toHaveLength(1);
});

it('never publishes a modern rotation receipt missing its new refresh credential', async () => {
  fetchMock.mockImplementation(async url => url.endsWith('/auth/refresh') ? ok({ access_token: 'rotated-access' }) : denied());
  const first = await tab(0);
  await expect(first.api.get('/auth/me')).rejects.toMatchObject({ code: 'AUTH_REQUIRED' });
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(db.committed()).toBeNull();
  expect(stores[0].getItem('access_token')).toBeNull();
});

it('without Web Locks a newly committed actor wins over a pending old refresh response', async () => {
  vi.stubGlobal('navigator', {});
  const reply = deferred();
  fetchMock.mockImplementation(async (url, options) => {
    if (url.endsWith('/auth/refresh')) return reply.promise;
    if (url.endsWith('/auth/login')) return ok(pair('new-owner'));
    return options.headers.Authorization === 'Bearer new-owner-access' ? ok({ id: 'new-owner' }) : denied();
  });
  const first = await tab(0); const second = await tab(1);
  const pending = first.api.get('/auth/me');
  await vi.waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/auth/refresh'))).toHaveLength(1));
  await second.login('new-owner', 'SyntheticPassword1');
  reply.resolve(ok(pair('old-family')));
  await expect(pending).resolves.toEqual({ id: 'new-owner' });
  expect(db.committed()).toEqual(pair('new-owner'));
  expect(stores[0].getItem('access_token')).toBe('new-owner-access');
});

it('without Web Locks a committed logout cannot be overwritten by another tab refresh', async () => {
  vi.stubGlobal('navigator', {});
  const reply = deferred();
  fetchMock.mockImplementation(async url => url.endsWith('/auth/refresh') ? reply.promise : url.endsWith('/auth/logout') ? ok({}) : denied());
  const first = await tab(0); const second = await tab(1);
  const pending = first.api.get('/auth/me');
  const failure = expect(pending).rejects.toMatchObject({ code: 'AUTH_REQUIRED' });
  await vi.waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/auth/refresh'))).toHaveLength(1));
  await second.logout();
  reply.resolve(ok(pair('old-family'))); await failure;
  expect(db.committed()).toBeNull();
  expect(stores.map(store => store.getItem('access_token'))).toEqual([null, null]);
});

it('a login response pending at logout cannot publish an authenticated pair', async () => {
  const reply = deferred();
  fetchMock.mockImplementation(async url => url.endsWith('/auth/login') ? reply.promise : ok({}));
  const first = await tab(0);
  const pending = first.login('owner', 'SyntheticPassword1');
  const failure = expect(pending).rejects.toMatchObject({ code: 'AUTH_LOGIN_SUPERSEDED' });
  await first.logout(); reply.resolve(ok(pair('late-login'))); await failure;
  expect(db.committed()).toBeNull();
  expect(stores[0].getItem('access_token')).toBeNull();
});

it('rejects an old successful auth/me response after a different actor login commits', async () => {
  const body = deferred();
  fetchMock.mockImplementation(async url => url.endsWith('/auth/login') ? ok(pair('new-owner'))
    : { ok: true, status: 200, json: () => body.promise });
  const first = await tab(0); const second = await tab(1);
  const pending = first.api.get('/auth/me');
  const failure = expect(pending).rejects.toMatchObject({ code: 'AUTH_SESSION_CHANGED' });
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
  await second.login('new-owner', 'SyntheticPassword1');
  // Real Storage normally observes these writes; this assertion targets an
  // older successful response rather than renderer-visibility delay.
  stores[0].setItem('access_token', 'new-owner-access');
  stores[0].setItem('refresh_token', 'new-owner-refresh');
  body.resolve({ id: 'previous-owner' }); await failure;
  expect(db.committed()).toEqual(pair('new-owner'));
});

it('notifies actor/family changes from committed state but preserves same-family editors on rotation', async () => {
  const initial = jwtPair('owner-a', 'family-a');
  stores = [storage(initial), storage(initial)];
  db = database(initial); vi.stubGlobal('indexedDB', db);
  const listeners = new Map();
  vi.stubGlobal('window', {
    location: { href: '/settings' },
    addEventListener: (type, listener) => listeners.set(type, listener),
    removeEventListener: (type, listener) => { if (listeners.get(type) === listener) listeners.delete(type); },
    dispatchEvent: event => listeners.get(event.type)?.(event),
  });
  const rotated = jwtPair('owner-a', 'family-a', 2);
  const nextActor = jwtPair('owner-b', 'family-b');
  fetchMock.mockImplementation(async (url, options) => {
    if (url.endsWith('/auth/refresh')) return ok(rotated);
    if (url.endsWith('/auth/login')) return ok(nextActor);
    return options.headers.Authorization === `Bearer ${rotated.access_token}` ? ok({ id: 'owner-a' }) : denied();
  });
  const first = await tab(0); const second = await tab(1);
  const changed = vi.fn(); const stop = first.watchSessionChange(changed);
  await first.api.get('/auth/me');
  await listeners.get('storage')({ type: 'storage', key: 'refresh_token', newValue: rotated.refresh_token });
  expect(changed).not.toHaveBeenCalled();
  await second.login('owner-b', 'SyntheticPassword1');
  await vi.waitFor(() => expect(changed).toHaveBeenCalledOnce());
  expect(stores[0].getItem('access_token')).toBe(nextActor.access_token);
  stop(); expect(listeners.size).toBe(0);
});

it('a remote logout notifies and clears private state immediately without acquiring a blocked refresh lock', async () => {
  const listeners = new Map();
  vi.stubGlobal('window', {
    location: { href: '/settings' }, addEventListener: (type, listener) => listeners.set(type, listener), removeEventListener: () => {},
  });
  const first = await tab(0); const changed = vi.fn(); first.watchSessionChange(changed);
  const acquire = vi.fn(() => new Promise(() => {})); vi.stubGlobal('navigator', { locks: { request: acquire } });
  await listeners.get('storage')({ type: 'storage', key: 'access_token', newValue: null });
  expect(acquire).not.toHaveBeenCalled();
  expect(stores[0].getItem('access_token')).toBeNull(); expect(changed).toHaveBeenCalledOnce();
});

it('an unauthorized request after local logout cannot restore another committed session', async () => {
  db = database(pair('new-owner')); vi.stubGlobal('indexedDB', db);
  stores[0].removeItem('access_token'); stores[0].removeItem('refresh_token');
  fetchMock.mockResolvedValue(denied());
  const first = await tab(0);
  await expect(first.api.get('/auth/me')).rejects.toMatchObject({ code: 'AUTH_REQUIRED' });
  expect(stores[0].getItem('access_token')).toBeNull();
  expect(db.committed()).toEqual(pair('new-owner'));
  expect(fetchMock).toHaveBeenCalledOnce();
});

it('a removed session watcher cannot clear a newer login through a delayed callback', async () => {
  const listeners = new Map();
  vi.stubGlobal('window', { location: { href: '/settings' },
    addEventListener: (type, listener) => listeners.set(type, listener), removeEventListener: () => {} });
  const first = await tab(0); const changed = vi.fn(); const stop = first.watchSessionChange(changed);
  const delayed = listeners.get('storage'); stop();
  stores[0].setItem('access_token', 'new-owner-access');
  await delayed({ type: 'storage', key: 'access_token', newValue: null });
  expect(stores[0].getItem('access_token')).toBe('new-owner-access');
  expect(changed).not.toHaveBeenCalled();
});
