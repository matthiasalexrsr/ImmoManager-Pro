import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import useLookupChoices from '../../hooks/useLookupChoices';
import { saveBlob } from '../documentShare/documentShare';
import './dataTransfer.css';

const BASE = '/data/import-batches';
const key = () => crypto.randomUUID();
const states = { ready: 'Bereit zur Bestätigung', invalid: 'Fehler in der Vorschau', committed: 'Übernommen', preview: 'Wird geprüft' };

export default function ImportWizard() {
  const choices = useLookupChoices({ portfolios: '/portfolios' });
  const [schema, setSchema] = useState(null);
  const [page, setPage] = useState(null);
  const [skip, setSkip] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [source, setSource] = useState('');
  const [portfolio, setPortfolio] = useState('');
  const [files, setFiles] = useState([]);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const command = useRef(key());
  const input = useRef(null);
  const detailHeading = useRef(null);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api.get(`${BASE}/schema`, { signal: controller.signal }), api.get(`${BASE}?skip=${skip}&limit=25`, { signal: controller.signal })])
      .then(([definition, list]) => { if (!controller.signal.aborted) { setSchema(definition); setPage(list); } })
      .catch(failure => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, [skip, refresh]);
  useEffect(() => { if (selected) detailHeading.current?.focus(); }, [selected?.id, selected?.state]); // eslint-disable-line react-hooks/exhaustive-deps
  const act = async action => {
    if (busy) return;
    setBusy(true); setError('');
    try { await action(); } catch (failure) { setError(failure.message); } finally { setBusy(false); }
  };
  const upload = event => {
    event.preventDefault();
    return act(async () => {
      const data = new FormData();
      files.forEach(file => data.append('files', file));
      data.set('options', JSON.stringify({ source_system: source, portfolio_id: portfolio || null }));
      const row = await api.upload(BASE, data, { idempotencyKey: command.current });
      setSelected(row); setFiles([]); if (input.current) input.current.value = '';
      command.current = key(); setRefresh(value => value + 1);
    });
  };
  const accepted = row => { setSelected(row); setRefresh(value => value + 1); };
  return <section className="panel data-transfer" aria-labelledby="migration-title">
    <div className="panel-body">
      <h2 id="migration-title">Datenübernahme mit geprüfter Vorschau</h2>
      <p>CSV-Vorlagen, ImmoManager-Snapshot oder Kundenexport (ZIP) auswählen, Referenzen zuordnen und Mengen sowie Beträge prüfen. Erst die bestätigte Übernahme verändert Geschäftsdaten.</p>
      <p>Vor einer echten Migration eine vollständige Sicherung erstellen. Wiederherstellungen mit Betriebsdaten verwenden weiterhin den Sicherungsbereich.</p>
      {error && <p role="alert" className="alert-error">{error} <button type="button" className="btn btn-secondary" onClick={() => { setError(''); setRefresh(value => value + 1); }}>Neu laden</button></p>}
      <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => act(async () => {
        const current = api.captureSession(); const blob = await api.getBlob(`${BASE}/templates`); current(); saveBlob(blob, 'ImmoManager-CSV-Vorlagen-v1.zip');
      })}>CSV-Vorlagen und Anleitung herunterladen</button>
      <form onSubmit={upload} className="transfer-grid">
        <label>Quellsystem / stabiler Importname<input required maxLength={100} value={source} disabled={busy} onChange={event => { setSource(event.target.value); command.current = key(); }} /></label>
        <label>Zielbestand für CSV<select value={portfolio} disabled={busy || !choices.ready} onChange={event => { setPortfolio(event.target.value); command.current = key(); }}>
          <option value="">Für Snapshot nicht erforderlich</option>{(choices.data.portfolios || []).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
        </select></label>
        <label>Dateien (bis sechs CSV-Dateien, ein Snapshot oder Kundenexport)<input ref={input} required type="file" multiple accept=".csv,.json,.zip" disabled={busy}
          onChange={event => { setFiles(Array.from(event.target.files || [])); command.current = key(); }} /></label>
        <button className="btn btn-primary" disabled={busy || !source.trim() || !files.length || files.length > 6 || (files.some(file => file.name.endsWith('.csv')) && !portfolio)}>{busy ? 'Wird geprüft …' : 'Vorschau erstellen'}</button>
      </form>
      {choices.error && <p role="alert">{choices.error} <button type="button" onClick={choices.reload}>Zielbestände erneut laden</button></p>}
      <h3>Gespeicherte Übernahmen</h3>
      {!page ? <p role="status">Liste wird geladen …</p> : <>
        <ul className="transfer-list">{page.items.map(row => <li key={row.id}><button type="button" disabled={busy} className="btn btn-secondary"
          onClick={() => act(async () => setSelected(await api.get(`${BASE}/${row.id}`)))}>{row.source_system} · {states[row.state] || row.state} · {new Date(row.created_at).toLocaleString('de-DE')}</button></li>)}</ul>
        {!page.items.length && <p>Noch keine Datenübernahme angelegt.</p>}
        <nav aria-label="Seiten der Datenübernahmen"><button type="button" className="btn btn-secondary" disabled={busy || skip === 0} onClick={() => setSkip(Math.max(0, skip - 25))}>Zurück</button>
          <span> {page.total} Übernahmen </span><button type="button" className="btn btn-secondary" disabled={busy || skip + 25 >= page.total} onClick={() => setSkip(skip + 25)}>Weiter</button></nav>
      </>}
      {selected && <div className="transfer-detail"><h3 ref={detailHeading} tabIndex={-1}>Übernahme: {selected.source_system}</h3>
        <ImportPreview key={selected.id} batch={selected} schema={schema} onChange={accepted} />
      </div>}
    </div>
  </section>;
}

function ImportPreview({ batch, schema, onChange }) {
  const [columns, setColumns] = useState(batch.mappings.columns || {});
  const [references, setReferences] = useState(Object.entries(batch.mappings.references || {}).map(([ref, id]) => `${ref}=${id}`).join('\n'));
  const [reason, setReason] = useState('');
  const [warnings, setWarnings] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const previewKey = useRef(key()), commitKey = useRef(key());
  const preview = batch.preview || {};
  const changed = () => { setDirty(true); setConfirmed(false); previewKey.current = key(); };
  useEffect(() => { setConfirmed(false); setWarnings(false); commitKey.current = key(); }, [batch.revision]);
  const execute = async action => {
    if (busy) return;
    setBusy(true); setError('');
    try { await action(); } catch (failure) { setError(failure.message); } finally { setBusy(false); }
  };
  const renew = () => execute(async () => {
    const mapping = {};
    for (const line of references.split('\n').map(value => value.trim()).filter(Boolean)) {
      const at = line.indexOf('=');
      if (at < 1 || at === line.length - 1) throw new Error('Referenzen zeilenweise als Datensatzart:externe_Referenz=interne_ID eintragen.');
      const ref = line.slice(0, at).trim();
      if (Object.hasOwn(mapping, ref)) throw new Error(`Referenz doppelt eingetragen: ${ref}`);
      mapping[ref] = line.slice(at + 1).trim();
    }
    const row = await api.post(`${BASE}/${batch.id}/preview`, { expected_revision: batch.revision, idempotency_key: previewKey.current, columns, references: mapping });
    onChange(row); setDirty(false);
  });
  return <>
    <p role="status"><strong>{states[batch.state] || batch.state}</strong> · Prüfstand {batch.revision}</p>
    {error && <p role="alert" className="alert-error">{error}</p>}
    {batch.state !== 'committed' && <>
      {(preview.files || []).filter(file => file.headers?.length).map(file => <details key={file.filename}><summary>Feldzuordnung: {file.filename}</summary>
        <div className="transfer-grid">{(schema?.entities[file.entity]?.fields || []).map(field => <label key={field}>{field}{schema.entities[file.entity].required.includes(field) ? ' (Pflicht)' : ''}
          <select value={(columns[file.filename] || file.mapping || {})[field] || ''} disabled={busy} onChange={event => {
            const next = { ...(columns[file.filename] || file.mapping || {}) };
            if (event.target.value) next[field] = event.target.value; else delete next[field];
            setColumns(value => ({ ...value, [file.filename]: next })); changed();
          }}><option value="">Nicht zugeordnet</option>{file.headers.map(header => <option key={header} value={header}>{header}</option>)}</select>
        </label>)}</div></details>)}
      <details><summary>Bestehende Referenzen ausdrücklich zuordnen</summary><p>Eine Zuordnung verwendet den vorhandenen Datensatz unverändert. Beispiel: properties:HAUS-1=vorhandene-ID</p>
        <label>Referenzen, eine Zuordnung je Zeile<textarea value={references} rows={4} disabled={busy} onChange={event => { setReferences(event.target.value); changed(); }} /></label>
      </details>
      <button type="button" className="btn btn-secondary" disabled={busy} onClick={renew}>Vorschau mit aktuellem Zielbestand erneuern</button>
    </>}
    {!!preview.error_count && <div role="alert"><h4>Fehler: {preview.error_count}</h4><ul>{preview.errors.map((message, index) => <li key={index}>{message}</li>)}</ul></div>}
    {!!preview.warning_count && <div><h4>Zu prüfende Hinweise: {preview.warning_count}</h4><ul>{preview.warnings.map((message, index) => <li key={index}>{message}</li>)}</ul></div>}
    <h4>Mengen- und Betragsabgleich der neuen Daten</h4>
    <div className="transfer-table"><table><thead><tr><th>Datensatzart</th><th>Anzahl neu</th><th>Kontrollsummen (EUR)</th></tr></thead><tbody>
      {Object.entries(preview.controls || {}).map(([name, control]) => <tr key={name}><th>{schema?.entities[name]?.label || name}</th><td>{control.count}</td>
        <td>{Object.entries(control.amounts).map(([field, amount]) => <div key={field}>{field}: {amount}</div>)}</td></tr>)}
    </tbody></table></div>
    <p>Originalversionen neu: {preview.document_versions || 0}. Identische vorhandene Datensätze: {Object.values(preview.skipped_existing || {}).reduce((sum, value) => sum + value, 0)}.</p>
    {preview.additional_evidence && <details><summary>Zusätzliche Originale und Fachnachweise</summary><pre>{JSON.stringify(preview.additional_evidence, null, 2)}</pre></details>}
    {(preview.duplicates || []).length > 0 && <details><summary>Dublettendetails ({preview.duplicate_count})</summary><ul>{preview.duplicates.map((row, index) => <li key={index}>{row.entity}: {row.id} – {row.same ? 'identisch, wird übersprungen' : 'abweichend, gesperrt'}</li>)}</ul></details>}
    <details><summary>Vorschau der zu übernehmenden Datensätze</summary><pre>{JSON.stringify(preview.sample || {}, null, 2)}</pre></details>
    {batch.state === 'committed' ? <p role="status">Die bestätigte Übernahme wurde gemeinsam gespeichert. Begründung: {batch.result?.reason}</p> : <form onSubmit={event => {
      event.preventDefault();
      execute(async () => onChange(await api.post(`${BASE}/${batch.id}/commit`, { expected_revision: batch.revision, idempotency_key: commitKey.current, acknowledge_warnings: warnings, reason })));
    }}>
      <label>Prüfvermerk<textarea required minLength={10} maxLength={2000} value={reason} disabled={busy} onChange={event => { setReason(event.target.value); commitKey.current = key(); }} /></label>
      {!!preview.warning_count && <label className="transfer-check"><input type="checkbox" checked={warnings} disabled={busy} onChange={event => { setWarnings(event.target.checked); commitKey.current = key(); }} />Hinweise und mögliche Dubletten geprüft</label>}
      <label className="transfer-check"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} />Zuordnungen, Mengen und Beträge mit der Quelle abgeglichen</label>
      {dirty && <p>Die Feldzuordnung wurde geändert. Bitte zuerst die Vorschau erneuern.</p>}
      <button className="btn btn-primary" disabled={busy || dirty || batch.state !== 'ready' || !confirmed || reason.trim().length < 10 || (!!preview.warning_count && !warnings)}>{busy ? 'Wird gespeichert …' : 'Übernahme verbindlich bestätigen'}</button>
    </form>}
  </>;
}
