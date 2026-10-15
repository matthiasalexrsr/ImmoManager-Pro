import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Bookings from '../pages/Bookings';
import Receivables from '../pages/Receivables';
import Contracts from '../pages/Contracts';
import Budgets from '../pages/Budgets';
import { api } from '../api';
import { cashflowSide } from '../utils/cashflowBasis';
import { occupancyMapOn } from '../utils/occupancy';

const fixture = vi.hoisted(() => ({ entities: {} }));
vi.mock('../api', () => ({ api: { list: vi.fn(), get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => null, useCanWrite: () => true }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null, useEntities: key => ({ items: fixture.entities[key] || [], loading: false, error: null }) }));
vi.mock('../components/DataTable', () => ({ default: ({ data }) => <ul aria-label="Quellvorgänge">{data.map(row => <li key={row.id}>{row.id}</li>)}</ul> }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn() }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn(), success: vi.fn() }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));
const mount = (component, route) => render(<MemoryRouter initialEntries={[route]}>{component}</MemoryRouter>);
beforeEach(() => { vi.resetAllMocks(); fixture.entities = {}; api.get.mockResolvedValue([]); api.list.mockResolvedValue([]); });
afterEach(cleanup);

describe('Kennzahlen öffnen ihre fachlichen Quellen', () => {
  it('keeps refunds and reversals on their original cashflow side', () => {
    const categories = [{ id: 'cost', category_type: 'expense' }];
    expect(cashflowSide({ amount: 50, category_id: 'cost' }, categories)).toBe('expense');
    expect(cashflowSide({ amount: -20, tenant_id: 'party' }, [])).toBe('income');
    expect(cashflowSide({ amount: 25, reverses_booking_id: 'expense' }, [])).toBe('expense');
    expect(cashflowSide({ amount: -25, reverses_booking_id: 'income' }, [])).toBe('income');
  });
  it('inherits the report period and includes the refund in the income sources', async () => {
    api.list.mockResolvedValue([
      { id: 'rent', amount: 100, tenant_id: 'party', booking_date: '2026-01-01' },
      { id: 'refund', amount: -30, tenant_id: 'party', booking_date: '2026-01-31' },
      { id: 'other-month', amount: 900, tenant_id: 'party', booking_date: '2026-02-01' },
      { id: 'cost', amount: -10, booking_date: '2026-01-15' },
    ]);
    mount(<Bookings />, '/bookings?date_from=2026-01-01&date_to=2026-01-31&flow=income');
    const income = await screen.findByRole('button', { name: 'Einnahmen: Quellvorgänge anzeigen' });
    expect(income).toHaveTextContent('70,00');
    expect(screen.getByRole('list')).toHaveTextContent('rentrefund');
    expect(screen.getByRole('list')).not.toHaveTextContent('cost');
    fireEvent.click(screen.getByRole('button', { name: 'Ausgaben: Quellvorgänge anzeigen' }));
    expect(screen.getByRole('list')).toHaveTextContent('cost');
    expect(screen.getByRole('list')).not.toHaveTextContent('refund');
  });
  it('overdue sources include partially paid past-due debts, exclude credits and cancelled debt', async () => {
    api.list.mockResolvedValue([
      { id: 'partial-debt', status: 'partial', amount_due: 25, due_date: '2000-01-01' },
      { id: 'credit', status: 'overdue', amount_due: -25, due_date: '2000-01-01' },
      { id: 'cancelled', status: 'cancelled', amount_due: 25, due_date: '2000-01-01' },
      { id: 'future', status: 'open', amount_due: 25, due_date: '2099-01-01' },
    ]);
    mount(<Receivables />, '/receivables?status=overdue');
    expect(await screen.findByRole('list')).toHaveTextContent('partial-debt');
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });
  it('missing contract documents opens only active undocumented contracts', async () => {
    fixture.entities.documents = [{ id: 'd1', contract_id: 'documented' }];
    api.list.mockResolvedValue([{ id: 'missing', status: 'active' }, { id: 'documented', status: 'active' }, { id: 'draft', status: 'draft' }]);
    api.get.mockResolvedValue({});
    mount(<Contracts />, '/contracts?filter=missing_documents');
    expect(await screen.findByRole('list')).toHaveTextContent('missing');
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });
  it('shows a load error instead of invented zero budget totals', async () => {
    api.list.mockRejectedValue(new Error('Sicherung läuft, bitte wiederholen'));
    mount(<Budgets />, '/budgets');
    expect(await screen.findByRole('alert')).toHaveTextContent('Sicherung läuft');
    expect(screen.queryByRole('button', { name: 'Geplant gesamt: Quellvorgänge anzeigen' })).not.toBeInTheDocument();
  });
  it('matches occupancy dates, terminated tenancies, drafts and manually occupied units', () => {
    const units = ['current', 'future', 'past', 'manual', 'draft'].map(id => ({ id, status: 'occupied' }));
    const contracts = [
      { id: 'a', unit_id: 'current', status: 'terminated', start_date: '2026-01-01', end_date: '2026-10-15', tenant_id: 'party' },
      { id: 'b', unit_id: 'future', status: 'active', start_date: '2026-10-16' },
      { id: 'c', unit_id: 'past', status: 'terminated', start_date: '2020-01-01', end_date: '2026-10-14' },
      { id: 'd', unit_id: 'draft', status: 'draft', start_date: '2020-01-01' },
    ];
    const states = occupancyMapOn(units, contracts, '2026-10-15');
    expect(states.current).toEqual({ status: 'occupied', tenant_id: 'party' });
    expect(states.future.status).toBe('vacant'); expect(states.past.status).toBe('vacant');
    expect(states.manual.status).toBe('occupied'); expect(states.draft.status).toBe('occupied');
  });
});
