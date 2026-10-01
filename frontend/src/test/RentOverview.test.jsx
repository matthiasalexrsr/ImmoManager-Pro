import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import RentOverview from '../pages/RentOverview';

const mocks = vi.hoisted(() => ({ getAll: vi.fn(), get: vi.fn(), post: vi.fn(), readonly: false }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isReadonly: mocks.readonly }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: key => key.split('.').at(-1) }) }));

const lists = {
  '/rent-charges': [{ id: 'charge', contract_id: 'contract', month: '2026-09', cold_rent: 100, amount_paid: 0, status: 'open' }],
  '/receivables': [{ id: 'receivable', contract_id: 'contract', due_date: '2026-09-03', amount_due: 100, amount_paid: 20, status: 'partial' }],
  '/contracts': [{ id: 'contract', contract_number: 'V-1', tenant_id: 'tenant', unit_id: 'unit' }],
  '/tenants': [{ id: 'tenant', full_name: 'Max Mustermann' }],
  '/units': [{ id: 'unit', label: 'WE1' }],
};

describe('RentOverview payment workflow', () => {
  beforeEach(() => {
    mocks.readonly = false;
    mocks.getAll.mockReset().mockImplementation(async path => structuredClone(lists[path]));
    mocks.post.mockReset().mockResolvedValue({ id: 'receipt' });
    mocks.get.mockReset().mockResolvedValue([]);
  });

  it('shows totals for the selected ledger without double-counting the other tab', async () => {
    const { container } = render(<RentOverview />);
    await screen.findByText('Max Mustermann');
    expect(container.querySelector('.rent-summary')).toHaveTextContent('100,00');
    expect(container.querySelector('.rent-summary')).not.toHaveTextContent('200,00');
    fireEvent.click(screen.getByRole('tab', { name: /receivables/ }));
    expect(container.querySelector('.rent-summary')).toHaveTextContent('80,00');
    expect(container.querySelector('.rent-summary')).toHaveTextContent('20,00');
  });

  it('submits amount, date and note with a stable retry reference', async () => {
    render(<RentOverview />);
    await screen.findByText('Max Mustermann');
    fireEvent.click(screen.getByRole('tab', { name: /receivables/ }));
    fireEvent.click(screen.getByRole('button', { name: 'recordPayment' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/paymentAmount/), { target: { value: '30' } });
    fireEvent.change(within(dialog).getByLabelText(/paymentDate/), { target: { value: '2026-09-20' } });
    fireEvent.change(within(dialog).getByLabelText('note'), { target: { value: 'Überweisung' } });
    mocks.post.mockRejectedValueOnce(new Error('Verbindung unterbrochen'));
    fireEvent.click(within(dialog).getByRole('button', { name: 'save' }));
    await within(dialog).findByText('Verbindung unterbrochen');
    const first = mocks.post.mock.calls[0];
    expect(first[0]).toBe('/receivables/receivable/payments');
    expect(first[1]).toMatchObject({ amount: 30, payment_date: '2026-09-20', note: 'Überweisung' });
    expect(first[1].idempotency_key).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'save' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[1][1].idempotency_key).toBe(first[1].idempotency_key);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByText('paymentSaved')).toBeInTheDocument();
  });

  it('shows data load errors and allows a fresh attempt', async () => {
    mocks.getAll.mockRejectedValueOnce(new Error('Server nicht erreichbar'));
    render(<RentOverview />);
    await screen.findByRole('alert');
    expect(screen.getByRole('alert')).toHaveTextContent('Server nicht erreichbar');
    expect(screen.queryByText('Max Mustermann')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'retry' }));
    await screen.findByText('Max Mustermann');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('allows readonly users to inspect history without payment controls', async () => {
    mocks.readonly = true;
    mocks.get.mockResolvedValue([{ id: 'receipt', payment_date: '2026-09-05', amount: '40.10', note: 'Teilzahlung' }]);
    render(<RentOverview />);
    await screen.findByText('Max Mustermann');
    expect(screen.queryByRole('button', { name: 'recordPayment' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'history' }));
    await screen.findByText('Teilzahlung');
    expect(mocks.get).toHaveBeenCalledWith('/rent-charges/charge/payments');
  });
});
