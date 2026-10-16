import { StrictMode } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import IntegrationConnections from '../pages/IntegrationConnections';

const access = vi.hoisted(() => ({ write: true }));
vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => access.write }));
const provider = { provider_id: 'proof', name: 'Prüfanbieter', planned: false, config_fields: [
  { key: 'endpoint', label: 'Server', type: 'string', required: true },
  { key: 'api_token', label: 'Zugangsschlüssel', type: 'string', secret: true, required: true },
], actions: [{ id: 'send', label: 'Nachricht senden', enabled: true, effect: 'external_write', inputs: [
  { key: 'text', label: 'Nachrichtentext', type: 'textarea', required: true },
] }] };
const connection = { id: 'c-a', provider_id: 'proof', provider_name: provider.name, name: 'Verbindung A', revision: 1,
  enabled: true, configured: true, archived: false, config: { endpoint: 'synthetic.example.test', api_token: '***' },
  secret_fields_present: ['api_token'], unmapped_fields: [] };
const other = { ...connection, id: 'c-b', name: 'Verbindung B' };
const prepared = { id: 'run-a', connection_id: 'c-a', actor_id: 'owner', action: 'send', effect: 'external_write', state: 'prepared',
  revision: 1, config_revision: 1, attempts: 0, completed_pages: 0, result_bytes: 0, safe_summary: 'Vorschau gespeichert; nichts gesendet.' };
const deferred = () => { let resolve, reject; const promise = new Promise((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; };
let rows;
let preview;
let customGet;

beforeEach(() => {
  vi.resetAllMocks(); access.write = true; rows = []; preview = { run: prepared, payload: { text: 'Serverseitig eingefrorener Text' } }; customGet = null;
  api.captureSession.mockReturnValue(() => {});
  api.get.mockImplementation((url, options) => {
    const custom = customGet?.(url, options); if (custom !== undefined) return custom;
    if (url.endsWith('/catalog')) return Promise.resolve({ providers: [provider] });
    if (url.startsWith('/integration-connections?')) return Promise.resolve({ items: [connection, other], total: 2, next_cursor: null });
    if (url.endsWith('/c-a')) return Promise.resolve(connection);
    if (url.endsWith('/c-b')) return Promise.resolve(other);
    if (url.includes('/runs?')) return Promise.resolve({ items: rows, total: rows.length, next_cursor: null });
    if (url.endsWith('/preview')) return Promise.resolve(preview);
    if (url.endsWith('/runs/run-a')) return Promise.resolve(prepared);
    throw new Error('Unexpected GET ' + url);
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

async function open(selected = true, strict = false) {
  const application = <MemoryRouter initialEntries={[selected ? '/integration-connections?connection=c-a' : '/integration-connections']}><IntegrationConnections /></MemoryRouter>;
  render(strict ? <StrictMode>{application}</StrictMode> : application);
  await screen.findByRole('heading', { name: selected ? 'Verbindung A' : 'Verbindung auswählen' });
}

it('opens the real editor in StrictMode and never submits the masked secret as a replacement', async () => {
  api.patch.mockResolvedValue({ ...connection, name: 'Umbenannt', revision: 2 });
  await open(true, true);
  fireEvent.click(screen.getByRole('button', { name: 'Verbindung bearbeiten' }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByLabelText('Zugangsschlüssel')).toHaveValue('');
  fireEvent.change(within(dialog).getByLabelText('Bezeichnung *'), { target: { value: 'Umbenannt' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Speichern', exact: true }));
  await act(async () => {});
  expect(api.patch).toHaveBeenCalledTimes(1);
  const command = api.patch.mock.calls[0][1];
  expect(command).toMatchObject({ name: 'Umbenannt', base_revision: 1, clear_secrets: [] });
  expect(command.config.api_token).toBeUndefined();
  expect(command.idempotency_key).toBeTruthy();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('retains an uncertain configuration command and repeats only its original key', async () => {
  api.patch.mockRejectedValueOnce(new Error('Speicherbestätigung verloren')).mockResolvedValueOnce({ ...connection, revision: 2 });
  await open(); fireEvent.click(screen.getByRole('button', { name: 'Verbindung bearbeiten' }));
  fireEvent.change(screen.getByLabelText('Zugangsschlüssel'), { target: { value: 'synthetic-private-secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Speichern', exact: true }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Speicherbestätigung verloren');
  const first = api.patch.mock.calls[0][1];
  expect(screen.getByLabelText('Zugangsschlüssel')).toHaveValue('synthetic-private-secret');
  expect(screen.getByLabelText('Zugangsschlüssel')).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Speicherstatus prüfen' }));
  await act(async () => {});
  expect(api.patch.mock.calls[1][1]).toEqual(first);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('saves a preview without dispatching and requires a separate explicit confirmation', async () => {
  api.post.mockResolvedValueOnce(prepared).mockResolvedValueOnce({ ...prepared, state: 'accepted', revision: 3, attempts: 1 });
  await open(); fireEvent.change(screen.getByLabelText('Nachrichtentext *'), { target: { value: 'Ausgewählte Nachricht' } });
  fireEvent.click(screen.getByRole('button', { name: 'Vorschau erstellen' }));
  await screen.findByRole('heading', { name: 'Vorgang: Vorbereitet' });
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post.mock.calls[0][0]).toBe('/integration-connections/c-a/runs');
  await screen.findByText('Serverseitig eingefrorener Text');
  expect(screen.getByRole('button', { name: 'Jetzt ausführen' })).toBeDisabled();
  fireEvent.click(screen.getByLabelText('Ich bestätige die ausgewählte externe Aktion.'));
  fireEvent.click(screen.getByRole('button', { name: 'Jetzt ausführen' }));
  await screen.findByRole('heading', { name: 'Vorgang: Extern angenommen' });
  expect(api.post.mock.calls[1][0]).toBe('/integration-connections/c-a/runs/run-a/dispatch');
  expect(screen.getByText(/noch kein Nachweis einer Zustellung/)).toBeInTheDocument();
});

it('never executes a historical run before its frozen server preview has loaded', async () => {
  rows = [prepared]; const held = deferred(); customGet = url => url.endsWith('/preview') ? held.promise : undefined;
  await open(); fireEvent.click(await screen.findByRole('button', { name: /Vorbereitet Vorschau gespeichert/ }));
  expect(screen.queryByRole('button', { name: 'Jetzt ausführen' })).not.toBeInTheDocument();
  await act(async () => held.resolve(preview));
  expect(screen.getByText('Serverseitig eingefrorener Text')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Jetzt ausführen' })).toBeDisabled();
  expect(api.post).not.toHaveBeenCalled();
});

it('keeps an unknown external result visible and offers no second-send button', async () => {
  const unknown = { ...prepared, state: 'unknown', revision: 3, attempts: 1, external_outcome_unknown: true,
    safe_summary: 'Externer Ausgang unklar; nicht erneut senden.' };
  rows = [unknown]; preview = { run: unknown, payload: { text: 'Einmal gewählte Nachricht' } };
  await open(); fireEvent.click(await screen.findByRole('button', { name: /Ausgang unklar Externer Ausgang/ }));
  await screen.findByText('Einmal gewählte Nachricht');
  expect(screen.getByText('Nicht erneut senden.')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Jetzt ausführen' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Weitere Schritte abbrechen' })).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('does not allow a read-only account to create, configure or prepare actions', async () => {
  access.write = false; await open();
  expect(screen.queryByRole('button', { name: 'Verbindung anlegen' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Verbindung bearbeiten' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Vorschau erstellen' })).not.toBeInTheDocument();
});

it('discards late details from A after navigating to B before A finishes', async () => {
  const held = deferred(); customGet = url => url.endsWith('/c-a') ? held.promise : undefined;
  function HistoryNavigation() {
    const navigate = useNavigate();
    return <><button onClick={() => navigate('/integration-connections?connection=c-b')}>Historieneintrag B öffnen</button><IntegrationConnections /></>;
  }
  render(<MemoryRouter initialEntries={['/integration-connections?connection=c-a']}><HistoryNavigation /></MemoryRouter>);
  await waitFor(() => expect(api.get.mock.calls.some(([url]) => url.endsWith('/c-a'))).toBe(true));
  const aSignal = api.get.mock.calls.find(([url]) => url.endsWith('/c-a'))[1].signal;
  fireEvent.click(screen.getByRole('button', { name: 'Historieneintrag B öffnen' }));
  await screen.findByRole('heading', { name: 'Verbindung B' });
  expect(aSignal.aborted).toBe(true);
  await act(async () => held.resolve(connection));
  expect(screen.getByRole('heading', { name: 'Verbindung B' })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Verbindung A' })).not.toBeInTheDocument();
});

it('removes private inputs and ignores a late save after a session change', async () => {
  const saving = deferred(); api.patch.mockReturnValue(saving.promise);
  await open(); fireEvent.click(screen.getByRole('button', { name: 'Verbindung bearbeiten' }));
  fireEvent.change(screen.getByLabelText('Zugangsschlüssel'), { target: { value: 'OLD-PRIVATE-INPUT' } });
  fireEvent.click(screen.getByRole('button', { name: 'Speichern', exact: true }));
  act(() => window.dispatchEvent(new Event('workspace-logout')));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await act(async () => saving.resolve({ ...connection, revision: 2 }));
  expect(screen.queryByDisplayValue('OLD-PRIVATE-INPUT')).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Verbindung A' })).not.toBeInTheDocument();
});
