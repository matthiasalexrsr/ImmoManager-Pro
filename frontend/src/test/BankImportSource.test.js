import { ReadableStream, WritableStream } from 'node:stream/web';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { streamBankOriginal } from '../utils/bankImportSource';

const get = vi.hoisted(() => vi.fn());
vi.mock('../api', () => ({ api: { get } }));
let bytes, abort, writable;
const path = '/bookings/imports/synthetic-source/source';
beforeEach(() => {
  bytes = []; abort = vi.fn(); get.mockReset();
  localStorage.setItem('access_token', 'synthetic-original');
  writable = new WritableStream({ write: chunk => bytes.push(...chunk), abort });
  vi.stubGlobal('showSaveFilePicker', vi.fn(async () => ({ createWritable: async () => writable })));
});
afterEach(() => vi.unstubAllGlobals());
const body = () => new ReadableStream({ start(controller) {
  controller.enqueue(new Uint8Array([0, 65, 255]));
  controller.enqueue(new Uint8Array([66, 67])); controller.close();
} });

it('preserves original bytes through a native stream and keeps credentials in same-origin headers', async () => {
  const fetch = vi.fn(async () => ({ ok: true, status: 200, body: body(),
    blob: vi.fn(() => { throw new Error('Must not buffer'); }) }));
  vi.stubGlobal('fetch', fetch);
  await streamBankOriginal(path, 'Kontoauszug Ä.sta');
  expect(window.showSaveFilePicker).toHaveBeenCalledWith({ suggestedName: 'Kontoauszug Ä.sta' });
  expect(bytes).toEqual([0, 65, 255, 66, 67]);
  expect(fetch).toHaveBeenCalledWith(`/api/v1${path}`, { signal: undefined,
    headers: { Authorization: 'Bearer synthetic-original' } });
  expect(abort).not.toHaveBeenCalled(); expect(get).not.toHaveBeenCalled();
});

it.each(['https://example.invalid/source', '/bookings/imports/job/source?token=secret',
  '/bookings/imports/../source', '/accounts/id/source'])('rejects unsafe paths before opening a file: %s', async invalid => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  await expect(streamBankOriginal(invalid, 'statement.sta')).rejects.toThrow('bankImport.invalidResponse');
  expect(fetch).not.toHaveBeenCalled(); expect(window.showSaveFilePicker).not.toHaveBeenCalled();
});

it('refreshes once and retries the same original with the renewed credential', async () => {
  get.mockImplementation(async () => { localStorage.setItem('access_token', 'synthetic-renewed'); });
  const fetch = vi.fn().mockResolvedValueOnce({ status: 401 })
    .mockResolvedValueOnce({ ok: true, status: 200, body: body() });
  vi.stubGlobal('fetch', fetch);
  await streamBankOriginal(path, 'statement.sta');
  expect(get).toHaveBeenCalledWith('/auth/me', { signal: undefined });
  expect(fetch.mock.calls.map(([url]) => url)).toEqual([`/api/v1${path}`, `/api/v1${path}`]);
  expect(fetch.mock.calls[1][1].headers.Authorization).toBe('Bearer synthetic-renewed');
});

it('aborts the destination and preserves a fresh permission error', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 403,
    json: async () => ({ error: { message: 'Account permission changed' } }) })));
  await expect(streamBankOriginal(path, 'statement.sta')).rejects.toThrow('Account permission changed');
  expect(bytes).toEqual([]); expect(abort).toHaveBeenCalledOnce();
});

it('does not retry or replace a destination after a mid-stream failure', async () => {
  const failure = new Error('Original stream interrupted');
  const responseBody = new ReadableStream({ start(controller) { controller.error(failure); } });
  const fetch = vi.fn(async () => ({ ok: true, status: 200, body: responseBody }));
  vi.stubGlobal('fetch', fetch);
  await expect(streamBankOriginal(path, 'statement.sta')).rejects.toThrow('Original stream interrupted');
  expect(fetch).toHaveBeenCalledOnce(); expect(abort).toHaveBeenCalledOnce();
  expect(get).not.toHaveBeenCalled();
});

it('cancels the writable destination when the owning view is aborted', async () => {
  const controller = new AbortController(); controller.abort();
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, body: body() })));
  await expect(streamBankOriginal(path, 'statement.sta', { signal: controller.signal }))
    .rejects.toMatchObject({ name: 'AbortError' });
  expect(abort).toHaveBeenCalledOnce(); expect(get).not.toHaveBeenCalled();
});
