import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import DataTable from '../components/DataTable';
import StatusBadge from '../components/StatusBadge';
import { ArrowRightIcon } from '../components/Icons';

function fmt(v) {
  return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(v || 0);
}

export default function PropertyDetail() {
  const { t } = useTranslation();
  const { id } = useParams();
  const navigate = useNavigate();
  const [property, setProperty] = useState(null);
  const [units, setUnits] = useState([]);
  const [contracts, setContracts] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [maintenance, setMaintenance] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('overview');

  useEffect(() => {
    Promise.all([
      api.get(`/properties/${id}`).catch(() => null),
      api.get('/units').catch(() => []),
      api.get('/contracts').catch(() => []),
      api.get('/documents').catch(() => []),
      api.get('/maintenance').catch(() => []),
    ]).then(([prop, allUnits, allContracts, allDocs, allMaint]) => {
      setProperty(prop);
      setUnits((allUnits || []).filter(u => u.property_id === id));
      setContracts((allContracts || []).filter(c => c.property_id === id));
      setDocuments((allDocs || []).filter(d => d.property_id === id));
      setMaintenance((allMaint || []).filter(m => m.property_id === id));
    }).finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;
  if (!property) return <div className="page"><div className="alert alert-error">{t('pages.propertyOverview.notFound') || 'Immobilie nicht gefunden'}</div></div>;

  const totalArea = units.reduce((s, u) => s + (u.area_sqm || 0), 0);
  const totalColdRent = units.reduce((s, u) => s + (u.cold_rent || 0), 0);
  const occupiedCount = units.filter(u => u.status === 'occupied').length;
  const vacantCount = units.filter(u => u.status === 'vacant').length;
  const rentPerSqm = totalArea > 0 ? totalColdRent / totalArea : 0;
  const activeContracts = contracts.filter(c => c.status === 'active').length;
  const openMaintenance = maintenance.filter(m => m.status === 'open' || m.status === 'in_progress').length;

  const unitLabel = t('units.list.title') || 'Einheiten';
  const docLabel = t('navigation.main.documents') || 'Dokumente';
  const maintLabel = t('navigation.main.maintenance') || 'Wartung';

  const TABS = [
    { key: 'overview', label: t('pages.propertyOverview.keyData') || 'Übersicht' },
    { key: 'units', label: `${unitLabel} (${units.length})` },
    { key: 'finance', label: t('navigation.sections.finance') || 'Finanzen' },
    { key: 'documents', label: `${docLabel} (${documents.length})` },
    { key: 'maintenance', label: `${maintLabel} (${openMaintenance})` },
  ];

  const UNIT_COLUMNS = [
    { key: 'label', label: t('units.list.columns.label') || 'Bezeichnung', filterType: 'text' },
    { key: 'unit_type', label: t('units.list.columns.type') || 'Typ', filterType: 'select' },
    { key: 'area_sqm', label: t('units.list.columns.area') || 'Fläche (m²)', type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toLocaleString('de-DE')} m²` : '—' },
    { key: 'cold_rent', label: t('units.list.columns.coldRent') || 'Kaltmiete (€)', type: 'number', align: 'right',
      render: v => v != null ? fmt(v) : '—' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select' },
  ];

  const DOC_COLUMNS = [
    { key: 'title', label: t('pages.propertyDetail.docTitle') || 'Titel', filterType: 'text' },
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
    <div className="page">
      <div className="detail-header">
        <button className="btn btn-sm btn-secondary" onClick={() => navigate('/properties')}>
          ← {t('pages.propertyOverview.back') || 'Zurück'}
        </button>
        <div className="detail-title">
          <h1>{property.name}</h1>
          <span className="text-muted">
            {[property.address_line, property.postal_code, property.city].filter(Boolean).join(', ') || t('pages.propertyDetail.noAddress') || 'Keine Adresse'}
          </span>
        </div>
        <StatusBadge status={property.status} />
      </div>

      {/* KPI Summary */}
      <div className="stats-grid" style={{ marginBottom: '1rem' }}>
        <div className="stat-card">
          <div className="stat-label">{t('pages.propertyDetail.totalColdRent') || 'Kaltmiete gesamt'}</div>
          <div className="stat-value">{fmt(totalColdRent)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">€/m²</div>
          <div className="stat-value">{rentPerSqm.toFixed(2)} €</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">{t('pages.propertyDetail.totalArea') || 'Gesamtfläche'}</div>
          <div className="stat-value">{totalArea.toLocaleString('de-DE')} m²</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">{unitLabel}</div>
          <div className="stat-value">
            <span className="text-green">{occupiedCount}</span>
            {' / '}
            {units.length}
            {vacantCount > 0 && <span className="text-red"> ({vacantCount} {t('units.status.vacant') || 'leer'})</span>}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">{t('pages.propertyOverview.activeContracts') || 'Aktive Verträge'}</div>
          <div className="stat-value">{activeContracts}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">{t('pages.dashboard.openMaintenance') || 'Offene Wartung'}</div>
          <div className={`stat-value ${openMaintenance > 0 ? 'text-red' : ''}`}>{openMaintenance}</div>
        </div>
      </div>

      {/* Tabs */}
      <div className="detail-tabs">
        {TABS.map(tb => (
          <button
            key={tb.key}
            className={`detail-tab ${tab === tb.key ? 'active' : ''}`}
            onClick={() => setTab(tb.key)}
          >
            {tb.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="detail-tab-content">
        {tab === 'overview' && (
          <div className="detail-overview-grid">
            <div className="panel">
              <div className="panel-header">{t('pages.propertyDetail.propertyDetails') || 'Immobiliendetails'}</div>
              <div className="panel-body">
                <div className="detail-field"><span>{t('portfolio.properties.form.type') || 'Typ'}:</span> {property.property_type || '—'}</div>
                <div className="detail-field"><span>{t('portfolio.properties.form.yearBuilt') || 'Baujahr'}:</span> {property.year_built || '—'}</div>
                <div className="detail-field"><span>{t('portfolio.properties.form.livingArea') || 'Wohnfläche'}:</span> {property.living_area_sqm ? `${property.living_area_sqm} m²` : '—'}</div>
                <div className="detail-field"><span>{t('portfolio.properties.form.plotArea') || 'Grundstück'}:</span> {property.plot_area_sqm ? `${property.plot_area_sqm} m²` : '—'}</div>
                <div className="detail-field"><span>{t('portfolio.properties.form.purchasePrice') || 'Kaufpreis'}:</span> {property.purchase_price ? fmt(property.purchase_price) : '—'}</div>
                <div className="detail-field"><span>{t('portfolio.properties.form.marketValue') || 'Marktwert'}:</span> {property.market_value ? fmt(property.market_value) : '—'}</div>
              </div>
            </div>
            <div className="panel">
              <div className="panel-header">{t('pages.propertyDetail.unitsOverview') || 'Einheiten-Übersicht'}</div>
              <div className="panel-body">
                {units.length === 0 ? <p className="empty-text">{t('pages.propertyDetail.noUnits') || 'Keine Einheiten'}</p> : (
                  <ul className="activity-list">
                    {units.slice(0, 8).map(u => (
                      <li key={u.id}>
                        <span className="activity-title">{u.label}</span>
                        <span className="text-muted">{u.unit_type} · {u.area_sqm || '—'} m²</span>
                        <StatusBadge status={u.status} />
                      </li>
                    ))}
                  </ul>
                )}
                {units.length > 8 && (
                  <button className="panel-link" onClick={() => setTab('units')}>
                    {t('pages.propertyDetail.allUnits') || `Alle ${units.length} Einheiten`} <ArrowRightIcon size={14} />
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
                        <span className="activity-title">{d.title}</span>
                        <span className="text-muted">{d.document_type || t('pages.propertyDetail.other') || 'Sonstig'}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>
        )}

        {tab === 'units' && (
          <DataTable title={unitLabel} columns={UNIT_COLUMNS} data={units} />
        )}

        {tab === 'finance' && (
          <div className="panel">
            <div className="panel-header">{t('pages.propertyDetail.financeOverview') || 'Finanzübersicht'}</div>
            <div className="panel-body">
              <div className="stats-grid">
                <div className="stat-card">
                  <div className="stat-label">{t('pages.propertyDetail.monthlyColdRent') || 'Monatliche Kaltmiete'}</div>
                  <div className="stat-value">{fmt(totalColdRent)}</div>
                </div>
                <div className="stat-card">
                  <div className="stat-label">{t('pages.propertyDetail.annualRent') || 'Jahresmiete (Kalt)'}</div>
                  <div className="stat-value">{fmt(totalColdRent * 12)}</div>
                </div>
                <div className="stat-card">
                  <div className="stat-label">{t('pages.propertyDetail.avgPerSqm') || 'Durchschnitt €/m²'}</div>
                  <div className="stat-value">{rentPerSqm.toFixed(2)} €</div>
                </div>
              </div>
              <div style={{ marginTop: '1rem' }}>
                <h4>{t('pages.propertyDetail.rentByUnit') || 'Mietübersicht nach Einheit'}</h4>
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
                        <td>{u.label}</td>
                        <td>{u.unit_type}</td>
                        <td style={{ textAlign: 'right' }}>{fmt(u.cold_rent)}</td>
                        <td style={{ textAlign: 'right' }}>{fmt(u.service_charge_advance)}</td>
                        <td style={{ textAlign: 'right' }}>{fmt(u.heating_advance)}</td>
                        <td style={{ textAlign: 'right', fontWeight: 600 }}>
                          {fmt((u.cold_rent || 0) + (u.service_charge_advance || 0) + (u.heating_advance || 0))}
                        </td>
                      </tr>
                    ))}
                    <tr style={{ fontWeight: 700, borderTop: '2px solid var(--color-border)' }}>
                      <td colSpan={2}>{t('pages.propertyDetail.total') || 'Gesamt'}</td>
                      <td style={{ textAlign: 'right' }}>{fmt(totalColdRent)}</td>
                      <td style={{ textAlign: 'right' }}>{fmt(units.reduce((s, u) => s + (u.service_charge_advance || 0), 0))}</td>
                      <td style={{ textAlign: 'right' }}>{fmt(units.reduce((s, u) => s + (u.heating_advance || 0), 0))}</td>
                      <td style={{ textAlign: 'right' }}>
                        {fmt(units.reduce((s, u) => s + (u.cold_rent || 0) + (u.service_charge_advance || 0) + (u.heating_advance || 0), 0))}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {tab === 'documents' && (
          <DataTable title={docLabel} columns={DOC_COLUMNS} data={documents} />
        )}

        {tab === 'maintenance' && (
          <DataTable title={t('pages.propertyDetail.maintenanceTitle') || 'Wartung & Instandhaltung'} columns={MAINT_COLUMNS} data={maintenance} />
        )}
      </div>
    </div>
  );
}
