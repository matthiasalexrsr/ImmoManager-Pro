import { useRef, useState } from 'react';
import { api } from '../api';
import { privateStorageKey } from '../utils/workspaceIdentity';

// Mounted only in NEW forms. First inspect; only explicit acceptance allocates.
export default function DraftDefaults({ context, propertyId, onApply, disabled = false }) {
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef(null);
  const storage = privateStorageKey(`draft-defaults:${context}:${propertyId || ''}`);
  const load = async () => {
    setBusy(true); setError(null); const same = api.captureSession();
    try {
      const query = new URLSearchParams({ context }); if (propertyId) query.set('property_id', propertyId);
      const result = await api.get(`/auth/users/me/settings/draft-defaults?${query}`); same(); setPreview(result);
    } catch (failure) { setError(failure.message); } finally { setBusy(false); }
  };
  const accept = async () => {
    setBusy(true); setError(null); const same = api.captureSession();
    try {
      if (!pending.current) { try { pending.current = JSON.parse(sessionStorage.getItem(storage) || 'null'); } catch { /* optional buffer */ } }
      if (!pending.current) pending.current = { context, property_id: propertyId || null, expected_revision: preview.revision, idempotency_key: crypto.randomUUID() };
      sessionStorage.setItem(storage, JSON.stringify(pending.current));
      const result = await api.post('/auth/users/me/settings/draft-defaults', pending.current); same();
      onApply(result.values); pending.current = null; sessionStorage.removeItem(storage); setPreview(null);
    } catch (failure) { setError(failure.message); } finally { setBusy(false); }
  };
  return <section aria-label="Vorgaben für neuen Entwurf">
    <button type="button" disabled={busy || disabled} onClick={load}>Vorgaben für neuen Entwurf prüfen</button>
    {preview && <><p>{preview.policy} {preview.numbering_enabled && 'Beim Übernehmen wird eine neue Mietvertragsnummer verbindlich reserviert; verworfene Nummern werden nicht erneut vergeben.'}</p>
      <dl>{Object.entries(preview.values).map(([key, value]) => <div key={key}><dt>{({ category_id: 'Buchungskategorie', cost_category: 'Kostenart', recoverable: 'Umlagefähig' })[key] || key}</dt><dd>{typeof value === 'boolean' ? value ? 'Ja' : 'Nein' : value || 'Keine Vorgabe'}</dd></div>)}</dl>
      <button type="button" disabled={busy || disabled} onClick={accept}>Vorgaben ausdrücklich übernehmen</button></>}
    {error && <p role="alert">{error} Die Eingabe bleibt erhalten. <button type="button" disabled={busy} onClick={load}>Vorschau neu laden</button>
      <button type="button" disabled={busy || !preview} onClick={accept}>Unbestätigte Übernahme erneut abgleichen</button></p>}
  </section>;
}
