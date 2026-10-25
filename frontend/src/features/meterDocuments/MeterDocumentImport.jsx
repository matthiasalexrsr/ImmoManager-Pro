import { useId, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { FileUp } from 'lucide-react';
import { formatDate, formatMoney } from '../../utils/format';
import AiReadingPanel from '../aiReading/AiReadingPanel';
import { aiReadingApi } from '../aiReading/aiReadingApi';
import { ACCEPT, CATEGORY_OPTIONS, applyBody, editableRows, meterDocumentsApi, rowProblem } from './meterDocumentsApi';
import './meterDocuments.css';

const KEY_TYPES = { area_sqm: 'Fläche', person_count: 'Personen', unit_count: 'Einheiten', consumption: 'Verbrauch' };

/** Drop a document of the metering service (ista, Techem, Brunata, Minol, …): the local rules or the AI of the connected
 *  account read it (with an instruction and a conversation about it), the person checks every row, and the chosen costs
 *  and meter readings are taken over. A document that was taken over before is asked about first. */
export default function MeterDocumentImport({ propertyId, periodId, withCosts = Boolean(periodId), onApplied, service = meterDocumentsApi,
  readingService = aiReadingApi }) {
  const id = useId();
  const input = useRef(null);
  const navigate = useNavigate();
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [source, setSource] = useState(null);             // the uploaded document: { documentId, name }
  const [error, setError] = useState('');
  const [done, setDone] = useState('');

  const choose = async files => {
    const file = files?.[0];
    if (!file || uploading) return;
    setError(''); setDone(''); setUploading(true);
    try {
      const document = await service.upload(file, propertyId);
      setSource({ documentId: document.id, name: file.name });
    } catch (failure) {
      setError(failure.message || 'Das Dokument konnte nicht hochgeladen werden.');
    } finally { setUploading(false); }
  };
  const applied = (result, message) => { setDone(message); setSource(null); onApplied?.(result); };

  return (
    <section className="meter-import" aria-labelledby={`${id}-title`}>
      <h3 id={`${id}-title`} className="sr-only">Dokument des Messdienstes auswerten</h3>
      {!source && <div className={`meter-drop${dragging ? ' is-dragging' : ''}`} role="button" tabIndex={0} aria-disabled={uploading || undefined}
        onClick={() => !uploading && input.current?.click()} onKeyDown={event => { if ((event.key === 'Enter' || event.key === ' ') && !uploading) { event.preventDefault(); input.current?.click(); } }}
        onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
        onDrop={event => { event.preventDefault(); setDragging(false); choose(event.dataTransfer.files); }}>
        <FileUp size={26} aria-hidden="true" />
        <strong>{uploading ? 'Wird hochgeladen …' : 'Abrechnung oder Ableseprotokoll des Messdienstes hier ablegen'}</strong>
        <span>ista, Techem, Brunata-Metrona, Minol, KALO und andere · PDF, Foto oder CSV · oder klicken zum Auswählen</span>
        <input ref={input} type="file" accept={ACCEPT} hidden onChange={event => { choose(event.target.files); event.target.value = ''; }} />
      </div>}
      {error && <p role="alert" className="alert alert-error">{error}</p>}
      {done && <p role="status" className="alert alert-success">{done}</p>}
      {source && <AiReadingPanel key={source.documentId} surface="meter_document" autoStart service={readingService} source={source}
        params={{ property_id: propertyId, billing_period_id: periodId || null }} title="Dokument des Messdienstes"
        onOpenExisting={item => navigate(item.href)} onCancel={() => setSource(null)}>
        {reading => reading.proposal ? <MeterReview key={reading.revision} reading={reading} withCosts={withCosts} propertyId={propertyId}
          periodId={periodId} service={service} readingService={readingService} onApplied={applied} /> : null}
      </AiReadingPanel>}
    </section>
  );
}

/** The rows of one reading to check and take over; a new answer in the conversation starts them afresh. */
function MeterReview({ reading, withCosts, propertyId, periodId, service, readingService, onApplied }) {
  const proposal = reading.proposal;
  const [rows, setRows] = useState(() => editableRows(proposal, { withCosts }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const change = (list, index, values) => setRows(current => ({
    ...current, [list]: current[list].map((row, position) => position === index ? { ...row, ...values } : row) }));
  const problem = rowProblem(rows, proposal.keys);
  const chosen = { costs: rows.costs.filter(row => row.checked), readings: rows.readings.filter(row => row.checked) };
  const chosenSum = chosen.costs.reduce((sum, row) => sum + (Number(row.amount) || 0), 0);
  const blocked = (reading.duplicates?.length > 0 && !reading.decision?.action) || reading.status !== 'open';

  const apply = async () => {
    if (problem || saving || blocked) return;
    setSaving(true); setError('');
    try {
      const result = await service.apply(proposal.document.id, applyBody(rows, { propertyId, periodId }));
      readingService.finish(reading, 'taken_over', { kind: 'meter_document', id: proposal.document.id }).catch(() => {});
      const parts = [result.cost_items.length && `${result.cost_items.length} Kostenpositionen`,
        result.readings_created && `${result.readings_created} Zählerstände`].filter(Boolean);
      onApplied(result, `${parts.join(' und ') || 'Nichts Neues'} übernommen${result.readings_skipped ? ` (${result.readings_skipped} Zählerstände waren schon gespeichert)` : ''}.`);
    } catch (failure) {
      setError(failure.message || 'Die Übernahme ist fehlgeschlagen.');
      setSaving(false);
    }
  };

  return (
  <div className="meter-review">
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
      <div className="toolbar meter-actions">
        <button type="button" className="btn btn-primary" disabled={Boolean(problem) || saving || blocked || (!chosen.costs.length && !chosen.readings.length)} onClick={apply}>
          {saving ? 'Wird übernommen …' : `Übernehmen (${chosen.costs.length} Kosten, ${chosen.readings.length} Zählerstände)`}</button>
        {blocked && <small className="text-muted">Bitte zuerst oben entscheiden, was mit dem vorhandenen Eintrag geschehen soll.</small>}
      </div>
      {error && <p role="alert" className="alert alert-error">{error}</p>}
    </div>
  );
}
