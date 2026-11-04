import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';

export function usePortalAdminPage(path, refresh = 0) {
  const [result, setResult] = useState({ path: '', data: null, error: '' });
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    setResult({ path, data: null, error: '' });
    api.get(path, { signal: controller.signal }).then(data => { if (!controller.signal.aborted) setResult({ path, data, error: '' }); })
      .catch(error => { if (!controller.signal.aborted) setResult({ path, data: null, error: error.message }); });
    return () => controller.abort();
  }, [path, refresh]);
  return result.path === path ? [result.data, result.error] : [null, ''];
}

export function usePortalGrantChoices(caseId) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState({ key: '', data: [], ready: false, error: '' });
  useEffect(() => {
    const controller = new AbortController();
    setResult({ key: caseId, data: [], ready: false, error: '' });
    const current = api.captureSession();
    (async () => {
      const collected = [], seen = new Set();
      for (let skip = 0; ;) {
        current();
        const page = await api.get(`/portal-admin/grants?case_id=${encodeURIComponent(caseId)}&skip=${skip}&limit=100`, { signal: controller.signal });
        current();
        if (controller.signal.aborted) return;
        if (!Array.isArray(page.items) || !Number.isSafeInteger(page.total) || page.total < 0) throw new Error('Die Portalzuordnungen konnten nicht vollständig gelesen werden.');
        for (const row of page.items) {
          if (seen.has(row.id)) throw new Error('Die Portalzuordnungen haben sich während des Ladens geändert. Bitte erneut laden.');
          seen.add(row.id); collected.push(row);
        }
        skip += page.items.length;
        if (skip >= page.total) break;
        if (!page.items.length) throw new Error('Die Portalzuordnungen sind unvollständig. Bitte erneut laden.');
      }
      setResult({ key: caseId, data: collected, ready: true, error: '' });
    })().catch(error => { if (!controller.signal.aborted) setResult({ key: caseId, data: [], ready: false, error: error.message }); });
    return () => controller.abort();
  }, [caseId, attempt]);
  return { ...(result.key === caseId ? result : { data: [], ready: false, error: '' }), reload: () => setAttempt(value => value + 1) };
}

export function usePortalAdminAction() {
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const inFlight = useRef(false), pending = useRef(null);
  const perform = async (path, body, method = 'post') => {
    if (inFlight.current) return null;
    const fingerprint = JSON.stringify([path, method, body]);
    if (pending.current?.fingerprint !== fingerprint) pending.current = { fingerprint, key: crypto.randomUUID() };
    inFlight.current = true; setBusy(true); setError('');
    try {
      const response = await api[method](path, { ...body, idempotency_key: pending.current.key });
      pending.current = null; return response;
    } catch (failure) { setError(failure.message); return null; }
    finally { inFlight.current = false; setBusy(false); }
  };
  return { busy, error, perform };
}
