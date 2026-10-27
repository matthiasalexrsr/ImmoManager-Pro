import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import useFormDraft from '../hooks/useFormDraft';
import useEntityFormDraft from '../hooks/useEntityFormDraft';
import { workspace } from '../utils/workspaceClient';

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'anchor-owner' } }) }));
vi.mock('../utils/workspaceClient', async original => {
  const actual = await original();
  return { ...actual, workspace: { list: vi.fn(), get: vi.fn(), put: vi.fn(), rebase: vi.fn(), remove: vi.fn(), command: () => crypto.randomUUID() } };
});

beforeEach(() => { localStorage.clear(); vi.clearAllMocks(); });
afterEach(cleanup);

it.each(['2026-10-15T12:00:00', '2026-10-15T11:00:00'])('explicitly rebases an anchored create draft without converting it to an edit (%s)', async currentRevision => {
  const anchor = { kind: 'property', id: 'property-1' };
  const values = { body: 'Gespräch noch nicht abschließen' };
  const saved = { id: 'draft-anchor', revision: 3, context: 'conversation-note', mode: 'create', source: null,
    anchor, anchor_revision: '2026-10-15T11:00:00', values, source_state: { status: 'changed', reference: 'anchor' } };
  workspace.list.mockResolvedValue({ items: [saved] });
  workspace.rebase.mockResolvedValue({ ...saved, revision: 4, anchor_revision: currentRevision, source_state: { status: 'current', reference: 'anchor' } });
  const hook = renderHook(() => useFormDraft({ fields: [{ key: 'body' }], context: 'conversation-note', anchor }));
  await waitFor(() => expect(hook.result.current.recovery?.id).toBe(saved.id));
  const tokens = [{ table: 'properties', id: anchor.id, revision: currentRevision }];
  await act(async () => { await hook.result.current.resume(values, currentRevision, tokens); });
  expect(workspace.rebase).toHaveBeenCalledWith(saved.id, expect.objectContaining({ base_revision: 3, source_revision: currentRevision, dependency_etags: tokens, values }));
  expect(hook.result.current.sourceRevision).toBe(currentRevision);
  expect(hook.result.current.recovery).toBeNull();
  expect(workspace.put).not.toHaveBeenCalled();
});

it('requires a fresh explicit comparison after a custom source changes between comparison and recovery', async () => {
  const first = { kind: 'maintenance', id: 'maintenance-1', revision: '2026-10-15T11:00:00', values: { title: 'Fall' },
    dependency_etags: [{ table: 'maintenance_cases', id: 'maintenance-1', revision: '2026-10-15T11:00:00' },
      { table: 'properties', id: 'property-1', revision: '2026-10-15T11:00:00' }] };
  let context = first;
  workspace.get.mockImplementation(async () => context);
  workspace.list.mockResolvedValue({ items: [{ id: 'custom-draft', revision: 1, context: 'maintenance-protocol',
    source: { kind: first.kind, id: first.id, revision: first.revision }, anchor: { kind: first.kind, id: first.id },
    values: { notes: 'Eigene Notiz' }, source_state: { status: 'changed' } }] });
  workspace.rebase.mockImplementation(async (_, body) => ({ id: 'custom-draft', revision: 2,
    source: { kind: first.kind, id: first.id, revision: body.source_revision }, source_state: { status: 'current' } }));
  const hook = renderHook(() => useEntityFormDraft({ context: 'maintenance-protocol', kind: first.kind, id: first.id, fields: [{ key: 'notes' }] }));
  await waitFor(() => expect(hook.result.current.recovery?.id).toBe('custom-draft'));
  await act(async () => { await hook.result.current.compare(async () => ({ notes: 'Verglichener Stand' })); });
  context = { ...first, dependency_etags: [first.dependency_etags[0], { ...first.dependency_etags[1], revision: '2026-10-15T12:00:00' }] };
  await act(async () => { await expect(hook.result.current.recover({ notes: 'Eigene Notiz' })).rejects.toMatchObject({ statusCode: 409 }); });
  expect(workspace.rebase).not.toHaveBeenCalled();
  expect(hook.result.current.status).toBe('changed');
  await act(async () => { await hook.result.current.compare(async () => ({ notes: 'Neu verglichen' })); });
  await act(async () => { await hook.result.current.recover({ notes: 'Eigene Notiz' }); });
  expect(workspace.rebase).toHaveBeenCalledWith('custom-draft', expect.objectContaining({ dependency_etags: context.dependency_etags }));
});
