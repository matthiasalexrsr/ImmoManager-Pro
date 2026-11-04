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
  revision: 1, config_revision: 1, attempts: 0, completed_pages: 0, result_bytes: 0, can_dispatch: true, can_cancel: true,
  safe_summary: 'Vorschau gespeichert; nichts gesendet.' };
const deferred = () => { let resolve, reject; const promise = new Promise((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; };
let rows;
let preview;
let customGet;
let providers;

beforeEach(() => {
  vi.resetAllMocks(); access.write = true; rows = []; preview = { run: prepared, payload: { text: 'Serverseitig eingefrorener Text' } }; customGet = null;
  providers = [provider];
  api.captureSession.mockReturnValue(() => {});
  api.get.mockImplementation((url, options) => {
    const custom = customGet?.(url, options); if (custom !== undefined) return custom;
    if (url.endsWith('/catalog')) return Promise.resolve({ providers });
    if (url.endsWith('/selected-connection')) return Promise.resolve({ selection: null });
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
  // The deep link is resolved after the asynchronous list response. Don't
  // inspect a request until the component has actually issued it.
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

it('keeps the usable connection list and create button available after an invalid deep link', async () => {
  customGet = url => url.endsWith('/c-a') ? Promise.reject(Object.assign(new Error('Verbindung nicht gefunden.'), { statusCode: 404 })) : undefined;
  render(<MemoryRouter initialEntries={['/integration-connections?connection=c-a']}><IntegrationConnections /></MemoryRouter>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Verbindung nicht gefunden.');
  expect(screen.getByRole('button', { name: 'Verbindung anlegen' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: /Verbindung B Prüfanbieter/ }));
  await screen.findByRole('heading', { name: 'Verbindung B' });
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('keeps management available when the stored preferred connection cannot be resolved', async () => {
  customGet = url => url.endsWith('/selected-connection') ? Promise.reject(new Error('Gespeicherte Auswahl nicht verfügbar.')) : undefined;
  await open(false);
  expect(screen.getByRole('alert')).toHaveTextContent('Gespeicherte Auswahl nicht verfügbar.');
  expect(screen.getByRole('button', { name: /Verbindung A Prüfanbieter/ })).toBeEnabled();
});

it('submits real JSON inputs, decimals and numeric options with the action schema defaults', async () => {
  providers = [{ ...provider, actions: [{ ...provider.actions[0], inputs: [
    { key: 'messages', label: 'Nachrichten (JSON)', type: 'array', required: true },
    { key: 'context', label: 'Kontext', type: 'object', default: { tenant: 0 } },
    { key: 'fraction', label: 'Anteil', type: 'number', required: true, min: 0, max: 2 },
    { key: 'batch', label: 'Abschnitt', type: 'integer', required: true, options: [0, 2], default: 0 },
    { key: 'sandbox', label: 'Sandbox', type: 'boolean', default: true },
  ] }] }];
  api.post.mockResolvedValue(prepared);
  await open();
  expect(screen.getByLabelText('Kontext')).toHaveValue(JSON.stringify({ tenant: 0 }, null, 2));
  expect(screen.getByLabelText('Sandbox')).toBeChecked();
  fireEvent.change(screen.getByLabelText('Nachrichten (JSON) *'), { target: { value: '[{"body":"Hallo"}]' } });
  fireEvent.change(screen.getByLabelText('Anteil *'), { target: { value: '0.25' } });
  expect(screen.getByLabelText('Anteil *').checkValidity()).toBe(true);
  fireEvent.change(screen.getByLabelText('Abschnitt *'), { target: { value: '2' } });
  fireEvent.click(screen.getByRole('button', { name: 'Vorschau erstellen' }));
  await screen.findByRole('heading', { name: 'Vorgang: Vorbereitet' });
  expect(api.post.mock.calls[0][1].payload).toEqual({ messages: [{ body: 'Hallo' }], context: { tenant: 0 }, fraction: 0.25, batch: 2, sandbox: true });
});

it('rejects invalid JSON locally without creating an uncertain command or calling the server', async () => {
  providers = [{ ...provider, actions: [{ ...provider.actions[0], inputs: [{ key: 'messages', label: 'Nachrichten', type: 'array', required: true }] }] }];
  await open();
  fireEvent.change(screen.getByLabelText('Nachrichten *'), { target: { value: '{broken' } });
  fireEvent.click(screen.getByRole('button', { name: 'Vorschau erstellen' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Nachrichten: Bitte gültiges JSON eingeben.');
  expect(screen.getByLabelText('Nachrichten *')).toBeEnabled();
  expect(screen.queryByRole('button', { name: 'Vorschau abgleichen' })).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('allows an inactive incomplete connection and makes email format and multiline contracts visible', async () => {
  providers = [{ ...provider, config_fields: [...provider.config_fields,
    { key: 'sender', label: 'Absender', type: 'string', format: 'email' },
    { key: 'description', label: 'Beschreibung', type: 'string', multiline: true }] }];
  api.post.mockResolvedValue({ ...connection, enabled: false, configured: false });
  await open(false);
  fireEvent.click(screen.getByRole('button', { name: 'Verbindung anlegen' }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByLabelText('Absender')).toHaveAttribute('type', 'email');
  expect(within(dialog).getByLabelText('Beschreibung').tagName).toBe('TEXTAREA');
  fireEvent.change(within(dialog).getByLabelText('Bezeichnung *'), { target: { value: 'Entwurf' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Speichern', exact: true }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  expect(api.post.mock.calls[0][1]).toMatchObject({ name: 'Entwurf', config: {}, enabled: false });
});

it('can explicitly remove a stored required secret after deactivation without also replacing it', async () => {
  api.patch.mockResolvedValue({ ...connection, enabled: false, configured: false, revision: 2 });
  await open(); fireEvent.click(screen.getByRole('button', { name: 'Verbindung bearbeiten' }));
  fireEvent.change(screen.getByLabelText('Zugangsschlüssel'), { target: { value: 'discard-this-draft-secret' } });
  fireEvent.click(screen.getByLabelText('Verbindung aktivieren'));
  fireEvent.click(screen.getByLabelText('Dieses gespeicherte Geheimnis ausdrücklich entfernen'));
  expect(screen.getByLabelText('Zugangsschlüssel')).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Speichern', exact: true }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
  expect(api.patch.mock.calls[0][1]).toMatchObject({ enabled: false, clear_secrets: ['api_token'], config: { endpoint: 'synthetic.example.test' } });
  expect(api.patch.mock.calls[0][1].config).not.toHaveProperty('api_token');
});

it('recovers a configuration revision conflict only through an explicit reload and new command', async () => {
  api.patch.mockRejectedValueOnce(Object.assign(new Error('Stand wurde geändert.'), { statusCode: 409 }))
    .mockResolvedValueOnce({ ...connection, revision: 8 });
  await open(); fireEvent.click(screen.getByRole('button', { name: 'Verbindung bearbeiten' }));
  fireEvent.change(screen.getByLabelText('Bezeichnung *'), { target: { value: 'Lokaler Entwurf' } });
  fireEvent.click(screen.getByRole('button', { name: 'Speichern', exact: true }));
  await screen.findByRole('button', { name: 'Formular neu laden' });
  customGet = url => url.endsWith('/c-a') ? Promise.resolve({ ...connection, revision: 7, name: 'Aktueller Serverstand' }) : undefined;
  fireEvent.click(screen.getByRole('button', { name: 'Formular neu laden' }));
  await waitFor(() => expect(screen.getByLabelText('Bezeichnung *')).toHaveValue('Aktueller Serverstand'));
  fireEvent.click(screen.getByRole('button', { name: 'Speichern', exact: true }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(2));
  expect(api.patch.mock.calls[1][1].base_revision).toBe(7);
  expect(api.patch.mock.calls[1][1].idempotency_key).not.toBe(api.patch.mock.calls[0][1].idempotency_key);
});

it('keeps a rejected oversized configuration editable instead of locking it as an uncertain save', async () => {
  api.patch.mockRejectedValue(Object.assign(new Error('Arbeitsschritt ist zu groß.'), { statusCode: 413 }));
  await open(); fireEvent.click(screen.getByRole('button', { name: 'Verbindung bearbeiten' }));
  fireEvent.click(screen.getByRole('button', { name: 'Speichern', exact: true }));
  await screen.findByRole('alert');
  expect(screen.getByLabelText('Bezeichnung *')).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Abbrechen', exact: true })).toBeEnabled();
  expect(screen.queryByRole('button', { name: 'Speicherstatus prüfen' })).not.toBeInTheDocument();
});

it('allows a prepared step to be cancelled even if its stored preview cannot be loaded', async () => {
  rows = [prepared]; customGet = url => url.endsWith('/preview') ? Promise.reject(Object.assign(new Error('Vorschau nicht lesbar.'), { statusCode: 503 })) : undefined;
  api.post.mockResolvedValue({ ...prepared, state: 'cancelled', revision: 2 });
  await open(); fireEvent.click(await screen.findByRole('button', { name: /Vorbereitet Vorschau gespeichert/ }));
  await screen.findByText('Vorschau nicht lesbar.');
  expect(screen.queryByRole('button', { name: 'Jetzt ausführen' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Weitere Schritte abbrechen' }));
  await screen.findByRole('heading', { name: 'Vorgang: Abgebrochen' });
  expect(api.post.mock.calls[0][0]).toMatch(/\/cancel$/);
});

it('retains an uncertain cancel command across a status read and never replaces it with dispatch', async () => {
  rows = [prepared]; api.post.mockRejectedValueOnce(new Error('Abbruchbestätigung verloren.')).mockResolvedValueOnce({ ...prepared, state: 'cancelled', revision: 2 });
  await open(); fireEvent.click(await screen.findByRole('button', { name: /Vorbereitet Vorschau gespeichert/ }));
  await screen.findByText('Serverseitig eingefrorener Text');
  fireEvent.click(screen.getByRole('button', { name: 'Weitere Schritte abbrechen' }));
  await screen.findByText('Abbruchbestätigung verloren.');
  const original = api.post.mock.calls[0];
  fireEvent.click(screen.getByRole('button', { name: 'Status aktualisieren' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Status aktualisieren' })).toBeEnabled());
  expect(screen.queryByRole('button', { name: 'Jetzt ausführen' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Unbestätigten Befehl abgleichen' }));
  await screen.findByRole('heading', { name: 'Vorgang: Abgebrochen' });
  expect(api.post.mock.calls[1]).toEqual(original);
});

it('honours separate server capabilities for cancellation and dispatch', async () => {
  rows = [{ ...prepared, can_dispatch: false, can_cancel: false }]; preview = { run: rows[0], payload: { text: 'Nicht mehr ausführbar' } };
  await open(); fireEvent.click(await screen.findByRole('button', { name: /Vorbereitet Vorschau gespeichert/ }));
  await screen.findByText('Nicht mehr ausführbar');
  expect(screen.queryByRole('button', { name: 'Jetzt ausführen' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Weitere Schritte abbrechen' })).not.toBeInTheDocument();
});

it('clarifies an expired execution lease through the dedicated recovery action without offering a new send', async () => {
  const interrupted = { ...prepared, state: 'executing', revision: 2, interrupted: true, can_dispatch: false, can_cancel: false,
    can_recover_interrupted: true, external_outcome_unknown: true };
  rows = [interrupted]; preview = { run: interrupted, payload: { text: 'Ursprünglicher Auftrag' } };
  api.post.mockResolvedValue({ ...interrupted, state: 'unknown', revision: 3, can_recover_interrupted: false });
  await open(); fireEvent.click(await screen.findByRole('button', { name: /Ausführung unbestätigt Vorschau gespeichert/ }));
  await screen.findByText('Ursprünglicher Auftrag');
  expect(screen.queryByRole('button', { name: 'Jetzt ausführen' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Unterbrochenen Vorgang klären' }));
  await screen.findByRole('heading', { name: 'Vorgang: Ausgang unklar' });
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post.mock.calls[0][0]).toBe('/integration-connections/c-a/runs/run-a/dispatch');
  expect(api.post.mock.calls[0][1]).toMatchObject({ confirm: true, base_revision: 2 });
});

it('does not expose a local secret payload while awaiting its redacted persisted preview', async () => {
  providers = [{ ...provider, actions: [{ ...provider.actions[0], inputs: [{ key: 'credential', label: 'Aktionsgeheimnis', type: 'string', secret: true, required: true }] }] }];
  const held = deferred(); customGet = url => url.endsWith('/preview') ? held.promise : undefined;
  api.post.mockResolvedValue(prepared);
  await open(); fireEvent.change(screen.getByLabelText('Aktionsgeheimnis *'), { target: { value: 'PRIVATE-ACTION-SECRET' } });
  fireEvent.click(screen.getByRole('button', { name: 'Vorschau erstellen' }));
  await screen.findByRole('heading', { name: 'Vorgang: Vorbereitet' });
  expect(screen.queryByText('PRIVATE-ACTION-SECRET')).not.toBeInTheDocument();
  expect(screen.queryByText('Ausgewählte Angaben')).not.toBeInTheDocument();
  await act(async () => held.resolve({ run: prepared, payload: { credential: '***' } }));
  expect(screen.getByText('***')).toBeInTheDocument();
});

it('recovers the unreadable connection state without rendering editable credentials', async () => {
  const unreadable = { ...connection, config: {}, configured: null, read_error: 'Geschützte Daten nicht lesbar.' };
  customGet = url => url.endsWith('/c-a') ? Promise.reject(Object.assign(new Error('Nicht entschlüsselbar.'), { statusCode: 503 }))
    : url.endsWith('/c-a/state') ? Promise.resolve(unreadable) : undefined;
  await open();
  expect(screen.getByRole('alert')).toHaveTextContent('Geschützte Daten nicht lesbar.');
  expect(screen.getByRole('button', { name: 'Verbindung sicher deaktivieren' })).toBeEnabled();
  expect(screen.queryByRole('button', { name: 'Verbindung bearbeiten' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Vorschau erstellen' })).not.toBeInTheDocument();
});

it('uses encoded cursors to page through connections and return to the first page', async () => {
  customGet = url => url.startsWith('/integration-connections?') ? Promise.resolve(url.includes('cursor=older%2F%2B%3D')
    ? { items: [other], total: 2, next_cursor: null }
    : { items: [connection], total: 2, next_cursor: 'older/+=' }) : undefined;
  await open(false);
  fireEvent.click(screen.getByRole('button', { name: 'Weitere Verbindungen' }));
  await screen.findByRole('button', { name: /Verbindung B Prüfanbieter/ });
  expect(screen.queryByRole('button', { name: /Verbindung A Prüfanbieter/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Zurück', exact: true }));
  await screen.findByRole('button', { name: /Verbindung A Prüfanbieter/ });
  expect(api.get.mock.calls.filter(([url]) => url.startsWith('/integration-connections?')).map(([url]) => url)).toEqual([
    '/integration-connections?limit=50', '/integration-connections?limit=50&cursor=older%2F%2B%3D', '/integration-connections?limit=50',
  ]);
});

it('pages the run history independently and allows navigating back after a page load', async () => {
  customGet = url => url.includes('/runs?') ? Promise.resolve(url.includes('cursor=history%2F%2B%3D')
    ? { items: [{ ...prepared, id: 'run-old', state: 'completed', safe_summary: 'Älterer Vorgang' }], total: 2, next_cursor: null }
    : { items: [prepared], total: 2, next_cursor: 'history/+=' }) : undefined;
  await open(); await screen.findByRole('button', { name: /Vorbereitet Vorschau gespeichert/ });
  fireEvent.click(screen.getByRole('button', { name: 'Ältere Vorgänge' }));
  await screen.findByRole('button', { name: /Abgeschlossen Älterer Vorgang/ });
  fireEvent.click(screen.getByRole('button', { name: 'Neuere Vorgänge' }));
  await screen.findByRole('button', { name: /Vorbereitet Vorschau gespeichert/ });
  expect(api.get.mock.calls.filter(([url]) => url.includes('/runs?')).map(([url]) => url)).toEqual([
    '/integration-connections/c-a/runs?limit=25', '/integration-connections/c-a/runs?limit=25&cursor=history%2F%2B%3D', '/integration-connections/c-a/runs?limit=25',
  ]);
});

it('unlocks a rejected oversized action preview for correction without a status-only retry', async () => {
  api.post.mockRejectedValue(Object.assign(new Error('Schritt zu groß.'), { statusCode: 413 }));
  await open(); fireEvent.change(screen.getByLabelText('Nachrichtentext *'), { target: { value: 'Nachricht' } });
  fireEvent.click(screen.getByRole('button', { name: 'Vorschau erstellen' }));
  await screen.findByRole('alert');
  expect(screen.getByLabelText('Nachrichtentext *')).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Vorschau erstellen' })).toBeEnabled();
  expect(screen.queryByRole('button', { name: 'Vorschau abgleichen' })).not.toBeInTheDocument();
});

it('does not accept another connections persisted preview as execution authority', async () => {
  rows = [prepared]; preview = { run: { ...prepared, connection_id: 'c-b' }, payload: { text: 'Falsche Verbindung' } };
  await open(); fireEvent.click(await screen.findByRole('button', { name: /Vorbereitet Vorschau gespeichert/ }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Die gespeicherte Vorschau ist unvollständig.');
  expect(screen.queryByRole('button', { name: 'Jetzt ausführen' })).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('requires explicit server capabilities before offering dispatch or cancellation', async () => {
  const incomplete = { ...prepared, can_dispatch: undefined, can_cancel: undefined };
  rows = [incomplete]; preview = { run: incomplete, payload: { text: 'Freigaben fehlen' } };
  await open(); fireEvent.click(await screen.findByRole('button', { name: /Vorbereitet Vorschau gespeichert/ }));
  await screen.findByText('Freigaben fehlen');
  expect(screen.queryByRole('button', { name: 'Jetzt ausführen' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Weitere Schritte abbrechen' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Status aktualisieren' })).toBeEnabled();
});

it('handles a synchronous session change before the initial list effect without issuing a request', async () => {
  api.captureSession.mockImplementation(() => { throw Object.assign(new Error('changed'), { code: 'SESSION_CHANGED' }); });
  render(<StrictMode><MemoryRouter><IntegrationConnections /></MemoryRouter></StrictMode>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  expect(api.get).not.toHaveBeenCalled();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Verbindung anlegen' })).toBeDisabled();
});

it('ends a history load cleanly if its synchronous session capture fails', async () => {
  api.captureSession.mockReturnValueOnce(() => {}).mockImplementation(() => { throw Object.assign(new Error('changed'), { code: 'SESSION_CHANGED' }); });
  render(<MemoryRouter initialEntries={['/integration-connections?connection=c-a']}><IntegrationConnections /></MemoryRouter>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  expect(api.get.mock.calls.some(([url]) => url.includes('/runs?'))).toBe(false);
  expect(screen.queryByRole('button', { name: 'Vorschau erstellen' })).not.toBeInTheDocument();
  expect(screen.queryByText('Vorgänge werden geladen …')).not.toBeInTheDocument();
});

it('hides the old run context if synchronous preview session capture fails', async () => {
  rows = [prepared]; await open();
  const historical = await screen.findByRole('button', { name: /Vorbereitet Vorschau gespeichert/ });
  api.captureSession.mockImplementation(() => { throw Object.assign(new Error('changed'), { code: 'SESSION_CHANGED' }); });
  fireEvent.click(historical);
  expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  expect(api.get.mock.calls.some(([url]) => url.endsWith('/preview'))).toBe(false);
  expect(screen.queryByRole('heading', { name: 'Vorgang: Vorbereitet' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Weitere Schritte abbrechen' })).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('discards an initial response when the captured session becomes invalid before it is applied', async () => {
  api.captureSession.mockReturnValue(() => { throw Object.assign(new Error('changed'), { code: 'SESSION_CHANGED' }); });
  render(<MemoryRouter initialEntries={['/integration-connections?connection=c-a']}><IntegrationConnections /></MemoryRouter>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  expect(screen.queryByRole('heading', { name: 'Verbindung A' })).not.toBeInTheDocument();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});

it('uses advertised labels in the frozen preview while preserving original values and command fields', async () => {
  providers = [{ ...provider, actions: [{ ...provider.actions[0], inputs: [
    { key: 'property_name', label: 'Immobilie', type: 'string' }, { key: 'tenant_name', label: 'Mieter', type: 'string' },
  ] }] }];
  rows = [prepared]; preview = { run: prepared, payload: { property_name: 'Haus Nord', tenant_name: 'Lina Muster' } };
  api.post.mockResolvedValue({ ...prepared, state: 'accepted', revision: 2 });
  await open(); fireEvent.click(await screen.findByRole('button', { name: /Vorbereitet Vorschau gespeichert/ }));
  await screen.findByText('Haus Nord');
  const selected = screen.getByText('Ausgewählte Angaben').closest('details');
  expect(within(selected).getByText('Immobilie')).toBeInTheDocument();
  expect(within(selected).getByText('Mieter')).toBeInTheDocument();
  expect(within(selected).getByText('Lina Muster')).toBeInTheDocument();
  expect(within(selected).queryByText('property_name')).not.toBeInTheDocument();
  expect(within(selected).queryByText('tenant_name')).not.toBeInTheDocument();
  fireEvent.click(screen.getByLabelText('Ich bestätige die ausgewählte externe Aktion.'));
  fireEvent.click(screen.getByRole('button', { name: 'Jetzt ausführen' }));
  await screen.findByRole('heading', { name: 'Vorgang: Extern angenommen' });
  expect(api.post.mock.calls[0][1]).toEqual({ idempotency_key: expect.any(String), base_revision: 1, confirm: true });
});
