import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useCanWrite } from '../contexts/AuthContext';
import { isDefiniteIntegrationFailure } from '../utils/integrationFields';

const BASE = '/integration-connections';
const SESSION_MESSAGE = 'Die Sitzung wurde geändert. Bitte erneut anmelden.';
const validRun = (value, run, connectionId) => value?.id === run.id && value.connection_id === connectionId
  && Number.isInteger(value.revision) && value.revision > 0;

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
  const [conflict, setConflict] = useState(false);
  const [sessionInvalid, setSessionInvalid] = useState(false);
  const pending = useRef(null);
  const alive = useRef(false);
  const invalidate = useCallback(() => {
    setSessionInvalid(true); setPage(null); setProof(null); setSelected(null); setReason(''); setConfirmed(false);
    pending.current = null; setUncertain(false); setConflict(false); setLoading(false);
  }, []);
  const path = `${BASE}/${encodeURIComponent(connectionId)}/runs/${encodeURIComponent(run.id)}`;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    if (sessionInvalid) return;
    const controller = new AbortController();
    setLoading(true); setError('');
    const query = new URLSearchParams({ limit: '25' }); if (cursor) query.set('cursor', cursor);
    async function load() {
      try {
        const current = api.captureSession();
        const result = await api.get(`${path}/attempts?${query}`, { signal: controller.signal });
        if (controller.signal.aborted) return; current();
        if (!Array.isArray(result?.items) || !Number.isInteger(result.total)
            || result.items.some(item => item.run_id !== run.id)) throw new Error('Die Ergebnisliste wurde nicht vollständig bestätigt.');
        setPage(result);
      } catch (failure) {
        if (controller.signal.aborted) return;
        if (failure.code === 'SESSION_CHANGED') invalidate();
        else setError(failure.message || 'Die Ergebnisliste konnte nicht geladen werden.');
      } finally { if (!controller.signal.aborted) setLoading(false); }
    }
    load();
    return () => controller.abort();
  }, [path, run.id, run.revision, cursor, refresh, sessionInvalid, invalidate]);
  useEffect(() => {
    setProof(null); setConfirmed(false); setReason('');
    if (!selected || sessionInvalid) return;
    const controller = new AbortController();
    async function load() {
      try {
        const current = api.captureSession();
        const result = await api.get(`${path}/attempts/${encodeURIComponent(selected)}`, { signal: controller.signal });
        if (controller.signal.aborted) return; current();
        if (result?.attempt?.id !== selected || result.attempt.run_id !== run.id || result.verified !== true
            || !/^[a-f0-9]{64}$/i.test(result.manifest?.sha256 || '') || !Number.isInteger(result.manifest.bytes) || result.manifest.bytes < 0
            || !Number.isInteger(result.manifest.blocks) || result.manifest.blocks < 0 || !Object.hasOwn(result, 'projection'))
          throw new Error('Der Ergebnisnachweis wurde nicht vollständig geprüft.');
        setProof(result);
      } catch (failure) {
        if (controller.signal.aborted) return;
        if (failure.code === 'SESSION_CHANGED') invalidate();
        else setError(failure.message || 'Der Ergebnisnachweis konnte nicht geladen werden.');
      }
    }
    load();
    return () => controller.abort();
  }, [path, selected, run.id, run.revision, refresh, sessionInvalid, invalidate]);
  async function reconcile(event) {
    event.preventDefault();
    if (busy || sessionInvalid || conflict || !canWrite || (!pending.current && (!confirmed || !reason.trim() || !proof?.verified))) return;
    setBusy(true); setError('');
    try {
      const current = api.captureSession();
      const command = pending.current || { idempotency_key: crypto.randomUUID(), base_revision: run.revision,
        attempt_id: proof.attempt.id, reason: reason.trim(), confirm: true };
      pending.current = command;
      const result = await api.post(`${path}/reconcile-recorded`, command);
      current(); if (!alive.current) return;
      if (!validRun(result, run, connectionId)) throw new Error('Der Abgleich wurde nicht eindeutig bestätigt.');
      pending.current = null; setUncertain(false); setConfirmed(false); onApplied(result); setRefresh(value => value + 1);
    } catch (failure) {
      if (!alive.current) return;
      if (failure.code === 'SESSION_CHANGED') { invalidate(); return; }
      if (isDefiniteIntegrationFailure(failure)) { pending.current = null; setUncertain(false); setConfirmed(false); } else setUncertain(true);
      setConflict(failure.statusCode === 409);
      setError(failure.message || 'Der Ergebnisabgleich ist nicht bestätigt.');
    } finally { if (alive.current) setBusy(false); }
  }
  async function reloadRun() {
    if (busy || sessionInvalid || uncertain) return;
    setBusy(true); setError('');
    try {
      const current = api.captureSession();
      const result = await api.get(path);
      current(); if (!alive.current) return;
      if (!validRun(result, run, connectionId)) throw new Error('Der aktuelle Vorgangsstand ist unvollständig.');
      setConflict(false); setConfirmed(false); onApplied(result); setRefresh(value => value + 1);
    } catch (failure) {
      if (!alive.current) return;
      if (failure.code === 'SESSION_CHANGED') invalidate();
      else setError(failure.message || 'Der Vorgangsstand konnte nicht geladen werden.');
    } finally { if (alive.current) setBusy(false); }
  }
  const reviewable = canWrite && !conflict && proof?.verified && proof.attempt.detached && !proof.attempt.reviewed_at
    && proof.attempt.number === run.attempts && ['unknown', 'retryable', 'blocked'].includes(run.state);
  if (sessionInvalid) return <section className="connection-evidence" role="alert">{SESSION_MESSAGE}</section>;
  return <section className="connection-evidence" aria-label="Ausführungsnachweise">
    <h4>Ausführungsnachweise{page && ` (${page.total})`}</h4>
    {run.late_result_count > 0 && <p role="status">Eine verspätete Bestätigung wurde erhalten. Prüfen Sie den Nachweis, bevor Sie den Vorgang abgleichen.</p>}
    <p>Jeder Versuch besitzt einen eigenen Nachweis. Hier wird keine Nachricht erneut gesendet und kein Anbieterauftrag wiederholt.</p>
    {error && <div role="alert">{error}<button type="button" className="btn btn-secondary" disabled={busy}
      onClick={() => setRefresh(value => value + 1)}>Nachweise erneut laden</button></div>}
    {conflict && <button type="button" className="btn btn-secondary" disabled={busy || uncertain} onClick={reloadRun}>Vorgangsstand neu laden</button>}
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
    {canWrite && (reviewable || uncertain) && <form onSubmit={reconcile}>
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
