import { useState, useEffect, useMemo } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';

const RENT_MODEL_LABELS = { index: 'Indexmiete', stepped: 'Staffelmiete', fixed: 'Festmiete' };

function remainingDays(endDate) {
  if (!endDate) return null;
  const end = new Date(endDate);
  const today = new Date();
  return Math.ceil((end - today) / (1000 * 60 * 60 * 24));
}

export default function Contracts() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');
  const { items: tenants } = useEntities('tenants', '/tenants');
  const [contracts, setContracts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [filter, setFilter] = useState('all');

  const refreshData = () => {
    setLoading(true);
    api.get('/contracts').catch(() => [])
      .then(data => setContracts(Array.isArray(data) ? data : []))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.get('/contracts').catch(() => [])
      .then(data => { if (!cancelled) setContracts(Array.isArray(data) ? data : []); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const propMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u]));
  const tenantMap = Object.fromEntries(tenants.map(tn => [tn.id, tn.full_name]));

  const enriched = contracts.map(c => {
    const unit = unitMap[c.unit_id];
    const remaining = remainingDays(c.end_date);
    return {
      ...c,
      property_name: propMap[c.property_id] || '—',
      unit_label: unit?.label || '—',
      tenant_name: tenantMap[c.tenant_id] || '—',
      cold_rent: unit?.cold_rent,
      rent_model: c.index_rent,
      remaining_days: remaining,
    };
  });

  const filtered = useMemo(() => {
    if (filter === 'all') return enriched;
    if (filter === 'active') return enriched.filter(c => c.status === 'active');
    if (filter === 'ending_soon') return enriched.filter(c => c.remaining_days != null && c.remaining_days > 0 && c.remaining_days <= 90 && c.status === 'active');
    if (filter === 'terminated') return enriched.filter(c => c.status === 'terminated');
    if (filter === 'draft') return enriched.filter(c => c.status === 'draft');
    if (filter === 'no_deposit') return enriched.filter(c => !c.deposit_amount || Number(c.deposit_amount) === 0);
    return enriched;
  }, [enriched, filter]);

  // Summary stats
  const totalActive = enriched.filter(c => c.status === 'active').length;
  const endingSoon = enriched.filter(c => c.remaining_days != null && c.remaining_days > 0 && c.remaining_days <= 90 && c.status === 'active').length;
  const terminated = enriched.filter(c => c.status === 'terminated').length;
  const noDeposit = enriched.filter(c => !c.deposit_amount || Number(c.deposit_amount) === 0).length;

  const columns = [
    { key: 'contract_number', label: t('tenantsContracts.contracts.form.contractNumber') || 'Vertragsnr.', filterType: 'text' },
    { key: 'property_name', label: 'Immobilie', filterType: 'text' },
    { key: 'unit_label', label: 'Einheit', filterType: 'text' },
    { key: 'tenant_name', label: 'Mieter', filterType: 'text' },
    { key: 'cold_rent', label: 'Kaltmiete (€)', type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
    { key: 'start_date', label: t('tenantsContracts.contracts.form.startDate') || 'Beginn', type: 'date', filterType: 'dateRange' },
    { key: 'end_date', label: t('tenantsContracts.contracts.form.endDate') || 'Ende', type: 'date', filterType: 'dateRange' },
    { key: 'remaining_days', label: 'Restlaufzeit', type: 'number', align: 'right',
      render: (v, row) => {
        if (v == null) return <span className="text-muted">unbefristet</span>;
        if (v < 0) return <span style={{ color: 'var(--danger)', fontWeight: 600 }}>abgelaufen</span>;
        const color = v <= 30 ? 'var(--danger)' : v <= 90 ? 'var(--warning)' : 'inherit';
        return <span style={{ color, fontWeight: v <= 90 ? 600 : 400 }}>{v} Tage</span>;
      }},
    { key: 'rent_model', label: 'Mietmodell', filterType: 'select',
      render: v => RENT_MODEL_LABELS[v] || v || '—' },
    { key: 'notice_period', label: 'Kündigungsfrist' },
    { key: 'deposit_amount', label: t('tenantsContracts.contracts.form.deposit') || 'Kaution (€)', type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
  ];

  const fields = [
    { key: 'contract_number', label: t('tenantsContracts.contracts.form.contractNumber') || 'Vertragsnr.', required: true, placeholder: 'z.B. MV-2024-001' },
    { key: 'property_id', label: t('portfolio.properties.form.name') || 'Immobilie', required: true, type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'unit_id', label: t('units.list.columns.label') || 'Einheit', required: true, type: 'select',
      options: units.map(u => ({ value: u.id, label: u.label })) },
    { key: 'tenant_id', label: t('tenantsContracts.tenants.title') || 'Mieter', required: true, type: 'select',
      options: tenants.map(tn => ({ value: tn.id, label: tn.full_name })) },
    { key: 'start_date', label: t('tenantsContracts.contracts.form.startDate') || 'Vertragsbeginn', type: 'date', required: true },
    { key: 'end_date', label: t('tenantsContracts.contracts.form.endDate') || 'Vertragsende', type: 'date' },
    { key: 'deposit_amount', label: t('tenantsContracts.contracts.form.deposit') || 'Kaution (€)', type: 'number' },
    { key: 'index_rent', label: t('tenantsContracts.contracts.form.indexRent') || 'Mietanpassung', type: 'select', options: [
      { value: 'index', label: t('tenantsContracts.contracts.indexRent.index') || 'Indexmiete' },
      { value: 'stepped', label: t('tenantsContracts.contracts.indexRent.stepped') || 'Staffelmiete' },
      { value: 'fixed', label: t('tenantsContracts.contracts.indexRent.fixed') || 'Festmiete' },
    ]},
    { key: 'service_charge_settlement', label: t('tenantsContracts.contracts.form.serviceChargeSettlement') || 'NK-Abrechnung', type: 'select', options: [
      { value: 'annual', label: t('tenantsContracts.contracts.settlement.annual') || 'Jährlich' },
      { value: 'monthly', label: t('tenantsContracts.contracts.settlement.monthly') || 'Monatlich' },
    ]},
    { key: 'notice_period', label: t('tenantsContracts.contracts.form.noticePeriod') || 'Kündigungsfrist', placeholder: 'z.B. 3 Monate' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'select', default: 'active', options: [
      { value: 'active', label: t('tenantsContracts.contracts.status.active') || 'Aktiv' },
      { value: 'terminated', label: t('tenantsContracts.contracts.status.terminated') || 'Gekündigt' },
      { value: 'expired', label: t('tenantsContracts.contracts.status.expired') || 'Ausgelaufen' },
      { value: 'draft', label: t('ui.filterChips.draft') || 'Entwurf' },
    ]},
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/contracts', data);
    } else {
      await api.put(`/contracts/${modal.id}`, data);
    }
    refreshData();
    if (store) store.invalidateRelated('contracts', 'properties', 'units', 'tenants', 'deposits', 'receivables', 'rent_adjustments');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.contract_number}" ${t('modals.confirmDelete.body')}`)) return;
    await api.del(`/contracts/${row.id}`);
    refreshData();
    if (store) store.invalidateRelated('contracts', 'properties', 'units', 'tenants', 'deposits', 'receivables', 'rent_adjustments');
  };

  if (loading) return <div className="page-loading">Lade Verträge...</div>;

  return (
    <div className="page">
      <h1 className="page-title">{t('tenantsContracts.contracts.title') || 'Verträge'}</h1>

      {/* Summary cards */}
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{enriched.length}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Gesamt</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--success)' }}>{totalActive}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Aktiv</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--warning)' }}>{endingSoon}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Endet &lt; 90 Tage</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--danger)' }}>{terminated}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Gekündigt</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: noDeposit > 0 ? 'var(--danger)' : 'inherit' }}>{noDeposit}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Ohne Kaution</div>
        </div>
      </div>

      {/* Filter tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        {[
          { key: 'all', label: 'Alle' },
          { key: 'active', label: 'Aktiv' },
          { key: 'ending_soon', label: 'Endet bald' },
          { key: 'terminated', label: 'Gekündigt' },
          { key: 'draft', label: 'Entwurf' },
          { key: 'no_deposit', label: 'Ohne Kaution' },
        ].map(f => (
          <button key={f.key} className={`btn btn-sm ${filter === f.key ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setFilter(f.key)}>
            {f.label}
          </button>
        ))}
      </div>

      <DataTable
        title={t('tenantsContracts.contracts.title') || 'Verträge'}
        columns={columns}
        data={filtered}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Vertrag erstellen' : 'Vertrag bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
