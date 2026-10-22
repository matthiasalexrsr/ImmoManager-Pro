import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import TaxExports from '../pages/TaxExports';
import { clearWorkspaceBrowserData } from '../utils/workspaceIdentity';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), getBlob: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true }));
const profile = { id: 'profile', tax_year: 2026, created_at: '2026-10-16', spec: { name: 'Geprüftes Profil' } };
const report = { manual_transfer_ready: true, tax_year: 2026, period_end: '2026-12-31', boundary: 'Manueller Übertragungsbogen',
  reconciled: true, mapped_totals: { income_cents: '10000', expense_cents: '0' }, unmapped_totals: { income_cents: '0', expense_cents: '0' },
  issues: [], rows: [], unused_object_ids: [], unused_line_mappings: [], profile_version_id: 'profile', source_sha256: 'f'.repeat(64),
  owners: [
    { owner_contact_id: 'linda', owner_name: 'Linda', note: 'Je Eigentümer nach den erfassten Eigentumsanteilen am Buchungstag',
      totals: { income_cents: '6000', expense_cents: '0' },
      rows: [{ object_number: 1, property_id: 'house', property_name: 'Haus', target_object_label: 'Zielhaus', treatment: 'income',
        form_line: 'Miete', target_label: 'Mieteinnahmen', amount_cents: '6000' }] },
    { owner_contact_id: 'matthias', owner_name: 'Matthias', note: 'Je Eigentümer', totals: { income_cents: '4000', expense_cents: '0' },
      rows: [{ object_number: 1, property_id: 'house', property_name: 'Haus', target_object_label: 'Zielhaus', treatment: 'income',
        form_line: 'Miete', target_label: 'Mieteinnahmen', amount_cents: '4000' }] },
  ] };

beforeEach(() => {
  vi.resetAllMocks();
  clearWorkspaceBrowserData();
  api.captureSession.mockReturnValue(() => {});
  api.list.mockResolvedValue([{ id: 'p', name: 'Synthetisches Portfolio' }]);
  api.get.mockImplementation(url => {
    if (url.includes('/options?')) return Promise.resolve({ accounts: [], categories: [], properties: [],
      owners: [{ id: 'linda', name: 'Linda' }, { id: 'matthias', name: 'Matthias' }] });
    if (url.includes('/profiles?')) return Promise.resolve({ items: [profile], total: 1 });
    if (url.includes('/projections?')) return Promise.resolve({ items: [{ id: 'retained', tax_year: 2026, wiso_preparation: {} }], total: 1 });
    if (url.includes('/exports?')) return Promise.resolve({ items: [{ id: 'old', start_date: '2026-01-01', end_date: '2026-12-31', owner_name: 'Matthias' }], total: 1 });
    if (url.endsWith('/retained/wiso-preparation')) return Promise.resolve(report);
    throw new Error(url);
  });
});
afterEach(cleanup);

async function choose(mode) {
  render(<TaxExports />);
  await act(async () => {});
  fireEvent.change(screen.getByLabelText('Verfahren'), { target: { value: mode } });
  fireEvent.change(screen.getByLabelText('Portfolio'), { target: { value: 'p' } });
  await act(async () => {});
  fireEvent.change(screen.getByLabelText('Profil für die Vorschau'), { target: { value: 'profile' } });
}

it('exports the DATEV bookings with one owner\'s part', async () => {
  api.post.mockResolvedValue({ id: 'new', rows: 3, income: '78.07', expense: '18.06', owner_name: 'Linda' });
  await choose('datev');
  expect(screen.getByText(/Anteil von Matthias/)).toBeInTheDocument();      // an earlier export of one owner
  const owner = screen.getByLabelText('Eigentümer');
  expect(within(owner).getByRole('option', { name: 'Ohne Eigentümer' })).toBeInTheDocument();
  fireEvent.change(owner, { target: { value: 'linda' } });
  fireEvent.click(screen.getByRole('button', { name: 'Vollständige Quellen prüfen' }));
  await screen.findByText(/Anteil von Linda · Eingänge: 78.07 EUR/);
  expect(api.post).toHaveBeenCalledWith('/reports/datev/preview', expect.objectContaining({ owner_contact_id: 'linda' }));
});

it('leaves the owner out of a DATEV export of the whole amounts', async () => {
  api.post.mockResolvedValue({ id: 'new', rows: 3, income: '100.01', expense: '0.00' });
  await choose('datev');
  fireEvent.click(screen.getByRole('button', { name: 'Vollständige Quellen prüfen' }));
  await screen.findByText(/Eingänge: 100.01 EUR/);
  expect(api.post.mock.calls[0][1]).not.toHaveProperty('owner_contact_id');
});

it('shows each owner\'s sheet of a retained WISO preparation', async () => {
  await choose('annual-tax');
  fireEvent.click(screen.getByRole('button', { name: 'Gesicherten Übertragungsbogen prüfen' }));
  await screen.findByText('Je Eigentümer');
  const linda = screen.getByRole('table', { name: /Linda/ });
  expect(linda).toHaveTextContent('Objekt 1 · Zielhaus');
  expect(within(linda).getByText('60,00 €')).toBeInTheDocument();
  expect(screen.getByRole('table', { name: /Matthias · Einnahmen 40,00 €/ })).toBeInTheDocument();
});
