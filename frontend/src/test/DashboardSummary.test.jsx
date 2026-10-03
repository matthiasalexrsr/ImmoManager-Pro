import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { checkedSummary, freshTrails, hintTarget, summaryQuery } from '../features/dashboardHome/dashboardModel';
import useDashboardSummary from '../features/dashboardHome/useDashboardSummary';

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../api', () => ({ api: { get: mocks.get } }));
export function summaryFixture() {
  return { portfolio_count: 1, property_count: 2, unit_count: 100005, tenant_count: 3, active_contracts: 3, account_count: 0,
    open_maintenance: 1, overdue_maintenance: 0, document_count: 4, open_tasks: 6, unread_notifications: 1,
    open_rent_charges: 2, overdue_rent_charges: 1, open_receivables: 3, overdue_receivables: 1, draft_billing_periods: 2,
    occupied_units: 2, vacant_units: 100000, reserved_units: 1,
    billing_preflight_periods_checked: 2, billing_preflight_blockers: 1, billing_preflight_warnings: 3,
    as_of: '2026-10-03', basis: 'dashboard-status-v1',
    occupancy: { total: 100005, occupied: 3, rented: 1, vacant: 100000, reserved: 1, other: 1, basis: 'stored_unit_status' },
    billing_presence: { periods_checked: 2, blockers: 1, warnings: 3, basis: 'basic_presence_checks', complete_preflight: false },
    work_hints: {
      tasks: { total: 6, items: [{ id: 'task-first', title: 'First task', due_date: null, priority: 'custom' }], has_more: true, next_after: 'actual-opaque-task-token', source_url: '/tasks?status=open' },
      notifications: { total: 1, items: [{ id: 'notice', title: 'Notice', severity: 'custom', entity_type: 'unit', entity_id: 'unit-id' }], has_more: false, next_after: null, source_url: '/notifications?status=unread' },
      expiring_contracts: { total: 1, items: [{ id: 'contract', contract_number: 'MV-1', end_date: '2026-10-03', days_remaining: 0 }], has_more: false, next_after: null, source_url: '/contracts' },
    } };
}
const checked = value => checkedSummary(value, { limit: 5 }, freshTrails());
beforeEach(() => { vi.resetAllMocks(); mocks.get.mockResolvedValue(summaryFixture()); });

describe('actual B1 summary projection contract', () => {
  it('retains complete counts and server order while projecting only safe hint fields', () => {
    const fixture = summaryFixture(); fixture.work_hints.tasks.items[0].description = 'DO NOT RETAIN';
    const result = checked(fixture);
    expect(result.occupancy.total).toBe(100005); expect(result.occupancy.occupied).toBe(3);
    expect(result.billing_presence.complete_preflight).toBe(false);
    expect(result.work_hints.tasks.items[0].priority).toBe('custom');
    expect(result.work_hints.tasks.items[0]).not.toHaveProperty('description');
  });
  it.each(['occupancy', 'presence', 'cursor', 'date', 'total', 'duplicate'])('rejects the actual %s inconsistency without zero fallback', fault => {
    const value = summaryFixture();
    if (fault === 'occupancy') value.occupancy.other = 0;
    if (fault === 'presence') value.billing_presence.complete_preflight = true;
    if (fault === 'cursor') value.work_hints.tasks.next_after = null;
    if (fault === 'date') value.as_of = '2026-02-30';
    if (fault === 'total') value.work_hints.tasks.total = 5;
    if (fault === 'duplicate') value.work_hints.tasks.items.push({ ...value.work_hints.tasks.items[0] });
    expect(() => checked(value)).toThrow('dashboard_summary_invalid');
  });
  it('preserves an empty live following page with a positive complete total', () => {
    const value = summaryFixture(); value.work_hints.tasks = { ...value.work_hints.tasks, items: [], has_more: false, next_after: null };
    expect(() => checked(value)).toThrow();
    const trails = freshTrails(); trails.tasks.push('previous-token');
    expect(checkedSummary(value, { limit: 5 }, trails).work_hints.tasks.total).toBe(6);
  });
  it('uses actual three cursor parameters and verified App routes rather than source_url', () => {
    const trails = freshTrails(); trails.tasks.push('task+token'); trails.notifications.push('notice/token'); trails.expiring_contracts.push('contract-token');
    const query = new URL(summaryQuery({ limit: 5, asOf: '2026-10-03' }, trails), 'https://example.invalid').searchParams;
    expect(query.get('tasks_after')).toBe('task+token'); expect(query.get('notifications_after')).toBe('notice/token');
    expect(query.get('contracts_after')).toBe('contract-token'); expect(query.get('as_of')).toBe('2026-10-03');
    expect(hintTarget({ entity_type: 'unit', entity_id: 'a/b', source_url: 'https://foreign.invalid' })).toBe('/units/a%2Fb');
    expect(hintTarget({ entity_type: 'notifications', entity_id: 'n' })).toBeNull();
  });
});

describe('one real UI summary lane', () => {
  it('publishes a following page atomically and retries its failed query with old pages visibly stale', async () => {
    const hook = renderHook(() => useDashboardSummary('principal'));
    await waitFor(() => expect(hook.result.current.status).toBe('ready'));
    mocks.get.mockRejectedValueOnce(Object.assign(new Error('offline'), { statusCode: 503 }));
    act(() => hook.result.current.navigate('tasks', 'next'));
    await waitFor(() => expect(hook.result.current.status).toBe('error'));
    expect(hook.result.current.data.work_hints.tasks.items[0].id).toBe('task-first');
    expect(hook.result.current.trails.tasks).toEqual([null]);
    const failedPath = mocks.get.mock.calls.at(-1)[0];
    const next = summaryFixture(); next.work_hints.tasks = { ...next.work_hints.tasks, items: [{ id: 'task-last', title: 'Last task', due_date: null, priority: 'normal' }], has_more: false, next_after: null };
    mocks.get.mockResolvedValueOnce(next); act(() => hook.result.current.retry());
    await waitFor(() => expect(hook.result.current.status).toBe('ready'));
    expect(mocks.get.mock.calls.at(-1)[0]).toBe(failedPath);
    expect(hook.result.current.trails.tasks).toEqual([null, 'actual-opaque-task-token']);
    expect(hook.result.current.data.work_hints.tasks.items[0].id).toBe('task-last');
    expect(hook.result.current.data.work_hints.notifications.items[0].id).toBe('notice');
  });
  it('keeps numerical cursor errors explicit and resets all families with a new server-selected day', async () => {
    const hook = renderHook(() => useDashboardSummary('principal'));
    await waitFor(() => expect(hook.result.current.status).toBe('ready'));
    mocks.get.mockRejectedValueOnce(Object.assign(new Error('expired page'), { statusCode: 422 }));
    act(() => hook.result.current.navigate('tasks', 'next'));
    await waitFor(() => expect(hook.result.current.error.statusCode).toBe(422));
    act(() => { void hook.result.current.reset(10); });
    await waitFor(() => expect(hook.result.current.status).toBe('ready'));
    expect(mocks.get.mock.calls.at(-1)[0]).toBe('/dashboard/stats?preview_limit=10');
    expect(hook.result.current.trails).toEqual(freshTrails());
  });
  it('aborts late responses across refresh and principal changes, with no preceding private frame', async () => {
    let release; let signal;
    mocks.get.mockImplementationOnce((_path, options) => { signal = options.signal; return new Promise(resolve => { release = resolve; }); });
    const hook = renderHook(({ principal }) => useDashboardSummary(principal), { initialProps: { principal: 'old' } });
    hook.rerender({ principal: 'new' }); expect(hook.result.current.data).toBeNull();
    await waitFor(() => expect(hook.result.current.status).toBe('ready'));
    expect(signal.aborted).toBe(true);
    const old = summaryFixture(); old.property_count = 999;
    await act(async () => release(old)); expect(hook.result.current.data.property_count).toBe(2);
    const pending = new Promise(() => {}); mocks.get.mockReturnValueOnce(pending);
    act(() => { void hook.result.current.reset(); });
    const finalSignal = mocks.get.mock.calls.at(-1)[1].signal;
    hook.unmount(); expect(finalSignal.aborted).toBe(true);
  });
  it('drops retained data on actual numerical authority denial and notifies the private workspace', async () => {
    const denied = vi.fn(); const hook = renderHook(() => useDashboardSummary('principal', denied));
    await waitFor(() => expect(hook.result.current.status).toBe('ready'));
    mocks.get.mockRejectedValueOnce(Object.assign(new Error('denied'), { statusCode: 403 }));
    act(() => { void hook.result.current.reset(); });
    await waitFor(() => expect(denied).toHaveBeenCalledOnce());
    expect(hook.result.current.data).toBeNull(); expect(hook.result.current.error.statusCode).toBe(403);
  });
});
