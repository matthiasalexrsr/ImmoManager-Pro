import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Bookings from '../pages/Bookings';
import { api } from '../api';

const context = vi.hoisted(() => ({
  owners: [{ id: 'linda', name: 'Linda' }, { id: 'matthias', name: 'Matthias' }],
  categories: [{ id: 'cost', name: 'Kosten', category_type: 'expense' }],
  empty: [], store: { invalidateRelated: vi.fn() },
}));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => null }));
vi.mock('../contexts/DataStoreContext', () => ({
  useEntities: key => ({ items: key === 'owners' ? context.owners : key === 'categories' ? context.categories : context.empty,
    loading: false, error: null }),
  useDataStore: () => context.store,
}));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn(), success: vi.fn() }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));

const booking = (id, amount, text) => ({ id, account_id: 'a1', category_id: 'cost', property_id: 'p1', booking_date: '2026-03-15',
  amount, payment_text: text, status: 'booked', receipt_url: null });
const bookings = [booking('b1', -200, 'Gebäudeversicherung'), booking('b2', -100, 'Reparatur WE 3'), booking('b3', -10, 'Kontoführung')];

beforeEach(() => {
  vi.resetAllMocks();
  api.get.mockResolvedValue({ allocations: [], reserved_amounts: {} });
  api.list.mockImplementation(path => Promise.resolve(path === '/bookings?owner_contact_id=linda'
    ? [{ ...bookings[0], owner_part: -110 }, { ...bookings[1], owner_part: -50 }] : bookings));
});
afterEach(cleanup);

describe('bookings of one owner', () => {
  it('lists only the owner\'s bookings with their part and adds up their part', async () => {
    render(<MemoryRouter initialEntries={['/bookings']}><Bookings /></MemoryRouter>);
    await screen.findByText('Kontoführung');
    expect(screen.getByRole('button', { name: 'Ausgaben: Quellvorgänge anzeigen' })).toHaveTextContent('310,00');
    fireEvent.change(screen.getByLabelText('Eigentümer'), { target: { value: 'linda' } });
    await screen.findByRole('columnheader', { name: /Anteil des Eigentümers/ });
    expect(api.list).toHaveBeenCalledWith('/bookings?owner_contact_id=linda', expect.anything());
    expect(screen.queryByText('Kontoführung')).not.toBeInTheDocument();
    const insurance = screen.getByText('Gebäudeversicherung').closest('tr');
    expect(within(insurance).getByText(/-110,00/)).toBeInTheDocument();
    // the figures are Linda's part: 110 + 50
    expect(screen.getByRole('button', { name: 'Ausgaben: Quellvorgänge anzeigen' })).toHaveTextContent('160,00');
  });
});
