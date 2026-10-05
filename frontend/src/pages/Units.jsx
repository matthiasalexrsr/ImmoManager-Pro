import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';
import { formatArea, formatMoney, formatPercent } from '../utils/format';

export default function Units() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const toast = useToast();
  const store = useDataStore();
  const { items: properties } = useEntities('properties', '/properties');
  const { items: contracts } = useEntities('contracts', '/contracts');
  const { items: tenants } = useEntities('tenants', '/tenants');
  const [units, setUnits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [filter, setFilter] = useState('all');

  const refreshData = () => {
    setLoading(true);
    api.list('/units').catch(() => [])
      .then(data => setUnits(Array.isArray(data) ? data : []))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.list('/units').catch(() => [])
      .then(data => { if (!cancelled) setUnits(Array.isArray(data) ? data : []); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const propMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const tenantMap = Object.fromEntries(tenants.map(tn => [tn.id, tn.full_name]));

  // Build a map of unit_id -> tenant name for active contracts
  const unitTenantMap = useMemo(() => {
    const map = {};
    contracts.forEach(c => {
      if (c.status === 'active' && c.unit_id && c.tenant_id) {
        map[c.unit_id] = tenantMap[c.tenant_id] || '—';
      }
    });
    return map;
  }, [contracts, tenantMap]);

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
      property_name: propMap[u.property_id] || '—',
      warm_rent: warmRent,
      tenant_name: unitTenantMap[u.id] || '—',
      vacant_since: u.status === 'vacant' ? (u.created_at || '—') : null,
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
    { key: 'property_name', label: 'Immobilie', filterType: 'text' },
    { key: 'unit_type', label: t('units.list.columns.type') || 'Typ', filterType: 'select' },
    { key: 'rooms', hidden: true, label: t('units.form.rooms') || 'Zimmer', type: 'number', align: 'right' },
    { key: 'floor', hidden: true, label: t('units.form.floor') || 'Etage' },
    { key: 'area_sqm', label: t('units.list.columns.area') || 'Fläche (m²)', type: 'number', align: 'right', filterType: 'numberRange',
      render: v => formatArea(v) },
    { key: 'cold_rent', label: t('units.list.columns.coldRent') || 'Kaltmiete (€)', type: 'number', align: 'right', filterType: 'numberRange',
      render: v => formatMoney(v) },
    { key: 'warm_rent', hidden: true, label: 'Warmmiete (€)', type: 'number', align: 'right',
      render: v => formatMoney(v) },
    { key: 'person_count', hidden: true, label: t('units.form.personCount') || 'Personen', type: 'number', align: 'right' },
    { key: 'tenant_name', label: 'Mieter', filterType: 'text' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
  ];

  const fields = [
    { key: 'property_id', label: t('portfolio.properties.form.name') || 'Immobilie', required: true, type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'label', label: t('units.list.columns.label') || 'Bezeichnung', required: true, placeholder: 'z.B. Wohnung 1 OG links' },
    { key: 'unit_type', label: t('units.list.columns.type') || 'Typ', required: true, type: 'select', options: [
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
    { key: 'cold_rent', label: t('units.list.columns.coldRent') || 'Kaltmiete (€)', type: 'number', placeholder: 'Vorgabe für neue Verträge; laufende Mieten über Mietanpassungen' },
    { key: 'service_charge_advance', label: t('units.form.serviceChargeAdvance') || 'NK-Vorauszahlung (€)', type: 'number', placeholder: 'Vorgabe für neue Verträge; laufende Mieten über Mietanpassungen' },
    { key: 'heating_advance', label: t('units.form.heatingAdvance') || 'Heizkosten-Vorauszahlung (€)', type: 'number', placeholder: 'Vorgabe für neue Verträge; laufende Mieten über Mietanpassungen' },
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

  if (loading) return <div className="page-loading">Lade Einheiten...</div>;

  return (
    <div className="page">
      <h1 className="page-title">{t('units.list.title') || 'Einheiten'}</h1>

      {/* Summary cards */}
      <div className="kpi-row">
        <div className="kpi">
          <div className="kpi-value">{totalCount}</div>
          <div className="kpi-label">Gesamt</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: 'var(--success)' }}>{occupiedCount}</div>
          <div className="kpi-label">Vermietet</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: 'var(--warning)' }}>{vacantCount}</div>
          <div className="kpi-label">Leer</div>
        </div>
        <div className="kpi">
          <div className="kpi-value">{formatMoney(avgColdRent)}</div>
          <div className="kpi-label">Ø Kaltmiete</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: Number(occupancyRate) >= 80 ? 'var(--success)' : 'var(--warning)' }}>{formatPercent(occupancyRate)}</div>
          <div className="kpi-label">Vermietungsquote</div>
        </div>
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
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
        onRowClick={row => navigate(`/units/${row.id}`)}
      />

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Einheit erstellen' : 'Einheit bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
