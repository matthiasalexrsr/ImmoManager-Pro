import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const jwt = (sub, jti = 'original') => `${btoa('{}')}.${btoa(JSON.stringify({ sub, jti }))}.synthetic`;
const reply = (body = {}, status = 200) => ({ ok: status < 400, status, json: async () => body });
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
let api, logout, identity, fetchMock;
beforeEach(async () => {
  vi.resetModules();
  localStorage.clear();
  localStorage.setItem('access_token', jwt('account-a'));
  localStorage.setItem('refresh_token', jwt('account-a', 'refresh'));
  fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
  ({ api, logout } = await import('../api'));
  identity = await import('../utils/workspaceIdentity');
  identity.setWorkspaceOwner('account-a');
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); localStorage.clear(); identity.setWorkspaceOwner(null); });

it('blocks an old editor before sending when another tab changed accounts, retaining private recovery data', async () => {
  localStorage.setItem('workspace:account-a:draft-buffer:contacts', 'private A draft');
  localStorage.setItem('access_token', jwt('account-b'));
  localStorage.setItem('refresh_token', jwt('account-b', 'refresh'));
  await expect(api.put('/workspace/drafts/new-draft', { values: { name: 'Private A' } })).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
  expect(fetchMock).not.toHaveBeenCalled();
  expect(localStorage.getItem('access_token')).toBe(jwt('account-b'));
  expect(localStorage.getItem('workspace:account-a:draft-buffer:contacts')).toBe('private A draft');
});

it('never replays an A write with B credentials after a pending 401', async () => {
  const response = deferred(); fetchMock.mockReturnValue(response.promise);
  const write = api.post('/workspace/recents/events', { kind: 'tenant', entity_id: 'private-a' });
  const rejected = expect(write).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
  localStorage.setItem('access_token', jwt('account-b'));
  response.resolve(reply({}, 401));
  await rejected;
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe(`Bearer ${jwt('account-a')}`);
});

it('rejects a response body completed after the account changes', async () => {
  const body = deferred(); fetchMock.mockResolvedValue({ ok: true, status: 200, json: () => body.promise });
  const read = api.get('/workspace/drafts');
  const rejected = expect(read).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  localStorage.setItem('access_token', jwt('account-b'));
  body.resolve({ items: [{ values: { name: 'Private A' } }] });
  await rejected;
});

it('allows another tab to rotate the token for the same owner before a 401 retry', async () => {
  const response = deferred(); fetchMock.mockReturnValueOnce(response.promise).mockResolvedValue(reply({ saved: true }));
  const write = api.put('/workspace/drafts/a-draft', { values: { name: 'Private A' } });
  localStorage.setItem('access_token', jwt('account-a', 'rotated'));
  response.resolve(reply({}, 401));
  await expect(write).resolves.toEqual({ saved: true });
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe(`Bearer ${jwt('account-a', 'rotated')}`);
});

it('continues a signed-subject-preserving refresh', async () => {
  fetchMock.mockImplementation((url, options) => Promise.resolve(url.endsWith('/auth/refresh')
    ? reply({ access_token: jwt('account-a', 'renewed'), refresh_token: jwt('account-a', 'renewed-refresh') })
    : reply({ saved: true }, options.headers.Authorization === `Bearer ${jwt('account-a')}` ? 401 : 200)));
  await expect(api.put('/workspace/drafts/a-draft', { values: { name: 'Private A' } })).resolves.toEqual({ saved: true });
  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(identity.workspaceOwner()).toBe('account-a');
});

it('does not overwrite B tokens with an A refresh completing after the switch', async () => {
  const refresh = deferred();
  fetchMock.mockImplementation(url => url.endsWith('/auth/refresh') ? refresh.promise : Promise.resolve(reply({}, 401)));
  const read = api.get('/workspace/drafts');
  const rejected = expect(read).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
  await vi.waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/auth/refresh'))).toBe(true));
  localStorage.setItem('access_token', jwt('account-b'));
  localStorage.setItem('refresh_token', jwt('account-b', 'refresh'));
  refresh.resolve(reply({ access_token: jwt('account-a', 'renewed'), refresh_token: jwt('account-a', 'renewed-refresh') }));
  await rejected;
  expect(localStorage.getItem('access_token')).toBe(jwt('account-b'));
  expect(localStorage.getItem('refresh_token')).toBe(jwt('account-b', 'refresh'));
});

it('blocks a network retry after an account switch', async () => {
  vi.useFakeTimers(); fetchMock.mockRejectedValue(new TypeError('offline'));
  const read = api.get('/workspace/drafts');
  const rejected = expect(read).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
  await Promise.resolve(); await Promise.resolve();
  localStorage.setItem('access_token', jwt('account-b'));
  await vi.advanceTimersByTimeAsync(1000);
  await rejected;
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('keeps multipart boundaries browser-owned and refuses an upload before first send under B', async () => {
  const form = new FormData(); form.append('file', new Blob(['synthetic A document']), 'synthetic.txt');
  fetchMock.mockResolvedValue(reply({ saved: true }));
  await expect(api.upload('/documents/upload', form)).resolves.toEqual({ saved: true });
  const [, options] = fetchMock.mock.calls[0];
  expect(options.body).toBe(form);
  expect(options.headers).not.toHaveProperty('Content-Type');
  expect(options.headers.Authorization).toBe(`Bearer ${jwt('account-a')}`);
  localStorage.setItem('access_token', jwt('account-b'));
  await expect(api.upload('/documents/upload', form)).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('rejects a multipart result completed after the account switch', async () => {
  const response = deferred(); fetchMock.mockReturnValue(response.promise);
  const form = new FormData(); form.append('file', new Blob(['synthetic A document']), 'synthetic.txt');
  const upload = api.upload('/documents/upload', form);
  const rejected = expect(upload).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
  localStorage.setItem('access_token', jwt('account-b'));
  response.resolve(reply({ file_url: '/uploads/synthetic-a.txt' }));
  await rejected;
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('keeps a multi-step operation bound to A even after B has been verified for new work', async () => {
  const current = api.captureSession();
  localStorage.setItem('access_token', jwt('account-b'));
  fetchMock.mockResolvedValue(reply({ id: 'account-b' }));
  await expect(api.get('/auth/me')).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
  expect(fetchMock).not.toHaveBeenCalled();
  await api.get('/auth/me', { sessionBootstrap: true });
  identity.setWorkspaceOwner('account-b');
  fetchMock.mockResolvedValue(reply({ saved: true }));
  await expect(api.put('/workspace/drafts/b-draft', { values: { name: 'Private B' } })).resolves.toEqual({ saved: true });
  expect(current).toThrow();
  await expect(api.put('/workspace/drafts/b-draft', { values: { name: 'Private B updated' } })).resolves.toEqual({ saved: true });
  expect(fetchMock.mock.calls.at(-1)[1].headers.Authorization).toBe(`Bearer ${jwt('account-b')}`);
});

it('rejects an old account error whose response body finishes after switching', async () => {
  const body = deferred(); fetchMock.mockResolvedValue({ ok: false, status: 409, json: () => body.promise });
  const write = api.put('/workspace/drafts/a-draft', { values: { name: 'Private A' } });
  const rejected = expect(write).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  localStorage.setItem('access_token', jwt('account-b'));
  body.resolve({ detail: 'Private A conflict details' });
  await rejected;
});

it('does not send an old editor logout with B credentials', async () => {
  localStorage.setItem('access_token', jwt('account-b'));
  localStorage.setItem('refresh_token', jwt('account-b', 'refresh'));
  await expect(logout()).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
  expect(fetchMock).not.toHaveBeenCalled();
  expect(localStorage.getItem('access_token')).toBe(jwt('account-b'));
});

it('preserves B credentials when an already-sent A logout finishes later', async () => {
  const response = deferred(); fetchMock.mockReturnValue(response.promise);
  const leaving = logout();
  expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe(`Bearer ${jwt('account-a')}`);
  localStorage.setItem('access_token', jwt('account-b'));
  localStorage.setItem('refresh_token', jwt('account-b', 'refresh'));
  response.resolve(reply());
  await leaving;
  expect(localStorage.getItem('access_token')).toBe(jwt('account-b'));
  expect(localStorage.getItem('refresh_token')).toBe(jwt('account-b', 'refresh'));
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
