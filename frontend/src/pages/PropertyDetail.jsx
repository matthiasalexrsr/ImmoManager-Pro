import { useState, useEffect, useCallback, useRef } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, ArrowUpRight, Building2, MapPin, Home, FileText, Wrench, Wallet, RefreshCw, FileCheck2 } from 'lucide-react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import './Properties.css';

const number = value => value == null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
const sumKnown = (items, key) => items.every(item => number(item[key]) != null) ? items.reduce((sum, item) => sum + number(item[key]), 0) : null;
function PropertyStatus({ status, t }) {
  if (!status) return null;
  const key = `properties.statusLabels.${status}`;
  const label = t(key);
  return <span className="property-status" data-status={status}>{label === key ? status : label}</span>;
}

const occupied = unit => ['occupied', 'rented'].includes(unit.status);
const emptySources = { units: [], contracts: [], documents: [], maintenance: [] };

export default function PropertyDetail() {
  const { t, locale } = useTranslation();
  const { id } = useParams();
  const [property, setProperty] = useState(null);
  const [sources, setSources] = useState(emptySources);
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('overview');
  const requestRef = useRef(null);
  const load = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    const paths = [
      ['property', `/properties/${encodeURIComponent(id)}`],
      ...Object.keys(emptySources).map(key => [key, `/${key}?property_id=${encodeURIComponent(id)}`]),
    ];
    const results = await Promise.allSettled(paths.map(async ([key, path]) => {
      const data = await (key === 'property' ? api.get : api.getAll)(path, { signal: controller.signal });
      if (key === 'property' ? !data || Array.isArray(data) || typeof data !== 'object' : !Array.isArray(data)) throw new Error(t('properties.invalidData'));
      return data;
    }));
    if (controller.signal.aborted) return;
    const nextErrors = {}, nextSources = { ...emptySources };
    let nextProperty = null;
    results.forEach((result, index) => {
      const key = paths[index][0];
      if (result.status === 'rejected') nextErrors[key] = result.reason?.message || t('properties.loadFailed');
      else if (key === 'property') nextProperty = result.value;
      else nextSources[key] = result.value;
    });
    setProperty(nextProperty);
    setSources(nextSources);
    setErrors(nextErrors);
    setLoading(false);
  }, [id, t]);

  useEffect(() => {
    void load();
    return () => requestRef.current?.abort();
  }, [load]);
  useEffect(() => { setTab('overview'); }, [id]);

  const { units, contracts, documents, maintenance } = sources;
  const ready = key => !loading && !errors[key];
  const money = value => value == null ? '—' : new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 }).format(value);
  const decimal = value => value == null ? '—' : new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
  const typeLabel = (value, root) => {
    const key = `${root}.${value}`;
    return t(key) === key ? value || '—' : t(key);
  };
  const unitLabel = t('properties.units');
  const totalArea = ready('units') ? sumKnown(units, 'area_sqm') : null;
  const totalColdRent = ready('units') ? sumKnown(units, 'cold_rent') : null;
  const occupiedCount = units.filter(occupied).length;
  const vacantCount = units.filter(unit => unit.status === 'vacant').length;
  const occupancyRate = ready('units') && units.length ? Math.round(occupiedCount / units.length * 100) : null;
  const rentPerSqm = totalArea > 0 && totalColdRent != null ? totalColdRent / totalArea : null;
  const openMaintenance = ready('maintenance') ? maintenance.filter(item => ['open', 'in_progress'].includes(item.status)).length : null;
  const activeContracts = ready('contracts') ? contracts.filter(contract => contract.status === 'active').length : null;
  const tabs = [
    { key: 'overview', label: t('properties.overview'), icon: Building2 },
    { key: 'units', label: `${unitLabel} (${ready('units') ? units.length : '—'})`, icon: Home },
    { key: 'finance', label: t('properties.finance'), icon: Wallet },
    { key: 'contracts', label: `${t('properties.contracts')} (${ready('contracts') ? contracts.length : '—'})`, icon: FileCheck2 },
    { key: 'documents', label: `${t('properties.documents')} (${ready('documents') ? documents.length : '—'})`, icon: FileText },
    { key: 'maintenance', label: `${t('properties.maintenance')} (${openMaintenance ?? '—'})`, icon: Wrench },
  ];
  const activateTab = key => {
    setTab(key);
    document.getElementById(`property-tab-${key}`)?.focus();
  };
  const onTabKeyDown = (event, index) => {
    const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
    if (next != null) { event.preventDefault(); activateTab(tabs[next].key); }
  };
  const errorNotice = key => errors[key] && <div className="property-notice property-notice-error" role="alert"><div><strong>{t(`properties.errors.${key}`)}</strong><p>{errors[key]}</p></div><button className="btn btn-secondary btn-sm" onClick={load}><RefreshCw size={15} aria-hidden="true" />{t('properties.retry')}</button></div>;
  const columns = {
    units: [
      { key: 'label', label: t('units.list.columns.label'), render: (value, unit) => <Link className="property-table-identity" to={`/units/${unit.id}`}><strong>{value}</strong></Link> },
      { key: 'unit_type', label: t('units.list.columns.type'), render: value => typeLabel(value, 'units.types') },
      { key: 'area_sqm', label: t('units.list.columns.area'), type: 'number', align: 'right', render: value => value == null ? '—' : `${decimal(number(value))} m²` },
      { key: 'cold_rent', label: t('properties.monthlyRent'), type: 'number', align: 'right', render: value => money(number(value)) },
      { key: 'status', label: t('ui.form.status'), render: value => <PropertyStatus status={value} t={t} /> },
    ],
    contracts: [
      { key: 'contract_number', label: t('properties.contractNumber') },
      { key: 'start_date', label: t('properties.startDate'), type: 'date' },
      { key: 'end_date', label: t('properties.endDate'), type: 'date' },
      { key: 'status', label: t('ui.form.status'), render: value => <PropertyStatus status={value} t={t} /> },
    ],
    documents: [
      { key: 'title', label: t('pages.propertyDetail.docTitle') },
      { key: 'document_type', label: t('units.list.columns.type') },
      { key: 'document_date', label: t('finance.bookings.form.date'), type: 'date' },
    ],
    maintenance: [
      { key: 'title', label: t('pages.propertyDetail.docTitle') },
      { key: 'priority', label: t('pages.propertyDetail.priority'), render: value => <PropertyStatus status={value} t={t} /> },
      { key: 'status', label: t('ui.form.status'), render: value => <PropertyStatus status={value} t={t} /> },
      { key: 'due_date', label: t('pages.propertyDetail.dueDate'), type: 'date' },
    ],
  };
  const display = (value, unit = '') => value == null || value === '' ? '—' : `${decimal(number(value))}${unit}`;

  if (loading && (!property || property.id !== id)) return <div className="page property-detail-page"><Link className="property-back-link" to="/properties"><ArrowLeft size={17} aria-hidden="true" />{t('properties.backToProperties')}</Link><div className="property-state" role="status"><Building2 size={30} aria-hidden="true" /><h1>{t('properties.loading')}</h1><p>{t('properties.loadingDescription')}</p></div></div>;
  if (!property) return <div className="page property-detail-page"><Link className="property-back-link" to="/properties"><ArrowLeft size={17} aria-hidden="true" />{t('properties.backToProperties')}</Link>{errorNotice('property')}</div>;

  const address = [property.address_line, [property.postal_code, property.city].filter(Boolean).join(' ')].filter(Boolean).join(', ');
  const recentDocuments = [...documents].sort((a, b) => String(b.document_date || b.created_at || '').localeCompare(String(a.document_date || a.created_at || ''))).slice(0, 4);
  return (
    <div className="page property-detail-page" aria-busy={loading}>
      <Link className="property-back-link" to="/properties"><ArrowLeft size={17} aria-hidden="true" />{t('properties.backToProperties')}</Link>
      <header className="property-detail-hero"><div className="property-detail-object-icon"><Building2 size={31} aria-hidden="true" /></div><div className="property-detail-identity"><div className="property-detail-heading-line"><span className="property-eyebrow">{typeLabel(property.property_type, 'properties.typeLabels')}</span><PropertyStatus status={property.status} t={t} /></div><h1>{property.name}</h1><p><MapPin size={16} aria-hidden="true" />{address || t('properties.noAddress')}</p></div><button className="property-icon-button" aria-label={t('properties.refresh')} onClick={load} disabled={loading}><RefreshCw size={18} aria-hidden="true" /></button></header>
      {loading && <p className="property-data-caption" role="status">{t('properties.refreshing')}</p>}
      <section className="property-metrics" aria-label={t('properties.summary')}>
        <div className="property-metric"><span>{t('properties.monthlyRent')}</span><strong>{money(totalColdRent)}</strong><small>{t('properties.currentUnitValues')}</small></div>
        <div className="property-metric"><span>{t('properties.occupancy')}</span><strong>{occupancyRate == null ? '—' : `${occupancyRate}%`}</strong><small>{ready('units') ? t('properties.occupiedOf', { occupied: occupiedCount, total: units.length }) : t('properties.notAvailable')}</small></div>
        <div className="property-metric"><span>{t('properties.unitArea')}</span><strong>{totalArea == null ? '—' : `${decimal(totalArea)} m²`}</strong><small>{t('properties.recordedUnitArea')}</small></div>
        <div className="property-metric"><span>{t('properties.openMaintenance')}</span><strong>{openMaintenance ?? '—'}</strong><small>{t('properties.maintenanceBasis')}</small></div>
      </section>
      <nav className="property-detail-tabs" role="tablist" aria-label={t('properties.detailSections')}>{tabs.map((item, index) => { const { key, label } = item; const Icon = item.icon; return <button key={key} id={`property-tab-${key}`} role="tab" aria-selected={tab === key} aria-controls={`property-panel-${key}`} tabIndex={tab === key ? 0 : -1} onClick={() => setTab(key)} onKeyDown={event => onTabKeyDown(event, index)}><Icon size={17} aria-hidden="true" />{label}</button>; })}</nav>
      <section className="property-detail-content" role="tabpanel" id={`property-panel-${tab}`} aria-labelledby={`property-tab-${tab}`} tabIndex={0}>
        {tab === 'overview' && <div className="property-overview-grid">
          <section className="property-section property-facts"><div className="property-section-heading"><h2>{t('properties.keyData')}</h2><Building2 size={19} aria-hidden="true" /></div><dl>
            <div><dt>{t('properties.form.general.type')}</dt><dd>{typeLabel(property.property_type, 'properties.typeLabels')}</dd></div>
            <div><dt>{t('properties.form.metrics.yearBuilt')}</dt><dd>{property.year_built ?? '—'}</dd></div>
            <div><dt>{t('properties.form.metrics.livingArea')}</dt><dd>{display(property.living_area_sqm, ' m²')}</dd></div>
            <div><dt>{t('properties.form.metrics.usableArea')}</dt><dd>{display(property.usable_area_sqm, ' m²')}</dd></div>
            <div><dt>{t('properties.form.metrics.plotArea')}</dt><dd>{display(property.plot_area_sqm, ' m²')}</dd></div>
            <div><dt>{t('properties.form.ownership.ownershipShare')}</dt><dd>{display(property.ownership_share, ' %')}</dd></div>
          </dl><p className="property-data-caption">{t('properties.propertyAreaBasis')}</p></section>
          <section className="property-section"><div className="property-section-heading"><div><h2>{unitLabel}</h2><p>{ready('units') ? t('properties.vacancyCount', { count: vacantCount }) : t('properties.notAvailable')}</p></div><button className="property-text-action" onClick={() => activateTab('units')}>{t('properties.viewAll')}<ArrowUpRight size={16} aria-hidden="true" /></button></div>{errorNotice('units')}{ready('units') && (units.length ? <div className="property-unit-list">{units.slice(0, 5).map(unit => <Link to={`/units/${unit.id}`} key={unit.id}><div className="property-unit-icon"><Home size={18} aria-hidden="true" /></div><div><strong>{unit.label}</strong><span>{typeLabel(unit.unit_type, 'units.types')} · {number(unit.area_sqm) == null ? '—' : `${decimal(number(unit.area_sqm))} m²`}</span></div><PropertyStatus status={unit.status} t={t} /><ArrowUpRight size={16} aria-hidden="true" /></Link>)}</div> : <div className="property-section-empty"><Home size={24} aria-hidden="true" /><p>{t('properties.noUnits')}</p><Link className="property-text-action" to="/units">{t('properties.manageUnits')}<ArrowUpRight size={15} aria-hidden="true" /></Link></div>)}</section>
          <section className="property-section"><div className="property-section-heading"><h2>{t('properties.rentalAndOperations')}</h2><FileCheck2 size={19} aria-hidden="true" /></div>{errorNotice('contracts')}{errorNotice('maintenance')}<div className="property-operating-summary"><button onClick={() => activateTab('contracts')}><span>{t('properties.activeContracts')}</span><strong>{activeContracts ?? '—'}</strong><ArrowUpRight size={17} aria-hidden="true" /></button><button onClick={() => activateTab('maintenance')}><span>{t('properties.openMaintenance')}</span><strong>{openMaintenance ?? '—'}</strong><ArrowUpRight size={17} aria-hidden="true" /></button></div><p className="property-data-caption">{t('properties.contractBasis')}</p></section>
          <section className="property-section"><div className="property-section-heading"><h2>{t('properties.recentDocuments')}</h2><button className="property-text-action" onClick={() => activateTab('documents')}>{t('properties.viewAll')}<ArrowUpRight size={16} aria-hidden="true" /></button></div>{errorNotice('documents')}{ready('documents') && (recentDocuments.length ? <ul className="property-document-list">{recentDocuments.map(document => <li key={document.id}><FileText size={18} aria-hidden="true" /><div><strong>{document.title}</strong><span>{document.document_date ? new Intl.DateTimeFormat(locale).format(new Date(`${document.document_date}T00:00:00`)) : t('properties.noDocumentDate')}</span></div></li>)}</ul> : <div className="property-section-empty"><FileText size={24} aria-hidden="true" /><p>{t('properties.noDocuments')}</p></div>)}</section>
        </div>}
        {tab === 'finance' && <section className="property-section">{errorNotice('units')}<div className="property-section-heading"><div><h2>{t('properties.rentStructure')}</h2><p>{t('properties.rentBasis')}</p></div><Wallet size={21} aria-hidden="true" /></div><div className="property-finance-summary"><div><span>{t('properties.monthlyRent')}</span><strong>{money(totalColdRent)}</strong></div><div><span>{t('properties.annualProjection')}</span><strong>{money(totalColdRent == null ? null : totalColdRent * 12)}</strong></div><div><span>{t('properties.rentPerSqm')}</span><strong>{money(rentPerSqm)}</strong></div></div><p className="property-data-caption">{t('properties.projectionBasis')}</p>{ready('units') && (units.length ? <div className="property-finance-table-scroll" role="region" aria-label={t('properties.rentStructure')} tabIndex={0}><table className="property-finance-table"><thead><tr><th scope="col">{unitLabel}</th><th scope="col">{t('properties.monthlyRent')}</th><th scope="col">{t('properties.serviceAdvance')}</th><th scope="col">{t('properties.heatingAdvance')}</th><th scope="col">{t('properties.total')}</th></tr></thead><tbody>{units.map(unit => { const parts = ['cold_rent', 'service_charge_advance', 'heating_advance'].map(key => number(unit[key])); return <tr key={unit.id}><th scope="row"><Link to={`/units/${unit.id}`}>{unit.label}</Link></th>{parts.map((amount, index) => <td key={index}>{money(amount)}</td>)}<td>{money(parts.every(amount => amount != null) ? parts.reduce((sum, amount) => sum + amount, 0) : null)}</td></tr>; })}</tbody><tfoot><tr><th scope="row">{t('properties.total')}</th><td>{money(totalColdRent)}</td><td>{money(sumKnown(units, 'service_charge_advance'))}</td><td>{money(sumKnown(units, 'heating_advance'))}</td><td>{money(units.every(unit => ['cold_rent', 'service_charge_advance', 'heating_advance'].every(key => number(unit[key]) != null)) ? units.reduce((sum, unit) => sum + number(unit.cold_rent) + number(unit.service_charge_advance) + number(unit.heating_advance), 0) : null)}</td></tr></tfoot></table></div> : <p className="property-section-empty">{t('properties.noUnits')}</p>)}<div className="property-valuation"><dl><div><dt>{t('properties.form.ownership.purchasePrice')}</dt><dd>{money(number(property.purchase_price))}</dd></div><div><dt>{t('properties.form.ownership.marketValue')}</dt><dd>{money(number(property.market_value))}</dd></div></dl></div></section>}
        {['units', 'contracts', 'documents', 'maintenance'].includes(tab) && <section className="property-section property-detail-list"><div className="property-section-heading"><div><h2>{t(`properties.${tab}`)}</h2><p>{t(`properties.sectionDescriptions.${tab}`)}</p></div><Link className="btn btn-secondary btn-sm" to={`/${tab}`}>{t(`properties.manage.${tab}`)}<ArrowUpRight size={15} aria-hidden="true" /></Link></div>{errorNotice(tab)}{ready(tab) && <DataTable title={t(`properties.${tab}`)} columns={columns[tab]} data={sources[tab]} />}</section>}
      </section>
    </div>
  );
}
