import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import RentOverview from '../pages/RentOverview';
import { api } from '../api';

const context = vi.hoisted(() => ({
  canWrite: true, user: { id: 'staff-1' }, store: { invalidateRelated: vi.fn() },
}));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => context.canWrite, useAuth: () => ({ user: context.user }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => context.store }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({ PartyLink: ({ children }) => <span>{children}</span> }));

const row = { id: 'c1:2026-10', contract_id: 'c1', contract_revision: 'rev-1', contract_number: 'MV-1',
  tenant_id: 't1', tenant_name: 'Mia Mieterin', unit_label: 'Wohnung 1', property_id: 'p1', property_name: 'Haus A',
  portfolio_id: 'north', month: '2026-10', expected: 600, paid: 200.1, outstanding: 399.9, contract_credit: 0, status: 'partial' };
const data = { month: '2026-10', as_of: '2026-10-13', rows: [row], totals: { expected: 600, paid: 200.1, outstanding: 399.9, contract_credit: 0 } };
const storageKey = 'immo:pending-rent-payment:staff-1';
const mount = () => render(<MemoryRouter><RentOverview /></MemoryRouter>);
const successful = () => ({ contract_id: 'c1', booking: { id: 'b1', amount: 123.45, booking_date: '2026-01-08' }, replayed: false });
const open = async () => {
  fireEvent.click(await screen.findByRole('button', { name: 'Eingang buchen' }));
  return screen.getByRole('dialog', { name: 'Zahlung zum Vertrag erfassen' });
};
const fill = dialog => {
  fireEvent.change(within(dialog).getByLabelText('Zahlungskonto'), { target: { value: 'a1' } });
  fireEvent.change(within(dialog).getByLabelText('Zahlungsbetrag (€)'), { target: { value: '123.45' } });
  fireEvent.change(within(dialog).getByLabelText('Tatsächlicher Zahlungseingang'), { target: { value: '2026-01-08' } });
  fireEvent.change(within(dialog).getByLabelText('Buchungstext / Bemerkung'), { target: { value: 'Teilzahlung per Überweisung' } });
};

beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
  context.canWrite = true;
  context.user = { id: 'staff-1' };
  api.get.mockResolvedValue(data);
  api.list.mockImplementation(path => Promise.resolve(path === '/accounts'
    ? [{ id: 'a1', portfolio_id: 'north', name: 'Mietkonto' }, { id: 'a2', portfolio_id: 'south', name: 'Fremdes Konto' }]
    : [{ id: 'p1', name: 'Haus A' }]));
  api.post.mockResolvedValue(successful());
});
afterEach(cleanup);

describe('actual contract payments', () => {
  it('requires an account, preserves date/note, links actual booking and never patches payment status', async () => {
    mount();
    const dialog = await open();
    expect(within(dialog).getByLabelText('Zahlungskonto')).toHaveValue('');
    expect(within(dialog).queryByRole('option', { name: 'Fremdes Konto' })).not.toBeInTheDocument();
    fill(dialog);
    fireEvent.click(within(dialog).getByRole('button', { name: /als Eingang buchen/ }));
    await screen.findByRole('link', { name: 'Buchung ansehen' });
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith('/rent-charges/contract-payment', expect.objectContaining({
      contract_id: 'c1', contract_revision: 'rev-1', account_id: 'a1', amount: '123.45', booking_date: '2026-01-08',
      payment_text: 'Teilzahlung per Überweisung', idempotency_key: expect.any(String),
    }));
    expect(api.patch).not.toHaveBeenCalled();
    expect(screen.getByRole('link', { name: 'Buchung ansehen' })).toHaveAttribute('href', '/bookings?booking_id=b1');
    expect(sessionStorage.getItem(storageKey)).toBeNull();
  });

  it('resumes the same immutable command after a lost response and page reload', async () => {
    api.post.mockRejectedValueOnce(new Error('Verbindung unterbrochen'));
    const view = mount();
    const dialog = await open();
    fill(dialog);
    fireEvent.click(within(dialog).getByRole('button', { name: /als Eingang buchen/ }));
    await within(dialog).findByRole('alert');
    const firstRequest = api.post.mock.calls[0][1];
    expect(within(dialog).getByLabelText('Zahlungsbetrag (€)')).toBeDisabled();
    expect(JSON.parse(sessionStorage.getItem(storageKey)).request).toEqual(firstRequest);
    view.unmount();
    api.post.mockResolvedValue({ ...successful(), replayed: true });
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Buchung fortsetzen' }));
    const recovered = screen.getByRole('dialog');
    expect(within(recovered).getByLabelText('Tatsächlicher Zahlungseingang')).toHaveValue('2026-01-08');
    fireEvent.click(within(recovered).getByRole('button', { name: 'Buchung prüfen' }));
    await screen.findByRole('link', { name: 'Buchung ansehen' });
    expect(api.post.mock.calls[1][1]).toEqual(firstRequest);
    expect(sessionStorage.getItem(storageKey)).toBeNull();
  });

  it('confirmed stale-contract rejection lets the user reload and start a fresh command', async () => {
    api.post.mockRejectedValueOnce(Object.assign(new Error('Es wurde nichts gebucht. Vertrag geändert.'),
      { statusCode: 409, code: 'RENT_PAYMENT_NOT_CREATED' }));
    mount();
    const dialog = await open();
    fill(dialog);
    fireEvent.click(within(dialog).getByRole('button', { name: /als Eingang buchen/ }));
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Mietübersicht neu laden' }));
    expect(sessionStorage.getItem(storageKey)).toBeNull();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await screen.findByRole('button', { name: 'Eingang buchen' });
  });

  it.each(['success', 'rejection'])('an old unmounted request %s cannot clear a newer pending command', async outcome => {
    let resolveOld;
    let rejectOld;
    api.post.mockImplementationOnce(() => new Promise((resolve, reject) => { resolveOld = resolve; rejectOld = reject; }));
    const previous = mount();
    const dialog = await open();
    fill(dialog);
    fireEvent.click(within(dialog).getByRole('button', { name: /als Eingang buchen/ }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    const oldCommand = JSON.parse(sessionStorage.getItem(storageKey));
    previous.unmount();
    const newer = { ...oldCommand, request: { ...oldCommand.request, idempotency_key: 'newer-command', amount: '456.78' } };
    sessionStorage.setItem(storageKey, JSON.stringify(newer));
    mount();
    await screen.findByRole('button', { name: 'Buchung fortsetzen' });
    await act(async () => {
      if (outcome === 'success') resolveOld(successful());
      else rejectOld(Object.assign(new Error('Nicht gebucht'), { statusCode: 404, code: 'RENT_PAYMENT_NOT_CREATED' }));
    });
    expect(JSON.parse(sessionStorage.getItem(storageKey))).toEqual(newer);
    expect(screen.queryByRole('link', { name: 'Buchung ansehen' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Buchung fortsetzen' }));
    expect(within(screen.getByRole('dialog')).getByLabelText('Zahlungsbetrag (€)')).toHaveValue(456.78);
  });

  it('clears a confirmed missing parent rejection so a fresh payment can be entered', async () => {
    api.post.mockRejectedValueOnce(Object.assign(new Error('Es wurde nichts gebucht: Zahlungskonto fehlt.'),
      { statusCode: 404, code: 'RENT_PAYMENT_NOT_CREATED' }));
    mount();
    const dialog = await open();
    fill(dialog);
    fireEvent.click(within(dialog).getByRole('button', { name: /als Eingang buchen/ }));
    await within(dialog).findByRole('alert');
    expect(sessionStorage.getItem(storageKey)).toBeNull();
    expect(within(dialog).getByLabelText('Zahlungsbetrag (€)')).not.toBeDisabled();
  });

  it('only removes the exact persisted command confirmed by its response', async () => {
    let resolve;
    api.post.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    mount();
    const dialog = await open();
    fill(dialog);
    fireEvent.click(within(dialog).getByRole('button', { name: /als Eingang buchen/ }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    const original = JSON.parse(sessionStorage.getItem(storageKey));
    const newer = { ...original, request: { ...original.request, idempotency_key: 'new-command' } };
    sessionStorage.setItem(storageKey, JSON.stringify(newer));
    await act(async () => { resolve(successful()); });
    expect(JSON.parse(sessionStorage.getItem(storageKey))).toEqual(newer);
  });

  it('keeps pending commands isolated by signed-in account and hides writes for a reader', async () => {
    sessionStorage.setItem(storageKey, JSON.stringify({ row, request: { contract_id: 'c1', idempotency_key: 'pending-1' } }));
    context.user = { id: 'staff-2' };
    context.canWrite = false;
    mount();
    await screen.findByRole('link', { name: 'Mieterkonto' });
    expect(screen.queryByRole('button', { name: 'Buchung fortsetzen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Eingang buchen' })).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('does not show old totals after failed refresh or stale responses after filter changes', async () => {
    let resolveOld;
    api.get.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
      .mockResolvedValueOnce({ ...data, rows: [], totals: { expected: 0, paid: 0, outstanding: 0, contract_credit: 0 } });
    mount();
    fireEvent.change(screen.getByLabelText('Mietmonat'), { target: { value: '2026-01' } });
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    resolveOld(data);
    await waitFor(() => expect(screen.queryByText('Mia Mieterin')).not.toBeInTheDocument());
    api.get.mockRejectedValueOnce(new Error('Server nicht erreichbar'));
    fireEvent.click(screen.getByRole('button', { name: 'Aktualisieren' }));
    await screen.findByRole('alert');
    expect(screen.queryByText('Offen im Mietmonat')).not.toBeInTheDocument();
  });
});
