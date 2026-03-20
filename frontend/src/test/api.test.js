import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

// Mock localStorage
const localStorageMock = (() => {
  let store = {};
  return {
    getItem: vi.fn((key) => store[key] ?? null),
    setItem: vi.fn((key, value) => { store[key] = String(value); }),
    removeItem: vi.fn((key) => { delete store[key]; }),
    clear: vi.fn(() => { store = {}; }),
  };
})();
Object.defineProperty(global, 'localStorage', { value: localStorageMock });

describe('API client', () => {
  beforeEach(() => {
    vi.resetModules();
    mockFetch.mockReset();
    localStorageMock.clear();
  });

  it('should include auth token in request headers', async () => {
    localStorageMock.setItem('access_token', 'test-jwt-123');

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ([]),
      headers: new Headers(),
    });

    const { api } = await import('../api.js');
    await api.get('/portfolios');

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, options] = mockFetch.mock.calls[0];
    expect(url).toBe('/api/v1/portfolios');
    expect(options.headers['Authorization']).toBe('Bearer test-jwt-123');
  });

  it('should not include auth header when no token is stored', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({}),
      headers: new Headers(),
    });

    const { api } = await import('../api.js');
    await api.get('/auth/me');

    const [, options] = mockFetch.mock.calls[0];
    expect(options.headers['Authorization']).toBeUndefined();
  });

  it('should throw on non-ok responses', async () => {
    localStorageMock.setItem('access_token', 'tok');

    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({ detail: 'Forbidden' }),
      headers: new Headers(),
    });

    const { api } = await import('../api.js');
    await expect(api.get('/admin/version')).rejects.toThrow();
  });
});

describe('isLoggedIn', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorageMock.clear();
  });

  it('returns true when access_token exists', async () => {
    localStorageMock.setItem('access_token', 'some-token');
    const { isLoggedIn } = await import('../api.js');
    expect(isLoggedIn()).toBe(true);
  });

  it('returns false when no token', async () => {
    const { isLoggedIn } = await import('../api.js');
    expect(isLoggedIn()).toBe(false);
  });
});
