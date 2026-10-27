import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import MeterDocumentImport from '../features/meterDocuments/MeterDocumentImport';
import { applyBody, editableRows, rowProblem, titleFrom } from '../features/meterDocuments/meterDocumentsApi';

afterEach(cleanup);

const proposal = {
  document: { id: 'doc', title: 'ista 2025' }, reader_label: 'Claude', company: 'ista', kind_label: 'Heizkostenabrechnung',
  period_start: '2025-01-01', period_end: '2025-12-31', reading_date: '2025-12-31', consumption_share: 70, total: 1200,
  notes: ['1 Gerätenummern gehören zu keinem Zähler dieser Immobilie (777).'],
  keys: [{ id: 'area', name: 'Wohnfläche', key_type: 'area_sqm' }, { id: 'heat', name: 'Heizung', key_type: 'consumption', meter_type: 'heating' }],
  meters: [{ id: 'm1', label: 'EG links · 1045', meter_type: 'heating' }],
  costs: [{ description: 'Fernwärme', amount: 1000, cost_category: 'heating', allocation_key_id: 'heat', consumption_share: 70, fixed_key_id: 'area', is_recoverable: true, reason: '70 % nach Verbrauch' },
    { description: 'Messdienst', amount: 200, cost_category: 'heating', allocation_key_id: 'heat', consumption_share: 70, fixed_key_id: 'area', is_recoverable: true }],
  readings: [{ serial: '1045', meter_id: 'm1', reading_date: '2025-12-31', value: 145, sure: true },
    { serial: '777', meter_id: null, reading_date: '2025-12-31', value: 12, sure: false }],
  unit_results: [{ label: 'NE 001', unit_label: 'EG links', amount: 512.3 }],
};

describe('Dokumente des Messdienstes', () => {
  it('prüft die Zeilen und baut die Übernahme nur aus den ausgewählten', () => {
    expect(titleFrom('ista_Abrechnung-2025.pdf')).toBe('ista Abrechnung 2025');
    const rows = editableRows(proposal, { withCosts: true });
    expect(rows.costs.map(row => row.checked)).toEqual([true, true]);
    expect(rows.readings.map(row => row.checked)).toEqual([true, false]);
    expect(rowProblem(rows, proposal.keys)).toBe('');
    expect(rowProblem({ ...rows, costs: [{ ...rows.costs[0], consumption_share: 80 }] }, proposal.keys)).toMatch(/zwischen 50 und 70/);
    expect(rowProblem({ ...rows, costs: [{ ...rows.costs[0], allocation_key_id: 'area' }] }, proposal.keys)).toMatch(/Verbrauchsschlüssel/);
    expect(rowProblem({ ...rows, readings: [{ ...rows.readings[1], checked: true }] }, proposal.keys)).toMatch(/Gerät 777: bitte einen Zähler/);
    const body = applyBody({ ...rows, costs: [rows.costs[0], { ...rows.costs[1], checked: false }] }, { propertyId: 'p', periodId: 'bp' });
    expect(body).toEqual({ property_id: 'p', billing_period_id: 'bp',
      costs: [{ description: 'Fernwärme', amount: 1000, cost_category: 'heating', allocation_key_id: 'heat', is_recoverable: true, consumption_share: 70, fixed_key_id: 'area' }],
      readings: [{ meter_id: 'm1', reading_date: '2025-12-31', value: 145 }] });
    expect(editableRows(proposal, { withCosts: false }).costs.every(row => !row.checked)).toBe(true);
  });

  const options = {
    readers: [{ id: 'local', label: 'Lokale Regeln', available: true, ai: false }, { id: 'claude', label: 'Claude', available: true, ai: true },
      { id: 'codex', label: 'ChatGPT', available: false, ai: true }],
    default_reader: 'auto', ai_enabled: true, chat: true, confirm_mode: 'confirm',
    surfaces: [{ id: 'meter_document', label: 'Dokument des Messdienstes', may_use: true, ai_allowed: true, needs_ai: false, fields: [] }],
  };
  const reading = extra => ({ id: 'rm', revision: 1, surface: 'meter_document', reader: 'claude', reader_label: 'Claude', status: 'open', chat: true,
    values: null, changed: [], duplicates: [], decision: null, questions: [], notes: [], dropped: [], proposal, messages: [
      { id: 'a1', role: 'assistant', text: 'Heizkostenabrechnung von ista für 2025.', changed: ['extraction'] }], ...extra });
  const services = start => ({
    service: { upload: vi.fn().mockResolvedValue({ id: 'doc' }),
      apply: vi.fn().mockResolvedValue({ cost_items: ['c1', 'c2'], readings_created: 1, readings_skipped: 0 }) },
    readingService: { options: vi.fn().mockResolvedValue(options), start: vi.fn().mockResolvedValue(start), say: vi.fn(), decide: vi.fn(),
      finish: vi.fn().mockResolvedValue({ ...start, status: 'taken_over' }) },
  });

  it('lädt hoch, lässt die verbundene KI mit Anweisung lesen und übernimmt die geprüften Zeilen', async () => {
    const { service, readingService } = services(reading());
    const onApplied = vi.fn();
    const { container } = render(<MemoryRouter><MeterDocumentImport propertyId="p" periodId="bp" service={service} readingService={readingService}
      onApplied={onApplied} /></MemoryRouter>);
    const file = new File(['%PDF-'], 'ista_2025.pdf', { type: 'application/pdf' });
    fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [file] } });
    await waitFor(() => expect(screen.getByRole('radio', { name: /Claude/ })).toBeChecked());
    expect(service.upload).toHaveBeenCalledWith(file, 'p');
    expect(screen.getByRole('radio', { name: /ChatGPT/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Was soll mit dem Dokument geschehen/), { target: { value: 'Nur die Heizkosten.' } });
    fireEvent.click(screen.getByRole('button', { name: /Einlesen/ }));
    await screen.findByText('Heizkostenabrechnung');
    expect(readingService.start).toHaveBeenCalledWith({ surface: 'meter_document', document_id: 'doc', file_url: null,
      params: { property_id: 'p', billing_period_id: 'bp' }, reader: 'claude', instruction: 'Nur die Heizkosten.' });
    expect(screen.getByText('Werte neu gelesen')).toBeInTheDocument();
    expect(screen.getByText(/gehören zu keinem Zähler/)).toBeInTheDocument();
    expect(screen.getByText('bitte prüfen')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Betrag Messdienst'), { target: { value: '210' } });
    fireEvent.click(screen.getByRole('button', { name: 'Übernehmen (2 Kosten, 1 Zählerstände)' }));
    await screen.findByText(/2 Kostenpositionen und 1 Zählerstände übernommen/);
    expect(service.apply.mock.calls[0][1].costs.map(cost => cost.amount)).toEqual([1000, 210]);
    expect(readingService.finish).toHaveBeenCalledWith(expect.objectContaining({ id: 'rm' }), 'taken_over', { kind: 'meter_document', id: 'doc' });
    expect(onApplied).toHaveBeenCalled();
  });

  it('übernimmt nichts, solange die Frage nach dem schon übernommenen Dokument offen ist', async () => {
    const earlier = { kind: 'meter_document', id: 'old', title: 'ista 2025 (Januar)', href: '/documents/old', reason: 'same_file',
      reason_label: 'dieselbe Datei', details: '', can_update: false };
    const { service, readingService } = services(reading({ duplicates: [earlier] }));
    readingService.options.mockResolvedValue({ ...options, readers: options.readers.map(item => ({ ...item, available: !item.ai })) });
    const { container } = render(<MemoryRouter><MeterDocumentImport propertyId="p" periodId="bp" service={service} readingService={readingService} /></MemoryRouter>);
    fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [new File(['%PDF-'], 'ista.pdf')] } });
    await screen.findByText('Heizkostenabrechnung');                        // the local rules read at once
    expect(readingService.start).toHaveBeenCalledWith(expect.objectContaining({ reader: 'local' }));
    expect(screen.getByRole('alertdialog')).toHaveTextContent('ista 2025 (Januar)');
    expect(screen.getByRole('button', { name: /^Übernehmen/ })).toBeDisabled();
    expect(service.apply).not.toHaveBeenCalled();
  });
});
