import { useEffect, useRef, useState } from 'react';
import { api } from '../api';

export default function BankMatch({ bookingId, onAssigned }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const command = useRef(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const run = action => {
    const current = api.captureSession(); setBusy(true); setError('');
    const check = () => { current(); if (!mounted.current) throw new Error('Ansicht geschlossen'); };
    Promise.resolve().then(() => action(check)).catch(e => { if (mounted.current && e.code !== 'SESSION_CHANGED') setError(e.message); })
      .finally(() => { if (mounted.current) setBusy(false); });
  };
  const load = () => run(async current => {
    const result = await api.get(`/bank-imports/matching/${encodeURIComponent(bookingId)}`); current(); setData(result); setConfirmed(false);
  });
  const assign = suggestion => run(async current => {
    const payload = { expected_revision: data.expected_revision, tenant_id: suggestion.tenant_id, allocations: suggestion.allocations };
    const signature = JSON.stringify(payload);
    if (command.current?.signature !== signature) command.current = { signature, key: crypto.randomUUID() };
    await api.post(`/bank-imports/matching/${encodeURIComponent(bookingId)}`, { ...payload, idempotency_key: command.current.key }); current();
    onAssigned?.();
    const result = await api.get(`/bank-imports/matching/${encodeURIComponent(bookingId)}`); current(); setData(result); setConfirmed(false);
  });
  return <details><summary>Zahlungszuordnung prüfen</summary><button type="button" disabled={busy} onClick={load}>Aktuelle Vorschläge laden</button>
    {error && <p role="alert">{error}</p>}{busy && <p role="status">Zuordnung wird geprüft …</p>}
    {data && <div><p>Budget der Originalbewegung: {(data.budget_cents / 100).toFixed(2)} EUR · zugeordnet: {(data.assigned_cents / 100).toFixed(2)} EUR · Rest am Original: {(data.remaining_cents / 100).toFixed(2)} EUR · {data.reversal_count} Stornos</p>
      {data.reversal_count > 0 && <p>Nach Stornos: Budget {(data.effective_budget_cents / 100).toFixed(2)} EUR · zugeordnet {(data.effective_assigned_cents / 100).toFixed(2)} EUR · verbleibend {(data.effective_remaining_cents / 100).toFixed(2)} EUR. Die gewählten Teilbeträge beziehen sich auf das Original; verknüpfte Stornos folgen der bestehenden Zuordnungsregel.</p>}
      {data.warning && <p>{data.warning}</p>}
      <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Ich habe Mieter, Teilbeträge und Rückläufer geprüft.</label>
      {data.suggestions.map(s => <div key={s.tenant_id}><p>{s.name} · {s.reason}</p><ul>{Object.entries(s.allocations).map(([id, cents]) => <li key={id}>Vertrag {id}: {(cents / 100).toFixed(2)} EUR</li>)}</ul><button type="button" disabled={busy || !confirmed || !Object.keys(s.allocations).length} onClick={() => assign(s)}>Diese Zuordnung ausdrücklich übernehmen</button></div>)}
      {!data.suggestions.length && <p>Kein eindeutiger Namensvorschlag. Mieter und Teilbeträge in der Buchung manuell prüfen und zuordnen.</p>}
    </div>}
  </details>;
}
