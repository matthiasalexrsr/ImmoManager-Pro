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
