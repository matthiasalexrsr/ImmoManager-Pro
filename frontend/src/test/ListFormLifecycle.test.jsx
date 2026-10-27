import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../api';
import { workspace } from '../utils/workspaceClient';
import { DataStoreProvider } from '../contexts/DataStoreContext';
import Tenants from '../pages/Tenants';
import Properties from '../pages/Properties';
import Contacts from '../pages/Contacts';
import CrudPage from '../pages/CrudPage';

vi.mock('../api', () => ({ api: { list: vi.fn(), get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'owner', role: 'eigentuemer' } }), useCanWrite: () => true }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => ({
  'ui.buttons.new': 'Neu', 'ui.buttons.edit': 'Bearbeiten', 'ui.buttons.create': 'Erstellen',
  'ui.buttons.save': 'Speichern', 'ui.buttons.cancel': 'Abbrechen', 'ui.buttons.close': 'Schließen',
}[key] || ''), locale: 'de-DE' }) }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn(), success: vi.fn() }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../components/DuplicateHints', () => ({ default: () => null }));
vi.mock('../features/partyWorkspace/PartyWorkspace', () => ({ PartyLink: ({ children }) => <button>{children}</button>, usePartyWorkspace: () => ({ openParty: vi.fn() }) }));
vi.mock('../utils/workspaceClient', async original => ({ ...await original(), workspace: {
  list: vi.fn(), get: vi.fn(), put: vi.fn(), remove: vi.fn(), rebase: vi.fn(), command: () => crypto.randomUUID(),
} }));

const revision = '2026-10-15T09:00:00Z';
const deferred = () => { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const categories = <CrudPage title="Kategorien" endpoint="/categories" columns={[{ key: 'name', label: 'Name' }]}
  formFields={[{ key: 'name', label: 'Name', required: true }]} />;
beforeEach(() => { vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear(); });
afterEach(() => { cleanup(); window.history.replaceState({}, '', '/'); });

async function prepare({ context, element, rows = [], kind, values, create = false }) {
  const reload = deferred(); const deletion = deferred(); let saved = false; let deleted = false;
  const endpoint = context === 'tenants' ? '/tenants?include_archived=true' : `/${context}`;
  const lookup = { '/properties': [{ id: 'p1', name: 'Haus', portfolio_id: 'p', property_type: 'residential' }],
    '/portfolios': [{ id: 'p', name: 'Bestand' }], '/units': [], '/contracts': [], '/maintenance': [] };
  api.list.mockImplementation(async path => saved && (path === endpoint || path === '/contracts') ? reload.promise : path === endpoint ? rows : lookup[path] || []);
  const accept = async () => { saved = true; return { id: 'accepted' }; };
  api.put.mockImplementation(accept); api.post.mockImplementation(accept);
  workspace.list.mockImplementation(async (resource, query) => ({ items: resource === 'drafts' && query.context === context && !deleted ? [{
    id: 'draft', revision: 1, context, form_key: query.form_key, values,
    source: create ? null : { kind, id: rows[0].id, revision }, source_state: { status: 'current' },
  }] : [], next_cursor: null }));
  workspace.get.mockResolvedValue({});
  workspace.put.mockImplementation(async (_resource, id, body) => ({ id, ...body, revision: body.base_revision + 1 }));
  workspace.remove.mockImplementation(async () => { await deletion.promise; deleted = true; return { deleted: true }; });
  window.history.replaceState({}, '', `/${context}`);
  await act(async () => { render(<MemoryRouter initialEntries={[`/${context}`]}><DataStoreProvider>{element}</DataStoreProvider></MemoryRouter>); });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: create ? 'Neu' : 'Bearbeiten' })); });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Entwurf wiederaufnehmen' })); });
  return { reload, deletion, dialog: screen.getByRole('dialog') };
}

it.each([
  { context: 'tenants', kind: 'tenant', element: <Tenants />, rows: [{ id: 't1', full_name: 'Alt', updated_at: revision }], values: { full_name: 'Neu' } },
  { context: 'properties', kind: 'property', element: <Properties />, rows: [{ id: 'p1', name: 'Alt', portfolio_id: 'p', property_type: 'residential', updated_at: revision }], values: { name: 'Neu', portfolio_id: 'p', property_type: 'residential' } },
  { context: 'categories', kind: 'category', element: categories, rows: [], values: { name: 'Neu' }, create: true },
])('keeps the $context form mounted through source refresh and draft deletion, then closes once', async fixture => {
  const { reload, deletion, dialog } = await prepare(fixture);
  await act(async () => { fireEvent.click(within(dialog).getByRole('button', { name: 'Speichern' })); });
  expect(screen.getByRole('dialog')).toBe(dialog);
  expect(workspace.remove).toHaveBeenCalledOnce();
  await act(async () => { reload.resolve([{ ...(fixture.rows[0] || { id: 'new' }), ...fixture.values }]); });
  expect(screen.getByRole('dialog')).toBe(dialog);
  await act(async () => { deletion.resolve(); });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect([...Object.keys(localStorage)].filter(key => key.includes('draft-buffer:'))).toEqual([]);
  expect(api.post.mock.calls.length + api.put.mock.calls.length).toBe(1);
});

it('lets draft cleanup finish before presenting a failed generic-list refresh', async () => {
  const { reload, deletion, dialog } = await prepare({ context: 'categories', element: categories, values: { name: 'Neu' }, create: true });
  await act(async () => { fireEvent.click(within(dialog).getByRole('button', { name: 'Speichern' })); });
  await act(async () => { reload.reject(new Error('Quelle offline')); });
  expect(screen.getByRole('dialog')).toBe(dialog);
  await act(async () => { deletion.resolve(); });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByText('Quelle offline')).toBeInTheDocument();
  expect(workspace.remove).toHaveBeenCalledOnce();
});

it('keeps save-and-new mounted, clears its draft and retains only the chosen contact role', async () => {
  const { reload, deletion, dialog } = await prepare({ context: 'contacts', element: <Contacts />, rows: [],
    values: { first_name: 'Anna', contact_type: 'supplier' }, create: true });
  await act(async () => { fireEvent.click(within(dialog).getByRole('button', { name: 'Speichern & weiteren' })); });
  expect(screen.getByRole('dialog')).toBe(dialog);
  await act(async () => { reload.resolve([{ id: 'new', first_name: 'Anna', contact_type: 'supplier' }]); deletion.resolve(); });
  expect(screen.getByRole('dialog')).toBe(dialog);
  expect(screen.getByLabelText('Vorname')).toHaveValue('');
  expect(screen.getByLabelText('Rolle *')).toHaveValue('supplier');
  expect(workspace.remove).toHaveBeenCalledOnce();
  expect([...Object.keys(localStorage)].filter(key => key.includes('draft-buffer:'))).toEqual([]);
  expect(api.post).toHaveBeenCalledTimes(1);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Abbrechen' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
