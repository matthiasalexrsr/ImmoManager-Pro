import { Blob as NativeBlob } from 'node:buffer';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import BackupSection from '../pages/settings/BackupSection';
import { api } from '../api';
import german from '../../../i18n/de-DE.json';

const mocks = vi.hoisted(() => ({ readonly: false, error: vi.fn(), invalidateAll: vi.fn(), createURL: vi.fn(), revokeURL: vi.fn() }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isReadonly: mocks.readonly }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => ({ invalidateAll: mocks.invalidateAll }) }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: mocks.error }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key.split('.').reduce((value, part) => value?.[part], german) || key }) }));

const businessData = () => ({ version: '1.0.0', exported_at: '2026-10-01T12:00:00Z', portfolios: [], properties: [], units: [], tenants: [], contracts: [], bookings: [], receivables: [], rent_charges: [], payments: [] });
const businessBlob = data => new NativeBlob([JSON.stringify(data || businessData())], { type: 'application/json' });
const validBackup = { backup: 'backup_synthetic.json', size_bytes: 42, scope: 'business-data-only' };
const upload = () => fireEvent.change(screen.getByLabelText('Daten importieren'), { target: { files: [new File(['{}'], 'synthetic.json', { type: 'application/json' })] } });
const exportButton = () => screen.getByRole('button', { name: 'JSON-Export' });

beforeEach(() => {
  mocks.readonly = false;
  mocks.error.mockReset();
  mocks.invalidateAll.mockReset();
  mocks.createURL.mockReset().mockReturnValue('blob:synthetic-business-export');
  mocks.revokeURL.mockReset();
  const originalURL = URL;
  vi.stubGlobal('URL', class extends originalURL {
    static createObjectURL(blob) { return mocks.createURL(blob); }
    static revokeObjectURL(url) { return mocks.revokeURL(url); }
  });
  vi.stubGlobal('Blob', NativeBlob);
  vi.stubGlobal('fetch', vi.fn());
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  vi.spyOn(api, 'get').mockResolvedValue({ backend: 'SQLite' });
  vi.spyOn(api, 'post').mockResolvedValue(validBackup);
  vi.spyOn(api, 'getBlob').mockResolvedValue(businessBlob());
  vi.spyOn(api, 'postForm').mockResolvedValue({ imported: { tenants: 1 }, errors: [], replace_existing: false });
  localStorage.clear();
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('downloads only a validated business export through the shared API and revokes its URL', async () => {
  render(<BackupSection />);
  fireEvent.click(exportButton());
  await waitFor(() => expect(mocks.createURL).toHaveBeenCalledTimes(1));
  expect(api.getBlob).toHaveBeenCalledWith('/data/export');
  expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1);
  expect(mocks.revokeURL).toHaveBeenCalledWith('blob:synthetic-business-export');
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.getByText(/ohne Anhänge, Benutzerkonten und vollständige Abrechnungsdaten/)).toBeInTheDocument();
  expect(screen.getByText(/offline nach dem Stoppen/)).toBeInTheDocument();
});

it.each(['backup', 'export', 'import'].flatMap(operation => [401, 500].map(status => [operation, status])))('reports %s HTTP %i failure without download or success', async (operation, status) => {
  const error = Object.assign(new Error('Synthetic server rejection'), { statusCode: status });
  const method = operation === 'backup' ? 'post' : operation === 'export' ? 'getBlob' : 'postForm';
  api[method].mockRejectedValue(error);
  render(<BackupSection />);
  if (operation === 'backup') fireEvent.click(screen.getByRole('button', { name: 'Backup erstellen' }));
  if (operation === 'export') fireEvent.click(exportButton());
  if (operation === 'import') upload();
  expect(await screen.findByRole('alert')).toHaveTextContent(`HTTP ${status}`);
  expect(screen.getByRole('alert')).toHaveTextContent('Synthetic server rejection');
  expect(mocks.createURL).not.toHaveBeenCalled();
  expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(mocks.invalidateAll).not.toHaveBeenCalled();
});

it.each([
  new NativeBlob(['<html>server error</html>'], { type: 'text/html' }),
  new NativeBlob(['not json'], { type: 'application/json' }),
  businessBlob({ detail: 'Not authenticated', access_token: 'synthetic-error-token' }),
  businessBlob({ ...businessData(), exported_at: 'bad timestamp' }),
  businessBlob({ ...businessData(), payments: 'broken collection' }),
])('rejects invalid export MIME/content/metadata without creating a download', async blob => {
  api.getBlob.mockResolvedValue(blob);
  render(<BackupSection />);
  fireEvent.click(exportButton());
  expect(await screen.findByRole('alert')).toHaveTextContent('kein gültiger JSON-Geschäftsdatenexport');
  expect(mocks.createURL).not.toHaveBeenCalled();
  expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
});

it.each([null, {}, { filename: 'backup.json' }, { ...validBackup, scope: 'full' }, { ...validBackup, size_bytes: 0 }, { ...validBackup, backup: '../unsafe.json' }])('rejects malformed backup result and never substitutes OK or a complete-backup claim', async result => {
  api.post.mockResolvedValue(result);
  render(<BackupSection />);
  fireEvent.click(screen.getByRole('button', { name: 'Backup erstellen' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('keine gültige Teil-Geschäftsdatensicherung');
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});

it('shows the backup filename and size with the server-confirmed business-only scope', async () => {
  render(<BackupSection />);
  fireEvent.click(screen.getByRole('button', { name: 'Backup erstellen' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Teil-Geschäftsdaten gespeichert: backup_synthetic.json (42 B)');
});

it('prevents duplicate backup clicks and conflicting uploads/exports while the request is pending', async () => {
  let resolve;
  api.post.mockReturnValue(new Promise(done => { resolve = done; }));
  render(<BackupSection />);
  const button = screen.getByRole('button', { name: 'Backup erstellen' });
  fireEvent.click(button);
  fireEvent.click(button);
  upload();
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.postForm).not.toHaveBeenCalled();
  expect(exportButton()).toBeDisabled();
  expect(screen.getByLabelText('Daten importieren')).toBeDisabled();
  await act(async () => resolve(validBackup));
  expect(screen.getByRole('button', { name: 'Backup erstellen' })).toBeEnabled();
});

it('blocks readonly mutations in handlers and leaves permitted export available', async () => {
  mocks.readonly = true;
  render(<BackupSection />);
  expect(screen.getByRole('button', { name: 'Backup erstellen' })).toBeDisabled();
  expect(screen.getByLabelText('Daten importieren')).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Backup erstellen' }));
  upload();
  expect(api.post).not.toHaveBeenCalled();
  expect(api.postForm).not.toHaveBeenCalled();
  fireEvent.click(exportButton());
  await waitFor(() => expect(mocks.createURL).toHaveBeenCalledTimes(1));
});

it('uploads multipart through the shared API, refreshes data only on confirmed success and clears input', async () => {
  render(<BackupSection />);
  upload();
  expect(await screen.findByRole('status')).toHaveTextContent('Teil-Geschäftsdaten importiert');
  expect(api.postForm.mock.calls[0][0]).toBe('/data/import');
  expect(api.postForm.mock.calls[0][1].get('file').name).toBe('synthetic.json');
  expect(mocks.invalidateAll).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText('Daten importieren')).toHaveValue('');
});

it('shows upload validation details from the API and permits retry without a false import success', async () => {
  api.postForm.mockRejectedValueOnce(Object.assign(new Error('Dateireferenzen ungültig'), { statusCode: 400, details: { field: 'payments[0].booking_id', reason: 'Buchung nicht gefunden' } }));
  render(<BackupSection />);
  upload();
  expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 400');
  expect(screen.getByRole('alert')).toHaveTextContent('payments[0].booking_id');
  expect(screen.getByRole('alert')).toHaveTextContent('Buchung nicht gefunden');
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(mocks.invalidateAll).not.toHaveBeenCalled();
  upload();
  expect(await screen.findByRole('status')).toHaveTextContent('Teil-Geschäftsdaten importiert');
  expect(api.postForm).toHaveBeenCalledTimes(2);
});

it('rejects malformed import success responses', async () => {
  api.postForm.mockResolvedValue({ detail: 'unexpected success payload' });
  render(<BackupSection />);
  upload();
  expect(await screen.findByRole('alert')).toHaveTextContent('keinen gültigen Import');
  expect(mocks.invalidateAll).not.toHaveBeenCalled();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});

it('treats reported import errors as failure even when the HTTP status was successful', async () => {
  api.postForm.mockResolvedValue({ imported: { tenants: 1 }, errors: [{ field: 'tenants[0].email', message: 'Invalid tenant email' }] });
  render(<BackupSection />);
  upload();
  expect(await screen.findByRole('alert')).toHaveTextContent('tenants[0].email');
  expect(screen.getByRole('alert')).toHaveTextContent('Invalid tenant email');
  expect(mocks.invalidateAll).not.toHaveBeenCalled();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});

it('uses the actual API token refresh before validating and downloading the JSON export', async () => {
  api.getBlob.mockRestore();
  localStorage.setItem('access_token', 'expired-synthetic-token');
  localStorage.setItem('refresh_token', 'synthetic-refresh-token');
  fetch.mockResolvedValueOnce({ status: 401, ok: false })
    .mockResolvedValueOnce({ status: 200, ok: true, json: async () => ({ access_token: 'renewed-synthetic-token' }) })
    .mockResolvedValueOnce({ status: 200, ok: true, blob: async () => businessBlob() });
  render(<BackupSection />);
  fireEvent.click(exportButton());
  await waitFor(() => expect(mocks.createURL).toHaveBeenCalledTimes(1));
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/v1/data/export', '/api/v1/auth/refresh', '/api/v1/data/export']);
  expect(fetch.mock.calls[2][1].headers.Authorization).toBe('Bearer renewed-synthetic-token');
});

it('uses actual API HTTP failure parsing instead of downloading the JSON error response', async () => {
  api.getBlob.mockRestore();
  fetch.mockResolvedValue({ status: 500, ok: false, json: async () => ({ error: { message: 'Export snapshot failed', details: 'Synthetic database unavailable' } }) });
  render(<BackupSection />);
  fireEvent.click(exportButton());
  expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 500');
  expect(screen.getByRole('alert')).toHaveTextContent('Export snapshot failed');
  expect(screen.getByRole('alert')).toHaveTextContent('Synthetic database unavailable');
  expect(mocks.createURL).not.toHaveBeenCalled();
});
