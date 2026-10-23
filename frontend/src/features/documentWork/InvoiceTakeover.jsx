import { useState } from 'react';
import { sourceCommand } from './documentWorkApi';
import AppLink from '../../components/AppLink';

const FIELDS = [
  ['supplier', 'Lieferant', 'text'], ['invoice_number', 'Rechnungsnummer', 'text'],
  ['invoice_date', 'Rechnungsdatum', 'date'], ['net_amount', 'Nettobetrag (€)', 'text'],
  ['vat_rate', 'Umsatzsteuer (%)', 'text'], ['vat_amount', 'Umsatzsteuerbetrag (€)', 'text'],
  ['gross_amount', 'Bruttobetrag (€)', 'text'],
];
const amount = value => {
  const text = String(value).trim().replace(',', '.');
  if (!/^\d+(\.\d{1,2})?$/.test(text)) throw new Error('Beträge bitte eindeutig mit höchstens zwei Nachkommastellen angeben.');
  return text;
};

export default function InvoiceTakeover({ source, proposal, perform, disabled, base }) {
  const observed = proposal.observed?.intake?.result || proposal.observed || {};
  const suggested = proposal.observation_state === 'stale' ? {} : observed.result || observed;
  const [values, setValues] = useState(() => ({ supplier: suggested.supplier || '', invoice_number: suggested.invoice_number || '',
    invoice_date: suggested.invoice_date || '', net_amount: '', vat_rate: '19', vat_amount: '', gross_amount: suggested.total_amount || '',
    skonto_percent: '', skonto_days: '', payment_days: '' }));
  const [origins, setOrigins] = useState({});
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [multiVat, setMultiVat] = useState(false);
  const [vatLines, setVatLines] = useState([{ rate: '19', net: '', vat: '' }, { rate: '7', net: '', vat: '' }]);
  const submit = event => {
    event.preventDefault(); setError(null);
    try {
      const invoice = Object.fromEntries(FIELDS.map(([name]) => [name, name.endsWith('_amount') || name === 'vat_rate' ? amount(values[name]) : values[name]]));
      const receipt = { invoice, vat_lines: [{ rate: invoice.vat_rate, net: invoice.net_amount, vat: invoice.vat_amount }] };
      if (multiVat) receipt.vat_lines = vatLines.map(line => ({ rate: amount(line.rate), net: amount(line.net), vat: amount(line.vat) }));
      if (values.skonto_percent || values.skonto_days) {
        receipt.skonto_percent = amount(values.skonto_percent); receipt.skonto_days = Number(values.skonto_days);
      }
      if (values.payment_days) receipt.payment_days = Number(values.payment_days);
      perform(`${base}/invoice-takeover`, { ...sourceCommand(source), proposal_id: proposal.proposal_id,
        confirmed, receipt, field_sources: origins }, setResult);
    } catch (failure) { setError(failure.message); }
  };
  return <section aria-label="Rechnung aus Beleg übernehmen"><h3>Rechnungsangaben prüfen</h3>
    <p>Quelle: {source.filename} · SHA-256 <code>{proposal.source_sha256}</code></p>
    <p>Erkannte Angaben sind Vorschläge. Prüfen Sie jede Angabe am Original. Die Übernahme eröffnet die vorhandene Rechnungsprüfung; eine Freigabe oder Buchung erfolgt erst in deren eigenen Schritten.</p>
    {proposal.observation_state === 'stale' && <p role="alert">Die gespeicherte Erkennung stammt aus einer anderen Dateifassung. Erfassen Sie die aktuellen Werte am Original neu.</p>}
    <details><summary>Erkennung und Quellenfelder anzeigen</summary><pre>{JSON.stringify(proposal.observed, null, 2)}</pre></details>
    {result ? <p role="status">Rechnung übernommen. <AppLink to={`/invoice-review/${result.invoice_id}`}>Rechnungsprüfung öffnen</AppLink></p>
      : <form onSubmit={submit}>
        <div className="document-invoice-grid">{FIELDS.map(([name, label, type]) => <div key={name}>
          <label>{label}<input required type={type} value={values[name]} onChange={event => setValues(previous => ({ ...previous, [name]: event.target.value }))} /></label>
          <label>Herkunft bestätigen<select required value={origins[name] || ''} onChange={event => setOrigins(previous => ({ ...previous, [name]: event.target.value }))}>
            <option value="">Bitte prüfen …</option><option value="reviewed_ocr">Erkennung am Original geprüft</option><option value="manual_correction">Manuell erfasst / korrigiert</option>
          </select></label></div>)}</div>
        <div className="document-invoice-grid">{[['skonto_percent', 'Skonto (%)'], ['skonto_days', 'Skontofrist (Tage)'], ['payment_days', 'Zahlungsfrist (Tage)']].map(([name, label]) =>
          <label key={name}>{label}<input value={values[name]} onChange={event => setValues(previous => ({ ...previous, [name]: event.target.value }))} /></label>)}</div>
        <label><input type="checkbox" checked={multiVat} onChange={event => setMultiVat(event.target.checked)} />Mehrere Umsatzsteuersätze laut Originalbeleg</label>
        {multiVat && <fieldset><legend>Steuerzeilen am Original prüfen</legend>{vatLines.map((line, index) => <div className="document-invoice-grid" key={index}>
          {Object.entries({ rate: 'Steuersatz (%)', net: 'Netto (€)', vat: 'Umsatzsteuer (€)' }).map(([key, label]) => <label key={key}>{label} · Zeile {index + 1}
            <input required value={line[key]} onChange={event => setVatLines(previous => previous.map((row, position) => position === index ? { ...row, [key]: event.target.value } : row))} /></label>)}
          <button type="button" onClick={() => setVatLines(previous => previous.filter((_, position) => position !== index))}>Steuerzeile entfernen</button></div>)}
          <button type="button" onClick={() => setVatLines(previous => [...previous, { rate: '', net: '', vat: '' }])}>Steuerzeile ergänzen</button></fieldset>}
        <label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />Ich habe die Angaben mit dem Original verglichen.</label>
        {error && <p role="alert">{error}</p>}
        <button className="btn btn-primary" disabled={disabled || !confirmed}>Als Rechnungsentwurf übernehmen</button>
      </form>}
  </section>;
}
