import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { useAuth } from '../contexts/AuthContext';
import StatusBadge from '../components/StatusBadge';
import PhotoDropZone from '../components/PhotoDropZone';
import useUnitWorkspace from '../features/unitWorkspace/useUnitWorkspace';
import { unitWorkspaceText } from '../features/unitWorkspace/text';
import './UnitOverview.css';

const initialPages = () => ({ active_cursor: [null], history_cursor: [null], insurance_cursor: [null] });

function UnitWorkspace({ id, principal }) {
  const { locale = 'de-DE' } = useTranslation();
  const copy = unitWorkspaceText(locale);
  const [pages, setPages] = useState(initialPages);
  const [generation, setGeneration] = useState(0);
  const cursors = Object.fromEntries(Object.entries(pages).map(([key, trail]) => [key, trail.at(-1)]));
  const result = useUnitWorkspace(id, principal, cursors, generation);
  const money = value => value == null ? '—' : new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(value);
  const day = value => value ? new Intl.DateTimeFormat(locale).format(new Date(`${value}T00:00:00`)) : '—';
  const label = (labels, value) => Object.hasOwn(labels, value) ? labels[value] : value;
  const badge = status => Object.hasOwn(copy.statuses, status)
    ? <span className={`badge ${['occupied', 'rented'].includes(status) ? 'badge-green' : status === 'expired' ? 'badge-red' : 'badge-yellow'}`}>{copy.statuses[status]}</span>
    : <StatusBadge status={status} />;
  const reset = () => { setPages(initialPages()); setGeneration(value => value + 1); };
  const pager = (name, page, heading) => <nav className="unit-workspace-pager" aria-label={heading}>
    <button type="button" className="btn btn-sm btn-secondary" disabled={pages[name].length === 1}
      onClick={() => setPages(previous => ({ ...previous, [name]: previous[name].slice(0, -1) }))}>{copy.previous}</button>
    <span>{copy.page} {pages[name].length}</span>
    <button type="button" className="btn btn-sm btn-secondary" disabled={!page.has_more}
      onClick={() => setPages(previous => ({ ...previous, [name]: [...previous[name], page.next_cursor] }))}>{copy.next}</button>
  </nav>;
  if (result.loading) return <div className="page unit-workspace" role="status">{copy.loading}</div>;
  if (result.error) {
    const denied = [401, 403, 404].includes(result.error.statusCode);
    return <div className="page unit-workspace"><div className="panel" role="alert">
      <h1>{copy.error}</h1><p>{denied ? copy.unavailable : result.error.message === 'unit_workspace_invalid' ? copy.invalid : result.error.message}</p>
      <div className="unit-workspace-actions"><button className="btn btn-primary" onClick={() => setGeneration(value => value + 1)}>{copy.retry}</button>
        {Object.values(pages).some(trail => trail.length > 1) && <button className="btn btn-secondary" onClick={reset}>{copy.restart}</button>}
        <Link to="/units" className="btn btn-secondary">{copy.back}</Link></div>
    </div></div>;
  }
  const { unit, property, active_contracts: active, contract_history: history, insurances } = result.data;
  const contract = row => <article className="unit-workspace-contract" key={row.id}>
    <div className="unit-workspace-contract-heading"><h3>{row.contract_number}</h3>{badge(row.status)}</div>
    <dl className="unit-workspace-facts">
      <div><dt>{copy.tenant}</dt><dd>{row.tenant_name || '—'}</dd></div>
      <div><dt>{copy.start}</dt><dd>{day(row.start_date)}</dd></div>
      <div><dt>{copy.end}</dt><dd>{row.end_date ? day(row.end_date) : copy.indefinite}</dd></div>
      <div><dt>{copy.deposit}</dt><dd>{money(row.deposit_amount)}</dd></div>
    </dl>
  </article>;
  return <div className="page unit-workspace">
    <header className="unit-workspace-header"><div><h1 className="page-title">{unit.label}</h1>
      <p><Link to={`/properties/${encodeURIComponent(property.id)}`}>{property.name}</Link>
        {[property.address_line, [property.postal_code, property.city].filter(Boolean).join(' ')].filter(Boolean).map(part => <span key={part}> · {part}</span>)}</p>
      <p>{copy.unitStatus}: {badge(unit.status)}</p></div>
      <div className="unit-workspace-actions"><button className="btn btn-secondary" onClick={reset}>{copy.refresh}</button><Link to="/units" className="btn btn-secondary">{copy.back}</Link></div>
    </header>
    <section className="panel unit-workspace-section" aria-labelledby="unit-workspace-facts"><h2 id="unit-workspace-facts">{copy.facts}</h2>
      <dl className="unit-workspace-facts">
        {[[copy.type, label(copy.types, unit.unit_type)], [copy.floor, unit.floor], [copy.area, unit.area_sqm == null ? null : `${unit.area_sqm} m²`],
          [copy.rooms, unit.rooms], [copy.people, unit.person_count], [copy.features, unit.features]].map(([label, value]) =>
          <div key={label}><dt>{label}</dt><dd>{value == null || value === '' ? '—' : value}</dd></div>)}
        <div><dt>{copy.rent}</dt><dd>{money(unit.cold_rent)}</dd></div>
        <div><dt>{copy.service}</dt><dd>{money(unit.service_charge_advance)}</dd></div>
        <div><dt>{copy.heating}</dt><dd>{money(unit.heating_advance)}</dd></div>
      </dl><p className="text-muted">{copy.amountBasis}</p>
    </section>
    <section className="panel unit-workspace-section" aria-labelledby="unit-workspace-active"><h2 id="unit-workspace-active">{copy.active}</h2>
      <p className="text-muted">{copy.activeBasis}</p>{(active.items.length > 1 || active.has_more || pages.active_cursor.length > 1) && <p role="status">{copy.multiple}</p>}
      {active.items.length ? active.items.map(contract) : <p>{pages.active_cursor.length > 1 ? copy.emptyPage : copy.noActive}</p>}{pager('active_cursor', active, copy.active)}
    </section>
    <section className="panel unit-workspace-section" aria-labelledby="unit-workspace-history"><h2 id="unit-workspace-history">{copy.history}</h2>
      {history.items.length ? history.items.map(contract) : <p>{pages.history_cursor.length > 1 ? copy.emptyPage : copy.emptyHistory}</p>}{pager('history_cursor', history, copy.history)}
    </section>
    <section className="panel unit-workspace-section" aria-labelledby="unit-workspace-insurances"><h2 id="unit-workspace-insurances">{copy.insurance}</h2>
      {insurances.items.length ? <ul className="unit-workspace-insurances">{insurances.items.map(row => <li key={row.id}>
        <span>{row.provider} · {label(copy.insuranceTypes, row.insurance_type)}{row.policy_number ? ` · ${row.policy_number}` : ''}</span>{badge(row.status)}
      </li>)}</ul> : <p>{pages.insurance_cursor.length > 1 ? copy.emptyPage : copy.emptyInsurance}</p>}{pager('insurance_cursor', insurances, copy.insurance)}
    </section>
    <PhotoDropZone entityType="unit" entityId={id} />
  </div>;
}

export default function UnitOverview() {
  const { id } = useParams();
  const auth = useAuth();
  const user = auth?.user;
  const principal = user ? JSON.stringify([user.id, user.role, user.portfolio_access, user.portfolio_access_origin,
    [...(user.portfolio_ids || [])].sort(), [...(user.write_permissions || [])].sort()]) : '';
  // A new identity drops private state synchronously, before effects execute.
  return <UnitWorkspace key={JSON.stringify([id, principal])} id={id} principal={principal} />;
}
