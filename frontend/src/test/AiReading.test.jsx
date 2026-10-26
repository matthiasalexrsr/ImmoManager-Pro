import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FormModal from '../components/FormModal';
import AiReadingPanel from '../features/aiReading/AiReadingPanel';
import { preferredReader, readingToForm } from '../features/aiReading/aiReadingApi';

afterEach(cleanup);

const fields = [{ key: 'supplier', label: 'Lieferant', required: true }, { key: 'gross_amount', label: 'Brutto', type: 'number' },
  { key: 'notes', label: 'Notiz' }];
const marks = { supplier: { value: 'Stadtwerke Leipzig GmbH', evidence: 'Stadtwerke Leipzig GmbH', confidence: 'high' },
  gross_amount: { value: '1070.00', evidence: 'Gesamtbetrag 1.070,00 EUR', confidence: 'low' } };
const initial = { supplier: 'Stadtwerke Leipzig GmbH', gross_amount: '1070.00' };

const options = {
  readers: [{ id: 'local', label: 'Lokale Regeln', available: true, ai: false }, { id: 'claude', label: 'Claude', available: true, ai: true },
    { id: 'codex', label: 'ChatGPT', available: false, ai: true }],
  default_reader: 'auto', ai_enabled: true, chat: true, confirm_mode: 'confirm',
  surfaces: [{ id: 'invoice', label: 'Rechnungseingang', may_use: true, ai_allowed: true, needs_ai: false,
    fields: [{ name: 'supplier', label: 'Lieferant', kind: 'text' }, { name: 'gross_amount', label: 'Brutto', kind: 'money' },
      { name: 'cost_category', label: 'Kostenart', kind: 'choice' }] }],
};
const reading = (extra = {}) => ({
  id: 'r1', revision: 1, surface: 'invoice', reader: 'claude', reader_label: 'Claude', status: 'open', chat: true,
  values: { supplier: { value: 'Stadtwerke Leipzig GmbH', evidence: 'Stadtwerke Leipzig GmbH', confidence: 'high', source: 'claude' },
    gross_amount: { value: '1070.00', evidence: 'Gesamtbetrag 1.070,00 EUR', confidence: 'low', source: 'claude' } },
  changed: ['supplier', 'gross_amount'], duplicates: [], decision: null, questions: ['Gehört die Rechnung zur Gohliser Straße 17?'],
  notes: [], dropped: [], messages: [{ id: 'm1', role: 'assistant', text: 'Rechnung der Stadtwerke.', changed: ['supplier'] }], ...extra,
});
const service = overrides => ({
  options: vi.fn().mockResolvedValue(options), start: vi.fn().mockResolvedValue(reading()),
  say: vi.fn(), decide: vi.fn(), finish: vi.fn().mockResolvedValue(reading({ status: 'cancelled' })), ...overrides,
});
const panel = (props, api) => render(<MemoryRouter><AiReadingPanel surface="invoice" source={{ fileUrl: '/uploads/documents/x.pdf', name: 'x.pdf' }}
  params={{ property_id: 'p' }} service={api} {...props} /></MemoryRouter>);

describe('Werte aus einem Dokument in der Maske', () => {
  it('lässt jeden KI-Wert bestätigen, bevor gespeichert wird', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { container } = render(<FormModal title="Beleg" fields={fields} initial={initial} onSave={onSave} onClose={() => {}}
      autosave={false} aiMarks={{ fields: marks, mode: 'confirm', document: 'Rechnung März', label: 'Claude' }} />);
    expect(screen.getByText('2 Werte von Claude')).toBeInTheDocument();
    expect(screen.getByText('2 noch zu bestätigen')).toBeInTheDocument();
    expect(screen.getByText(/Beleg: „Gesamtbetrag 1.070,00 EUR“/)).toBeInTheDocument();
    expect(screen.getByText(/unsicher – bitte genau prüfen/)).toBeInTheDocument();
    fireEvent.submit(container.querySelector('form'));
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toContain('prüfen und bestätigen: Lieferant, Brutto');
    fireEvent.click(screen.getByRole('button', { name: 'Lieferant: von der KI eingetragenen Wert bestätigen' }));
    fireEvent.change(screen.getByLabelText(/^Brutto/, { selector: 'input' }), { target: { value: '1000' } });     // changed by hand: no confirmation needed
    expect(within(screen.getByLabelText(/^Brutto/, { selector: 'input' }).closest('.form-group')).getByText('geändert')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Notiz/), { target: { value: 'Wasser 2025' } });
    expect(within(screen.getByLabelText(/^Notiz/).closest('.form-group')).getByText('neu')).toBeInTheDocument();
    fireEvent.submit(container.querySelector('form'));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ supplier: 'Stadtwerke Leipzig GmbH', gross_amount: 1000 })));
  });

  it('markiert im Modus „nur markieren“ ohne zu sperren', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { container } = render(<FormModal title="Beleg" fields={fields} initial={initial} onSave={onSave} onClose={() => {}}
      autosave={false} aiMarks={{ fields: marks, mode: 'mark' }} />);
    expect(within(screen.getByLabelText(/^Lieferant/, { selector: 'input' }).closest('.form-group')).getByText('KI')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /bestätigen/ })).toBeNull();
    fireEvent.submit(container.querySelector('form'));
    await waitFor(() => expect(onSave).toHaveBeenCalled());
  });

  it('übersetzt eine Lesung in Maskenwerte und wählt den Leser', () => {
    const { initial: values, marks: found } = readingToForm(reading({ values: { ...reading().values,
      unit: { value: { id: 'u1', label: 'EG links' }, source: 'claude' } } }), { supplier: 'supplier', unit_id: 'unit', gross: 'gross_amount', none: 'missing' });
    expect(values).toEqual({ supplier: 'Stadtwerke Leipzig GmbH', unit_id: 'u1', gross: '1070.00' });
    expect(found.gross).toEqual({ value: '1070.00', evidence: 'Gesamtbetrag 1.070,00 EUR', confidence: 'low', source: 'claude' });
    expect(preferredReader(options)).toBe('claude');
    expect(preferredReader({ ...options, default_reader: 'local' })).toBe('local');
    expect(preferredReader({ ...options, readers: options.readers.map(item => ({ ...item, available: !item.ai })) })).toBe('local');
    expect(preferredReader({ ...options, readers: options.readers.map(item => ({ ...item, available: !item.ai })) }, true)).toBe('');
  });
});

describe('Lesepanel', () => {
  it('liest mit dem gewählten Leser, zeigt Werte, Beleg und Rückfragen und übergibt an die Maske', async () => {
    const api = service();
    const onApply = vi.fn();
    panel({ onApply }, api);
    await screen.findByRole('radio', { name: /Claude/ });
    expect(screen.getByRole('radio', { name: /Claude/ })).toBeChecked();
    expect(screen.getByRole('radio', { name: /ChatGPT/ })).toBeDisabled();
    expect(screen.getByText(/wird zum Lesen an Claude/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Was soll mit dem Dokument geschehen/), { target: { value: 'Als Wasserkosten erfassen.' } });
    fireEvent.click(screen.getByRole('button', { name: /Einlesen/ }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith({ surface: 'invoice', document_id: null, file_url: '/uploads/documents/x.pdf',
      params: { property_id: 'p' }, reader: 'claude', instruction: 'Als Wasserkosten erfassen.' }));
    const table = await screen.findByRole('table');
    expect(within(table).getByText('1.070,00 €')).toBeInTheDocument();
    expect(within(table).getByText('„Gesamtbetrag 1.070,00 EUR“')).toBeInTheDocument();
    expect(within(table).getByText('unsicher')).toBeInTheDocument();
    expect(screen.getByText('Gehört die Rechnung zur Gohliser Straße 17?')).toBeInTheDocument();
    expect(screen.getByText('Geändert: Lieferant')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'In die Maske übernehmen' }));
    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({ id: 'r1' }));
  });

  it('fragt bei einem vorhandenen Eintrag nach, bevor übernommen wird', async () => {
    const existing = { kind: 'invoice', id: 'i1', title: 'Stadtwerke Leipzig GmbH vom 04.03.2026', href: '/invoice-review/i1',
      reason: 'same_amount_near_date', reason_label: 'gleicher Betrag des Lieferanten in Datumsnähe', details: '1.070,00 €', can_update: false };
    const api = service({ start: vi.fn().mockResolvedValue(reading({ duplicates: [existing] })),
      decide: vi.fn().mockResolvedValue(reading({ duplicates: [existing], decision: { action: 'use_existing' }, revision: 2 })) });
    const onOpenExisting = vi.fn();
    panel({ onApply: vi.fn(), onOpenExisting }, api);
    fireEvent.click(await screen.findByRole('button', { name: /Einlesen/ }));
    const question = await screen.findByRole('alertdialog');
    expect(within(question).getByText(/gibt es vermutlich schon einen Eintrag/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'In die Maske übernehmen' })).toBeDisabled();
    fireEvent.click(within(question).getByRole('button', { name: 'Öffnen' }));
    await waitFor(() => expect(api.decide).toHaveBeenCalledWith(expect.objectContaining({ id: 'r1' }), 'use_existing', existing));
    expect(onOpenExisting).toHaveBeenCalledWith(existing, expect.objectContaining({ revision: 2 }));
  });

  it('führt das Gespräch über das Dokument', async () => {
    const api = service({ say: vi.fn().mockResolvedValue(reading({ revision: 2, changed: ['gross_amount'],
      messages: [...reading().messages, { id: 'm2', role: 'user', text: 'Der Betrag ist netto.' },
        { id: 'm3', role: 'assistant', text: 'Ich habe Netto und Brutto getrennt.', changed: ['gross_amount'] }] })) });
    panel({ onApply: vi.fn() }, api);
    fireEvent.click(await screen.findByRole('button', { name: /Einlesen/ }));
    const box = await screen.findByLabelText('Nachricht an Claude');
    fireEvent.change(box, { target: { value: 'Der Betrag ist netto.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Senden' }));
    await waitFor(() => expect(api.say).toHaveBeenCalledWith(expect.objectContaining({ id: 'r1', revision: 1 }), 'Der Betrag ist netto.', expect.any(String)));
    const chat = screen.getByRole('list', { name: 'Gespräch zum Dokument' });
    expect(await within(chat).findByText('Ich habe Netto und Brutto getrennt.')).toBeInTheDocument();
    expect(within(chat).getByText('Geändert: Brutto')).toBeInTheDocument();
    expect(box).toHaveValue('');
  });
});
