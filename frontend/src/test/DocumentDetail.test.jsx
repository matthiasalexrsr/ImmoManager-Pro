import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import DocumentDetail from '../pages/DocumentDetail';
import { shownFilename, uploadNewVersion } from '../features/documentDetail/documentDetailApi';

vi.mock('../api', () => ({ api: { get: vi.fn(), captureSession: () => () => {} } }));
vi.mock('../i18n', () => {
  const t = key => ({ 'modals.confirmDelete.body': 'wirklich löschen?' })[key] || '';
  return { useTranslation: () => ({ t, locale: 'de-DE' }) };
});
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ role: 'verwalter' }), useCanWrite: () => true }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => () => Promise.resolve(true) }));
vi.mock('../components/PdfPreview', () => ({ default: ({ url }) => <div data-testid="pdf-preview">{url}</div> }));
vi.mock('../components/FileViewer', () => ({ default: ({ title }) => <div role="dialog">{title}</div> }));
vi.mock('../features/documentWork/DocumentWorkbench', () => ({ default: () => <div role="dialog">Werkzeuge</div> }));
vi.mock('../features/channels/ChannelPanel', () => ({ default: () => <div>Kanal</div> }));

const version = (number, extra = {}) => ({ id: `v${number}`, document_id: 'd1', number, operation: number === 1 ? 'archive_original' : 'upload',
  comment: number === 1 ? 'Unveränderliches Eingangsoriginal' : 'Neue Fassung: korrigierte Rechnungsnummer', filename: `rechnung-${number}.pdf`,
  media_type: 'application/pdf', size_bytes: 20480, created_at: '2026-10-20T10:00:00+00:00', restored_from_id: null, ...extra });
const details = (overrides = {}) => ({
  document: { id: 'd1', title: 'Rechnung Heizung', document_type: 'Rechnung', document_date: '2026-03-01', file_url: '/uploads/documents/r.pdf',
    property_id: 'p1', unit_id: null, contract_id: 'c1', tenant_id: null, valid_until: null, tags: 'Heizung', description: 'Wartung',
    retention_class: null, reminder_days: null },
  places: { property: 'Haus am See', unit: null, contract: 'MV-2021-053', tenant: null },
  retention: { retention_class: 'booking_record', chosen: false, label: 'Buchungsbeleg', basis: '§ 147 AO', state: 'running', locked: true,
    until: '2034-12-31', years: 8, text: 'Buchungsbeleg: aufzubewahren bis 31.12.2034.' },
  text: { source: 'pdf_text', characters: 1200, indexed_at: '2026-10-20T10:05:00', excerpt: 'Rechnung Nr. 17 Heizungswartung', source_ref: 'version:v2' },
  versions: { items: [version(2), version(1)], next_before: null },
  ...overrides,
});
const makeService = value => ({
  load: vi.fn().mockResolvedValue(value), olderVersions: vi.fn(), source: vi.fn(), uploadVersion: vi.fn(), patch: vi.fn(),
  remove: vi.fn().mockResolvedValue(null), versionBlob: vi.fn().mockResolvedValue(new Blob(['%PDF-1.7'], { type: 'application/pdf' })),
});
const mount = service => render(<MemoryRouter initialEntries={['/documents/d1']}><Routes>
  <Route path="/documents/:documentId" element={<DocumentDetail service={service} />} />
  <Route path="/documents" element={<p>Liste</p>} />
</Routes></MemoryRouter>);

beforeEach(() => {
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:fassung-2');
  globalThis.URL.revokeObjectURL = vi.fn();
});
afterEach(cleanup);

describe('the page of one document', () => {
  it('shows the current version, its facts, places, retention, versions and the text read', async () => {
    const service = makeService(details());
    mount(service);
    expect(await screen.findByRole('heading', { name: 'Rechnung Heizung' })).toBeInTheDocument();
    expect(await screen.findByTestId('pdf-preview')).toHaveTextContent('blob:fassung-2');
    expect(service.versionBlob).toHaveBeenCalledWith('d1', 'v2', expect.anything());
    expect(screen.getByRole('region', { name: 'Zuordnung' })).toHaveTextContent('Haus am See');
    expect(within(screen.getByRole('region', { name: 'Zuordnung' })).getByRole('link', { name: 'MV-2021-053' })).toHaveAttribute('href', '/contracts?contract_id=c1');
    expect(screen.getByRole('region', { name: 'Aufbewahrung' })).toHaveTextContent('bis 31.12.2034');
    const list = screen.getByRole('list', { name: 'Archivierte Fassungen' });
    expect(within(list).getAllByRole('listitem').map(item => item.textContent)).toEqual([
      expect.stringContaining('Fassung 2aktuell'), expect.stringContaining('Fassung 1')]);
    expect(list).toHaveTextContent('korrigierte Rechnungsnummer');
    expect(shownFilename('5a899c6245f642a688d5b0f24d9b64ba_rechnung-heizung.pdf')).toBe('rechnung-heizung.pdf');
    expect(shownFilename('scan_2026.pdf')).toBe('scan_2026.pdf');
    expect(screen.getByRole('region', { name: 'Gelesener Text' })).toHaveTextContent('aus Fassung 2');
    // documents with archived versions stay
    expect(screen.getByRole('button', { name: 'Dokument löschen' })).toBeDisabled();
  });

  it('previews the uploaded file while there is no archived version and deletes after asking', async () => {
    const service = makeService(details({ versions: { items: [], next_before: null }, retention: { state: 'ended', locked: false, text: 'abgelaufen' } }));
    mount(service);
    expect(await screen.findByTestId('pdf-preview')).toHaveTextContent('/uploads/documents/r.pdf');
    expect(service.versionBlob).not.toHaveBeenCalled();
    expect(screen.getByRole('region', { name: 'Fassungen' })).toHaveTextContent('Bisher gibt es nur die hochgeladene Datei');
    fireEvent.click(screen.getByRole('button', { name: 'Dokument löschen' }));
    await screen.findByText('Liste');
    expect(service.remove).toHaveBeenCalledWith('d1');
  });

  it('says why a document without a property or contract has no versions', async () => {
    const service = makeService(details({ versions: { items: [], next_before: null, unavailable: 'Das Dokument ist keiner Immobilie und keinem Vertrag zugeordnet.' } }));
    mount(service);
    const region = await screen.findByRole('region', { name: 'Fassungen' });
    expect(region).toHaveTextContent('keiner Immobilie und keinem Vertrag zugeordnet. Fassungen und die Dokumentwerkzeuge gibt es, sobald');
    expect(screen.queryByRole('form', { name: 'Neue Fassung hochladen' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Dokumentwerkzeuge' })).toBeNull();
  });

  it('explains the retention lock instead of deleting', async () => {
    const service = makeService(details({ versions: { items: [], next_before: null } }));
    mount(service);
    fireEvent.click(await screen.findByRole('button', { name: 'Dokument löschen' }));
    expect(await screen.findByRole('dialog', { name: 'Aufbewahrungspflicht' })).toHaveTextContent('aufzubewahren bis 31.12.2034');
    expect(service.remove).not.toHaveBeenCalled();
  });

  it('uploads a new version against the current source and reloads the page', async () => {
    const service = makeService(details());
    service.source.mockResolvedValue({ sha256: 'a'.repeat(64), document_revision: 'rev-7', version: { id: 'v2' } });
    service.uploadVersion.mockResolvedValue({ version: version(3), previous: version(2) });
    mount(service);
    const form = await screen.findByRole('form', { name: 'Neue Fassung hochladen' });
    const file = new File(['%PDF-1.7 neu'], 'rechnung-neu.pdf', { type: 'application/pdf' });
    fireEvent.change(within(form).getByLabelText('Datei'), { target: { files: [file] } });
    fireEvent.change(within(form).getByLabelText('Was hat sich geändert? (optional)'), { target: { value: ' neue Nummer ' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Als neue Fassung speichern' }));
    expect(await within(form).findByRole('status')).toHaveTextContent('Gespeichert als Fassung 3');
    const [id, sent] = service.uploadVersion.mock.calls[0];
    expect(id).toBe('d1');
    expect(Object.fromEntries([...sent.entries()].filter(([key]) => key !== 'file' && key !== 'command_key'))).toEqual({
      expected_sha256: 'a'.repeat(64), expected_document_revision: 'rev-7', expected_version: 'v2', comment: 'neue Nummer' });
    await waitFor(() => expect(service.load).toHaveBeenCalledTimes(2));
  });
});

describe('a repeated version upload', () => {
  it('reuses the command after a lost answer, and starts fresh for another file', async () => {
    const service = { source: vi.fn().mockResolvedValue({ sha256: 'b'.repeat(64), document_revision: 'r1', version: null }),
      uploadVersion: vi.fn().mockRejectedValueOnce(new Error('Netzwerkfehler')).mockResolvedValue({ version: { number: 2 } }) };
    const attempt = { current: null };
    const file = new File(['x'], 'scan.pdf', { lastModified: 1 });
    await expect(uploadNewVersion(service, 'd1', file, '', attempt)).rejects.toThrow('Netzwerkfehler');
    await uploadNewVersion(service, 'd1', file, '', attempt);
    const keys = service.uploadVersion.mock.calls.map(([, form]) => form.get('command_key'));
    expect(keys[0]).toBe(keys[1]);
    expect(service.source).toHaveBeenCalledTimes(1);
    expect(service.uploadVersion.mock.calls[0][1].has('expected_version')).toBe(false);
    await uploadNewVersion(service, 'd1', new File(['y'], 'anders.pdf', { lastModified: 2 }), '', attempt);
    expect(service.source).toHaveBeenCalledTimes(2);
    expect(service.uploadVersion.mock.calls[2][1].get('command_key')).not.toBe(keys[0]);
  });
});
