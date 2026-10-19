import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import FormModal from '../components/FormModal';
import { deriveAmounts } from '../utils/invoiceAmounts';

afterEach(() => cleanup());

describe('invoice amounts', () => {
  it('derive VAT and gross in cents, half up, until one of them is set by hand', () => {
    expect(deriveAmounts({ net_amount: '123.45', vat_rate: '19' }, 'net_amount', new Set()))
      .toEqual({ vat_amount: '23.46', gross_amount: '146.91' });
    expect(deriveAmounts({ net_amount: '1234.5', vat_rate: 19 }, 'vat_rate', new Set()))
      .toEqual({ vat_amount: '234.56', gross_amount: '1469.06' });
    expect(deriveAmounts({ net_amount: '100', vat_rate: '7' }, 'net_amount', new Set())).toEqual({ vat_amount: '7.00', gross_amount: '107.00' });
    expect(deriveAmounts({ net_amount: '100', vat_rate: '19' }, 'net_amount', new Set(['gross_amount']))).toEqual({});
    expect(deriveAmounts({ net_amount: '', vat_rate: '19' }, 'net_amount', new Set())).toEqual({});
    expect(deriveAmounts({ net_amount: '100', vat_rate: '19' }, 'supplier', new Set())).toEqual({});
  });

  it('the form fills them in and keeps a gross typed by hand', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const fields = [{ key: 'net_amount', label: 'Netto (€)', type: 'number', required: true },
      { key: 'vat_rate', label: 'MwSt-Satz (%)', type: 'select', default: 19, options: [{ value: 19, label: '19 %' }, { value: 7, label: '7 %' }] },
      { key: 'vat_amount', label: 'MwSt-Betrag (€)', type: 'number' },
      { key: 'gross_amount', label: 'Brutto (€)', type: 'number', required: true }];
    const { container } = render(<FormModal title="Rechnung" fields={fields} derive={deriveAmounts} onSave={onSave} onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText(/^Netto/), { target: { value: '200' } });
    expect(screen.getByLabelText(/^Brutto/)).toHaveValue(238);
    expect(screen.getByLabelText(/^MwSt-Betrag/)).toHaveValue(38);
    fireEvent.change(screen.getByLabelText(/^MwSt-Satz/), { target: { value: '7' } });
    expect(screen.getByLabelText(/^Brutto/)).toHaveValue(214);
    fireEvent.change(screen.getByLabelText(/^Brutto/), { target: { value: '215' } });
    fireEvent.change(screen.getByLabelText(/^Netto/), { target: { value: '300' } });
    expect(screen.getByLabelText(/^Brutto/)).toHaveValue(215);
    fireEvent.submit(container.querySelector('form'));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ net_amount: 300, gross_amount: 215 })));
  });
});
