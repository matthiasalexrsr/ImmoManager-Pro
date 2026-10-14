import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Bookings from '../pages/Bookings';
import { api } from '../api';

const context = vi.hoisted(() => ({
  canWrite: true, categories: [], contractsError: null, contractsLoading: false,
  empty: [], contracts: [{ id: 'c1', tenant_id: 't1', contract_number: 'MV-1' }],
  accounts: [{ id: 'a1', name: 'Mietkonto' }],
  store: { invalidateRelated: vi.fn() }, toast: { error: vi.fn(), success: vi.fn() },
}));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => ({
  'ui.buttons.save': 'Speichern', 'ui.buttons.cancel': 'Abbrechen', 'ui.buttons.close': 'Schließen',
  'ui.buttons.edit': 'Bearbeiten', 'ui.buttons.delete': 'Löschen', 'ui.buttons.new': 'Neu',
})[key], locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => context.canWrite }));
vi.mock('../contexts/DataStoreContext', () => ({
  useEntities: key => ({
    items: key === 'categories' ? context.categories : key === 'contracts' ? context.contracts
      : key === 'accounts' ? context.accounts : context.empty,
    loading: key === 'contracts' && context.contractsLoading,
    error: key === 'contracts' ? context.contractsError : null,
  }),
  useDataStore: () => context.store,
}));
vi.mock('../components/Toast', () => ({ useToast: () => context.toast }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));

const target = { id: 'target', tenant_id: 't1', account_id: 'a1', category_id: 'cat-assigned',
  property_id: 'p1', unit_id: 'u1', booking_date: '2026-09-03', amount: 612,
  payment_text: 'Miete September', receipt_url: null, status: 'open', updated_at: '2026-09-03T10:00:00Z' };
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const mount = () => render(<MemoryRouter initialEntries={['/bookings?booking_id=target']}><Bookings /></MemoryRouter>);
const selected = () => screen.getByRole('region', { name: 'Ausgewählte Buchung' });

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  context.canWrite = true;
  context.categories = [];
  context.contractsError = null;
  context.contractsLoading = false;
  api.list.mockResolvedValue([]);
  api.get.mockImplementation(path => Promise.resolve(path === '/bookings/allocations' ? [] : target));
});
afterEach(cleanup);

describe('Independent booking review boundaries', () => {
  it('preserves a reopened edit draft when an older edit save completes', async () => {
    const pending = deferred();
    api.put.mockReturnValue(pending.promise);
    mount();
    await screen.findByText('Miete September');
    fireEvent.click(within(selected()).getByRole('button', { name: 'Bearbeiten' }));
    const oldForm = screen.getByRole('dialog', { name: 'Buchung bearbeiten' });
    fireEvent.change(within(oldForm).getByLabelText('Buchungstext'), { target: { value: 'Alter Auftrag' } });
    fireEvent.click(within(oldForm).getByRole('button', { name: 'Speichern' }));
    expect(api.put).toHaveBeenCalledWith('/bookings/target', expect.objectContaining({
      payment_text: 'Alter Auftrag', updated_at: target.updated_at,
    }));
    fireEvent.click(within(oldForm).getByRole('button', { name: 'Abbrechen' }));
    fireEvent.click(within(selected()).getByRole('button', { name: 'Bearbeiten' }));
    const newForm = screen.getByRole('dialog', { name: 'Buchung bearbeiten' });
    fireEvent.change(within(newForm).getByLabelText('Buchungstext'), { target: { value: 'Neuer ungespeicherter Entwurf' } });
    await act(async () => { pending.resolve(target); });
    expect(screen.getByRole('dialog', { name: 'Buchung bearbeiten' })).toBeInTheDocument();
    expect(within(newForm).getByLabelText('Buchungstext')).toHaveValue('Neuer ungespeicherter Entwurf');
  });

  it('does not describe an assigned category as unassigned when its lookup is unavailable', async () => {
    mount();
    await screen.findByText('Miete September');
    const category = within(selected()).getByText('Kategorie').closest('div');
    expect(category).not.toHaveTextContent('Noch nicht zugeordnet');
    expect(category).toHaveTextContent('cat-assigned');
  });

  it('still creates a new booking through the existing form after introducing edit sessions', async () => {
    api.post.mockResolvedValue({ ...target, id: 'new-booking' });
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Neu' }));
    const form = screen.getByRole('dialog', { name: 'Buchung erstellen' });
    fireEvent.change(within(form).getByLabelText('Konto *'), { target: { value: 'a1' } });
    fireEvent.change(within(form).getByLabelText('Buchungsdatum *'), { target: { value: '2026-10-07' } });
    fireEvent.change(within(form).getByLabelText('Betrag (€) *'), { target: { value: '100' } });
    fireEvent.change(within(form).getByLabelText('Buchungstext'), { target: { value: 'Neue Buchung' } });
    await act(async () => { fireEvent.click(within(form).getByRole('button', { name: 'Speichern' })); });
    expect(api.post).toHaveBeenCalledWith('/bookings', expect.objectContaining({
      account_id: 'a1', booking_date: '2026-10-07', amount: 100, payment_text: 'Neue Buchung',
    }));
    expect(api.put).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps reopened split draft separate from an older failed request and prevents duplicate submission', async () => {
    const pending = deferred();
    api.put.mockReturnValue(pending.promise);
    mount();
    await screen.findByText('Miete September');
    fireEvent.click(within(selected()).getByRole('button', { name: 'Aufteilen' }));
    const oldForm = screen.getByRole('dialog', { name: 'Zahlung aufteilen' });
    fireEvent.change(within(oldForm).getByLabelText('Vertrag MV-1 (€)'), { target: { value: '300' } });
    fireEvent.click(within(oldForm).getByRole('button', { name: 'Speichern' }));
    fireEvent.click(within(oldForm).getByRole('button', { name: 'Speichert …' }));
    expect(api.put).toHaveBeenCalledTimes(1);
    fireEvent.click(within(oldForm).getByRole('button', { name: 'Abbrechen' }));
    fireEvent.click(within(selected()).getByRole('button', { name: 'Aufteilen' }));
    const newForm = screen.getByRole('dialog', { name: 'Zahlung aufteilen' });
    fireEvent.change(within(newForm).getByLabelText('Vertrag MV-1 (€)'), { target: { value: '111' } });
    await act(async () => { pending.reject(new Error('Alter fehlgeschlagener Auftrag')); });
    expect(within(newForm).queryByRole('alert')).not.toBeInTheDocument();
    expect(within(newForm).getByLabelText('Vertrag MV-1 (€)')).toHaveValue(111);
    expect(within(newForm).getByRole('button', { name: 'Speichern' })).toBeEnabled();
  });

  it.each(['loading', 'error'])('blocks split while contracts are %s', async state => {
    context.contractsLoading = state === 'loading';
    context.contractsError = state === 'error' ? new Error('Verträge offline') : null;
    mount();
    await screen.findByText('Miete September');
    expect(within(selected()).queryByRole('button', { name: 'Aufteilen' })).not.toBeInTheDocument();
    expect(api.put).not.toHaveBeenCalled();
  });

  it('offers no write action for a reader even with a tenant and loaded contracts', async () => {
    context.canWrite = false;
    api.list.mockResolvedValue([target]);
    mount();
    await within(await screen.findByRole('region', { name: 'Ausgewählte Buchung' })).findByText('Miete September');
    expect(screen.queryByRole('button', { name: /Bearbeiten|Aufteilen|Löschen/ })).not.toBeInTheDocument();
    expect(api.put).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
    expect(api.del).not.toHaveBeenCalled();
  });
});
