import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import useMessageConversation from '../hooks/useMessageConversation';
const account = vi.hoisted(() => ({ id: 'owner-a' }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: account }) }));
vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), captureSession: vi.fn() } }));
const thread = { id: 'thread-a', subject: 'Vorgang', updated_at: '2026-10-16T10:00:00Z' };
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); account.id = 'owner-a';
  api.captureSession.mockReturnValue(() => {});
  api.get.mockResolvedValue({ items: [], thread, total: 0 });
});
afterEach(() => localStorage.clear());

it('recovers an uncertain internal send after restart with the original command key', async () => {
  api.post.mockRejectedValueOnce(new Error('Lost success response'));
  let hook = renderHook(() => useMessageConversation());
  await act(async () => hook.result.current.selectThread(thread));
  act(() => hook.result.current.setDraft('Antwort nach Absturz'));
  await act(async () => hook.result.current.send());
  const original = api.post.mock.calls[0][1];
  expect(hook.result.current.notice.uncertain).toBe(true);
  hook.unmount();
  hook = renderHook(() => useMessageConversation());
  await act(async () => hook.result.current.selectThread(thread));
  expect(hook.result.current.draft).toBe('Antwort nach Absturz');
  expect(hook.result.current.notice.uncertain).toBe(true);
  api.post.mockResolvedValueOnce({ id: 'one-confirmed-message', thread_id: thread.id, body: original.body });
  await act(async () => hook.result.current.send({ retry: true }));
  expect(api.post.mock.calls[1][1]).toEqual(original);
  expect(localStorage.getItem('workspace:owner-a:message-command:thread-a')).toBeNull();
  hook.unmount();
});

it('never reveals an old pending body before current source authorization succeeds', async () => {
  localStorage.setItem('workspace:owner-a:message-command:thread-a', JSON.stringify({ thread_id: thread.id, body: 'PRIVATE', base_revision: thread.updated_at, idempotency_key: 'old-key', draftVersion: 1 }));
  api.get.mockRejectedValue(new Error('Access revoked'));
  const hook = renderHook(() => useMessageConversation());
  await act(async () => hook.result.current.selectThread(thread));
  expect(hook.result.current.draft).toBe('');
  expect(hook.result.current.page.error).toBe('Access revoked');
  hook.unmount();
});

it('does not read another account crash buffer', async () => {
  localStorage.setItem('workspace:owner-a:message-command:thread-a', JSON.stringify({ thread_id: thread.id, body: 'PRIVATE', base_revision: thread.updated_at, idempotency_key: 'old-key', draftVersion: 1 }));
  account.id = 'owner-b';
  const hook = renderHook(() => useMessageConversation());
  await act(async () => hook.result.current.selectThread(thread));
  expect(hook.result.current.draft).toBe('');
  expect(hook.result.current.notice.uncertain).toBeFalsy();
  hook.unmount();
});
