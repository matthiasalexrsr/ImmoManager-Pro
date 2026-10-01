import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useFinanceData } from '../hooks/useFinanceData';

const mocks = vi.hoisted(() => ({ getAll: vi.fn() }));
vi.mock('../api', () => ({ api: mocks }));
const sources = { items: '/bookings', accounts: '/accounts' };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
beforeEach(() => mocks.getAll.mockReset().mockImplementation(async path => [{ id: path }]));

describe('useFinanceData', () => {
  it('preserves error context, cancels siblings, and clears errors after a retry', async () => {
    const cause = Object.assign(new Error('Reference failed'), { requestId: 'request-123', code: 'DB_ERROR' });
    mocks.getAll.mockImplementation(path => path === '/accounts' ? Promise.reject(cause) : new Promise(() => {}));
    const { result } = renderHook(() => useFinanceData(sources));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toMatchObject({ message: 'Reference failed', endpoint: '/accounts', requestId: 'request-123', code: 'DB_ERROR' });
    expect(result.current.data).toEqual({ items: [], accounts: [] });
    expect(mocks.getAll.mock.calls.every(([, { signal }]) => signal.aborted)).toBe(true);
    mocks.getAll.mockResolvedValue([{ id: 'restored' }]);
    await act(async () => { expect(await result.current.reload()).toBe(true); });
    expect(result.current.error).toBeNull();
    expect(result.current.data.items).toEqual([{ id: 'restored' }]);
  });

  it.each([null, {}, 'not a list'])('rejects malformed responses: %j', async rows => {
    mocks.getAll.mockResolvedValue(rows);
    const { result } = renderHook(() => useFinanceData(sources));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error.message).toContain('Ungültige Listenantwort');
    expect(result.current.data.items).toEqual([]);
  });

  it('aborts on unmount and does not restart requests after a delayed mutation', async () => {
    const pending = deferred();
    mocks.getAll.mockReturnValue(pending.promise);
    const { result, unmount } = renderHook(() => useFinanceData(sources));
    const reload = result.current.reload;
    const signals = mocks.getAll.mock.calls.map(([, options]) => options.signal);
    unmount();
    expect(signals.every(signal => signal.aborted)).toBe(true);
    expect(await reload()).toBe(false);
    expect(mocks.getAll).toHaveBeenCalledTimes(2);
    await act(async () => { pending.resolve([{ id: 'too late' }]); });
  });

  it('ignores late success from an earlier request, including its loading state', async () => {
    const old = deferred();
    const current = deferred();
    mocks.getAll.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const { result } = renderHook(() => useFinanceData({ items: '/bookings' }));
    let refreshed;
    act(() => { refreshed = result.current.reload(); });
    expect(mocks.getAll.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => { old.resolve([{ id: 'stale' }]); });
    expect(result.current.loading).toBe(true);
    expect(result.current.data.items).toEqual([]);
    await act(async () => { current.resolve([{ id: 'fresh' }]); await refreshed; });
    expect(result.current.data.items).toEqual([{ id: 'fresh' }]);
  });

  it('ignores late failure from a superseded request', async () => {
    const old = deferred();
    mocks.getAll.mockReturnValueOnce(old.promise);
    const { result } = renderHook(() => useFinanceData({ items: '/bookings' }));
    await act(async () => { await result.current.reload(); });
    await act(async () => { old.reject(new Error('obsolete failure')); });
    expect(result.current.error).toBeNull();
    expect(result.current.data.items).toEqual([{ id: '/bookings' }]);
  });

  it('does not reload when an equivalent source object is recreated', async () => {
    const { result, rerender } = renderHook(() => useFinanceData({ items: '/bookings' }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    rerender();
    expect(mocks.getAll).toHaveBeenCalledTimes(1);
  });

  it('replaces the entire data snapshot when endpoints change', async () => {
    const pending = deferred();
    const { result, rerender } = renderHook(({ path }) => useFinanceData({ items: path }), { initialProps: { path: '/accounts' } });
    await waitFor(() => expect(result.current.loading).toBe(false));
    mocks.getAll.mockReturnValue(pending.promise);
    rerender({ path: '/bookings' });
    expect(result.current.data.items).toEqual([]);
    expect(result.current.loading).toBe(true);
    await act(async () => { pending.resolve([{ id: 'booking' }]); });
    expect(result.current.data.items).toEqual([{ id: 'booking' }]);
  });

  it('handles StrictMode effect cleanup without losing the current request', async () => {
    const { result } = renderHook(() => useFinanceData(sources), {
      reactStrictMode: true,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
    expect(result.current.data.items).toEqual([{ id: '/bookings' }]);
    expect(mocks.getAll.mock.calls[0][1].signal.aborted).toBe(true);
    expect(mocks.getAll.mock.calls.at(-1)[1].signal.aborted).toBe(false);
  });
});
