import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import Accounts from '../pages/Accounts';
import Invoices from '../pages/Invoices';
import Receivables from '../pages/Receivables';
import RentCharges from '../pages/RentCharges';
import RentAdjustments from '../pages/RentAdjustments';
import Budgets from '../pages/Budgets';
import Deposits from '../pages/Deposits';
import AllocationKeys from '../pages/AllocationKeys';
import Categories from '../pages/Categories';
import TaxRates from '../pages/TaxRates';
import Insurances from '../pages/Insurances';
import Meters from '../pages/Meters';

const mocks = vi.hoisted(() => ({ lists: {}, invalidateRelated: vi.fn(), confirm: vi.fn(), toast: { error: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ role: 'eigentuemer' }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key.split('.').at(-1) }) }));
vi.mock('../contexts/DataStoreContext', () => ({
  useDataStore: () => ({ invalidateRelated: mocks.invalidateRelated }),
  useEntities: (_key, path) => ({ items: mocks.lists[path] || [], loading: false, error: null, reload: vi.fn() }),
}));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../components/Toast', () => ({ useToast: () => mocks.toast }));
vi.mock('../components/DataTable', () => ({
  default: ({ title, data, columns, onAdd, onEdit, onDelete }) => (
    <section aria-label={title || 'readings'}>
      <output data-testid="row-count">{data.length}</output>
      {onAdd && <button onClick={onAdd}>Add</button>}
      {data.slice(-1).map(row => <div key={row.id} data-testid="last-row">
        {columns.map(col => <span key={col.key}>{col.render ? col.render(row[col.key], row) : String(row[col.key] ?? '')}</span>)}
        {onEdit && <button onClick={() => onEdit(row)}>Edit</button>}
        {onDelete && <button onClick={() => onDelete(row)}>Delete</button>}
      </div>)}
    </section>
  ),
}));

const cases = [
  ['Accounts', Accounts, '/accounts', ['/portfolios']],
  ['Invoices', Invoices, '/invoices', ['/properties', '/tax-rates']],
  ['Receivables', Receivables, '/receivables', ['/contracts']],
  ['RentCharges', RentCharges, '/rent-charges', ['/contracts']],
  ['RentAdjustments', RentAdjustments, '/rent-adjustments', ['/contracts']],
  ['Budgets', Budgets, '/budgets', ['/properties']],
  ['Deposits', Deposits, '/deposits', ['/contracts']],
  ['AllocationKeys', AllocationKeys, '/billing/allocation-keys', ['/properties']],
  ['Categories', Categories, '/categories', ['/portfolios']],
  ['TaxRates', TaxRates, '/tax-rates', []],
  ['Insurances', Insurances, '/insurances', ['/properties', '/units']],
  ['Meters', Meters, '/meters', ['/units', '/properties', '/meters/readings/all']],
];
let failedPaths;
let mutationStatus;
const requests = [];
function row(index = 0) {
  return { id: `row-${index}`, name: `Name ${index}`, label: `Unit ${index}`,
    contract_number: `Contract ${index}`, serial_number: `Meter ${index}`, full_name: `Tenant ${index}`,
    portfolio_id: `row-${index}`, property_id: `row-${index}`, unit_id: `row-${index}`,
    account_id: `row-${index}`, category_id: `row-${index}`, tenant_id: `row-${index}`,
    contract_id: `row-${index}`, meter_id: `row-${index}`, status: 'open', is_active: true,
    supplier: `Supplier ${index}`, provider: `Provider ${index}`, invoice_number: `RE-${index}`,
    invoice_date: '2026-01-01', booking_date: '2026-01-01', due_date: '2026-02-01',
    effective_date: '2026-02-01', reading_date: '2026-01-01', month: '2026-01', year: 2026,
    amount: '0.01', amount_due: '0.01', amount_paid: '0.00', balance: '0.01', net_amount: '0.01',
    gross_amount: '0.01', vat_amount: '0.00', vat_rate: 0, rate: 0, is_default: true,
    planned_amount: '0.01', actual_amount: '0.02', cold_rent: '0.01', service_charge: '0.00',
    heating_charge: '0.00', other_charges: '0.00', new_rent: '0.02', previous_rent: '0.01',
    adjustment_type: 'index', key_type: 'area_sqm', value: '10.00' };
}
function response(body, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}
beforeEach(() => {
  requests.length = 0;
  failedPaths = new Set();
  mutationStatus = 200;
  mocks.confirm.mockResolvedValue(true);
  mocks.invalidateRelated.mockClear();
  mocks.lists = Object.fromEntries(cases.flatMap(([, , path, refs]) => [path, ...refs]).map(path => [path, [row()]]));
  localStorage.clear();
  localStorage.setItem('access_token', 'synthetic-test-token');
  vi.stubGlobal('fetch', vi.fn(async (url, options = {}) => {
    const parsed = new URL(url, 'http://localhost');
    const path = parsed.pathname.replace('/api/v1', '');
    const method = options.method || 'GET';
    requests.push({ path, method, params: parsed.searchParams, signal: options.signal });
    if (method !== 'GET') return response(mutationStatus >= 400 ? { detail: 'Mutation failed' } : row(), mutationStatus);
    if (failedPaths.has(path)) return response({ detail: `Load failed: ${path}` }, 503);
    const rows = mocks.lists[path] || [];
    const skip = Number(parsed.searchParams.get('skip') || 0);
    const limit = Number(parsed.searchParams.get('limit') || 100);
    return response(rows.slice(skip, skip + limit));
  }));
});

describe.each(cases)('%s finance loading', (_name, Page, path, refs) => {
  it('loads all primary and reference pages, not just the default 100 rows', async () => {
    for (const source of [path, ...refs]) mocks.lists[source] = Array.from({ length: 1001 }, (_, i) => row(i));
    render(<Page />);
    await waitFor(() => expect(screen.getAllByTestId('row-count')[0]).toHaveTextContent(/^1001$/));
    for (const source of [path, ...refs]) {
      expect(requests.some(r => r.path === source && r.params.get('skip') === '1000')).toBe(true);
    }
    if (refs.includes('/contracts')) expect(screen.getByTestId('last-row')).toHaveTextContent('Contract 1000');
  });

  it.each(['primary', ...refs])('keeps %s failures visible and recovers via retry', async source => {
    const failing = source === 'primary' ? path : source;
    failedPaths.add(failing);
    render(<Page />);
    expect(await screen.findByRole('alert')).toHaveTextContent(`Load failed: ${failing}`);
    expect(screen.queryByTestId('row-count')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add' })).not.toBeInTheDocument();
    failedPaths.clear();
    fireEvent.click(screen.getByRole('button', { name: 'retry' }));
    expect(await screen.findByTestId('row-count')).toHaveTextContent(/^1$/);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('distinguishes successful empty results from a failed request', async () => {
    mocks.lists[path] = [];
    render(<Page />);
    expect(await screen.findByTestId('row-count')).toHaveTextContent(/^0$/);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add' })).toBeEnabled();
  });
});

describe('finance mutations and totals', () => {
  it.each([['Accounts', Accounts], ['Invoices', Invoices]])('%s shows deletion failures', async (...scenario) => {
    const Page = scenario[1];
    mutationStatus = 409;
    render(<Page />);
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Mutation failed');
    expect(screen.getByTestId('row-count')).toHaveTextContent(/^1$/);
  });
  it('shows invoice status-update failures without an unhandled rejection', async () => {
    mutationStatus = 409;
    render(<Invoices />);
    fireEvent.click(await screen.findByRole('button', { name: '✓ Bezahlt' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Mutation failed');
  });

  it('retries a failed post-mutation refresh without repeating the mutation', async () => {
    render(<Invoices />);
    const button = await screen.findByRole('button', { name: '✓ Bezahlt' });
    failedPaths.add('/invoices');
    fireEvent.click(button);
    expect(await screen.findByRole('alert')).toHaveTextContent('Load failed: /invoices');
    failedPaths.clear();
    fireEvent.click(screen.getByRole('button', { name: 'retry' }));
    await screen.findByTestId('row-count');
    expect(requests.filter(r => r.method === 'PATCH')).toHaveLength(1);
  });

  it('adds decimal-string budgets as cents rather than concatenating strings', async () => {
    mocks.lists['/budgets'] = [
      { ...row(), planned_amount: '10.25', actual_amount: '12.20' },
      { ...row(1), planned_amount: '20.10', actual_amount: '25.30' },
    ];
    const { container } = render(<Budgets />);
    await screen.findByTestId('row-count');
    expect(container.querySelector('.stats-grid')).toHaveTextContent('30,35');
    expect(container.querySelector('.stats-grid')).toHaveTextContent('37,50');
    expect(container.querySelector('.stats-grid')).toHaveTextContent('7,15');
  });
});

describe('complete snapshots and form refreshes', () => {
  it.each(['/accounts', '/portfolios'])('does not publish a partial result when page two of %s fails', async source => {
    mocks.lists[source] = Array.from({ length: 1001 }, (_, index) => row(index));
    const originalFetch = globalThis.fetch;
    vi.stubGlobal('fetch', vi.fn((url, options) => {
      const parsed = new URL(url, 'http://localhost');
      if (parsed.pathname === `/api/v1${source}` && parsed.searchParams.get('skip') === '1000') {
        return Promise.resolve(response({ detail: 'Second page failed' }, 503));
      }
      return originalFetch(url, options);
    }));
    render(<Accounts />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Second page failed');
    expect(screen.queryByTestId('row-count')).not.toBeInTheDocument();
    vi.stubGlobal('fetch', originalFetch);
    fireEvent.click(screen.getByRole('button', { name: 'retry' }));
    await screen.findByTestId('row-count');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('includes references beyond page one in editable selectors', async () => {
    mocks.lists['/portfolios'] = Array.from({ length: 1001 }, (_, index) => row(index));
    render(<Accounts />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add' }));
    const option = screen.getByRole('dialog').querySelector('option[value="row-1000"]');
    expect(option).toHaveTextContent('Name 1000');
    expect(option).toHaveValue('row-1000');
  });
  it('does not reopen a saved form or repeat a write when reloading fails', async () => {
    render(<TaxRates />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = screen.getByRole('dialog');
    failedPaths.add('/tax-rates');
    fireEvent.submit(dialog.querySelector('form'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Load failed: /tax-rates');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    failedPaths.clear();
    fireEvent.click(screen.getByRole('button', { name: 'retry' }));
    await screen.findByTestId('row-count');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(requests.filter(r => r.method === 'PUT')).toHaveLength(1);
  });

  it('uses all reading pages for the latest meter value and consumption history', async () => {
    mocks.lists['/meters/readings/all'] = Array.from({ length: 1001 }, (_, index) => ({
      id: `reading-${index}`, meter_id: 'row-0', value: String(index),
      reading_date: new Date(Date.UTC(2020, 0, 1 + index)).toISOString().slice(0, 10),
    }));
    render(<Meters />);
    expect(await screen.findByTestId('last-row')).toHaveTextContent('1000.00');
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    expect(screen.getAllByTestId('row-count')[1]).toHaveTextContent(/^1001$/);
    expect(screen.getAllByTestId('last-row')[1]).toHaveTextContent('1000.001.00');
    expect(requests.some(r => r.path === '/meters/row-0/readings')).toBe(false);
  });
});
