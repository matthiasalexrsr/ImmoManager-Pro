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

  it('loads a protected Blob through token refresh without putting credentials in the URL', async () => {
    localStorageMock.setItem('access_token', 'expired-token');
    localStorageMock.setItem('refresh_token', 'refresh-token');
    const blob = new Blob(['private PDF'], { type: 'application/pdf' });
    mockFetch.mockResolvedValueOnce({ status: 401, ok: false })
      .mockResolvedValueOnce({ status: 200, ok: true, json: async () => ({ access_token: 'new-token', refresh_token: 'new-refresh' }) })
      .mockResolvedValueOnce({ status: 200, ok: true, blob: async () => blob });
    const { api } = await import('../api.js');
    expect(await api.getBlob('/files/download?key=documents%2Fprivate.pdf')).toBe(blob);
    expect(mockFetch.mock.calls[2][0]).toBe('/api/v1/files/download?key=documents%2Fprivate.pdf');
    expect(mockFetch.mock.calls[2][1].headers.Authorization).toBe('Bearer new-token');
    expect(mockFetch.mock.calls.flatMap(([url]) => url).join(' ')).not.toContain('token');
  });

  it('lets the browser set the multipart boundary while preserving upload authentication', async () => {
    localStorageMock.setItem('access_token', 'upload-token');
    mockFetch.mockResolvedValueOnce({ status: 201, ok: true, json: async () => ({ id: 'photo' }) });
    const { api } = await import('../api.js');
    const form = new FormData();
    form.append('file', new Blob(['image'], { type: 'image/png' }), 'photo.png');
    await api.postForm('/photos/upload?entity_type=unit&entity_id=1', form);
    expect(mockFetch.mock.calls[0][1].body).toBe(form);
    expect(mockFetch.mock.calls[0][1].headers.Authorization).toBe('Bearer upload-token');
    expect(mockFetch.mock.calls[0][1].headers['Content-Type']).toBeUndefined();
  });

  it('shares one token refresh between simultaneous protected-file and OCR requests', async () => {
    localStorageMock.setItem('access_token', 'expired-token');
    localStorageMock.setItem('refresh_token', 'refresh-token');
    let refreshCount = 0;
    const blob = new Blob(['file']);
    mockFetch.mockImplementation(async (url, options) => {
      if (url.endsWith('/auth/refresh')) {
        refreshCount += 1;
        return { ok: true, status: 200, json: async () => ({ access_token: 'valid-token' }) };
      }
      if (options.headers.Authorization === 'Bearer expired-token') return { ok: false, status: 401 };
      return { ok: true, status: 200, blob: async () => blob, json: async () => ({ has_ocr: false }) };
    });
    const { api } = await import('../api.js');
    const results = await Promise.all([api.getBlob('/files/download?key=file.pdf'), api.get('/files/ocr-text?file_url=file.pdf')]);
    expect(results).toEqual([blob, { has_ocr: false }]);
    expect(refreshCount).toBe(1);
    expect(localStorageMock.getItem('access_token')).toBe('valid-token');
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

  it('loads every page instead of truncating financial lists at the API default', async () => {
    const firstPage = Array.from({ length: 1000 }, (_, id) => ({ id }));
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => firstPage });
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => [{ id: 1000 }] });
    const { api } = await import('../api.js');
    const rows = await api.getAll('/rent-charges?status=open');
    expect(rows).toHaveLength(1001);
    expect(mockFetch.mock.calls[1][0]).toBe('/api/v1/rent-charges?status=open&skip=1000&limit=1000');
  });

  it('rejects malformed list responses instead of displaying an empty ledger', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => null });
    const { api } = await import('../api.js');
    await expect(api.getAll('/receivables')).rejects.toThrow('Ungültige Listenantwort');
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

describe('two-factor login', () => {
  beforeEach(() => {
    vi.resetModules();
    mockFetch.mockReset();
    localStorageMock.clear();
  });

  it('preserves the server challenge and submits an optional code', async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 401,
      headers: new Headers({ 'X-2FA-Required': 'true' }),
      json: async () => ({ error: { message: 'Code required', code: 'AUTH_FAILED' } }),
    }).mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ access_token: 'access', refresh_token: 'refresh' }) });
    const { login } = await import('../api.js');
    await expect(login('owner', 'Strong123')).rejects.toMatchObject({ requiresTwoFactor: true, statusCode: 401 });
    expect(localStorageMock.getItem('access_token')).toBeNull();
    await login('owner', 'Strong123', '123456');
    expect(JSON.parse(mockFetch.mock.calls[1][1].body)).toEqual({ username: 'owner', password: 'Strong123', totp_code: '123456' });
    expect(localStorageMock.getItem('access_token')).toBe('access');
  });
});
