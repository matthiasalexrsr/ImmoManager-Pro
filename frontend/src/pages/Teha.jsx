import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useCanWrite } from '../contexts/AuthContext';
import './teha.css';

const labels = { property: 'Immobilie', period: 'Periode', document: 'Dokument', unit: 'Einheit', user: 'Nutzer', technical_order: 'Techniktermin',
  new: 'Neu', unchanged: 'Unverändert', changed: 'Geändert', conflict: 'Konflikt', receiving: 'Empfang wird aufbereitet', ready: 'Vollständig aufbereitet',
  cancelled: 'Abgebrochen', revoked: 'Quelle zurückgezogen', completed: 'Empfang abgeschlossen', retryable: 'Erneut abrufbar', executing: 'Abruf läuft', prepared: 'Vorbereitet' };
const key = () => crypto.randomUUID();
const query = values => new URLSearchParams(Object.entries(values).filter(([, v]) => v != null && v !== '')).toString();
const definite = error => [400, 401, 403, 404, 409, 413, 422].includes(error.statusCode);

function RunProblem({ connection, run }) {
  const [message, setMessage] = useState('');
  useEffect(() => {
    let active = true;
    const current = api.captureSession();
    api.get(`/teha/${connection}/runs/${run.id}/diagnostic`).then(value => {
      current(); if (active) setMessage(value.message + (value.retry_after_seconds ? ` Wartezeit: ${value.retry_after_seconds} Sekunden.` : ''));
    }).catch(error => { if (active && error.code !== 'SESSION_CHANGED') setMessage(error.message); });
    return () => { active = false; };
  }, [connection, run.id]);
  return message ? <p role="alert">{message}</p> : null;
}

function Page({ url, render, refresh = 0, title }) {
  const [page, setPage] = useState(null), [error, setError] = useState(''), [cursor, setCursor] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => { setCursor(''); setPage(null); }, [url]);
  useEffect(() => {
    let active = true;
    setError(''); setPage(null);
    const current = api.captureSession();
    api.get(`${url}${url.includes('?') ? '&' : '?'}${query({ cursor, limit: 50 })}`)
      .then(result => { current(); if (active) setPage(result); })
      .catch(failure => { if (active && failure.code !== 'SESSION_CHANGED') setError(failure.message); });
    return () => { active = false; };
  }, [url, cursor, refresh, attempt]);
  return <section className="teha-panel"><h2>{title}</h2>
    {error ? <p role="alert">{error} <button onClick={() => setAttempt(v => v + 1)}>Erneut laden</button></p> :
      !page ? <p role="status">Wird geladen …</p> : <>
        <p>{page.total} Einträge insgesamt</p>{page.items.length ? <ul className="teha-list">{page.items.map(render)}</ul> : <p>Keine Einträge vorhanden.</p>}
        <div className="teha-actions"><button disabled={!cursor} onClick={() => setCursor('')}>Erste Seite</button>
          <button disabled={!page.next_cursor} onClick={() => setCursor(page.next_cursor)}>Weitere Einträge</button></div>
      </>}
  </section>;
}

function TargetPicker({ connection, kind, propertyId, selected, onSelect, disabled }) {
  const names = { property: 'Immobilie', billing_period: 'Abrechnungsperiode', unit: 'Einheit', tenant: 'Partei', contract: 'Mietvertrag' };
  return <details className="teha-target"><summary>{names[kind]}: {selected?.title || selected?.id || 'Bitte zuordnen'}</summary>
    {selected && <button disabled={disabled} onClick={() => onSelect(null)}>Zuordnung entfernen</button>}
    <Page title={`${names[kind]} auswählen`} url={`/teha/${connection}/choices/${kind}?${query({ property_id: propertyId })}`}
      render={row => <li key={row.id}><button disabled={disabled} onClick={() => onSelect(row)}>{row.title} <small>{row.id}</small></button></li>} />
  </details>;
}

function ItemReview({ connection, item, initialTargets, mutate, busy, onPublished }) {
  const [preview, setPreview] = useState(null), [targets, setTargets] = useState(initialTargets || {}), [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setPreview(null); setError('');
    const current = api.captureSession();
    api.get(`/teha/${connection}/items/${item.id}/preview`).then(result => {
      current(); if (!active) return;
      setPreview(result);
      if (result.targets.length) setTargets(Object.fromEntries(result.targets.map(target => [target.kind, target])));
    }).catch(failure => { if (active && failure.code !== 'SESSION_CHANGED') setError(failure.message); });
    return () => { active = false; };
  }, [connection, item.id, attempt]);
  async function map() {
    await mutate(`/teha/${connection}/items/${item.id}/mapping`, {
      idempotency_key: key(), mapping_revision: preview.mapping_revision, source_sha256: item.source_sha256, confirm: true,
      targets: Object.values(targets).filter(Boolean).map(({ kind, id, revision }) => ({ kind, id, revision })),
    }, () => setAttempt(v => v + 1));
  }
  async function prepareReturn() {
    const current = api.captureSession();
    try {
      let source = preview.targets.find(t => t.kind === 'billing_period');
      if (item.kind === 'technical_order') {
        const value = await api.get(`/workspace/source/maintenance/${preview.publication.project_id}`); current();
        source = { kind: 'maintenance', id: value.id, revision: value.revision };
      }
      await mutate(`/teha/${connection}/items/${item.id}/prepare-return`, {
        idempotency_key: key(), kind: item.kind === 'period' ? 'cost_user_data' : 'maintenance_order',
        mapping_revision: preview.mapping_revision, source, confirm: true,
      });
    } catch (failure) { if (failure.code !== 'SESSION_CHANGED') setError(failure.message); }
  }
  return <section className="teha-panel" aria-label="Zuordnung und Vorschau">
    <h2>{item.source.title}</h2><p>{labels[item.kind]} · Quellkennung <code>{JSON.stringify(item.source.identity)}</code></p>
    {error && <p role="alert">{error} <button onClick={() => setAttempt(v => v + 1)}>Vorschau erneut laden</button></p>}
    {preview && <>
      <p><strong>{labels[preview.state]}</strong></p>{preview.errors.map(message => <p role="alert" key={message}>{message}</p>)}
      <p>Zuordnung ausdrücklich prüfen. Anzeigenamen werden nicht als Identitäten verwendet.</p>
      {['property', 'billing_period', 'unit', 'tenant', 'contract'].map(kind => <TargetPicker key={kind} kind={kind} connection={connection}
        propertyId={kind === 'property' ? null : targets.property?.id} selected={targets[kind]} disabled={busy}
        onSelect={value => setTargets(old => kind === 'property' ? { property: value } : { ...old, [kind]: value })} />)}
      <div className="teha-actions"><button disabled={busy || !targets.property} onClick={map}>Zuordnung bestätigen</button>
        <button disabled={busy || preview.state === 'conflict'} onClick={() => mutate(`/teha/${connection}/items/${item.id}/confirm`, {
          idempotency_key: key(), preview_sha256: preview.preview_sha256, confirm: true,
        }, result => { onPublished(result); setAttempt(v => v + 1); })}>
          {preview.state === 'unchanged' ? 'Vorhandenen Übernahmebeleg prüfen' : 'Geprüfte Übernahme bestätigen'}</button></div>
      <p>Originalhash: <code>{item.content_sha256 || 'Keine Originalbytes empfangen'}</code></p>
      <details><summary>Unveränderte Quellfelder prüfen</summary><pre>{JSON.stringify(item.source.raw, null, 2)}</pre></details>
      <p className="text-muted">{preview.evidence_gap}</p>
      {(item.kind === 'period' && preview.targets.some(t => t.kind === 'billing_period') || item.kind === 'technical_order' && preview.publication?.project_id) &&
        <button disabled={busy || !preview.mapping_revision} onClick={prepareReturn}>Rückübertragung lokal vorbereiten (ohne Versand)</button>}
    </>}
  </section>;
}

export default function Teha() {
  const [params, setParams] = useSearchParams();
  const connection = params.get('connection') || '', batch = params.get('batch') || '';
  const [item, setItem] = useState(null), [refresh, setRefresh] = useState(0), [error, setError] = useState('');
  const [busy, setBusy] = useState(false), [uncertain, setUncertain] = useState(false), [receipt, setReceipt] = useState(null);
  const [action, setAction] = useState('inventory'), [lieg, setLieg] = useState(''), [reference, setReference] = useState(''), [termin, setTermin] = useState('');
  const [prepared, setPrepared] = useState(null), [reason, setReason] = useState('');
  const pending = useRef(null), mounted = useRef(true), epoch = useRef(0);
  const canWrite = useCanWrite('/integrations');
  const [initialTargets, setInitialTargets] = useState({});
  useEffect(() => {
    let active = true;
    const current = api.captureSession();
    const selected = {};
    Promise.all(['property', 'billing_period'].map(async kind => {
      const id = params.get(kind === 'property' ? 'property_id' : 'period_id');
      if (id) { const value = await api.get(`/workspace/source/${kind}/${encodeURIComponent(id)}`); selected[kind] = { kind, ...value }; }
    })).then(() => { current(); if (active) setInitialTargets(selected); }).catch(failure => { if (active && failure.code !== 'SESSION_CHANGED') setError(failure.message); });
    return () => { active = false; };
  }, [params]);
  useEffect(() => {
    mounted.current = true;
    const clear = () => { epoch.current++; pending.current = null; setItem(null); setReceipt(null); setPrepared(null); setInitialTargets({}); setUncertain(false); };
    window.addEventListener('workspace-logout', clear);
    return () => { mounted.current = false; window.removeEventListener('workspace-logout', clear); };
  }, []);
  useEffect(() => { epoch.current++; pending.current = null; setUncertain(false); setItem(null); setReceipt(null); setPrepared(null); }, [connection, batch]);

  async function mutate(path, payload, done) {
    if (busy) return;
    const current = api.captureSession(), captured = epoch.current;
    pending.current = pending.current || { path, payload, done };
    const command = pending.current;
    setBusy(true); setError('');
    try {
      const result = await api.post(command.path, command.payload);
      current(); if (!mounted.current || captured !== epoch.current) return;
      pending.current = null; setUncertain(false); command.done?.(result); setRefresh(v => v + 1);
    } catch (failure) {
      if (!mounted.current || failure.code === 'SESSION_CHANGED' || captured !== epoch.current) return;
      if (definite(failure)) { pending.current = null; setUncertain(false); }
      else setUncertain(true);
      setError(failure.message || 'Der Vorgang wurde nicht bestätigt.');
    } finally { if (mounted.current) setBusy(false); }
  }
  async function prepare(event) {
    event.preventDefault();
    const current = api.captureSession(), captured = epoch.current;
    try {
      const config = await api.get(`/integration-connections/${connection}`); current();
      if (!mounted.current || captured !== epoch.current) return;
      const payload = action === 'document' ? { lieg_nr: lieg, reference } : action === 'documents' ? { lieg_nr: lieg } : action === 'users' ? { termin_id: Number(termin), lieg_nr: lieg } : {};
      await mutate(`/integration-connections/${connection}/runs`, { idempotency_key: key(), config_revision: config.revision, action, payload }, setPrepared);
    } catch (failure) { if (failure.code !== 'SESSION_CHANGED') setError(failure.message); }
  }
  async function download(row) {
    const current = api.captureSession();
    try {
      const blob = await api.getBlob(`/teha/${connection}/receipts/${row.id}/original`); current();
      const url = URL.createObjectURL(blob), anchor = document.createElement('a');
      anchor.href = url; anchor.download = 'TEHA-Original.pdf'; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) { if (failure.code !== 'SESSION_CHANGED') setError(failure.message); }
  }
  const historyRow = row => <li key={row.id}><code>{row.content_sha256 || row.source_sha256}</code>
    {row.predecessor_id && <span>Neue Fassung zu Übernahme {row.predecessor_id}</span>}
    <div className="teha-actions">{row.document_id && <><button onClick={() => download(row)}>Original herunterladen</button><Link to={`/documents?focus_id=${row.document_id}`}>Dokumentenakte</Link></>}
      {row.task_id && <Link to={`/tasks?focus_id=${row.task_id}`}>Aufgabe</Link>}{row.project_id && <Link to={`/maintenance/${row.project_id}`}>Projekt</Link>}</div></li>;
  return <main className="page teha-workspace"><h1>TEHA Kundenportal</h1>
    <p>Empfangen, exakt zuordnen und nach Prüfung übernehmen. Die Vorschau verändert keine Abrechnung und sendet keine Daten an TEHA.</p>
    <p><Link to="/integration-connections">Verbindungen verwalten</Link> · <Link to="/documents">Dokumente</Link></p>
    {error && <div role="alert" className="alert alert-danger">{error}</div>}
    {uncertain && <p role="status">Die Antwort ist unbestätigt. Den identischen Befehl prüfen, damit kein zweiter Vorgang entsteht.
      <button disabled={busy} onClick={() => mutate()}>Speicherstatus prüfen</button></p>}
    <fieldset disabled={busy || uncertain}>
      <Page title="TEHA-Verbindung auswählen" url="/teha/connections" refresh={refresh}
        render={row => <li key={row.id}><button aria-pressed={connection === row.id} onClick={() => {
          setParams(old => { const next = new URLSearchParams(old); next.set('connection', row.id); next.delete('batch'); return next; });
        }}>{row.name}{row.enabled && !row.archived ? '' : ' (deaktiviert)'}</button></li>} />
      {connection && <>
        {canWrite && <section className="teha-panel"><h2>Neuen Empfang vorbereiten</h2><form onSubmit={prepare}>
          <label>Quelle<select value={action} onChange={e => { setAction(e.target.value); setPrepared(null); }}>
            <option value="inventory">Immobilien und Perioden</option><option value="documents">Dokumentverzeichnis</option>
            <option value="document">Dokumentoriginal</option><option value="orders">Techniktermine</option><option value="users">Nutzer eines Techniktermins</option></select></label>
          {['documents', 'document', 'users'].includes(action) && <label>Exakte TEHA-Liegenschaftsnummer<input value={lieg} required onChange={e => setLieg(e.target.value)} /></label>}
          {action === 'document' && <label>Exakter Dokumentverweis<input value={reference} required onChange={e => setReference(e.target.value)} /></label>}
          {action === 'users' && <label>Termin-ID (nicht Auftragsnummer)<input type="number" min="1" step="1" value={termin} required onChange={e => setTermin(e.target.value)} /></label>}
          <button type="submit">Empfang vorbereiten</button></form>
          {prepared && <p>Vorbereitet: {action}. <button onClick={() => mutate(`/integration-connections/${connection}/runs/${prepared.id}/dispatch`, {
            idempotency_key: key(), base_revision: prepared.revision, confirm: true,
          }, () => setPrepared(null))}>Lesenden Empfang ausdrücklich starten</button></p>}
        </section>}
        <Page title="Empfangsläufe und Fehler" url={`/integration-connections/${connection}/runs`} refresh={refresh}
          render={row => <li key={row.id}><strong>{labels[row.state] || row.state}</strong> · {row.action}<p>{row.safe_summary}</p>
            {['retryable', 'blocked'].includes(row.state) && <RunProblem connection={connection} run={row} />}
            {canWrite && row.state === 'completed' && <button onClick={() => mutate(`/teha/${connection}/runs/${row.id}/stage`, {
              idempotency_key: key(), run_revision: row.revision, batch_revision: 0,
            }, result => setParams(old => { const next = new URLSearchParams(old); next.set('batch', result.id); return next; }))}>Empfang aufbereiten</button>}
            {canWrite && ['prepared', 'retryable'].includes(row.state) && <button onClick={() => mutate(`/integration-connections/${connection}/runs/${row.id}/dispatch`, {
              idempotency_key: key(), base_revision: row.revision, confirm: true,
            })}>Lesenden Empfang {row.state === 'prepared' ? 'starten' : 'erneut versuchen'}</button>}</li>} />
        <Page title="Gespeicherte Empfänge und Fortschritt" url={`/teha/${connection}/batches`} refresh={refresh}
          render={row => <li key={row.id}><strong>{labels[row.state]}</strong> · {row.next_index} von {row.total}
            <button onClick={() => setParams(old => { const next = new URLSearchParams(old); next.set('batch', row.id); return next; })}>Öffnen</button>
            {canWrite && row.state === 'receiving' && <button onClick={async () => {
              const current = api.captureSession(); const run = await api.get(`/integration-connections/${connection}/runs/${row.run_id}`); current();
              mutate(`/teha/${connection}/runs/${row.run_id}/stage`, { idempotency_key: key(), run_revision: run.revision, batch_revision: row.revision });
            }}>Nächsten Abschnitt aufbereiten</button>}
            {canWrite && !['cancelled', 'revoked'].includes(row.state) && <details><summary>Abbruch / Quellwiderruf</summary>
              <label>Begründung<input value={reason} onChange={e => setReason(e.target.value)} /></label>
              {['cancelled', 'revoked'].map(state => <button key={state} disabled={!reason.trim()} onClick={() => mutate(`/teha/${connection}/batches/${row.id}/decision`, {
                idempotency_key: key(), base_revision: row.revision, state, reason,
              })}>{state === 'cancelled' ? 'Weiterverarbeitung abbrechen' : 'Quelle zurückziehen'}</button>)}</details>}</li>} />
        {batch && <Page title="Empfangene Einträge" url={`/teha/${connection}/batches/${batch}/items`} refresh={refresh}
          render={row => <li key={row.id}><button onClick={() => { setReceipt(null); setItem(row); }}>{row.source.title} · {labels[row.kind]}</button></li>} />}
        {item && canWrite && <ItemReview key={item.id} connection={connection} item={item} initialTargets={initialTargets} mutate={mutate}
          busy={busy || uncertain} onPublished={setReceipt} />}
        {receipt && <section className="teha-panel" role="status"><h2>Übernahme bestätigt</h2><ul className="teha-list">{historyRow(receipt)}</ul></section>}
        <Page title="Unveränderliche Übernahmehistorie" url={`/teha/${connection}/history`} refresh={refresh} render={historyRow} />
        <Page title="Lokal vorbereitete Rückübertragungen" url={`/teha/${connection}/returns`} refresh={refresh} render={row => <li key={row.id}>
          <strong>{row.snapshot.kind === 'cost_user_data' ? 'Kosten-/Nutzerdaten' : 'Wartungsvorgang'}</strong> · {row.source_changed ? 'Quelle inzwischen geändert – neu vorbereiten' : 'Quellstand eingefroren'}
          <p>Nicht versandt; kein freigegebener TEHA-Schreibvertrag.</p><code>{row.snapshot_sha256}</code>
          <details><summary>Vorbereitete lokale Daten prüfen</summary><pre>{JSON.stringify(row.snapshot, null, 2)}</pre></details></li>} />
        <section className="teha-panel"><h2>Rückübertragung</h2><p>Kosten-/Nutzerdaten und Wartungsaufträge können noch nicht an TEHA übertragen werden.
          Es fehlen belegte Endpunkte, Feldverträge, Wiederholungsschutz und Ergebnisabgleich. Lokale Übernahmebelege sind keine Portalbestätigung.</p>
          <button disabled>Kosten-/Nutzerdaten übertragen</button> <button disabled>Wartungsauftrag senden</button></section>
      </>}
    </fieldset>
  </main>;
}
