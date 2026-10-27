import { Fragment, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { codeLabel } from '../../utils/codeLabels';
import { formatDate, getFormatLocale } from '../../utils/format';
import './meterHistory.css';

// The unit a meter of this kind counts in when none is set.
const USUAL_UNIT = { cold_water: 'm³', hot_water: 'm³', gas: 'm³', electricity: 'kWh', heating: 'kWh' };
// up to three decimals as read, without trailing zeros (1.500,2 rather than 1.500,200)
const number = (value, digits = 3) => {
  if (value == null || value === '' || !Number.isFinite(Number(value))) return '—';
  return new Intl.NumberFormat(getFormatLocale(), { maximumFractionDigits: digits }).format(Number(value));
};

/** One meter over time: its readings, the consumption between them and per year, and who supplies it. */
export default function MeterHistory({ meterId, meterLabel, unitLabel, propertyName, propertyId, revision = 0, covered = false,
  onClose, onRecord, onEdit, canWrite = true }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const closeRef = useRef(null);
  const dialogRef = useRef(null);
  const pressStartedOnOverlay = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    setError(null); setData(null);
    api.get(`/meters/${encodeURIComponent(meterId)}/history`, { signal: controller.signal })
      .then(result => {
        if (controller.signal.aborted) return;
        if (result?.meter?.id !== meterId || !['readings', 'years', 'contracts'].every(key => Array.isArray(result[key]))) {
          throw new Error('Der Zählerverlauf wurde nicht vollständig geladen. Bitte erneut versuchen.');
        }
        setData(result);
      })
      .catch(failure => { if (!controller.signal.aborted) setError(failure.message || 'Verlauf konnte nicht geladen werden.'); });
    return () => controller.abort();
  }, [meterId, revision, attempt]);

  useEffect(() => {
    const previous = document.activeElement;
    const dialog = dialogRef.current;
    return () => {
      if (previous?.isConnected && (document.activeElement === document.body || dialog?.contains(document.activeElement))) previous.focus();
    };
  }, []);
  useEffect(() => { if (!covered) closeRef.current?.focus(); }, [covered]);
  useEffect(() => {
    // a form opened from here takes Escape for itself
    const keydown = event => {
      if (covered || event.defaultPrevented) return;
      if (event.key === 'Escape') { event.preventDefault(); onClose(); }
      if (event.key !== 'Tab') return;
      const targets = [...(dialogRef.current?.querySelectorAll('button:not(:disabled), a[href], [tabindex="0"]') || [])];
      const first = targets[0]; const last = targets.at(-1);
      if (!first) return;
      if (!dialogRef.current.contains(document.activeElement) || (event.shiftKey && document.activeElement === first)) {
        event.preventDefault(); (event.shiftKey ? last : first).focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener('keydown', keydown);
    return () => document.removeEventListener('keydown', keydown);
  }, [onClose, covered]);

  const meter = data?.meter?.id === meterId ? data.meter : null;
  const unit = meter?.measure_unit || USUAL_UNIT[meter?.meter_type] || '';
  const readings = [...(data?.readings || [])].reverse();          // newest first
  return (
    <div className="modal-overlay" role="presentation"
      onMouseDown={event => { pressStartedOnOverlay.current = event.target === event.currentTarget; }}
      onClick={event => {
        if (!covered && pressStartedOnOverlay.current && event.target === event.currentTarget) onClose();
        pressStartedOnOverlay.current = false;
      }}>
      <div ref={dialogRef} className="modal modal-wide meter-history" role="dialog" aria-modal={!covered || undefined} aria-labelledby="meter-history-title"
        aria-hidden={covered || undefined} inert={covered}>
        <div className="modal-header">
          <div>
            <p className="meter-history-eyebrow">Zählerverlauf · {codeLabel(meter?.meter_type) || ''}</p>
            <h3 id="meter-history-title">{meterLabel}</h3>
            <p className="meter-history-place">
              {propertyId ? <Link to={`/properties/${encodeURIComponent(propertyId)}`}>{propertyName}</Link> : propertyName}
              {unitLabel && <> · {meter?.unit_id ? <Link to={`/units/${encodeURIComponent(meter.unit_id)}`}>{unitLabel}</Link> : unitLabel}</>}
            </p>
          </div>
          <button ref={closeRef} type="button" className="btn-close" onClick={onClose} disabled={covered} aria-label="Schließen">×</button>
        </div>
        <div className="modal-body">
          {error && <div className="alert alert-error" role="alert">{error}
            <button type="button" className="btn btn-sm btn-secondary" disabled={covered} onClick={() => setAttempt(value => value + 1)}>Erneut laden</button>
          </div>}
          {!data && !error && <p role="status">Verlauf wird geladen …</p>}
          {meter && <>
            <div className="meter-history-actions">
              {canWrite && <button type="button" className="btn btn-sm btn-primary" disabled={covered} onClick={onRecord}>+ Ablesung erfassen</button>}
              {canWrite && <button type="button" className="btn btn-sm btn-secondary" disabled={covered} onClick={onEdit}>Zähler bearbeiten</button>}
            </div>
            <section className="meter-history-section" aria-labelledby="meter-history-facts">
              <h4 id="meter-history-facts">Zähler</h4>
              <dl className="overview-dl">
                {[['Einheit der Ablesung', unit], ['Standort', meter.location], ['Eingebaut', meter.installation_date && formatDate(meter.installation_date)],
                  ['Ausgebaut', meter.removal_date && formatDate(meter.removal_date)],
                  ['Nächste Prüfung', meter.next_inspection && formatDate(meter.next_inspection)],
                  ['Status', meter.is_active === false ? 'Inaktiv' : 'Aktiv']].filter(([, value]) => value)
                  .map(([label, value]) => <Fragment key={label}><dt>{label}</dt><dd>{value}</dd></Fragment>)}
              </dl>
            </section>
            <SupplySection meter={meter} contracts={data.contracts} />
            <YearSection years={data.years} unit={unit} />
            <section className="meter-history-section" aria-labelledby="meter-history-readings">
              <h4 id="meter-history-readings">Ablesungen ({readings.length})</h4>
              {readings.length === 0 ? <p className="text-muted">Noch keine Ablesung erfasst.</p> : (
                <div className="table-scroll"><table className="data-table" aria-labelledby="meter-history-readings">
                  <thead><tr><th>Datum</th><th className="text-right">Stand ({unit})</th><th className="text-right">Verbrauch</th>
                    <th className="text-right">Tage</th><th className="text-right">je Tag</th><th>Erfasst / Notiz</th></tr></thead>
                  <tbody>{readings.map(row => (
                    <tr key={row.id}>
                      <td>{formatDate(row.reading_date)}</td>
                      <td className="text-right td-num">{number(row.value)}</td>
                      <td className="text-right td-num">{row.consumption == null ? '—' : number(row.consumption)}</td>
                      <td className="text-right td-num">{row.days ?? '—'}</td>
                      <td className="text-right td-num">{row.per_day == null ? '—' : number(row.per_day)}</td>
                      <td className="td-wrap">{[row.recorded_by, row.notes].filter(Boolean).join(' · ') || '—'}
                        {row.warning && <div className="meter-history-warning" role="note">⚠ {row.warning}</div>}</td>
                    </tr>))}
                  </tbody>
                </table></div>)}
            </section>
          </>}
        </div>
      </div>
    </div>
  );
}

// Who supplies the meter: the landlord's own contract on the meter and the service contracts naming it.
function SupplySection({ meter, contracts }) {
  const own = meter.supplier || meter.contract_number || meter.contract_end_date || meter.portal_url;
  if (!own && !contracts.length) return null;
  return <section className="meter-history-section" aria-labelledby="meter-history-supply">
    <h4 id="meter-history-supply">Versorgung</h4>
    {own && <div className="meter-history-contract">
      <dl className="overview-dl">
        {[['Versorger', meter.supplier], ['Vertragsnummer', meter.contract_number],
          ['Vertragslaufzeit bis', meter.contract_end_date && formatDate(meter.contract_end_date)]].filter(([, value]) => value)
          .map(([label, value]) => <Fragment key={label}><dt>{label}</dt><dd>{value}</dd></Fragment>)}
      </dl>
      {meter.portal_url && <PortalLink href={meter.portal_url} />}
    </div>}
    {contracts.map(contract => <div key={contract.id} className="meter-history-contract">
      <p><Link to={contract.href}>{contract.title}</Link>{contract.provider && <span className="text-muted"> · {contract.provider}</span>}</p>
      {(contract.contract_number || contract.customer_number) && <p className="text-muted">
        {[contract.contract_number && `Vertrag ${contract.contract_number}`, contract.customer_number && `Kunde ${contract.customer_number}`].filter(Boolean).join(' · ')}</p>}
      {contract.portal_url && <PortalLink href={contract.portal_url} />}
    </div>)}
  </section>;
}

function PortalLink({ href }) {
  return <a className="btn btn-sm btn-secondary meter-history-portal" href={href} target="_blank" rel="noopener noreferrer">
    Kundenportal des Anbieters öffnen ↗</a>;
}

// Consumption per calendar year: columns (a single series, so no legend) and the same figures as a table.
function YearSection({ years, unit }) {
  const [active, setActive] = useState(null);
  if (!years.length) return null;
  const top = Math.max(...years.map(year => year.consumption), 0) || 1;
  const height = 140; const step = 56; const width = Math.max(years.length * step, 240); const bar = 24;
  const shown = years[active] ?? null;
  return <section className="meter-history-section" aria-labelledby="meter-history-years">
    <h4 id="meter-history-years">Verbrauch je Kalenderjahr ({unit})</h4>
    <div className="meter-history-chart">
      <svg viewBox={`0 0 ${width} ${height + 24}`} role="img" aria-label="Verbrauch je Kalenderjahr als Säulen; Zahlen in der Tabelle darunter"
        onMouseLeave={() => setActive(null)}>
        <defs>
          <pattern id="meter-history-partial" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" className="meter-history-hatch-ground" /><rect width="2" height="6" className="meter-history-hatch-line" />
          </pattern>
        </defs>
        <line x1="0" x2={width} y1={height} y2={height} className="meter-history-axis" />
        {years.map((year, index) => {
          const h = Math.max(2, (year.consumption / top) * (height - 18));
          const x = index * step + (step - bar) / 2; const y = height - h; const r = Math.min(4, h);
          return <g key={year.year} tabIndex={0} onMouseEnter={() => setActive(index)} onFocus={() => setActive(index)} onBlur={() => setActive(null)}
            aria-label={`${year.year}: ${number(year.consumption)} ${unit}${year.complete ? '' : ' (nur teilweise abgelesen)'}`}>
            <rect x={index * step} y="0" width={step} height={height} fill="transparent" />
            <path d={`M${x},${height} V${y + r} Q${x},${y} ${x + r},${y} H${x + bar - r} Q${x + bar},${y} ${x + bar},${y + r} V${height} Z`}
              className={year.complete ? 'meter-history-bar' : 'meter-history-bar meter-history-bar-partial'} />
            <text x={index * step + step / 2} y={height + 16} textAnchor="middle" className="meter-history-tick">{year.year}</text>
            {index === years.length - 1 && <text x={x + bar / 2} y={y - 6} textAnchor="middle" className="meter-history-cap">{number(year.consumption, 0)}</text>}
          </g>;
        })}
      </svg>
      {shown && <div className="meter-history-tooltip" role="status">{shown.year}: <strong>{number(shown.consumption)} {unit}</strong>
        {!shown.complete && <> · {shown.covered_days} Tage abgelesen</>}</div>}
    </div>
    {years.some(year => !year.complete) && <p className="text-muted meter-history-note">Schraffiert: Jahr nur teilweise durch Ablesungen abgedeckt; der Verbrauch ist nach Tagen anteilig.</p>}
    <div className="table-scroll"><table className="data-table" aria-labelledby="meter-history-years">
      <thead><tr><th>Jahr</th><th className="text-right">Verbrauch ({unit})</th><th className="text-right">Abgelesene Tage</th></tr></thead>
      <tbody>{[...years].reverse().map(year => <tr key={year.year}><td>{year.year}</td>
        <td className="text-right td-num">{number(year.consumption)}</td>
        <td className="text-right td-num">{year.covered_days}{year.complete ? '' : ' (teilweise)'}</td></tr>)}</tbody>
    </table></div>
  </section>;
}
