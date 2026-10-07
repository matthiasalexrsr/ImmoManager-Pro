import { useState, useEffect, useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';
import { formatMoney, formatArea } from '../utils/format';
import { useCanWrite } from '../contexts/AuthContext';
import { PlusIcon, PropertyIcon } from '../components/Icons';
import './ListWorkspace.css';

export default function Properties() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const toast = useToast();
  const store = useDataStore();
  const canWrite = useCanWrite('/properties');

  const portfolioSource = useEntities('portfolios', '/portfolios');
  const unitSource = useEntities('units', '/units');
  const maintenanceSource = useEntities('maintenance', '/maintenance');
  const { items: portfolios } = portfolioSource;
  const { items: units } = unitSource;
  const { items: maintenance } = maintenanceSource;
  const relatedSources = [portfolioSource, unitSource, maintenanceSource];

  const [properties, setProperties] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [filter, setFilter] = useState('all');
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState(0);

  const refreshData = () => setRevision(value => value + 1);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.list('/properties', { signal: controller.signal })
      .then(data => {
        if (!Array.isArray(data)) throw new Error('Immobiliendaten konnten nicht gelesen werden.');
        if (!cancelled) setProperties(data);
      })
      .catch(err => { if (!cancelled) setError(err.message || 'Immobilien konnten nicht geladen werden.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; controller.abort(); };
  }, [revision]);

  // Lookup maps
  const portfolioMap = Object.fromEntries(portfolios.map(p => [p.id, p.name]));

  // Group units by property_id
  const unitsByProperty = useMemo(() => {
    const map = {};
    units.forEach(u => {
      if (!map[u.property_id]) map[u.property_id] = [];
      map[u.property_id].push(u);
    });
    return map;
  }, [units]);

  // Group maintenance by property_id (only open/in_progress)
  const openMaintenanceByProperty = useMemo(() => {
    const map = {};
    maintenance.forEach(m => {
      if (m.status === 'open' || m.status === 'in_progress') {
        map[m.property_id] = (map[m.property_id] || 0) + 1;
      }
    });
    return map;
  }, [maintenance]);

  // Enrich properties
  const enriched = useMemo(() => properties.map(prop => {
    const propUnits = unitsByProperty[prop.id] || [];
    const totalUnits = propUnits.length;
    const occupiedUnits = propUnits.filter(u => u.status === 'occupied' || u.status === 'rented').length;
    const occupancyRate = totalUnits > 0 ? Math.round((occupiedUnits / totalUnits) * 100) : 0;
    const totalRent = propUnits.reduce((sum, u) => sum + (Number(u.cold_rent) || 0), 0);
    const openMaint = openMaintenanceByProperty[prop.id] || 0;
    const hasVacancy = totalUnits > 0 && occupiedUnits < totalUnits;

    return {
      ...prop,
      portfolio_name: portfolioMap[prop.portfolio_id] || '—',
      unit_count: totalUnits,
      occupancy_rate: occupancyRate,
      total_rent: totalRent,
      open_maintenance: openMaint,
      _hasVacancy: hasVacancy,
    };
  }), [properties, unitsByProperty, openMaintenanceByProperty, portfolioMap]);

  // Filtered data
  const filtered = useMemo(() => {
    if (filter === 'all') return enriched;
    if (filter === 'active') return enriched.filter(p => p.status === 'active');
    if (filter === 'inactive') return enriched.filter(p => p.status === 'inactive');
    if (filter === 'vacancy') return enriched.filter(p => p._hasVacancy);
    if (filter === 'open_maintenance') return enriched.filter(p => p.open_maintenance > 0);
    return enriched;
  }, [enriched, filter]);

  // Summary stats
  const totalCount = enriched.length;
  const activeCount = enriched.filter(p => p.status === 'active').length;
  const vacancyCount = enriched.filter(p => p._hasVacancy).length;
  const avgOccupancy = totalCount > 0
    ? Math.round(enriched.reduce((sum, p) => sum + p.occupancy_rate, 0) / totalCount)
    : 0;

  const columns = [
    { key: 'name', label: t('portfolio.properties.form.name') || 'Name', filterType: 'text',
      render: (name, row) => <Link className="list-identity list-property-link" to={`/properties/${encodeURIComponent(row.id)}`} onClick={event => event.stopPropagation()}>
        <span className="list-identity-icon" aria-hidden="true"><PropertyIcon size={20} /></span>
        <span className="list-identity-copy"><strong>{name}</strong><span>{[row.address_line, [row.postal_code, row.city].filter(Boolean).join(' ')].filter(Boolean).join(' · ') || 'Adresse ergänzen'}</span></span>
      </Link> },
    { key: 'portfolio_name', hidden: true, label: 'Portfolio', filterType: 'text' },
    { key: 'property_type', label: t('portfolio.properties.form.type') || 'Typ', filterType: 'select' },
    { key: 'city', hidden: true, label: t('portfolio.properties.form.city') || 'Stadt', filterType: 'text' },
    { key: 'postal_code', hidden: true, label: t('portfolio.properties.form.postalCode') || 'PLZ', filterType: 'text' },
    { key: 'unit_count', label: 'Einheiten', type: 'number', align: 'right' },
    { key: 'occupancy_rate', label: 'Vermietung', type: 'number', align: 'right',
      render: v => {
        const color = v >= 80 ? 'var(--color-success)' : v >= 50 ? 'var(--color-warning)' : 'var(--color-danger)';
        return <span className="list-occupancy"><span style={{ color, fontWeight: 600 }}>{v}%</span><span className="list-occupancy-track" aria-hidden="true"><span style={{ width: `${v}%`, background: color }} /></span></span>;
      }},
    { key: 'total_rent', label: 'Plan-Kaltmiete', type: 'number', align: 'right',
      render: v => formatMoney(v) },
    { key: 'open_maintenance', hidden: true, label: 'Offene Wartung', type: 'number', align: 'right',
      render: v => v > 0 ? <span style={{ color: 'var(--color-warning)', fontWeight: 600 }}>{v}</span> : '0' },
    { key: 'year_built', hidden: true, label: t('portfolio.properties.form.yearBuilt') || 'Baujahr', type: 'number' },
    { key: 'living_area_sqm', hidden: true, label: t('portfolio.properties.form.livingArea') || 'Wohnfläche (m²)', type: 'number', align: 'right',
      render: v => formatArea(v) },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
  ];

  const sStamm = t('portfolio.properties.sections.basic') || 'Stammdaten';
  const sAddr = t('portfolio.properties.sections.address') || 'Adresse';
  const sArea = t('portfolio.properties.sections.areas') || 'Flächen';
  const sFin = t('portfolio.properties.sections.valuation') || 'Kauf & Bewertung';

  const fields = [
    { section: sStamm, key: 'portfolio_id', label: 'Portfolio', required: true, type: 'select',
      options: portfolios.map(p => ({ value: p.id, label: p.name })) },
    { section: sStamm, key: 'name', label: t('portfolio.properties.form.name') || 'Name', required: true },
    { section: sStamm, key: 'property_type', label: t('portfolio.properties.form.type') || 'Typ', required: true, type: 'select', options: [
      { value: 'residential', label: t('portfolio.properties.types.residential') || 'Wohngebäude' },
      { value: 'commercial', label: t('portfolio.properties.types.commercial') || 'Gewerbe' },
      { value: 'mixed', label: t('portfolio.properties.types.mixed') || 'Gemischt' },
    ]},
    { section: sStamm, key: 'status', label: t('ui.form.status') || 'Status', type: 'select', default: 'active', options: [
      { value: 'active', label: t('status.general.active') || 'Aktiv' },
      { value: 'inactive', label: t('portfolio.properties.status.inactive') || 'Inaktiv' },
    ]},
    { section: sAddr, key: 'address_line', label: t('portfolio.properties.form.address') || 'Straße' },
    { section: sAddr, key: 'postal_code', label: t('portfolio.properties.form.postalCode') || 'PLZ' },
    { section: sAddr, key: 'city', label: t('portfolio.properties.form.city') || 'Stadt' },
    { section: sAddr, key: 'country', label: t('portfolio.properties.form.country') || 'Land', default: 'DE' },
    { section: sArea, key: 'year_built', label: t('portfolio.properties.form.yearBuilt') || 'Baujahr', type: 'number' },
    { section: sArea, key: 'living_area_sqm', label: t('portfolio.properties.form.livingArea') || 'Wohnfläche (m²)', type: 'number' },
    { section: sArea, key: 'usable_area_sqm', label: t('portfolio.properties.form.usableArea') || 'Nutzfläche (m²)', type: 'number' },
    { section: sArea, key: 'plot_area_sqm', label: t('portfolio.properties.form.plotArea') || 'Grundstücksfläche (m²)', type: 'number' },
    { section: sArea, key: 'ownership_share', label: t('portfolio.properties.form.ownershipShare') || 'Eigentumsanteil (%)', type: 'number' },
    { section: sFin, key: 'purchase_price', label: t('portfolio.properties.form.purchasePrice') || 'Kaufpreis (€)', type: 'number' },
    { section: sFin, key: 'purchase_date', label: t('portfolio.properties.form.purchaseDate') || 'Kaufdatum', type: 'date' },
    { section: sFin, key: 'market_value', label: t('portfolio.properties.form.marketValue') || 'Marktwert (€)', type: 'number' },
    { section: sFin, key: 'valuation_date', label: t('portfolio.properties.form.valuationDate') || 'Bewertungsdatum', type: 'date' },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/properties', data);
    } else {
      await api.put(`/properties/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('properties', 'portfolios', 'units', 'contracts');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.name}" ${t('modals.confirmDelete.body')}`)) return;
    try {
      await api.del(`/properties/${row.id}`);
    } catch (err) {
      toast.error(err.message);
      return;
    }
    refreshData();
    if (store) store.invalidateRelated('properties', 'portfolios', 'units', 'contracts');
  };

  if (loading || relatedSources.some(source => source.loading)) return <div className="page-loading">Lade Immobilien...</div>;
  const loadError = error || relatedSources.find(source => source.error)?.error;
  if (loadError) return <div className="page list-workspace"><h1 className="page-title">Immobilien</h1><div className="alert alert-error" role="alert">{loadError}</div><button className="btn btn-secondary" onClick={() => { refreshData(); relatedSources.filter(source => source.error).forEach(source => source.reload()); }}>Erneut laden</button></div>;

  return (
    <div className="page list-workspace">
      <header className="list-page-header">
        <div><p className="list-eyebrow">BESTAND</p><h1 className="page-title">{t('portfolio.properties.title') || 'Immobilien'}</h1><p className="list-description">Objekte, Vermietung und offene Arbeiten im Überblick.</p></div>
        {canWrite && <button className="btn btn-primary" onClick={() => setModal('create')}><PlusIcon size={18} /> Immobilie anlegen</button>}
      </header>

      {/* Summary cards */}
      <div className="kpi-row list-summary" aria-label="Bestandsübersicht">
        <div className="kpi">
          <div className="kpi-value">{totalCount}</div>
          <div className="kpi-label">Immobilien gesamt</div>
        </div>
        <div className="kpi">
          <div className="kpi-value">{activeCount}</div>
          <div className="kpi-label">Aktiv</div>
        </div>
        <div className="kpi">
          <div className="kpi-value">{vacancyCount}</div>
          <div className="kpi-label">Mit Leerstand</div>
        </div>
        <div className="kpi">
          <div className="kpi-value">{avgOccupancy}%</div>
          <div className="kpi-label">&Oslash; Vermietungsquote</div>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="filter-chips list-view-filters" role="group" aria-label="Immobilien filtern">
        {[
          { key: 'all', label: 'Alle' },
          { key: 'active', label: 'Aktiv' },
          { key: 'inactive', label: 'Inaktiv' },
          { key: 'vacancy', label: 'Mit Leerstand' },
          { key: 'open_maintenance', label: 'Mit offener Wartung' },
        ].map(f => (
          <button
            key={f.key}
            className={`btn btn-sm ${filter === f.key ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setFilter(f.key)}
            aria-pressed={filter === f.key}
          >{f.label}</button>
        ))}
      </div>

      <DataTable
        hideTitle
        title={t('portfolio.properties.title') || 'Immobilien'}
        columns={columns}
        data={filtered}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
        onRowClick={row => navigate(`/properties/${row.id}`)}
      />

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Immobilie erstellen' : 'Immobilie bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
