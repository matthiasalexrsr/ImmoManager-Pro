import PhotoDropZone from '../components/PhotoDropZone';
import NotificationArrival from '../components/NotificationArrival';
import { useState, useEffect, useRef } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useCanWrite } from '../contexts/AuthContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import FileViewer from '../components/FileViewer';
import { ArrowRightIcon, EditIcon } from '../components/Icons';
import NewForMenu from '../components/NewForMenu';
import { formatArea, formatDate, formatMoney, plainLabel } from '../utils/format';
import { codeLabel } from '../utils/codeLabels';
import { newEntryLink } from '../utils/newEntry';
import { resolveFileUrl } from '../features/partyWorkspace/files';
import { PartyLink } from '../features/partyWorkspace/PartyWorkspace';
import { propertyFields } from '../features/properties/propertyFields';
import EntityActions from '../features/workCenter/EntityActions';
import EntityTimeline from '../features/workCenter/EntityTimeline';
import DossierTabs from '../components/DossierTabs';
import { currentContractsOn, localDay, occupancyMapOn } from '../utils/occupancy';
import './propertyDossier.css';

// What can be started from a property, each opened prefilled with it.
const NEW_FOR_PROPERTY = [
  ['/units', 'Einheit'], ['/contracts', 'Mietvertrag'], ['/maintenance', 'Wartungsfall'],
  ['/bookings', 'Buchung'], ['/invoices', 'Rechnung'], ['/tasks', 'Aufgabe'],
];
const TAB_KEYS = ['overview', 'units', 'contracts', 'finance', 'documents', 'maintenance', 'timeline'];

const fmt = formatMoney;
const RENT_FIELDS = ['cold_rent', 'service_charge_advance', 'heating_advance'];

function rentSubtotal(values) {
  const known = values.filter(value => value != null && value !== '' && Number.isFinite(Number(value)));
  // Match the table's money totals: add each source amount in whole cents.
  const cents = known.reduce((total, value) => total + Math.round(Number(value) * 100), 0);
  return { amount: known.length ? cents / 100 : null, missing: values.length - known.length };
}

function subtotalLabel(subtotal) {
  return `${formatMoney(subtotal.amount)}${subtotal.missing ? ' (unvollständig)' : ''}`;
}

function DocumentReference({ document, onOpen }) {
  const hasFile = typeof document.file_url === 'string' && document.file_url.trim();
  if (!resolveFileUrl(document.file_url)) return <span className="dossier-document-reference">
    <span>{document.title}</span>
    <small className="text-muted">{hasFile ? 'Ungültiger Dateiverweis' : 'Datei fehlt'}</small>
  </span>;
  return <button type="button" className="dossier-document-link" aria-label={`Dokument ansehen: ${document.title}`}
    onClick={() => onOpen(document)}>{document.title}</button>;
}

export default function PropertyDetail() {
  const { id } = useParams();
  return <PropertyDossier key={id} id={id} />;
}

function PropertyDossier({ id }) {
  const { t } = useTranslation();
  const [property, setProperty] = useState(null);
  const [unitRows, setUnits] = useState([]);
  const [contracts, setContracts] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [maintenance, setMaintenance] = useState([]);
  const [loading, setLoading] = useState(true);
  const [params, setParams] = useSearchParams();
  const tab = TAB_KEYS.includes(params.get('tab')) ? params.get('tab') : 'overview';
  const setTab = (value, filters = {}) => setParams(current => {
    const next = new URLSearchParams(current);
    if (value === 'overview') next.delete('tab'); else next.set('tab', value);
    Object.entries(filters).forEach(([key, filter]) => next.set(key, filter));
    return next;
  }, { replace: true });
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [viewerFile, setViewerFile] = useState(null);
  const [tenants, setTenants] = useState([]);
  const [tenantError, setTenantError] = useState(null);
  const [editing, setEditing] = useState(null);       // the portfolios for the edit form, once loaded
  const [activityRevision, setActivityRevision] = useState(0);
  const contractView = params.get('contracts') === 'active' ? 'active' : 'all';
  const maintenanceView = params.get('maintenance') === 'open' ? 'open' : 'all';
  const setView = (key, value) => setParams(current => {
    const next = new URLSearchParams(current);
    if (value === 'all') next.delete(key); else next.set(key, value);
    return next;
  }, { replace: true });
  const setContractView = value => setView('contracts', value);
  const setMaintenanceView = value => setView('maintenance', value);
  const [photosOpen, setPhotosOpen] = useState(false);
  const rentSources = useRef(null);
  const focusRentSources = () => { rentSources.current?.focus(); rentSources.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' }); };
  const canEdit = useCanWrite('/properties');
  const navigate = useNavigate();
  // a New form of another list, prefilled with this property
  const startNew = path => () => { const link = newEntryLink(path, { property_id: id }); navigate(link.to, { state: link.state }); };

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const options = { signal: controller.signal };
    const propertyId = encodeURIComponent(id);
    setLoading(true);
    setError(null);
    setTenantError(null);
    Promise.all([
      api.get(`/properties/${propertyId}`, options),
      api.list(`/units?property_id=${propertyId}`, options),
      api.list(`/contracts?property_id=${propertyId}`, options),
      api.list(`/documents?property_id=${propertyId}`, options),
      api.list(`/maintenance?property_id=${propertyId}`, options),
      api.list('/tenants', options).catch(failure => {
        if (!cancelled) setTenantError(failure.message || 'Parteiennamen konnten nicht geladen werden.');
        return [];
      }),
    ]).then(([prop, propUnits, propContracts, propDocs, propMaint, allTenants]) => {
      if (cancelled) return;
      if (!prop) throw new Error('Immobilie nicht gefunden');
      setProperty(prop);
      setUnits(propUnits || []);
      setContracts(propContracts || []);
      setDocuments(propDocs || []);
      setMaintenance(propMaint || []);
      setTenants(allTenants || []);
    }).catch(failure => { if (!cancelled) setError(failure.message || 'Immobilienakte konnte nicht geladen werden.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; controller.abort(); };
  }, [id, revision]);

  const occupancy = occupancyMapOn(unitRows, contracts, localDay());
  const units = unitRows.map(unit => ({ ...unit, status: occupancy[unit.id].status }));

  if (loading) return <div className="page-loading" role="status">{t('ui.table.loading') || 'Immobilienakte wird geladen…'}</div>;
  if (error) return <div className="page property-dossier">
    <div role="alert" className="alert alert-error">{error}</div>
    <div className="dossier-navigation">
      <button type="button" className="btn btn-secondary" onClick={() => setRevision(value => value + 1)}>Erneut laden</button>
      <Link className="btn btn-secondary" to="/properties">Zur Immobilienliste</Link>
    </div>
  </div>;
  if (!property) return <div className="page"><div className="alert alert-error">{t('pages.propertyOverview.notFound') || 'Immobilie nicht gefunden'}</div></div>;

  const withArea = units.filter(unit => unit.area_sqm != null && Number.isFinite(Number(unit.area_sqm)));
  const totalArea = withArea.length ? withArea.reduce((sum, unit) => sum + Number(unit.area_sqm), 0) : null;
  const rentTotals = Object.fromEntries(RENT_FIELDS.map(key => [key, rentSubtotal(units.map(unit => unit[key]))]));
  const coldRent = rentTotals.cold_rent;
  const totalColdRent = coldRent.amount;
  const totalRent = rentSubtotal(units.flatMap(unit => RENT_FIELDS.map(key => unit[key])));
  const annualColdRent = coldRent.missing === 0 && totalColdRent != null ? Math.round(totalColdRent * 100) * 12 / 100 : null;
  const occupiedCount = units.filter(u => u.status === 'occupied').length;
  const vacantCount = units.filter(u => u.status === 'vacant').length;
  const rentPerSqm = coldRent.missing === 0 && totalColdRent != null && withArea.length === units.length && totalArea > 0 ? totalColdRent / totalArea : null;
  const currentContracts = currentContractsOn(contracts);
  const activeContracts = currentContracts.length;
  const openMaintenance = maintenance.filter(m => m.status === 'open' || m.status === 'in_progress').length;

  const unitLabel = t('units.list.title') || 'Einheiten';
  const docLabel = t('navigation.main.documents') || 'Dokumente';
  const maintLabel = t('navigation.main.maintenance') || 'Wartung';

  const TABS = [
    { key: 'overview', label: t('pages.propertyOverview.keyData') || 'Übersicht' },
    { key: 'units', label: `${unitLabel} (${units.length})` },
    { key: 'contracts', label: `Mieter & Verträge (${activeContracts})` },
    { key: 'finance', label: t('navigation.sections.finance') || 'Finanzen' },
    { key: 'documents', label: `${docLabel} (${documents.length})` },
    { key: 'maintenance', label: `${maintLabel} (${openMaintenance})` },
    { key: 'timeline', label: 'Aktivitäten' },
  ];

  const UNIT_COLUMNS = [
    { key: 'label', label: t('units.list.columns.label') || 'Bezeichnung', filterType: 'text',
      render: (value, unit) => <Link to={`/units/${encodeURIComponent(unit.id)}`}>{value || unit.unit_number || 'Einheit öffnen'}</Link> },
    { key: 'unit_type', label: t('units.list.columns.type') || 'Typ', filterType: 'select' },
    { key: 'area_sqm', label: t('units.list.columns.area') || 'Fläche (m²)', type: 'number', sum: 'number', formatTotal: formatArea, align: 'right',
      render: v => formatArea(v) },
    { key: 'cold_rent', label: 'Plan-Kaltmiete (€)', type: 'number', sum: coldRent.missing === 0, align: 'right',
      render: v => v != null ? fmt(v) : '—' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select' },
  ];

  const tenantName = Object.fromEntries(tenants.map(tn => [tn.id, tn.full_name]));
  const unitName = Object.fromEntries(units.map(u => [u.id, u.label || u.unit_number]));
  const CONTRACT_COLUMNS = [
    { key: 'contract_number', label: 'Vertrag', filterType: 'text' },
    { key: 'tenant_name', label: 'Mieter', filterType: 'text',
      render: (value, contract) => <PartyLink tenantId={contract.tenant_id}>{value || '—'}</PartyLink> },
    { key: 'unit_name', label: 'Einheit', filterType: 'text',
      render: (value, contract) => <Link to={`/units/${encodeURIComponent(contract.unit_id)}`}>{value || 'Einheit öffnen'}</Link> },
    { key: 'start_date', label: 'Beginn', type: 'date', render: v => formatDate(v) },
    { key: 'end_date', label: 'Ende', type: 'date', render: v => (v ? formatDate(v) : 'unbefristet') },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select' },
  ];
  const contractRows = contracts.map(c => ({ ...c, tenant_name: tenantName[c.tenant_id], unit_name: unitName[c.unit_id] }));

  const openEdit = async () => {
    const portfolios = await api.list('/portfolios').catch(() => []);
    setEditing({ portfolios });
  };
  const saveProperty = async data => {
    await api.put(`/properties/${encodeURIComponent(id)}`, data);
    setRevision(value => value + 1);
  };

  const DOC_COLUMNS = [
    { key: 'title', label: t('pages.propertyDetail.docTitle') || 'Titel', filterType: 'text', wrap: true,
      render: (_, document) => <DocumentReference document={document} onOpen={setViewerFile} /> },
    { key: 'document_type', label: t('units.list.columns.type') || 'Typ', filterType: 'select' },
    { key: 'document_date', label: t('finance.bookings.form.date') || 'Datum', type: 'date' },
  ];

  const MAINT_COLUMNS = [
    { key: 'title', label: t('pages.propertyDetail.docTitle') || 'Titel', filterType: 'text' },
    { key: 'priority', label: t('pages.propertyDetail.priority') || 'Priorität', type: 'status' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select' },
    { key: 'due_date', label: t('pages.propertyDetail.dueDate') || 'Fällig', type: 'date' },
  ];

  return (
    <div className="page property-dossier">
      <div className="detail-header">
        <Link className="btn btn-sm btn-secondary" to="/properties">
          ← {t('pages.propertyOverview.back') || 'Zurück'}
        </Link>
        <div className="detail-title">
          <NotificationArrival record={property} ready={!loading && !error} /><p className="dossier-eyebrow">Immobilienakte</p><h1>{property.name}</h1>
          <span className="text-muted">
            {[property.address_line, property.postal_code, property.city].filter(Boolean).join(', ') || t('pages.propertyDetail.noAddress') || 'Keine Adresse'}
          </span>
        </div>
        <StatusBadge status={property.status} />
        <div className="dossier-actions">
          <Link className="btn btn-secondary btn-sm" to={`/reports?kind=cash-v2&property_id=${encodeURIComponent(id)}`}>Auswertungen dieses Objekts</Link>
          <Link className="btn btn-secondary btn-sm" to={`/teha?property_id=${encodeURIComponent(id)}`}>TEHA Kundenportal</Link>
          {canEdit && <button type="button" className="btn btn-secondary btn-sm" onClick={openEdit}><EditIcon size={15} /> Bearbeiten</button>}
          <NewForMenu label="Neu für dieses Objekt" items={NEW_FOR_PROPERTY} prefill={{ property_id: id }} />
          <EntityActions entityType="property" entityId={id} entityRevision={property.updated_at} title={property.name}
            onChanged={() => setActivityRevision(value => value + 1)} />
        </div>
      </div>

      {/* KPI Summary */}
      <div className="stats-grid" style={{ marginBottom: '1rem' }}>
        <button type="button" className="stat-card dossier-kpi-button" onClick={() => setTab('units')}>
          <div className="stat-label">{coldRent.missing ? 'Plan-Kaltmiete – unvollständige Zwischensumme' : 'Plan-Kaltmiete gesamt'}</div>
          <div className="stat-value">{fmt(totalColdRent)}</div>
        </button>
        <button type="button" className="stat-card dossier-kpi-button" onClick={() => setTab('units')}>
          <div className="stat-label">Plan-Kaltmiete €/m²</div>
          <div className="stat-value">{formatMoney(rentPerSqm)}</div>
        </button>
        <button type="button" className="stat-card dossier-kpi-button" onClick={() => setTab('units')}>
          <div className="stat-label">{t('pages.propertyDetail.totalArea') || 'Gesamtfläche'}</div>
          <div className="stat-value">{formatArea(totalArea)}</div>
        </button>
        <button type="button" className="stat-card dossier-kpi-button" onClick={() => setTab('units')}>
          <div className="stat-label">{unitLabel}</div>
          <div className="stat-value">
            <span className="text-green">{occupiedCount}</span>
            {' / '}
            {units.length}
            {vacantCount > 0 && <span className="text-red"> ({vacantCount} {t('units.status.vacant') || 'leer'})</span>}
          </div>
        </button>
        <button type="button" className="stat-card dossier-kpi-button" onClick={() => setTab('contracts', { contracts: 'active' })}>
          <div className="stat-label">{t('pages.propertyOverview.activeContracts') || 'Aktive Verträge'}</div>
          <div className="stat-value">{activeContracts}</div>
        </button>
        <button type="button" className="stat-card dossier-kpi-button" onClick={() => setTab('maintenance', { maintenance: 'open' })}>
          <div className="stat-label">{t('pages.dashboard.openMaintenance') || 'Offene Wartung'}</div>
          <div className={`stat-value ${openMaintenance > 0 ? 'text-red' : ''}`}>{openMaintenance}</div>
        </button>
      </div>
      <p className="text-muted dossier-rent-note">Planmieten aus den Stammdaten der Einheiten. Tatsächliche Vertragsmieten und Zahlungseingänge können abweichen.</p>
      {coldRent.missing > 0 && <p className="text-muted dossier-rent-note">Für {coldRent.missing} von {units.length} Einheiten fehlt die Plan-Kaltmiete. Die Zwischensumme enthält nur erfasste Beträge. Jahresplan und €/m² erscheinen nach vollständiger Erfassung.</p>}
      {withArea.length < units.length && <p className="text-muted dossier-rent-note">Für {units.length - withArea.length} von {units.length} Einheiten fehlt die Fläche. Die Kennzahl €/m² erscheint nach vollständiger Erfassung.</p>}

      {/* Tabs */}
      <DossierTabs tabs={TABS} value={tab} onChange={setTab} label="Bereiche der Immobilienakte">
        {tab === 'timeline' && <EntityTimeline entityType="property" entityId={id} revision={activityRevision} />}
        {tab === 'overview' && (
          <><details className="panel dossier-media" open={photosOpen} onToggle={event => setPhotosOpen(event.currentTarget.open)}>
            <summary className="panel-header">Fotos der Immobilie</summary>
            {photosOpen && <div className="panel-body"><PhotoDropZone entityType="property" entityId={id} /></div>}
          </details><div className="detail-overview-grid">
            <div className="panel">
              <div className="panel-header">{t('pages.propertyDetail.propertyDetails') || 'Immobiliendetails'}</div>
              <div className="panel-body">
                <div className="detail-field"><span>{t('portfolio.properties.form.type') || 'Typ'}:</span> {codeLabel(property.property_type) || '—'}</div>
                <div className="detail-field"><span>{t('portfolio.properties.form.yearBuilt') || 'Baujahr'}:</span> {property.year_built || '—'}</div>
                <div className="detail-field"><span>{plainLabel(t('portfolio.properties.form.livingArea') || 'Wohnfläche')}:</span> {formatArea(property.living_area_sqm)}</div>
                <div className="detail-field"><span>{plainLabel(t('portfolio.properties.form.plotArea') || 'Grundstück')}:</span> {formatArea(property.plot_area_sqm)}</div>
                <div className="detail-field"><span>{plainLabel(t('portfolio.properties.form.purchasePrice') || 'Kaufpreis')}:</span> {property.purchase_price ? fmt(property.purchase_price) : '—'}</div>
                <div className="detail-field"><span>{plainLabel(t('portfolio.properties.form.marketValue') || 'Marktwert')}:</span> {property.market_value ? fmt(property.market_value) : '—'}</div>
              </div>
            </div>
            <div className="panel">
              <div className="panel-header">{t('pages.propertyDetail.unitsOverview') || 'Einheiten-Übersicht'}</div>
              <div className="panel-body">
                {units.length === 0 ? <p className="empty-text">{t('pages.propertyDetail.noUnits') || 'Keine Einheiten'}</p> : (
                  <ul className="activity-list">
                    {units.slice(0, 8).map(u => (
                      <li key={u.id}>
                        <Link className="activity-title" to={`/units/${encodeURIComponent(u.id)}`}>{u.label || u.unit_number || 'Einheit öffnen'}</Link>
                        <span className="text-muted">{codeLabel(u.unit_type)} · {formatArea(u.area_sqm)}</span>
                        <StatusBadge status={u.status} />
                      </li>
                    ))}
                  </ul>
                )}
                {units.length > 8 && (
                  <button className="panel-link" onClick={() => setTab('units')}>
                    {t('pages.propertyDetail.allUnits', { count: units.length })} <ArrowRightIcon size={14} />
                  </button>
                )}
              </div>
            </div>
            <div className="panel">
              <div className="panel-header">{t('pages.propertyDetail.recentDocuments') || 'Letzte Dokumente'}</div>
              <div className="panel-body">
                {documents.length === 0 ? <p className="empty-text">{t('pages.propertyDetail.noDocuments') || 'Keine Dokumente'}</p> : (
                  <ul className="activity-list">
                    {documents.slice(0, 5).map(d => (
                      <li key={d.id}>
                        <span className="activity-title"><DocumentReference document={d} onOpen={setViewerFile} /></span>
                        <span className="text-muted">{codeLabel(d.document_type) || t('pages.propertyDetail.other') || 'Sonstig'}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div></>
        )}

        {tab === 'units' && (
          <DataTable title={unitLabel} columns={UNIT_COLUMNS} data={units} settingsKey="property-units"
            onAdd={startNew('/units')} addLabel="Einheit anlegen" writeArea="/units"
            onRowClick={unit => navigate(`/units/${encodeURIComponent(unit.id)}`)} />
        )}

        {tab === 'contracts' && (
          <>{tenantError && <div role="alert" className="alert alert-error">Parteiennamen konnten nicht geladen werden. {tenantError} <button type="button" className="btn btn-sm btn-secondary" onClick={() => setRevision(value => value + 1)}>Erneut laden</button></div>}
          <div className="filter-chips"><button type="button" className="btn btn-sm btn-secondary" aria-pressed={contractView === 'all'} onClick={() => setContractView('all')}>Alle Verträge</button>
            <button type="button" className="btn btn-sm btn-secondary" aria-pressed={contractView === 'active'} onClick={() => setContractView('active')}>Aktive Verträge</button></div>
          <DataTable title="Mieter & Verträge" columns={CONTRACT_COLUMNS} data={contractView === 'active' ? contractRows.filter(row => currentContracts.some(contract => contract.id === row.id)) : contractRows} settingsKey="property-contracts"
            viewConfig={{ column_filters: { workflow_filter: contractView } }} viewAnchor={{ kind: 'property', id }}
            onApplyView={config => setContractView(config.column_filters?.workflow_filter === 'active' ? 'active' : 'all')}
            onAdd={startNew('/contracts')} addLabel="Vertrag anlegen" writeArea="/contracts" /></>
        )}

        {tab === 'finance' && (
          <div className="panel">
            <div className="panel-header">{t('pages.propertyDetail.financeOverview') || 'Finanzübersicht'}</div>
            <div className="panel-body">
              <div className="stats-grid">
                <button type="button" className="stat-card dossier-kpi-button" onClick={focusRentSources}>
                  <div className="stat-label">{coldRent.missing ? 'Monatliche Plan-Kaltmiete (unvollständige Zwischensumme)' : 'Monatliche Plan-Kaltmiete'}</div>
                  <div className="stat-value">{fmt(totalColdRent)}</div>
                </button>
                <button type="button" className="stat-card dossier-kpi-button" onClick={focusRentSources}>
                  <div className="stat-label">Jährliche Plan-Kaltmiete</div>
                  <div className="stat-value">{fmt(annualColdRent)}</div>
                </button>
                <button type="button" className="stat-card dossier-kpi-button" onClick={focusRentSources}>
                  <div className="stat-label">Plan-Kaltmiete Ø €/m²</div>
                  <div className="stat-value">{formatMoney(rentPerSqm)}</div>
                </button>
              </div>
              <div style={{ marginTop: '1rem' }}>
                <h4>Planmieten nach Einheit</h4>
                <p className="text-muted">Monatssumme aus diesen Einheiten · Jahresplan = Monatssumme × 12 · €/m² = Monatssumme / Gesamtfläche ({formatArea(totalArea)}).</p>
                {totalRent.missing > 0 && <p className="text-muted">Fehlende Beträge erscheinen als —. Unvollständige Zwischensummen enthalten nur erfasste Beträge; fehlende Werte sind keine Nullbeträge.</p>}
                <div ref={rentSources} className="dossier-table-scroll" role="region" aria-label="Planmieten nach Einheit" tabIndex={0}>
                <table className="simple-table">
                  <thead>
                    <tr>
                      <th>{unitLabel}</th>
                      <th>{t('units.list.columns.type') || 'Typ'}</th>
                      <th style={{ textAlign: 'right' }}>{t('units.list.columns.coldRent') || 'Kaltmiete'}</th>
                      <th style={{ textAlign: 'right' }}>{t('pages.propertyDetail.serviceCharge') || 'NK'}</th>
                      <th style={{ textAlign: 'right' }}>{t('pages.propertyDetail.heating') || 'Heizung'}</th>
                      <th style={{ textAlign: 'right' }}>{t('pages.propertyDetail.total') || 'Gesamt'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {units.map(u => (
                      <tr key={u.id}>
                        <td><Link to={`/units/${encodeURIComponent(u.id)}`}>{u.label || u.unit_number || 'Einheit öffnen'}</Link></td>
                        <td>{codeLabel(u.unit_type)}</td>
                        <td style={{ textAlign: 'right' }}>{fmt(u.cold_rent)}</td>
                        <td style={{ textAlign: 'right' }}>{fmt(u.service_charge_advance)}</td>
                        <td style={{ textAlign: 'right' }}>{fmt(u.heating_advance)}</td>
                        <td style={{ textAlign: 'right', fontWeight: 600 }}>
                          {subtotalLabel(rentSubtotal(RENT_FIELDS.map(key => u[key])))}
                        </td>
                      </tr>
                    ))}
                    <tr style={{ fontWeight: 700, borderTop: '2px solid var(--color-border)' }}>
                      <td colSpan={2}>{totalRent.missing ? 'Zwischensummen (unvollständig)' : t('pages.propertyDetail.total') || 'Gesamt'}</td>
                      <td style={{ textAlign: 'right' }}>{subtotalLabel(coldRent)}</td>
                      <td style={{ textAlign: 'right' }}>{subtotalLabel(rentTotals.service_charge_advance)}</td>
                      <td style={{ textAlign: 'right' }}>{subtotalLabel(rentTotals.heating_advance)}</td>
                      <td style={{ textAlign: 'right' }}>
                        {subtotalLabel(totalRent)}
                      </td>
                    </tr>
                  </tbody>
                </table>
                </div>
              </div>
              <div className="dossier-navigation dossier-finance-links">
                <Link className="btn btn-secondary btn-sm" to={`/bookings?property_id=${encodeURIComponent(id)}`}>Buchungen dieser Immobilie <ArrowRightIcon size={14} /></Link>
                <Link className="btn btn-secondary btn-sm" to="/rent-overview">Mietübersicht (Soll und Ist) <ArrowRightIcon size={14} /></Link>
                <Link className="btn btn-secondary btn-sm" to={`/invoices?property_id=${encodeURIComponent(id)}`}>Rechnungen <ArrowRightIcon size={14} /></Link>
              </div>
            </div>
          </div>
        )}

        {tab === 'documents' && (
          <DataTable title={docLabel} columns={DOC_COLUMNS} data={documents} />
        )}

        {tab === 'maintenance' && (
          <><div className="filter-chips"><button type="button" className="btn btn-sm btn-secondary" aria-pressed={maintenanceView === 'all'} onClick={() => setMaintenanceView('all')}>Alle Wartungsfälle</button>
            <button type="button" className="btn btn-sm btn-secondary" aria-pressed={maintenanceView === 'open'} onClick={() => setMaintenanceView('open')}>Offene Wartung</button></div>
          <DataTable title={t('pages.propertyDetail.maintenanceTitle') || 'Wartung & Instandhaltung'} columns={MAINT_COLUMNS} data={maintenanceView === 'open' ? maintenance.filter(row => ['open', 'in_progress'].includes(row.status)) : maintenance}
            viewConfig={{ column_filters: { workflow_filter: maintenanceView } }} viewAnchor={{ kind: 'property', id }}
            onApplyView={config => setMaintenanceView(config.column_filters?.workflow_filter === 'open' ? 'open' : 'all')}
            settingsKey="property-maintenance" onAdd={startNew('/maintenance')} addLabel="Wartungsfall anlegen" writeArea="/maintenance"
            onRowClick={item => navigate(`/maintenance/${encodeURIComponent(item.id)}`)} /></>
        )}
      </DossierTabs>
      {editing && <FormModal title="Immobilie bearbeiten" fields={propertyFields(t, editing.portfolios)}
        initial={property} onSave={saveProperty} onClose={() => setEditing(null)} />}
      {viewerFile && <FileViewer key={viewerFile.id} fileUrl={viewerFile.file_url} title={viewerFile.title} onClose={() => setViewerFile(null)} />}
    </div>
  );
}
