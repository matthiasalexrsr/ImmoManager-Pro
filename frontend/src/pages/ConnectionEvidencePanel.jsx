import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useCanWrite } from '../contexts/AuthContext';

const BASE = '/integration-connections';
const definite = error => [400, 401, 403, 404, 409, 413, 422].includes(error.statusCode);

/** One verified attempt at a time; retained late results never trigger a send. */
export default function ConnectionEvidencePanel({ connectionId, run, onApplied }) {
  const canWrite = useCanWrite('/integrations');
  const [page, setPage] = useState(null);
  const [cursor, setCursor] = useState(null);
  const [history, setHistory] = useState([]);
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState(null);
  const [proof, setProof] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const pending = useRef(null);
  const alive = useRef(false);
  const path = `${BASE}/${encodeURIComponent(connectionId)}/runs/${encodeURIComponent(run.id)}`;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController(); const current = api.captureSession();
    setLoading(true); setError('');
    const query = new URLSearchParams({ limit: '25' }); if (cursor) query.set('cursor', cursor);
    api.get(`${path}/attempts?${query}`, { signal: controller.signal }).then(result => {
      if (controller.signal.aborted) return; current();
      if (!Array.isArray(result?.items) || !Number.isInteger(result.total)
          || result.items.some(item => item.run_id !== run.id)) throw new Error('Die Ergebnisliste wurde nicht vollständig bestätigt.');
      setPage(result);
    }).catch(failure => { if (!controller.signal.aborted && failure.code !== 'SESSION_CHANGED') setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [path, run.id, run.revision, cursor, refresh]);
  useEffect(() => {
    setProof(null); setConfirmed(false); setReason('');
    if (!selected) return;
    const controller = new AbortController(); const current = api.captureSession();
    api.get(`${path}/attempts/${encodeURIComponent(selected)}`, { signal: controller.signal }).then(result => {
      if (controller.signal.aborted) return; current();
      if (result?.attempt?.id !== selected || result.attempt.run_id !== run.id || result.verified !== true)
        throw new Error('Der Ergebnisnachweis wurde nicht vollständig geprüft.');
      setProof(result);
    }).catch(failure => { if (!controller.signal.aborted && failure.code !== 'SESSION_CHANGED') setError(failure.message); });
    return () => controller.abort();
  }, [path, selected, run.id, run.revision, refresh]);
  async function reconcile(event) {
    event.preventDefault();
    if (busy || (!pending.current && (!confirmed || !reason.trim() || !proof?.verified))) return;
    const current = api.captureSession();
    const command = pending.current || { idempotency_key: crypto.randomUUID(), base_revision: run.revision,
      attempt_id: proof.attempt.id, reason: reason.trim(), confirm: true };
    pending.current = command; setBusy(true); setError('');
    try {
      const result = await api.post(`${path}/reconcile-recorded`, command);
      current(); if (!alive.current) return;
      if (result?.id !== run.id || !Number.isInteger(result.revision)) throw new Error('Der Abgleich wurde nicht eindeutig bestätigt.');
      pending.current = null; setUncertain(false); setConfirmed(false); onApplied(result); setRefresh(value => value + 1);
    } catch (failure) {
      if (!alive.current || failure.code === 'SESSION_CHANGED') return;
      if (definite(failure)) { pending.current = null; setUncertain(false); } else setUncertain(true);
      setError(failure.message || 'Der Ergebnisabgleich ist nicht bestätigt.');
    } finally { if (alive.current) setBusy(false); }
  }
  const reviewable = canWrite && proof?.verified && proof.attempt.detached && !proof.attempt.reviewed_at
    && proof.attempt.number === run.attempts && ['unknown', 'retryable', 'blocked'].includes(run.state);
  return <section className="connection-evidence" aria-label="Ausführungsnachweise">
    <h4>Ausführungsnachweise{page && ` (${page.total})`}</h4>
    {run.late_result_count > 0 && <p role="status">Eine verspätete Bestätigung wurde erhalten. Prüfen Sie den Nachweis, bevor Sie den Vorgang abgleichen.</p>}
    <p>Jeder Versuch besitzt einen eigenen Nachweis. Hier wird keine Nachricht erneut gesendet und kein Anbieterauftrag wiederholt.</p>
    {error && <div role="alert">{error}<button type="button" className="btn btn-secondary" disabled={busy}
      onClick={() => setRefresh(value => value + 1)}>Nachweise erneut laden</button></div>}
    {loading && <p role="status">Nachweise werden geladen …</p>}
    {!loading && page?.total === 0 && !error && <p>Noch kein Ausführungsversuch. Eine vorbereitete Vorschau allein führt keinen Auftrag aus.</p>}
    <div className="connection-run-list" aria-busy={loading}>{page?.items.map(item => <button type="button" className="connection-run-row"
      key={item.id} disabled={busy || uncertain || item.state !== 'finished'} aria-pressed={selected === item.id}
      onClick={() => { setSelected(item.id); setError(''); }}>
      <strong>Versuch {item.number}: {item.state === 'finished' ? item.detached ? 'Verspäteter Nachweis' : 'Ergebnis gespeichert' : 'Ergebnis ausstehend'}</strong>
      <span>{item.result_bytes} gespeicherte Bytes{item.reviewed_at ? ' · geprüft' : ''}</span>
    </button>)}</div>
    <nav className="connection-actions" aria-label="Nachweisseiten">
      <button type="button" className="btn btn-secondary" disabled={loading || busy || uncertain || !history.length}
        onClick={() => { setCursor(history.at(-1)); setHistory(values => values.slice(0, -1)); }}>Neuere Nachweise</button>
      <button type="button" className="btn btn-secondary" disabled={loading || busy || uncertain || !page?.next_cursor}
        onClick={() => { setHistory(values => [...values, cursor]); setCursor(page.next_cursor); }}>Ältere Nachweise</button>
    </nav>
    {selected && !proof && !error && <p role="status">Der ausgewählte Nachweis wird vollständig geprüft …</p>}
    {proof && <div className="connection-proof">
      <p>Blöcke, Zuordnung und Prüfsumme wurden vollständig geprüft. Angezeigt wird eine um Zugangsdaten bereinigte Ansicht; sie ist nicht die unveränderte Originalantwort.</p>
      <dl className="connection-facts"><dt>Versuch</dt><dd>{proof.attempt.number}</dd><dt>Prüfsumme des gespeicherten Ergebnisses</dt>
        <dd>{proof.manifest.sha256}</dd><dt>Ergebnisumfang</dt><dd>{proof.manifest.bytes} Bytes in {proof.manifest.blocks} Blöcken</dd></dl>
      <details><summary>Geprüftes Ergebnis ansehen</summary><pre className="connection-result-json">{JSON.stringify(proof.projection, null, 2)}</pre></details>
    </div>}
    {(reviewable || uncertain) && <form onSubmit={reconcile}>
      <fieldset disabled={busy || uncertain}>
        <label className="connection-field">Begründung des Abgleichs<textarea value={reason} maxLength={500} required
          onChange={event => setReason(event.target.value)} /></label>
        <label className="connection-check"><input type="checkbox" checked={confirmed} required onChange={event => setConfirmed(event.target.checked)} />
          Ich habe diesen gespeicherten Ergebnisnachweis geprüft. Es wird kein neuer Anbieteraufruf gestartet.</label>
      </fieldset>
      {uncertain && <p role="status">Die Antwort auf den Abgleich fehlt. Die Wiederholung prüft ausschließlich denselben Abgleichsbefehl.</p>}
      <button type="submit" className="btn btn-primary" disabled={busy || (!uncertain && (!confirmed || !reason.trim()))}>
        {busy ? 'Wird abgeglichen …' : uncertain ? 'Abgleichsbestätigung erneut prüfen' : 'Gespeicherten Nachweis übernehmen'}</button>
    </form>}
  </section>;
}
