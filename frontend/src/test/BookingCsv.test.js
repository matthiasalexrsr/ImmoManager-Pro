import { ReadableStream, WritableStream } from 'node:stream/web';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { streamBookingCsv } from '../utils/bookingCsv';

const get = vi.hoisted(() => vi.fn());
vi.mock('../api', () => ({ api: { get } }));
let bytes, abort, writable;
beforeEach(() => {
  bytes = []; abort = vi.fn(); get.mockReset();
  localStorage.setItem('access_token', 'synthetic-original');
  writable = new WritableStream({ write: chunk => bytes.push(...chunk), abort });
  vi.stubGlobal('showSaveFilePicker', vi.fn(async () => ({ createWritable: async () => writable })));
});
afterEach(() => vi.unstubAllGlobals());
const body = () => new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array([65, 66, 67])); controller.close(); } });

it('streams directly to the file with same-origin Bearer headers, without buffering a Blob or exposing the token in the URL', async () => {
  const fetch = vi.fn(async () => ({ ok: true, status: 200, body: body(), blob: vi.fn(() => { throw new Error('Must not buffer'); }) }));
  vi.stubGlobal('fetch', fetch);
  await streamBookingCsv('/bookings/export.csv?search=Miete');
  expect(bytes).toEqual([65, 66, 67]);
  expect(fetch.mock.calls[0][0]).toBe('/api/v1/bookings/export.csv?search=Miete');
  expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer synthetic-original');
  expect(get).not.toHaveBeenCalled(); expect(abort).not.toHaveBeenCalled();
});

it('uses the existing serialized refresh flow and retries the same download once with the renewed token', async () => {
  get.mockImplementation(async () => { localStorage.setItem('access_token', 'synthetic-renewed'); });
  const fetch = vi.fn().mockResolvedValueOnce({ status: 401 }).mockResolvedValueOnce({ ok: true, status: 200, body: body() });
  vi.stubGlobal('fetch', fetch);
  await streamBookingCsv('/bookings/export.csv?status=booked');
  expect(get).toHaveBeenCalledWith('/auth/me', { signal: undefined });
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls.map(([path]) => path)).toEqual(['/api/v1/bookings/export.csv?status=booked', '/api/v1/bookings/export.csv?status=booked']);
  expect(fetch.mock.calls[1][1].headers.Authorization).toBe('Bearer synthetic-renewed');
});

it('aborts the pending file on download failure and propagates the actual error for retry', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({ error: { message: 'Snapshot unavailable' } }) })));
  await expect(streamBookingCsv('/bookings/export.csv?')).rejects.toThrow('Snapshot unavailable');
  expect(abort).toHaveBeenCalledOnce();
});

it('rejects an external path before opening a file or sending credentials', async () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  await expect(streamBookingCsv('https://example.invalid/export.csv')).rejects.toThrow('Ungültiger Exportpfad');
  expect(fetch).not.toHaveBeenCalled(); expect(window.showSaveFilePicker).not.toHaveBeenCalled();
});

it('does not retry a network failure', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Connection lost')));
  await expect(streamBookingCsv('/bookings/export.csv?')).rejects.toThrow('Connection lost');
  expect(get).not.toHaveBeenCalled(); expect(abort).toHaveBeenCalledOnce();
});

it('stops after a second unauthorized response and aborts the file instead of retrying forever', async () => {
  const fetch = vi.fn(async () => ({ ok: false, status: 401, json: async () => ({ error: { message: 'Session expired' } }) }));
  vi.stubGlobal('fetch', fetch); get.mockResolvedValue({});
  await expect(streamBookingCsv('/bookings/export.csv?')).rejects.toThrow('Session expired');
  expect(fetch).toHaveBeenCalledTimes(2); expect(get).toHaveBeenCalledOnce(); expect(abort).toHaveBeenCalledOnce();
});

it('propagates cancellation to the native stream and aborts the writable file', async () => {
  const controller = new AbortController(); controller.abort();
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, body: body() })));
  await expect(streamBookingCsv('/bookings/export.csv?', { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' });
  expect(abort).toHaveBeenCalledOnce(); expect(get).not.toHaveBeenCalled();
});
