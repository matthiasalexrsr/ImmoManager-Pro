import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import Accounts from '../pages/Accounts';
import { EDIT_REVISION } from '../editRevision';
import german from '../../../i18n/de-DE.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), reload: vi.fn(), invalidate: vi.fn(), role: 'eigentuemer' }));
vi.mock('../api', () => ({ api: { get: mocks.get, patch: mocks.patch } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'synthetic-owner', role: mocks.role }, role: mocks.role }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => ({ invalidateRelated: mocks.invalidate }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn() }));
vi.mock('../hooks/useFinanceData', () => ({ useFinanceData: () => ({ data: { accounts: [], portfolios: [] }, loading: false,
  error: new Error('Full legacy account read unavailable'), reload: mocks.reload }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: key => key.split('.').reduce((value, part) => value?.[part], german) || key }) }));

const originalStamp = '2026-10-01T12:00:00.123456Z';
beforeEach(() => {
  vi.clearAllMocks(); mocks.role = 'eigentuemer'; mocks.patch.mockResolvedValue({});
  mocks.get.mockImplementation(async path => {
    if (path.startsWith('/bookings/lookup/')) return { items: [{ id: 'legacy', label: 'Legacy bank' }], has_more: false };
    if (path.includes('balance-summary')) return { account_id: 'legacy', account_name: 'Legacy bank', account_updated_at: originalStamp,
      source_kind: 'stored_account_and_cash_bookings', source_hash: 'a'.repeat(64), opening_balance_cents: null, comparison_balance_cents: null,
      calculated_balance_cents: null, difference_cents: null, bookings_sum_cents: '0', income_sum_cents: '0', expense_sum_cents: '0',
      is_computable: false, booking_count: 0, issues_count: 2, issues_sample: [],
      status_totals: Object.fromEntries(['open', 'matched', 'booked', 'confirmed', 'other'].map(key => [key, { booking_count: 0, amount_cents: '0' }])) };
    if (path.includes('balance-sources')) return { items: [], has_more: false, source_count: 0 };
    throw new Error('A complete invalid account cannot be read');
  });
});

async function repair() {
  fireEvent.click(screen.getByRole('button', { name: german.accountBalance.title, exact: true }));
  await screen.findByRole('option', { name: 'Legacy bank' });
  fireEvent.change(screen.getByRole('combobox', { name: 'Konto', exact: true }), { target: { value: 'legacy' } });
  fireEvent.click(await screen.findByRole('button', { name: german.accountBalance.repairValues, exact: true }));
  const dialog = screen.getByRole('dialog');
  fireEvent.change(within(dialog).getByLabelText(/Anfangsbestand/), { target: { value: '10.00' } });
  fireEvent.change(within(dialog).getByLabelText(/Manueller Vergleichssaldo/), { target: { value: '20.00' } });
  fireEvent.submit(dialog.querySelector('form'));
  await waitFor(() => expect(mocks.patch).toHaveBeenCalledOnce());
  return dialog;
}

it('repairs only two explicit amounts with their original version despite a failed legacy list', async () => {
  render(<Accounts />);
  await repair();
  expect(mocks.patch.mock.calls[0][0]).toBe('/accounts/legacy');
  const payload = mocks.patch.mock.calls[0][1];
  expect(Object.keys(payload)).toEqual(['opening_balance', 'balance']);
  expect(payload).toMatchObject({ opening_balance: 10, balance: 20 });
  expect(payload[EDIT_REVISION]).toMatchObject({ id: 'legacy', updatedAt: originalStamp });
  expect(mocks.get.mock.calls.some(([path]) => path === '/accounts/legacy')).toBe(false);
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(mocks.reload).toHaveBeenCalledOnce();
});

it('keeps a repair draft on conflict and does not automatically refresh or repeat its PATCH', async () => {
  mocks.patch.mockRejectedValue(Object.assign(new Error('Account changed'), { isEditConflict: true, resourcePath: '/accounts/legacy' }));
  render(<Accounts />);
  const dialog = await repair();
  await waitFor(() => expect(within(dialog).getByRole('alert')).toHaveTextContent('Account changed'));
  expect(within(dialog).getByLabelText(/Anfangsbestand/)).toHaveValue(10);
  expect(within(dialog).getByLabelText(/Manueller Vergleichssaldo/)).toHaveValue(20);
  expect(mocks.patch).toHaveBeenCalledOnce();
  expect(mocks.get.mock.calls.some(([path]) => path === '/accounts/legacy')).toBe(false);
});

it('allows a reader to inspect legacy evidence but exposes no account repair action', async () => {
  mocks.role = 'readonly';
  render(<Accounts />);
  fireEvent.click(screen.getByRole('button', { name: german.accountBalance.title, exact: true }));
  await screen.findByRole('option', { name: 'Legacy bank' });
  fireEvent.change(screen.getByRole('combobox', { name: 'Konto', exact: true }), { target: { value: 'legacy' } });
  await screen.findByText(german.accountBalance.blocked);
  expect(screen.queryByRole('button', { name: german.accountBalance.repairValues, exact: true })).not.toBeInTheDocument();
  expect(mocks.patch).not.toHaveBeenCalled();
});
