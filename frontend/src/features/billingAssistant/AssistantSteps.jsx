import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Check, Plus, Trash2 } from 'lucide-react';
import { formatDate, formatMoney, formatNumber } from '../../utils/format';
import StatusBadge from '../../components/StatusBadge';
import MeterDocumentImport from '../meterDocuments/MeterDocumentImport';
import { KEY_TYPE_LABELS, METER_LABELS, keyFor, segmentText } from './billingAssistantApi';

function Facts({ view }) {
  const { property, deadline } = view;
  const meters = Object.entries(property.meters || {}).map(([type, count]) => `${count} ${METER_LABELS[type] || type}`).join(', ');
  return <dl className="assistant-facts">
    <div><dt>Einheiten</dt><dd>{property.units}{property.residential !== property.units
      ? ` (${[property.residential && `${property.residential} Wohnungen`, property.commercial && `${property.commercial} Gewerbe`,
        property.parking && `${property.parking} Stellplätze/Nebenräume`].filter(Boolean).join(', ')})` : ''}</dd></div>
    <div><dt>Fläche</dt><dd>{formatNumber(property.area_sqm)}{'\u00a0'}m²</dd></div>
    <div><dt>Zähler</dt><dd>{meters || 'keine erfasst'}</dd></div>
    <div><dt>Frist für die Abrechnung</dt><dd>{formatDate(deadline.date)}{deadline.days_left >= 0 ? ` (noch ${deadline.days_left} Tage)` : ' (abgelaufen)'}</dd></div>
  </dl>;
}

export function PeriodStep({ view, canWrite, onCreate, onChoose, busy }) {
  const [form, setForm] = useState(view.suggested_period);
  const drafts = view.periods.filter(period => period.status === 'draft');
  return <div className="assistant-step">
    <Facts view={view} />
    {view.periods.length > 0 && <section>
      <h3>Vorhandene Abrechnungen</h3>
      <ul className="assistant-choices">{view.periods.map(period => <li key={period.id}>
        <button type="button" className={`assistant-choice${view.period?.id === period.id ? ' is-active' : ''}`} onClick={() => onChoose(period.id)}>
          <strong>{period.label}</strong><span>{formatDate(period.start_date)} – {formatDate(period.end_date)}</span>
          <StatusBadge status={period.status} /></button></li>)}</ul>
      {drafts.length > 0 && !view.period && <p className="text-muted">Einen Entwurf auswählen, um dort weiterzumachen, oder unten eine neue Abrechnung anlegen.</p>}
    </section>}
    {canWrite && <section>
      <h3>Neue Abrechnung</h3>
      <p className="text-muted">Vorschlag: die zwölf Monate nach der letzten Abrechnung. Der Zeitraum darf höchstens zwölf Monate lang sein.</p>
      <div className="assistant-form-row">
        <label>Bezeichnung<input value={form.label} onChange={event => setForm({ ...form, label: event.target.value })} /></label>
        <label>Beginn<input type="date" value={form.start_date} onChange={event => setForm({ ...form, start_date: event.target.value })} /></label>
        <label>Ende<input type="date" value={form.end_date} onChange={event => setForm({ ...form, end_date: event.target.value })} /></label>
        <button type="button" className="btn btn-primary" disabled={busy || !form.label || !form.start_date || !form.end_date}
          onClick={() => onCreate(form)}>Abrechnung anlegen</button>
      </div>
    </section>}
  </div>;
}

export function OccupancyStep({ view }) {
  return <div className="assistant-step">
    <p className="text-muted">Jede Einheit nimmt am ganzen Zeitraum teil. Mieterwechsel werden tagesgenau geteilt, Leerstand trägt der Vermieter.</p>
    <div className="table-scroll"><table className="data-table assistant-table">
      <thead><tr><th>Einheit</th><th className="text-right">Fläche</th><th>Nutzung im Zeitraum</th><th className="text-right">Vorauszahlungen</th></tr></thead>
      <tbody>{view.occupancy.units.map(unit => <tr key={unit.unit_id}>
        <td><Link className="entity-link" to={`/units/${encodeURIComponent(unit.unit_id)}`}>{unit.label}</Link></td>
        <td className="text-right">{unit.area_sqm ? `${formatNumber(unit.area_sqm)}\u00a0m²` : <span className="text-muted">—</span>}</td>
        <td><ul className="assistant-segments">{unit.segments.map((segment, index) =>
          <li key={index} className={segment.kind === 'vacancy' ? 'is-vacancy' : ''}>{segmentText(segment)}</li>)}</ul></td>
        <td className="text-right">{unit.segments.filter(segment => segment.kind === 'tenancy').map((segment, index) =>
          <div key={index}>{segment.advances == null ? '—' : formatMoney(segment.advances)}</div>)}</td>
      </tr>)}</tbody>
    </table></div>
  </div>;
}

export function KeysStep({ view, canWrite, onCreateKey, busy }) {
  return <div className="assistant-step">
    <section>
      <h3>Verteilerschlüssel dieser Immobilie</h3>
      {view.keys.present.length ? <div className="table-scroll"><table className="data-table assistant-table">
        <thead><tr><th>Name</th><th>Verteilt nach</th><th>In dieser Abrechnung</th></tr></thead>
        <tbody>{view.keys.present.map(key => <tr key={key.id}><td>{key.name}</td>
          <td>{key.key_label}{key.meter_type ? ` · ${METER_LABELS[key.meter_type] || key.meter_type}${key.measure_unit ? ` (${key.measure_unit})` : ''}` : ''}</td>
          <td>{key.used ? <span className="assistant-done"><Check size={14} aria-hidden="true" /> benutzt</span> : '—'}</td></tr>)}</tbody>
      </table></div> : <p className="text-muted">Noch keine Verteilerschlüssel.</p>}
    </section>
    {view.keys.suggested.length > 0 && <section>
      <h3>Für diese Immobilie empfohlen</h3>
      <ul className="assistant-cards">{view.keys.suggested.map(key => <li key={`${key.key_type}:${key.meter_type || ''}`} className="assistant-card">
        <div><strong>{key.name}</strong><span className="text-muted"> · nach {KEY_TYPE_LABELS[key.key_type]}</span><p>{key.reason}</p></div>
        {canWrite && <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={() => onCreateKey(key)}>
          <Plus size={14} aria-hidden="true" /> Anlegen</button>}
      </li>)}</ul>
    </section>}
  </div>;
}

function CostForm({ view, prefill, onAdd, busy }) {
  const catalogue = view.costs.catalogue;
  const blank = { category: '', description: '', amount: '', allocation_key_id: keyFor('area_sqm', view.keys.present), is_recoverable: true, consumption_share: '' };
  const [form, setForm] = useState(() => ({ ...blank, ...prefill }));
  const keyOf = id => view.keys.present.find(key => key.id === id);
  const consumption = keyOf(form.allocation_key_id)?.key_type === 'consumption';
  const choose = category => {
    const entry = catalogue.find(item => item.category === category);
    const allocation = keyFor(entry?.key, view.keys.present);
    setForm(current => ({ ...current, category, description: entry?.label || current.description, allocation_key_id: allocation,
      consumption_share: keyOf(allocation)?.key_type === 'consumption' && ['heating', 'hot_water'].includes(category) ? 70 : '' }));
  };
  const ready = form.description.trim() && Number(form.amount) > 0 && form.allocation_key_id
    && (!form.consumption_share || (Number(form.consumption_share) >= 50 && Number(form.consumption_share) <= 70));
  return <div className="assistant-form-row assistant-cost-form">
    <label>Kostenart (§ 2 BetrKV)<select value={form.category} onChange={event => choose(event.target.value)}>
      <option value="">Bitte wählen</option>{catalogue.map(item => <option key={item.category} value={item.category}>{item.label}</option>)}</select></label>
    <label className="assistant-wide">Bezeichnung<input value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} /></label>
    <label>Betrag (€)<input type="number" step="0.01" min="0" value={form.amount} onChange={event => setForm({ ...form, amount: event.target.value })} /></label>
    <label>Verteilerschlüssel<select value={form.allocation_key_id} onChange={event => setForm({ ...form, allocation_key_id: event.target.value,
      consumption_share: keyOf(event.target.value)?.key_type === 'consumption' && ['heating', 'hot_water'].includes(form.category) ? (form.consumption_share || 70) : '' })}>
      <option value="">Bitte wählen</option>{view.keys.present.map(key => <option key={key.id} value={key.id}>{key.name}</option>)}</select></label>
    {consumption && ['heating', 'hot_water'].includes(form.category) && <label>Nach Verbrauch (%)<input type="number" min="50" max="70"
      value={form.consumption_share} onChange={event => setForm({ ...form, consumption_share: event.target.value })} /></label>}
    <label className="assistant-check"><input type="checkbox" checked={form.is_recoverable} onChange={event => setForm({ ...form, is_recoverable: event.target.checked })} />Umlagefähig</label>
    <button type="button" className="btn btn-primary" disabled={busy || !ready} onClick={async () => {
      if (await onAdd(form)) setForm({ ...blank, allocation_key_id: form.allocation_key_id });
    }}><Plus size={14} aria-hidden="true" /> Hinzufügen</button>
  </div>;
}

export function CostsStep({ view, canWrite, onAdd, onRemove, onImported, busy }) {
  const [prefill, setPrefill] = useState(null);
  const previous = view.costs.previous.filter(row => row.missing && row.is_recoverable !== false);
  return <div className="assistant-step">
    <section>
      <h3>Kosten dieser Abrechnung</h3>
      {view.costs.items.length ? <div className="table-scroll"><table className="data-table assistant-table">
        <thead><tr><th>Bezeichnung</th><th className="text-right">Betrag</th><th>Verteilerschlüssel</th><th>Umlagefähig</th><th>Herkunft</th>
          {canWrite && <th className="th-actions"><span className="sr-only">Aktion</span></th>}</tr></thead>
        <tbody>{view.costs.items.map(row => <tr key={row.id}>
          <td>{row.description}{row.consumption_share ? <span className="td-sub">{row.consumption_share}{'\u00a0'}% nach Verbrauch</span> : null}</td>
          <td className="text-right">{formatMoney(row.amount)}</td><td>{row.key_name || '—'}</td><td>{row.is_recoverable === false ? 'nein' : 'ja'}</td>
          <td>{row.source_document_id ? <Link to={`/documents/${encodeURIComponent(row.source_document_id)}`}>Dokument</Link>
            : row.service_contract_invoice_id ? 'Objektvertrag' : 'erfasst'}</td>
          {canWrite && <td className="action-cell"><button type="button" className="btn btn-ghost btn-sm" aria-label={`${row.description} entfernen`}
            disabled={busy} onClick={() => onRemove(row)}><Trash2 size={15} aria-hidden="true" /></button></td>}
        </tr>)}</tbody>
        <tfoot><tr className="table-totals"><td>Umlagefähig zusammen</td><td className="text-right">{formatMoney(view.costs.total)}</td><td colSpan={canWrite ? 4 : 3} /></tr></tfoot>
      </table></div> : <p className="text-muted">Noch keine Kosten erfasst.</p>}
    </section>
    {canWrite && <section>
      <h3>Kosten hinzufügen</h3>
      <CostForm key={prefill ? JSON.stringify(prefill) : 'new'} view={view} prefill={prefill || undefined} busy={busy}
        onAdd={async form => { const ok = await onAdd(form); if (ok) setPrefill(null); return ok; }} />
      <p className="text-muted assistant-note">Nicht umlagefähig sind Verwaltung, Instandhaltung und Reparaturen sowie Rücklagen (§ 1 Abs. 2 BetrKV);
        sie lassen sich als „nicht umlagefähig“ festhalten, damit die Abrechnung vollständig ist.</p>
    </section>}
    {previous.length > 0 && <section>
      <h3>Aus dem Vorjahr ({view.costs.previous_period?.label})</h3>
      <ul className="assistant-cards">{previous.map(row => <li key={row.description} className="assistant-card">
        <div><strong>{row.description}</strong><span className="text-muted"> · Vorjahr {formatMoney(row.amount)} · {row.key_name || '—'}</span></div>
        {canWrite && <button type="button" className="btn btn-sm btn-secondary" onClick={() => setPrefill({ category: row.category || '',
          description: row.description, amount: '', allocation_key_id: row.allocation_key_id, is_recoverable: row.is_recoverable !== false,
          consumption_share: row.consumption_share || '' })}>Übernehmen und Betrag eintragen</button>}
      </li>)}</ul>
    </section>}
    {view.costs.service_contracts.length > 0 && <section>
      <h3>Objektverträge</h3>
      <ul className="assistant-list">{view.costs.service_contracts.map(contract => <li key={contract.id}>
        <Link to={`/service-contracts/${encodeURIComponent(contract.id)}`}>{contract.title}</Link>: {contract.bills} Rechnung(en) im Zeitraum
        {contract.open ? `, ${contract.open} noch nicht übernommen` : ', alle übernommen'}</li>)}</ul>
    </section>}
    {canWrite && view.period && <section>
      <h3>Abrechnung des Messdienstes einlesen</h3>
      <MeterDocumentImport key={view.period.id} propertyId={view.property.id} periodId={view.period.id} onApplied={onImported} />
    </section>}
  </div>;
}

export function ReadingsStep({ view, canWrite, onSave, onImported, busy }) {
  const [values, setValues] = useState({});
  const needed = view.readings.needed;
  return <div className="assistant-step">
    {needed.length ? <div className="table-scroll"><table className="data-table assistant-table">
      <thead><tr><th>Einheit</th><th>Zähler</th><th>Ablesetag</th><th>Anlass</th><th className="text-right">Stand</th></tr></thead>
      <tbody>{needed.map(row => {
        const id = `${row.meter_id}:${row.day}`;
        return <tr key={id} className={row.present ? '' : 'assistant-missing'}>
          <td>{row.unit_label}</td><td>{row.meter_label} · {row.serial_number || '—'}</td><td>{formatDate(row.day)}</td><td>{row.reason}</td>
          <td className="text-right">{row.present ? <span className="assistant-done"><Check size={14} aria-hidden="true" /> {formatNumber(row.value)}
            {row.reading_date !== row.day ? <span className="td-sub">am {formatDate(row.reading_date)}</span> : null}</span>
            : canWrite ? <span className="assistant-inline">
              <input type="number" step="any" min="0" aria-label={`Stand ${row.unit_label} am ${formatDate(row.day)}`} value={values[id] ?? ''}
                onChange={event => setValues({ ...values, [id]: event.target.value })} />
              <button type="button" className="btn btn-sm btn-primary" disabled={busy || values[id] === undefined || values[id] === ''}
                onClick={async () => { if (await onSave(row, Number(values[id]))) setValues(current => { const next = { ...current }; delete next[id]; return next; }); }}>
                Speichern</button></span> : 'fehlt'}</td>
        </tr>;
      })}</tbody>
    </table></div> : <p className="text-muted">Für diese Abrechnung werden keine Zählerstände gebraucht: Kein Verteilerschlüssel verteilt nach Verbrauch.</p>}
    {canWrite && view.period && <section>
      <h3>Ableseprotokoll des Messdienstes einlesen</h3>
      <MeterDocumentImport key={view.period.id} propertyId={view.property.id} periodId={view.period.id} onApplied={onImported} />
    </section>}
  </div>;
}

export function CheckStep({ view }) {
  const checks = view.checks;
  if (!checks) return <p className="text-muted">Erst eine Abrechnung anlegen.</p>;
  return <div className="assistant-step">
    {checks.blockers.length === 0 && <p className="alert alert-success">Keine Fehler: Die Einzelabrechnungen lassen sich erzeugen.</p>}
    {checks.blockers.length > 0 && <section><h3>Muss vorher geklärt werden</h3><ul className="assistant-issues is-blocker">
      {checks.blockers.map((issue, index) => <li key={index}><strong>{issue.message}</strong>{issue.context && <span>{issue.context}</span>}</li>)}</ul></section>}
    {checks.warnings.length > 0 && <section><h3>Bitte ansehen</h3><ul className="assistant-issues">
      {checks.warnings.map((issue, index) => <li key={index}><strong>{issue.message}</strong>{issue.context && <span>{issue.context}</span>}</li>)}</ul></section>}
  </div>;
}

export function ResultStep({ view, canWrite, onGenerate, busy }) {
  const blocked = view.checks?.blockers?.length > 0;
  const rows = view.statements.items;
  const mutable = view.period && ['draft', 'review'].includes(view.period.status);
  return <div className="assistant-step">
    {canWrite && mutable && <div className="toolbar">
      <button type="button" className="btn btn-primary" disabled={busy || blocked} onClick={onGenerate}>
        {rows.length ? 'Einzelabrechnungen neu erzeugen' : 'Einzelabrechnungen erzeugen'}</button>
      {blocked && <span className="text-muted">Erst die Punkte unter „Prüfen“ klären.</span>}
      {view.statements.outdated && <span className="text-muted">Die Daten haben sich geändert; bitte neu erzeugen.</span>}
    </div>}
    {rows.length > 0 && <div className="table-scroll"><table className="data-table assistant-table">
      <thead><tr><th>Einheit</th><th>Partei</th><th>Zeitraum</th><th className="text-right">Kosten</th><th className="text-right">Vorauszahlungen</th>
        <th className="text-right">Ergebnis</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.id}>
        <td>{row.unit_label}</td><td>{row.party === 'vacancy' ? <span className="text-muted">Leerstand (Vermieter)</span> : row.tenant || '—'}</td>
        <td><span className="cell-stack"><span>{formatDate(row.usage_start)} – {formatDate(row.usage_end)}</span>
          <span className="td-sub">{row.usage_days} Tage</span></span></td>
        <td className="text-right">{formatMoney(row.total_cost)}</td><td className="text-right">{formatMoney(row.advance_paid)}</td>
        <td className="text-right">{row.party === 'vacancy' ? '—' : <span className="cell-stack">
          <span className={row.balance > 0 ? 'text-red' : row.balance < 0 ? 'text-green' : ''}>{formatMoney(Math.abs(row.balance))}</span>
          <span className="td-sub">{row.balance > 0 ? 'Nachzahlung' : row.balance < 0 ? 'Guthaben' : 'ausgeglichen'}</span></span>}</td>
      </tr>)}</tbody>
      <tfoot><tr className="table-totals"><td colSpan={3}>Summe</td><td className="text-right">{formatMoney(view.statements.total_cost)}</td>
        <td className="text-right">{formatMoney(view.statements.advances)}</td>
        <td className="text-right"><span className="cell-stack"><span>{formatMoney(Math.abs(view.statements.balance))}</span>
          <span className="td-sub">{view.statements.balance >= 0 ? 'Nachzahlungen zusammen' : 'Guthaben zusammen'}</span></span></td></tr></tfoot>
    </table></div>}
    {rows.length > 0 && <p><Link className="btn btn-secondary" to={`/statements?period_id=${encodeURIComponent(view.period.id)}`}>
      Weiter zu Schreiben, Prüfung und Versand</Link></p>}
  </div>;
}
