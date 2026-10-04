import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Dashboard from '../pages/Dashboard';
import { summaryFixture } from './fixtures/dashboardSummary';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getAll: vi.fn(), updateUser: vi.fn(), user: null, currentUser: null, admin: true, readonly: false, locale: 'de-DE', t: null }));
vi.mock('../api', () => ({ api: { get: mocks.get, getAll: mocks.getAll } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user, updateUser: mocks.updateUser, isAdmin: mocks.admin, isReadonly: mocks.readonly }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: mocks.locale, t: mocks.t }) }));
vi.mock('recharts', () => {
  const Container = ({ children }) => <div>{children}</div>; const Empty = () => null;
  return { ResponsiveContainer: Container, BarChart: Container, PieChart: Container, LineChart: Container, Bar: Container, Pie: Container, XAxis: Empty, YAxis: Empty, Tooltip: Empty, Cell: Empty, Legend: Empty, Line: Empty, CartesianGrid: Empty };
});
const dictionaries = { 'de-DE': de, 'en-US': en, 'es-ES': es };
const t = (key, params = {}) => {
  let value = key.split('.').reduce((part, name) => part?.[name], dictionaries[mocks.locale]) || key;
  for (const [name, replacement] of Object.entries(params)) value = value.replaceAll(`{{${name}}}`, replacement);
  return value;
};
let data, failed, summary;
const paths = { stats: '/dashboard/stats', cashflow: '/reports/cashflow', aging: '/reports/receivables-aging', maintenance: '/reports/maintenance-costs', forecast: '/reports/liquidity-forecast?months=6', finance: '/reports/finance', audit: '/audit?limit=10' };
const renderHome = () => render(<MemoryRouter><Dashboard /></MemoryRouter>);
const metric = key => screen.getByRole('article', { name: t(key) });
const panel = key => screen.getByRole('region', { name: t(key) });
const analysis = () => fireEvent.click(screen.getByRole('tab', { name: t('dashboardHome.analysisTab') }));
const openTable = key => { const report = panel(key); fireEvent.click(within(report).getByText(t('dashboardHome.chartValues'))); return within(report).getByRole('table'); };
const summaryCalls = () => mocks.get.mock.calls.filter(([path]) => path.startsWith(paths.stats));
const resetCounts = () => {
  Object.entries(summary).filter(([, value]) => typeof value === 'number').forEach(([key]) => { summary[key] = 0; });
  Object.entries(summary.occupancy).filter(([, value]) => typeof value === 'number').forEach(([key]) => { summary.occupancy[key] = 0; });
  for (const key of ['periods_checked', 'blockers', 'warnings']) summary.billing_presence[key] = 0;
  Object.values(summary.work_hints).forEach(page => Object.assign(page, { total: 0, items: [], has_more: false, next_after: null }));
};

beforeEach(() => {
  vi.resetAllMocks(); mocks.admin = true; mocks.readonly = false; mocks.locale = 'de-DE'; mocks.t = t;
  mocks.user = { id: 'actor', role: 'owner', portfolio_access: 'all', portfolio_ids: [], write_permissions: [] }; mocks.currentUser = mocks.user;
  failed = new Set(); summary = summaryFixture();
  summary.unit_count = 5; summary.vacant_units = 1;
  Object.assign(summary.occupancy, { total: 5, vacant: 1, other: 0 });
  Object.assign(summary.work_hints.tasks, { total: 2, items: [
    { id: 'early', title: 'Dach prüfen', due_date: '2026-10-03', priority: 'urgent' },
    { id: 'late', title: 'Späterer Termin', due_date: null, priority: 'custom' },
  ], has_more: false, next_after: null }); summary.open_tasks = 2;
  Object.assign(summary.work_hints.notifications, { items: [{ id: 'n1', title: 'Miete fehlt', severity: 'warning', entity_type: 'rent_charge', entity_id: 'charge1' }] });
  Object.assign(summary.work_hints.expiring_contracts, { items: [{ id: 'c1', contract_number: 'MV-123', end_date: '2026-11-02', days_remaining: 30 }] });
  data = {
    [paths.cashflow]: { incomeTotal: 1000.25, expenseTotal: 250, netTotal: 750.25 },
    [paths.aging]: { openTotal: 251.25, buckets: { current: 100, days1to30: 151.25, days31to60: 0, days61to90: 0, days90plus: 0 } },
    [paths.maintenance]: { openCases: 2, totalEstimatedCost: 300, categories: [{ category: 'Dach', estimatedCost: 300 }] },
    [paths.forecast]: { current_balance: 750.25, forecast: [{ month: '2026-12', projected_balance: 1500.5, projected_income: 1000.25, projected_expense: 250 }] },
    [paths.finance]: { uncategorizedTotal: 10, bookingsTotal: 510, totalsByCategory: [{ categoryName: 'Mieten', total: 600 }, { categoryName: 'Reparatur', total: -100 }] },
    [paths.audit]: [{ action: 'create', entity_type: 'property', username: 'Owner', timestamp: '2026-10-01T08:00:00Z' }],
    '/tasks/early': { id: 'early', title: 'Exact task', status: 'open', due_date: '2026-10-03', unit_id: 'u1', property_id: 'p1', description: 'NOT IN OVERVIEW' },
    '/tasks/late': { id: 'late', title: 'Exact later task', status: 'open', due_date: null, unit_id: null, property_id: null },
    '/contracts/c1': { id: 'c1', contract_number: 'Exact MV-123', status: 'active', start_date: '2025-01-01', end_date: '2026-11-02', unit_id: 'u1', property_id: 'p1', tenant_id: 'private-tenant' },
    '/units/u1': { id: 'u1', label: 'Exact unit', property_id: 'p1' },
    '/properties/p1': { id: 'p1', name: 'Exact property', portfolio_id: 'portfolio' },
  };
  mocks.get.mockImplementation(async path => {
    const key = path.startsWith(paths.stats) ? paths.stats : path;
    if (failed.has(key)) throw new Error('Quelle offline');
    if (key === '/auth/me') return mocks.currentUser;
    if (key === paths.stats) return structuredClone(summary);
    if (!(key in data)) throw new Error(`Unexpected API source: ${key}`);
    return structuredClone(data[key]);
  });
  mocks.getAll.mockResolvedValue([]);
});

describe('actual bounded dashboard composition', () => {
  it('uses complete server occupancy and one canonical amount without any legacy stock or hint request', async () => {
    renderHome(); expect(mocks.getAll).not.toHaveBeenCalled(); await screen.findByText('3 / 5');
    expect(metric('dashboardHome.occupiedUnits')).toHaveTextContent('60 %');
    expect(metric('dashboardHome.openAmount')).toHaveTextContent('251,25');
    expect(metric('dashboardHome.openAmount')).not.toHaveTextContent('502,50');
    expect(metric('dashboardHome.draftBilling')).toHaveTextContent('2');
    expect(mocks.getAll).not.toHaveBeenCalled();
    expect(mocks.get.mock.calls.every(([path]) => !['/units', '/tasks?', '/notifications?', '/reports/contracts-expiring'].some(prefix => path.startsWith(prefix)))).toBe(true);
    expect(summaryCalls()).toHaveLength(1);
    expect(within(panel('dashboardHome.priorities')).getAllByRole('link')[0]).toHaveTextContent('151,25');
    expect(panel('pages.dashboard.openTasks')).toHaveTextContent('2 insgesamt');
    expect(panel('dashboardHome.priorities')).toHaveTextContent(t('dashboardHome.billingHint'));
  });
  it('preserves valid zero, undefined zero-unit occupancy and an honest empty authorized scope', async () => {
    resetCounts(); data[paths.aging] = { openTotal: 0, buckets: Object.fromEntries(['current', 'days1to30', 'days31to60', 'days61to90', 'days90plus'].map(key => [key, 0])) };
    data[paths.maintenance] = { openCases: 0, totalEstimatedCost: 0, categories: [] };
    renderHome(); await screen.findByText('0 / 0');
    expect(metric('dashboardHome.openAmount')).toHaveTextContent('0,00');
    expect(metric('dashboardHome.occupiedUnits')).toHaveTextContent(t('dashboardHome.noOccupancy'));
    expect(metric('dashboardHome.occupiedUnits')).not.toHaveTextContent('0 %');
    expect(await screen.findByText(t('dashboardHome.noPriorities'))).toBeVisible();
    expect(screen.getByRole('heading', { name: t('dashboardHome.emptyScopeTitle') })).toBeVisible();
    expect(screen.queryByText(t('dashboardHome.startHint'))).not.toBeInTheDocument();
  });
  it('shows a failed summary as unknown hints and figures while the separate canonical money loads', async () => {
    failed.add(paths.stats); renderHome();
    expect(await screen.findByRole('alert')).toHaveTextContent('Quelle offline');
    expect(metric('pages.dashboard.properties')).toHaveTextContent('—');
    expect(metric('dashboardHome.openAmount')).toHaveTextContent('251,25');
    expect(screen.queryByText(t('dashboardHome.noPriorities'))).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: t('dashboardHome.emptyScopeTitle') })).not.toBeInTheDocument();
    for (const key of ['pages.dashboard.noOpenTasks', 'pages.dashboard.noNotifications', 'dashboardHome.noExpiring']) expect(screen.queryByText(t(key))).not.toBeInTheDocument();
  });
  it('rechecks grants then retries just the same failed summary and restores all coupled hint groups', async () => {
    failed.add(paths.stats); renderHome(); const error = await screen.findByRole('alert');
    const calls = mocks.get.mock.calls.length; failed.clear(); summary.property_count = 7;
    fireEvent.click(within(error).getByRole('button', { name: t('dashboardHome.retry') }));
    await waitFor(() => expect(metric('pages.dashboard.properties')).toHaveTextContent('7'));
    expect(mocks.get.mock.calls).toHaveLength(calls + 2);
    expect(await screen.findByRole('button', { name: 'Dach prüfen' })).toBeVisible();
  });
  it.each(['aging', 'stats'])('rejects an inconsistent actual %s source rather than inventing zero', async fault => {
    if (fault === 'aging') data[paths.aging].openTotal = 900; else delete summary.draft_billing_periods;
    renderHome(); expect(await screen.findByRole('alert')).toHaveTextContent(t('dashboardHome.invalidResponse'));
    expect(metric(fault === 'aging' ? 'dashboardHome.openAmount' : 'dashboardHome.draftBilling')).toHaveTextContent('—');
  });
  it('renders independent money while one summary request remains pending', async () => {
    const original = mocks.get.getMockImplementation(); mocks.get.mockImplementation((path, options) => path.startsWith(paths.stats) ? new Promise(() => {}) : original(path, options));
    renderHome(); await waitFor(() => expect(metric('dashboardHome.openAmount')).toHaveTextContent('251,25'));
    expect(metric('pages.dashboard.properties')).toHaveAttribute('aria-busy', 'true');
    expect(screen.queryByText(t('pages.dashboard.noOpenTasks'))).not.toBeInTheDocument();
  });
  it('aborts an earlier summary after refresh and ignores its late response', async () => {
    let releaseOld, oldSignal; const original = mocks.get.getMockImplementation();
    mocks.get.mockImplementationOnce((_path, options) => { oldSignal = options.signal; return new Promise(resolve => { releaseOld = resolve; }); }).mockImplementation(original);
    renderHome(); await waitFor(() => expect(metric('dashboardHome.openAmount')).toHaveTextContent('251,25'));
    summary.property_count = 8; fireEvent.click(screen.getByRole('button', { name: t('dashboardHome.refresh'), exact: true }));
    await waitFor(() => expect(metric('pages.dashboard.properties')).toHaveTextContent('8')); expect(oldSignal.aborted).toBe(true);
    await act(async () => releaseOld({ ...summary, property_count: 999 })); expect(metric('pages.dashboard.properties')).not.toHaveTextContent('999');
  });
  it('loads analysis on demand and keeps all six reports with signed accessible tables and separate bases', async () => {
    renderHome(); await screen.findByText('3 / 5'); expect(mocks.get.mock.calls.some(([path]) => path === paths.cashflow)).toBe(false); analysis();
    await within(panel('pages.dashboard.cashflow')).findByText(t('dashboardHome.chartValues'));
    for (const key of ['pages.dashboard.occupancyChart', 'pages.dashboard.cashflow', 'pages.dashboard.receivablesAging', 'analyticsLabels.forecast', 'pages.dashboard.maintenanceCosts', 'dashboardHome.categoryVolume']) expect(openTable(key)).toBeVisible();
    expect(panel('pages.dashboard.cashflow')).toHaveTextContent('1.000,25');
    expect(panel('dashboardHome.categoryVolume')).toHaveTextContent('-100,00');
    expect(panel('dashboardHome.categoryVolume')).toHaveTextContent('510,00');
    expect(panel('dashboardHome.categoryVolume')).toHaveTextContent(t('dashboardHome.categoryScope'));
    expect(screen.getAllByText(t('dashboardHome.separateReports')).length).toBeGreaterThan(0);
  });
  it('keeps other reports usable and retries one failed report without reloading the summary', async () => {
    failed.add(paths.cashflow); renderHome(); await screen.findByText('3 / 5'); analysis();
    const report = panel('pages.dashboard.cashflow'); const error = await within(report).findByRole('alert');
    expect(openTable('pages.dashboard.receivablesAging')).toHaveTextContent('151,25');
    const calls = mocks.get.mock.calls.length; failed.clear(); fireEvent.click(within(error).getByRole('button', { name: t('dashboardHome.retry') }));
    expect(await within(report).findByText(t('dashboardHome.chartValues'))).toBeVisible(); expect(mocks.get.mock.calls).toHaveLength(calls + 1);
  });
  it('keeps other stored statuses separate from vacancies', async () => {
    summary.occupancy.vacant = 0; summary.occupancy.other = 1; summary.vacant_units = 0;
    renderHome(); await screen.findByText('3 / 5'); expect(screen.queryByRole('link', { name: new RegExp(t('dashboardHome.vacancyTitle')) })).not.toBeInTheDocument(); analysis();
    expect(within(openTable('pages.dashboard.occupancyChart')).getByRole('row', { name: `${t('dashboardHome.otherUnitStatuses')} 1` })).toBeVisible();
  });
  it('keeps readonly navigation while hiding creation and protected audit', async () => {
    mocks.admin = false; mocks.readonly = true; mocks.user.role = 'readonly'; renderHome(); await screen.findByText('3 / 5');
    expect(screen.queryByRole('link', { name: t('dashboardHome.createContract') })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: t('pages.dashboard.recentActivity') })).not.toBeInTheDocument();
    expect(within(screen.getByRole('complementary', { name: t('dashboardHome.quickActions') })).getByRole('link', { name: t('dashboardHome.openInventory') })).toHaveAttribute('href', '/properties');
    expect(mocks.get.mock.calls.some(([path]) => path === paths.audit)).toBe(false);
  });
  it('loads audit only after expansion and supports its independent failure retry', async () => {
    failed.add(paths.audit); renderHome(); await screen.findByText('3 / 5'); expect(mocks.get.mock.calls.some(([path]) => path === paths.audit)).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: t('pages.dashboard.recentActivity') })); const error = await screen.findByRole('alert');
    failed.clear(); fireEvent.click(within(error).getByRole('button', { name: t('dashboardHome.retry') }));
    const section = screen.getByRole('button', { name: t('pages.dashboard.recentActivity') }).parentElement;
    fireEvent.click(await within(section).findByText(t('dashboardHome.chartValues'))); expect(within(section).getByRole('table')).toHaveTextContent('Owner');
  });
  it('uses only known actual entity routes and leaves unknown references as plain text', async () => {
    summary.unread_notifications = 3; summary.work_hints.notifications.total = 3;
    summary.work_hints.notifications.items.push({ id: 'general', title: 'Allgemeiner Hinweis', severity: 'info', entity_type: null, entity_id: null }, { id: 'unsafe', title: 'Unknown type', severity: 'custom', entity_type: 'notifications', entity_id: 'n', source_url: 'https://foreign.invalid' });
    renderHome(); expect(await screen.findByRole('link', { name: 'Miete fehlt' })).toHaveAttribute('href', '/rent-charges');
    expect(screen.queryByRole('link', { name: 'Allgemeiner Hinweis' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Unknown type' })).not.toBeInTheDocument();
    expect(document.querySelector('a[href*="foreign.invalid"]')).toBeNull();
  });
  it('supports keyboard tab navigation with the correct panel', async () => {
    renderHome(); await screen.findByText('3 / 5'); const work = screen.getByRole('tab', { name: t('dashboardHome.workTab') }); work.focus(); fireEvent.keyDown(work, { key: 'ArrowRight' });
    const analytics = screen.getByRole('tab', { name: t('dashboardHome.analysisTab') }); expect(analytics).toHaveFocus(); expect(analytics).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', analytics.id); fireEvent.keyDown(analytics, { key: 'Home' }); expect(work).toHaveFocus();
  });
  it('retains old bounded pages explicitly stale on failure and retries the same cursor', async () => {
    summary.open_tasks = 12; Object.assign(summary.work_hints.tasks, { total: 12, has_more: true, next_after: 'real-token' });
    renderHome(); await screen.findByText('3 / 5'); failed.add(paths.stats);
    fireEvent.click(within(panel('pages.dashboard.openTasks')).getByRole('button', { name: t('dashboardHome.nextPage'), exact: true }));
    const error = await screen.findByRole('alert'); expect(error).toHaveTextContent('Quelle offline');
    expect(screen.getByText(/Älterer Stand von/)).toBeVisible(); expect(metric('pages.dashboard.properties')).toHaveTextContent('2');
    expect(within(panel('pages.dashboard.openTasks')).getByRole('button', { name: 'Dach prüfen' })).toBeDisabled();
    const query = summaryCalls().at(-1)[0]; failed.clear(); summary.work_hints.tasks.items = [{ id: 'last', title: 'Actual last task', due_date: null, priority: 'custom' }]; summary.work_hints.tasks.has_more = false; summary.work_hints.tasks.next_after = null;
    fireEvent.click(within(error).getByRole('button', { name: t('dashboardHome.retry') }));
    expect(await screen.findByRole('button', { name: 'Actual last task' })).toBeVisible(); expect(summaryCalls().at(-1)[0]).toBe(query);
    expect(screen.queryByText(/Älterer Stand von/)).not.toBeInTheDocument();
  });
  it('offers a real 422 restart which resets the day and all three cursor families', async () => {
    summary.open_tasks = 12; Object.assign(summary.work_hints.tasks, { total: 12, has_more: true, next_after: 'real-token' });
    renderHome(); await screen.findByText('3 / 5'); const original = mocks.get.getMockImplementation();
    mocks.get.mockImplementation((path, options) => path.includes('tasks_after=') ? Promise.reject(Object.assign(new Error('actual cursor mismatch'), { statusCode: 422 })) : original(path, options));
    fireEvent.click(within(panel('pages.dashboard.openTasks')).getByRole('button', { name: t('dashboardHome.nextPage'), exact: true }));
    const error = await screen.findByRole('alert'); expect(error).toHaveTextContent(t('dashboardHome.pageExpired'));
    fireEvent.click(within(error).getByRole('button', { name: t('dashboardHome.restartPages') }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument()); expect(summaryCalls().at(-1)[0]).toBe('/dashboard/stats?preview_limit=5');
  });
  it('continues all three families independently while submitting every current opaque cursor together', async () => {
    summary.open_tasks = 6; summary.unread_notifications = 6;
    for (const [family, page] of Object.entries(summary.work_hints)) Object.assign(page, { total: 6, has_more: true, next_after: `${family}-opaque` });
    renderHome(); await screen.findByText('3 / 5');
    const original = mocks.get.getMockImplementation();
    mocks.get.mockImplementation(async (path, options) => {
      const result = await original(path, options); if (!path.startsWith(paths.stats)) return result;
      const query = new URL(path, 'https://example.invalid').searchParams;
      const cursors = { tasks: 'tasks_after', notifications: 'notifications_after', expiring_contracts: 'contracts_after' };
      for (const [family, cursor] of Object.entries(cursors)) if (query.has(cursor)) Object.assign(result.work_hints[family], { has_more: false, next_after: null, items: [result.work_hints[family].items.at(-1)] });
      return result;
    });
    for (const key of ['pages.dashboard.openTasks', 'pages.dashboard.notifications', 'dashboardHome.next90Days']) {
      fireEvent.click(within(panel(key)).getByRole('button', { name: t('dashboardHome.nextPage'), exact: true }));
      await waitFor(() => expect(within(panel(key)).getByRole('button', { name: t('dashboardHome.nextPage'), exact: true })).toBeDisabled());
    }
    const final = new URL(summaryCalls().at(-1)[0], 'https://example.invalid').searchParams;
    expect(final.get('tasks_after')).toBe('tasks-opaque'); expect(final.get('notifications_after')).toBe('notifications-opaque'); expect(final.get('contracts_after')).toBe('expiring_contracts-opaque'); expect(final.get('as_of')).toBe('2026-10-03');
    fireEvent.click(within(panel('pages.dashboard.openTasks')).getByRole('button', { name: t('dashboardHome.previousPage'), exact: true }));
    await waitFor(() => expect(within(panel('pages.dashboard.openTasks')).getByRole('button', { name: 'Dach prüfen' })).toBeVisible());
    expect(new URL(summaryCalls().at(-1)[0], 'https://example.invalid').searchParams.has('tasks_after')).toBe(false);
  });
  it('retains a failed separate money report as older data without treating it as current priorities', async () => {
    renderHome(); await screen.findByText('3 / 5'); failed.add(paths.aging);
    fireEvent.click(screen.getByRole('button', { name: t('dashboardHome.refresh'), exact: true }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Quelle offline');
    expect(metric('dashboardHome.openAmount')).toHaveTextContent('251,25'); expect(screen.getByText(/Älterer Stand von/)).toBeVisible();
    expect(screen.queryByRole('link', { name: new RegExp(t('dashboardHome.overdueTitle')) })).not.toBeInTheDocument();
    expect(panel('dashboardHome.priorities')).toHaveTextContent(t('dashboardHome.prioritiesIncomplete'));
  });
  it('loads only an explicitly selected exact context and checked parents, with a focus return', async () => {
    renderHome(); await screen.findByText('3 / 5'); expect(mocks.get.mock.calls.some(([path]) => path.startsWith('/tasks/') || path.startsWith('/contracts/') || path.startsWith('/units/'))).toBe(false);
    const button = screen.getByRole('button', { name: 'Dach prüfen' }); fireEvent.click(button);
    const context = await screen.findByRole('region', { name: t('dashboardHome.context') }); expect(await within(context).findByText('Exact task')).toBeVisible();
    expect(within(context).getByRole('link', { name: 'Exact property' })).toHaveAttribute('href', '/properties/p1');
    expect(within(context).getByRole('link', { name: 'Exact unit' })).toHaveAttribute('href', '/units/u1');
    expect(mocks.get.mock.calls.filter(([path]) => ['/tasks/early', '/units/u1', '/properties/p1'].includes(path)).map(([path]) => path)).toEqual(['/tasks/early', '/units/u1', '/properties/p1']);
    expect(document.body).not.toHaveTextContent('NOT IN OVERVIEW'); expect(mocks.get.mock.calls.some(([path]) => path.startsWith('/tenants'))).toBe(false);
    fireEvent.click(within(context).getByRole('button', { name: t('dashboardHome.closeContext') })); expect(button).toHaveFocus(); expect(screen.queryByRole('region', { name: t('dashboardHome.context') })).not.toBeInTheDocument();
  });
  it('aborts A to B detail selection before reading further parents and never shows the preceding context', async () => {
    renderHome(); await screen.findByText('3 / 5'); let release, signal; const original = mocks.get.getMockImplementation();
    mocks.get.mockImplementation((path, options) => path === '/tasks/early' ? (signal = options.signal, new Promise(resolve => { release = resolve; })) : original(path, options));
    fireEvent.click(screen.getByRole('button', { name: 'Dach prüfen' })); await waitFor(() => expect(signal).toBeDefined());
    fireEvent.click(screen.getByRole('button', { name: 'Späterer Termin' })); expect(await screen.findByText('Exact later task')).toBeVisible(); expect(signal.aborted).toBe(true);
    await act(async () => release(data['/tasks/early'])); expect(screen.queryByText('Exact task')).not.toBeInTheDocument(); expect(mocks.get.mock.calls.some(([path]) => path === '/units/u1')).toBe(false);
  });
  it.each(['parent', '404'])('hides an unverified selected %s context without a foreign name or false empty result', async fault => {
    if (fault === 'parent') data['/units/u1'].property_id = 'foreign'; else {
      const original = mocks.get.getMockImplementation(); mocks.get.mockImplementation((path, options) => path === '/tasks/early' ? Promise.reject(Object.assign(new Error('PRIVATE MUST NOT SHOW'), { statusCode: 404 })) : original(path, options));
    }
    renderHome(); await screen.findByText('3 / 5'); fireEvent.click(screen.getByRole('button', { name: 'Dach prüfen' }));
    const context = await screen.findByRole('region', { name: t('dashboardHome.context') }); const error = await within(context).findByRole('alert');
    expect(error).toHaveTextContent(t(fault === 'parent' ? 'dashboardHome.invalidResponse' : 'dashboardHome.contextUnavailable')); expect(screen.queryByText('Exact task')).not.toBeInTheDocument(); expect(document.body).not.toHaveTextContent('PRIVATE MUST NOT SHOW');
  });
  it.each(['summary', 'report', 'context'])('fences all private data and cancels pending reads on numerical 403 in the %s source', async source => {
    renderHome(); await screen.findByText('3 / 5'); const original = mocks.get.getMockImplementation(); let pendingSignal;
    mocks.get.mockImplementation((path, options) => {
      if (path === paths.forecast) { pendingSignal = options.signal; return new Promise(() => {}); }
      if ((source === 'summary' && path.startsWith(paths.stats)) || (source === 'report' && path === paths.cashflow) || (source === 'context' && path === '/tasks/early')) return Promise.reject(Object.assign(new Error('SECRET 403 MESSAGE'), { statusCode: 403 }));
      return original(path, options);
    });
    if (source === 'summary') fireEvent.click(screen.getByRole('button', { name: t('dashboardHome.refresh'), exact: true }));
    else if (source === 'report') analysis(); else fireEvent.click(screen.getByRole('button', { name: 'Dach prüfen' }));
    expect(await screen.findByText(t('dashboardHome.accessChanged'))).toBeVisible(); expect(screen.queryByText('3 / 5')).not.toBeInTheDocument(); expect(screen.queryByText('Dach prüfen')).not.toBeInTheDocument(); expect(document.body).not.toHaveTextContent('SECRET 403 MESSAGE');
    if (pendingSignal) expect(pendingSignal.aborted).toBe(true);
  });
  it('flushes the preceding actor and all grants before publishing a new scope, including a fresh zero-grant response', async () => {
    const rendered = renderHome(); await screen.findByText('3 / 5');
    mocks.currentUser = { ...mocks.user, role: 'readonly', portfolio_access: 'selected', portfolio_ids: [] };
    fireEvent.click(screen.getByRole('button', { name: t('dashboardHome.refresh'), exact: true })); expect(await screen.findByText(t('dashboardHome.accessChanged'))).toBeVisible();
    expect(screen.queryByText('3 / 5')).not.toBeInTheDocument(); expect(summaryCalls()).toHaveLength(1);
    mocks.user = mocks.currentUser; mocks.admin = false; mocks.readonly = true; resetCounts();
    rendered.rerender(<MemoryRouter><Dashboard /></MemoryRouter>); expect(screen.queryByText('3 / 5')).not.toBeInTheDocument(); await screen.findByText('0 / 0');
    expect(screen.queryByRole('button', { name: t('pages.dashboard.recentActivity') })).not.toBeInTheDocument(); expect(screen.queryByRole('link', { name: t('dashboardHome.createContract') })).not.toBeInTheDocument();
  });
});

for (const locale of ['de-DE', 'en-US', 'es-ES']) {
  it(`provides complete bounded dashboard translations in ${locale}`, async () => {
    mocks.locale = locale; renderHome(); await screen.findByText('3 / 5');
    expect(screen.getByRole('heading', { name: t('dashboardHome.title') })).toBeVisible();
    expect(screen.getByRole('tab', { name: t('dashboardHome.analysisTab') })).toBeVisible();
    expect(Object.keys(dictionaries[locale].dashboardHome).sort()).toEqual(Object.keys(de.dashboardHome).sort()); expect(document.body.textContent).not.toContain('dashboardHome.');
  });
}
