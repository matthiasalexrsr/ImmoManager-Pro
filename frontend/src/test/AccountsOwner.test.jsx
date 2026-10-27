import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Accounts from '../pages/Accounts';
import { api } from '../api';

const context = vi.hoisted(() => ({
  owners: [{ id: 'linda', name: 'Linda' }, { id: 'matthias', name: 'Matthias' }],
  empty: [], store: { invalidateRelated: vi.fn() },
}));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => (key === 'ui.buttons.new' ? 'Neu' : undefined), locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => null }));
vi.mock('../contexts/DataStoreContext', () => ({
  useEntities: key => ({ items: key === 'owners' ? context.owners : context.empty, loading: false, error: null }),
  useDataStore: () => context.store,
}));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn(), success: vi.fn() }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));

beforeEach(() => {
  vi.resetAllMocks();
  api.list.mockResolvedValue([
    { id: 'a1', name: 'Konto', portfolio_id: 'p', account_type: 'Girokonto', opening_balance: 0, balance: -1310 },
    { id: 'a2', name: 'Konto Linda', portfolio_id: 'p', account_type: 'Girokonto', opening_balance: 500, balance: 1200, owner_contact_id: 'linda' },
  ]);
  api.get.mockResolvedValue({ as_of: '2026-03-31', owners: [
    { owner_contact_id: 'linda', name: 'Linda', balance: 40, accounts: [{ account_id: 'a1', name: 'Konto', balance: -1160 }, { account_id: 'a2', name: 'Konto Linda', balance: 1200 }] },
    { owner_contact_id: 'matthias', name: 'Matthias', balance: -140, accounts: [{ account_id: 'a1', name: 'Konto', balance: -140 }] },
    { owner_contact_id: 'none', name: 'Ohne Eigentümer', balance: -10, accounts: [{ account_id: 'a1', name: 'Konto', balance: -10 }] },
  ], accounts: [] });
});
afterEach(cleanup);

describe('account balances by owner', () => {
  it('shows each owner\'s part of the balances adding up to the total', async () => {
    render(<MemoryRouter><Accounts /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'Kontostand je Eigentümer: Quellvorgänge anzeigen' }));
    const section = await screen.findByRole('region', { name: 'Kontostand je Eigentümer' });
    expect(api.get).toHaveBeenCalledWith('/accounts/owner-balances');
    const linda = within(section).getByText('Linda').closest('tr');
    expect(linda).toHaveTextContent('Konto Linda: 1.200,00');
    expect(linda).toHaveTextContent('40,00');
    // the owners add up to the total of the accounts (-1310 + 1200)
    expect(within(section).getByText('Gesamt').closest('tr')).toHaveTextContent('-110,00');
  });

  it('offers the account holder in the account form', async () => {
    render(<MemoryRouter><Accounts /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: /Neu/ }));
    const holder = await screen.findByLabelText('Kontoinhaber (Eigentümer)');
    expect(within(holder).getByRole('option', { name: 'Gemeinsames Konto' })).toBeInTheDocument();
    expect(within(holder).getByRole('option', { name: 'Linda' })).toBeInTheDocument();
  });
});
