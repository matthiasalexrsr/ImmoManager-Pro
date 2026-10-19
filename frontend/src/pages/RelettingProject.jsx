import { Fragment, useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api';
import FormModal from '../components/FormModal';
import RelatedPageLinks from '../components/RelatedPageLinks';
import { useCanWrite } from '../contexts/AuthContext';
import { formatDate, formatMoney, formatNumber } from '../utils/format';
import { OFFER_FIELDS, PROJECT_STATUS, offerPayload } from '../features/reletting/relettingModel';
import { ApplicantsTab, ClosingTab, ComparisonTab, ExposeTab, ViewingsTab } from '../features/reletting/ProjectTabs';
import '../features/reletting/reletting.css';
import './propertyDossier.css';

const TABS = [['overview', 'Übersicht'], ['expose', 'Exposé & Portale'], ['applicants', 'Interessenten'],
  ['viewings', 'Besichtigungen'], ['compare', 'Vergleich'], ['closing', 'Abschluss & Datenschutz']];

export default function RelettingProject() {
  const { id } = useParams();
  return <ProjectFile key={id} id={id} />;
}

function ProjectFile({ id }) {
  const path = `/reletting/${encodeURIComponent(id)}`;
  const mayWrite = useCanWrite('/reletting');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [tab, setTab] = useState('overview');
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    api.get(path, { signal: controller.signal }).then(setData)
      .catch(failure => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, [path, revision]);

  // Every change answers with the whole project, so the page shows exactly what was saved.
  const apply = useCallback(result => { if (result?.project) setData(result); return result; }, []);
  const reload = () => setRevision(value => value + 1);

  if (error) return <div className="page"><div role="alert" className="alert alert-error">{error}</div>
    <div className="dossier-navigation">
      <button type="button" className="btn btn-secondary" onClick={reload}>Erneut laden</button>
      <Link className="btn btn-secondary" to="/reletting">Zur Neuvermietung</Link></div></div>;
  if (!data) return <div className="page-loading" role="status">Projekt wird geladen …</div>;

  const { project, unit, property } = data;
  const canWrite = mayWrite && project.status === 'open';
  const status = PROJECT_STATUS[project.status] || PROJECT_STATUS.open;
  const active = data.applicants.filter(row => !['rejected', 'withdrawn'].includes(row.status));
  const planned = data.viewings.filter(row => row.status === 'scheduled').length;
  const attended = data.viewings.filter(row => row.status === 'completed').length;
  const done = data.steps.filter(step => step.done).length;
  const label = key => {
    if (key === 'applicants') return `Interessenten (${active.length})`;
    if (key === 'viewings') return `Besichtigungen (${data.viewings.length})`;
    return TABS.find(([value]) => value === key)[1];
  };

  return (
    <div className="page property-dossier reletting-project">
      <div className="detail-header">
        <Link className="btn btn-sm btn-secondary" to="/reletting">← Neuvermietung</Link>
        <div className="detail-title">
          <h1>{project.headline || unit.label}</h1>
          <span className="text-muted"><Link to={property.href}>{property.name}</Link> · <Link to={unit.href}>{unit.label}</Link>
            {property.address ? ` · ${property.address}` : ''}</span>
        </div>
        <span className={`badge ${status.badge}`}>{status.label}</span>
      </div>

      <RelatedPageLinks items={[
        { to: unit.href, label: 'Einheit' }, { to: property.href, label: 'Objekt' }, { to: '/viewings', label: 'Besichtigungskalender' },
        ...(data.listing ? [{ to: `/listings?focus_id=${encodeURIComponent(data.listing.id)}`, label: 'Inserat' }] : []),
        ...(data.tenant ? [{ to: data.tenant.href, label: 'Mieterkonto' }] : []),
        ...(project.contract_id ? [{ to: `/contracts?contract_id=${encodeURIComponent(project.contract_id)}`, label: 'Mietvertrag' }] : []),
      ]} />

      <div className="stats-grid">
        <div className="stat-card"><div className="stat-label">Warmmiete</div>
          <div className="stat-value reletting-kpi">{data.warm_rent == null ? '—' : formatMoney(data.warm_rent)}</div>
          {project.target_rent != null && <div className="text-muted reletting-small">Kaltmiete {formatMoney(project.target_rent)}</div>}</div>
        <div className="stat-card"><div className="stat-label">Bezugsfrei ab</div>
          <div className="stat-value reletting-kpi">{formatDate(project.available_from)}</div></div>
        <div className="stat-card"><div className="stat-label">Offene Bewerbungen</div>
          <div className="stat-value reletting-kpi">{active.length}</div>
          {project.deleted_applicants > 0 && <div className="text-muted reletting-small">{project.deleted_applicants} gelöscht</div>}</div>
        <div className="stat-card"><div className="stat-label">Besichtigungen</div>
          <div className="stat-value reletting-kpi">{attended} / {planned + attended}</div>
          <div className="text-muted reletting-small">wahrgenommen / insgesamt geplant</div></div>
      </div>

      <div className="detail-tabs" role="tablist" aria-label="Neuvermietung">
        {TABS.map(([key]) => (
          <button key={key} type="button" role="tab" id={`reletting-tab-${key}`} aria-selected={tab === key}
            aria-controls={`reletting-panel-${key}`} className={`detail-tab ${tab === key ? 'active' : ''}`} onClick={() => setTab(key)}>
            {label(key)}
          </button>
        ))}
      </div>

      <div className="detail-tab-content" role="tabpanel" id={`reletting-panel-${tab}`} aria-labelledby={`reletting-tab-${tab}`}>
        {tab === 'overview' && <Overview data={data} done={done} canWrite={canWrite} onEdit={() => setEditing(true)} onGo={setTab} />}
        {tab === 'expose' && <ExposeTab data={data} path={path} canWrite={canWrite} onChanged={apply} onEdit={() => setEditing(true)} />}
        {tab === 'applicants' && <ApplicantsTab data={data} path={path} canWrite={canWrite} onChanged={apply} />}
        {tab === 'viewings' && <ViewingsTab data={data} path={path} canWrite={canWrite} onChanged={apply} />}
        {tab === 'compare' && <ComparisonTab data={data} path={path} canWrite={canWrite} onChanged={apply} onGo={setTab} />}
        {tab === 'closing' && <ClosingTab data={data} path={path} canWrite={canWrite} mayWrite={mayWrite} onChanged={apply} onGo={setTab} />}
      </div>

      {editing && <FormModal title="Angebot bearbeiten" fields={OFFER_FIELDS} initial={project} autosave={false}
        onSave={async values => { apply(await api.put(path, offerPayload(values, project))); }}
        onClose={() => setEditing(false)} />}
    </div>
  );
}

// The steps of the project, each with what is still missing, and the offer at a glance.
function Overview({ data, done, canWrite, onEdit, onGo }) {
  const { project, unit } = data;
  const depositRatio = project.deposit_amount != null && project.target_rent ? project.deposit_amount / project.target_rent : null;
  const target = { offer: 'overview', expose: 'expose', applicants: 'applicants', viewings: 'viewings', choice: 'compare',
    contract: 'closing', privacy: 'closing' };
  const facts = [
    ['Kaltmiete', project.target_rent != null && formatMoney(project.target_rent)],
    ['Nebenkosten', project.service_charge != null && formatMoney(project.service_charge)],
    ['Heizkosten', project.heating_charge != null && formatMoney(project.heating_charge)],
    ['Kaution', project.deposit_amount != null && <>{formatMoney(project.deposit_amount)}{depositRatio != null
      && <span className={depositRatio > 3 ? 'reletting-warning' : 'text-muted'}> · {formatNumber(depositRatio, 1)} Kaltmieten
        {depositRatio > 3 ? ' – mehr als drei (§ 551 BGB)' : ''}</span>}</>],
    ['Wohnfläche', unit.area_sqm && `${String(unit.area_sqm).replace('.', ',')} m²`],
    ['Zimmer', unit.rooms && String(unit.rooms).replace('.', ',')],
    ['Etage', unit.floor],
    ['Einkommensvorgabe', `mindestens ${String(project.income_factor).replace('.', ',')}-fache Warmmiete`],
    ['Personen höchstens', project.max_persons],
  ].filter(([, value]) => value);
  return (
    <div className="detail-overview-grid">
      <section className="panel" aria-labelledby="reletting-steps">
        <div className="panel-header" id="reletting-steps">Ablauf · {done} von {data.steps.length} erledigt</div>
        <div className="panel-body">
          <ol className="reletting-steps">
            {data.steps.map(step => (
              <li key={step.key} className={step.done ? 'is-done' : ''}>
                <span className="reletting-step-mark" aria-hidden="true">{step.done ? '✓' : ''}</span>
                <div><button type="button" className="link-button" onClick={() => onGo(target[step.key])}>{step.label}</button>
                  <span className="sr-only">{step.done ? ' – erledigt' : ' – offen'}</span>
                  <div className="text-muted reletting-small">{step.detail}</div></div>
              </li>
            ))}
          </ol>
        </div>
      </section>
      <section className="panel" aria-labelledby="reletting-offer">
        <div className="panel-header reletting-panel-header" id="reletting-offer"><span>Angebot</span>
          {canWrite && <button type="button" className="btn btn-sm btn-secondary" onClick={onEdit}>Angebot bearbeiten</button>}</div>
        <div className="panel-body">
          <dl className="overview-dl">
            {facts.map(([labelText, value]) => <Fragment key={labelText}><dt>{labelText}</dt><dd>{value}</dd></Fragment>)}
          </dl>
          {project.notes && <p className="reletting-notes">{project.notes}</p>}
        </div>
      </section>
    </div>
  );
}
