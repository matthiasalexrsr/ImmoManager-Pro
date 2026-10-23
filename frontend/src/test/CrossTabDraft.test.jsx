import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import useFormDraft from '../hooks/useFormDraft';
import { workspace } from '../utils/workspaceClient';
import { setWorkspaceOwner } from '../utils/workspaceIdentity';

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'account-a' } }) }));
vi.mock('../utils/workspaceClient', () => ({
  FORM_KINDS: { contacts: 'contact' }, formContext: () => 'contacts',
  workspace: { list: vi.fn(), put: vi.fn(), command: () => crypto.randomUUID() },
}));
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); setWorkspaceOwner('account-a'); workspace.list.mockResolvedValue({ items: [] }); });
afterEach(() => { cleanup(); localStorage.clear(); setWorkspaceOwner(null); vi.useRealTimers(); });

it('invalidates a captured A writer synchronously before React commits a verified B owner', async () => {
  const hook = renderHook(() => useFormDraft({ fields: [{ key: 'name' }], context: 'contacts' }));
  await waitFor(() => expect(hook.result.current.ready).toBe(true));
  vi.useFakeTimers();
  act(() => hook.result.current.stage({ name: 'Private A' }));
  // Deliberately leave useAuth and the React render unchanged: owner binding
  // happens before React commits, and must already stop the queued old writer.
  setWorkspaceOwner('account-b');
  await act(async () => { await hook.result.current.flush(); await vi.advanceTimersByTimeAsync(700); });
  expect(workspace.put).not.toHaveBeenCalled();
  const keys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index));
  expect(keys).toEqual([expect.stringContaining('workspace:account-a:draft-buffer:')]);
  expect(JSON.parse(localStorage.getItem(keys[0])).values).toEqual({ name: 'Private A' });
});
