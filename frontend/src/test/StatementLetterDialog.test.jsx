import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createHash, webcrypto } from 'node:crypto';
import { StrictMode } from 'react';
import { MemoryRouter, createMemoryRouter, RouterProvider } from 'react-router-dom';
import StatementLetterDialog from '../features/billing/StatementLetterDialog';
import { NavigationProtectionProvider } from '../components/UnsavedNavigationGuard';
import { letterDownloadPath, statementLetterService } from '../features/billing/statementLetterApi';

const mocks = vi.hoisted(() => ({ auth: { user: { id: 'owner', role: 'eigentuemer' }, write: null }, draft: {} }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => mocks.auth }));
vi.mock('../hooks/useEntityFormDraft', () => ({ default: () => mocks.draft }));
vi.mock('../components/PdfPreview', () => ({ default: ({ url }) => <div role="img" aria-label="Echte Briefvorschau" data-url={url} /> }));
vi.mock('../api', () => ({ api: { getBlob: vi.fn() } }));

const bytes = new TextEncoder().encode('%PDF-1.7 synthetic letter');
const hash = createHash('sha256').update(bytes).digest('hex');
const blob = { arrayBuffer: async () => bytes.buffer };
const defaults = { sender_name: 'Verwaltung', sender_address: 'Markt 1\n10115 Berlin', recipient_name: 'Mieter Eins', recipient_address: 'Weg 2\n10115 Berlin', issue_date: '2026-10-19', subject: 'Ihre Betriebskostenabrechnung', salutation: 'Guten Tag,', intro: 'Hier erhalten Sie die Abrechnung.', closing: 'Mit freundlichen Grüßen', signature: 'Verwaltung' };
const context = (extra = {}) => ({ source_revision: 'revision-one', statement_status: 'final', period_status: 'final', can_publish: true, defaults: { ...defaults }, warnings: [], originals: [], ...extra });
const review = (body, draft = false) => ({ state: 'preview', review_hash: 'a'.repeat(64), pdf_sha256: hash, size_bytes: bytes.length, review: { source_revision: body.source_revision, data: body.data, draft, pdf_sha256: hash } });
const result = { document_id: 'doc-1', version_id: 'version-1', review_hash: 'a'.repeat(64), pdf_sha256: hash, download_url: '/files/download?key=billing-letters%2Fdoc-1.pdf', created_at: '2026-10-19T10:00:00Z' };
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const serviceFor = (source = context()) => ({ loadContext: vi.fn().mockResolvedValue(source), preview: vi.fn(async (_id, body) => review(body, !source.can_publish)), previewPdf: vi.fn().mockResolvedValue(blob), publish: vi.fn().mockResolvedValue(result), downloadOriginal: vi.fn().mockResolvedValue(blob) });
const mount = (service = serviceFor(), props = {}) => ({ service, ...render(<MemoryRouter><StatementLetterDialog statementId="statement-1" service={service} onClose={vi.fn()} {...props} /></MemoryRouter>) });
const ready = async () => screen.findByLabelText('Betreff *');
async function makePreview() { fireEvent.click(screen.getByRole('button', { name: 'PDF-Vorschau erstellen' })); await screen.findByRole('img', { name: 'Echte Briefvorschau' }); }
async function approve() { await makePreview(); fireEvent.click(screen.getByRole('checkbox')); }

beforeEach(() => {
  mocks.auth = { user: { id: 'owner', role: 'eigentuemer' }, write: null };
  mocks.draft = { enabled: false, ready: true, clear: vi.fn().mockResolvedValue(), stage: vi.fn(), sessionKey: 'test-draft' };
  vi.stubGlobal('crypto', { subtle: webcrypto.subtle, randomUUID: vi.fn(() => 'fixed-command-key') });
  URL.createObjectURL = vi.fn(() => 'blob:letter-test'); URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('statement letter review and immutable original', () => {
  it('shows a draft PDF without permitting an original and retains accessible fields', async () => {
    const service = serviceFor(context({ can_publish: false, statement_status: 'draft' }));
    mount(service); await ready(); await makePreview();
    expect(screen.getByRole('heading', { name: 'Entwurf – nicht archiviert' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Als Original archivieren' })).toBeDisabled();
    expect(screen.getByRole('checkbox')).toBeDisabled(); expect(service.publish).not.toHaveBeenCalled();
  });
  it('archives only an explicitly reviewed final PDF and preserves previous originals with protected downloads', async () => {
    const old = { ...result, document_id: 'old-document', version_id: 'old-version' };
    const service = serviceFor(context({ originals: [old] })); const onPublished = vi.fn();
    mount(service, { onPublished }); await ready();
    expect(screen.getByRole('button', { name: 'Als Original archivieren' })).toBeDisabled();
    await approve(); fireEvent.click(screen.getByRole('button', { name: 'Als Original archivieren' }));
    await waitFor(() => expect(onPublished).toHaveBeenCalledWith(result));
    expect(service.publish).toHaveBeenCalledWith('statement-1', {
      source_revision: 'revision-one', data: defaults, review_hash: 'a'.repeat(64), idempotency_key: 'fixed-command-key',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(mocks.draft.clear).toHaveBeenCalledWith({ completed: true });
    expect(screen.getAllByRole('link', { name: 'Dokument öffnen' }).some(link => link.getAttribute('href') === '/documents?focus_id=old-document')).toBe(true);
    fireEvent.click(screen.getAllByRole('button', { name: 'Original herunterladen' })[0]);
    await waitFor(() => expect(service.downloadOriginal).toHaveBeenCalledWith(result, expect.objectContaining({ signal: expect.any(AbortSignal) })));
    expect(screen.getByText(/Der Brief wurde nicht versendet/)).toBeInTheDocument();
  });
  it('invalidates PDF, approval and blob on every field edit', async () => {
    const { service } = mount(); await ready(); await approve();
    fireEvent.change(screen.getByLabelText('Betreff *'), { target: { value: 'Geänderter Betreff' } });
    expect(screen.queryByRole('img', { name: 'Echte Briefvorschau' })).not.toBeInTheDocument();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:letter-test');
    expect(screen.getByRole('checkbox')).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Als Original archivieren' })).toBeDisabled();
    expect(service.publish).not.toHaveBeenCalled(); expect(mocks.draft.stage).toHaveBeenCalledWith(expect.objectContaining({ subject: 'Geänderter Betreff' }));
  });
  it('rejects a PDF whose bytes do not match the reviewed server hash', async () => {
    const service = serviceFor(); service.previewPdf.mockResolvedValue({ arrayBuffer: async () => new TextEncoder().encode('different PDF').buffer });
    mount(service); await ready(); fireEvent.click(screen.getByRole('button', { name: 'PDF-Vorschau erstellen' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('PDF-Datei stimmt nicht');
    expect(screen.getByRole('button', { name: 'Als Original archivieren' })).toBeDisabled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
  it('discards a late preview answer after editing while preserving the new values', async () => {
    const waiting = deferred(); const service = serviceFor(); service.preview.mockImplementationOnce(() => waiting.promise);
    mount(service); await ready(); fireEvent.click(screen.getByRole('button', { name: 'PDF-Vorschau erstellen' }));
    const sent = service.preview.mock.calls[0][1];
    fireEvent.change(screen.getByLabelText('Betreff *'), { target: { value: 'Neuer Stand' } });
    await act(async () => waiting.resolve(review(sent)));
    expect(service.previewPdf).not.toHaveBeenCalled(); expect(screen.getByLabelText('Betreff *')).toHaveValue('Neuer Stand');
    expect(screen.queryByRole('img', { name: 'Echte Briefvorschau' })).not.toBeInTheDocument();
  });
  it('reloads a changed source explicitly, retaining input and requiring a new review', async () => {
    const service = serviceFor(); service.preview.mockRejectedValueOnce(Object.assign(new Error('Quelle geändert'), { statusCode: 412 }));
    mount(service); await ready(); fireEvent.change(screen.getByLabelText('Betreff *'), { target: { value: 'Mein Brief' } });
    fireEvent.click(screen.getByRole('button', { name: 'PDF-Vorschau erstellen' }));
    await screen.findByText('Quelle geändert');
    service.loadContext.mockResolvedValue(context({ source_revision: 'revision-two', defaults: { ...defaults, subject: 'Andere Quelle' } }));
    fireEvent.click(screen.getByRole('button', { name: 'Aktuellen Stand laden, Eingaben behalten' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'PDF-Vorschau erstellen' })).toBeEnabled());
    expect(screen.getByLabelText('Betreff *')).toHaveValue('Mein Brief'); await makePreview();
    expect(service.preview.mock.lastCall[1]).toMatchObject({ source_revision: 'revision-two', data: { subject: 'Mein Brief' } });
    expect(screen.getByRole('checkbox')).not.toBeChecked();
  });
  it('forgets an old user session and ignores its late source answer', async () => {
    const old = deferred(); const service = serviceFor(); service.loadContext.mockReturnValueOnce(old.promise);
    const view = mount(service);
    mocks.auth = { user: { id: 'other', role: 'verwalter' }, write: ['/billing/periods', '/documents'] };
    service.loadContext.mockResolvedValue(context({ defaults: { ...defaults, recipient_name: 'Neuer Benutzer' } }));
    view.rerender(<MemoryRouter><StatementLetterDialog statementId="statement-1" service={service} onClose={vi.fn()} /></MemoryRouter>);
    await screen.findByDisplayValue('Neuer Benutzer');
    await act(async () => old.resolve(context({ defaults: { ...defaults, recipient_name: 'Privater alter Empfänger' } })));
    expect(screen.queryByDisplayValue('Privater alter Empfänger')).not.toBeInTheDocument();
  });
  it.each([undefined, 408, 503])('holds an uncertain outcome (%s) unchanged, blocks close and editing, then replays without another original', async statusCode => {
    const service = serviceFor(); service.publish.mockRejectedValueOnce(Object.assign(new Error('Antwort verloren'), { isNetwork: true, statusCode }));
    const onClose = vi.fn(); const onPublished = vi.fn(); mount(service, { onClose, onPublished }); await ready(); await approve();
    fireEvent.click(screen.getByRole('button', { name: 'Als Original archivieren' }));
    await screen.findByRole('button', { name: 'Archivierung erneut prüfen' });
    expect(screen.getByLabelText('Betreff *')).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Betreff *'), { target: { value: 'Manipulierter Stand' } });
    fireEvent.click(screen.getByRole('button', { name: 'Briefdialog schließen', exact: true })); expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Archivierung erneut prüfen' }));
    await waitFor(() => expect(onPublished).toHaveBeenCalledTimes(1));
    expect(service.publish.mock.calls[1][1]).toEqual(service.publish.mock.calls[0][1]);
    expect(service.publish.mock.calls[1][1].data.subject).toBe(defaults.subject);
    expect(screen.getAllByRole('button', { name: 'Original herunterladen' })).toHaveLength(1);
  });
  it.each([401, 403])('clears all private data and blobs after a %s publishing denial', async statusCode => {
    const service = serviceFor(); service.publish.mockRejectedValue(Object.assign(new Error('Kein Zugriff'), { statusCode }));
    mount(service); await ready(); await approve(); fireEvent.click(screen.getByRole('button', { name: 'Als Original archivieren' }));
    await screen.findByText(/privaten Briefdaten wurden ausgeblendet/);
    expect(screen.queryByLabelText('Betreff *')).not.toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Echte Briefvorschau' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Originalhistorie' })).not.toBeInTheDocument();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:letter-test');
  });
  it('keeps a dirty letter through actual router Back and holds delayed draft deletion before discard', async () => {
    const clearing = deferred(); mocks.draft.clear.mockReturnValue(clearing.promise);
    const router = createMemoryRouter([{ path: '*', element: <NavigationProtectionProvider><StatementLetterDialog statementId="statement-1" service={serviceFor()} onClose={vi.fn()} /></NavigationProtectionProvider> }], { initialEntries: ['/previous', '/statements'], initialIndex: 1 });
    render(<RouterProvider router={router} />); await ready();
    fireEvent.change(screen.getByLabelText('Betreff *'), { target: { value: 'Nicht verlieren' } });
    await act(async () => router.navigate(-1)); await screen.findByRole('alertdialog');
    fireEvent.click(screen.getByRole('button', { name: 'Weiter bearbeiten' }));
    expect(router.state.location.pathname).toBe('/statements'); expect(screen.getByLabelText('Betreff *')).toHaveValue('Nicht verlieren');
    await act(async () => router.navigate(-1)); fireEvent.click(screen.getByRole('button', { name: 'Eingaben verwerfen' }));
    expect(screen.getByRole('button', { name: 'Weiter bearbeiten' })).toBeDisabled();
    expect(router.state.location.pathname).toBe('/statements');
    await act(async () => clearing.resolve()); await waitFor(() => expect(router.state.location.pathname).toBe('/previous'));
  });
  it('restores editable draft values while discarding any prior PDF approval', async () => {
    mocks.draft = { ...mocks.draft, enabled: true, recovery: { values: { ...defaults, subject: 'Gesicherter Brief' }, source_state: { status: 'current' } }, recover: vi.fn(async () => { mocks.draft.recovery = null; }) };
    mount(); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Entwurf übernehmen' }));
    await screen.findByDisplayValue('Gesicherter Brief'); expect(mocks.draft.recover).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Als Original archivieren' })).toBeDisabled();
  });
  it('ignores the aborted StrictMode source request and releases only the active preview blob', async () => {
    const first = deferred(); const service = serviceFor(); service.loadContext.mockReturnValueOnce(first.promise);
    const view = render(<StrictMode><MemoryRouter><StatementLetterDialog statementId="statement-1" service={service} onClose={vi.fn()} /></MemoryRouter></StrictMode>);
    await ready(); expect(service.loadContext).toHaveBeenCalledTimes(2);
    expect(service.loadContext.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => first.resolve(context({ defaults: { ...defaults, subject: 'Alter StrictMode-Aufruf' } })));
    expect(screen.getByLabelText('Betreff *')).toHaveValue(defaults.subject);
    await makePreview(); view.unmount(); expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:letter-test');
  });
  it('holds actual Back, local close and Escape throughout publish and its delayed draft cleanup', async () => {
    const publishing = deferred(); const clearing = deferred(); const service = serviceFor(); service.publish.mockReturnValue(publishing.promise);
    mocks.draft.clear.mockReturnValue(clearing.promise); const onClose = vi.fn(); const onPublished = vi.fn();
    const router = createMemoryRouter([{ path: '*', element: <NavigationProtectionProvider><StatementLetterDialog statementId="statement-1" service={service} onClose={onClose} onPublished={onPublished} /></NavigationProtectionProvider> }], { initialEntries: ['/previous', '/statements'], initialIndex: 1 });
    render(<RouterProvider router={router} />); await ready(); await approve();
    fireEvent.click(screen.getByRole('button', { name: 'Als Original archivieren' }));
    await act(async () => router.navigate(-1));
    fireEvent.click(screen.getByRole('button', { name: 'Briefdialog schließen' })); fireEvent.keyDown(document, { key: 'Escape' });
    expect(router.state.location.pathname).toBe('/statements'); expect(onClose).not.toHaveBeenCalled();
    await act(async () => publishing.resolve(result)); await waitFor(() => expect(mocks.draft.clear).toHaveBeenCalled());
    await act(async () => router.navigate(-1)); fireEvent.click(screen.getByRole('button', { name: 'Briefdialog schließen' }));
    expect(router.state.location.pathname).toBe('/statements'); expect(onClose).not.toHaveBeenCalled(); expect(onPublished).not.toHaveBeenCalled();
    await act(async () => clearing.resolve()); await waitFor(() => expect(onPublished).toHaveBeenCalledTimes(1));
  });
  it('forgets a pending original and its late success when permissions change for the same user', async () => {
    const publishing = deferred(); const service = serviceFor(); service.publish.mockReturnValue(publishing.promise); const onPublished = vi.fn();
    const view = mount(service, { onPublished }); await ready(); await approve(); fireEvent.click(screen.getByRole('button', { name: 'Als Original archivieren' }));
    mocks.auth = { user: { id: 'owner', role: 'readonly' }, write: [] };
    service.loadContext.mockResolvedValue(context({ can_publish: false, defaults: { ...defaults, subject: 'Nur lesbar' } }));
    view.rerender(<MemoryRouter><StatementLetterDialog statementId="statement-1" service={service} onClose={vi.fn()} onPublished={onPublished} /></MemoryRouter>);
    await screen.findByDisplayValue('Nur lesbar'); await act(async () => publishing.resolve(result));
    expect(onPublished).not.toHaveBeenCalled(); expect(screen.getByRole('button', { name: 'Als Original archivieren' })).toBeDisabled();
    expect(screen.queryByText(/Das Original wurde archiviert/)).not.toBeInTheDocument();
  });
  it('cancels a read before discard so its late completion cannot unlock delayed draft deletion', async () => {
    const downloading = deferred(); const clearing = deferred(); const service = serviceFor(context({ originals: [result] }));
    service.downloadOriginal.mockReturnValue(downloading.promise); mocks.draft.clear.mockReturnValue(clearing.promise); const onClose = vi.fn();
    mount(service, { onClose }); await ready(); fireEvent.change(screen.getByLabelText('Betreff *'), { target: { value: 'Mein Entwurf' } });
    fireEvent.click(screen.getByRole('button', { name: 'Original herunterladen' }));
    fireEvent.click(screen.getByRole('button', { name: 'Briefdialog schließen' }));
    await screen.findByRole('alertdialog'); expect(service.downloadOriginal.mock.calls[0][1].signal.aborted).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Eingaben verwerfen' }));
    await act(async () => downloading.resolve(blob));
    expect(screen.getByRole('button', { name: 'Weiter bearbeiten' })).toBeDisabled();
    fireEvent.keyDown(document, { key: 'Escape' }); expect(onClose).not.toHaveBeenCalled();
    await act(async () => clearing.resolve()); await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });
});

describe('protected original download URL', () => {
  it('uses the authenticated blob client with an API-relative path and rejects external or token URLs', async () => {
    const { api } = await import('../api'); api.getBlob.mockResolvedValue(blob);
    await statementLetterService.downloadOriginal(result, {});
    expect(api.getBlob).toHaveBeenCalledWith('/files/download?key=billing-letters%2Fdoc-1.pdf', {});
    expect(letterDownloadPath('/api/v1/files/download?key=one')).toBe('/files/download?key=one');
    for (const url of ['https://elsewhere.test/file.pdf', '//elsewhere.test/file.pdf', '/files/download?token=secret', '/uploads/file.pdf']) expect(() => letterDownloadPath(url)).toThrow();
  });
});
