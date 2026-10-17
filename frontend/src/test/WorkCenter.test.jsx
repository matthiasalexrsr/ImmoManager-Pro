import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { api } from '../api';
import EntityTimeline from '../features/workCenter/EntityTimeline';
import EntityActions from '../features/workCenter/EntityActions';
import EntityShelf from '../features/workCenter/EntityShelf';
import InlineFieldEditor from '../features/workCenter/InlineFieldEditor';
import UndoNotice from '../features/workCenter/UndoNotice';
import WorkSummary from '../features/workCenter/WorkSummary';
import WorkCenter from '../features/workCenter/WorkCenter';
import DeferralControl from '../features/workCenter/DeferralControl';

const auth = vi.hoisted(() => ({ user: { id: 'u1' }, write: null }));
vi.mock('../api', () => ({ api: { captureSession: vi.fn(), get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth, useCanWrite: () => auth.write === null }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => null, useEntities: () => ({ items: [] }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));
const deferred = () => { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const empty = () => ({ items: [], next_cursor: null });
const missing = () => Object.assign(new Error('Nicht vorhanden'), { statusCode: 404 });
const rev1 = '2026-10-15T09:00:00Z';
const rev2 = '2026-10-15T09:01:00Z';
const event = (id, title) => ({ id, title, occurred_at: rev1, kind: 'note', body: 'Gespräch geführt', actor: 'Anna' });
const show = (content, path = '/') => render(<MemoryRouter initialEntries={[path]}>{content}</MemoryRouter>);

beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); auth.user = { id: 'u1' }; auth.write = null;
  api.captureSession.mockReturnValue(() => {});
  api.get.mockImplementation(path => path.startsWith('/workspace/favorites/') ? Promise.reject(missing()) : Promise.resolve(empty()));
  api.list.mockResolvedValue([]); api.post.mockResolvedValue({});
  api.put.mockImplementation(async (path, body) => ({ ...body, id: path.split('/').at(-1), revision: 1 }));
  api.del.mockResolvedValue({ deleted: true });
});
afterEach(cleanup);

describe('shared entity activities', () => {
  it('does not display a previous entity response after changing the dossier', async () => {
    const old = deferred();
    api.get.mockImplementation(path => path.includes('entity_id=p1') ? old.promise : Promise.resolve({ items: [event('new', 'Haus Beta')], next_cursor: null }));
    const { rerender } = show(<EntityTimeline entityType="property" entityId="p1" />);
    rerender(<MemoryRouter><EntityTimeline entityType="property" entityId="p2" /></MemoryRouter>);
    expect(await screen.findByText('Haus Beta')).toBeInTheDocument();
    await act(async () => old.resolve({ items: [event('old', 'Haus Alpha')], next_cursor: null }));
    expect(screen.queryByText('Haus Alpha')).not.toBeInTheDocument();
  });

  it('keeps existing events when loading the next page fails', async () => {
    api.get.mockResolvedValueOnce({ items: [event('one', 'Erstes Gespräch')], next_cursor: 'next' }).mockRejectedValueOnce(new Error('Verbindung unterbrochen'));
    show(<EntityTimeline entityType="tenant" entityId="t1" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Weitere laden' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Verbindung unterbrochen');
    expect(screen.getByText('Erstes Gespräch')).toBeInTheDocument();
  });
});

describe('private entity recents and favourites', () => {
  it('pins with the private revision and records an entity visit without changing domain data', async () => {
    show(<EntityActions entityType="property" entityId="p1" title="Lindenhof" entityRevision={rev1} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Als Favorit merken: Lindenhof' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Als Favorit merken: Lindenhof' }));
    expect(await screen.findByRole('button', { name: 'Favorit entfernen: Lindenhof' })).toHaveAttribute('aria-pressed', 'true');
    expect(api.put).toHaveBeenCalledWith('/workspace/favorites/property/p1', expect.objectContaining({ base_revision: 0, idempotency_key: expect.any(String) }), undefined);
    expect(api.post).toHaveBeenCalledWith('/workspace/recents/events', expect.objectContaining({ kind: 'property', entity_id: 'p1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Favorit entfernen: Lindenhof' }));
    await waitFor(() => expect(api.del).toHaveBeenCalledWith('/workspace/favorites/property/p1', expect.objectContaining({ data: expect.objectContaining({ base_revision: 1 }) })));
  });

  it('permits private favourites for readers but offers no conversation action', async () => {
    auth.write = [];
    show(<EntityActions entityType="tenant" entityId="t1" title="Anna" entityRevision={rev1} />);
    expect(screen.queryByRole('button', { name: 'Gespräch / Wiedervorlage' })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Als Favorit merken: Anna' })).toBeEnabled());
  });

  it('discards old private shelves after a user switch', async () => {
    const old = deferred();
    api.get.mockImplementation(() => auth.user.id === 'u1' ? old.promise : Promise.resolve({ items: [{ kind: 'property', entity_id: 'p2', title: 'Nur Benutzer 2', href: '/properties/p2' }], next_cursor: null }));
    const { rerender } = show(<EntityShelf />);
    auth.user = { id: 'u2' };
    rerender(<MemoryRouter><EntityShelf /></MemoryRouter>);
    expect((await screen.findAllByText('Nur Benutzer 2')).length).toBe(2);
    await act(async () => old.resolve({ items: [{ kind: 'property', entity_id: 'p1', title: 'Geheime alte Akte', href: '/properties/p1' }], next_cursor: null }));
    expect(screen.queryByText('Geheime alte Akte')).not.toBeInTheDocument();
  });
});

describe('conversation and follow-up workflow', () => {
  it('retains a failed conversation and retries one atomic note plus task command', async () => {
    api.get.mockImplementation(path => path.startsWith('/work-center/timeline')
      ? Promise.resolve({ ...empty(), entity_revision: rev1, can_note: true })
      : path.startsWith('/workspace/favorites/') ? Promise.reject(missing()) : Promise.resolve(empty()));
    let attempts = 0;
    api.post.mockImplementation(async path => {
      if (path === '/work-center/notes' && ++attempts === 1) throw new Error('Verbindung unterbrochen');
      return {};
    });
    show(<EntityActions entityType="tenant" entityId="t1" title="Anna" entityRevision={rev1} />);
    fireEvent.click(screen.getByRole('button', { name: 'Gespräch / Wiedervorlage' }));
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(within(dialog).getByLabelText('Gesprächsnotiz *')).toBeEnabled());
    fireEvent.change(within(dialog).getByLabelText('Gesprächsnotiz *'), { target: { value: 'Rückruf wegen Heizung' } });
    fireEvent.change(within(dialog).getByLabelText('Aufgabe'), { target: { value: 'Heizungsfirma zurückrufen' } });
    fireEvent.change(within(dialog).getByLabelText('Fällig am'), { target: { value: '2026-10-16' } });
    fireEvent.submit(dialog.querySelector('form'));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Verbindung unterbrochen');
    expect(within(dialog).getByLabelText('Gesprächsnotiz *')).toHaveValue('Rückruf wegen Heizung');
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const notes = api.post.mock.calls.filter(([path]) => path === '/work-center/notes');
    expect(notes).toHaveLength(2);
    expect(notes[1][1]).toEqual(notes[0][1]);
    expect(notes[0][1]).toMatchObject({ entity_type: 'tenant', entity_id: 't1', base_revision: rev1,
      follow_up: { title: 'Heizungsfirma zurückrufen', due_date: '2026-10-16', priority: 'medium' } });
  });
});

describe('safe task edits and undo', () => {
  function Editor() {
    const [record, setRecord] = useState({ id: 't1', title: 'Rückruf', assignee: 'Anna', updated_at: rev1 });
    const [change, setChange] = useState(null);
    return <><InlineFieldEditor record={record} field="assignee" label="Zuständig" canEdit onSaved={result => { setRecord(result.record); setChange(result); }} />
      {change && <UndoNotice change={change} onDismiss={() => setChange(null)} onUndone={result => { setRecord(result.record); setChange(null); }} />}</>;
  }
  it('retains conflicted input and never rolls back locally when undo conflicts', async () => {
    api.post.mockRejectedValueOnce(Object.assign(new Error('Inzwischen geändert'), { statusCode: 409 }))
      .mockResolvedValueOnce({ record: { id: 't1', title: 'Rückruf', assignee: 'Ben', updated_at: rev2 }, revision: rev2, undo_id: 'undo1' })
      .mockRejectedValueOnce(Object.assign(new Error('Neuere Änderung vorhanden'), { statusCode: 409 }));
    show(<Editor />);
    fireEvent.click(screen.getByRole('button', { name: 'Zuständig bearbeiten: Rückruf' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Zuständig' }), { target: { value: 'Ben' } });
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Inzwischen geändert');
    expect(screen.getByRole('textbox', { name: 'Zuständig' })).toHaveValue('Ben');
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Rückgängig' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Neuere Änderung vorhanden');
    expect(screen.getByText('Ben')).toBeInTheDocument();
    expect(api.post).toHaveBeenLastCalledWith('/work-center/quick-edits/undo1/undo', expect.objectContaining({ base_revision: rev2 }));
  });
});

describe('source-bound work lists', () => {
  it('requires a reason before saving a personal deferral and keeps business due dates untouched', async () => {
    api.get.mockImplementation(path => path.startsWith('/workspace/deferrals/') ? Promise.reject(missing()) : Promise.resolve(empty()));
    show(<DeferralControl item={{ work_item_key: 'task:t1:overdue', title: 'Rückruf' }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Später bearbeiten' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Wieder anzeigen am'), { target: { value: '2026-10-20' } });
    fireEvent.submit(dialog.querySelector('form'));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Bitte eine kurze Notiz');
    expect(api.put).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText('Notiz'), { target: { value: '  Rückruf vereinbart  ' } });
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/workspace/deferrals/task%3At1%3Aoverdue', expect.objectContaining({
      base_revision: 0, due_on: '2026-10-20', reason: 'Rückruf vereinbart',
    }), undefined));
    expect(api.post).not.toHaveBeenCalled();
  });
  it('uses exact server drilldowns for each displayed count', async () => {
    api.get.mockResolvedValue({ as_of: rev1, counts: { task: 3 }, drilldowns: { task: { href: '/work-center?kind=task&property_id=p1' } } });
    show(<WorkSummary />);
    expect(await screen.findByRole('link', { name: /Offene Aufgaben: 3/ })).toHaveAttribute('href', '/work-center?kind=task&property_id=p1');
  });

  it('applies due and personal deferral filters to the server feed and preserves the source link', async () => {
    api.get.mockImplementation(path => path.startsWith('/work-center/items') ? Promise.resolve({ items: [{ work_item_key: 'task:t1:due', kind: 'task', entity_id: 't1', title: 'Rückruf', href: '/tasks?suche=R%C3%BCckruf', revision: rev1, actions: [], can_edit: false }], next_cursor: null })
      : path.startsWith('/work-center/summary') ? Promise.resolve({ counts: {}, drilldowns: {} }) : Promise.resolve(empty()));
    const Where = () => <span data-testid="where">{useLocation().search}</span>;
    show(<><WorkCenter /><Where /></>, '/work-center?due_before=2026-10-15&deferred=due');
    expect(await screen.findByRole('link', { name: 'Vorgang öffnen' })).toHaveAttribute('href', '/tasks?suche=R%C3%BCckruf');
    expect(api.get).toHaveBeenCalledWith('/work-center/items?due_before=2026-10-15&deferred=due&limit=25', expect.anything());
    fireEvent.change(screen.getByLabelText('Bereich'), { target: { value: 'task' } });
    expect(screen.getByTestId('where')).toHaveTextContent('kind=task');
  });
});


it('lädt den persönlichen Eingang erst, wenn die eingeklappte Übersicht geöffnet wird', async () => {
  api.get.mockImplementation(path => {
    if (path.startsWith('/notifications/inbox?')) return Promise.resolve({
      items: [], total: 0, unread_count: 0, snapshot: 'empty-work-center', next_cursor: null,
    });
    if (path.startsWith('/workspace/favorites/')) return Promise.reject(missing());
    return Promise.resolve(empty());
  });
  show(<WorkCenter />, '/work-center');
  await waitFor(() => expect(api.get.mock.calls.some(([url]) =>
    url.startsWith('/work-center/items?'))).toBe(true));
  expect(api.get.mock.calls.some(([url]) => url.startsWith('/notifications/inbox?'))).toBe(false);
  fireEvent.click(screen.getByText('Persönliche Benachrichtigungen und Archiv'));
  await waitFor(() => expect(api.get.mock.calls.some(([url]) =>
    url.startsWith('/notifications/inbox?'))).toBe(true));
  expect(await screen.findByText('Keine Hinweise in dieser Ansicht.')).toBeInTheDocument();
});
