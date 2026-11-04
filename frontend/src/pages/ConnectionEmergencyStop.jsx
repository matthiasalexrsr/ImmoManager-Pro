import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useCanWrite } from '../contexts/AuthContext';
import { isDefiniteIntegrationFailure } from '../utils/integrationFields';

/** Only deactivation metadata changes; unreadable secrets are never replaced. */
export default function ConnectionEmergencyStop({ connection, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [sessionInvalid, setSessionInvalid] = useState(false);
  const canWrite = useCanWrite('/integrations');
  const pending = useRef(null);
  const alive = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  function invalidate() {
    setSessionInvalid(true); pending.current = null; setUncertain(false); setConflict(false);
    setError('Die Sitzung wurde geändert. Bitte erneut anmelden.');
  }
  async function stop() {
    if (busy || sessionInvalid || conflict || !canWrite) return;
    setBusy(true); setError('');
    try {
      const current = api.captureSession();
      const payload = pending.current || { idempotency_key: crypto.randomUUID(), base_revision: connection.revision, enabled: false };
      pending.current = payload;
      const result = await api.patch(`/integration-connections/${encodeURIComponent(connection.id)}`, payload);
      current(); if (!alive.current) return;
      if (result?.id !== connection.id || result.enabled !== false || !Number.isInteger(result.revision) || result.revision < 1) throw new Error('Die Deaktivierung wurde nicht eindeutig bestätigt.');
      pending.current = null; setUncertain(false); onChanged(result);
    } catch (failure) {
      if (!alive.current) return;
      if (failure.code === 'SESSION_CHANGED') { invalidate(); return; }
      if (isDefiniteIntegrationFailure(failure)) { pending.current = null; setUncertain(false); }
      else setUncertain(true);
      setConflict(failure.statusCode === 409);
      setError(failure.message || 'Die Verbindung konnte nicht bestätigt deaktiviert werden.');
    } finally { if (alive.current) setBusy(false); }
  }
  async function reload() {
    if (busy || sessionInvalid || uncertain) return;
    setBusy(true); setError('');
    try {
      const current = api.captureSession();
      const result = await api.get(`/integration-connections/${encodeURIComponent(connection.id)}/state`);
      current(); if (!alive.current) return;
      if (result?.id !== connection.id || !Number.isInteger(result.revision) || result.revision < 1) throw new Error('Der aktuelle Verbindungsstand ist unvollständig.');
      setConflict(false); onChanged(result);
    } catch (failure) {
      if (!alive.current) return;
      if (failure.code === 'SESSION_CHANGED') invalidate();
      else setError(failure.message || 'Der aktuelle Verbindungsstand konnte nicht geladen werden.');
    } finally { if (alive.current) setBusy(false); }
  }
  return <section aria-label="Unlesbare Verbindung deaktivieren">
    <p>Die Zugangsdaten bleiben unverändert verschlüsselt gespeichert. Eine Deaktivierung stoppt neue Ausführungen; sie widerruft keine bereits erteilten externen Aufträge.</p>
    {error && <p role="alert">{error}</p>}
    {conflict && <button type="button" className="btn btn-secondary" disabled={busy || uncertain} onClick={reload}>Verbindungsstand neu laden</button>}
    <button type="button" className="btn btn-secondary" disabled={!canWrite || sessionInvalid || busy || conflict || (!connection.enabled && !uncertain)} onClick={stop}>
      {busy ? 'Deaktivierung wird geprüft …' : uncertain ? 'Deaktivierung abgleichen' : connection.enabled ? 'Verbindung sicher deaktivieren' : 'Verbindung ist deaktiviert'}</button>
  </section>;
}
