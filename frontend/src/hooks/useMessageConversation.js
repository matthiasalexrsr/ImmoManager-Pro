import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useAuth } from '../contexts/AuthContext';

const emptyPage = () => ({ items: [], status: 'idle', error: '', cursor: null, nextCursor: null, history: [], number: 1, total: null });
const pendingKey = (owner, thread) => `workspace:${owner}:message-command:${thread}`;
const bufferCommand = (owner, thread, command) => {
  if (!owner) return true;
  try { if (command) localStorage.setItem(pendingKey(owner, thread), JSON.stringify(command));
    else localStorage.removeItem(pendingKey(owner, thread)); return true; } catch { return false; }
};
const recoverCommand = (owner, thread) => {
  if (!owner) return null;
  try { const value = JSON.parse(localStorage.getItem(pendingKey(owner, thread)) || 'null');
    return value?.thread_id === thread && typeof value.body === 'string' && typeof value.idempotency_key === 'string'
      && typeof value.base_revision === 'string' && Number.isInteger(value.draftVersion) ? value : null;
  } catch { return null; }
};
const rejected = error => [400, 401, 403, 404, 409, 422].includes(error.statusCode);

// A conversation, a read attempt and a submitted command have separate identities.
// Aborting a read is an optimization; generation/session checks are the boundary.
export default function useMessageConversation(onThreadLoaded) {
  const owner = useAuth()?.user?.id;
  const [selectedThread, setSelectedThread] = useState(null);
  const [page, setPage] = useState(emptyPage);
  const [drafts, setDrafts] = useState({});
  const [notices, setNotices] = useState({});
  const selected = useRef(null);
  const draftValues = useRef(new Map());
  const pending = useRef(new Map());
  const sending = useRef(new Set());
  const request = useRef(null);
  const generation = useRef(0);
  const session = useRef(0);
  const live = useRef(true);

  const invalidate = useCallback(() => {
    session.current += 1;
    generation.current += 1;
    request.current?.abort();
    selected.current = null;
    draftValues.current.clear();
    pending.current.clear();
    sending.current.clear();
    setSelectedThread(null); setPage(emptyPage()); setDrafts({}); setNotices({});
  }, []);

  useEffect(() => {
    live.current = true;
    window.addEventListener('workspace-logout', invalidate);
    window.addEventListener('workspace-owner', invalidate);
    return () => {
      live.current = false; session.current += 1; generation.current += 1;
      request.current?.abort();
      window.removeEventListener('workspace-logout', invalidate);
      window.removeEventListener('workspace-owner', invalidate);
    };
  }, [invalidate]);

  const loadPage = useCallback(async (thread, cursor = null, history = [], number = 1) => {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    const epoch = ++generation.current;
    const current = () => live.current && epoch === generation.current && selected.current?.id === thread.id;
    setPage({ ...emptyPage(), status: 'loading', cursor, history, number });
    try {
      const sameSession = api.captureSession();
      const query = new URLSearchParams({ limit: '100' });
      if (cursor) query.set('cursor', cursor);
      const result = await api.get(`/messages/threads/${encodeURIComponent(thread.id)}/page?${query}`, { signal: controller.signal });
      if (!current() || controller.signal.aborted) return;
      sameSession();
      if (!result || !Array.isArray(result.items) || result.items.some(row => row.thread_id !== thread.id)
          || (result.next_cursor != null && (typeof result.next_cursor !== 'string' || result.next_cursor === cursor))) {
        throw new Error('Die Nachrichtenantwort ist unvollständig oder gehört nicht zu dieser Konversation.');
      }
      if (result.thread?.id === thread.id) {
        selected.current = result.thread;
        setSelectedThread(result.thread);
        onThreadLoaded?.(result.thread);
      }
      // Read a crash buffer only after this server page has rechecked the source rights.
      if (!pending.current.has(thread.id)) {
        const recovered = recoverCommand(owner, thread.id);
        if (recovered) {
          pending.current.set(thread.id, recovered);
          if (!draftValues.current.has(thread.id)) {
            draftValues.current.set(thread.id, { body: recovered.body, version: recovered.draftVersion });
            setDrafts(values => ({ ...values, [thread.id]: recovered.body }));
          }
          setNotices(values => ({ ...values, [thread.id]: { uncertain: true, sending: false,
            error: 'Eine unterbrochene Speicherung wurde wiedergefunden. Bitte mit derselben Kennung abgleichen.' } }));
        }
      }
      setPage({ items: result.items, status: 'ready', error: '', cursor, history, number,
        nextCursor: result.next_cursor || null, total: result.total ?? null });
    } catch (failure) {
      if (!current() || controller.signal.aborted || failure.name === 'AbortError') return;
      if (failure.code === 'SESSION_CHANGED') { invalidate(); return; }
      setPage({ ...emptyPage(), status: 'error', cursor, history, number,
        error: failure.message || 'Nachrichten konnten nicht geladen werden.' });
    }
  }, [invalidate, onThreadLoaded, owner]);

  const selectThread = useCallback(thread => {
    selected.current = thread;
    setSelectedThread(thread);
    return loadPage(thread);
  }, [loadPage]);

  const setDraft = useCallback(body => {
    const id = selected.current?.id;
    if (!id) return;
    const previous = draftValues.current.get(id);
    draftValues.current.set(id, { body, version: (previous?.version || 0) + 1 });
    setDrafts(values => ({ ...values, [id]: body }));
  }, []);

  const send = useCallback(async ({ retry = false } = {}) => {
    const thread = selected.current;
    if (!thread || sending.current.has(thread.id)) return;
    const draft = draftValues.current.get(thread.id);
    const prior = pending.current.get(thread.id);
    if (!retry && !draft?.body.trim()) return;
    if (prior && !retry && prior.body !== draft?.body) {
      setNotices(values => ({ ...values, [thread.id]: { ...values[thread.id], uncertain: true,
        error: 'Eine frühere Speicherung ist noch unbestätigt. Bitte zuerst deren Ergebnis abgleichen; der neue Entwurf bleibt erhalten.' } }));
      return;
    }
    if (retry && !prior) return;
    const epoch = session.current;
    const active = () => live.current && epoch === session.current;
    let sameSession;
    try { sameSession = api.captureSession(); }
    catch (failure) { if (failure.code === 'SESSION_CHANGED') invalidate(); return; }
    const command = prior || {
      thread_id: thread.id, sender_name: 'Ich', body: draft.body,
      base_revision: thread.updated_at,
      idempotency_key: crypto.randomUUID(), draftVersion: draft.version,
    };
    if (!bufferCommand(owner, thread.id, command)) {
      setNotices(values => ({ ...values, [thread.id]: { error: 'Die sichere Wiederaufnahme konnte nicht gespeichert werden. Bitte Browserspeicher prüfen; es wurde keine Nachricht übertragen.' } }));
      return;
    }
    pending.current.set(thread.id, command);
    sending.current.add(thread.id);
    setNotices(values => ({ ...values, [thread.id]: { sending: true, error: '', uncertain: false } }));
    try {
      const { draftVersion: _draftVersion, ...payload } = command;
      const saved = await api.post(`/messages/threads/${encodeURIComponent(thread.id)}/messages`, payload);
      if (!active()) return;
      sameSession();
      if (!saved?.id || saved.thread_id !== thread.id) throw new Error('Die Speicherung wurde nicht eindeutig bestätigt.');
      pending.current.delete(thread.id);
      bufferCommand(owner, thread.id, null);
      const latest = draftValues.current.get(thread.id);
      // Typing while a send is in flight creates a new draft, even after undoing
      // back to identical text. Its version must not be cleared by the old send.
      if (latest?.version === command.draftVersion && latest.body === command.body) {
        draftValues.current.delete(thread.id);
        setDrafts(values => ({ ...values, [thread.id]: '' }));
      }
      setNotices(values => ({ ...values, [thread.id]: { sending: false, error: '', uncertain: false, saved: true } }));
      if (selected.current?.id === thread.id) await loadPage(selected.current);
    } catch (failure) {
      if (!active()) return;
      if (failure.code === 'SESSION_CHANGED') { invalidate(); return; }
      const definite = rejected(failure);
      if (definite) { pending.current.delete(thread.id); bufferCommand(owner, thread.id, null); }
      setNotices(values => ({ ...values, [thread.id]: { sending: false,
        error: failure.message || 'Nachricht konnte nicht gespeichert werden.', uncertain: !definite } }));
    } finally {
      if (active()) sending.current.delete(thread.id);
    }
  }, [invalidate, loadPage, owner]);

  const refresh = () => selectedThread && loadPage(selectedThread);
  const retryRead = () => selectedThread && loadPage(selectedThread, page.cursor, page.history, page.number);
  const older = () => selectedThread && page.nextCursor && loadPage(selectedThread, page.nextCursor,
    [...page.history, page.cursor], page.number + 1);
  const newer = () => selectedThread && page.history.length && loadPage(selectedThread,
    page.history.at(-1), page.history.slice(0, -1), page.number - 1);

  return { selectedThread, page, selectThread, setDraft, send, refresh, retryRead, older, newer,
    draft: drafts[selectedThread?.id] || '', notice: notices[selectedThread?.id] || {} };
}
