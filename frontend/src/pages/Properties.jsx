import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';

export default function Properties() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const store = useDataStore();

  const { items: portfolios } = useEntities('portfolios', '/portfolios');
  const { items: units } = useEntities('units', '/units');
  const { items: maintenance } = useEntities('maintenance', '/maintenance');

  const [properties, setProperties] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [filter, setFilter] = useState('all');

  const refreshData = () => {
    setLoading(true);
    api.get('/properties').catch(() => [])
      .then(data => setProperties(Array.isArray(data) ? data : []))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.get('/properties').catch(err => { console.warn('[Properties] load:', err.message); return []; })
      .then(data => { if (!cancelled) setProperties(Array.isArray(data) ? data : []); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

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
    { key: 'name', label: t('portfolio.properties.form.name') || 'Name', filterType: 'text' },
    { key: 'portfolio_name', label: 'Portfolio', filterType: 'text' },
    { key: 'property_type', label: t('portfolio.properties.form.type') || 'Typ', filterType: 'select' },
    { key: 'city', label: t('portfolio.properties.form.city') || 'Stadt', filterType: 'text' },
    { key: 'postal_code', label: t('portfolio.properties.form.postalCode') || 'PLZ', filterType: 'text' },
    { key: 'unit_count', label: 'Einheiten', type: 'number', align: 'right' },
    { key: 'occupancy_rate', label: 'Vermietung', type: 'number', align: 'right',
      render: v => {
        const color = v >= 80 ? 'var(--success)' : v >= 50 ? 'var(--warning)' : 'var(--danger)';
        return <span style={{ color, fontWeight: 600 }}>{v}%</span>;
      }},
    { key: 'total_rent', label: 'Kaltmiete (€)', type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
    { key: 'open_maintenance', label: 'Offene Wartung', type: 'number', align: 'right',
      render: v => v > 0 ? <span style={{ color: 'var(--warning)', fontWeight: 600 }}>{v}</span> : '0' },
    { key: 'year_built', label: t('portfolio.properties.form.yearBuilt') || 'Baujahr', type: 'number' },
    { key: 'living_area_sqm', label: t('portfolio.properties.form.livingArea') || 'Wohnfläche (m²)', type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toLocaleString('de-DE')} m²` : '—' },
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
      { value: 'active', label: t('tenantsContracts.contracts.status.active') || 'Aktiv' },
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
    await api.del(`/properties/${row.id}`);
    refreshData();
    if (store) store.invalidateRelated('properties', 'portfolios', 'units', 'contracts');
  };

  if (loading) return <div className="page-loading">Lade Immobilien...</div>;

  return (
    <div className="page">
      <h1 className="page-title">{t('portfolio.properties.title') || 'Immobilien'}</h1>

      {/* Summary cards */}
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{totalCount}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Gesamt</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--success)' }}>{activeCount}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Aktiv</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--warning)' }}>{vacancyCount}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Mit Leerstand</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: avgOccupancy >= 80 ? 'var(--success)' : 'var(--warning)' }}>{avgOccupancy}%</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>&Oslash; Vermietungsquote</div>
        </div>
      </div>

      {/* Filter tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
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
          >{f.label}</button>
        ))}
      </div>

      <DataTable
        title={t('portfolio.properties.title') || 'Immobilien'}
        columns={columns}
        data={filtered}
        onAdd={() => setModal('create')}
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
