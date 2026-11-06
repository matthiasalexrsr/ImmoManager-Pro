import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { useAuth } from '../../contexts/AuthContext';

export default function useReminders(status = 'active') {
  const owner = useAuth()?.user?.id;
  const [page, setPage] = useState(null); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0); const pending = useRef(null); const writing = useRef(false);
  const current = useRef(false);
  const [offset, setOffset] = useState(0);
  const reload = useCallback(() => setAttempt(value => value + 1), []);
  useEffect(() => {
    if (!owner) return;
    current.current = true;
    let live = true; const controller = new AbortController();
    const invalidate = () => { current.current = false; live = false; controller.abort(); setPage(null); setError('Die Sitzung wurde geändert. Bitte erneut anmelden.'); pending.current = null; };
    window.addEventListener('workspace-owner', invalidate); window.addEventListener('workspace-logout', invalidate);
    (async () => {
      const same = api.captureSession();
      const result = await api.get(`/notifications/reminders?status=${encodeURIComponent(status)}&offset=${offset}`, { signal: controller.signal });
      same(); if (!live) return;
      if (!Array.isArray(result?.items) || !Number.isSafeInteger(result.total) || result.total < 0) throw new Error('Erinnerungen wurden nicht vollständig geladen.');
      setPage({ ...result, _workspaceOwner: owner, _view: status }); setError('');
    })().catch(failure => { if (live && failure.name !== 'AbortError') { setPage(null); setError(failure.message || 'Erinnerungen konnten nicht geladen werden.'); } });
    return () => { current.current = false; live = false; controller.abort(); window.removeEventListener('workspace-owner', invalidate); window.removeEventListener('workspace-logout', invalidate); };
  }, [owner, status, attempt, offset]);
  useEffect(() => { setOffset(0); }, [owner, status]);
  useEffect(() => {
    const timer = setInterval(reload, 60000);
    window.addEventListener('focus', reload); window.addEventListener('reminder-change', reload);
    return () => { clearInterval(timer); window.removeEventListener('focus', reload); window.removeEventListener('reminder-change', reload); };
  }, [reload]);
  const change = async (row, action) => {
    if (writing.current || !current.current) return; writing.current = true; setBusy(true); setError('');
    const identity = `${row.id}:${action}:${row.revision}`;
    if (pending.current?.identity !== identity) pending.current = { identity, body: { action, base_revision: row.revision, idempotency_key: crypto.randomUUID() } };
    try {
      const same = api.captureSession(); await api.post(`/notifications/reminders/${encodeURIComponent(row.id)}/command`, pending.current.body); same();
      if (current.current) { pending.current = null; reload(); window.dispatchEvent(new Event('reminder-change')); }
    } catch (failure) {
      if (current.current && failure.code !== 'SESSION_CHANGED') setError(failure.message || 'Erinnerung nicht geändert. Erneut versuchen.');
      if (current.current && (failure.statusCode || failure.status) === 409) { pending.current = null; reload(); }
    } finally { writing.current = false; if (current.current) setBusy(false); }
  };
  return { page: owner && page?._workspaceOwner === owner && page?._view === status ? page : null, error, busy, reload, change, offset, setOffset };
}
