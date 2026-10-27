import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import InvoiceReview from '../pages/InvoiceReview';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(),
  upload: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => null }));

const options = surface => ({
  readers: [{ id: 'local', label: 'Lokale Regeln', available: true, ai: false }, { id: 'claude', label: 'Claude', available: true, ai: true }],
  default_reader: 'local', ai_enabled: true, chat: true, confirm_mode: 'confirm',
  surfaces: [{ id: surface, label: 'Rechnungseingang', may_use: true, ai_allowed: true, needs_ai: false,
    fields: [{ name: 'supplier', label: 'Lieferant', kind: 'text' }, { name: 'gross_amount', label: 'Brutto', kind: 'money' }] }],
});
const invoiceReading = { id: 'r9', revision: 1, surface: 'invoice', reader: 'local', reader_label: 'Lokale Regeln', status: 'open',
  chat: false, changed: [], duplicates: [], decision: null, questions: [], notes: [], dropped: [], messages: [], confirm_mode: 'confirm',
  file: { name: 'rechnung.pdf' },
  values: { supplier: { value: 'Stadtwerke Leipzig GmbH', evidence: 'Stadtwerke Leipzig GmbH', confidence: 'high', source: 'local' },
    invoice_number: { value: 'RE-2026-0042', evidence: 'Rechnungsnummer RE-2026-0042', confidence: 'high', source: 'local' },
    invoice_date: { value: '2026-03-04', evidence: '04.03.2026', confidence: 'high', source: 'local' },
    net_amount: { value: '1000.00', evidence: 'Netto 1.000,00', confidence: 'medium', source: 'local' },
    gross_amount: { value: '1190.00', evidence: 'Gesamtbetrag 1.190,00 EUR', confidence: 'medium', source: 'local' } } };

beforeEach(() => {
  vi.clearAllMocks();
  api.list.mockResolvedValue([{ id: 'p1', name: 'Nordhaus' }]);
  api.get.mockImplementation(path => {
    if (path.startsWith('/invoice-review/inbox')) return Promise.resolve({ items: [], total: 0, skip: 0, limit: 50, has_more: false });
    if (path.startsWith('/invoice-review/duplicates')) return Promise.resolve({ duplicates: [] });
    if (path.startsWith('/ai/readings/options')) return Promise.resolve(options('invoice'));
    if (path.startsWith('/auth/users/me/settings/draft-defaults')) return Promise.resolve({ values: {} });
    return Promise.reject(new Error(`unexpected ${path}`));
  });
  api.upload.mockResolvedValue({ file_url: '/uploads/documents/rechnung.pdf' });
  api.post.mockImplementation(path => Promise.resolve(path === '/ai/readings' ? invoiceReading
    : path === '/documents' ? { id: 'd7' } : path === '/invoice-review/receipts' ? { invoice: { id: 'i7' } } : {}));
});
afterEach(cleanup);
const field = (scope, name) => within(scope).getByLabelText(new RegExp(`^${name}`), { selector: 'input' });

describe('Beleg einlesen im Rechnungseingang', () => {
  it('liest den Beleg, lässt die Werte bestätigen und legt Rechnung und Beleg aus derselben Datei an', async () => {
    render(<MemoryRouter><InvoiceReview /></MemoryRouter>);
    const create = await screen.findByRole('button', { name: 'Rechnung erfassen' });
    await waitFor(() => expect(create).toBeEnabled());
    fireEvent.click(create);
    const dialog = await screen.findByRole('dialog', { name: 'Rechnung erfassen' });
    fireEvent.change(within(dialog).getByLabelText('Beleg'), { target: { files: [new File(['%PDF-1.4'], 'rechnung.pdf', { type: 'application/pdf' })] } });
    fireEvent.click(within(dialog).getByRole('button', { name: /Beleg einlesen/ }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/ai/readings', expect.objectContaining({
      surface: 'invoice', file_url: '/uploads/documents/rechnung.pdf', reader: 'local' })));
    fireEvent.click(await within(dialog).findByRole('button', { name: 'In die Rechnung übernehmen' }));
    expect(field(dialog, 'Lieferant')).toHaveValue('Stadtwerke Leipzig GmbH');
    expect(field(dialog, 'Brutto')).toHaveValue(1190);
    expect(within(dialog).getByText('5 Werte von Lokale Regeln')).toBeInTheDocument();
    expect(within(dialog).getByText('Werte aus „rechnung.pdf“ übernommen.')).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Speichern' }));
    expect(within(dialog).getByRole('alert').textContent).toContain('prüfen und bestätigen: Lieferant, Rechnungsnr., Rechnungsdatum, Netto, Brutto');
    expect(api.post).not.toHaveBeenCalledWith('/invoice-review/receipts', expect.anything());
    fireEvent.change(field(dialog, 'Netto'), { target: { value: '1000.5' } });          // changed: no confirmation needed
    expect(within(field(dialog, 'Netto').closest('.form-group')).getByText('geändert')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Alle bestätigen' }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Speichern' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/invoice-review/receipts', expect.objectContaining({ document_id: 'd7',
      invoice: expect.objectContaining({ supplier: 'Stadtwerke Leipzig GmbH', invoice_number: 'RE-2026-0042', net_amount: 1000.5, gross_amount: 1190 }) })));
    expect(api.post).toHaveBeenCalledWith('/documents', expect.objectContaining({ file_url: '/uploads/documents/rechnung.pdf', document_type: 'invoice' }));
    expect(api.upload).toHaveBeenCalledTimes(1);                                   // the same upload, not a second copy
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/ai/readings/r9/finish', expect.objectContaining({
      outcome: 'taken_over', record_kind: 'invoice', record_id: 'i7' })));
  });
});
