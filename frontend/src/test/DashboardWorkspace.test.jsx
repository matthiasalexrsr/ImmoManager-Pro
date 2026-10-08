import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Dashboard from '../pages/Dashboard';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));
vi.mock('recharts', () => {
  const Container = ({ children }) => <div>{children}</div>;
  const Empty = () => null;
  return {
    ResponsiveContainer: Container, BarChart: Container, PieChart: Container, LineChart: Container,
    Bar: Container, Pie: Container, Cell: Empty, XAxis: Empty, YAxis: Empty,
    Tooltip: Empty, Legend: Empty, Line: Empty, CartesianGrid: Empty,
  };
});

const stats = {
  portfolio_count: 2, property_count: 8, unit_count: 40, occupied_units: 30, reserved_units: 2,
  tenant_count: 35, active_contracts: 31, account_count: 3,
  open_receivables: 7, overdue_receivables: 2, dunning_receivables: 1,
  open_tasks: 4, open_maintenance: 1, unread_notifications: 1,
  allocation_key_count: 3, billing_period_count: 1, utility_statement_count: 2,
  document_count: 20, rent_charge_count: 30,
};
const data = {
  '/dashboard/stats': stats,
  '/tasks?status=open&limit=5': [{ id: 't1', title: 'Heizung prüfen', due_date: '2026-10-09', priority: 'high' }],
  '/notifications?status=unread&limit=5': [{ id: 'n1', title: 'Neue Ablesung', severity: 'info' }],
  '/reports/cashflow?months=12': { incomeTotal: 10000, expenseTotal: 2500, netTotal: 7500 },
  '/reports/receivables-aging': { openTotal: 3250, openCredits: 100, buckets: { current: 1500, days1to30: 1750, days31to60: 0, days61to90: 0, days90plus: 0 } },
  '/reports/maintenance-costs': { categories: [{ category: 'Heizung', estimatedCost: 400 }] },
  '/reports/liquidity-forecast?months=6': { forecast: [{ month: '2026-11', projected_balance: 15000, projected_income: 3000, projected_expense: 1000 }] },
  '/reports/contracts-expiring?days=90': { contracts: [{ contractId: 'c1', contractNumber: 'MV-42', endDate: '2026-12-01', daysRemaining: 55 }] },
  '/reports/finance': { totalsByCategory: [{ categoryName: 'Miete', total: 10000 }] },
  '/audit?limit=10': [{ id: 'a1', action: 'create', entity_type: 'task', username: 'Verwaltung', timestamp: '2026-10-07T10:00:00Z' }],
};
const load = path => Promise.resolve(data[path]);
const show = () => render(<MemoryRouter><Dashboard /></MemoryRouter>);
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

beforeEach(() => { vi.resetAllMocks(); api.get.mockImplementation(load); });
afterEach(cleanup);

describe('dashboard working overview', () => {
  it('presents four real inventory metrics, operational content and supported routes', async () => {
    show();
    await screen.findByText('Heizung prüfen');
    expect(screen.getByRole('heading', { level: 1, name: 'Verwaltungsübersicht' })).toBeInTheDocument();
    const metrics = screen.getByRole('region', { name: 'Bestand im Überblick' });
    expect(within(metrics).getAllByRole('link')).toHaveLength(4);
    expect(within(metrics).getByRole('link', { name: /Immobilien/ })).toHaveAttribute('href', '/properties');
    expect(within(metrics).getByRole('link', { name: /Aktive Verträge/ })).toHaveAttribute('href', '/contracts');
    expect(within(metrics).getByText('75 %')).toBeInTheDocument();
    expect(screen.getByText('MV-42')).toBeInTheDocument();
    expect(screen.getByText('Neue Ablesung')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /Forderungen/ }).every(link => link.getAttribute('href') === '/receivables')).toBe(true);
    expect(screen.queryByText('Fortschritt')).not.toBeInTheDocument();
    expect(screen.queryByText('100%')).not.toBeInTheDocument();
  });

  it('renders available inventory without waiting for a slow task request', async () => {
    const tasks = deferred();
    api.get.mockImplementation(path => path.startsWith('/tasks?') ? tasks.promise : load(path));
    show();
    const metrics = await screen.findByRole('region', { name: 'Bestand im Überblick' });
    await waitFor(() => expect(within(metrics).getByText('40')).toBeInTheDocument());
    expect(screen.getByText('Aufgaben werden geladen…')).toBeInTheDocument();
    await act(async () => tasks.resolve(data['/tasks?status=open&limit=5']));
    expect(screen.getByText('Heizung prüfen')).toBeInTheDocument();
  });

  it('labels open-work counts accurately inside the expanded management areas', async () => {
    api.get.mockImplementation(path => path === '/dashboard/stats' ? Promise.resolve({ ...stats, active_contracts_missing_documents: 2, overdue_maintenance: 3, utility_statement_count: 0, billing_preflight_blockers: 4 }) : load(path));
    show();
    await screen.findByText('Heizung prüfen');
    const area = name => screen.getByText(name, { selector: 'summary > strong' }).closest('details');
    for (const name of ['Finanzen', 'Betrieb', 'Abrechnung']) fireEvent.click(within(area(name)).getByText(name, { selector: 'summary > strong' }));
    expect(within(area('Finanzen')).getByRole('link', { name: 'Offene Forderungen 7' })).toHaveAttribute('href', '/receivables');
    expect(within(area('Betrieb')).getByRole('link', { name: 'Offene Aufgaben 4' })).toHaveAttribute('href', '/tasks');
    expect(within(area('Betrieb')).getByRole('link', { name: 'Überfällige Instandhaltung 3' })).toHaveAttribute('href', '/maintenance');
    expect(within(area('Betrieb')).getByRole('link', { name: 'Fehlende Vertragsdokumente 2' })).toHaveAttribute('href', '/documents');
    expect(within(area('Abrechnung')).getByRole('link', { name: 'Abrechnungen 0' })).toHaveAttribute('href', '/statements');
    expect(within(area('Abrechnung')).getByRole('link', { name: 'Offene Rechnungen 0' })).toHaveAttribute('href', '/invoices');
  });

  it('keeps failed inventory unknown and retries that source without reloading the others', async () => {
    let failed = true;
    api.get.mockImplementation(path => path === '/dashboard/stats' && failed ? Promise.reject(new Error('Bestand offline')) : load(path));
    show();
    await screen.findByText('Bestandsdaten konnten nicht geladen werden.');
    const metrics = screen.getByRole('region', { name: 'Bestand im Überblick' });
    expect(within(metrics).getAllByText('—')).toHaveLength(4);
    expect(screen.queryByText(/Alles im gr/)).not.toBeInTheDocument();
    expect(screen.getByText('Heizung prüfen')).toBeInTheDocument();
    const callsBefore = api.get.mock.calls.filter(([path]) => path !== '/dashboard/stats').length;
    failed = false;
    fireEvent.click(within(screen.getByText('Bestandsdaten konnten nicht geladen werden.').closest('[role="alert"]')).getByRole('button'));
    await waitFor(() => expect(within(metrics).getByText('40')).toBeInTheDocument());
    expect(api.get.mock.calls.filter(([path]) => path !== '/dashboard/stats')).toHaveLength(callsBefore);
  });

  it('does not turn a task failure into an empty task list and offers a local retry', async () => {
    let failed = true;
    api.get.mockImplementation(path => path.startsWith('/tasks?') && failed ? Promise.reject(new Error('Aufgaben offline')) : load(path));
    show();
    const error = await screen.findByText('Aufgaben konnten nicht geladen werden.');
    expect(screen.queryByText('Keine offenen Aufgaben.')).not.toBeInTheDocument();
    failed = false;
    fireEvent.click(within(error.closest('[role="alert"]')).getByRole('button'));
    await screen.findByText('Heizung prüfen');
    expect(api.get.mock.calls.filter(([path]) => path === '/dashboard/stats')).toHaveLength(1);
  });

  it('rejects malformed inventory instead of rendering a false zero portfolio', async () => {
    api.get.mockImplementation(path => path === '/dashboard/stats' ? Promise.resolve([]) : load(path));
    show();
    await screen.findByText('Bestandsdaten konnten nicht geladen werden.');
    expect(within(screen.getByRole('region', { name: 'Bestand im Überblick' })).getAllByText('—')).toHaveLength(4);
  });

  it('keeps finance errors separate from available tasks and real financial values', async () => {
    api.get.mockImplementation(path => path === '/reports/cashflow?months=12' ? Promise.resolve({}) : load(path));
    show();
    await screen.findByText('Zahlungsübersicht konnte nicht geladen werden.');
    expect(screen.getByText('Heizung prüfen')).toBeInTheDocument();
    expect(screen.getByText(/3\.250,00/)).toBeInTheDocument();
    expect(screen.queryByText(/^0,00\s*€/)).not.toBeInTheDocument();
  });

  it('retains all six analysis reports behind the analysis view', async () => {
    show();
    await screen.findByText('Heizung prüfen');
    expect(api.get).not.toHaveBeenCalledWith('/reports/finance', expect.anything());
    fireEvent.click(screen.getByRole('button', { name: 'Analyse' }));
    for (const title of ['Belegung', 'Zahlungsfluss · 12 Monate', 'Alter offener Forderungen', 'Liquiditätsprognose', 'Instandhaltungskosten', 'Finanzen nach Kategorie']) {
      expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument();
    }
    expect(api.get).toHaveBeenCalledWith('/reports/finance', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    fireEvent.click(screen.getByRole('button', { name: 'Arbeit' }));
    expect(screen.getByText('Heizung prüfen')).toBeInTheDocument();
  });

  it('opens activity through a semantic toggle and exposes its own load failure and retry', async () => {
    let failed = true;
    api.get.mockImplementation(path => path === '/audit?limit=10' && failed ? Promise.reject(new Error('Audit offline')) : load(path));
    show();
    const toggle = screen.getByRole('button', { name: 'Letzte Aktivitäten' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    const error = await screen.findByText('Aktivitäten konnten nicht geladen werden.');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    failed = false;
    fireEvent.click(within(error.closest('[role="alert"]')).getByRole('button'));
    await screen.findByText('Verwaltung');
  });

  it('aborts pending requests when leaving the working overview', () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    const view = show();
    const requests = api.get.mock.calls.map(([, options]) => options);
    expect(requests.length).toBeGreaterThan(0);
    view.unmount();
    expect(requests.every(options => options?.signal?.aborted)).toBe(true);
  });
});
