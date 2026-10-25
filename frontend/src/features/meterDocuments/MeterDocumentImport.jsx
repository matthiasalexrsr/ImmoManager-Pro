import { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { FileUp, Sparkles } from 'lucide-react';
import { formatDate, formatMoney } from '../../utils/format';
import { ACCEPT, CATEGORY_OPTIONS, applyBody, editableRows, meterDocumentsApi, rowProblem } from './meterDocumentsApi';
import './meterDocuments.css';

const KEY_TYPES = { area_sqm: 'Fläche', person_count: 'Personen', unit_count: 'Einheiten', consumption: 'Verbrauch' };

/** Drop a document of the metering service (ista, Techem, Brunata, Minol, …): the AI of the connected account or
 *  the local rules read it, the person checks every row, and the chosen costs and meter readings are taken over. */
export default function MeterDocumentImport({ propertyId, periodId, withCosts = Boolean(periodId), onApplied, service = meterDocumentsApi }) {
  const id = useId();
  const input = useRef(null);
  const [readers, setReaders] = useState([{ id: 'local', label: 'Lokale Regeln', available: true, ai: false }]);
  const [reader, setReader] = useState('local');
  const [stage, setStage] = useState('idle');
  const [dragging, setDragging] = useState(false);
  const [proposal, setProposal] = useState(null);
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [done, setDone] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    service.readers({ signal: controller.signal }).then(list => {
      if (controller.signal.aborted || !Array.isArray(list)) return;
      setReaders(list);
      const ai = list.find(item => item.ai && item.available);
      if (ai) setReader(ai.id);                // the AI reads by default once an account is connected
    }).catch(() => {});
    return () => controller.abort();
  }, [service]);

  const read = async (file, documentId) => {
    setError(''); setDone('');
    try {
      let document = documentId;
      if (!document) {
        setStage('uploading');
        document = (await service.upload(file, propertyId)).id;
      }
      setStage('reading');
      const result = await service.analyse(document, { property_id: propertyId, billing_period_id: periodId || null, reader });
      setProposal(result);
      setRows(editableRows(result, { withCosts }));
      setStage('review');
    } catch (failure) {
      setError(failure.message || 'Das Dokument konnte nicht ausgewertet werden.');
      setStage(proposal ? 'review' : 'idle');
    }
  };
  const choose = files => { const file = files?.[0]; if (file) read(file); };
  const change = (list, index, values) => setRows(current => ({
    ...current, [list]: current[list].map((row, position) => position === index ? { ...row, ...values } : row) }));
  const problem = rows ? rowProblem(rows, proposal?.keys) : '';
  const chosen = rows ? { costs: rows.costs.filter(row => row.checked), readings: rows.readings.filter(row => row.checked) } : null;
  const chosenSum = chosen ? chosen.costs.reduce((sum, row) => sum + (Number(row.amount) || 0), 0) : 0;

  const apply = async () => {
    if (problem || stage === 'saving') return;
    setStage('saving'); setError('');
    try {
      const result = await service.apply(proposal.document.id, applyBody(rows, { propertyId, periodId }));
      const parts = [result.cost_items.length && `${result.cost_items.length} Kostenpositionen`,
        result.readings_created && `${result.readings_created} Zählerstände`].filter(Boolean);
      setDone(`${parts.join(' und ') || 'Nichts Neues'} übernommen${result.readings_skipped ? ` (${result.readings_skipped} Zählerstände waren schon gespeichert)` : ''}.`);
      setStage('idle'); setProposal(null); setRows(null);
      onApplied?.(result);
    } catch (failure) {
      setError(failure.message || 'Die Übernahme ist fehlgeschlagen.');
      setStage('review');
    }
  };

  const busy = stage === 'uploading' || stage === 'reading' || stage === 'saving';
  const activeReader = readers.find(item => item.id === reader);
  return (
    <section className="meter-import" aria-labelledby={`${id}-title`}>
      <h3 id={`${id}-title`} className="sr-only">Dokument des Messdienstes auswerten</h3>
      {!proposal && <>
        <div className={`meter-drop${dragging ? ' is-dragging' : ''}`} role="button" tabIndex={0} aria-disabled={busy || undefined}
          onClick={() => !busy && input.current?.click()} onKeyDown={event => { if ((event.key === 'Enter' || event.key === ' ') && !busy) { event.preventDefault(); input.current?.click(); } }}
          onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
          onDrop={event => { event.preventDefault(); setDragging(false); if (!busy) choose(event.dataTransfer.files); }}>
          <FileUp size={26} aria-hidden="true" />
          <strong>{stage === 'uploading' ? 'Wird hochgeladen …' : stage === 'reading' ? `${activeReader?.ai ? `${activeReader.label} liest` : 'Wird gelesen'} … das kann bis zu einer Minute dauern`
            : 'Abrechnung oder Ableseprotokoll des Messdienstes hier ablegen'}</strong>
          <span>ista, Techem, Brunata-Metrona, Minol, KALO und andere · PDF, Foto oder CSV · oder klicken zum Auswählen</span>
          <input ref={input} type="file" accept={ACCEPT} hidden onChange={event => { choose(event.target.files); event.target.value = ''; }} />
        </div>
        <fieldset className="meter-readers">
          <legend>Auswertung</legend>
          {readers.map(item => <label key={item.id} className={item.available ? '' : 'is-unavailable'}>
            <input type="radio" name={`${id}-reader`} value={item.id} checked={reader === item.id} disabled={!item.available || busy}
              onChange={() => setReader(item.id)} />
            {item.ai && <Sparkles size={14} aria-hidden="true" />} {item.ai ? `KI: ${item.label}` : item.label}
            {!item.available && <small> (nicht verbunden)</small>}
          </label>)}
          {!readers.some(item => item.ai && item.available) && <p className="text-muted">
            Für die KI-Auswertung im <Link to="/assistant">Assistenten</Link> ein Claude- oder ChatGPT-Konto verbinden. Die lokalen
            Regeln lesen die üblichen Abrechnungen mit Textebene; Scans und Fotos liest die KI.</p>}
        </fieldset>
      </>}
      {error && <p role="alert" className="alert alert-error">{error}</p>}
      {done && <p role="status" className="alert alert-success">{done}</p>}

      {proposal && rows && <div className="meter-review">
        <div className="meter-summary">
          <span><small>Messdienst</small>{proposal.company || 'nicht erkannt'}</span>
          <span><small>Art</small>{proposal.kind_label}</span>
          <span><small>Zeitraum</small>{proposal.period_start ? `${formatDate(proposal.period_start)} – ${formatDate(proposal.period_end)}` : 'nicht erkannt'}</span>
          <span><small>Ablesetag</small>{proposal.reading_date ? formatDate(proposal.reading_date) : '—'}</span>
          {proposal.consumption_share != null && <span><small>Nach Verbrauch</small>{proposal.consumption_share}{'\u00a0%'}</span>}
          {proposal.total != null && <span><small>Summe laut Dokument</small>{formatMoney(proposal.total)}</span>}
          <span><small>Gelesen von</small>{proposal.reader_label}</span>
          <Link to={`/documents/${encodeURIComponent(proposal.document.id)}`} target="_blank" rel="noopener noreferrer">Original öffnen</Link>
        </div>
        {proposal.notes?.length > 0 && <ul className="meter-notes">{proposal.notes.map(note => <li key={note}>{note}</li>)}</ul>}

        {rows.costs.length > 0 && <div className="table-scroll"><table className="data-table meter-table meter-costs">
          <caption>Kosten {withCosts ? '' : '(werden bei einer Abrechnungsperiode übernommen)'}</caption>
          <thead><tr><th className="th-select"><span className="sr-only">Übernehmen</span></th><th>Bezeichnung</th><th className="text-right">Betrag</th>
            <th>Kostenart</th><th>Verteilerschlüssel</th><th className="text-right">Nach Verbrauch</th><th>Umlagefähig</th></tr></thead>
          <tbody>{rows.costs.map((row, index) => <tr key={index}>
            <td className="td-select"><input type="checkbox" aria-label={`${row.description} übernehmen`} checked={row.checked} disabled={!withCosts}
              onChange={event => change('costs', index, { checked: event.target.checked })} /></td>
            <td><input aria-label="Bezeichnung" value={row.description} onChange={event => change('costs', index, { description: event.target.value })} /></td>
            <td className="text-right"><input aria-label={`Betrag ${row.description}`} type="number" step="0.01" min="0" className="meter-number" value={row.amount}
              onChange={event => change('costs', index, { amount: event.target.value })} /></td>
            <td><select aria-label={`Kostenart ${row.description}`} value={row.cost_category || 'other'} onChange={event => change('costs', index, { cost_category: event.target.value })}>
              {CATEGORY_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></td>
            <td><select aria-label={`Verteilerschlüssel ${row.description}`} value={row.allocation_key_id || ''}
              onChange={event => change('costs', index, { allocation_key_id: event.target.value,
                consumption_share: proposal.keys.find(key => key.id === event.target.value)?.key_type === 'consumption' ? (row.consumption_share || 70) : null })}>
              <option value="">Bitte wählen</option>
              {proposal.keys.map(key => <option key={key.id} value={key.id}>{key.name} ({KEY_TYPES[key.key_type] || key.key_type})</option>)}</select>
              {row.reason && <small className="meter-reason">{row.reason}</small>}</td>
            <td className="text-right">{proposal.keys.find(key => key.id === row.allocation_key_id)?.key_type === 'consumption'
              ? <input aria-label={`Verbrauchsanteil ${row.description}`} type="number" min="50" max="70" step="1" className="meter-share" value={row.consumption_share ?? ''}
                onChange={event => change('costs', index, { consumption_share: event.target.value })} /> : '—'}</td>
            <td><input type="checkbox" aria-label={`${row.description} umlagefähig`} checked={row.is_recoverable !== false}
              onChange={event => change('costs', index, { is_recoverable: event.target.checked })} /></td>
          </tr>)}</tbody>
          <tfoot><tr className="table-totals"><td /><td>Ausgewählt</td><td className="text-right">{formatMoney(chosenSum)}</td><td colSpan={4}>
            {proposal.total != null && Math.abs(chosenSum - proposal.total) > 0.05 ? `Dokument: ${formatMoney(proposal.total)}` : ''}</td></tr></tfoot>
        </table></div>}

        {rows.readings.length > 0 && <div className="table-scroll"><table className="data-table meter-table meter-readings">
          <caption>Zählerstände</caption>
          <thead><tr><th className="th-select"><span className="sr-only">Übernehmen</span></th><th>Gerät</th><th>Zähler der Immobilie</th>
            <th>Ablesetag</th><th className="text-right">Stand</th><th className="text-right">Vorjahr / Verbrauch</th></tr></thead>
          <tbody>{rows.readings.map((row, index) => <tr key={index} className={row.sure ? '' : 'meter-unsure'}>
            <td className="td-select"><input type="checkbox" aria-label={`Stand von Gerät ${row.serial} übernehmen`} checked={row.checked}
              onChange={event => change('readings', index, { checked: event.target.checked })} /></td>
            <td><span className="cell-stack"><span>{row.serial}</span>{row.line && <span className="td-sub meter-line" title={row.line}>{row.line}</span>}</span></td>
            <td><select aria-label={`Zähler für Gerät ${row.serial}`} value={row.meter_id || ''}
              onChange={event => change('readings', index, { meter_id: event.target.value || null, checked: Boolean(event.target.value) && row.checked !== false })}>
              <option value="">Keinem Zähler zuordnen</option>
              {proposal.meters.map(meter => <option key={meter.id} value={meter.id}>{meter.label}</option>)}</select></td>
            <td><input aria-label={`Ablesetag Gerät ${row.serial}`} type="date" value={row.reading_date || ''}
              onChange={event => change('readings', index, { reading_date: event.target.value })} /></td>
            <td className="text-right"><input aria-label={`Stand Gerät ${row.serial}`} type="number" step="any" min="0" className="meter-number" value={row.value}
              onChange={event => change('readings', index, { value: event.target.value })} />
              {!row.sure && <small className="meter-reason">bitte prüfen</small>}</td>
            <td className="text-right text-muted">{row.previous != null ? row.previous.toLocaleString('de-DE') : '—'} / {row.consumption != null ? row.consumption.toLocaleString('de-DE') : '—'}</td>
          </tr>)}</tbody>
        </table></div>}

        {proposal.unit_results?.length > 0 && <details className="meter-units"><summary>Ergebnis je Nutzeinheit laut Messdienst ({proposal.unit_results.length})</summary>
          <p className="text-muted">Zum Vergleich mit der eigenen Abrechnung; übernommen werden die Kosten und Zählerstände oben.</p>
          <table className="data-table"><thead><tr><th>Im Dokument</th><th>Einheit</th><th className="text-right">Betrag</th></tr></thead>
            <tbody>{proposal.unit_results.map((item, index) => <tr key={index}><td>{item.label}</td><td>{item.unit_label || '—'}</td>
              <td className="text-right">{formatMoney(item.amount)}</td></tr>)}</tbody></table></details>}

        {problem && <p className="meter-problem" role="status">{problem}</p>}
        {stage === 'reading' && <p role="status" className="text-muted">{activeReader?.ai ? `${activeReader.label} liest` : 'Wird gelesen'} …</p>}
        <div className="toolbar meter-actions">
          <button type="button" className="btn btn-primary" disabled={Boolean(problem) || busy || (!chosen.costs.length && !chosen.readings.length)} onClick={apply}>
            {stage === 'saving' ? 'Wird übernommen …' : `Übernehmen (${chosen.costs.length} Kosten, ${chosen.readings.length} Zählerstände)`}</button>
          <span className="meter-reread">
            <select aria-label="Auswertung" value={reader} disabled={busy} onChange={event => setReader(event.target.value)}>
              {readers.filter(item => item.available).map(item => <option key={item.id} value={item.id}>{item.ai ? `KI: ${item.label}` : item.label}</option>)}
            </select>
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => read(null, proposal.document.id)}>Erneut lesen</button>
          </span>
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => { setProposal(null); setRows(null); setError(''); }}>Verwerfen</button>
        </div>
      </div>}
    </section>
  );
}
