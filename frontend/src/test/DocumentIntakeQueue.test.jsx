import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../api';
import DocumentIntakeQueue from '../features/workCenter/DocumentIntakeQueue';
import DuplicateFinder from '../features/workCenter/DuplicateFinder';

const access = vi.hoisted(() => ({ canWrite: true }));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => null, useCanWrite: () => access.canWrite }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null, useEntities: key => ({ items: key === 'properties' ? [{ id: 'p1', name: 'Nordhaus' }, { id: 'p2', name: 'Südhaus' }] : [] }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key }) }));
vi.mock('../components/FileViewer', () => ({ default: () => null }));
const revision = '2026-10-15T09:00:00Z';
const source = { id: 'd1', title: 'Heizung', document_type: 'Sonstiges', file_url: '/uploads/heizung.pdf', updated_at: revision };
const rows = [
  { document_id: 'd1', title: 'Heizung', status: 'pending', document_revision: revision, revision, can_process: true },
  { document_id: 'd2', title: 'Wasser', status: 'failed', document_revision: revision, revision, can_process: true },
];
const detail = { document: source, intake: { ...rows[0], status: 'review', can_review: true,
  result: { document_type: 'Rechnung', summary: 'Erkannte Heizungsrechnung' } } };
const show = (content = <DocumentIntakeQueue />, path = '/document-queue') => render(<MemoryRouter initialEntries={[path]}>{content}</MemoryRouter>);
beforeEach(() => {
  vi.resetAllMocks(); access.canWrite = true;
  api.get.mockImplementation(path => Promise.resolve(path === '/work-center/documents/d1' ? detail : path === '/documents/d1' ? source : path.startsWith('/documents?') ? [source] : { items: rows, next_cursor: null }));
  api.list.mockResolvedValue([source]); api.post.mockResolvedValue({});
});
afterEach(cleanup);

describe('document intake with explicit review', () => {
  it('reports partial analysis failures and retains only failed documents in the selection', async () => {
    api.post.mockImplementation(async path => { if (path.includes('/d2/process')) throw new Error('Datei nicht lesbar'); return { intake: { status: 'review' } }; });
    show();
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Auswählen: Heizung' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Auswählen: Wasser' }));
    fireEvent.click(screen.getByRole('button', { name: 'Auswahl analysieren (2)' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('1 analysiert · 1 fehlgeschlagen');
    expect(screen.getByRole('alert')).toHaveTextContent('Wasser: Datei nicht lesbar');
    expect(screen.getByRole('checkbox', { name: 'Auswählen: Heizung' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Auswählen: Wasser' })).toBeChecked();
    expect(api.post.mock.calls.every(([path]) => path.endsWith('/process'))).toBe(true);
  });

  it('treats OCR as a proposal and retains edited metadata after a revision conflict', async () => {
    api.post.mockRejectedValue(Object.assign(new Error('Dokument wurde inzwischen geändert'), { statusCode: 409 }));
    show();
    await screen.findByText('Heizung');
    fireEvent.click(screen.getAllByRole('button', { name: 'Vorschläge prüfen' })[0]);
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByLabelText('Dokumententyp')).toHaveValue('Rechnung');
    expect(within(dialog).getByLabelText('Inhalt / Erkennungsvorschlag')).toHaveValue('Erkannte Heizungsrechnung');
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText('Titel *'), { target: { value: 'Heizung Oktober geprüft' } });
    fireEvent.submit(dialog.querySelector('form'));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('inzwischen geändert');
    expect(within(dialog).getByLabelText('Titel *')).toHaveValue('Heizung Oktober geprüft');
    expect(api.post).toHaveBeenCalledWith('/work-center/documents/d1/review', expect.objectContaining({
      base_revision: revision, document_revision: revision,
      changes: expect.objectContaining({ title: 'Heizung Oktober geprüft', document_type: 'Rechnung' }),
    }));
  });

  it('offers revision-checked metadata undo without hiding a newer-change conflict', async () => {
    const savedRevision = '2026-10-15T10:00:00Z';
    api.post.mockResolvedValueOnce({ document: source, revision: savedRevision, undo_id: 'document-undo' })
      .mockRejectedValueOnce(Object.assign(new Error('Dokument wurde erneut bearbeitet'), { statusCode: 409 }));
    show();
    await screen.findByText('Heizung');
    fireEvent.click(screen.getAllByRole('button', { name: 'Vorschläge prüfen' })[0]);
    const dialog = await screen.findByRole('dialog');
    fireEvent.submit(dialog.querySelector('form'));
    fireEvent.click(await screen.findByRole('button', { name: 'Rückgängig' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Dokument wurde erneut bearbeitet');
    expect(screen.getByRole('alert')).toHaveTextContent('Ihre Änderung bleibt bestehen.');
    expect(api.post).toHaveBeenLastCalledWith('/work-center/quick-edits/document-undo/undo', expect.objectContaining({ base_revision: savedRevision }));
  });

  it('reports persisted analysis failure even when the process request itself returns successfully', async () => {
    api.post.mockResolvedValue({ intake: { status: 'failed', error: 'Kein Text extrahierbar' } });
    show();
    await screen.findByText('Heizung');
    fireEvent.click(screen.getAllByRole('button', { name: 'Analysieren' })[0]);
    expect(await screen.findByRole('alert')).toHaveTextContent('0 analysiert · 1 fehlgeschlagen');
    expect(screen.getByRole('alert')).toHaveTextContent('Kein Text extrahierbar');
  });

  it('offers safe continuation when the previous worker lease has expired', async () => {
    api.get.mockResolvedValue({ items: [{ ...rows[0], status: 'processing', lease_expired: true }], next_cursor: null });
    api.post.mockResolvedValue({ intake: { status: 'review' } });
    show();
    fireEvent.click(await screen.findByRole('button', { name: 'Analyse fortsetzen' }));
    expect(await screen.findByText('1 analysiert')).toBeInTheDocument();
    expect(api.post).toHaveBeenCalledWith('/work-center/documents/d1/process', expect.objectContaining({ base_revision: revision }));
  });

  it('shows review information to readers without analysis or metadata write controls', async () => {
    access.canWrite = false;
    show();
    await screen.findByText('Heizung');
    expect(screen.queryByRole('button', { name: 'Analysieren' })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'Vorschläge prüfen' })[0]);
    const dialog = await screen.findByRole('dialog', { name: 'Dokumentvorschläge' });
    expect(within(dialog).getByText('Erkannte Heizungsrechnung')).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: 'Speichern' })).not.toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('continues across cursor pages and carries only opted-in assignments to unassigned documents', async () => {
    const nextRows = [{ ...rows[1], status: 'review' }, { ...rows[1], document_id: 'd3', title: 'Strom', status: 'review' }];
    api.get.mockImplementation(async path => {
      if (path === '/work-center/documents/d1') return detail;
      if (path === '/work-center/documents/d2') return { ...detail, document: { ...source, id: 'd2', title: 'Wasser', description: 'Eigene Beschreibung' } };
      if (path === '/work-center/documents/d3') return { ...detail, document: { ...source, id: 'd3', title: 'Strom', property_id: 'p2' } };
      if (path.includes('cursor=page-2')) return { items: nextRows, next_cursor: null };
      return { items: [rows[0]], next_cursor: 'page-2' };
    });
    show();
    fireEvent.click(await screen.findByRole('button', { name: 'Vorschläge prüfen' }));
    let dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Titel *'), { target: { value: 'Einmaliger Titel' } });
    fireEvent.change(within(dialog).getByLabelText('Immobilie'), { target: { value: 'p1' } });
    fireEvent.click(within(dialog).getByRole('checkbox', { name: /Zuordnung für den nächsten/ }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Speichern & nächster Beleg' }));
    dialog = await screen.findByRole('dialog', { name: 'Dokument prüfen · Wasser' });
    expect(within(dialog).getByLabelText('Titel *')).toHaveValue('Wasser');
    expect(within(dialog).getByLabelText('Immobilie')).toHaveValue('p1');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Speichern & nächster Beleg' }));
    dialog = await screen.findByRole('dialog', { name: 'Dokument prüfen · Strom' });
    expect(within(dialog).getByLabelText('Immobilie')).toHaveValue('p2');
    expect(api.get.mock.calls.filter(([path]) => path.includes('cursor=page-2'))).toHaveLength(1);
    expect(api.post.mock.calls.filter(([path]) => path.endsWith('/review')).map(([path]) => path))
      .toEqual(['/work-center/documents/d1/review', '/work-center/documents/d2/review']);
  });

  it('retries next-document loading without submitting the already saved document again', async () => {
    let failNext = true;
    api.get.mockImplementation(async path => {
      if (path === '/work-center/documents/d1') return detail;
      if (path === '/work-center/documents/d2') {
        if (failNext) throw new Error('Nächste Datei offline');
        return { ...detail, document: { ...source, id: 'd2', title: 'Wasser' } };
      }
      return { items: rows, next_cursor: null };
    });
    show();
    await screen.findByText('Heizung');
    fireEvent.click(screen.getAllByRole('button', { name: 'Vorschläge prüfen' })[0]);
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Speichern & nächster Beleg' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Der vorherige Beleg ist gespeichert. Nächste Datei offline');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    failNext = false;
    fireEvent.click(screen.getByRole('button', { name: 'Nächsten Beleg erneut laden' }));
    expect(await screen.findByRole('dialog', { name: 'Dokument prüfen · Wasser' })).toBeInTheDocument();
    expect(api.post).toHaveBeenCalledTimes(1);
  });
});

describe('duplicate evidence and justified exceptions', () => {
  it('makes incomplete hash coverage explicit even when no duplicate was found', async () => {
    api.post.mockResolvedValue({ items: [], next_cursor: null, coverage: {
      indexed_count: 2, unindexed_count: 3, complete: false, note: 'Drei Dateien sind noch nicht analysiert.', pending_href: '/document-queue?status=pending',
    } });
    show(<DuplicateFinder />, '/duplicate-check?kind=file&id=d1');
    expect(await screen.findByRole('alert')).toHaveTextContent('Drei Dateien sind noch nicht analysiert.');
    expect(screen.getByRole('link', { name: 'Offene Dateien analysieren' })).toHaveAttribute('href', '/document-queue?status=pending');
    expect(screen.getByText('In den bisher geprüften Inhalten wurde keine Übereinstimmung gefunden.')).toBeInTheDocument();
    expect(screen.queryByText('Keine Übereinstimmungen gefunden.')).not.toBeInTheDocument();
  });
  it('checks the selected file and saves a reasoned exception with both source revisions', async () => {
    const match = { entity_id: 'd2', title: 'Heizung Kopie', href: '/documents?suche=Heizung', revision, reason: 'Identischer Dateiinhalt', confidence: 1 };
    api.post.mockImplementation(async (path, body) => path.endsWith('/check') ? { items: [match], next_cursor: null, fingerprint: 'sha256:abc' } : { exception: { reason: body.reason } });
    show(<DuplicateFinder />, '/duplicate-check?kind=file&id=d1');
    expect(await screen.findByRole('link', { name: 'Heizung Kopie' })).toHaveAttribute('href', '/documents?suche=Heizung');
    expect(api.post).toHaveBeenCalledWith('/work-center/duplicates/check', expect.objectContaining({ kind: 'file', candidate: { document_id: 'd1' }, exclude_id: 'd1' }), expect.anything());
    fireEvent.click(screen.getByRole('button', { name: 'Bewusst getrennt lassen' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Begründung *'), { target: { value: 'Original und bestätigte Kopie für unterschiedliche Akten' } });
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/work-center/duplicates/exceptions', expect.objectContaining({
      kind: 'file', entity_id: 'd1', duplicate_id: 'd2', base_revision: revision, duplicate_revision: revision,
      reason: 'Original und bestätigte Kopie für unterschiedliche Akten', idempotency_key: expect.any(String),
    })));
    expect(api.del).not.toHaveBeenCalled();
  });
});
