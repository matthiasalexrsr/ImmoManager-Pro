import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import Tasks from '../pages/Tasks';
import { api } from '../api';

const state = vi.hoisted(() => ({ canWrite: true, actor: 'owner', lookupError: null, toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), patch: vi.fn(), post: vi.fn(), del: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => '', locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: state.actor } }), useCanWrite: () => state.canWrite }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => ({ invalidateRelated: vi.fn() }), useEntities: kind => ({
  items: kind === 'properties' ? [{ id: 'p1', name: 'Haus Nord' }, { id: 'p2', name: 'Haus Süd' }]
    : [{ id: 'u1', property_id: 'p1', label: 'Wohnung 1' }], loading: false, error: state.lookupError, reload: vi.fn(),
}) }));
vi.mock('../components/Toast', () => ({ useToast: () => state.toast }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn() }));
vi.mock('../components/NotificationArrival', () => ({ default: ({ record }) => <p data-testid="arrived-source">{record.id}</p> }));
vi.mock('../components/DataTable', () => ({ default: ({ columns, data, rowActions, acknowledgeNotifications, clearFocusedRow, onApplyView }) => <section aria-label="Aufgabenliste">
  <span data-testid="table-receipts">{String(acknowledgeNotifications)}</span>
  <button onClick={clearFocusedRow}>Listenfokus entfernen</button>
  <button onClick={() => onApplyView({column_filters:{workflow_filter:'open',property_id:'p1'}})}>Gespeicherte Ansicht anwenden</button>
  {data.map(row => <div key={row.id} data-testid={`row-${row.id}`}>
    {columns.find(column => column.key === 'title').render(row.title, row)}
    {rowActions(row).map(action => <button key={action.label} onClick={() => action.onClick(row)}>{action.label}</button>)}
  </div>)}
</section> }));

const one = { id: 't1', title: 'Nebenkostenabrechnung prüfen', description: 'Belege und Verteilerschlüssel vergleichen.',
  property_id: 'p1', unit_id: 'u1', status: 'open', priority: 'high', due_date: '2026-11-20', assignee: 'Nora Seidel', updated_at: '2026-11-06T10:00:00Z' };
const two = { ...one, id: 't2', title: 'Zählertermin vereinbaren', property_id: 'p2', unit_id: null, status: 'completed' };
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }
function Navigation() {
  const navigate = useNavigate(), location = useLocation();
  return <><output data-testid="location">{location.pathname}{location.search}</output>
    <button onClick={() => navigate('/tasks?focus_id=t2')}>Andere Aufgabe</button>
    <button onClick={() => navigate(-1)}>Browser zurück</button>
    <button onClick={() => navigate(1)}>Browser vor</button></>;
}
function show(url = '/tasks?focus_id=t1', entries = [url]) {
  return render(<MemoryRouter initialEntries={entries} initialIndex={entries.length - 1}><Navigation /><Tasks /></MemoryRouter>);
}
beforeEach(() => {
  vi.resetAllMocks(); state.canWrite = true; state.actor = 'owner'; state.lookupError = null;
  api.captureSession.mockImplementation(() => () => {});
  api.list.mockResolvedValue([one, two]);
  api.get.mockImplementation(async path => path === '/tasks/t1' ? { ...one } : path === '/tasks/t2' ? { ...two } : {});
  api.patch.mockImplementation(async (_path, values) => ({ ...one, ...values, updated_at: '2026-11-06T11:00:00Z' }));
});
afterEach(cleanup);

describe('task overview navigation', () => {
  it('contains the API asynchronous session rejection and removes the previous task overview', async () => {
    show();await screen.findByRole('heading',{name:one.title,level:2});
    api.get.mockImplementationOnce(async()=>{
      window.dispatchEvent(new Event('workspace-logout'));
      throw Object.assign(new Error('Die Sitzung wurde geändert. Bitte erneut anmelden.'),{code:'SESSION_CHANGED'});
    });
    expect(()=>fireEvent.click(screen.getByRole('button',{name:'Andere Aufgabe'}))).not.toThrow();
    expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert');
    expect(screen.queryByRole('heading',{name:one.title,level:2})).not.toBeInTheDocument();
    expect(screen.queryByTestId('arrived-source')).not.toBeInTheDocument();
    expect(api.get.mock.calls.map(([path])=>path)).toEqual(['/tasks/t1','/tasks/t2']);
    expect(api.post).not.toHaveBeenCalled();
  });
  it.each(['Listenfokus entfernen','Gespeicherte Ansicht anwenden'])('cleans receipt context when %s leaves an exact source', async action => {
    show('/tasks?focus_id=t1&source_id=t1&notice_id=n1&property_id=p1');
    await screen.findByRole('heading',{name:one.title,level:2});
    fireEvent.click(screen.getByRole('button',{name:action}));
    const url=screen.getByTestId('location').textContent;
    expect(url).not.toMatch(/focus_id|source_id|notice_id/);
    expect(url).toContain('property_id=p1');
    expect(screen.queryByRole('heading',{name:one.title,level:2})).not.toBeInTheDocument();
  });
  it.each(['title','action'])('clears a previous notice when selecting another task by %s', async selection => {
    show('/tasks?focus_id=t1&source_id=t1&notice_id=n1');
    await screen.findByRole('heading',{name:one.title,level:2});
    const row=screen.getByTestId('row-t2');
    fireEvent.click(selection==='title' ? within(row).getByRole('link',{name:two.title}) : within(row).getByRole('button',{name:'Aufgabe ansehen'}));
    expect(await screen.findByRole('heading',{name:two.title,level:2})).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/tasks?focus_id=t2');
    expect(screen.getByTestId('location')).not.toHaveTextContent(/source_id|notice_id/);
  });
  it('opens the authoritative overview despite incompatible property, status and search filters', async () => {
    show('/tasks?focus_id=t1&property_id=p2&status=completed&suche=Zähler');
    const detail = await screen.findByRole('heading', { name: one.title, level: 2 });
    const overview = detail.closest('section');
    expect(within(overview).getByText(one.description)).toBeInTheDocument();
    expect(within(overview).getByText(one.assignee)).toBeInTheDocument();
    expect(within(overview).getByRole('link', { name: /Haus Nord/ })).toHaveAttribute('href', '/properties/p1');
    expect(within(overview).getByRole('link', { name: /Wohnung 1/ })).toHaveAttribute('href', '/units/u1');
    expect(within(screen.getByRole('region', { name: 'Aufgabenliste' })).queryByRole('link', { name: one.title })).not.toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/tasks/t1', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(screen.getByTestId('arrived-source')).toHaveTextContent('t1');
    expect(screen.getByTestId('table-receipts')).toHaveTextContent('false');
  });

  it('keeps the overview readable if the list and lookup requests fail', async () => {
    api.list.mockRejectedValue(new Error('Liste nicht erreichbar')); state.lookupError = 'Zuordnungen nicht erreichbar';
    show();
    const overview = (await screen.findByRole('heading', { name: one.title, level: 2 })).closest('section');
    expect(within(overview).getByText(one.description)).toBeInTheDocument();
    expect(within(overview).queryByRole('button', { name: 'Aufgabe bearbeiten' })).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Liste nicht erreichbar');
    expect(screen.getByRole('alert')).toHaveTextContent('Zuordnungen nicht erreichbar');
  });

  it.each([403, 404])('shows one non-disclosing unavailable state for HTTP %s', async status => {
    api.get.mockRejectedValue(Object.assign(new Error('Server detail must not leak'), { statusCode: status }));
    show();
    const overview = screen.getByRole('region', { name: 'Aufgabendetails' });
    expect(await within(overview).findByRole('alert')).toHaveTextContent('Diese Aufgabe wurde gelöscht oder ist für Sie nicht zugänglich.');
    expect(within(overview).queryByText('Server detail must not leak')).not.toBeInTheDocument();
    expect(within(overview).queryByRole('heading', { name: one.title })).not.toBeInTheDocument();
    expect(screen.queryByTestId('arrived-source')).not.toBeInTheDocument();
    expect(screen.getByTestId('table-receipts')).toHaveTextContent('false');
  });

  it('retries a failed individual read without losing list filters', async () => {
    api.get.mockRejectedValueOnce(new Error('Verbindung unterbrochen'));
    show('/tasks?focus_id=t1&property_id=p1');
    const overview = screen.getByRole('region', { name: 'Aufgabendetails' });
    await within(overview).findByText('Verbindung unterbrochen');
    fireEvent.click(within(overview).getByRole('button', { name: 'Aufgabe erneut laden' }));
    await screen.findByRole('heading', { name: one.title, level: 2 });
    expect(screen.getByTestId('location')).toHaveTextContent('/tasks?focus_id=t1&property_id=p1');
  });

  it('discards an old task response after navigation and restores the source on browser back', async () => {
    const pending = deferred();
    api.get.mockImplementationOnce(() => pending.promise);
    show();
    const request = api.get.mock.calls.find(([url]) => url === '/tasks/t1')[1];
    fireEvent.click(screen.getByRole('button', { name: 'Andere Aufgabe' }));
    await screen.findByRole('heading', { name: two.title, level: 2 });
    expect(request.signal.aborted).toBe(true);
    await act(async () => pending.resolve({ ...one, title: 'Veraltete Antwort' }));
    expect(screen.queryByText('Veraltete Antwort')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Browser zurück' }));
    await screen.findByRole('heading', { name: one.title, level: 2 });
    fireEvent.click(screen.getByRole('button', { name: 'Browser vor' }));
    await screen.findByRole('heading', { name: two.title, level: 2 });
  });

  it('closes the overview without retaining acknowledgement parameters or creating a history trap', async () => {
    show(null, ['/dashboard', '/tasks?focus_id=t1&notice_id=n1&source_id=t1&status=open&property_id=p1']);
    await screen.findByRole('heading', { name: one.title, level: 2 });
    fireEvent.click(screen.getByRole('button', { name: 'Detailansicht schließen' }));
    expect(screen.queryByRole('region', { name: 'Aufgabendetails' })).not.toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/tasks?status=open&property_id=p1');
    expect(screen.getByTestId('table-receipts')).toHaveTextContent('true');
    fireEvent.click(screen.getByRole('button', { name: 'Browser zurück' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/dashboard');
  });

  it('keeps mutation actions out of a read-only overview', async () => {
    state.canWrite = false; show();
    const overview = (await screen.findByRole('heading', { name: one.title, level: 2 })).closest('section');
    expect(within(overview).queryByRole('button', { name: 'Aufgabe bearbeiten' })).not.toBeInTheDocument();
    expect(within(overview).queryByRole('button', { name: 'Aufgabe erledigen' })).not.toBeInTheDocument();
    expect(within(overview).getByRole('link', { name: /Haus Nord/ })).toBeInTheDocument();
    expect(api.patch).not.toHaveBeenCalled();
  });

  it('allows a reader to prepare a message and plan a personal reminder without changing the task', async () => {
    state.canWrite = false; show();
    const overview = (await screen.findByRole('heading', { name: one.title, level: 2 })).closest('section');
    fireEvent.click(within(overview).getByRole('button', { name: 'Nachricht vorbereiten' }));
    const composer = screen.getByRole('dialog', { name: 'Nachricht vorbereiten' });
    expect(within(composer).getByLabelText('Nachricht')).toHaveValue(`${one.title}\n\n${one.description}`);
    fireEvent.change(within(composer).getByLabelText('Mobilnummer mit Vorwahl'), { target: { value: '+49 170 1234567' } });
    expect(within(composer).getByRole('link', { name: 'WhatsApp-Chat mit Text öffnen' }).href).toContain('web.whatsapp.com');
    fireEvent.click(within(composer).getAllByRole('button', { name: 'Schließen' })[0]);
    fireEvent.click(within(overview).getByRole('button', { name: 'Erinnerung planen' }));
    const planner = screen.getByRole('dialog', { name: 'Erinnerung planen' });
    expect(within(planner).getByText(one.title)).toBeInTheDocument();
    api.post.mockResolvedValue({ due_at: '2026-11-19T08:00:00Z' });
    fireEvent.click(within(planner).getByRole('button', { name: 'Erinnerung speichern' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/reminders', expect.objectContaining({
      source_kind: 'task', source_id: 't1', channel: 'in_app', recipient: '',
    })));
    expect(api.patch).not.toHaveBeenCalled();
  });

  it('immediately hides the previous account list and overview while rechecking access for another account', async () => {
    const view = show();
    await screen.findByRole('heading', { name: one.title, level: 2 });
    const nextList = deferred(); api.list.mockImplementation(() => nextList.promise);
    api.get.mockRejectedValue(Object.assign(new Error('Unrelated private server detail'), { statusCode: 403 }));
    state.actor = 'another-account';
    view.rerender(<MemoryRouter initialEntries={['/tasks?focus_id=t1']}><Navigation /><Tasks /></MemoryRouter>);
    expect(screen.queryByRole('heading', { name: one.title, level: 2 })).not.toBeInTheDocument();
    expect(screen.queryByTestId('row-t1')).not.toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('Diese Aufgabe wurde gelöscht oder ist für Sie nicht zugänglich.');
    expect(screen.queryByTestId('arrived-source')).not.toBeInTheDocument();
    await act(async () => nextList.resolve([]));
    expect(screen.queryByTestId('row-t1')).not.toBeInTheDocument();
  });

  it('shows a confirmed completion and uses its new revision for reopening, even if the list refresh fails', async () => {
    show();
    await screen.findByRole('heading', { name: one.title, level: 2 });
    api.list.mockRejectedValue(new Error('Liste offline'));
    fireEvent.click(screen.getByRole('button', { name: 'Aufgabe erledigen' }));
    await screen.findByRole('button', { name: 'Aufgabe wieder öffnen' });
    expect(api.patch).toHaveBeenLastCalledWith('/tasks/t1', { status: 'completed', updated_at: one.updated_at });
    fireEvent.click(screen.getByRole('button', { name: 'Aufgabe wieder öffnen' }));
    await waitFor(() => expect(api.patch).toHaveBeenLastCalledWith('/tasks/t1', { status: 'open', updated_at: '2026-11-06T11:00:00Z' }));
  });

  it('does not let a pending read overwrite a more recent confirmed list action', async () => {
    const pending = deferred(); api.get.mockImplementationOnce(() => pending.promise);
    show();
    const request = api.get.mock.calls.find(([url]) => url === '/tasks/t1')[1];
    const row = await screen.findByTestId('row-t1');
    api.patch.mockResolvedValue({ ...one, status: 'completed', title: 'Aktueller Serverstand', updated_at: '2026-11-06T11:00:00Z' });
    fireEvent.click(within(row).getByRole('button', { name: 'Erledigen' }));
    await screen.findByRole('heading', { name: 'Aktueller Serverstand', level: 2 });
    expect(request.signal.aborted).toBe(true);
    await act(async () => pending.resolve({ ...one, title: 'Veraltete Aufgabe' }));
    expect(screen.queryByRole('heading', { name: 'Veraltete Aufgabe' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Aufgabe wieder öffnen' })).toBeInTheDocument();
  });

  it('rejects a response for another task and aborts pending reads when unmounted', async () => {
    api.get.mockResolvedValue(two); const view = show();
    expect(await screen.findByRole('alert')).toHaveTextContent('Die Aufgabe konnte nicht vollständig geladen werden.');
    expect(screen.queryByRole('heading', { name: two.title })).not.toBeInTheDocument();
    const request = api.get.mock.calls.find(([url]) => url === '/tasks/t1')[1];
    view.unmount(); expect(request.signal.aborted).toBe(true);
  });
});
