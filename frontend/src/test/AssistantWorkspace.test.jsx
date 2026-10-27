import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { StrictMode } from 'react';
import Assistant from '../pages/Assistant';
import ConversationDialog from '../features/workCenter/ConversationDialog';
import { api } from '../api';
import { workspace } from '../utils/workspaceClient';

const state = vi.hoisted(() => ({ owner: 'owner-a', conversations: [], runs: {}, messages: {}, files: {}, proposals: {}, connections: {}, views: [], capabilities: null }));
vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), del: vi.fn(), upload: vi.fn(), getBlob: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: state.owner } }), useCanWrite: () => true }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => ({ 'ui.buttons.save': 'Speichern', 'ui.buttons.cancel': 'Abbrechen', 'ui.buttons.close': 'Schließen' }[key]), locale: 'de-DE' }) }));
vi.mock('../utils/workspaceClient', async original => ({ ...await original(), workspace: { list: vi.fn(), get: vi.fn(), put: vi.fn(), remove: vi.fn(), command: () => crypto.randomUUID() } }));
const stamp = '2026-10-18T09:00:00Z';
const conversation = (id, provider = 'local') => ({ id, provider, model: null, effort: 'high', revision: 1, title: `Chat ${id}`, created_at: stamp, updated_at: stamp, archived: false, active_run_id: null });
const run = (id = 'run-1', conversationId = 'a', runState = 'queued') => ({ id, conversation_id: conversationId, state: runState, revision: 1, response: '', events: [], created_at: stamp, updated_at: stamp });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
function Location() { const location = useLocation(); return <output data-testid="location">{JSON.stringify({ pathname: location.pathname, search: location.search, state: location.state })}</output>; }
function App() { return <><Location /><Routes><Route path="/assistant" element={<Assistant />} /><Route path="/tasks" element={<h1>Aufgabenformular</h1>} /><Route path="/reports" element={<h1>Auswertungen</h1>} /></Routes></>; }
const mount = (path = '/assistant?conversation=a', strict = false) => { const element = <MemoryRouter initialEntries={[path]}><App /></MemoryRouter>; return render(strict ? <StrictMode>{element}</StrictMode> : element); };
async function ready() {
  await waitFor(() => expect(screen.getByLabelText('Ihre Nachricht')).toBeEnabled());
  await screen.findByRole('option', { name: 'Lokale Regelprüfung' });
  const provider = screen.getByLabelText('Assistent auswählen'); if (provider.value !== 'local' && !provider.disabled) fireEvent.change(provider, { target: { value: 'local' } });
  await screen.findByText('Lokal verfügbar');
  const context = document.getElementById('assistant-context'); if (context && !context.open) fireEvent.click(context.querySelector('summary'));
}
async function accounts() { fireEvent.click(screen.getByRole('button', { name: 'Konten und Modelle', exact: true })); return screen.findByRole('dialog', { name: 'Konten und Modelle' }); }
const body = text => fireEvent.change(screen.getByLabelText('Ihre Nachricht'), { target: { value: text } });

beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); sessionStorage.clear(); state.owner = 'owner-a';
  state.conversations = [conversation('a'), conversation('b')]; state.runs = {}; state.messages = {}; state.files = {}; state.proposals = {};
  state.capabilities = { providers: [{ id: 'local', label: 'Lokale Analyse', available: true, models: [], web_research: false }, { id: 'codex', label: 'ChatGPT', available: true, models: [{ id: 'verified-model', label: 'Verfügbares Modell' }], web_research: true }, { id: 'claude', label: 'Claude', available: false, reason: 'Claude Code ist nicht installiert.', models: [], web_research: false }], attachment_max_bytes: 8 * 1024 * 1024, allowed_mime_types: ['application/pdf', 'image/png', 'text/plain'] };
  state.connections = { local: { status: 'connected', connected: true, models: [] }, codex: { status: 'disconnected', connected: false, models: [{ id: 'verified-model', label: 'Verfügbares Modell' }] }, claude: { status: 'unavailable', connected: false } };
  api.captureSession.mockReturnValue(() => {});
  api.get.mockImplementation(async path => {
    const url = new URL(path, 'http://localhost'); const parts = url.pathname.split('/');
    if (url.pathname === '/assistant/capabilities') return state.capabilities;
    if (url.pathname === '/assistant/conversations') return { items: state.conversations, next_cursor: null };
    if (parts[2] === 'connections') return state.connections[parts[3]];
    if (parts[2] === 'runs') return state.runs[parts[3]];
    if (parts[2] === 'conversations') {
      const id = parts[3];
      if (!parts[4]) return state.conversations.find(item => item.id === id);
      if (parts[4] === 'messages') return { items: state.messages[id] || [], next_cursor: null };
      if (parts[4] === 'runs') return { items: Object.values(state.runs).filter(item => item.conversation_id === id), next_cursor: null };
      if (parts[4] === 'attachments') return { items: state.files[id] || [] };
      if (parts[4] === 'proposals') return { items: state.proposals[id] || [] };
    }
    if (url.pathname === '/search') return { results: [{ entity_type: 'property', id: 'p1', display: 'Gleiches Haus', detail: 'Straße A' }, { entity_type: 'property', id: 'p2', display: 'Gleiches Haus', detail: 'Straße B' }], next_cursor: null };
    throw new Error(`Unerwartete Abfrage ${path}`);
  });
  api.post.mockImplementation(async (path, payload) => {
    if (path === '/assistant/conversations') { const created = { ...conversation('new', payload.provider), model: payload.model, title: payload.title }; state.conversations.push(created); return created; }
    if (/\/conversations\/[^/]+\/runs$/.test(path)) {
      const id = path.split('/')[3]; const accepted = run('run-1', id); state.runs[accepted.id] = accepted;
      state.messages[id] = [{ id: 'm1', role: 'user', content: payload.content, run_id: accepted.id, attachment_ids: payload.attachment_ids, created_at: stamp }];
      state.conversations = state.conversations.map(item => item.id === id ? { ...item, revision: item.revision + 1, active_run_id: accepted.id } : item);
      return accepted;
    }
    if (path === '/assistant/context/preview') return { context: { sources: [{ kind: 'property', id: 'p1', title: 'Gleiches Haus', revision: 'source-r1', sha256: 'b'.repeat(64) }], sha256: 'a'.repeat(64), warnings: [] }, findings: [{ message: 'Ein lokaler Hinweis' }], documents: [] };
    if (path.endsWith('/cancel')) return { ...state.runs[path.split('/')[3]], state: 'cancelled', revision: 2 };
    if (path.endsWith('/retry')) return run('run-2', 'a');
    if (path.endsWith('/login')) { const provider = path.split('/')[3]; const value = { status: 'connecting', connected: false, pending_login: { id: 'login-1', verification_url: 'https://auth.openai.com/codex/device', user_code: 'TEST-DEVICE' } }; state.connections[provider] = value; return value; }
    if (path.endsWith('/complete')) { const value = { status: 'connected', connected: true, models: [] }; state.connections.claude = value; return value; }
    if (path === '/work-center/notes') return { id: 'note-created' };
    throw new Error(`Unerwarteter Auftrag ${path}`);
  });
  api.upload.mockImplementation(async (path, form) => { const file = form.get('file'); const attachment = { id: 'file-1', name: file.name, mime: file.type, byte_length: file.size, sha256: 'f'.repeat(64), status: 'ready' }; state.files[path.split('/')[3]] = [attachment]; return attachment; });
  api.patch.mockImplementation(async (path, data) => { const id = path.split('/')[3]; const old = state.conversations.find(item => item.id === id); const changed = { ...old, ...data, revision: old.revision + 1 }; state.conversations = state.conversations.map(item => item.id === id ? changed : item); return changed; });
  api.getBlob.mockResolvedValue(new Blob(['image'], { type: 'image/png' }));
  URL.createObjectURL = vi.fn(() => 'blob:assistant-preview'); URL.revokeObjectURL = vi.fn();
  workspace.list.mockResolvedValue({ items: [], next_cursor: null });
  workspace.get.mockRejectedValue(Object.assign(new Error('Kein Entwurf'), { statusCode: 404 }));
  workspace.put.mockImplementation(async (_resource, id, data) => ({ id, ...data, revision: 1 })); workspace.remove.mockResolvedValue({ deleted: true });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('guided administration and evidence-bound investigations', () => {
  const finding = { id: 'finding-1', code: 'unit_area_missing', severity: 'review', message: 'Für diese Einheit ist keine Fläche erfasst.', next_step: 'Originalakte prüfen.', evidence: [{ kind: 'unit', id: 'u1', title: 'Wohnung Blau', href: '/units/u1', revision: 'r1', sha256: 'b'.repeat(64) }] };
  const completed = () => {
    state.runs['run-1'] = { ...run('run-1', 'a', 'completed'), findings: [finding], local_checks: { as_of: '2026-10-18', scope: 'explicit_selection' } };
    state.messages.a = [{ id: 'answer', role: 'assistant', content: 'Prüfung abgeschlossen.', run_id: 'run-1', provider: 'local', created_at: stamp, findings: [finding] }];
  };
  it('offers workflows throughout a chat and appends them without sending or changing data permissions', async () => {
    state.conversations[0] = { ...conversation('a', 'codex'), data_scope: 'none' };
    state.connections.codex.connected = true; state.connections.codex.status = 'connected';
    mount(); await screen.findByText('Verbunden', {}, { timeout: 5000 }); body('Mein eigener Kontext');
    fireEvent.click(screen.getByText('Verwaltungsaufträge'));
    fireEvent.click(screen.getByRole('button', { name: /Unstimmigkeiten prüfen Fristen/ }));
    expect(screen.getByLabelText('Ihre Nachricht').value).toMatch(/^Mein eigener Kontext\n\nUntersuche Unstimmigkeiten/);
    expect(screen.getByLabelText('Datenzugriff')).toHaveValue('none'); expect(api.post).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Ihre Nachricht')).toHaveFocus();
  });
  it('presents local evidence as links and prepares a task in the existing workbasket without saving a domain record', async () => {
    completed(); const base = api.post.getMockImplementation();
    api.post.mockImplementation(async (path, payload) => path.endsWith('/prepare-task') ? { run: { ...state.runs['run-1'], revision: 2, finding_proposals: { 'finding-1': 'task-proposal' } }, proposal: { id: 'task-proposal', conversation_id: 'a', revision: 1, state: 'proposed', payload: { kind: 'task', values: { title: 'Fläche prüfen', status: 'open' }, evidence: finding.evidence } } } : base(path, payload));
    mount(); await ready();
    const region = screen.getByRole('region', { name: 'Belegte Prüfhinweise' });
    expect(within(region).getByRole('link', { name: 'Wohnung Blau' })).toHaveAttribute('href', '/units/u1');
    fireEvent.click(within(region).getByRole('button', { name: 'Klärungsaufgabe vorbereiten' }));
    await screen.findByText('Im Arbeitskorb vorbereitet'); await screen.findByText('Fläche prüfen');
    expect(api.post.mock.calls.filter(([path]) => path.endsWith('/prepare-task'))).toHaveLength(1);
    expect(api.post.mock.calls.some(([path]) => path === '/tasks' || path.endsWith('/save'))).toBe(false);
    expect(screen.queryByRole('button', { name: 'Klärungsaufgabe vorbereiten' })).not.toBeInTheDocument();
  });
  it('reconciles an uncertain finding preparation with the identical command after reload', async () => {
    completed(); const base = api.post.getMockImplementation(); let lost = true;
    api.post.mockImplementation(async (path, payload) => {
      if (!path.endsWith('/prepare-task')) return base(path, payload);
      if (lost) { lost = false; throw new Error('Vorbereitung unbestätigt'); }
      return { run: { ...state.runs['run-1'], revision: 2, finding_proposals: { 'finding-1': 'task-proposal' } }, proposal: { id: 'task-proposal', conversation_id: 'a', revision: 1, state: 'proposed', payload: { kind: 'task', values: { title: 'Fläche prüfen' } } } };
    });
    const view = mount(); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Klärungsaufgabe vorbereiten' })); await screen.findByText('Vorbereitung unbestätigt');
    const original = api.post.mock.calls.find(([path]) => path.endsWith('/prepare-task'))[1];
    view.unmount(); mount(); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Klärungsaufgabe vorbereiten' })); await screen.findByText('Im Arbeitskorb vorbereitet');
    expect(api.post.mock.calls.filter(([path]) => path.endsWith('/prepare-task'))[1][1]).toEqual(original);
  });
  it('keeps old findings readable but blocks stale actions and directs existing tasks to their own record', async () => {
    completed(); state.runs['run-1'].verification_status = 'stale';
    mount(); await ready(); expect(screen.getByRole('button', { name: 'Klärungsaufgabe vorbereiten' })).toBeDisabled();
    cleanup(); state.runs['run-1'].verification_status = 'current'; state.runs['run-1'].findings = [{ ...finding, evidence: [{ kind: 'task', id: 't1', title: 'Vorhandene Aufgabe', href: '/tasks?focus_id=t1' }] }];
    mount(); await ready(); expect(screen.getByRole('link', { name: 'Vorhandene Aufgabe' })).toHaveAttribute('href', '/tasks?focus_id=t1');
    expect(screen.queryByRole('button', { name: 'Klärungsaufgabe vorbereiten' })).not.toBeInTheDocument();
  });
});

describe('assistant providers and explicit cloud controls', () => {
  it('starts with explicit cloud onboarding, authorized scope and a compact closed working context instead of a silent local answer', async () => {
    mount('/assistant'); await screen.findByText('Verbinden Sie Ihren Verwaltungsassistenten');
    expect(screen.getByLabelText('Assistent auswählen')).toHaveValue('codex'); expect(screen.getByLabelText('Datenzugriff')).toHaveValue('authorized');
    expect(document.getElementById('assistant-context')).not.toHaveAttribute('open'); expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    body('Warum fehlt hier Miete?'); expect(screen.getByRole('button', { name: 'Senden' })).toBeDisabled(); expect(api.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Lokal prüfen ohne KI-Konto' })); await screen.findByText('Lokal verfügbar'); expect(screen.getByLabelText('Datenzugriff')).toHaveValue('selected');
  });

  it.each(['authorized', 'selected', 'none'])('persists and sends the explicit %s data scope with its correct source/report boundaries', async data_scope => {
    state.conversations[0] = { ...state.conversations[0], provider: 'codex', data_scope: 'authorized' }; state.connections.codex = { status: 'connected', connected: true, models: [] };
    localStorage.setItem('workspace:owner-a:assistant:draft:a', JSON.stringify({ body: '', attachments: [], context: [{ kind: 'property', id: 'p1', title: 'Haus' }], data_scope: 'authorized', report: { version: 2, kind: 'cash-v2', as_of: '2026-10-18', property_id: 'p1' } }));
    mount(); await screen.findByText('Verbunden'); fireEvent.change(screen.getByLabelText('Datenzugriff'), { target: { value: data_scope } });
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/assistant/conversations/a', expect.objectContaining({ data_scope })));
    body('Bitte den Auftrag bearbeiten'); fireEvent.click(screen.getByRole('button', { name: 'Senden' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assistant/conversations/a/runs', expect.objectContaining({ data_scope, context: expect.objectContaining({ property_ids: data_scope === 'none' ? [] : ['p1'] }), report: data_scope === 'none' ? null : expect.objectContaining({ property_id: 'p1' }) })));
  });

  it('keeps uploaded files when changing the provider of the same conversation before sending', async () => {
    state.capabilities.providers[2].available = true; state.connections.claude = { status: 'connected', connected: true, models: [] };
    mount('/assistant'); await screen.findByText('Verbinden Sie Ihren Verwaltungsassistenten');
    const file = new File(['Beleg'], 'Original.txt', { type: 'text/plain' }); fireEvent.change(document.querySelector('input[type="file"]'), { target: { files: [file] } });
    await within(screen.getByRole('group', { name: 'Dateiauswahl für die Nachricht' })).findByRole('button', { name: 'Datei ansehen: Original.txt' }); await waitFor(() => expect(screen.getByLabelText('Assistent auswählen')).toBeEnabled());
    body('Lies diese Datei'); fireEvent.change(screen.getByLabelText('Assistent auswählen'), { target: { value: 'claude' } }); await screen.findByText('Verbunden');
    expect(api.patch).toHaveBeenCalledWith('/assistant/conversations/new', expect.objectContaining({ provider: 'claude', model: null, expected_revision: 1 }));
    expect(within(screen.getByRole('group', { name: 'Dateiauswahl für die Nachricht' })).getByRole('button', { name: 'Datei ansehen: Original.txt' })).toBeInTheDocument(); expect(screen.getByLabelText('Ihre Nachricht')).toHaveValue('Lies diese Datei'); await waitFor(() => expect(screen.getByRole('button', { name: 'Senden' })).toBeEnabled()); fireEvent.click(screen.getByRole('button', { name: 'Senden' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assistant/conversations/new/runs', expect.objectContaining({ attachment_ids: ['file-1'], data_scope: 'authorized' })));
  });

  it('shows a genuine account status probe separately from a successful model response and closes setup with Escape', async () => {
    state.connections.codex = { status: 'connected', connected: true, models: [], client_available: true, model_discovery_status: 'unavailable', account_access_verified_by_inference: false };
    const base = api.post.getMockImplementation(); api.post.mockImplementation((path, payload) => path === '/assistant/connections/codex/probe' ? Promise.resolve({ ...state.connections.codex, auth_probe_status: 'verified' }) : base(path, payload));
    mount('/assistant'); await screen.findByText('Verbunden'); const opener = screen.getByRole('button', { name: 'Konten und Modelle' }); opener.focus(); fireEvent.click(opener);
    const dialog = await screen.findByRole('dialog', { name: 'Konten und Modelle' }); expect(within(dialog).getByText(/erfolgreiche Modellantwort.*noch nicht bestätigt/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Anmeldestatus prüfen' })); await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assistant/connections/codex/probe', {}));
    expect(within(dialog).queryByText('Eine Modellantwort wurde mit diesem Konto erfolgreich verarbeitet.')).not.toBeInTheDocument(); fireEvent.keyDown(document, { key: 'Escape' }); expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); expect(opener).toHaveFocus();
  });

  it('manages another account without changing the conversation provider and refreshes capabilities after actions and closing', async () => {
    state.conversations[0].provider = 'codex'; state.connections.codex = { status: 'connected', connected: true, models: [{ id: 'verified-model', label: 'Verfügbares Modell' }] };
    state.capabilities.providers[2] = { id: 'claude', label: 'Claude', available: true, models: [] }; state.connections.claude = { status: 'connected', connected: true, models: [], account_access_verified_by_inference: false };
    const base = api.post.getMockImplementation(); api.post.mockImplementation(async (path, payload) => {
      if (path === '/assistant/connections/claude/probe') { state.connections.claude = { ...state.connections.claude, auth_probe_status: 'verified' }; return state.connections.claude; }
      if (path === '/assistant/connections/claude/disconnect') { state.connections.claude = { status: 'disconnected', connected: false, models: [] }; state.capabilities = { ...state.capabilities, providers: state.capabilities.providers.map(item => item.id === 'claude' ? { ...item, connected: false } : item) }; return state.connections.claude; }
      return base(path, payload);
    });
    mount(); await screen.findByText('Verbunden'); const dialog = await accounts();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Claude', exact: true })); await within(dialog).findByText('Angemeldet');
    expect(screen.getByLabelText('Assistent auswählen')).toHaveValue('codex'); expect(api.patch).not.toHaveBeenCalled();
    const countCapabilities = () => api.get.mock.calls.filter(([path]) => path === '/assistant/capabilities').length; const initial = countCapabilities();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Anmeldestatus prüfen' })); await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assistant/connections/claude/probe', {})); await waitFor(() => expect(countCapabilities()).toBeGreaterThan(initial));
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Kontoverbindung trennen' })).toBeEnabled()); fireEvent.click(within(dialog).getByRole('button', { name: 'Kontoverbindung trennen' })); await within(dialog).findByText('Nicht angemeldet');
    expect(api.post).toHaveBeenCalledWith('/assistant/connections/claude/disconnect', {}); expect(screen.getByLabelText('Assistent auswählen')).toHaveValue('codex'); expect(screen.getByText('Verbunden')).toBeInTheDocument(); expect(screen.getByRole('option', { name: /Verfügbares Modell/ })).toBeInTheDocument(); expect(api.patch).not.toHaveBeenCalled();
    const beforeClose = countCapabilities(); fireEvent.click(within(dialog).getByRole('button', { name: 'Zur Unterhaltung' })); await waitFor(() => expect(countCapabilities()).toBeGreaterThan(beforeClose)); expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); expect(state.conversations[0].provider).toBe('codex'); expect(api.patch).not.toHaveBeenCalled();
  });

  it('displays actual application activities, incomplete coverage and the provider of a historical answer', async () => {
    state.runs['run-1'] = { ...run(), state: 'completed', activity: [{ id: 'call-1', sequence: 1, tool: 'search_records', status: 'completed', summary: 'Mietverträge gefunden', at: stamp, coverage: { returned: 2, has_more: true, truncated: false }, sources: [{ kind: 'contract', id: 'c1', title: 'Mietvertrag Wohnung 2', href: '/contracts?focus_id=c1', revision: 'r1', sha256: 'a'.repeat(64) }] }, { id: 'call-2', sequence: 2, tool: 'compute_report', status: 'failed', summary: 'Zahlungsübersicht prüfen', error: { code: 'missing_period', message: 'Der Zeitraum fehlt.' }, sources: [] }] };
    state.messages.a = [{ id: 'answer', role: 'assistant', provider: 'claude', model: 'verified-model', content: 'Frühere Antwort', run_id: 'run-1', created_at: stamp }];
    mount(); await ready(); fireEvent.click(screen.getByText(/Arbeitsprotokoll · 2 Schritte/)); expect(screen.getByText('Mietverträge gefunden')).toBeInTheDocument(); expect(screen.getByText('Der Zeitraum fehlt.')).toBeInTheDocument(); expect(screen.getByText(/Weitere Ergebnisse vorhanden/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Mietvertrag Wohnung 2' })).toHaveAttribute('href', '/contracts?focus_id=c1'); expect(within(screen.getByRole('article')).getByText('Claude')).toBeInTheDocument();
  });

  it('retains active chat files for a follow-up and explicitly excludes a removed file without deleting its original', async () => {
    state.conversations[0] = { ...state.conversations[0], attachment_ids: ['file-1'] }; state.files.a = [{ id: 'file-1', name: 'Vertrag.pdf', mime: 'application/pdf', byte_length: 100 }];
    mount(); await ready(); const selection = screen.getByRole('group', { name: 'Dateiauswahl für die Nachricht' }); expect(within(selection).getByRole('button', { name: 'Datei ansehen: Vertrag.pdf' })).toBeInTheDocument();
    fireEvent.click(within(selection).getByRole('button', { name: 'Datei entfernen: Vertrag.pdf' })); body('Ohne diese Datei prüfen'); fireEvent.click(screen.getByRole('button', { name: 'Lokal prüfen' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assistant/conversations/a/runs', expect.objectContaining({ attachment_ids: [], excluded_attachment_ids: ['file-1'] })));
    expect(api.del).not.toHaveBeenCalled();
  });

  it.each([false, true])('restores discovered working sources and preserves them unless explicitly removed (%s)', async remove => {
    state.conversations[0] = { ...state.conversations[0], context: { contract_ids: ['contract-1'] }, context_sources: [{ kind: 'contract', id: 'contract-1', title: 'Mietvertrag Wohnung 2', href: '/contracts?focus_id=contract-1', revision: 'r1', sha256: 'a'.repeat(64) }] };
    mount(); await ready(); expect(screen.getByLabelText('Gewählte Akten').getAttribute('class')).toContain('assistant-context-chips');
    if (remove) fireEvent.click(screen.getByRole('button', { name: 'Kontext entfernen: Mietvertrag Wohnung 2' }));
    body('Prüfe den aktuellen Stand'); fireEvent.click(screen.getByRole('button', { name: 'Lokal prüfen' }));
    await waitFor(() => expect(api.post).toHaveBeenCalled()); const payload = api.post.mock.calls.find(([path]) => path.endsWith('/runs'))[1];
    if (remove) expect(Object.values(payload.context).every(ids => ids.length === 0)).toBe(true); else expect(Object.hasOwn(payload, 'context')).toBe(false);
  });
  it('keeps local reports available and distinguishes a local analysis from a disconnected cloud account', async () => {
    state.capabilities.max_attachments = 12; state.capabilities.request_attachment_max_bytes = 128 * 1024 * 1024;
    mount('/assistant'); await ready();
    expect(screen.getByText(/Höchstens 12 Dateien je Nachricht/)).toHaveTextContent('Insgesamt höchstens 128.0 MB je Nachricht');
    expect(screen.getByRole('link', { name: 'Lokale Auswertungen' })).toHaveAttribute('href', '/reports');
    expect(screen.getByRole('checkbox', { name: /Internetrecherche zulassen/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Assistent auswählen'), { target: { value: 'codex' } }); await accounts();
    expect(await screen.findByRole('button', { name: 'Mit ChatGPT anmelden' })).toBeInTheDocument();
    expect(screen.getByText(/Gerätecode-Anmeldung in den ChatGPT-Sicherheitseinstellungen freigeben/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Offizielle Anmeldehilfe' })).toHaveAttribute('href', 'https://learn.chatgpt.com/docs/auth#preferred-device-code-authentication-beta');
    body('Bitte prüfen'); expect(screen.getByRole('button', { name: 'Senden' })).toBeDisabled();
    expect(screen.getByLabelText('KI-Modell')).toHaveValue('');
    expect(screen.getByRole('option', { name: /Verfügbares Modell/ })).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Konten und Modelle' })).getByRole('button', { name: 'Claude', exact: true }));
    expect(await screen.findByText('Claude Code ist nicht installiert.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Mit Claude anmelden' })).not.toBeInTheDocument();
  });

  it('shows the provider device code without requesting a password or storing the login state', async () => {
    mount('/assistant'); await ready();
    fireEvent.change(screen.getByLabelText('Assistent auswählen'), { target: { value: 'codex' } }); await accounts();
    fireEvent.click(await screen.findByRole('button', { name: 'Mit ChatGPT anmelden' }));
    expect(await screen.findByText('TEST-DEVICE')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Anmeldung im Browser öffnen' })).toHaveAttribute('href', 'https://auth.openai.com/codex/device');
    expect(screen.queryByLabelText('Einmal-Anmeldecode')).not.toBeInTheDocument();
    expect([...Object.values(localStorage)].join('')).not.toContain('TEST-DEVICE');
    expect(api.post).toHaveBeenCalledWith('/assistant/connections/codex/login', {});
  });

  it('submits a Claude one-time code only to the completion endpoint and immediately clears the input', async () => {
    state.capabilities.providers[2].available = true;
    state.connections.claude = { status: 'connecting', connected: false, pending_login: { id: 'claude-login', can_submit_code: true, auth_url: 'https://claude.ai/oauth/authorize' } };
    mount('/assistant'); await ready();
    fireEvent.change(screen.getByLabelText('Assistent auswählen'), { target: { value: 'claude' } }); await accounts();
    const code = await screen.findByLabelText('Einmal-Anmeldecode'); fireEvent.change(code, { target: { value: 'one-use-test-code' } });
    fireEvent.click(screen.getByRole('button', { name: 'Anmeldung bestätigen' }));
    expect(code).toHaveValue('');
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assistant/connections/claude/login/claude-login/complete', { code: 'one-use-test-code' }));
    expect([...Object.values(localStorage)].join('')).not.toContain('one-use-test-code');
  });

  it.each(['failed', 'cancelled', 'expired', 'completed'])('immediately allows a new login after a %s attempt', async status => {
    state.connections.codex = { status: 'disconnected', connected: false, pending_login: { id: 'old-login', status, error: 'Voriger Versuch beendet' } };
    mount('/assistant'); await ready(); fireEvent.change(screen.getByLabelText('Assistent auswählen'), { target: { value: 'codex' } }); await accounts();
    fireEvent.click(await screen.findByRole('button', { name: 'Erneut anmelden' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assistant/connections/codex/login', {}));
    expect(await screen.findByRole('button', { name: 'Anmeldung abbrechen' })).toBeInTheDocument();
  });

  it.each(['http://auth.openai.com/codex/device', 'https://evil.example.test/login', 'https://auth.openai.com.evil.example.test/login', 'https://auth.openai.com:8443/login', 'https://user:password@auth.openai.com/login'])('does not expose an unsafe login URL %s', async verification_url => {
    state.connections.codex = { status: 'connecting', connected: false, pending_login: { id: 'login-1', status: 'running', verification_url } };
    mount('/assistant'); await ready(); fireEvent.change(screen.getByLabelText('Assistent auswählen'), { target: { value: 'codex' } }); await accounts();
    await screen.findByRole('button', { name: 'Anmeldung abbrechen' }); expect(screen.queryByRole('link', { name: 'Anmeldung im Browser öffnen' })).not.toBeInTheDocument();
  });

  it('opens the existing task form directly from a local starter without promising a model-generated task', async () => {
    mount('/assistant'); await ready(); fireEvent.click(screen.getByRole('link', { name: 'Aufgabe im Fachformular anlegen' }));
    await screen.findByRole('heading', { name: 'Aufgabenformular' }); expect(screen.getByTestId('location')).toHaveTextContent('neu=1'); expect(api.post).not.toHaveBeenCalled();
  });

  it('sends web research only after the explicit cloud checkbox is selected', async () => {
    state.conversations[0].provider = 'codex'; state.connections.codex = { status: 'connected', connected: true, models: [] };
    mount(); await screen.findByText('Verbunden');
    const web = screen.getByRole('checkbox', { name: /Internetrecherche zulassen/ }); expect(web).not.toBeChecked();
    fireEvent.click(web); body('Quellen im Internet prüfen'); fireEvent.click(screen.getByRole('button', { name: 'Senden' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assistant/conversations/a/runs', expect.objectContaining({ web_research: true, expected_revision: 1, idempotency_key: expect.any(String) })));
  });
});

describe('private conversations, durable runs and files', () => {
  it('keeps separate unsent drafts when switching chats and never sends on plain Enter', async () => {
    mount(); await ready(); body('Entwurf A');
    fireEvent.keyDown(screen.getByLabelText('Ihre Nachricht'), { key: 'Enter' }); expect(api.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /Chat b/ })); await ready(); expect(screen.getByLabelText('Ihre Nachricht')).toHaveValue(''); body('Entwurf B');
    fireEvent.click(screen.getByRole('button', { name: 'Chat öffnen: Chat a', exact: true })); await ready(); expect(screen.getByLabelText('Ihre Nachricht')).toHaveValue('Entwurf A');
    expect(localStorage.getItem('workspace:owner-a:assistant:draft:b')).toContain('Entwurf B');
  });

  it('repeats an uncertain submission with exactly the same body, revision and durable key', async () => {
    const base = api.post.getMockImplementation(); let first = true;
    api.post.mockImplementation((path, data) => path.endsWith('/runs') && first ? (first = false, Promise.reject(new Error('Antwort verloren'))) : base(path, data));
    mount(); await ready(); body('Ein Auftrag'); fireEvent.click(screen.getByRole('button', { name: 'Lokal prüfen' }));
    await screen.findByRole('button', { name: 'Übermittlung abgleichen' });
    const request = api.post.mock.calls[0][1]; expect(request.web_research).toBe(false); expect(request.report).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Übermittlung abgleichen' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2)); expect(api.post.mock.calls[1][1]).toEqual(request);
    await waitFor(() => expect(screen.getByLabelText('Ihre Nachricht')).toHaveValue(''));
    expect(localStorage.getItem('workspace:owner-a:assistant:command:a')).toBeNull();
  });

  it('discards a delayed old conversation response after selecting another chat', async () => {
    const old = deferred(); const base = api.get.getMockImplementation();
    api.get.mockImplementation(path => path === '/assistant/conversations/a' ? old.promise : base(path));
    mount(); await screen.findByRole('button', { name: /Chat b/ }); fireEvent.click(screen.getByRole('button', { name: /Chat b/ })); await ready(); body('Bleibt bei B');
    await act(async () => old.resolve(conversation('a')));
    expect(screen.getByRole('heading', { name: 'Chat b' })).toBeInTheDocument(); expect(screen.getByLabelText('Ihre Nachricht')).toHaveValue('Bleibt bei B');
  });

  it('starts a new private conversation and persists the first run rather than keeping only a browser answer', async () => {
    mount('/assistant'); await ready(); body('Erste Frage'); fireEvent.click(screen.getByRole('button', { name: 'Lokal prüfen' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assistant/conversations', expect.objectContaining({ title: 'Erste Frage', provider: 'local', effort: 'high', idempotency_key: expect.any(String) })));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assistant/conversations/new/runs', expect.objectContaining({ content: 'Erste Frage' })));
    await screen.findByRole('heading', { name: 'Erste Frage' }); expect(screen.getByTestId('location')).toHaveTextContent('conversation=new');
  });

  it('restores a queued run after reload and cancels it with its current revision', async () => {
    state.runs['run-1'] = { ...run(), revision: 4 }; state.conversations[0].active_run_id = 'run-1';
    mount(); await ready(); fireEvent.click(await screen.findByRole('button', { name: 'Antwort abbrechen' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assistant/runs/run-1/cancel', expect.objectContaining({ expected_revision: 4, idempotency_key: expect.any(String) })));
    expect(await screen.findByText('Abgebrochen')).toBeInTheDocument();
  });

  it('never retries an unknown provider result automatically and repeats an uncertain manual retry unchanged', async () => {
    state.runs['run-1'] = run('run-1', 'a', 'unknown');
    const base = api.post.getMockImplementation(); let lost = true;
    api.post.mockImplementation((path, data) => path.endsWith('/retry') && lost ? (lost = false, Promise.reject(new Error('Wiederholung unbestätigt'))) : base(path, data));
    mount(); await ready(); expect(api.post).not.toHaveBeenCalled(); fireEvent.click(screen.getByRole('button', { name: 'Neuen Versuch starten' }));
    await screen.findByRole('alert'); const first = api.post.mock.calls[0][1]; fireEvent.click(screen.getByRole('button', { name: 'Neuen Versuch starten' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2)); expect(api.post.mock.calls[1][1]).toEqual(first);
  });

  it('uploads a dropped image, previews it through an authorized blob request, and removes only its selection', async () => {
    mount(); await ready(); const file = new File(['png'], 'beleg.png', { type: 'image/png' });
    fireEvent.drop(screen.getByRole('form', { name: 'Nachricht verfassen' }), { dataTransfer: { files: [file] } });
    const selectedFiles = within(screen.getByRole('group', { name: 'Dateiauswahl für die Nachricht' }));
    const open = await selectedFiles.findByRole('button', { name: 'Datei ansehen: beleg.png' });
    expect(api.upload).toHaveBeenCalledWith('/assistant/conversations/a/attachments', expect.any(FormData), undefined);
    fireEvent.click(open); const dialog = await screen.findByRole('dialog', { name: 'beleg.png' });
    expect(await within(dialog).findByRole('img', { name: 'beleg.png' })).toHaveAttribute('src', 'blob:assistant-preview');
    expect(api.getBlob).toHaveBeenCalledWith('/assistant/attachments/file-1/download', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    fireEvent.keyDown(document, { key: 'Escape' }); expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Datei entfernen: beleg.png' })); expect(selectedFiles.queryByRole('button', { name: 'Datei ansehen: beleg.png' })).not.toBeInTheDocument(); expect(api.del).not.toHaveBeenCalled();
  });

  it('selects same-named records by exact ID and displays the local context finding', async () => {
    mount(); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Akte hinzufügen' }));
    fireEvent.change(screen.getByLabelText('Akten durchsuchen'), { target: { value: 'Haus' } }); fireEvent.click(screen.getByRole('button', { name: 'Akten suchen' }));
    const results = await screen.findAllByRole('button', { name: 'Hinzufügen' }); fireEvent.click(results[1]);
    expect(screen.getByRole('link', { name: 'Akte öffnen →' })).toHaveAttribute('href', '/properties/p2');
    fireEvent.click(screen.getByRole('button', { name: 'Ausgewählte Quellen lokal prüfen' }));
    await screen.findByText('Ein lokaler Hinweis'); expect(api.post).toHaveBeenCalledWith('/assistant/context/preview', expect.objectContaining({ selection: expect.objectContaining({ property_ids: ['p2'] }) }), undefined);
    body('Akten prüfen'); fireEvent.click(screen.getByRole('button', { name: 'Lokal prüfen' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assistant/conversations/a/runs', expect.objectContaining({ context: expect.objectContaining({ property_ids: ['p2'] }) })));
  });

  it('remounts private state on owner change and does not restore the previous owner draft', async () => {
    const view = mount(); await ready(); body('Private Eingabe A'); state.owner = 'owner-b';
    view.rerender(<MemoryRouter><App /></MemoryRouter>);
    await ready(); expect(screen.getByLabelText('Ihre Nachricht')).toHaveValue('');
    expect(localStorage.getItem('workspace:owner-a:assistant:draft:a')).toContain('Private Eingabe A');
  });

  it('polls a persisted run to completion and refreshes the revision for the next question', async () => {
    state.runs['run-1'] = run(); state.conversations[0].active_run_id = 'run-1'; const base = api.get.getMockImplementation();
    api.get.mockImplementation(async path => {
      if (path === '/assistant/runs/run-1') {
        state.messages.a = [{ id: 'answer', role: 'assistant', content: 'Lokal überprüfte Antwort', run_id: 'run-1', created_at: stamp }];
        state.conversations[0] = { ...state.conversations[0], revision: 3, active_run_id: null };
        return { ...run(), state: 'completed', response: 'Lokal überprüfte Antwort', revision: 3 };
      }
      return base(path);
    });
    mount(); await ready(); expect(await screen.findByText('Lokal überprüfte Antwort', {}, { timeout: 4000 })).toBeInTheDocument();
    body('Nächste Frage'); fireEvent.click(screen.getByRole('button', { name: 'Lokal prüfen' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assistant/conversations/a/runs', expect.objectContaining({ expected_revision: 3 })));
  });

  it('hides historical content when the current run reports lost source access', async () => {
    state.runs['run-1'] = run(); state.conversations[0].active_run_id = 'run-1'; state.messages.a = [{ id: 'secret', role: 'assistant', content: 'Bisher berechtigter Akteninhalt', created_at: stamp }];
    const base = api.get.getMockImplementation(); api.get.mockImplementation(path => path === '/assistant/runs/run-1' ? Promise.reject(Object.assign(new Error('Quelle nicht mehr berechtigt'), { statusCode: 404 })) : base(path));
    mount(); await screen.findByText('Bisher berechtigter Akteninhalt');
    await waitFor(() => expect(screen.queryByText('Bisher berechtigter Akteninhalt')).not.toBeInTheDocument(), { timeout: 4000 });
    expect(screen.getByLabelText('Ihre Nachricht')).toBeDisabled(); expect(screen.queryByRole('button', { name: /Chat a/ })).not.toBeInTheDocument();
  });

  it('keeps actions locked until a completed run has loaded the new conversation revision', async () => {
    state.runs['run-1'] = run(); state.conversations[0].active_run_id = 'run-1';
    const fresh = deferred(); let loading = true; const base = api.get.getMockImplementation();
    api.get.mockImplementation(path => {
      if (path === '/assistant/runs/run-1') { loading = false; return Promise.resolve({ ...run(), state: 'completed', response: 'Fertige Antwort' }); }
      if (path === '/assistant/conversations/a' && !loading) return fresh.promise;
      return base(path);
    });
    mount(); await ready(); fireEvent.click(screen.getByText('Chat verwalten')); fireEvent.change(screen.getByLabelText('Chattitel'), { target: { value: 'Neuer Titel' } });
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/assistant/runs/run-1', expect.anything()), { timeout: 4000 });
    expect(screen.getByRole('button', { name: 'Titel speichern' })).toBeDisabled(); expect(screen.getByRole('button', { name: 'Lokal prüfen' })).toBeDisabled(); expect(screen.queryByText('Abgeschlossen')).not.toBeInTheDocument();
    await act(async () => fresh.resolve({ ...conversation('a'), revision: 4 }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Titel speichern' })).toBeEnabled()); fireEvent.click(screen.getByRole('button', { name: 'Titel speichern' }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/assistant/conversations/a', expect.objectContaining({ expected_revision: 4 })));
  });

  it('retains older message pages before current messages without dropping either page', async () => {
    const base = api.get.getMockImplementation(); api.get.mockImplementation(path => {
      if (path.startsWith('/assistant/conversations/a/messages')) return Promise.resolve(path.includes('cursor=older')
        ? { items: [{ id: 'old', role: 'user', content: 'Ältere Nachricht', created_at: '2026-10-17T08:00:00Z' }], next_cursor: null }
        : { items: [{ id: 'current', role: 'user', content: 'Aktuelle Nachricht', created_at: stamp }], next_cursor: 'older' });
      return base(path);
    });
    mount(); await ready();
    const transcript = screen.getByRole('region', { name: 'Chatverlauf' }); Object.defineProperty(transcript, 'clientHeight', { configurable: true, value: 300 });
    Object.defineProperty(transcript, 'scrollHeight', { configurable: true, get: () => screen.queryByText('Ältere Nachricht') ? 1600 : 1000 });
    transcript.scrollTop = 200; fireEvent.scroll(transcript);
    fireEvent.click(screen.getByRole('button', { name: 'Weitere Nachrichten laden' }));
    await screen.findByText('Ältere Nachricht');
    const rows = screen.getAllByRole('article'); expect(rows[0]).toHaveTextContent('Ältere Nachricht'); expect(rows[1]).toHaveTextContent('Aktuelle Nachricht');
    expect(transcript.scrollTop).toBe(800);
  });

  it('keeps a reader above the end in place while streaming, and follows only after scrolling near the end', async () => {
    state.runs['run-1'] = run(); state.conversations[0].active_run_id = 'run-1'; state.messages.a = [{ id: 'old', role: 'user', content: 'Frühere Nachricht', created_at: stamp }];
    let revision = 1; const base = api.get.getMockImplementation(); api.get.mockImplementation(path => path === '/assistant/runs/run-1' ? Promise.resolve({ ...run(), state: 'running', response: `Streaming Stand ${++revision}`, revision }) : base(path));
    mount(); await ready(); const transcript = screen.getByRole('region', { name: 'Chatverlauf' });
    Object.defineProperty(transcript, 'clientHeight', { configurable: true, value: 300 }); Object.defineProperty(transcript, 'scrollHeight', { configurable: true, value: 1200 });
    transcript.scrollTop = 150; fireEvent.scroll(transcript); await screen.findByText('Streaming Stand 2', {}, { timeout: 4000 }); expect(transcript.scrollTop).toBe(150);
    transcript.scrollTop = 880; fireEvent.scroll(transcript); await screen.findByText('Streaming Stand 3', {}, { timeout: 4000 }); expect(transcript.scrollTop).toBe(1200);
  });

  it('retains older immutable messages and their deepest cursor when the active run completes', async () => {
    state.runs['run-1'] = run(); state.conversations[0].active_run_id = 'run-1';
    const current = { id: 'current', role: 'user', content: 'Aktuelle Nachricht', created_at: stamp }; let completed = false;
    const base = api.get.getMockImplementation(); api.get.mockImplementation(path => {
      if (path === '/assistant/runs/run-1') { completed = true; return Promise.resolve({ ...run(), state: 'completed' }); }
      if (path.startsWith('/assistant/conversations/a/messages')) {
        if (path.includes('cursor=deep')) return Promise.resolve({ items: [{ id: 'oldest', role: 'user', content: 'Älteste Nachricht', created_at: stamp }], next_cursor: null });
        if (path.includes('cursor=older')) return Promise.resolve({ items: [{ id: 'older', role: 'user', content: 'Ältere Seite', created_at: stamp }], next_cursor: 'deep' });
        return Promise.resolve({ items: [current, ...(completed ? [{ id: 'answer', role: 'assistant', content: 'Fertige Antwort', created_at: stamp }] : [])], next_cursor: 'older' });
      }
      return base(path);
    });
    mount(); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Weitere Nachrichten laden' })); await screen.findByText('Ältere Seite');
    await screen.findByText('Fertige Antwort', {}, { timeout: 4000 }); expect(screen.getByText('Ältere Seite')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Weitere Nachrichten laden' })); await screen.findByText('Älteste Nachricht');
    expect(api.get).toHaveBeenCalledWith('/assistant/conversations/a/messages?limit=50&cursor=deep', undefined); expect(screen.getByText('Ältere Seite')).toBeInTheDocument();
  });

  it('adds a local report only after explicit selection and removes it when its source is deselected', async () => {
    mount(); await ready(); const enabled = screen.getByRole('checkbox', { name: 'Lokale Auswertung mitsenden' }); expect(enabled).toBeDisabled(); expect(enabled).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Akte hinzufügen' })); fireEvent.change(screen.getByLabelText('Akten durchsuchen'), { target: { value: 'Haus' } }); fireEvent.click(screen.getByRole('button', { name: 'Akten suchen' }));
    const add = await screen.findAllByRole('button', { name: 'Hinzufügen' }); fireEvent.click(add[1]); fireEvent.click(enabled);
    expect(screen.getByLabelText('Berichtsbezug')).toHaveValue('property:p2');
    fireEvent.change(screen.getByLabelText('Berichtsstichtag'), { target: { value: '2026-10-18' } });
    fireEvent.change(screen.getByLabelText('Berichtszeitraum von'), { target: { value: '2026-01-01' } });
    fireEvent.change(screen.getByLabelText('Berichtszeitraum bis'), { target: { value: '2026-10-18' } });
    const href = screen.getByRole('link', { name: 'Diese Auswahl in lokalen Auswertungen öffnen →' }).getAttribute('href'); const query = new URLSearchParams(href.split('?')[1]);
    expect(query.get('property_id')).toBe('p2'); expect(query.get('as_of')).toBe('2026-10-18'); expect(query.get('date_from')).toBe('2026-01-01');
    body('Auswertung erläutern'); fireEvent.click(screen.getByRole('button', { name: 'Lokal prüfen' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assistant/conversations/a/runs', expect.objectContaining({ report: { version: 2, kind: 'cash-v2', as_of: '2026-10-18', date_from: '2026-01-01', date_to: '2026-10-18', property_id: 'p2' } })));
    await screen.findByText('Auswertung erläutern'); fireEvent.click(screen.getByRole('button', { name: 'Kontext entfernen: Gleiches Haus' })); expect(enabled).not.toBeChecked(); expect(screen.queryByLabelText('Berichtsbezug')).not.toBeInTheDocument();
  });

  it('searches records by button or Enter without submitting the unsent chat message', async () => {
    mount(); await ready(); body('Noch nicht senden'); fireEvent.click(screen.getByRole('button', { name: 'Akte hinzufügen' }));
    const input = screen.getByLabelText('Akten durchsuchen'); fireEvent.change(input, { target: { value: 'Haus' } }); fireEvent.click(screen.getByRole('button', { name: 'Akten suchen' }));
    await screen.findAllByRole('button', { name: 'Hinzufügen' }); expect(api.post).not.toHaveBeenCalled(); expect(screen.getByLabelText('Ihre Nachricht')).toHaveValue('Noch nicht senden');
    fireEvent.keyDown(input, { key: 'Enter' }); await waitFor(() => expect(api.get.mock.calls.filter(([path]) => path.startsWith('/search?'))).toHaveLength(2));
    expect(api.post).not.toHaveBeenCalled(); expect(document.querySelector('form form')).toBeNull();
  });

  it('shows canonical local totals, preserves zero versus missing, and links to the exact original report', async () => {
    localStorage.setItem('workspace:owner-a:assistant:draft:a', JSON.stringify({ body: '', attachments: [], context: [{ kind: 'property', id: 'p1', title: 'Haus' }], report: { version: 2, kind: 'cash-v2', as_of: '2026-10-18', property_id: 'p1' } }));
    const base = api.post.getMockImplementation(); api.post.mockImplementation(async (path, payload) => path === '/assistant/context/preview'
      ? { context: { sources: [], sha256: 'd'.repeat(64), warnings: [] }, finance: { basis: 'cash-v2', currency: 'EUR', totals: { income: '0.00', expense: null, net: '0.00' }, definition: payload.report, result_hash: 'e'.repeat(64) }, findings: [] } : base(path, payload));
    mount(); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Ausgewählte Quellen lokal prüfen' }));
    const proof = await screen.findByRole('region', { name: 'Lokaler Berechnungsnachweis' });
    expect(within(proof).getByText('Einnahmen').nextElementSibling).toHaveTextContent('0,00'); expect(within(proof).getByText('Ausgaben').nextElementSibling).toHaveTextContent('—');
    expect(within(proof).getByText(/Stichtag: 2026-10-18/)).toBeInTheDocument(); expect(proof).toHaveTextContent('e'.repeat(64));
    expect(within(proof).getByRole('link', { name: 'Originalauswertung mit diesen Filtern öffnen →' })).toHaveAttribute('href', '/reports?kind=cash-v2&as_of=2026-10-18&property_id=p1');
  });

  it('renders researched links and source revisions without interpreting provider HTML or script URLs', async () => {
    state.messages.a = [{ id: 'answer', role: 'assistant', content: '## Ergebnis\n\n**Geprüft** [Quelle](https://example.test/evidence) [Originalakte](/properties/p1)\n\n| Monat | Einnahmen | Ausgaben |\n| --- | ---: | ---: |\n| 2026-10 | 0,00 € | — |\n\n[Gefährlich](javascript:alert) [Fremd](//evil.example.test) [Backslash](/\\evil.example.test) <script>nicht ausführen</script>', created_at: stamp, sources: [{ kind: 'property', id: 'p1', title: 'Hausquelle', revision: 'revision-7', sha256: 'f'.repeat(64) }] }];
    mount(); await ready(); expect(screen.getByRole('heading', { name: 'Ergebnis' })).toBeInTheDocument(); expect(screen.getByRole('link', { name: 'Quelle' })).toHaveAttribute('href', 'https://example.test/evidence');
    expect(screen.queryByRole('link', { name: 'Gefährlich' })).not.toBeInTheDocument(); expect(document.querySelector('script')).toBeNull();
    expect(screen.queryByRole('link', { name: 'Fremd' })).not.toBeInTheDocument(); expect(screen.queryByRole('link', { name: 'Backslash' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Originalakte' })).toHaveAttribute('href', '/properties/p1');
    const table = screen.getByRole('table', { name: 'Tabelle aus der Antwort' }); expect(within(table).getByRole('columnheader', { name: 'Einnahmen' })).toBeInTheDocument(); const cells = within(within(table).getByRole('row', { name: /2026-10/ })).getAllByRole('cell'); expect(cells[1]).toHaveTextContent('0,00 €'); expect(cells[2]).toHaveTextContent('—');
    fireEvent.click(screen.getByText('Quellen (1)')); fireEvent.click(screen.getByText('Hausquelle')); expect(screen.getByRole('link', { name: 'Originalakte öffnen →' })).toHaveAttribute('href', '/properties/p1'); expect(screen.getByText('Stand revision-7')).toBeInTheDocument();
  });

  it('renames and archives a private chat through revision-bound commands and restores it from its archive', async () => {
    mount(); await ready(); fireEvent.click(screen.getByText('Chat verwalten')); fireEvent.change(screen.getByLabelText('Chattitel'), { target: { value: 'Geprüfter Verlauf' } }); fireEvent.click(screen.getByRole('button', { name: 'Titel speichern' }));
    await screen.findByRole('heading', { name: 'Geprüfter Verlauf' }); expect(api.patch).toHaveBeenCalledWith('/assistant/conversations/a', expect.objectContaining({ title: 'Geprüfter Verlauf', expected_revision: 1, idempotency_key: expect.any(String) }));
    fireEvent.click(screen.getByRole('button', { name: 'Chat archivieren' })); await screen.findByText(/Dieser Chat ist archiviert/); expect(screen.getByLabelText('Ihre Nachricht')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Archiv anzeigen' })); expect(screen.getByRole('button', { name: /Geprüfter Verlauf/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Aus Archiv zurückholen' })); await waitFor(() => expect(screen.getByLabelText('Ihre Nachricht')).toBeEnabled());
  });

  it('reconciles an archived chat after a lost acknowledgement with the original durable command', async () => {
    let lost = true; const base = api.patch.getMockImplementation(); api.patch.mockImplementation(async (path, payload) => {
      if (lost) { lost = false; await base(path, payload); throw new Error('Archivbestätigung verloren'); }
      return state.conversations.find(item => item.id === path.split('/')[3]);
    });
    mount(); await ready(); fireEvent.click(screen.getByText('Chat verwalten')); fireEvent.click(screen.getByRole('button', { name: 'Chat archivieren' }));
    await screen.findByText('Archivbestätigung verloren'); const command = api.patch.mock.calls[0][1]; cleanup(); mount();
    const reconcile = await screen.findByRole('button', { name: 'Chatänderung abgleichen' }); fireEvent.click(screen.getByText('Chat verwalten'));
    expect(screen.getByRole('button', { name: 'Aus Archiv zurückholen' })).toBeDisabled(); fireEvent.click(reconcile);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Aus Archiv zurückholen' })).toBeEnabled()); expect(api.patch.mock.calls[1][1]).toEqual(command);
    expect(localStorage.getItem('workspace:owner-a:assistant:command:edit:a')).toBeNull();
  });
});

describe('complete private proposal pagination', () => {
  const item = index => ({ id: `proposal-${index}`, revision: 1, state: index >= 50 ? 'proposed' : 'rejected', payload: { kind: 'task', anchor: { kind: 'property', id: 'p1' }, evidence: [], values: { title: `Vorschlag ${index}` } } });

  it('loads more than fifty proposals by cursor, merges duplicate IDs, reloads and honors false has_more', async () => {
    const first = Array.from({ length: 50 }, (_, index) => item(index)); const base = api.get.getMockImplementation();
    api.get.mockImplementation(path => {
      if (path.startsWith('/assistant/conversations/a/proposals')) return Promise.resolve(path.includes('cursor=oldest')
        ? { items: [item(52)], has_more: false, next_cursor: 'must-not-be-followed' }
        : path.includes('cursor=older') ? { items: [{ ...item(49), revision: 2 }, item(50), item(51)], has_more: true, next_cursor: 'oldest' }
          : { items: first, has_more: true, next_cursor: 'older' });
      return base(path);
    });
    mount(); await ready(); expect(screen.getAllByRole('region', { name: 'Vorschlag prüfen: Aufgabe' })).toHaveLength(50);
    fireEvent.click(screen.getByRole('button', { name: 'Weitere Vorschläge laden' })); await screen.findByText('Vorschlag 51');
    expect(screen.getAllByText('Vorschlag 49', { exact: true })).toHaveLength(1); expect(screen.getAllByRole('button', { name: 'Im Fachformular prüfen' })).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Weitere Vorschläge laden' })); await screen.findByText('Vorschlag 52');
    expect(screen.getAllByRole('region', { name: 'Vorschlag prüfen: Aufgabe' })).toHaveLength(53); expect(screen.queryByRole('button', { name: 'Weitere Vorschläge laden' })).not.toBeInTheDocument();
    cleanup(); mount(); await ready(); expect(screen.queryByText('Vorschlag 51')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Weitere Vorschläge laden' })); await screen.findByText('Vorschlag 51');
    expect(api.get).toHaveBeenCalledWith('/assistant/conversations/a/proposals?limit=50&cursor=older', undefined);
    expect(api.get.mock.calls.some(([path]) => path.includes('cursor=must-not-be-followed'))).toBe(false);
  });

  it('retains loaded proposal pages and the oldest cursor after a terminal run refresh', async () => {
    state.runs['run-1'] = run(); state.conversations[0].active_run_id = 'run-1'; let completed = false; const base = api.get.getMockImplementation();
    api.get.mockImplementation(path => {
      if (path === '/assistant/runs/run-1') { completed = true; return Promise.resolve({ ...run(), state: 'completed' }); }
      if (path.startsWith('/assistant/conversations/a/proposals')) return Promise.resolve(path.includes('cursor=oldest') ? { items: [item(52)], has_more: false }
        : path.includes('cursor=older') ? { items: [item(50)], has_more: true, next_cursor: 'oldest' }
          : { items: [item(0), ...(completed ? [item(51)] : [])], has_more: true, next_cursor: 'older' });
      return base(path);
    });
    mount(); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Weitere Vorschläge laden' })); await screen.findByText('Vorschlag 50');
    await screen.findByText('Vorschlag 51', {}, { timeout: 4000 }); expect(screen.getByText('Vorschlag 50')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Weitere Vorschläge laden' })); await screen.findByText('Vorschlag 52');
    expect(api.get).toHaveBeenCalledWith('/assistant/conversations/a/proposals?limit=50&cursor=oldest', undefined);
    expect(screen.getByText('Vorschlag 50')).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Weitere Vorschläge laden' })).not.toBeInTheDocument();
  });

  it('discards loaded proposals, cursors and a late page response when the application owner changes', async () => {
    const late = deferred(); const base = api.get.getMockImplementation();
    api.get.mockImplementation(path => {
      if (path.startsWith('/assistant/conversations/a/proposals')) {
        if (state.owner === 'owner-b') return Promise.resolve({ items: [], has_more: false });
        return path.includes('cursor=older') ? late.promise : Promise.resolve({ items: [item(0)], has_more: true, next_cursor: 'older' });
      }
      return base(path);
    });
    const view = mount(); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Weitere Vorschläge laden' }));
    state.owner = 'owner-b'; view.rerender(<MemoryRouter><App /></MemoryRouter>); await ready();
    await act(async () => late.resolve({ items: [item(50)], has_more: true, next_cursor: 'private-oldest' }));
    expect(screen.queryByText('Vorschlag 0')).not.toBeInTheDocument(); expect(screen.queryByText('Vorschlag 50')).not.toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Weitere Vorschläge laden' })).not.toBeInTheDocument();
  });
});

describe('reviewed proposal handoff to existing forms', () => {
  const proposal = kind => ({ id: 'proposal-1', revision: 1, state: 'proposed', run_id: 'run-1', payload: { kind, anchor: { kind: 'property', id: 'p1' }, evidence: [{ kind: 'property', id: 'p1', revision: 'source-r1', sha256: 'b'.repeat(64) }], values: kind === 'note' ? { body: 'Geprüfter Notizentwurf', conversation_kind: 'note' } : { title: 'Geprüfte Aufgabe', priority: 'medium', status: 'open', property_id: 'p1' } } });
  async function prepare(kind, strict = false) {
    const item = proposal(kind); state.proposals.a = [item]; const base = api.post.getMockImplementation();
    api.post.mockImplementation(async (path, data) => {
      if (path.endsWith('/preview')) return { proposal: item, review: { allowed: true, normalized: item.payload.values, warnings: [], review_hash: 'c'.repeat(64) } };
      if (path.endsWith('/apply')) return { proposal: { ...item, state: 'applied', revision: 2 }, handoff: { draft_id: 'draft-1', to: kind === 'note' ? '/work-center' : '/tasks?neu=1', state: { prefill: item.payload.values, assistant_draft_id: 'draft-1' }, values: item.payload.values, anchor: item.payload.anchor, anchor_revision: 'source-r1', title: 'Gleiches Haus' } };
      return base(path, data);
    });
    mount(undefined, strict); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Im Fachformular prüfen' }));
    await waitFor(() => expect(api.post.mock.calls.some(([path]) => path.endsWith('/apply'))).toBe(true));
  }

  it('passes an approved task draft into the existing new-entry route without creating a task', async () => {
    await prepare('task'); await screen.findByRole('heading', { name: 'Aufgabenformular' });
    expect(screen.getByTestId('location')).toHaveTextContent('assistant_draft_id'); expect(screen.getByTestId('location')).toHaveTextContent('Geprüfte Aufgabe');
    expect(api.post.mock.calls.some(([path]) => path === '/tasks')).toBe(false);
  });

  it('reviews a note in the existing FormModal, saves once through the atomic proposal endpoint and retains its final record after reload', async () => {
    await prepare('note'); const base = api.post.getMockImplementation();
    api.post.mockImplementation(async (path, data) => {
      if (path.endsWith('/save')) { const record = { kind: 'note', id: 'note-1', href: '/properties/p1?tab=notes', title: 'Gespeicherte Notiz' }; const saved = { ...proposal('note'), revision: 3, state: 'saved', record }; state.proposals.a = [saved]; return { proposal: saved, record }; }
      return base(path, data);
    });
    const dialog = await screen.findByRole('dialog', { name: 'Aktennotiz prüfen · Gleiches Haus' });
    expect(within(dialog).getByLabelText('Gesprächsnotiz *')).toHaveValue('Geprüfter Notizentwurf'); expect(api.post.mock.calls.some(([path]) => path.endsWith('/save'))).toBe(false);
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled()); fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/assistant/proposals/proposal-1/save', expect.objectContaining({ expected_revision: 2, values: { body: 'Geprüfter Notizentwurf', conversation_kind: 'note' }, idempotency_key: expect.any(String) })));
    await screen.findByRole('link', { name: 'Gespeicherte Notiz →' }); cleanup(); mount(); await ready();
    expect(screen.getByRole('link', { name: 'Gespeicherte Notiz →' })).toHaveAttribute('href', '/properties/p1?tab=notes'); expect(screen.queryByRole('button', { name: 'Im Fachformular prüfen' })).not.toBeInTheDocument();
    expect(api.post.mock.calls.some(([path]) => path === '/work-center/notes')).toBe(false);
  });

  it('retains a note and replays exactly the same final save after a lost acknowledgement', async () => {
    await prepare('note'); const base = api.post.getMockImplementation(); let lost = true;
    api.post.mockImplementation(async (path, data) => { if (path.endsWith('/save')) { if (lost) { lost = false; throw new Error('Speicherbestätigung verloren'); } const record = { kind: 'note', id: 'note-1', href: '/properties/p1', title: 'Gespeicherte Notiz' }; return { proposal: { ...proposal('note'), state: 'saved', revision: 3, record }, record }; } return base(path, data); });
    const dialog = await screen.findByRole('dialog'); await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled()); fireEvent.submit(dialog.querySelector('form'));
    await screen.findByText('Speicherbestätigung verloren'); expect(within(dialog).getByLabelText('Gesprächsnotiz *')).toHaveValue('Geprüfter Notizentwurf');
    fireEvent.submit(dialog.querySelector('form')); await screen.findByRole('link', { name: 'Gespeicherte Notiz →' });
    const saves = api.post.mock.calls.filter(([path]) => path.endsWith('/save')); expect(saves).toHaveLength(2); expect(saves[1][1]).toEqual(saves[0][1]); expect(localStorage.getItem('workspace:owner-a:assistant:command:save:proposal-1')).toBeNull();
  });

  it('keeps note review mounted until private form-draft cleanup finishes before showing the saved record', async () => {
    await prepare('note'); const base = api.post.getMockImplementation(); const cleanup = deferred(); workspace.remove.mockImplementation(() => cleanup.promise);
    api.post.mockImplementation((path, data) => path.endsWith('/save') ? Promise.resolve({ proposal: { ...proposal('note'), state: 'saved', revision: 3 }, record: { kind: 'note', id: 'note-1', href: '/properties/p1', title: 'Gespeicherte Notiz' } }) : base(path, data));
    const dialog = await screen.findByRole('dialog'); fireEvent.change(within(dialog).getByLabelText('Gesprächsnotiz *'), { target: { value: 'Geprüfte und ergänzte Notiz' } });
    await waitFor(() => expect(workspace.put).toHaveBeenCalled(), { timeout: 3000 }); await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled()); fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(workspace.remove).toHaveBeenCalled()); expect(dialog).toBeInTheDocument(); expect(screen.queryByRole('link', { name: 'Gespeicherte Notiz →' })).not.toBeInTheDocument();
    await act(async () => cleanup.resolve({ deleted: true })); await screen.findByRole('link', { name: 'Gespeicherte Notiz →' }); expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('saves a note once under React StrictMode without falsely reporting an owner or conversation change', async () => {
    await prepare('note', true); const base = api.post.getMockImplementation(); api.post.mockImplementation((path, data) => path.endsWith('/save') ? Promise.resolve({ proposal: { ...proposal('note'), state: 'saved', revision: 3 }, record: { kind: 'note', id: 'strict-note', href: '/properties/p1', title: 'StrictMode Notiz' } }) : base(path, data));
    const dialog = await screen.findByRole('dialog'); await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Speichern', exact: true })).toBeEnabled()); fireEvent.submit(dialog.querySelector('form'));
    await screen.findByRole('link', { name: 'StrictMode Notiz →' }); expect(api.post.mock.calls.filter(([path]) => path.endsWith('/save'))).toHaveLength(1); expect(screen.queryByText(/Die Unterhaltung wurde gewechselt/)).not.toBeInTheDocument();
  });

  it('preserves the existing blank note dialog default for callers without assistant prefill', async () => {
    render(<MemoryRouter><ConversationDialog entityType="property" entityId="p1" entityRevision="source-r1" title="Haus" onClose={() => {}} /></MemoryRouter>);
    const dialog = await screen.findByRole('dialog'); expect(within(dialog).getByLabelText('Gesprächsnotiz *')).toHaveValue(''); expect(within(dialog).getByLabelText('Art *')).toHaveValue('note');
  });

  it('keeps an uncertain proposal decision and confirms the exact same reviewed command', async () => {
    const item = proposal('task'); state.proposals.a = [item]; const base = api.post.getMockImplementation(); let lost = true;
    api.post.mockImplementation(async (path, data) => {
      if (path.endsWith('/preview')) return { proposal: item, review: { allowed: true, warnings: [], review_hash: 'c'.repeat(64) } };
      if (path.endsWith('/apply')) {
        if (lost) { lost = false; throw new Error('Entwurfsbestätigung verloren'); }
        return { proposal: { ...item, revision: 2, state: 'applied' }, handoff: { draft_id: 'stable-draft', to: '/tasks?neu=1', state: { prefill: item.payload.values } } };
      }
      return base(path, data);
    });
    mount(); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Im Fachformular prüfen' }));
    await screen.findByRole('button', { name: 'Vorbereitung abgleichen' }); const sent = api.post.mock.calls.find(([path]) => path.endsWith('/apply'))[1];
    expect(screen.queryByRole('button', { name: 'Im Fachformular prüfen' })).not.toBeInTheDocument(); fireEvent.click(screen.getByRole('button', { name: 'Vorbereitung abgleichen' }));
    await screen.findByRole('heading', { name: 'Aufgabenformular' }); const decisions = api.post.mock.calls.filter(([path]) => path.endsWith('/apply'));
    expect(decisions).toHaveLength(2); expect(decisions[1][1]).toEqual(sent); expect(localStorage.getItem('workspace:owner-a:assistant:command:proposal:proposal-1')).toBeNull();
  });
});
