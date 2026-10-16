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
