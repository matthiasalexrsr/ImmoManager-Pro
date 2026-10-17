import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useAuth } from '../contexts/AuthContext';

export function receiptCommand(values) {
  return { base_revision: 0, idempotency_key: crypto.randomUUID(), ...values };
}

export default function useNotificationInbox(status = 'unread', cursor = null, limit = 50, snapshot = null, severity = '', kind = '') {
  const owner = useAuth()?.user?.id;
  const [page, setPage] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const pending = useRef(null);
  const reload = useCallback(() => setAttempt(n => n + 1), []);
  useEffect(() => {
    let live = true;
    const same = api.captureSession();
    setPage(null); setError(null);
    const clear = () => { live = false; setPage(null); pending.current = null; };
    window.addEventListener('workspace-owner', clear);
    window.addEventListener('workspace-logout', clear);
    const query = new URLSearchParams({ limit });
    if (cursor) query.set('cursor', cursor);
    if (status) query.set('status', status);
    if (snapshot) query.set('expected_snapshot', snapshot);
    if (severity) query.set('severity', severity);
    if (kind) query.set('kind', kind);
    api.get(`/notifications/inbox?${query}`).then(data => {
      same();
      // Fail visibly for incomplete/old provider responses. A fabricated
      // empty list would hide unread notices; rendering undefined items can
      // crash unrelated dashboard and tenant-workspace screens.
      if (!data || !Array.isArray(data.items)
          || !Number.isInteger(data.total) || data.total < 0
          || !Number.isInteger(data.unread_count) || data.unread_count < 0
          || data.items.some(item => !item || typeof item.id !== 'string')) {
        throw new Error('Benachrichtigungen sind unvollständig. Bitte erneut laden.');
      }
      if (live) setPage(data);
    }).catch(failure => { if (live) setError(failure.message || 'Benachrichtigungen konnten nicht geladen werden.'); });
    return () => { live = false; window.removeEventListener('workspace-owner', clear); window.removeEventListener('workspace-logout', clear); };
  }, [owner, status, cursor, limit, snapshot, severity, kind, attempt]);
  useEffect(() => {
    const update = () => reload();
    window.addEventListener('focus', update);
    window.addEventListener('notification-receipt', update);
    const timer = setInterval(update, 60000);
    return () => { clearInterval(timer); window.removeEventListener('focus', update); window.removeEventListener('notification-receipt', update); };
  }, [reload]);
  const mutate = async (id, values) => {
    if (busy) return;
    setBusy(true); setError(null);
    const identity = JSON.stringify([id, values]);
    if (pending.current?.identity !== identity) pending.current = { identity, body: receiptCommand(values) };
    const same = api.captureSession();
    try {
      await api.post(`/notifications/${encodeURIComponent(id)}/receipt`, pending.current.body);
      same(); pending.current = null; reload();
      window.dispatchEvent(new Event('notification-receipt'));
    } catch (failure) {
      if (failure.code === 'SESSION_CHANGED') return;
      setError(failure.message || 'Änderung nicht bestätigt. Mit derselben Aktion erneut versuchen.');
      if ((failure.statusCode || failure.status) === 409) { pending.current = null; reload(); }
    } finally { setBusy(false); }
  };
  return { page, error, busy, reload, mutate };
}
