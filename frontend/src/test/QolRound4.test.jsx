import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import { duplicateOf } from '../utils/duplicate';
import { SEND_BATCH, sendAll } from '../features/aktenwerk/aktenwerkApi';

vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => null }));

beforeEach(() => { localStorage.clear(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

const columns = [
  { key: 'text', label: 'Text', filterType: 'text' },
  { key: 'amount', label: 'Betrag (€)', type: 'number', sum: true },
];
const rows = [
  { id: 'a', text: 'Miete A', amount: 0.1 },
  { id: 'b', text: 'Miete B', amount: '0.2' },
  { id: 'c', text: 'Reparatur', amount: -1000.55 },
  ...Array.from({ length: 30 }, (_, i) => ({ id: `m${i}`, text: `Miete ${i}`, amount: 100 })),
];
const totals = () => within(document.querySelector('tfoot')).getAllByRole('cell').map(cell => cell.textContent);

describe('totals', () => {
  it('sums every filtered row of a money column in exact cents, beyond the current page', () => {
    render(<DataTable title="Buchungen" columns={columns} data={rows} />);
    // 0.1 + 0.2 - 1000.55 + 30 * 100 over all 33 rows, though only 25 are shown
    expect(totals()[0]).toBe('Summe (33)');
    expect(totals()[1]).toMatch(/1\.999,75\s?€/);

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Miete' } });
    expect(totals()[0]).toBe('Summe (32)');
    expect(totals()[1]).toMatch(/3\.000,30\s?€/);
  });

  it('shows no totals without money columns or rows', () => {
    const { unmount } = render(<DataTable title="Notizen" columns={[{ key: 'text', label: 'Text' }]} data={rows} />);
    expect(document.querySelector('tfoot')).toBeNull();
    unmount();
    render(<DataTable title="Buchungen" columns={columns} data={[]} />);
    expect(document.querySelector('tfoot')).toBeNull();
  });

  it('shows the sum of the selected rows in the selection bar', () => {
    render(<DataTable title="Buchungen" columns={columns} data={rows} bulkActions={[{ key: 'x', label: 'X', run: vi.fn() }]} />);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Auswählen: Miete A' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Auswählen: Miete B' }));
    expect(screen.getByRole('region', { name: 'Auswahl' })).toHaveTextContent(/Betrag: 0,30\s?€/);
  });
});

describe('Heute in date fields', () => {
  it('fills the local calendar day, also shortly after midnight', () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date(2026, 9, 1, 0, 30));   // 1 Oct 2026, 00:30 local time
    render(<FormModal title="Buchung" fields={[{ key: 'booking_date', label: 'Datum', type: 'date' }]} initial={null}
      onSave={vi.fn()} onClose={vi.fn()} />);
    const today = screen.getByRole('button', { name: 'Heute eintragen' });
    expect(today).toHaveAttribute('aria-controls', screen.getByLabelText('Datum').id);
    fireEvent.click(today);
    expect(screen.getByLabelText('Datum')).toHaveValue('2026-10-01');
  });
});

describe('Duplizieren', () => {
  it('copies a record without what identifies the original', () => {
    const invoice = { id: 'i1', created_at: 'x', updated_at: 'y', supplier: 'Wärmemeister', invoice_number: 'R-17', status: 'paid', gross_amount: 119 };
    expect(duplicateOf(invoice, ['invoice_number', 'status'])).toEqual({ supplier: 'Wärmemeister', gross_amount: 119 });
    expect(invoice.id).toBe('i1');
  });

  it('saves a duplicate as a new record (no edit token, no id)', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const fields = [{ key: 'supplier', label: 'Lieferant' }, { key: 'invoice_number', label: 'Nr.' }];
    const { container } = render(<FormModal title="Rechnung erstellen" fields={fields}
      initial={duplicateOf({ id: 'i1', updated_at: '2026-10-01T10:00:00', supplier: 'Wärmemeister', invoice_number: 'R-17' }, ['invoice_number'])}
      onSave={onSave} onClose={vi.fn()} repeatKeep={[]} />);
    expect(screen.getByLabelText('Lieferant')).toHaveValue('Wärmemeister');
    expect(screen.getByLabelText('Nr.')).toHaveValue('');
    // a new record: "Speichern & weiteren" is offered, and the payload carries no edit token
    expect(screen.getByRole('button', { name: 'Speichern & weiteren' })).toBeInTheDocument();
    fireEvent.submit(container.querySelector('form'));
    await vi.waitFor(() => expect(onSave).toHaveBeenCalledWith({ supplier: 'Wärmemeister', invoice_number: null }));
  });
});

describe('Aktenwerk hand-over', () => {
  it('sends a large selection in batches the server accepts and reports one result', async () => {
    const ids = Array.from({ length: SEND_BATCH * 2 + 5 }, (_, i) => `immomanager:document:${i}`);
    const send = vi.fn(async batch => ({
      sent: batch.length - 1, failed: 1,
      results: batch.map((id, i) => ({ exchange_id: id, status: i === 0 ? 'failed' : 'sent' })),
    }));
    const outcome = await sendAll(ids, send);
    expect(send.mock.calls.map(([batch]) => batch.length)).toEqual([SEND_BATCH, SEND_BATCH, 5]);
    expect(send.mock.calls.flatMap(([batch]) => batch)).toEqual(ids);
    expect(outcome).toMatchObject({ sent: ids.length - 3, failed: 3, message: `${ids.length - 3} an Aktenwerk übergeben, 3 fehlgeschlagen` });
    expect(outcome.results).toHaveLength(ids.length);
  });

  it('says nothing was handed over when every document failed', async () => {
    const outcome = await sendAll(['immomanager:document:x'], async () => ({ sent: 0, failed: 1, results: [] }));
    expect(outcome.message).toBe('Nichts übergeben (1 fehlgeschlagen)');
  });
});
