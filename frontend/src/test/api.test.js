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

describe('api.list', () => {
  const rows = (from, count) => Array.from({ length: count }, (_, i) => ({ id: `r${from + i}` }));
  const respond = (body) => ({ ok: true, status: 200, json: async () => body, headers: new Headers() });

  beforeEach(() => {
    vi.resetModules();
    mockFetch.mockReset();
    localStorageMock.clear();
  });

  it('loads every page instead of stopping at the server default of 100 rows', async () => {
    // Regression: lists showed 100 of 1060 bookings because pages called the API without paging.
    mockFetch.mockResolvedValueOnce(respond(rows(0, 1000))).mockResolvedValueOnce(respond(rows(1000, 60)));

    const { api } = await import('../api.js');
    const result = await api.list('/bookings');

    expect(result).toHaveLength(1060);
    expect(mockFetch.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/bookings?skip=0&limit=1000',
      '/api/v1/bookings?skip=1000&limit=1000',
    ]);
  });

  it('keeps filters and replaces paging parameters', async () => {
    mockFetch.mockResolvedValueOnce(respond(rows(0, 3)));

    const { api } = await import('../api.js');
    await api.list('/tenants?include_archived=true&limit=10');

    expect(mockFetch.mock.calls[0][0]).toBe('/api/v1/tenants?include_archived=true&limit=1000&skip=0');
  });

  it('stops when an endpoint ignores skip and repeats the same rows', async () => {
    mockFetch.mockResolvedValue(respond(rows(0, 1000)));

    const { api } = await import('../api.js');
    const result = await api.list('/integrations');

    expect(result).toHaveLength(1000);
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('passes non-list responses through', async () => {
    mockFetch.mockResolvedValueOnce(respond({ items: [] }));

    const { api } = await import('../api.js');
    expect(await api.list('/reports/summary')).toEqual({ items: [] });
  });
});

describe('validation errors', () => {
  beforeEach(() => {
    vi.resetModules();
    mockFetch.mockReset();
  });

  it('shows the messages of a validation error instead of its JSON', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({ detail: [{ type: 'value_error', loc: ['body', 'amount'], msg: 'Value error, Betrag darf nicht 0 sein' }] }),
      headers: new Headers(),
    });

    const { api } = await import('../api.js');
    await expect(api.post('/bookings', { amount: 0 })).rejects.toThrow(/^Betrag darf nicht 0 sein$/);
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
