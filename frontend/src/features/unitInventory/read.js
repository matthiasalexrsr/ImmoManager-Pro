import { useEffect, useState } from 'react';
import { api } from '../../api';

export function usePrivateRead(path, principal, generation = 0) {
  const source = JSON.stringify([path, principal, generation]);
  const [result, setResult] = useState({ source: null });
  useEffect(() => {
    if (!principal || !path) return undefined;
    const controller = new AbortController();
    api.get(path, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) setResult({ source, data, error: null });
    }).catch(error => {
      if (!controller.signal.aborted) setResult({ source, data: null, error });
    });
    return () => controller.abort();
  }, [source, path, principal]);
  return result.source === source ? { ...result, loading: false } : { data: null, error: null, loading: true };
}

export const principalKey = user => user ? JSON.stringify([user.id, user.role, user.portfolio_access, user.portfolio_access_origin,
  [...(user.portfolio_ids || [])].sort(), [...(user.write_permissions || [])].sort()]) : '';

export function queryString(values) {
  return new URLSearchParams(Object.entries(values).filter(([, value]) => value !== '' && value != null)).toString();
}

export function checkedPage(data) {
  return data && Array.isArray(data.items) && data.items.length <= 25 && typeof data.has_more === 'boolean'
    && (data.has_more ? typeof data.next_cursor === 'string' && data.next_cursor.length > 0 && data.items.length > 0 : data.next_cursor === null)
    && data.items.every(row => row && typeof row.id === 'string') && new Set(data.items.map(row => row.id)).size === data.items.length;
}

export const errorMessage = error => [401, 403, 404].includes(error?.statusCode)
  ? 'Der Zugriff wurde geändert oder die Daten sind nicht verfügbar.'
  : error?.message || 'Die Antwort konnte nicht geprüft werden. Bitte erneut laden.';
