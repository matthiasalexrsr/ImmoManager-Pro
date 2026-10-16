import { useEffect, useRef, useState } from 'react';
import { api } from '../api';

/** Only deactivation metadata changes; unreadable secrets are never replaced. */
export default function ConnectionEmergencyStop({ connection, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const pending = useRef(null);
  const alive = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function stop() {
    if (busy) return;
    const current = api.captureSession();
    const payload = pending.current || { idempotency_key: crypto.randomUUID(), base_revision: connection.revision, enabled: false };
    pending.current = payload; setBusy(true); setError('');
    try {
      const result = await api.patch(`/integration-connections/${encodeURIComponent(connection.id)}`, payload);
      current(); if (!alive.current) return;
      if (result?.id !== connection.id || result.enabled !== false) throw new Error('Die Deaktivierung wurde nicht eindeutig bestätigt.');
      pending.current = null; setUncertain(false); onChanged(result);
    } catch (failure) {
      if (!alive.current || failure.code === 'SESSION_CHANGED') return;
      if ([400, 401, 403, 404, 409, 422].includes(failure.statusCode)) { pending.current = null; setUncertain(false); }
      else setUncertain(true);
      setError(failure.message || 'Die Verbindung konnte nicht bestätigt deaktiviert werden.');
    } finally { if (alive.current) setBusy(false); }
  }
  return <section aria-label="Unlesbare Verbindung deaktivieren">
    <p>Die Zugangsdaten bleiben unverändert verschlüsselt gespeichert. Eine Deaktivierung stoppt neue Ausführungen; sie widerruft keine bereits erteilten externen Aufträge.</p>
    {error && <p role="alert">{error}</p>}
    <button type="button" className="btn btn-secondary" disabled={busy || (!connection.enabled && !uncertain)} onClick={stop}>
      {busy ? 'Deaktivierung wird geprüft …' : uncertain ? 'Deaktivierung abgleichen' : connection.enabled ? 'Verbindung sicher deaktivieren' : 'Verbindung ist deaktiviert'}</button>
  </section>;
}
