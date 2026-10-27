import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { Payment } from '../features/invoiceReview/ReviewPanels';
import { PickerDialog } from '../features/maintenanceProject/ProjectUi';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => null }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE' }) }));

const booking = (id, free = 60) => ({ id, free, booking_date: '2026-10-01', amount: -100, payment_text: `Überweisung ${id}` });
const view = { invoice: { id: 'i1' }, kind: 'invoice', abilities: { pay: true }, payments: [],
  settlement: { payment_status: 'partially_paid', paid: 40, payable: 100, open: 60 } };
const show = () => render(<MemoryRouter><Payment view={view} onChanged={vi.fn()} /></MemoryRouter>);
beforeEach(() => { vi.resetAllMocks(); });
afterEach(cleanup);

describe('invoice payment lookup', () => {
  it('can find and link a payment beyond the first page, retaining the exact booking link', async () => {
    api.get.mockImplementation(path => Promise.resolve(path.includes('skip=25')
      ? { items: [booking('last')], has_more: false }
      : { items: Array.from({ length: 25 }, (_, i) => booking(`b${i}`)), has_more: true }));
    api.post.mockResolvedValue({});
    show();
    fireEvent.click(screen.getByRole('button', { name: 'Zahlung zuordnen' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Weitere laden' }));
    const last = (await screen.findByText('Überweisung last')).closest('li');
    fireEvent.click(within(last).getByRole('button', { name: 'Auswählen' }));
    expect(screen.getByRole('link', { name: /Überweisung last/ })).toHaveAttribute('href', '/bookings?booking_id=last');
    expect(screen.getByLabelText('Betrag')).toHaveValue(60);
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/invoices/i1/payments', { booking_id: 'last', amount: 60 }));
  });

  it('shows failed pages as retryable errors and keeps a chosen payment and amount', async () => {
    api.get.mockResolvedValueOnce({ items: [booking('selected')], has_more: false });
    show();
    fireEvent.click(screen.getByRole('button', { name: 'Zahlung zuordnen' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Auswählen' }));
    fireEvent.change(screen.getByLabelText('Betrag'), { target: { value: '12.34' } });
    api.get.mockRejectedValueOnce(new Error('Bankdaten vorübergehend nicht erreichbar'));
    fireEvent.click(screen.getByRole('button', { name: 'Zahlung zuordnen' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Bankdaten vorübergehend nicht erreichbar');
    expect(screen.queryByText('Nichts gefunden.')).not.toBeInTheDocument();
    api.get.mockResolvedValueOnce({ items: [booking('other')], has_more: false });
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByText('Überweisung other')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(screen.getByLabelText('Betrag')).toHaveValue(12.34);
    expect(screen.getByRole('link', { name: /Überweisung selected/ })).toBeInTheDocument();
  });

  it('ignores an obsolete search response, including transports that do not honor abort', async () => {
    let old;
    const load = vi.fn().mockImplementation(({ q }) => q
      ? Promise.resolve({ items: [booking('new')], has_more: false })
      : new Promise(resolve => { old = resolve; }));
    render(<PickerDialog title="Buchung wählen" load={load} renderItem={row => row.payment_text} onPick={vi.fn()} onClose={vi.fn()} />);
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'neue Suche' } });
    fireEvent.submit(screen.getByRole('search'));
    expect(await screen.findByText('Überweisung new')).toBeInTheDocument();
    await act(async () => old({ items: [booking('old')], has_more: true }));
    expect(screen.queryByText('Überweisung old')).not.toBeInTheDocument();
    expect(screen.getByText('Überweisung new')).toBeInTheDocument();
  });
});
