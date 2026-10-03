import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import german from '../../../i18n/de-DE.json';
import Documents from '../pages/Documents';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getBlob: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), user: null }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
vi.mock('../components/FileViewer', () => ({ default: ({ fileUrl }) => <div role="dialog">Dateiansicht {fileUrl}</div> }));
vi.mock('../components/DocumentVersionHistory', () => ({ default: ({ document }) => <div role="dialog">Versionen {document.title}</div> }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE', t: key => key.split('.').reduce((value, part) => value?.[part], german) || key }) }));
const doc = (id = 'document-a', title = 'Private Rechnung') => ({ id, title, property_id: 'property-a', unit_id: 'unit-a', contract_id: 'contract-a',
  document_type: 'Rechnung', property_name: 'Lindenhof', unit_label: 'Gartenwohnung', contract_label: 'MV-101',
  file_url: '/uploads/private.pdf', ai_analyzed_at: null, document_date: '2026-01-01', tags: null,
  updated_at: '2026-10-03T00:00:00.000001Z', edit_etag: 'doc-revision' });
const page = (items, cursor = null) => ({ items, has_more: Boolean(cursor), next_cursor: cursor });
const totals = { total: 10001, with_file: 9999, analyzed: 301, no_assignment: 12 };
const draftPath = '/auth/users/me/form-drafts';
const draftSaved = { revision: 'draft-a', updated_at: '2026-10-03T00:00:00Z', expires_at: '2026-10-10T00:00:00Z' };
const writes = () => mocks.put.mock.calls.filter(([path]) => path.startsWith('/documents/'));
const response = path => path.startsWith(draftPath) ? { draft: null } : path.includes('/summary?') ? totals : path.startsWith('/workflow-references/')
  ? { ...page([{ id: 'property-a', name: 'Lindenhof' }]), selected: { id: 'selected', name: 'Bestehende Zuordnung' } }
  : path.startsWith('/documents/inventory/') ? page([doc()]) : { ...doc(), description: 'Vollständiger Beschreibungstext' };
const view = () => render(<MemoryRouter><Documents /></MemoryRouter>);
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

beforeEach(() => {
  Object.values(mocks).forEach(value => value?.mockReset?.());
  mocks.user = { id: 'owner', role: 'eigentuemer', portfolio_access: 'all', portfolio_ids: [] };
  mocks.get.mockImplementation(path => Promise.resolve(response(path)));
  mocks.put.mockImplementation(path => Promise.resolve(path === draftPath ? draftSaved : {}));
  mocks.del.mockResolvedValue({ discarded: true });
});

describe('bounded document list and retained document workflows', () => {
  it('shows full counts and real analysis evidence without inventing OCR processing', async () => {
    view(); await screen.findByRole('button', { name: 'Private Rechnung', exact: true });
    expect(screen.getByRole('region', { name: 'Kennzahlen der gefilterten Dokumente' })).toHaveTextContent('10001');
    expect(screen.getByRole('table')).toHaveTextContent('Keine Analyse gespeichert');
    expect(screen.getByRole('table')).not.toHaveTextContent('Läuft');
    expect(screen.getByRole('table')).toHaveTextContent('MV-101');
    expect(mocks.get.mock.calls.every(([path]) => path.includes('/inventory/') || path.includes('/workflow-references/'))).toBe(true);
  });

  it('filters and pages from the server while complete counts stay independent', async () => {
    mocks.get.mockImplementation(path => Promise.resolve(path.includes('/page?') ? path.includes('cursor=later')
      ? page([doc('document-b', 'Späteres Dokument')]) : page([doc()], 'later') : response(path)));
    view(); await screen.findByRole('button', { name: 'Private Rechnung', exact: true });
    fireEvent.change(screen.getByRole('searchbox', { name: 'Dokumente durchsuchen' }), { target: { value: 'Rechnung 10001' } });
    await screen.findByRole('button', { name: 'Private Rechnung', exact: true });
    await userEvent.click(screen.getByRole('button', { name: 'Nächste Seite', exact: true }));
    expect(await screen.findByRole('button', { name: 'Späteres Dokument', exact: true })).toBeVisible();
    expect(mocks.get.mock.calls.at(-1)[0]).toContain('search=Rechnung+10001');
    expect(mocks.get.mock.calls.at(-1)[0]).toContain('cursor=later');
  });

  it('retains filter input when reads fail and does not claim empty inventory', async () => {
    mocks.get.mockImplementation(path => path.includes('/page?') ? Promise.reject(new Error('Dokumentserver nicht erreichbar')) : Promise.resolve(response(path)));
    view(); await screen.findByText('Dokumentserver nicht erreichbar');
    fireEvent.change(screen.getByRole('searchbox', { name: 'Dokumente durchsuchen' }), { target: { value: 'Aufbewahrt' } });
    expect(await screen.findByText('Dokumentserver nicht erreichbar')).toBeVisible();
    expect(screen.getByRole('searchbox', { name: 'Dokumente durchsuchen' })).toHaveValue('Aufbewahrt');
    expect(screen.queryByText('Keine passenden Dokumente auf dieser Seite.')).not.toBeInTheDocument();
  });

  it('keeps file and version actions reachable', async () => {
    const first = view(); await screen.findByRole('button', { name: 'Private Rechnung', exact: true });
    await userEvent.click(screen.getByRole('button', { name: 'Private Rechnung', exact: true }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Dateiansicht /uploads/private.pdf');
    first.unmount(); view(); await screen.findByRole('button', { name: 'Private Rechnung Versionshistorie' });
    await userEvent.click(screen.getByRole('button', { name: 'Private Rechnung Versionshistorie' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Versionen Private Rechnung');
  });

  it('reads the exact full document before editing and preserves its failed draft and revision', async () => {
    mocks.put.mockImplementation(path => path === draftPath ? Promise.resolve(draftSaved) : Promise.reject(new Error('Dokument konnte nicht gespeichert werden')));
    view(); await screen.findByRole('button', { name: 'Private Rechnung bearbeiten' });
    await userEvent.click(screen.getByRole('button', { name: 'Private Rechnung bearbeiten' }));
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByText('Entwurfsschutz bereit');
    expect(mocks.get.mock.calls.some(([path]) => path === '/documents/document-a')).toBe(true);
    expect(within(dialog).getByLabelText('Beschreibung')).toHaveValue('Vollständiger Beschreibungstext');
    fireEvent.change(within(dialog).getByLabelText('Titel *'), { target: { value: 'Erhaltener Entwurf' } });
    fireEvent.submit(dialog.querySelector('form'));
    expect(await within(dialog).findByText('Dokument konnte nicht gespeichert werden')).toBeVisible();
    expect(within(dialog).getByLabelText('Titel *')).toHaveValue('Erhaltener Entwurf');
    expect(writes()[0][1]).toMatchObject({ property_id: 'property-a', unit_id: 'unit-a', contract_id: 'contract-a', description: 'Vollständiger Beschreibungstext' });
    expect(writes()[0][2].ifMatch.updatedAt).toBe(doc().updated_at);
  });

  it.each(['user', 'scope', 'role'])('removes previous document names immediately on %s change', async kind => {
    const rendered = view(); await screen.findByRole('button', { name: 'Private Rechnung', exact: true });
    const old = mocks.get.mock.calls[0][1].signal;
    mocks.get.mockReturnValue(new Promise(() => {}));
    if (kind === 'user') mocks.user = { ...mocks.user, id: 'other' };
    if (kind === 'scope') mocks.user = { ...mocks.user, portfolio_ids: ['other'] };
    if (kind === 'role') mocks.user = { ...mocks.user, role: 'readonly' };
    rendered.rerender(<MemoryRouter><Documents /></MemoryRouter>);
    expect(screen.queryByText('Private Rechnung')).not.toBeInTheDocument();
    expect(old.aborted).toBe(true);
  });

  it('drops a late old document page after a filter change', async () => {
    const old = deferred(); mocks.get.mockImplementation(path => path.includes('/page?') && !path.includes('search=') ? old.promise : Promise.resolve(response(path)));
    view(); fireEvent.change(screen.getByRole('searchbox', { name: 'Dokumente durchsuchen' }), { target: { value: 'Neu' } });
    await screen.findByRole('button', { name: 'Private Rechnung', exact: true });
    await act(async () => old.resolve(page([doc('old', 'Alter privater Titel')])));
    expect(screen.queryByText('Alter privater Titel')).not.toBeInTheDocument();
  });

  it('exports the full query and surfaces failure while preserving filters', async () => {
    mocks.getBlob.mockRejectedValue(new Error('CSV unterbrochen'));
    view(); await screen.findByRole('button', { name: 'Private Rechnung', exact: true });
    fireEvent.change(screen.getByRole('searchbox', { name: 'Dokumente durchsuchen' }), { target: { value: 'Steuer' } });
    await userEvent.click(screen.getByRole('button', { name: 'Alle gefilterten Dokumente exportieren' }));
    expect(await screen.findByText('CSV unterbrochen')).toBeVisible();
    expect(mocks.getBlob.mock.calls[0][0]).toContain('search=Steuer');
    expect(mocks.getBlob.mock.calls[0][0]).not.toContain('cursor=');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Alle gefilterten Dokumente exportieren' })).toBeEnabled());
  });
});
