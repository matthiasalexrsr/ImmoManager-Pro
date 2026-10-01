import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const response = value => ({ status: 200, ok: true, json: async () => value });
const unauthorized = () => ({ status: 401, ok: false });
const tokens = (access, refresh) => {
  localStorage.setItem('access_token', access); localStorage.setItem('refresh_token', refresh);
};
let fetchMock;

beforeEach(() => {
  vi.resetModules();
  localStorage.clear(); tokens('expired-access', 'initial-refresh');
  fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
  // Stub navigation only: the real token store is shared between module/tab instances.
  vi.stubGlobal('window', { location: { href: '/settings' } });
  vi.stubGlobal('navigator', {});
});
afterEach(() => { vi.unstubAllGlobals(); });

describe('session refresh coordination', () => {
  it('serializes two independent tabs through Web Locks and rereads the rotated pair before waiting tab sends', async () => {
    const firstReply = deferred(); let tail = Promise.resolve();
    const requestLock = vi.fn((name, callback) => {
      const task = tail.then(callback); tail = task.catch(() => {}); return task;
    });
    vi.stubGlobal('navigator', { locks: { request: requestLock } });
    const sent = [];
    fetchMock.mockImplementation(async (url, options) => {
      sent.push({ url, authorization: options.headers.Authorization });
      if (url.endsWith('/auth/refresh')) return firstReply.promise;
      return options.headers.Authorization === 'Bearer expired-access' ? unauthorized() : response({ id: url });
    });
    const firstTab = (await import('../api.js')).api;
    vi.resetModules();
    const secondTab = (await import('../api.js')).api;
    const first = firstTab.get('/portfolio-a'); const second = secondTab.get('/portfolio-b');
    await vi.waitFor(() => expect(requestLock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/auth/refresh'))).toHaveLength(1);
    firstReply.resolve(response({ access_token: 'rotated-access', refresh_token: 'rotated-refresh', token_type: 'bearer' }));
    expect(await Promise.all([first, second])).toEqual([{ id: '/api/v1/portfolio-a' }, { id: '/api/v1/portfolio-b' }]);
    expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/auth/refresh'))).toHaveLength(1);
    expect(requestLock.mock.calls.map(([name]) => name)).toEqual(['immomanager-token-refresh', 'immomanager-token-refresh']);
    expect(localStorage.getItem('refresh_token')).toBe('rotated-refresh');
    expect(sent.filter(call => call.authorization === 'Bearer rotated-access')).toHaveLength(2);
  });

  it('coalesces simultaneous requests in browsers without Web Locks', async () => {
    const reply = deferred();
    fetchMock.mockImplementation(async (url, options) => url.endsWith('/auth/refresh') ? reply.promise
      : options.headers.Authorization === 'Bearer expired-access' ? unauthorized() : response({ ok: true }));
    const { api } = await import('../api.js');
    const calls = [api.get('/a'), api.get('/b')];
    await vi.waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/auth/refresh'))).toHaveLength(1));
    reply.resolve(response({ access_token: 'new-access', refresh_token: 'new-refresh' }));
    expect(await Promise.all(calls)).toEqual([{ ok: true }, { ok: true }]);
  });

  it('does not overwrite a newer login while an old refresh response is pending', async () => {
    const reply = deferred();
    fetchMock.mockImplementation(async (url, options) => url.endsWith('/auth/refresh') ? reply.promise
      : options.headers.Authorization === 'Bearer expired-access' ? unauthorized() : response({ account: 'new-account' }));
    const { api } = await import('../api.js'); const pending = api.get('/auth/me');
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    tokens('new-account-access', 'new-account-refresh');
    reply.resolve(response({ access_token: 'old-family-access', refresh_token: 'old-family-refresh' }));
    expect(await pending).toEqual({ account: 'new-account' });
    expect(localStorage.getItem('access_token')).toBe('new-account-access');
    expect(localStorage.getItem('refresh_token')).toBe('new-account-refresh');
  });

  it('does not resurrect a logout with a pending refresh response', async () => {
    const reply = deferred();
    fetchMock.mockResolvedValueOnce(unauthorized()).mockReturnValueOnce(reply.promise);
    const { api } = await import('../api.js'); const pending = api.get('/auth/me');
    const result = expect(pending).rejects.toThrow('Nicht authentifiziert');
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    localStorage.clear(); reply.resolve(response({ access_token: 'old-family-access', refresh_token: 'old-family-refresh' }));
    await result;
    expect(localStorage.getItem('access_token')).toBeNull(); expect(localStorage.getItem('refresh_token')).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('does not clear a new login when a late retry from the previous account returns 401', async () => {
    const retry = deferred();
    fetchMock.mockResolvedValueOnce(unauthorized()).mockResolvedValueOnce(response({ access_token: 'old-rotated-access', refresh_token: 'old-rotated-refresh' }))
      .mockReturnValueOnce(retry.promise);
    const { api } = await import('../api.js'); const pending = api.get('/auth/me');
    const result = expect(pending).rejects.toThrow('Nicht authentifiziert');
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    tokens('new-account-access', 'new-account-refresh'); retry.resolve(unauthorized());
    await result;
    expect(localStorage.getItem('access_token')).toBe('new-account-access');
    expect(localStorage.getItem('refresh_token')).toBe('new-account-refresh');
    expect(window.location.href).toBe('/settings');
  });

  it.each([{ access_token: null }, { access_token: 'candidate', refresh_token: '' }, { detail: 'OK' }])('rejects malformed refresh receipts without retrying as authenticated: %j', async value => {
    fetchMock.mockResolvedValueOnce(unauthorized()).mockResolvedValueOnce(response(value));
    const { api } = await import('../api.js');
    await expect(api.get('/auth/me')).rejects.toThrow('Nicht authentifiziert');
    expect(fetchMock).toHaveBeenCalledTimes(2); expect(localStorage.getItem('access_token')).toBeNull();
  });

  it('fails closed if the browser rejects its refresh lock', async () => {
    vi.stubGlobal('navigator', { locks: { request: vi.fn().mockRejectedValue(new Error('Synthetic lock failure')) } });
    fetchMock.mockResolvedValueOnce(unauthorized());
    const { api } = await import('../api.js');
    await expect(api.get('/auth/me')).rejects.toThrow('Nicht authentifiziert');
    expect(fetchMock).toHaveBeenCalledOnce(); expect(localStorage.getItem('refresh_token')).toBeNull();
  });
});
