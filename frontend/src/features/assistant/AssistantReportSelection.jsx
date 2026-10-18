import { Link } from 'react-router-dom';
import { formatMoney, formatNumber } from '../../utils/format';
import { reportHref } from './assistantLinks';

const kinds = { 'cash-v2': 'Zahlungsübersicht', 'performance-period-v2': 'Periodenergebnis', 'liquidity-v2': 'Liquiditätsplanung' };
const today = () => new Date().toLocaleDateString('sv-SE');
export default function AssistantReportSelection({ cards, report, onChange, disabled }) {
  const dimensions = cards.filter(card => ['property', 'unit'].includes(card.kind));
  const target = report?.unit_id ? `unit:${report.unit_id}` : report?.property_id ? `property:${report.property_id}` : '';
  const choose = value => {
    const card = dimensions.find(item => `${item.kind}:${item.id}` === value);
    if (!card) return;
    const next = { ...report }; delete next.property_id; delete next.unit_id; next[`${card.kind}_id`] = card.id; onChange(next);
  };
  return <div className="assistant-report-selection">
    <label className="assistant-web-option"><input type="checkbox" checked={Boolean(report)} disabled={disabled || dimensions.length === 0} onChange={event => {
      if (!event.target.checked) onChange(null);
      else { const first = dimensions[0]; onChange({ version: 2, kind: 'cash-v2', as_of: today(), date_from: null, date_to: null, [`${first.kind}_id`]: first.id }); }
    }} /> Lokale Auswertung mitsenden</label>
    {!dimensions.length && <p className="assistant-composer-help">Wählen Sie dafür ausdrücklich eine Immobilie oder Einheit als Aktenkontext aus.</p>}
    {report && <><div className="assistant-report-fields">
      <label>Berichtsart<select aria-label="Lokale Berichtsart" value={report.kind} disabled={disabled} onChange={event => onChange({ ...report, kind: event.target.value })}>{Object.entries(kinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label>Ausgewählte Immobilie / Einheit<select aria-label="Berichtsbezug" value={target} disabled={disabled} onChange={event => choose(event.target.value)}>{dimensions.map(card => <option key={`${card.kind}:${card.id}`} value={`${card.kind}:${card.id}`}>{card.title} · {card.detail || card.id} · {card.kind === 'unit' ? 'Einheit' : 'Immobilie'}</option>)}</select></label>
      <label>Stichtag<input aria-label="Berichtsstichtag" type="date" value={report.as_of} disabled={disabled} required onChange={event => onChange({ ...report, as_of: event.target.value })} /></label>
      {report.kind !== 'liquidity-v2' && <><label>Zeitraum von<input aria-label="Berichtszeitraum von" type="date" value={report.date_from || ''} disabled={disabled} onChange={event => onChange({ ...report, date_from: event.target.value || null })} /></label>
        <label>Zeitraum bis<input aria-label="Berichtszeitraum bis" type="date" value={report.date_to || ''} disabled={disabled} onChange={event => onChange({ ...report, date_to: event.target.value || null })} /></label></>}
    </div><p className="assistant-composer-help">{report.kind === 'performance-period-v2' ? 'Ganze Kalendermonate auswählen; ohne Zeitraum gilt das Stichtagsjahr.' : report.kind === 'liquidity-v2' ? 'Die vorhandene lokale Liquiditätsberechnung verwendet die Vorgabe der Berichtsdefinition. Weitere Annahmen lassen sich in Auswertungen prüfen.' : 'Ohne Zeitraum: passende Zahlungen bis einschließlich Stichtag.'} Es wird ausschließlich der gewählte Aktenbezug ausgewertet.</p>
      <Link to={reportHref(report)}>Diese Auswahl in lokalen Auswertungen öffnen →</Link>
    </>}
  </div>;
}

export function FinancialProof({ finance, report }) {
  if (!finance) return null;
  const labels = { income: 'Einnahmen', expense: 'Ausgaben', net: 'Saldo', rent_due: 'Sollmiete', other_income: 'Sonstige Einnahmen', costs: 'Kosten', result: 'Periodenergebnis', opening_balance: 'Anfangssaldo', closing_balance: 'Endsaldo' };
  const totals = finance.totals || { opening_balance: finance.opening_balance, closing_balance: finance.closing_balance };
  const definition = finance.definition || report || { ...finance.filters, kind: finance.basis, as_of: finance.as_of };
  return <section className="assistant-financial-proof" aria-label="Lokaler Berechnungsnachweis"><strong>{kinds[finance.basis || definition.kind] || 'Lokale Auswertung'}</strong><p>Stichtag: {definition.as_of || finance.as_of || 'Nicht übermittelt'}</p>
    <dl>{Object.entries(totals).filter(([key]) => labels[key]).map(([key, value]) => <div key={key}><dt>{labels[key]}</dt><dd>{finance.currency ? formatMoney(value, { currency: finance.currency }) : formatNumber(value, 2)}</dd></div>)}</dl>
    {!finance.currency && <p>Die Währung wurde nicht übermittelt.</p>}
    <Link to={reportHref(definition)}>Originalauswertung mit diesen Filtern öffnen →</Link><details><summary>Berechnungsnachweis</summary><p>Ergebnisstand: <code>{finance.result_hash || 'Nicht übermittelt'}</code></p></details>
  </section>;
}
