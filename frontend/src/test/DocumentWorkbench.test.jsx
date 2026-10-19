import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { NavigationProtectionProvider } from '../components/UnsavedNavigationGuard';
import DocumentWorkbench from '../features/documentWork/DocumentWorkbench';
import InvoiceTakeover from '../features/documentWork/InvoiceTakeover';
import { pageNumbers } from '../features/documentWork/documentWorkApi';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getBlob: vi.fn(), post: vi.fn(), mountEditor: vi.fn(), destroyEditor: vi.fn(), current: vi.fn(), canWrite: true }));
vi.mock('../api', () => ({ api: { get: mocks.get, getBlob: mocks.getBlob, post: mocks.post, captureSession: () => mocks.current } }));
vi.mock('../features/documentWork/documentEditorRuntime', () => ({ loadDocumentEditor: async () => ({ mountEditor: mocks.mountEditor }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => mocks.canWrite }));
vi.mock('../components/PdfPreview', () => ({ default: () => <div>PDF-Originalansicht</div> }));
vi.mock('../features/partyWorkspace/useModalDialog', () => ({ useModalDialog: () => {} }));

const SOURCE = { document: { id: 'd1', title: 'Rechnung Wärme', file_url: '/uploads/documents/rechnung.pdf' },
  filename: 'rechnung.pdf', sha256: 'a'.repeat(64), document_revision: 'b'.repeat(64),
  inspection: { format: 'pdf' }, version: null, annotations: [], layer_revision: 0 };
const close = vi.fn();
const routers = [];
afterEach(() => { routers.splice(0).forEach(router => router.dispose()); });
beforeEach(() => {
  vi.clearAllMocks(); mocks.canWrite = true;
  mocks.get.mockImplementation(path => Promise.resolve(path.endsWith('/source') ? SOURCE : { items: [], next_after: null }));
});

async function openDocx({ routedClose = false } = {}) {
  const saved = { session_id: 'docx-session', mode: 'docx', filename: 'vertrag.docx', version_id: 'v1', revision: 's1',
    sha256: SOURCE.sha256, document_revision: SOURCE.document_revision };
  mocks.get.mockImplementation(path => Promise.resolve(path.endsWith('/source')
    ? { ...SOURCE, filename: 'vertrag.docx', inspection: { format: 'docx' }, version: { id: 'v1', number: 1 } }
    : path.includes('/sessions/') ? saved : { items: [], next_after: null }));
  mocks.getBlob.mockResolvedValue(new Blob(['native docx']));
  mocks.post.mockImplementation(async path => {
    if (path.endsWith('/sessions')) return saved;
    return { ...saved, revision: 's2' };
  });
  mocks.mountEditor.mockImplementation((host, _file, callbacks) => {
    const field = document.createElement('textarea');
    field.setAttribute('aria-label', 'Native DOCX input');
    host.appendChild(field);
    callbacks.onReady();
    return { destroy: () => { mocks.destroyEditor(); field.remove(); }, suggesting: vi.fn(),
      exportDocx: async () => new Blob([field.value]) };
  });
  if (routedClose) {
    const router = createMemoryRouter([{ path: '/work', element: <NavigationProtectionProvider>
      <DocumentWorkbench documentId="d1" onClose={() => router.navigate('/closed')} />
    </NavigationProtectionProvider> }, { path: '/closed', element: <h1>Workbench closed</h1> }], { initialEntries: ['/work'] });
    routers.push(router);
    render(<RouterProvider router={router} />);
  } else render(<DocumentWorkbench documentId="d1" onClose={close} />);
  fireEvent.click(await screen.findByRole('button', { name: 'DOCX im lokalen Editor öffnen' }));
  const input = await screen.findByRole('textbox', { name: 'Native DOCX input' });
  await screen.findByText('Bearbeitung bereit.');
  fireEvent.change(input, { target: { value: 'Unsaved contract paragraph' } });
  return { input, saved };
}

it('guards local workbench tab changes and preserves the same native editor when kept', async () => {
  const { input } = await openDocx();
  fireEvent.click(screen.getByRole('button', { name: 'Fassungen und Wiederanlauf' }));
  expect(screen.getByRole('group', { name: 'DOCX-Editor verlassen' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Weiter bearbeiten' }));
  expect(screen.getByRole('textbox', { name: 'Native DOCX input' })).toBe(input);
  expect(input).toHaveValue('Unsaved contract paragraph');
  expect(mocks.destroyEditor).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Fassungen und Wiederanlauf' }));
  fireEvent.click(screen.getByRole('button', { name: 'Ohne weiteres Sichern verlassen' }));
  expect(await screen.findByRole('heading', { name: 'Archivfassungen' })).toBeInTheDocument();
  expect(mocks.destroyEditor).toHaveBeenCalledOnce();
});

it('does not ask twice when a locally confirmed DOCX close navigates the workbench route', async () => {
  await openDocx({ routedClose: true });
  fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Ohne weiteres Sichern verlassen' }));
  expect(await screen.findByRole('heading', { name: 'Workbench closed' })).toBeInTheDocument();
});

it('rechecks parent commands started after the DOCX leave question before honoring its local close', async () => {
  const { saved } = await openDocx();
  fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
  let finish;
  mocks.post.mockImplementation(path => path.endsWith('/exports') ? new Promise(resolve => { finish = resolve; }) : Promise.resolve(saved));
  fireEvent.click(screen.getByRole('button', { name: 'Ausgabeauftrag anlegen' }));
  await waitFor(() => expect(finish).toBeTypeOf('function'));
  fireEvent.click(screen.getByRole('button', { name: 'Ohne weiteres Sichern verlassen' }));
  expect(close).not.toHaveBeenCalled();
  expect(screen.getByRole('textbox', { name: 'Native DOCX input' })).toHaveValue('Unsaved contract paragraph');
  await act(async () => { finish({ job_id: 'job', state: 'pending', outputs: [] }); });
  fireEvent.click(screen.getByRole('button', { name: 'Ohne weiteres Sichern verlassen' }));
  expect(close).toHaveBeenCalledOnce();
});

it('holds local workbench tab changes and close while a DOCX save is unresolved', async () => {
  const { input, saved } = await openDocx();
  let finish;
  mocks.post.mockImplementation(path => path.endsWith('/docx') ? new Promise(resolve => { finish = resolve; }) : Promise.resolve(saved));
  fireEvent.click(screen.getByRole('button', { name: 'Zwischenstand sichern' }));
  await waitFor(() => expect(finish).toBeTypeOf('function'));
  fireEvent.click(screen.getByRole('button', { name: 'Rechnung übernehmen' }));
  expect(screen.getByRole('alert')).toHaveTextContent('Ein Speicherauftrag läuft noch');
  expect(screen.getByRole('textbox', { name: 'Native DOCX input' })).toBe(input);
  fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
  expect(close).not.toHaveBeenCalled();
  expect(mocks.destroyEditor).not.toHaveBeenCalled();
  await act(async () => { finish({ ...saved, revision: 's2' }); });
  expect(screen.getByRole('textbox', { name: 'Native DOCX input' })).toBe(input);
  fireEvent.click(screen.getByRole('button', { name: 'Rechnung übernehmen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Ohne weiteres Sichern verlassen' }));
  expect(screen.queryByRole('textbox', { name: 'Native DOCX input' })).not.toBeInTheDocument();
});

it('retains the exact archive command after a lost reply and retries with its original key', async () => {
  mocks.post.mockRejectedValueOnce(new Error('Antwort verloren')).mockResolvedValueOnce({ version: { id: 'v1' } });
  render(<DocumentWorkbench documentId="d1" onClose={close} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Original jetzt archivieren' }));
  await screen.findByText('Antwort verloren');
  const first = mocks.post.mock.calls[0];
  expect(first[1]).toMatchObject({ expected_version: null, expected_sha256: 'a'.repeat(64), expected_document_revision: 'b'.repeat(64) });
  expect(first[1].command_key).toMatch(/^[\da-f-]{36}$/);
  fireEvent.click(screen.getByRole('button', { name: 'Denselben Auftrag wiederholen' }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
  expect(mocks.post.mock.calls[1]).toEqual(first);
});

it('keeps a pending workbench command mounted on local close and tab changes, including an uncertain reply', async () => {
  let reject;
  mocks.post.mockImplementation(() => new Promise((_resolve, fail) => { reject = fail; }));
  render(<DocumentWorkbench documentId="d1" onClose={close} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Original jetzt archivieren' }));
  fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
  expect(close).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Fassungen und Wiederanlauf' }));
  expect(screen.getByRole('button', { name: 'Bearbeiten', pressed: true })).toBeInTheDocument();
  await act(async () => { reject(new Error('Antwort verloren')); });
  fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
  expect(close).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Denselben Auftrag wiederholen' })).toBeInTheDocument();
});

it('keeps tools read-only without current write permission', async () => {
  mocks.canWrite = false;
  render(<DocumentWorkbench documentId="d1" onClose={close} />);
  expect(await screen.findByRole('button', { name: 'Original jetzt archivieren' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Original jetzt archivieren' }));
  expect(mocks.post).not.toHaveBeenCalled();
});

it('closes its document on session change', async () => {
  render(<DocumentWorkbench documentId="d1" onClose={close} />);
  await screen.findByText('Datei: rechnung.pdf · Noch nicht archiviert');
  act(() => window.dispatchEvent(new CustomEvent('workspace-logout')));
  expect(close).toHaveBeenCalledTimes(1);
});

it('does not expose a source when the captured session rejects a late response', async () => {
  mocks.current.mockImplementationOnce(() => { throw new Error('Sitzung geändert'); });
  render(<DocumentWorkbench documentId="d1" onClose={close} />);
  await screen.findByText('Sitzung geändert');
  expect(screen.queryByText('Rechnung Wärme', { exact: true })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Original jetzt archivieren' })).not.toBeInTheDocument();
});

it('requires reviewed field origins and carries decimal strings plus VAT and Skonto to the existing review receipt', async () => {
  const perform = vi.fn();
  render(<InvoiceTakeover source={SOURCE} proposal={{ proposal_id: 'p1', source_sha256: SOURCE.sha256,
    observed: { supplier: 'OCR-Lieferant', total_amount: '119,00', invoice_number: 'R-1', invoice_date: '2026-10-01' } }}
    perform={perform} disabled={false} base="/documents/d1/work" />);
  expect(screen.getByRole('button', { name: 'Als Rechnungsentwurf übernehmen' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Nettobetrag (€)'), { target: { value: '100,00' } });
  fireEvent.change(screen.getByLabelText('Umsatzsteuerbetrag (€)'), { target: { value: '19,00' } });
  fireEvent.change(screen.getByLabelText('Skonto (%)'), { target: { value: '2' } });
  fireEvent.change(screen.getByLabelText('Skontofrist (Tage)'), { target: { value: '10' } });
  for (const select of screen.getAllByLabelText('Herkunft bestätigen')) fireEvent.change(select, { target: { value: 'manual_correction' } });
  fireEvent.click(screen.getByLabelText('Ich habe die Angaben mit dem Original verglichen.'));
  fireEvent.click(screen.getByRole('button', { name: 'Als Rechnungsentwurf übernehmen' }));
  expect(perform).toHaveBeenCalledTimes(1);
  const payload = perform.mock.calls[0][1];
  expect(payload.receipt.invoice).toMatchObject({ net_amount: '100.00', vat_amount: '19.00', gross_amount: '119.00' });
  expect(payload.receipt).toMatchObject({ skonto_percent: '2', skonto_days: 10, vat_lines: [{ rate: '19', net: '100.00', vat: '19.00' }] });
  expect(payload.confirmed).toBe(true);
  expect(Object.keys(payload.field_sources)).toHaveLength(7);
});

describe('human page selection', () => {
  it('preserves explicit ordering, extraction ranges and duplicate pages', () => {
    expect(pageNumbers('3,1-2,3')).toEqual([2, 0, 1, 2]);
  });
  it.each(['0', '2-1', 'NaN', '1;2', '1.5', ''])('refuses ambiguous selection %s', value => {
    expect(() => pageNumbers(value)).toThrow();
  });
});
