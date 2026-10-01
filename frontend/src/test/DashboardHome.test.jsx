import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Dashboard from '../pages/Dashboard';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getAll: vi.fn(), admin: true, readonly: false, locale: 'de-DE', t: null }));
vi.mock('../api', () => ({ api: { get: mocks.get, getAll: mocks.getAll } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isAdmin: mocks.admin, isReadonly: mocks.readonly }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: mocks.locale, t: mocks.t }) }));
vi.mock('recharts', () => {
  const Container = ({ children }) => <div>{children}</div>;
  const Empty = () => null;
  return { ResponsiveContainer: Container, BarChart: Container, PieChart: Container, LineChart: Container, Bar: Container, Pie: Container, XAxis: Empty, YAxis: Empty, Tooltip: Empty, Cell: Empty, Legend: Empty, Line: Empty, CartesianGrid: Empty };
});
const dictionaries = { 'de-DE': de, 'en-US': en, 'es-ES': es };
const t = (key, params = {}) => {
  let value = key.split('.').reduce((part, name) => part?.[name], dictionaries[mocks.locale]) || key;
  for (const [name, replacement] of Object.entries(params)) value = value.replaceAll(`{{${name}}}`, replacement);
  return value;
};
let data, failed;
const paths = { stats: '/dashboard/stats', units: '/units', tasks: '/tasks?status=open&limit=5&sort_by=due_date&sort_order=asc', notifications: '/notifications?status=unread&limit=5', cashflow: '/reports/cashflow', aging: '/reports/receivables-aging', maintenance: '/reports/maintenance-costs', forecast: '/reports/liquidity-forecast?months=6', expiring: '/reports/contracts-expiring?days=90', finance: '/reports/finance', audit: '/audit?limit=10' };
const renderHome = () => render(<MemoryRouter><Dashboard /></MemoryRouter>);
const metric = key => screen.getByRole('article', { name: t(key) });
const panel = key => screen.getByRole('region', { name: t(key) });
const analysis = () => fireEvent.click(screen.getByRole('tab', { name: t('dashboardHome.analysisTab') }));
const openTable = key => { const report = panel(key); fireEvent.click(within(report).getByText(t('dashboardHome.chartValues'))); return within(report).getByRole('table'); };

beforeEach(() => {
  vi.clearAllMocks();
  mocks.admin = true; mocks.readonly = false; mocks.locale = 'de-DE'; mocks.t = t;
  failed = new Set();
  data = {
    [paths.stats]: { portfolio_count: 1, property_count: 2, unit_count: 5, tenant_count: 3, active_contracts: 3, account_count: 0, open_maintenance: 1, overdue_maintenance: 0, document_count: 4, open_tasks: 2, unread_notifications: 1, open_rent_charges: 2, overdue_rent_charges: 1, open_receivables: 3, overdue_receivables: 1, draft_billing_periods: 2, billing_preflight_blockers: 1 },
    [paths.units]: ['occupied', 'rented', 'occupied', 'reserved', 'vacant'].map((status, index) => ({ id: `u${index}`, status })),
    [paths.tasks]: [{ id: 'late', title: 'Späterer Termin', due_date: '2026-12-02', priority: 'normal' }, { id: 'early', title: 'Dach prüfen', due_date: '2026-01-02', priority: 'urgent' }],
    [paths.notifications]: [{ id: 'n1', title: 'Miete fehlt', severity: 'warning', entity_type: 'rent_charge', entity_id: 'charge1' }],
    [paths.cashflow]: { incomeTotal: 1000.25, expenseTotal: 250, netTotal: 750.25 },
    [paths.aging]: { openTotal: 251.25, buckets: { current: 100, days1to30: 151.25, days31to60: 0, days61to90: 0, days90plus: 0 } },
    [paths.maintenance]: { openCases: 2, totalEstimatedCost: 300, categories: [{ category: 'Dach', estimatedCost: 300 }] },
    [paths.forecast]: { current_balance: 750.25, forecast: [{ month: '2026-12', projected_balance: 1500.5, projected_income: 1000.25, projected_expense: 250 }] },
    [paths.expiring]: { count: 1, contracts: [{ contractId: 'c1', contractNumber: 'MV-123', endDate: '2026-12-01', daysRemaining: 30 }] },
    [paths.finance]: { uncategorizedTotal: 10, bookingsTotal: 510, totalsByCategory: [{ categoryName: 'Mieten', total: 600 }, { categoryName: 'Reparatur', total: -100 }] },
    [paths.audit]: [{ action: 'create', entity_type: 'property', username: 'Owner', timestamp: '2026-10-01T08:00:00Z' }],
  };
  mocks.get.mockImplementation(async path => { if (failed.has(path)) throw new Error('Quelle offline'); return data[path]; });
  mocks.getAll.mockImplementation((path, options) => mocks.get(path, options));
});

describe('DashboardHome', () => {
  it('shows actual counts, weighted unit status and one canonical outstanding amount', async () => {
    renderHome();
    await screen.findByText('3 / 5');
    expect(metric('dashboardHome.occupiedUnits')).toHaveTextContent('60 %');
    expect(metric('dashboardHome.openAmount')).toHaveTextContent('251,25');
    expect(metric('dashboardHome.openAmount')).not.toHaveTextContent('502,50');
    expect(metric('dashboardHome.draftBilling')).toHaveTextContent('2');
    expect(mocks.getAll).toHaveBeenCalledWith('/units', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    const priorities = panel('dashboardHome.priorities');
    expect(within(priorities).getAllByRole('link')[0]).toHaveTextContent('151,25');
    expect(within(priorities).getAllByRole('link')[0]).toHaveAttribute('href', '/rent-overview');
  });

  it('preserves valid zero values and leaves zero-unit occupancy undefined', async () => {
    Object.keys(data[paths.stats]).forEach(key => { data[paths.stats][key] = 0; });
    data[paths.units] = [];
    data[paths.aging] = { openTotal: 0, buckets: Object.fromEntries(['current', 'days1to30', 'days31to60', 'days61to90', 'days90plus'].map(key => [key, 0])) };
    data[paths.maintenance] = { openCases: 0, totalEstimatedCost: 0, categories: [] };
    renderHome();
    await screen.findByText('0 / 0');
    expect(metric('dashboardHome.openAmount')).toHaveTextContent('0,00');
    expect(metric('dashboardHome.occupiedUnits')).toHaveTextContent(t('dashboardHome.noOccupancy'));
    expect(metric('dashboardHome.occupiedUnits')).not.toHaveTextContent('0 %');
    expect(await screen.findByText(t('dashboardHome.noPriorities'))).toBeVisible();
    expect(screen.getByRole('heading', { name: t('dashboardHome.startTitle') })).toBeVisible();
  });

  it('keeps failed statistics unknown while independently showing loaded tasks and money', async () => {
    failed.add(paths.stats);
    renderHome();
    expect(await screen.findByRole('alert')).toHaveTextContent('Quelle offline');
    expect(metric('pages.dashboard.properties')).toHaveTextContent('—');
    expect(metric('pages.dashboard.properties')).toHaveAttribute('aria-busy', 'false');
    expect(await screen.findByText('Dach prüfen')).toBeVisible();
    expect(metric('dashboardHome.openAmount')).toHaveTextContent('251,25');
    expect(screen.queryByText(t('dashboardHome.noPriorities'))).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: t('dashboardHome.startTitle') })).not.toBeInTheDocument();
  });

  it('retries only the failed statistics source and restores its figures', async () => {
    failed.add(paths.stats);
    renderHome();
    const error = await screen.findByRole('alert');
    const calls = mocks.get.mock.calls.length;
    failed.clear();
    data[paths.stats].property_count = 7;
    fireEvent.click(within(error).getByRole('button', { name: t('dashboardHome.retry') }));
    await waitFor(() => expect(metric('pages.dashboard.properties')).toHaveTextContent('7'));
    expect(mocks.get.mock.calls).toHaveLength(calls + 1);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not label a failed task list as empty and can retry to a confirmed empty list', async () => {
    failed.add(paths.tasks);
    renderHome();
    const tasks = panel('pages.dashboard.openTasks');
    const error = await within(tasks).findByRole('alert');
    expect(within(tasks).queryByText(t('pages.dashboard.noOpenTasks'))).not.toBeInTheDocument();
    failed.clear(); data[paths.tasks] = [];
    fireEvent.click(within(error).getByRole('button', { name: t('dashboardHome.retry') }));
    expect(await within(tasks).findByText(t('pages.dashboard.noOpenTasks'))).toBeVisible();
  });

  it('shows notification failures as failures instead of reporting no notifications', async () => {
    failed.add(paths.notifications);
    renderHome();
    const notifications = panel('pages.dashboard.notifications');
    expect(await within(notifications).findByRole('alert')).toHaveTextContent('Quelle offline');
    expect(within(notifications).queryByText(t('pages.dashboard.noNotifications'))).not.toBeInTheDocument();
  });

  it('rejects inconsistent aging totals rather than showing a misleading amount', async () => {
    data[paths.aging].openTotal = 900;
    renderHome();
    expect(await screen.findByRole('alert')).toHaveTextContent(t('dashboardHome.invalidResponse'));
    expect(metric('dashboardHome.openAmount')).toHaveTextContent('—');
    expect(metric('dashboardHome.openAmount')).not.toHaveTextContent('900');
  });

  it('rejects incomplete statistics rather than filling missing fields with zero', async () => {
    delete data[paths.stats].draft_billing_periods;
    renderHome();
    expect(await screen.findByRole('alert')).toHaveTextContent(t('dashboardHome.invalidResponse'));
    expect(metric('dashboardHome.draftBilling')).toHaveTextContent('—');
  });

  it('renders other sources while a statistics request is still pending', async () => {
    const original = mocks.get.getMockImplementation();
    mocks.get.mockImplementation((path, options) => path === paths.stats ? new Promise(() => {}) : original(path, options));
    renderHome();
    expect(await screen.findByText('Dach prüfen')).toBeVisible();
    expect(metric('dashboardHome.openAmount')).toHaveTextContent('251,25');
    expect(metric('pages.dashboard.properties')).toHaveAttribute('aria-busy', 'true');
  });

  it('aborts a superseded request and ignores its late response', async () => {
    let releaseOld, oldSignal;
    const original = mocks.get.getMockImplementation();
    mocks.get.mockImplementationOnce((_path, options) => { oldSignal = options.signal; return new Promise(resolve => { releaseOld = resolve; }); }).mockImplementation(original);
    renderHome();
    await screen.findByText('Dach prüfen');
    data[paths.stats].property_count = 8;
    fireEvent.click(screen.getByRole('button', { name: t('dashboardHome.refresh'), exact: true }));
    await waitFor(() => expect(metric('pages.dashboard.properties')).toHaveTextContent('8'));
    expect(oldSignal.aborted).toBe(true);
    await act(async () => releaseOld({ ...data[paths.stats], property_count: 999 }));
    expect(metric('pages.dashboard.properties')).not.toHaveTextContent('999');
  });

  it('keeps the six reports and accessible signed data tables with accurate semantic hints', async () => {
    renderHome(); await screen.findByText('3 / 5'); analysis();
    const titles = ['pages.dashboard.occupancyChart', 'pages.dashboard.cashflow', 'pages.dashboard.receivablesAging', 'analyticsLabels.forecast', 'pages.dashboard.maintenanceCosts', 'dashboardHome.categoryVolume'];
    for (const key of titles) expect(openTable(key)).toBeVisible();
    expect(panel('pages.dashboard.cashflow')).toHaveTextContent('1.000,25');
    expect(panel('dashboardHome.categoryVolume')).toHaveTextContent('-100,00');
    expect(panel('dashboardHome.categoryVolume')).toHaveTextContent('510,00');
    expect(panel('dashboardHome.categoryVolume')).toHaveTextContent(t('dashboardHome.categoryScope'));
    expect(panel('analyticsLabels.forecast')).toHaveTextContent(t('dashboardHome.forecastScope'));
  });

  it('keeps independent reports usable when one report fails and retries that report alone', async () => {
    failed.add(paths.cashflow);
    renderHome(); await screen.findByText('3 / 5'); analysis();
    const report = panel('pages.dashboard.cashflow');
    const error = await within(report).findByRole('alert');
    expect(openTable('pages.dashboard.receivablesAging')).toHaveTextContent('151,25');
    const calls = mocks.get.mock.calls.length;
    failed.clear(); fireEvent.click(within(error).getByRole('button', { name: t('dashboardHome.retry') }));
    expect(await within(report).findByText(t('dashboardHome.chartValues'))).toBeVisible();
    expect(mocks.get.mock.calls).toHaveLength(calls + 1);
  });

  it('shows additional unit statuses separately instead of counting them as vacant', async () => {
    data[paths.units][4].status = 'maintenance';
    renderHome(); await screen.findByText('3 / 5');
    expect(screen.queryByRole('link', { name: new RegExp(t('dashboardHome.vacancyTitle')) })).not.toBeInTheDocument();
    analysis();
    const table = openTable('pages.dashboard.occupancyChart');
    const row = within(table).getByRole('row', { name: `${t('dashboardHome.otherUnitStatuses')} 1` });
    expect(row).toBeVisible();
  });

  it('hides creation and protected audit access for readonly users while retaining readable navigation', async () => {
    mocks.admin = false; mocks.readonly = true;
    renderHome(); await screen.findByText('3 / 5');
    expect(screen.queryByRole('link', { name: t('dashboardHome.createContract') })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: t('pages.dashboard.recentActivity') })).not.toBeInTheDocument();
    expect(within(screen.getByRole('complementary', { name: t('dashboardHome.quickActions') })).getByRole('link', { name: t('dashboardHome.openInventory') })).toHaveAttribute('href', '/properties');
    expect(mocks.get.mock.calls.some(([path]) => path === paths.audit)).toBe(false);
  });

  it('loads the protected audit only after expansion and supports a failure retry', async () => {
    failed.add(paths.audit);
    renderHome(); await screen.findByText('3 / 5');
    expect(mocks.get.mock.calls.some(([path]) => path === paths.audit)).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: t('pages.dashboard.recentActivity') }));
    const error = await screen.findByRole('alert');
    failed.clear(); fireEvent.click(within(error).getByRole('button', { name: t('dashboardHome.retry') }));
    const section = screen.getByRole('button', { name: t('pages.dashboard.recentActivity') }).parentElement;
    fireEvent.click(await within(section).findByText(t('dashboardHome.chartValues')));
    expect(within(section).getByRole('table')).toHaveTextContent('Owner');
  });

  it('routes notifications to their actual entity and leaves generic notices as plain text', async () => {
    data[paths.notifications].push({ id: 'general', title: 'Allgemeiner Hinweis', severity: 'info' });
    renderHome();
    expect(await screen.findByRole('link', { name: 'Miete fehlt' })).toHaveAttribute('href', '/rent-charges');
    expect(screen.getByText('Allgemeiner Hinweis')).toBeVisible();
    expect(screen.queryByRole('link', { name: 'Allgemeiner Hinweis' })).not.toBeInTheDocument();
  });

  it('supports keyboard tab navigation with the correct selected panel', async () => {
    renderHome(); await screen.findByText('3 / 5');
    const work = screen.getByRole('tab', { name: t('dashboardHome.workTab') }); work.focus();
    fireEvent.keyDown(work, { key: 'ArrowRight' });
    const analytics = screen.getByRole('tab', { name: t('dashboardHome.analysisTab') });
    expect(analytics).toHaveFocus(); expect(analytics).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', analytics.id);
    fireEvent.keyDown(analytics, { key: 'Home' }); expect(work).toHaveFocus();
  });
});

for (const locale of ['de-DE', 'en-US', 'es-ES']) {
  it(`provides complete translated dashboard labels in ${locale}`, async () => {
    mocks.locale = locale; renderHome(); await screen.findByText('3 / 5');
    expect(screen.getByRole('heading', { name: t('dashboardHome.title') })).toBeVisible();
    expect(screen.getByRole('tab', { name: t('dashboardHome.analysisTab') })).toBeVisible();
    expect(Object.keys(dictionaries[locale].dashboardHome).sort()).toEqual(Object.keys(de.dashboardHome).sort());
    expect(document.body.textContent).not.toContain('dashboardHome.');
  });
}
