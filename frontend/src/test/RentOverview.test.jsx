import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render as renderComponent, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import RentOverview from '../pages/RentOverview';

const render = component => renderComponent(<MemoryRouter>{component}</MemoryRouter>);

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
  '/bookings': [
    { id: 'bank', booking_date: '2026-09-18', amount: 120, allocated_amount: 40, tenant_id: 'tenant', unit_id: 'unit', payment_text: 'Miete September' },
    { id: 'foreign', booking_date: '2026-09-18', amount: 50, tenant_id: 'other', payment_text: 'Anderer Mieter' },
    { id: 'expense', booking_date: '2026-09-18', amount: -20, payment_text: 'Ausgabe' },
    { id: 'exhausted', booking_date: '2026-09-18', amount: 50, allocated_amount: 50, payment_text: 'Bereits zugeordnet' },
  ],
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
    expect(screen.queryByRole('button', { name: 'allocateBooking' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'history' }));
    await screen.findByText('Teilzahlung');
    expect(mocks.get).toHaveBeenCalledWith('/rent-charges/charge/payments');
    expect(screen.queryByRole('button', { name: 'reversePayment' })).not.toBeInTheDocument();
  });

  it('allocates a matching bank transaction using its available amount and date', async () => {
    render(<RentOverview />);
    await screen.findByText('Max Mustermann');
    fireEvent.click(screen.getByRole('button', { name: 'allocateBooking' }));
    const dialog = screen.getByRole('dialog');
    const select = await within(dialog).findByLabelText(/bankBooking/);
    expect(within(select).getByRole('option', { name: /80,00.*Miete September/ })).toBeInTheDocument();
    expect(within(select).queryByRole('option', { name: /Anderer Mieter|Ausgabe|Bereits zugeordnet/ })).not.toBeInTheDocument();
    fireEvent.change(select, { target: { value: 'bank' } });
    expect(within(dialog).getByLabelText(/paymentAmount/)).toHaveValue(80);
    expect(within(dialog).getByLabelText(/paymentAmount/)).toHaveAttribute('max', '80');
    expect(within(dialog).getByLabelText(/paymentDate/)).toHaveValue('2026-09-18');
    fireEvent.click(within(dialog).getByRole('button', { name: 'save' }));
    await screen.findByText('allocationSaved');
    expect(mocks.post).toHaveBeenCalledWith('/rent-charges/charge/payments', expect.objectContaining({
      booking_id: 'bank', amount: 80, payment_date: '2026-09-18', idempotency_key: expect.any(String),
    }));
  });

  it('keeps bank lookup failures visible and retries without submitting an empty payment', async () => {
    let failed = false;
    mocks.getAll.mockImplementation(async path => {
      if (path === '/bookings' && !failed) { failed = true; throw new Error('Bankliste nicht erreichbar'); }
      return structuredClone(lists[path]);
    });
    render(<RentOverview />);
    await screen.findByText('Max Mustermann');
    fireEvent.click(screen.getByRole('button', { name: 'allocateBooking' }));
    const dialog = screen.getByRole('dialog');
    await within(dialog).findByText('Bankliste nicht erreichbar');
    expect(within(dialog).getByRole('button', { name: 'save' })).toBeDisabled();
    expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'retry' }));
    await within(dialog).findByLabelText(/bankBooking/);
    expect(within(dialog).queryByRole('alert')).not.toBeInTheDocument();
  });

  it('records a reversal with a reason and preserves its reference on retry', async () => {
    const receipt = { id: 'receipt', amount: '40.10', payment_date: '2026-09-05', note: 'Teilzahlung' };
    mocks.get.mockResolvedValueOnce([receipt]).mockResolvedValueOnce([
      { ...receipt, reversal: { reversal_date: '2026-09-25', reason: 'Falsche Zuordnung' } },
    ]);
    render(<RentOverview />);
    await screen.findByText('Max Mustermann');
    fireEvent.click(screen.getByRole('button', { name: 'history' }));
    fireEvent.click(await screen.findByRole('button', { name: 'reversePayment' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/reversalDate/), { target: { value: '2026-09-25' } });
    fireEvent.change(within(dialog).getByLabelText(/reversalReason/), { target: { value: '  Falsche Zuordnung  ' } });
    mocks.post.mockRejectedValueOnce(new Error('Zeitüberschreitung'));
    fireEvent.click(within(dialog).getByRole('button', { name: 'save' }));
    await within(dialog).findByText('Zeitüberschreitung');
    const first = mocks.post.mock.calls[0];
    expect(first).toEqual(['/rent-charges/charge/payments/receipt/reversal', expect.objectContaining({
      reversal_date: '2026-09-25', reason: 'Falsche Zuordnung', idempotency_key: expect.any(String),
    })]);
    expect(within(dialog).getByLabelText(/reversalReason/)).toHaveValue('  Falsche Zuordnung  ');
    fireEvent.click(within(dialog).getByRole('button', { name: 'save' }));
    await screen.findByText('reversalSaved');
    expect(mocks.post.mock.calls[1][1].idempotency_key).toBe(first[1].idempotency_key);
    await screen.findByText(/reversed.*2026-09-25.*Falsche Zuordnung/);
    expect(screen.queryByRole('button', { name: 'reversePayment' })).not.toBeInTheDocument();
  });

  it('requires a nonblank reversal reason before sending the request', async () => {
    mocks.get.mockResolvedValue([{ id: 'receipt', amount: '40.10', payment_date: '2026-09-05' }]);
    render(<RentOverview />);
    await screen.findByText('Max Mustermann');
    fireEvent.click(screen.getByRole('button', { name: 'history' }));
    fireEvent.click(await screen.findByRole('button', { name: 'reversePayment' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/reversalReason/), { target: { value: '   ' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'save' }));
    await within(dialog).findByText('reasonRequired');
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('ignores an older history response when the same panel has been reopened', async () => {
    let resolveOld;
    mocks.get.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
      .mockResolvedValueOnce([{ id: 'new', amount: '40', payment_date: '2026-09-05', note: 'Aktueller Stand' }]);
    render(<RentOverview />);
    await screen.findByText('Max Mustermann');
    fireEvent.click(screen.getByRole('button', { name: 'history' }));
    fireEvent.click(screen.getByRole('button', { name: 'close' }));
    fireEvent.click(screen.getByRole('button', { name: 'history' }));
    await screen.findByText('Aktueller Stand');
    resolveOld([{ id: 'old', amount: '20', payment_date: '2026-09-01', note: 'Alter Stand' }]);
    await waitFor(() => expect(screen.queryByText('Alter Stand')).not.toBeInTheDocument());
    expect(screen.getByText('Aktueller Stand')).toBeInTheDocument();
  });

  it('provides the rent-charge route and keyboard navigation between labelled ledger panels', async () => {
    render(<RentOverview />);
    await screen.findByText('Max Mustermann');
    expect(screen.getByRole('link', { name: 'manageCharges' })).toHaveAttribute('href', '/rent-charges');
    const charges = screen.getByRole('tab', { name: /charges/ });
    const receivables = screen.getByRole('tab', { name: /receivables/ });
    charges.focus();
    expect(charges).toHaveAttribute('tabindex', '0');
    expect(receivables).toHaveAttribute('tabindex', '-1');
    fireEvent.keyDown(charges, { key: 'ArrowRight' });
    expect(receivables).toHaveFocus();
    expect(receivables).toHaveAttribute('aria-selected', 'true');
    let panel = screen.getByRole('tabpanel', { name: /receivables/ });
    expect(panel.id).toBe(receivables.getAttribute('aria-controls'));
    expect(panel).toHaveAttribute('aria-labelledby', receivables.id);
    fireEvent.keyDown(receivables, { key: 'ArrowRight' });
    expect(charges).toHaveFocus();
    fireEvent.keyDown(charges, { key: 'End' });
    expect(receivables).toHaveFocus();
    fireEvent.keyDown(receivables, { key: 'Home' });
    expect(charges).toHaveFocus();
    fireEvent.keyDown(charges, { key: 'ArrowLeft' });
    expect(receivables).toHaveFocus();
    panel = screen.getByRole('tabpanel', { name: /receivables/ });
    expect(panel).toHaveAttribute('tabindex', '0');
  });

  it('focuses and scrolls history as it opens, keeps focus during loading, and returns it on close', async () => {
    let resolveHistory;
    mocks.get.mockImplementation(() => new Promise(resolve => { resolveHistory = resolve; }));
    const originalScroll = HTMLElement.prototype.scrollIntoView;
    const scroll = vi.fn();
    HTMLElement.prototype.scrollIntoView = scroll;
    try {
      render(<RentOverview />);
      await screen.findByText('Max Mustermann');
      const origin = screen.getByRole('button', { name: 'history' });
      fireEvent.click(origin);
      const history = screen.getByRole('region', { name: 'history' });
      expect(history).toHaveFocus();
      expect(history).toHaveAttribute('aria-busy', 'true');
      expect(within(history).getByRole('status')).toHaveTextContent('loading');
      expect(scroll).toHaveBeenCalledTimes(1);
      resolveHistory([{ id: 'receipt', amount: '40', payment_date: '2026-09-05', note: 'Loaded receipt' }]);
      await within(history).findByText('Loaded receipt');
      expect(history).toHaveFocus();
      expect(scroll).toHaveBeenCalledTimes(1);
      fireEvent.click(within(history).getByRole('button', { name: 'close' }));
      expect(screen.queryByRole('region', { name: 'history' })).not.toBeInTheDocument();
      expect(origin).toHaveFocus();
    } finally {
      if (originalScroll) HTMLElement.prototype.scrollIntoView = originalScroll;
      else delete HTMLElement.prototype.scrollIntoView;
    }
  });

  it('sorts string-valued receipt amounts numerically', async () => {
    mocks.get.mockResolvedValue([
      { id: 'large', amount: '100', payment_date: '2026-09-05', note: 'Large receipt' },
      { id: 'small', amount: '9', payment_date: '2026-09-06', note: 'Small receipt' },
    ]);
    render(<RentOverview />);
    await screen.findByText('Max Mustermann');
    fireEvent.click(screen.getByRole('button', { name: 'history' }));
    const history = screen.getByRole('region', { name: 'history' });
    await within(history).findByText('Large receipt');
    fireEvent.click(within(history).getByRole('columnheader', { name: 'paymentAmount' }));
    expect(within(history).getAllByRole('row')[1]).toHaveTextContent('Small receipt');
    expect(within(history).getAllByRole('row')[2]).toHaveTextContent('Large receipt');
  });

  it('retries a history failure in place and keeps its close action accessible', async () => {
    mocks.get.mockRejectedValueOnce(new Error('History unavailable')).mockResolvedValueOnce([
      { id: 'receipt', amount: '40', payment_date: '2026-09-05', note: 'Recovered history' },
    ]);
    render(<RentOverview />);
    await screen.findByText('Max Mustermann');
    fireEvent.click(screen.getByRole('button', { name: 'history' }));
    const history = screen.getByRole('region', { name: 'history' });
    await within(history).findByRole('alert');
    expect(within(history).getByRole('alert')).toHaveTextContent('History unavailable');
    fireEvent.click(within(history).getByRole('button', { name: 'retry' }));
    await within(history).findByText('Recovered history');
    expect(within(history).queryByRole('alert')).not.toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(within(history).getByRole('button', { name: 'close' })).toBeEnabled();
  });
});
