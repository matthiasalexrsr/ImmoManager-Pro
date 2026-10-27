import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const reply = (body = {}, status = 200) => ({ ok: status < 400, status, json: async () => body });
let fetchMock;
beforeEach(() => {
  vi.resetModules();
  localStorage.clear();
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

const calls = path => fetchMock.mock.calls.filter(([url]) => url.endsWith(path));

describe('refresh token in the HttpOnly cookie', () => {
  it('asks for the cookie at login and keeps no refresh token in the page', async () => {
    fetchMock.mockResolvedValue(reply({ access_token: 'access-1', refresh_token: null }));
    const { login } = await import('../api');
    await login('anna', 'geheim');
    const [, options] = calls('/auth/login')[0];
    expect(options.headers['X-Token-Transport']).toBe('cookie');
    expect(options.credentials).toBe('include');
    expect(localStorage.getItem('access_token')).toBe('access-1');
    expect(localStorage.getItem('refresh_token')).toBeNull();
  });

  it('renews by cookie without sending a token and moves an old stored one into the cookie', async () => {
    localStorage.setItem('access_token', 'expired');
    localStorage.setItem('refresh_token', 'stored-by-older-version');
    fetchMock.mockImplementation((url, options) => Promise.resolve(url.endsWith('/auth/refresh') ? reply({ access_token: 'access-2' })
      : options.headers.Authorization === 'Bearer access-2' || options.headers.Authorization === 'Bearer access-3' ? reply({ ok: true }) : reply({}, 401)));
    const { api } = await import('../api');
    await api.get('/things');
    expect(JSON.parse(calls('/auth/refresh')[0][1].body)).toEqual({ refresh_token: 'stored-by-older-version' });
    expect(localStorage.getItem('refresh_token')).toBeNull();                 // from now on only the cookie
    localStorage.setItem('access_token', 'expired-again');
    fetchMock.mockImplementation((url, options) => Promise.resolve(url.endsWith('/auth/refresh') ? reply({ access_token: 'access-3' })
      : options.headers.Authorization === 'Bearer access-3' ? reply({ ok: true }) : reply({}, 401)));
    await api.get('/things');
    const [, second] = calls('/auth/refresh').at(-1);
    expect(JSON.parse(second.body)).toEqual({});
    expect(second.headers['X-Token-Transport']).toBe('cookie');
    expect(localStorage.getItem('access_token')).toBe('access-3');
  });

  it('tries the rotated cookie once more when another window renewed at the same moment', async () => {
    localStorage.setItem('access_token', 'expired');
    let refreshes = 0;
    fetchMock.mockImplementation((url, options) => {
      if (url.endsWith('/auth/refresh')) return Promise.resolve(++refreshes === 1 ? reply({}, 401) : reply({ access_token: 'access-4' }));
      return Promise.resolve(options.headers.Authorization === 'Bearer access-4' ? reply({ ok: true }) : reply({}, 401));
    });
    const { api } = await import('../api');
    await expect(api.get('/things')).resolves.toEqual({ ok: true });
    expect(refreshes).toBe(2);
  });

  it('does not try to renew when nobody is signed in', async () => {
    fetchMock.mockResolvedValue(reply({}, 401));
    const { api } = await import('../api');
    await api.get('/things').catch(() => {});
    expect(calls('/auth/refresh')).toHaveLength(0);
  });
});
