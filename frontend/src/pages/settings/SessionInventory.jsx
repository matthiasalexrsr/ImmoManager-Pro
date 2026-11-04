import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { formatDateTime } from '../../utils/format';
import { privateStorageKey } from '../../utils/workspaceIdentity';

export default function SessionInventory() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [sessionInvalid, setSessionInvalid] = useState(false);
  const pending = useRef({});
  useEffect(() => {
    if (sessionInvalid) return;
    let live = true;
    async function load() {
      try {
        const same = api.captureSession();
        const result = await api.get('/auth/users/me/settings/sessions'); same();
        if (!Array.isArray(result?.items)) throw new Error('Die Sitzungsantwort ist unvollständig. Bitte erneut laden.');
        if (live) { setData(result); setError(null); }
      } catch (failure) {
        if (!live) return;
        if (failure.code === 'SESSION_CHANGED') { setSessionInvalid(true); setData(null); setConfirm(null); pending.current = {}; }
        else setError(failure.message);
      }
    }
    load();
    return () => { live = false; };
  }, [attempt, sessionInvalid]);
  const revoke = async row => {
    if (busy || sessionInvalid) return;
    setBusy(true); setError(null);
    try {
      const same = api.captureSession();
      const key = privateStorageKey(`revoke-session:${row.id}`);
      if (!pending.current[row.id]) { try { pending.current[row.id] = JSON.parse(sessionStorage.getItem(key) || 'null'); } catch { /* optional recovery */ } }
      const body = pending.current[row.id] || { base_revision: row.revision, idempotency_key: crypto.randomUUID() };
      pending.current[row.id] = body;
      try { sessionStorage.setItem(key, JSON.stringify(body)); } catch { /* in-memory retry remains available */ }
      await api.post(`/auth/users/me/settings/sessions/${encodeURIComponent(row.id)}/revoke`, body); same();
      try { sessionStorage.removeItem(key); } catch { /* optional recovery */ }
      delete pending.current[row.id]; setConfirm(null);
      setData(current => ({ ...current, items: current.items.map(item => item.id === row.id ? { ...item, revoked_at: new Date().toISOString() } : item) }));
      if (row.current) setError('Diese Sitzung wurde widerrufen. Bitte erneut anmelden.');
      else setAttempt(n => n + 1);
    } catch (failure) {
      if (failure.code === 'SESSION_CHANGED') { setSessionInvalid(true); setData(null); setConfirm(null); pending.current = {}; }
      else setError(failure.message || 'Widerruf nicht bestätigt. Denselben Befehl erneut abgleichen.');
    }
    finally { setBusy(false); }
  };
  if (sessionInvalid) return <section className="settings-support-section" aria-label="Sitzungsübersicht"><p role="alert">Die Sitzung wurde geändert. Bitte erneut anmelden.</p></section>;
  return <section className="settings-support-section" aria-label="Sitzungsübersicht"><h3>Sicherheit und Sitzungen</h3>
    {data && <><p>{data.legacy_notice}</p><ul>{data.items.map(row => <li key={row.id}>
      <strong>{row.current ? 'Diese Anmeldung' : 'Weitere Anmeldung'}</strong> · Beginn {formatDateTime(row.created_at)} · Ablauf {formatDateTime(row.expires_at)}
      {row.revoked_at ? <span> · Widerrufen</span> : <button disabled={busy} onClick={() => setConfirm(row.id)}>Sitzung widerrufen</button>}
      {confirm === row.id && <p>Alle Zugriffs- und Erneuerungstokens dieser Anmeldung werden gesperrt.
        <button disabled={busy} onClick={() => revoke(row)}>Widerruf ausdrücklich bestätigen</button><button disabled={busy} onClick={() => setConfirm(null)}>Abbrechen</button></p>}
    </li>)}</ul></>}
    {error && <p role="alert">{error} <button disabled={busy} onClick={() => setAttempt(n => n + 1)}>Übersicht erneut laden</button></p>}
    {!data && !error && <p role="status">Sitzungen werden geladen …</p>}
  </section>;
}
