import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import TenantAccount from '../pages/TenantAccount';
import Bookings from '../pages/Bookings';
import { api } from '../api';

const context = vi.hoisted(() => ({
  confirm: null, store: { invalidateRelated: vi.fn() }, toast: { error: vi.fn(), success: vi.fn() },
}));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true }));
vi.mock('../contexts/DataStoreContext', () => ({
  useEntities: () => ({ items: [], loading: false, error: null }),
  useDataStore: () => context.store,
}));
vi.mock('../components/Toast', () => ({ useToast: () => context.toast }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => context.confirm }));

beforeEach(() => {
  vi.resetAllMocks();
  context.confirm = vi.fn().mockResolvedValue(true);
});
afterEach(cleanup);

describe('Tenant account totals', () => {
  it('shows the exact totals of the server instead of adding rounded rows', async () => {
    // 0.1 + 0.2 - 0.3 is 5.55e-17 in floating point: the account would read "Offen" in red
    const account = {
      contracts: [
        { contract_id: 'a', contract_number: 'MV-A', expected: 0.1, paid: 0, outstanding: 0.1, overpaid: 0 },
        { contract_id: 'b', contract_number: 'MV-B', expected: 0.2, paid: 0, outstanding: 0.2, overpaid: 0 },
        { contract_id: 'c', contract_number: 'MV-C', expected: 0, paid: 0.3, outstanding: 0, overpaid: 0.3 },
      ],
      totals: { expected: 0.3, paid: 0.3, outstanding: 0.3, overpaid: 0.3, balance: 0, unassigned: 0 },
      unassigned: [],
    };
    api.get.mockImplementation(path => Promise.resolve(path.includes('/account') ? account : { full_name: 'Mia' }));
    render(<MemoryRouter initialEntries={['/tenants/t1/account']}>
      <Routes><Route path="/tenants/:id/account" element={<TenantAccount />} /></Routes>
    </MemoryRouter>);

    const label = (await screen.findAllByText('Offen')).find(element => element.classList.contains('stat-label'));
    const value = label.parentElement.querySelector('.stat-value');
    expect(value).toHaveTextContent('0,00');
    expect(value).not.toHaveClass('text-red');
  });
});

describe('Booking reversal', () => {
  const booking = { id: 'b1', tenant_id: null, account_id: 'a1', category_id: null, property_id: null, unit_id: null,
    booking_date: '2026-02-03', amount: 633.33, payment_text: 'Miete Februar', receipt_url: null, status: 'booked',
    reverses_booking_id: null };
  const mount = id => render(<MemoryRouter initialEntries={[`/bookings?booking_id=${id}`]}><Bookings /></MemoryRouter>);
  const selected = () => screen.getByRole('region', { name: 'Ausgewählte Buchung' });

  it('books a linked counter-booking after confirmation', async () => {
    api.list.mockResolvedValue([booking]);
    api.get.mockImplementation(path => Promise.resolve(path === '/bookings/allocations' ? [] : booking));
    api.post.mockResolvedValue({ ...booking, id: 'r1', amount: -633.33, reverses_booking_id: 'b1' });
    mount('b1');
    await within(await screen.findByRole('region', { name: 'Ausgewählte Buchung' })).findByText('Miete Februar');

    fireEvent.click(within(selected()).getByRole('button', { name: 'Stornieren' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/bookings/b1/reverse', {}));
    expect(context.confirm.mock.calls[0][0]).toContain('beide zusammen zählen in allen Auswertungen null');
    await waitFor(() => expect(context.toast.success).toHaveBeenCalledWith('Storno gebucht'));
  });

  it('does nothing without confirmation', async () => {
    context.confirm = vi.fn().mockResolvedValue(false);
    api.list.mockResolvedValue([booking]);
    api.get.mockImplementation(path => Promise.resolve(path === '/bookings/allocations' ? [] : booking));
    mount('b1');
    await within(await screen.findByRole('region', { name: 'Ausgewählte Buchung' })).findByText('Miete Februar');
    fireEvent.click(within(selected()).getByRole('button', { name: 'Stornieren' }));
    await waitFor(() => expect(context.confirm).toHaveBeenCalled());
    expect(api.post).not.toHaveBeenCalled();
  });

  it('shows a reversal with its original and offers no second reversal', async () => {
    const reversal = { ...booking, id: 'r1', amount: -633.33, payment_text: 'Rücklastschrift', reverses_booking_id: 'b1' };
    api.list.mockResolvedValue([reversal]);
    api.get.mockImplementation(path => Promise.resolve(path === '/bookings/allocations' ? [] : reversal));
    mount('r1');
    await within(await screen.findByRole('region', { name: 'Ausgewählte Buchung' })).findByText('Rücklastschrift');

    expect(within(selected()).getByRole('link', { name: 'Stornierte Buchung öffnen' }))
      .toHaveAttribute('href', '/bookings?booking_id=b1');
    expect(within(selected()).queryByRole('button', { name: 'Stornieren' })).not.toBeInTheDocument();
    expect(await screen.findByTitle('Storno: zählt mit der stornierten Buchung zusammen')).toHaveTextContent('Storno');
  });
});
