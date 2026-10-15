import { useState, useEffect, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import { PartyLink } from '../features/partyWorkspace/PartyWorkspace';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';
import { formatArea, formatMoney, formatPercent } from '../utils/format';
import KpiAction from '../components/KpiAction';
import { occupancyMapOn } from '../utils/occupancy';

export default function Units() {
  const [params] = useSearchParams();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const toast = useToast();
  const store = useDataStore();
  const { items: properties } = useEntities('properties', '/properties');
  const contractState = useEntities('contracts', '/contracts');
  const contracts = contractState.items;
  const { items: tenants } = useEntities('tenants', '/tenants');
  const [units, setUnits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [modal, setModal] = useState(null);
  // values a New form starts with when opened from elsewhere (the property page's "Einheit anlegen")
  const [prefill, setPrefill] = useState(null);
  const [filter, setFilter] = useState(() => params.get('status') || params.get('filter') || 'all');
  const [drilldown, setDrilldown] = useState(0);
  const openSources = key => { setFilter(key); setDrilldown(value => value + 1); };

  const refreshData = () => {
    setLoading(true);
    setLoadError(null);
    api.list('/units')
      .then(data => { if (!Array.isArray(data)) throw new Error('Einheiten konnten nicht gelesen werden.'); setUnits(data); })
      .catch(error => setLoadError(error.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setLoadError(null);
    api.list('/units')
      .then(data => { if (!Array.isArray(data)) throw new Error('Einheiten konnten nicht gelesen werden.'); if (!cancelled) setUnits(data); })
      .catch(error => { if (!cancelled) setLoadError(error.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [attempt]);

  const propMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const tenantMap = Object.fromEntries(tenants.map(tn => [tn.id, tn.full_name]));

  const today = new Date().toLocaleDateString('sv-SE');
  const occupancy = useMemo(() => occupancyMapOn(units, contracts, today), [units, contracts, today]);

  // Build a map of unit_id -> true for units that have any contract
  const unitHasContract = useMemo(() => {
    const map = {};
    contracts.forEach(c => {
      if (c.unit_id) map[c.unit_id] = true;
    });
    return map;
  }, [contracts]);

  const enriched = units.map(u => {
    const coldRent = Number(u.cold_rent) || 0;
    const serviceCharge = Number(u.service_charge_advance) || 0;
    const heatingAdvance = Number(u.heating_advance) || 0;
    const warmRent = (u.cold_rent != null) ? coldRent + serviceCharge + heatingAdvance : null;
    return {
      ...u,
      status: occupancy[u.id].status,
      property_name: propMap[u.property_id] || '—',
      warm_rent: warmRent,
      tenant_id: occupancy[u.id].tenant_id,
      tenant_name: tenantMap[occupancy[u.id].tenant_id] || '—',
      vacant_since: occupancy[u.id].status === 'vacant' ? (u.created_at || '—') : null,
    };
  });

  const filtered = useMemo(() => {
    if (filter === 'all') return enriched;
    if (filter === 'occupied') return enriched.filter(u => u.status === 'occupied');
    if (filter === 'vacant') return enriched.filter(u => u.status === 'vacant');
    if (filter === 'reserved') return enriched.filter(u => u.status === 'reserved');
    if (filter === 'no_contract') return enriched.filter(u => !unitHasContract[u.id]);
    if (filter === 'no_area') return enriched.filter(u => !u.area_sqm || Number(u.area_sqm) === 0);
    if (filter === 'no_person_count') return enriched.filter(u => !u.person_count || Number(u.person_count) === 0);
    if (filter === 'with_rent') return enriched.filter(u => u.cold_rent != null && Number(u.cold_rent) > 0);
    return enriched;
  }, [enriched, filter, unitHasContract]);

  // Summary stats
  const totalCount = enriched.length;
  const occupiedCount = enriched.filter(u => u.status === 'occupied').length;
  const vacantCount = enriched.filter(u => u.status === 'vacant').length;
  const coldRents = enriched.filter(u => u.cold_rent != null && Number(u.cold_rent) > 0).map(u => Number(u.cold_rent));
  const avgColdRent = coldRents.length > 0 ? coldRents.reduce((s, v) => s + v, 0) / coldRents.length : 0;
  const occupancyRate = totalCount > 0 ? Math.round((occupiedCount / totalCount) * 100) : 0;

  const columns = [
    { key: 'label', label: t('units.list.columns.label') || 'Bezeichnung', filterType: 'text' },
    { key: 'property_name', label: 'Immobilie', filterType: 'text', link: 'property' },
    { key: 'unit_type', label: t('units.list.columns.type') || 'Typ', filterType: 'select' },
    { key: 'rooms', hidden: true, label: t('units.form.rooms') || 'Zimmer', type: 'number', align: 'right' },
    { key: 'floor', hidden: true, label: t('units.form.floor') || 'Etage' },
    { key: 'area_sqm', label: t('units.list.columns.area') || 'Fläche (m²)', type: 'number', align: 'right', filterType: 'numberRange',
      render: v => formatArea(v) },
    { key: 'cold_rent', label: t('units.list.columns.coldRent') || 'Kaltmiete (€)', type: 'number', sum: true, align: 'right', filterType: 'numberRange',
      render: v => formatMoney(v) },
    { key: 'warm_rent', hidden: true, label: 'Warmmiete (€)', type: 'number', align: 'right',
      render: v => formatMoney(v) },
    { key: 'person_count', hidden: true, label: t('units.form.personCount') || 'Personen', type: 'number', align: 'right' },
    { key: 'tenant_name', label: 'Mieter', filterType: 'text',
      render: (v, row) => row.tenant_id && v !== '—' ? <PartyLink tenantId={row.tenant_id}>{v}</PartyLink> : v },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
  ];

  const fields = [
    { key: 'property_id', label: t('portfolio.properties.form.name') || 'Immobilie', required: true, type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'label', label: t('units.list.columns.label') || 'Bezeichnung', required: true, placeholder: 'z.B. Wohnung 1 OG links' },
    { key: 'unit_type', label: t('units.list.columns.type') || 'Typ', required: true, type: 'select', default: 'Wohnung', options: [
      { value: 'Wohnung', label: t('units.types.apartment') || 'Wohnung' },
      { value: 'Gewerbe', label: t('units.types.commercial') || 'Gewerbe' },
      { value: 'Stellplatz', label: t('units.types.parking') || 'Stellplatz' },
      { value: 'Keller', label: t('units.types.basement') || 'Keller' },
      { value: 'Sonstiges', label: t('units.types.other') || 'Sonstiges' },
    ]},
    { key: 'area_sqm', label: t('units.list.columns.area') || 'Fläche (m²)', type: 'number' },
    { key: 'rooms', label: t('units.form.rooms') || 'Zimmer', type: 'number' },
    { key: 'person_count', label: t('units.form.personCount') || 'Personenzahl', type: 'number', placeholder: 'Bewohneranzahl für NK-Abrechnung' },
    { key: 'floor', label: t('units.form.floor') || 'Etage' },
    { key: 'cold_rent', label: t('units.list.columns.coldRent') || 'Kaltmiete (€)', type: 'number',
      hint: 'Vorgabe für neue Verträge. Laufende Mieten ändern Sie über Mietanpassungen.' },
    { key: 'service_charge_advance', label: t('units.form.serviceChargeAdvance') || 'NK-Vorauszahlung (€)', type: 'number' },
    { key: 'heating_advance', label: t('units.form.heatingAdvance') || 'Heizkosten-Vorauszahlung (€)', type: 'number' },
    { key: 'features', label: t('units.form.features') || 'Ausstattung', type: 'textarea', placeholder: 'z.B. Balkon, Einbauküche, Keller' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'select', default: 'vacant', options: [
      { value: 'vacant', label: t('units.status.vacant') || 'Leer' },
      { value: 'occupied', label: t('units.status.occupied') || 'Vermietet' },
      { value: 'reserved', label: t('units.status.reserved') || 'Reserviert' },
    ]},
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/units', data);
    } else {
      await api.put(`/units/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('units', 'properties', 'contracts');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.label}" ${t('modals.confirmDelete.body')}`)) return;
    try {
      await api.del(`/units/${row.id}`);
    } catch (err) {
      toast.error(err.message);
      return;
    }
    refreshData();
    if (store) store.invalidateRelated('units', 'properties', 'contracts');
  };

  // only the first load replaces the page; a reload keeps the table and an open form ("Speichern & weiteren")
  if ((loading && units.length === 0 || contractState.loading) && !modal) return <div className="page-loading">Lade Einheiten...</div>;
  if ((loadError || contractState.error) && !modal) return <div className="page"><div className="alert alert-error" role="alert">{loadError || contractState.error}<button type="button" className="btn btn-secondary" onClick={() => { setAttempt(value => value + 1); contractState.reload?.(); }}>Erneut laden</button></div></div>;

  return (
    <div className="page">
      <h1 className="page-title">{t('units.list.title') || 'Einheiten'}</h1>

      {/* Summary cards */}
      <div className="kpi-row">
        <KpiAction label="Gesamt" value={totalCount} onClick={() => openSources('all')} />
        <KpiAction label="Vermietet" value={occupiedCount} onClick={() => openSources('occupied')} />
        <KpiAction label="Leer" value={vacantCount} onClick={() => openSources('vacant')} />
        <KpiAction label="Ø Kaltmiete" value={formatMoney(avgColdRent)} onClick={() => openSources('with_rent')} />
        <KpiAction label="Vermietungsquote" value={formatPercent(occupancyRate)} onClick={() => openSources('occupied')} />
      </div>

      {/* Filter tabs */}
      <div className="filter-chips">
        {[
          { key: 'all', label: 'Alle' },
          { key: 'occupied', label: 'Vermietet' },
          { key: 'vacant', label: 'Leer' },
          { key: 'reserved', label: 'Reserviert' },
          { key: 'no_contract', label: 'Ohne Vertrag' },
          { key: 'no_area', label: 'Ohne Fläche' },
          { key: 'no_person_count', label: 'Ohne Personenzahl' },
          { key: 'with_rent', label: 'Mit Mietvorgabe' },
        ].map(f => (
          <button key={f.key} className={`btn btn-sm ${filter === f.key ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setFilter(f.key)}>
            {f.label}
          </button>
        ))}
      </div>

      <DataTable
        title={t('units.list.title') || 'Einheiten'}
        columns={columns}
        data={filtered}
        drilldownKey={drilldown}
        viewConfig={{ column_filters: { source_filter: filter } }}
        onApplyView={config => setFilter(config.column_filters?.source_filter || 'all')}
        onAdd={values => { setPrefill(values || null); setModal('create'); }}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
        onRowClick={row => navigate(`/units/${row.id}`)}
      />

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Einheit erstellen' : 'Einheit bearbeiten'}
          repeatKeep={['property_id', 'unit_type']}
          fields={fields}
          initial={modal === 'create' ? prefill : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
