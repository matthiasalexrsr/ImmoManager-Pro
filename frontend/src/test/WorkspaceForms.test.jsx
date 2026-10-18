import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import FormModal from '../components/FormModal';
import NamedViews from '../components/NamedViews';
import { ConfirmProvider } from '../components/ConfirmDialog';
import { workspace } from '../utils/workspaceClient';
import { api } from '../api';
import useFormDraft from '../hooks/useFormDraft';
import useWorkspaceViewState from '../hooks/useWorkspaceViewState';
import CustomDraftNotice from '../components/CustomDraftNotice';
import ContractWizard from '../pages/ContractWizard';

const auth = vi.hoisted(() => ({ owner: 'viewer-1' }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: auth.owner ? { id: auth.owner } : null }) }));
vi.mock('../utils/workspaceClient', async original => {
  const actual = await original();
  return { ...actual, workspace: { list: vi.fn(), get: vi.fn(), put: vi.fn(), rebase: vi.fn(), remove: vi.fn(), command: () => crypto.randomUUID() } };
});
vi.mock('../api', () => ({ api: { get: vi.fn() } }));

const fields = [{ key: 'full_name', label: 'Name' }, { key: 'email', label: 'E-Mail' }];
const revision = '2026-10-15T10:00:00';
const initial = { id: 'tenant-1', full_name: 'Anna', email: '', updated_at: revision };
beforeEach(() => {
  auth.owner = 'viewer-1';
  localStorage.clear(); sessionStorage.clear(); vi.clearAllMocks();
  window.history.replaceState({}, '', '/tenants');
  workspace.list.mockResolvedValue({ items: [], next_cursor: null });
  workspace.remove.mockResolvedValue({ deleted: true });
  workspace.put.mockImplementation(async (resource, id, body) => ({ id, revision: body.base_revision + 1, ...body,
    source_state: { status: body.source ? 'current' : 'new' }, updated_at: revision }));
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('persistent form drafts', () => {
  it('keeps an explicit discard durable when navigation unmounts before DELETE returns', async () => {
    let deleted = false;
    let finishDelete;
    const saved = { id: 'discarded-draft', revision: 1, context: 'tenants', source: { kind: 'tenant', id: initial.id, revision },
      values: { full_name: 'Entwurf', email: '' }, source_state: { status: 'current' } };
    workspace.list.mockImplementation(async () => ({ items: deleted ? [] : [saved] }));
    workspace.remove.mockImplementationOnce(() => new Promise(resolve => { finishDelete = () => { deleted = true; resolve({ deleted: true }); }; }));
    workspace.put.mockRejectedValue({ statusCode: 409 });
    workspace.get.mockRejectedValue({ statusCode: 404 });
    const first = renderHook(() => useFormDraft({ fields, initial }));
    await waitFor(() => expect(first.result.current.recovery?.id).toBe(saved.id));
    await act(async () => { await first.result.current.resume(saved.values); });
    act(() => first.result.current.stage(saved.values));
    let clearing;
    act(() => { clearing = first.result.current.clear(); });
    await waitFor(() => expect(workspace.remove).toHaveBeenCalledTimes(1));
    const deletion = workspace.remove.mock.calls[0];
    expect(Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index))).toEqual([expect.stringContaining(':completion:')]);
    first.unmount();
    await act(async () => { finishDelete(); await clearing; });
    const reopened = renderHook(() => useFormDraft({ fields, initial }));
    await waitFor(() => expect(reopened.result.current.status).toBe('ready'));
    expect(workspace.remove.mock.calls[1]).toEqual(deletion);
    expect(workspace.put).not.toHaveBeenCalled();
    expect(reopened.result.current.recovery).toBeNull();
    expect(localStorage.length).toBe(0);
  });

  it('shows a source deleted during autosave as copyable recovery and disables domain save', async () => {
    workspace.put.mockImplementation(async (_, id, body) => ({ id, ...body, revision: 1, source_state: { status: 'deleted' } }));
    const onSave = vi.fn();
    const { container } = render(<FormModal title="Mieter" fields={fields} initial={initial} onSave={onSave} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByLabelText('Name')).toBeEnabled());
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Kopierbarer Entwurf' } });
    await screen.findByText('Entwurfsinhalt prüfen und kopieren', {}, { timeout: 3000 });
    expect(screen.getByText('Kopierbarer Entwurf')).toBeInTheDocument();
    expect(container.querySelector('button[type="submit"]')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Entwurf wiederaufnehmen' })).not.toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });
  it('does not close or replace a newer form after an older business save resolves', async () => {
    let finish;
    const onSave = vi.fn(() => new Promise(resolve => { finish = resolve; }));
    const onClose = vi.fn();
    const { container, rerender } = render(<FormModal title="Mieter" fields={fields} initial={initial} onSave={onSave} onClose={onClose} />);
    await waitFor(() => expect(screen.getByLabelText('Name')).toBeEnabled());
    fireEvent.submit(container.querySelector('form'));
    expect(onSave).toHaveBeenCalledTimes(1);
    rerender(<FormModal title="Mieter" fields={fields} initial={{ ...initial, id: 'tenant-2', full_name: 'Neue Akte' }} onSave={onSave} onClose={onClose} />);
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('Neue Akte'));
    await act(async () => { finish(); });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Name')).toHaveValue('Neue Akte');
  });

  it('does not apply an earlier custom recovery after its source changed', async () => {
    let finish;
    let currentKey = 'source-1';
    const onRestore = vi.fn();
    const oldDraft = { enabled: true, sessionKey: currentKey, isCurrent: key => key === currentKey,
      recovery: { values: { notes: 'Alte private Notiz' } }, recover: () => new Promise(resolve => { finish = resolve; }) };
    const { rerender } = render(<CustomDraftNotice draft={oldDraft} onRestore={onRestore} />);
    fireEvent.click(screen.getByText('Entwurf übernehmen'));
    currentKey = 'source-2';
    rerender(<CustomDraftNotice draft={{ ...oldDraft, sessionKey: currentKey, recovery: null }} onRestore={onRestore} />);
    await act(async () => { finish(); });
    expect(onRestore).not.toHaveBeenCalled();
    expect(screen.queryByText('Alte private Notiz')).not.toBeInTheDocument();
  });

  it('preserves both conflicting private drafts and authorizes local reference values before recovery', async () => {
    const pending = { id: 'conflicting-draft', body: { base_revision: 1, idempotency_key: 'uncertain-key',
      context: 'tenants', mode: 'edit', source: { kind: 'tenant', id: initial.id, revision },
      field_keys: ['email', 'full_name'], form_key: 'test-form', values: { full_name: 'Lokaler Stand', email: '' } } };
    const probe = renderHook(() => useFormDraft({ fields, initial }));
    await waitFor(() => expect(probe.result.current.ready).toBe(true));
    act(() => probe.result.current.stage(pending.body.values));
    const key = localStorage.key(0); probe.unmount();
    localStorage.setItem(key, JSON.stringify({ pending, values: pending.body.values }));
    workspace.put.mockRejectedValueOnce({ statusCode: 409 });
    workspace.get.mockResolvedValue({ id: pending.id, revision: 4, values: { full_name: 'Server Stand', email: '' } });
    const hook = renderHook(() => useFormDraft({ fields, initial }));
    await waitFor(() => expect(hook.result.current.recovery?.server_values.full_name).toBe('Server Stand'));
    const sibling = workspace.put.mock.calls[1];
    expect(sibling[1]).not.toBe(pending.id);
    expect(sibling[2]).toMatchObject({ base_revision: 0, values: pending.body.values });
    expect(hook.result.current.recovery.values.full_name).toBe('Lokaler Stand');
  });
  it('recovers edits made before the autosave delay after an authorized server roundtrip', async () => {
    const first = renderHook(() => useFormDraft({ fields, initial }));
    await waitFor(() => expect(first.result.current.ready).toBe(true));
    act(() => first.result.current.stage({ full_name: 'Vor 600 ms', email: '' }));
    expect(workspace.put).not.toHaveBeenCalled();
    const buffered = JSON.parse(localStorage.getItem(localStorage.key(0)));
    expect(buffered.pending.body.values.full_name).toBe('Vor 600 ms');
    first.unmount();
    const second = renderHook(() => useFormDraft({ fields, initial }));
    await waitFor(() => expect(second.result.current.recovery?.values.full_name).toBe('Vor 600 ms'));
    expect(workspace.put).toHaveBeenCalledWith('drafts', buffered.pending.id, buffered.pending.body);
  });

  it('keeps later typing separate from an uncertain command and recovers both in order', async () => {
    let reject;
    workspace.put.mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; }));
    const first = renderHook(() => useFormDraft({ fields, initial }));
    await waitFor(() => expect(first.result.current.ready).toBe(true));
    act(() => first.result.current.stage({ full_name: 'Erster Stand', email: '' }));
    let flush;
    act(() => { flush = first.result.current.flush().catch(() => {}); });
    await waitFor(() => expect(workspace.put).toHaveBeenCalledTimes(1));
    act(() => first.result.current.stage({ full_name: 'Neuester Stand', email: '' }));
    await act(async () => { reject(new Error('Antwort verloren')); await flush; });
    const original = workspace.put.mock.calls[0];
    first.unmount();
    const second = renderHook(() => useFormDraft({ fields, initial }));
    await waitFor(() => expect(second.result.current.recovery?.values.full_name).toBe('Neuester Stand'));
    expect(workspace.put.mock.calls[1]).toEqual(original);
    expect(workspace.put.mock.calls[2][2]).toMatchObject({ base_revision: 1, values: { full_name: 'Neuester Stand' } });
    expect(workspace.put.mock.calls[2][2].idempotency_key).not.toBe(original[2].idempotency_key);
  });

  it('ignores a previous owner autosave response without erasing the next owner pending command', async () => {
    let resolveOld;
    workspace.put.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const hook = renderHook(() => useFormDraft({ fields, initial }));
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    act(() => hook.result.current.stage({ full_name: 'Alter Nutzer', email: '' }));
    let oldFlush;
    act(() => { oldFlush = hook.result.current.flush(); });
    await waitFor(() => expect(workspace.put).toHaveBeenCalledTimes(1));
    const oldCommand = workspace.put.mock.calls[0];
    auth.owner = 'viewer-2'; hook.rerender();
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    act(() => hook.result.current.stage({ full_name: 'Neuer Nutzer', email: '' }));
    await act(async () => { resolveOld({ id: oldCommand[1], revision: 7, values: oldCommand[2].values }); await oldFlush; });
    await act(async () => { await hook.result.current.flush(); });
    expect(workspace.put.mock.calls[1][2]).toMatchObject({ base_revision: 0, values: { full_name: 'Neuer Nutzer' } });
    expect(workspace.put.mock.calls[1][1]).not.toBe(oldCommand[1]);
  });

  it('retries private cleanup after an accepted business write and an uncertain first autosave', async () => {
    workspace.put.mockRejectedValue(new Error('Offline'));
    const first = renderHook(() => useFormDraft({ fields, initial }));
    await waitFor(() => expect(first.result.current.ready).toBe(true));
    act(() => first.result.current.stage({ full_name: 'Bereits fachlich gespeichert', email: '' }));
    await act(async () => { await first.result.current.flush().catch(() => {}); });
    const original = workspace.put.mock.calls[0];
    await act(async () => { await first.result.current.clear({ completed: true }).catch(() => {}); });
    const completionKey = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).find(key => key.includes(':completion:'));
    expect(JSON.parse(localStorage.getItem(completionKey)).completion_pending.pending.body).toEqual(original[2]);
    first.unmount();
    workspace.put.mockImplementation(async (_, id, body) => ({ id, revision: 1, ...body }));
    const second = renderHook(() => useFormDraft({ fields, initial }));
    await waitFor(() => expect(second.result.current.status).toBe('ready'));
    expect(workspace.put.mock.calls.at(-1)).toEqual(original);
    expect(workspace.remove).toHaveBeenCalledWith('drafts', original[1], expect.objectContaining({ base_revision: 1 }));
    expect(second.result.current.recovery).toBeNull();
    expect(localStorage.length).toBe(0);
  });
  it('saves an incomplete draft without executing the domain action', async () => {
    const onSave = vi.fn();
    render(<FormModal title="Mieter" fields={fields} initial={initial} onSave={onSave} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByLabelText('Name')).toBeEnabled());
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: '' } });
    await waitFor(() => expect(workspace.put).toHaveBeenCalled(), { timeout: 2000 });
    expect(workspace.put.mock.calls[0][2]).toMatchObject({ mode: 'edit', source: { kind: 'tenant', id: initial.id, revision }, values: { full_name: '', email: '' } });
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText('Entwurf automatisch gesichert')).toBeInTheDocument();
  });

  it.each(['2026-10-15T11:00:00', revision])('rebases changed source or ancestor after explicit comparison (%s)', async freshRevision => {
    const draft = { id: 'draft-1', revision: 3, context: 'tenants', source: { kind: 'tenant', id: initial.id, revision },
      values: { full_name: 'Entwurf', email: 'neu@example.test' }, source_state: { status: 'changed' } };
    workspace.list.mockResolvedValue({ items: [draft] });
    api.get.mockResolvedValue({ kind: 'tenant', id: initial.id, revision: freshRevision,
      dependency_etags: [{ table: 'tenants', id: initial.id, revision: freshRevision }], values: { ...initial, full_name: 'Aktueller Name', updated_at: freshRevision } });
    workspace.rebase.mockResolvedValue({ ...draft, source: { ...draft.source, revision: freshRevision } });
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { container } = render(<FormModal title="Mieter" fields={fields} initial={initial} onSave={onSave} onClose={vi.fn()} />);
    await screen.findByText('Ungespeicherter Entwurf vorhanden');
    fireEvent.submit(container.querySelector('form')); expect(onSave).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Aktuellen Stand vergleichen'));
    await screen.findByText('Aktueller Name');
    expect(workspace.rebase).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Verglichenen Entwurf übernehmen'));
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('Entwurf'));
    expect(workspace.rebase).toHaveBeenCalledWith('draft-1', expect.objectContaining({ base_revision: 3, source_revision: freshRevision }));
    fireEvent.submit(container.querySelector('form'));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ full_name: 'Entwurf', updated_at: freshRevision })));
  });

  it('retries an uncertain autosave with exactly the same command', async () => {
    workspace.put.mockRejectedValueOnce(new Error('Verbindung unterbrochen')).mockImplementation(async (_, id, body) => ({ id, ...body, revision: 1, source_state: { status: 'current' } }));
    render(<FormModal title="Mieter" fields={fields} initial={initial} onSave={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByLabelText('Name')).toBeEnabled());
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Entwurf' } });
    await screen.findByText(/Entwurf noch nicht auf dem Server gesichert/);
    const first = workspace.put.mock.calls[0];
    fireEvent.click(screen.getByText('Sicherung erneut versuchen'));
    await screen.findByText('Entwurf automatisch gesichert');
    expect(workspace.put.mock.calls[1]).toEqual(first);
  });

  it('compares and explicitly rebases an anchored new note without inventing a note source URL', async () => {
    const anchor = { kind: 'property', id: 'property-1' };
    const draft = { id: 'anchored-draft', revision: 2, context: 'conversation-note', source: null, anchor,
      anchor_revision: revision, values: { body: 'Gesprächsentwurf' }, source_state: { status: 'changed' } };
    workspace.list.mockResolvedValue({ items: [draft] });
    api.get.mockResolvedValue({ ...anchor, revision: 'new-property-revision', title: 'Aktualisierte Immobilie',
      dependency_etags: [{ table: 'properties', id: anchor.id, revision: 'new-property-revision' }], values: { name: 'Aktualisierte Immobilie' } });
    workspace.rebase.mockResolvedValue({ ...draft, anchor_revision: 'new-property-revision', source_state: { status: 'current' } });
    const rebased = vi.fn();
    render(<FormModal title="Notiz" fields={[{ key: 'body', label: 'Notiz' }]} draftContext="conversation-note" draftAnchor={anchor}
      onSave={vi.fn()} onClose={vi.fn()} onDraftRebase={rebased} />);
    fireEvent.click(await screen.findByText('Aktuellen Stand vergleichen'));
    await screen.findByText(/Aktualisierte Immobilie/);
    expect(api.get).toHaveBeenCalledWith('/workspace/source/property/property-1');
    expect(workspace.rebase).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Verglichenen Entwurf übernehmen'));
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Notiz', exact: true })).toHaveValue('Gesprächsentwurf'));
    expect(workspace.rebase).toHaveBeenCalledWith('anchored-draft', expect.objectContaining({ source_revision: 'new-property-revision' }));
    expect(rebased).toHaveBeenCalledWith(expect.objectContaining({ revision: 'new-property-revision', contextOnly: true }));
  });

  it('never stores credential forms', async () => {
    render(<FormModal title="Zugang" fields={[{ key: 'password', label: 'Passwort', type: 'password' }]} onSave={vi.fn()} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Passwort'), { target: { value: 'private-value' } });
    await act(async () => {});
    expect(workspace.list).not.toHaveBeenCalled(); expect(workspace.put).not.toHaveBeenCalled(); expect(localStorage.length).toBe(0);
  });

  it('does not buffer nested credentials in custom editable values', async () => {
    const hook = renderHook(() => useFormDraft({ fields: [{ key: 'occupants' }], context: 'housing-confirmation' }));
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    act(() => hook.result.current.stage({ occupants: [{ name: 'Anna', authorization: 'private-value' }] }));
    expect(localStorage.length).toBe(0);
    expect(workspace.put).not.toHaveBeenCalled();
    expect(hook.result.current.error).toMatch(/Zugangsdaten/);
  });
});

it('accepts wizard snapshots only from the ready current owner iframe', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ json: async () => ({ contract_wizard_available: true }) }));
  const { container, rerender } = render(<ContractWizard />);
  await waitFor(() => expect(container.querySelector('iframe')).not.toBeNull());
  const firstFrame = container.querySelector('iframe');
  firstFrame.contentWindow.immoWizardDraft = { restore: vi.fn() };
  fireEvent.load(firstFrame);
  await act(async () => {});
  act(() => window.dispatchEvent(new MessageEvent('message', { origin: window.location.origin,
    source: firstFrame.contentWindow, data: { type: 'immo-wizard-draft', form: { fields: { name: 'Alter Nutzer' } } } })));
  const firstKey = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).find(key => key.startsWith('workspace:viewer-1:'));
  expect(JSON.parse(localStorage.getItem(firstKey)).values.form.fields.name).toBe('Alter Nutzer');
  auth.owner = 'viewer-2'; rerender(<ContractWizard />);
  const nextFrame = container.querySelector('iframe');
  expect(nextFrame).not.toBe(firstFrame);
  act(() => window.dispatchEvent(new MessageEvent('message', { origin: window.location.origin,
    source: firstFrame.contentWindow, data: { type: 'immo-wizard-draft', form: { fields: { name: 'Verspäteter alter Nutzer' } } } })));
  expect(Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).some(key => key.startsWith('workspace:viewer-2:'))).toBe(false);
  nextFrame.contentWindow.immoWizardDraft = { restore: vi.fn() };
  fireEvent.load(nextFrame); await act(async () => {});
  act(() => window.dispatchEvent(new MessageEvent('message', { origin: window.location.origin,
    source: nextFrame.contentWindow, data: { type: 'immo-wizard-draft', form: { fields: { name: 'Neuer Nutzer' } } } })));
  const nextKey = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).find(key => key.startsWith('workspace:viewer-2:'));
  expect(JSON.parse(localStorage.getItem(nextKey)).values.form.fields.name).toBe('Neuer Nutzer');
});

describe('named views', () => {
  it('does not display a previous context save after changing the workspace', async () => {
    let resolveOld;
    workspace.put.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const config = { search: 'Privater alter Filter' };
    const { rerender } = render(<NamedViews context="tenants#old" config={config} onApply={vi.fn()} />);
    await act(async () => {});
    fireEvent.change(screen.getByLabelText('Name der neuen Ansicht'), { target: { value: 'Alte Ansicht' } });
    fireEvent.click(screen.getByText('Ansicht speichern'));
    const original = workspace.put.mock.calls[0];
    rerender(<NamedViews context="tasks#new" config={{ search: '' }} onApply={vi.fn()} />);
    await act(async () => { resolveOld({ id: original[1], revision: 1, ...original[2] }); });
    expect(screen.queryByRole('option', { name: 'Alte Ansicht' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Name der neuen Ansicht')).toHaveValue('');
  });
  it('stores several names and applies the selected complete configuration', async () => {
    const first = { id: 'v1', revision: 1, name: 'Offene Posten', config: { search: 'offen', column_filters: { status: 'open' } } };
    workspace.list.mockResolvedValue({ items: [first] });
    const onApply = vi.fn();
    const config = { search: 'Haus A', column_filters: {}, sort: null, visible_columns: ['name'], column_order: ['name'], page_size: 25 };
    render(<NamedViews context="tenants#main" config={config} onApply={onApply} />);
    await screen.findByRole('option', { name: 'Offene Posten' });
    fireEvent.change(screen.getByLabelText('Ansicht'), { target: { value: 'v1' } });
    expect(onApply).toHaveBeenCalledWith(first.config);
    fireEvent.change(screen.getByLabelText('Name der neuen Ansicht'), { target: { value: 'Haus A' } });
    fireEvent.click(screen.getByText('Ansicht speichern'));
    await screen.findByRole('option', { name: 'Haus A' });
    expect(screen.getByRole('option', { name: 'Offene Posten' })).toBeInTheDocument();
    expect(workspace.put.mock.calls[0][2]).toMatchObject({ context: 'tenants#main', name: 'Haus A', config, base_revision: 0 });
  });
});

it('treats a null view state as a first visit without applying or failing', async () => {
  vi.useFakeTimers();
  workspace.get.mockResolvedValue(null);
  workspace.put.mockResolvedValue({ id: 'tasks#first', revision: 1, state: { scroll_top: 5 } });
  const apply = vi.fn();
  renderHook(() => useWorkspaceViewState('tasks#first', { scroll_top: 5 }, apply));
  await act(async () => {});
  expect(workspace.get).toHaveBeenCalledWith('view-state', 'tasks#first', undefined, { missing_ok: true });
  expect(apply).not.toHaveBeenCalled();
  await act(async () => { vi.advanceTimersByTime(900); });
  expect(workspace.put.mock.calls.at(-1)).toMatchObject(['view-state', 'tasks#first', { base_revision: 0, state: { scroll_top: 5 } }]);
});

it('ignores a late table-state response from a different context', async () => {
  vi.useFakeTimers();
  workspace.get.mockRejectedValue({ statusCode: 404 });
  let resolveOld;
  workspace.put.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  const hook = renderHook(({ context, state }) => useWorkspaceViewState(context, state, vi.fn()),
    { initialProps: { context: 'tenants#old', state: { scroll_top: 10 } } });
  await act(async () => {});
  await act(async () => { vi.advanceTimersByTime(900); });
  const original = workspace.put.mock.calls[0];
  expect(original[2].base_revision).toBe(0);
  hook.rerender({ context: 'tasks#new', state: { scroll_top: 20 } });
  await act(async () => {});
  await act(async () => { resolveOld({ id: 'tenants#old', revision: 9, state: { scroll_top: 10 } }); });
  await act(async () => { vi.advanceTimersByTime(900); });
  expect(workspace.put.mock.calls[1]).toMatchObject(['view-state', 'tasks#new', { base_revision: 0, state: { scroll_top: 20 } }]);
});

it('saves the latest table position typed while the preceding state write was running', async () => {
  vi.useFakeTimers();
  workspace.get.mockRejectedValue({ statusCode: 404 });
  let resolveFirst;
  workspace.put.mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }));
  const hook = renderHook(({ state }) => useWorkspaceViewState('tenants#scroll', state, vi.fn()),
    { initialProps: { state: { scroll_top: 10 } } });
  await act(async () => {});
  await act(async () => { vi.advanceTimersByTime(900); });
  hook.rerender({ state: { scroll_top: 200 } });
  await act(async () => { vi.advanceTimersByTime(900); });
  expect(workspace.put).toHaveBeenCalledTimes(1);
  await act(async () => { resolveFirst({ id: 'tenants#scroll', revision: 1, state: { scroll_top: 10 } }); });
  expect(workspace.put.mock.calls[1][2]).toMatchObject({ base_revision: 1, state: { scroll_top: 200 } });
});


describe('named-view destructive-action safety', () => {
  const view = { id: 'view-old', revision: 7, name: 'Wichtige Objektfilter', config: { search: 'Alt' } };
  it('asks before deletion; cancel leaves the original server view intact', async () => {
    workspace.list.mockResolvedValue({ items: [view], next_cursor: null });
    render(<ConfirmProvider><NamedViews context="tenants#main" config={{ search: '' }} onApply={vi.fn()} /></ConfirmProvider>);
    await screen.findByRole('option', { name: view.name });
    fireEvent.change(screen.getByLabelText('Ansicht'), { target: { value: view.id } });
    fireEvent.click(screen.getByRole('button', { name: 'Ansicht löschen' }));
    expect(screen.getByRole('dialog')).toHaveTextContent(view.name);
    expect(workspace.remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(workspace.remove).not.toHaveBeenCalled();
    expect(screen.getByRole('option', { name: view.name })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Ansicht löschen' }));
    fireEvent.click(screen.getByRole('button', { name: 'Bestätigen' }));
    await waitFor(() => expect(workspace.remove).toHaveBeenCalledTimes(1));
    expect(workspace.remove).toHaveBeenCalledWith('views', view.id, {
      base_revision: 7, idempotency_key: expect.any(String),
    });
    await waitFor(() => expect(screen.queryByRole('option', { name: view.name })).not.toBeInTheDocument());
  });

  it('cannot delete an old context after a delayed confirmation from another workspace', async () => {
    workspace.list.mockResolvedValue({ items: [view], next_cursor: null });
    const { rerender } = render(<ConfirmProvider>
      <NamedViews context="tenants#old" config={{ search: 'Original' }} onApply={vi.fn()} />
    </ConfirmProvider>);
    await screen.findByRole('option', { name: view.name });
    fireEvent.change(screen.getByLabelText('Ansicht'), { target: { value: view.id } });
    fireEvent.click(screen.getByRole('button', { name: 'Ansicht löschen' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    rerender(<ConfirmProvider>
      <NamedViews context="tasks#new" config={{ search: 'Anders' }} onApply={vi.fn()} />
    </ConfirmProvider>);
    await screen.findByRole('option', { name: view.name });
    fireEvent.click(screen.getByRole('button', { name: 'Bestätigen' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(workspace.remove).not.toHaveBeenCalled();
  });
});
