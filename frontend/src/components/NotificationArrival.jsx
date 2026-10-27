import { useEffect, useState } from 'react';
import { api } from '../api';
import { privateStorageKey } from '../utils/workspaceIdentity';

// Place this in the successful, rendered source view, never in a loading shell.
export default function NotificationArrival({ rows = [], record, ready = true }) {
  const noticeId = new URLSearchParams(window.location.search).get('notice_id');
  const focusId = new URLSearchParams(window.location.search).get('source_id') || new URLSearchParams(window.location.search).get('focus_id');
  const foreignParent = Boolean(record && focusId && String(record.id) !== focusId);
  const row = foreignParent ? null : record || rows.find(candidate => String(candidate.id) === focusId);
  const [result, setResult] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const rowId = row?.id;
  const rowRevision = row?.updated_at;
  const rowIdentity = row ? JSON.stringify(row) : null;
  const arrivalKey = JSON.stringify([noticeId, rowId, rowIdentity, ready]);
  useEffect(() => {
    if (!noticeId || !rowId || !ready) return;
    let live = true; const same = api.captureSession();
    const storage = privateStorageKey(`notice-arrival:${noticeId}`);
    (async () => {
      const { notice, source } = await api.get(`/notifications/${encodeURIComponent(noticeId)}/source`);
      same();
      const expected = new URL(source.href, window.location.origin);
      if (!live || source.entity_id !== rowId || expected.pathname !== window.location.pathname) return;
      const displayed = JSON.parse(rowIdentity);
      const differs = rowRevision ? Date.parse(rowRevision) !== Date.parse(source.revision)
        : Object.entries(source.values || {}).some(([key, value]) => key in displayed && String(displayed[key] ?? '') !== String(value ?? ''));
      if (differs) throw new Error('Die angezeigte Quelle wurde geändert. Bitte die Akte neu laden.');
      let body;
      try { body = JSON.parse(sessionStorage.getItem(storage) || 'null'); } catch { /* optional recovery */ }
      if (!body) body = { action: 'landed', base_revision: notice.revision,
        source_kind: source.kind, source_id: source.entity_id, source_revision: source.revision, idempotency_key: crypto.randomUUID() };
      try { sessionStorage.setItem(storage, JSON.stringify(body)); } catch { /* optional recovery */ }
      await api.post(`/notifications/${encodeURIComponent(noticeId)}/receipt`, body);
      same(); if (!live) return;
      sessionStorage.removeItem(storage); setResult({ key: arrivalKey, ok: true }); window.dispatchEvent(new Event('notification-receipt'));
    })().catch(failure => { if ((failure.statusCode || failure.status) === 409) sessionStorage.removeItem(storage); if (live) setResult({ key: arrivalKey, error: failure.message }); });
    return () => { live = false; };
  }, [noticeId, rowId, rowRevision, rowIdentity, ready, attempt, arrivalKey]);
  if (!noticeId || foreignParent) return null;
  const current = result?.key === arrivalKey ? result : null;
  if (current?.error) return <p role="alert">Lesebestätigung nicht bestätigt: {current.error} Der Hinweis bleibt erhalten. <button onClick={() => setAttempt(n => n + 1)}>Erneut bestätigen</button></p>;
  if (current?.ok) return <p role="status">Hinweis persönlich gelesen und archiviert.</p>;
  return <p role="status">Der Hinweis wird erst nach erfolgreichem Laden der zugehörigen Quelle bestätigt.</p>;
}
