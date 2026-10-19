import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';

const LABELS = { contacts: 'Kontakte', properties: 'Immobilien', units: 'Einheiten', meters: 'Zähler', portfolios: 'Portfolios' };

// A failed or unfinished collection never becomes a successful empty choice.
// Each scope/retry owns its response, even if an aborted transport resolves late.
export default function useLookupChoices(collections, enabled = true, scope = '') {
  const signature = JSON.stringify(collections);
  const [attempt, setAttempt] = useState(0);
  const key = JSON.stringify([signature, enabled, scope, attempt]);
  const [result, setResult] = useState({ key: null, data: {}, ready: false, error: null });
  const reload = useCallback(() => setAttempt(value => value + 1), [setAttempt]);
  useEffect(() => {
    const controller = new AbortController();
    setResult(previous => ({ ...previous, key, ready: false, error: null }));
    if (!enabled) return () => controller.abort();
    const entries = Object.entries(JSON.parse(signature));
    Promise.allSettled(entries.map(([, path]) => api.list(path, { signal: controller.signal }))).then(results => {
      if (controller.signal.aborted) return;
      const data = {}, failures = [];
      entries.forEach(([name], index) => {
        const source = results[index];
        if (source.status === 'fulfilled' && Array.isArray(source.value)) data[name] = source.value;
        else failures.push(`${LABELS[name] || 'Auswahl'}: ${source.reason?.message || 'Die Datenquelle konnte nicht vollständig gelesen werden.'}`);
      });
      setResult({ key, data, ready: !failures.length, error: failures.length ? failures.join(' · ') : null });
    });
    return () => controller.abort();
  }, [signature, enabled, scope, attempt, key]);
  const current = result.key === key;
  return { data: current ? result.data : {}, ready: Boolean(enabled && current && result.ready),
    loading: Boolean(enabled && (!current || (!result.ready && !result.error))), error: current ? result.error : null, reload };
}
