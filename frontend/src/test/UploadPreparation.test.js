import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const get = vi.hoisted(() => vi.fn());
vi.mock('../api', () => ({ api: { get } }));
const deferred = () => { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
beforeEach(() => { vi.resetModules(); get.mockReset(); localStorage.setItem('access_token', 'session-a'); });
afterEach(() => { vi.unstubAllEnvs(); localStorage.clear(); });

it('shares only active preparations and does not reuse successful checks after later actions', async () => {
  const first = deferred();
  get.mockReturnValueOnce(first.promise).mockResolvedValue({});
  const { prepareUploadAccess } = await import('../utils/uploadAccess');
  const a = prepareUploadAccess('/uploads/a.png');
  const b = prepareUploadAccess('/uploads/b.pdf');
  expect(get).toHaveBeenCalledTimes(1);
  first.resolve({});
  await Promise.all([a, b]);
  await prepareUploadAccess('/uploads/a.png');
  expect(get).toHaveBeenCalledTimes(2);
});

it('aborts one participant without cancelling a different viewer that still needs the session', async () => {
  const check = deferred();
  get.mockReturnValue(check.promise);
  const { prepareUploadAccess } = await import('../utils/uploadAccess');
  const owner = new AbortController();
  const a = prepareUploadAccess('/uploads/a.png', { signal: owner.signal }).catch(error => error);
  const b = prepareUploadAccess('/uploads/b.pdf');
  owner.abort();
  expect((await a).name).toBe('AbortError');
  expect(get.mock.calls[0][1].signal.aborted).toBe(false);
  check.resolve({});
  await b;
});

it('cancels an abandoned check and starts fresh even if the old network response is late', async () => {
  const old = deferred();
  get.mockReturnValueOnce(old.promise).mockResolvedValue({});
  const { prepareUploadAccess } = await import('../utils/uploadAccess');
  const owner = new AbortController();
  const a = prepareUploadAccess('/uploads/a.png', { signal: owner.signal }).catch(error => error);
  owner.abort();
  expect((await a).name).toBe('AbortError');
  expect(get.mock.calls[0][1].signal.aborted).toBe(true);
  await prepareUploadAccess('/uploads/b.pdf');
  expect(get).toHaveBeenCalledTimes(2);
  old.resolve({});
});

it('prepares the renewed token and rejects an old check after local logout', async () => {
  get.mockImplementationOnce(async () => { localStorage.setItem('access_token', 'session-b'); }).mockResolvedValue({});
  const { prepareUploadAccess } = await import('../utils/uploadAccess');
  await prepareUploadAccess('/uploads/a.png');
  expect(get).toHaveBeenCalledTimes(2);
  get.mockImplementationOnce(async () => { localStorage.clear(); });
  await expect(prepareUploadAccess('/uploads/a.png')).rejects.toThrow('geändert');
});

it('prepares only uploads on the explicitly configured backend origin', async () => {
  vi.stubEnv('VITE_API_URL', 'https://backend.example/api/v1');
  get.mockResolvedValue({});
  const { prepareUploadAccess, isOwnUploadUrl } = await import('../utils/uploadAccess');
  expect(isOwnUploadUrl('https://backend.example/uploads/a.pdf')).toBe(true);
  expect(isOwnUploadUrl('https://backend.example.evil.test/uploads/a.pdf')).toBe(false);
  expect(isOwnUploadUrl('https://backend.example/other/a.pdf')).toBe(false);
  await prepareUploadAccess('https://outside.example/uploads/a.pdf?sig=unchanged');
  expect(get).not.toHaveBeenCalled();
  await prepareUploadAccess('https://backend.example/uploads/a.pdf');
  expect(get).toHaveBeenCalledWith('/auth/me', expect.objectContaining({ signal: expect.any(AbortSignal) }));
});
