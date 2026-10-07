import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

const reply = (body = {}, status = 200) => ({ ok: status < 400, status, json: async () => body });
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
let fetchMock;
beforeEach(() => {
  vi.resetModules();
  localStorage.clear();
  localStorage.setItem('access_token', 'old-access');
  localStorage.setItem('refresh_token', 'old-refresh');
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); window.history.replaceState({}, '', '/'); });

describe('coordinated session lifecycle', () => {
  it('deduplicates concurrent refreshes before retrying protected requests', async () => {
    const refresh = deferred();
    fetchMock.mockImplementation((url, options) => url.endsWith('/auth/refresh') ? refresh.promise
      : Promise.resolve(reply({}, options.headers.Authorization === 'Bearer old-access' ? 401 : 200)));
    const { api } = await import('../api');
    const one = api.get('/auth/me');
    const two = api.get('/photos');
    await vi.waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/auth/refresh'))).toHaveLength(1));
    refresh.resolve(reply({ access_token: 'new-access', refresh_token: 'new-refresh' }));
    await Promise.all([one, two]);
    expect(localStorage.getItem('access_token')).toBe('new-access');
    expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/auth/refresh'))).toHaveLength(1);
  });

  it('retains local credentials after failed logout and supports confirmed retry', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('offline')).mockResolvedValueOnce(reply());
    const { logout } = await import('../api');
    await expect(logout()).rejects.toThrow();
    expect(localStorage.getItem('access_token')).toBe('old-access');
    await logout();
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(localStorage.getItem('refresh_token')).toBeNull();
  });

  it('clears the server file cookie even when local tokens are absent', async () => {
    localStorage.clear();
    fetchMock.mockResolvedValue(reply());
    const { logout } = await import('../api');
    await logout();
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/logout', expect.objectContaining({ method: 'POST' }));
  });

  it('waits for an in-flight refresh and revokes its newest tokens before completing logout', async () => {
    const refresh = deferred();
    fetchMock.mockImplementation(url => url.endsWith('/auth/refresh') ? refresh.promise
      : Promise.resolve(reply({}, url.endsWith('/auth/logout') ? 200 : 401)));
    const { api, logout } = await import('../api');
    const read = api.get('/auth/me').catch(error => error);
    await vi.waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/auth/refresh'))).toBe(true));
    const leaving = logout();
    expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/auth/logout'))).toBe(false);
    refresh.resolve(reply({ access_token: 'new-access', refresh_token: 'new-refresh' }));
    await leaving;
    await read;
    const [, options] = fetchMock.mock.calls.find(([url]) => url.endsWith('/auth/logout'));
    expect(JSON.parse(options.body)).toEqual({ access_token: 'new-access', refresh_token: 'new-refresh' });
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/auth/refresh'))).toHaveLength(1);
  });

  it('does not accept unsuccessful logout HTTP responses as completion', async () => {
    fetchMock.mockResolvedValue(reply({ detail: 'Abmeldung derzeit nicht möglich' }, 503));
    const { logout } = await import('../api');
    await expect(logout()).rejects.toThrow();
    expect(localStorage.getItem('refresh_token')).toBe('old-refresh');
  });

  it.each(['unavailable', 'offline'])('keeps credentials after a temporary refresh failure: %s', async failure => {
    fetchMock.mockImplementation(url => url.endsWith('/auth/refresh')
      ? failure === 'offline' ? Promise.reject(new TypeError('offline')) : Promise.resolve(reply({}, 503))
      : Promise.resolve(reply({}, url.endsWith('/auth/logout') ? 200 : 401)));
    const { api } = await import('../api');
    await expect(api.get('/auth/me')).rejects.toThrow();
    expect(localStorage.getItem('refresh_token')).toBe('old-refresh');
    expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/auth/logout'))).toBe(false);
  });

  it('still confirms explicit logout after its pending refresh fails temporarily', async () => {
    const refresh = deferred();
    fetchMock.mockImplementation(url => url.endsWith('/auth/refresh') ? refresh.promise
      : Promise.resolve(reply({}, url.endsWith('/auth/logout') ? 200 : 401)));
    const { api, logout } = await import('../api');
    const read = api.get('/auth/me').catch(error => error);
    await vi.waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/auth/refresh'))).toBe(true));
    const leaving = logout();
    refresh.resolve(reply({}, 503));
    await leaving;
    await read;
    expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/auth/logout'))).toBe(true);
    expect(localStorage.getItem('access_token')).toBeNull();
  });

  it('ends a rejected session only after the server confirms cookie deletion', async () => {
    window.history.replaceState({}, '', '/login');
    fetchMock.mockImplementation(url => Promise.resolve(reply({}, url.endsWith('/auth/logout') ? 200 : 401)));
    const { api } = await import('../api');
    await expect(api.get('/auth/me')).rejects.toThrow('Nicht authentifiziert');
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(['/api/v1/auth/me', '/api/v1/auth/refresh', '/api/v1/auth/logout']);
    expect(localStorage.getItem('access_token')).toBeNull();
  });

  it('retains credentials if a terminal 401 cannot confirm server logout', async () => {
    fetchMock.mockImplementation(url => Promise.resolve(reply({}, url.endsWith('/auth/logout') ? 503 : 401)));
    const { api } = await import('../api');
    await expect(api.get('/auth/me')).rejects.toThrow('Abmeldung ist fehlgeschlagen');
    expect(localStorage.getItem('refresh_token')).toBe('old-refresh');
  });

  it('discards a response body completed after logout', async () => {
    const body = deferred();
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: () => body.promise }).mockResolvedValue(reply());
    const { api, logout } = await import('../api');
    const read = api.get('/auth/me').catch(error => error);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await logout();
    body.resolve({ id: 'old-reader' });
    expect(await read).toBeInstanceOf(Error);
  });

  it('sends session requests only to the configured backend, with cookies enabled there', async () => {
    vi.stubEnv('VITE_API_URL', 'https://backend.example/api/v1');
    fetchMock.mockResolvedValue(reply());
    const { api } = await import('../api');
    await api.get('/auth/me');
    expect(fetchMock).toHaveBeenCalledWith('https://backend.example/api/v1/auth/me', expect.objectContaining({ credentials: 'include', headers: expect.objectContaining({ Authorization: 'Bearer old-access' }) }));
  });
});
