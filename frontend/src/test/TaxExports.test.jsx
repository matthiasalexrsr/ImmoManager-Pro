import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import TaxExports from '../pages/TaxExports';
import { clearWorkspaceBrowserData, setWorkspaceOwner } from '../utils/workspaceIdentity';

const access = vi.hoisted(() => ({ write: true }));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), getBlob: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => access.write }));
const profile = { id: 'profile', tax_year: 2026, created_at: '2026-10-16', spec: { name: 'Geprüftes Profil' } };
const preview = { ready: true, source_rows: 21, source_samples: [], blocking_issues: [], preview_hash: 'a'.repeat(64),
  totals: { cash_cents: '10001', income_cents: '10001', expense_cents: '0', excluded_cash_cents: '0', unclassified_cash_cents: '0' } };

beforeEach(() => {
  vi.resetAllMocks(); access.write = true;
  clearWorkspaceBrowserData();
  api.captureSession.mockReturnValue(() => {});
  api.list.mockResolvedValue([{ id: 'p', name: 'Synthetisches Portfolio' }]);
  api.get.mockImplementation(url => {
    if (url.includes('/options?')) return Promise.resolve({ accounts: [{ id: 'bank', name: 'Bank', account_type: 'bank' }], categories: [], properties: [] });
    if (url.includes('/profiles?')) return Promise.resolve({ items: [profile], total: 1 });
    if (url.includes('/projections?') || url.includes('/exports?')) return Promise.resolve({ items: [], total: 0 });
    throw new Error(url);
  });
});
afterEach(cleanup);

async function open() {
  render(<TaxExports />);
  await act(async () => {});
  expect(screen.getByRole('option', { name: 'Synthetisches Portfolio' })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Portfolio'), { target: { value: 'p' } });
  await act(async () => {});
  expect(screen.getByRole('option', { name: /Geprüftes Profil/ })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Profil für die Vorschau'), { target: { value: 'profile' } });
}

it('shows a neutral annual workflow and reaches sources beyond the preview sample', async () => {
  api.post.mockImplementation(url => Promise.resolve(url.includes('/source-page?') ? { items: [{ booking: { id: 'last', booking_date: '2026-10-01', payment_text: 'Letzte Quelle', amount_cents: '-1' }, classification_state: 'needs_review' }], total: 21, preview_hash: preview.preview_hash } : preview));
  await open();
  expect(screen.getByText(/keine WISO-Datei/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Vollständige Quellen prüfen' }));
  await screen.findByText(/Zur Bestätigung bereit/);
  fireEvent.click(screen.getByRole('button', { name: 'Weitere Quellen' }));
  await screen.findByText(/Letzte Quelle/);
  expect(api.post).toHaveBeenCalledWith(expect.stringContaining('/source-page?offset=20&limit=20'), expect.objectContaining({ profile_version_id: 'profile' }));
  expect(screen.getByText(/-0,01 €/)).toBeInTheDocument();
});

it('reuses the original idempotency key after a lost save response and retains entered values', async () => {
  setWorkspaceOwner('synthetic-tax-reviewer');
  let count = 0;
  api.post.mockImplementation(url => {
    if (url.endsWith('/preflight')) return Promise.resolve(preview);
    if (url.endsWith('/projections') && count++ === 0) return Promise.reject(new Error('Bestätigung verloren'));
    return Promise.resolve({ id: 'saved' });
  });
  await open();
  fireEvent.change(screen.getByLabelText('Begründung für offene Buchungen'), { target: { value: 'Geprüfte offene Quelle' } });
  fireEvent.click(screen.getByRole('button', { name: 'Vollständige Quellen prüfen' }));
  await screen.findByText(/Zur Bestätigung bereit/);
  fireEvent.click(screen.getByRole('button', { name: 'Geprüfte Jahresfassung unveränderlich speichern' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Bestätigung verloren');
  expect(screen.getByLabelText('Begründung für offene Buchungen')).toHaveValue('Geprüfte offene Quelle');
  fireEvent(window, new Event('beforeunload'));
  cleanup();
  await open();
  expect(screen.getByLabelText('Begründung für offene Buchungen')).toHaveValue('Geprüfte offene Quelle');
  fireEvent.click(screen.getByRole('button', { name: 'Vollständige Quellen prüfen' }));
  await screen.findByText(/Zur Bestätigung bereit/);
  fireEvent.click(screen.getByRole('button', { name: 'Geprüfte Jahresfassung unveränderlich speichern' }));
  await act(async () => {});
  const saves = api.post.mock.calls.filter(([path]) => path.endsWith('/projections'));
  expect(saves).toHaveLength(2);
  expect(saves[0][1]).toEqual(saves[1][1]);
  expect(saves[0][1].preview_hash).toBe(preview.preview_hash);
});

it('blocks confirmation when a later source page has changed and never saves stale totals', async () => {
  api.post.mockImplementation(url => Promise.resolve(url.includes('/source-page?') ? { items: [], total: 21, preview_hash: 'b'.repeat(64) } : preview));
  await open();
  fireEvent.click(screen.getByRole('button', { name: 'Vollständige Quellen prüfen' }));
  await screen.findByText(/Zur Bestätigung bereit/);
  fireEvent.click(screen.getByRole('button', { name: 'Weitere Quellen' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Buchungsquellen wurden geändert');
  expect(screen.queryByRole('button', { name: 'Geprüfte Jahresfassung unveränderlich speichern' })).not.toBeInTheDocument();
});

it('hides profile editing and disables source checks for a reader', async () => {
  access.write = false;
  await open();
  expect(screen.queryByRole('button', { name: 'Profilfassung speichern' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Vollständige Quellen prüfen' })).toBeDisabled();
  expect(api.post).not.toHaveBeenCalled();
});

it('does not display a preview after the captured session has been replaced', async () => {
  await open();
  let reject;
  api.captureSession.mockReturnValue(() => { if (reject) throw new Error('Sitzung geändert'); });
  let resolve;
  api.post.mockReturnValue(new Promise(done => { resolve = done; }));
  fireEvent.click(screen.getByRole('button', { name: 'Vollständige Quellen prüfen' }));
  reject = true;
  await act(async () => resolve(preview));
  expect(await screen.findByRole('alert')).toHaveTextContent('Sitzung geändert');
  expect(screen.queryByText(/Zur Bestätigung bereit/)).not.toBeInTheDocument();
});

const manualReport = { manual_transfer_ready: false, tax_year: 2026, period_end: '2026-10-18',
  boundary: 'Manueller Übertragungsbogen, keine importierbare WISO-Datei.', reconciled: true,
  mapped_totals: { income_cents: '0', expense_cents: '0' }, unmapped_totals: { income_cents: '-1', expense_cents: '0' },
  issues: [{ code: 'partial_year' }, { code: 'mapping_incomplete', form_line: 'Miete', property_id: 'house' }],
  rows: [{ object_number: null, property_id: 'house', property_name: 'Quellhaus', treatment: 'income', form_line: 'Miete', amount_cents: '-1', source_parts: 2 }],
  unused_object_ids: [], unused_line_mappings: [], profile_version_id: 'profile', source_sha256: 'c'.repeat(64) };

it('saves reviewed annual manual object and target labels without inventing vendor field codes', async () => {
  const originalGet = api.get.getMockImplementation();
  api.get.mockImplementation(url => url.includes('/options?') ? Promise.resolve({ accounts: [{ id: 'bank', name: 'Bank' }], categories: [], properties: [{ id: 'house', name: 'Quellhaus' }] }) : originalGet(url));
  api.post.mockResolvedValue({ id: 'saved-profile' });
  await open();
  fireEvent.change(screen.getByLabelText('Profilname'), { target: { value: 'Manuell geprüft 2026' } });
  fireEvent.change(screen.getByLabelText('Fachlich geprüft durch'), { target: { value: 'Fachprüfung' } });
  fireEvent.change(screen.getByLabelText('Quellkonto'), { target: { value: 'bank' } });
  fireEvent.change(screen.getByLabelText('Geprüfte Formularzeile (freie Bezeichnung)'), { target: { value: 'Miete' } });
  fireEvent.change(screen.getByLabelText('Fachliche Begründung'), { target: { value: 'Zahlung geprüft' } });
  fireEvent.click(screen.getByLabelText('Manuellen WISO-Übertragungsbogen für Fachjahr 2026 vorbereiten'));
  fireEvent.click(screen.getByRole('button', { name: 'Zielobjekt hinzufügen' }));
  fireEvent.change(screen.getByLabelText('Quellobjekt 1'), { target: { value: 'house' } });
  fireEvent.change(screen.getByLabelText('Geprüfte Objektbezeichnung im Ziel 1'), { target: { value: 'Mein Zielhaus' } });
  fireEvent.click(screen.getByRole('button', { name: 'Manuelle Zielzeile hinzufügen' }));
  fireEvent.change(screen.getByLabelText('Quell-Formularzeile exakt 1'), { target: { value: 'Miete' } });
  fireEvent.change(screen.getByLabelText('Manuelle Zielbezeichnung 1'), { target: { value: 'Abgelesene Zielzeile Miete' } });
  fireEvent.change(screen.getByLabelText('Begründung der Zielzuordnung 1'), { target: { value: 'Manuell für dieses Jahr geprüft' } });
  fireEvent.click(screen.getByLabelText('Zuordnungen und Ausschlüsse fachlich geprüft'));
  fireEvent.click(screen.getByRole('button', { name: 'Profilfassung speichern' }));
  await act(async () => {});
  expect(api.post).toHaveBeenCalledWith('/reports/annual-tax/profiles', expect.objectContaining({ tax_year: 2026,
    wiso_preparation: { target_product: 'WISO Steuer Windows', tax_year: 2026, evidence_version: 'hv365-21.02.1530-observed-2026-v1',
      objects: [{ property_id: 'house', object_number: 1, target_object_label: 'Mein Zielhaus' }],
      lines: [{ treatment: 'income', form_line: 'Miete', target_label: 'Abgelesene Zielzeile Miete', review_reason: 'Manuell für dieses Jahr geprüft' }] } }));
  expect(JSON.stringify(api.post.mock.calls[0][1])).not.toContain('field_nr');
  fireEvent.click(screen.getByLabelText('Manuellen WISO-Übertragungsbogen für Fachjahr 2026 vorbereiten'));
  fireEvent.click(screen.getByLabelText('Zuordnungen und Ausschlüsse fachlich geprüft'));
  fireEvent.click(screen.getByRole('button', { name: 'Profilfassung speichern' }));
  await act(async () => {});
  expect(api.post.mock.calls[1][1]).not.toHaveProperty('wiso_preparation');
});

it('shows incomplete manual mappings and a partial year separately from a valid neutral snapshot', async () => {
  api.post.mockResolvedValue({ ...preview, wiso_preparation: manualReport });
  await open();
  fireEvent.click(screen.getByRole('button', { name: 'Vollständige Quellen prüfen' }));
  await screen.findByText(/Übertragungsbogen enthält offene Punkte/);
  expect(screen.getByText(/Teiljahr: Der Zahlungsstichtag/)).toBeInTheDocument();
  expect(screen.getByText(/Objektzuordnung oder manuelle Zielbezeichnung fehlt/)).toBeInTheDocument();
  expect(screen.getByText(/Herstellerdatei: nicht verfügbar/)).toBeInTheDocument();
  expect(screen.getByText(/Zielbezeichnung fehlt · -0,01 €/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Geprüfte Jahresfassung unveränderlich speichern' })).toBeEnabled();
});

it('reads the verified retained worksheet and downloads the neutral original archive for a reader', async () => {
  access.write = false;
  const originalGet = api.get.getMockImplementation();
  api.get.mockImplementation(url => url.includes('/projections?') ? Promise.resolve({ items: [{ id: 'retained', tax_year: 2026, wiso_preparation: manualReport }], total: 1 }) : url.endsWith('/retained/wiso-preparation') ? Promise.resolve(manualReport) : originalGet(url));
  api.getBlob.mockResolvedValue(new Blob(['synthetic neutral original']));
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  const objectUrl = vi.fn(() => 'blob:synthetic');
  const revokeUrl = vi.fn();
  vi.stubGlobal('URL', class extends URL { static createObjectURL = objectUrl; static revokeObjectURL = revokeUrl; });
  try {
    await open();
    fireEvent.click(screen.getByRole('button', { name: 'Gesicherten Übertragungsbogen prüfen' }));
    await screen.findByText('Gesicherter Beleg retained');
    expect(api.get).toHaveBeenCalledWith('/reports/annual-tax/projections/retained/wiso-preparation');
    fireEvent.click(screen.getByRole('button', { name: 'Neutrale Quellen und manuellen Übertragungsbogen herunterladen' }));
    await act(async () => {});
    expect(api.getBlob).toHaveBeenCalledWith('/reports/annual-tax/projections/retained/download');
    expect(objectUrl).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(api.post).not.toHaveBeenCalled();
    await act(async () => { await new Promise(done => setTimeout(done, 1010)); });
    expect(revokeUrl).toHaveBeenCalledWith('blob:synthetic');
  } finally {
    click.mockRestore(); vi.unstubAllGlobals();
  }
});
