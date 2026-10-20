import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SepaDebitDialog from '../features/sepaDebit/SepaDebitDialog';
import { nextMonth, preselected, totalOf } from '../features/sepaDebit/sepaDebitApi';

vi.mock('../api', () => ({ api: {} }));

const line = (number, extra = {}) => ({ contract_id: `c${number}`, contract_number: `MV-${number}`, tenant_name: `Mieter ${number}`,
  account_holder: `Mieter ${number}`, property_name: 'Bautzner Straße 61', unit_label: `Whg ${number}`, iban: 'DE02 … 2051',
  mandate_reference: `MR-${number}`, mandate_date: '2021-04-20', receivables: [{ id: `r${number}`, description: 'Miete', open: '812.40', earlier: [] }],
  amount: '812.40', problems: [], repeated: false, ready: true, ...extra });
const preview = {
  account: { id: 'a1', name: 'Mietkonto' }, month: '2026-11', collection_date: '2026-11-02', collection_date_problem: null,
  creditor: { revision: 0, creditor_id: '', creditor_name: '', suggested_name: 'Linda Reiser' },
  lines: [line(1), line(2, { problems: ['IBAN fehlt.'], ready: false, iban: '' }),
    line(3, { repeated: true, receivables: [{ id: 'r3', description: 'Miete', open: '500.00', earlier: [{ message_id: 'IMMO-1', created_at: '2026-10-01T09:00:00' }] }], amount: '500.00' })],
  files: [{ message_id: 'IMMO-1', created_at: '2026-10-01T09:00:00', month: '2026-10', count: 2, total: '1312.40', collection_date: '2026-10-02' }],
};
const makeService = () => ({
  accounts: vi.fn().mockResolvedValue([{ id: 'a1', name: 'Mietkonto', iban: 'DE89370400440532013000' }, { id: 'a2', name: 'Kasse', iban: null }]),
  preview: vi.fn().mockResolvedValue(preview),
  create: vi.fn(),
});

beforeEach(() => {
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:sepa');
  globalThis.URL.revokeObjectURL = vi.fn();
});
afterEach(cleanup);

describe('SEPA direct debit file', () => {
  it('suggests the next month and preselects only ready contracts not written before', () => {
    expect(nextMonth(new Date(2026, 11, 15))).toBe('2027-01');
    const chosen = preselected(preview.lines);
    expect([...chosen]).toEqual(['c1']);
    expect(totalOf(preview.lines, new Set(['c1', 'c3']))).toBe(1312.4);
  });

  it('shows what keeps a contract out, asks before repeating, and writes the file once per request', async () => {
    const service = makeService();
    service.create.mockRejectedValueOnce(new Error('Netzwerkfehler')).mockResolvedValue({
      message_id: 'IMMO-2', filename: 'SEPA-Lastschriften_2026-11_2026-11-02.xml', xml: '<Document/>', count: 2, total: '1312.40',
      collection_date: '2026-11-02' });
    render(<SepaDebitDialog onClose={vi.fn()} service={service} />);
    const table = await screen.findByRole('region', { name: 'Lastschriften des Monats' });
    expect(service.preview).toHaveBeenCalledWith(expect.objectContaining({ account_id: 'a1' }), expect.anything());
    expect(screen.getByRole('combobox')).toHaveTextContent('Mietkonto');            // only accounts with an IBAN
    expect(screen.getByLabelText('Zahlungsempfänger')).toHaveValue('Linda Reiser');
    expect(within(table).getByLabelText('MV-1 aufnehmen')).toBeChecked();
    expect(within(table).getByLabelText('MV-2 aufnehmen')).toBeDisabled();
    expect(table).toHaveTextContent('IBAN fehlt.');
    expect(within(table).getByLabelText('MV-3 aufnehmen')).not.toBeChecked();
    expect(table).toHaveTextContent('Schon in einer Datei vom');
    fireEvent.change(screen.getByLabelText('Gläubiger-ID'), { target: { value: 'DE98ZZZ09999999999' } });
    fireEvent.click(within(table).getByLabelText('MV-3 aufnehmen'));
    expect(screen.getAllByRole('status').some(element => element.textContent.startsWith('2 Lastschriften ·'))).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Datei erstellen' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('erneute Aufnahme');
    expect(service.create).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText(/Ich habe geprüft, dass die Bank MV-3/));
    fireEvent.click(screen.getByRole('button', { name: 'Datei erstellen' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Netzwerkfehler');
    fireEvent.click(screen.getByRole('button', { name: 'Datei erstellen' }));
    expect(await screen.findByText(/wurde gespeichert/)).toBeInTheDocument();
    const [first, second] = service.create.mock.calls.map(([body]) => body);
    expect(first.idempotency_key).toBe(second.idempotency_key);                       // a retry is the same request
    expect(second).toMatchObject({ account_id: 'a1', month: nextMonth(), collection_date: '2026-11-02',
      creditor_id: 'DE98ZZZ09999999999', creditor_name: 'Linda Reiser', contract_ids: ['c1', 'c3'], allow_repeat: true });
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('status')).toHaveTextContent('Nichts wurde an die Bank gesendet');
  });

  it('explains a missing bank account', async () => {
    const service = makeService();
    service.accounts.mockResolvedValue([{ id: 'a2', name: 'Kasse', iban: null }]);
    render(<SepaDebitDialog onClose={vi.fn()} service={service} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('kein Konto mit IBAN');
    await waitFor(() => expect(service.preview).not.toHaveBeenCalled());
  });
});
