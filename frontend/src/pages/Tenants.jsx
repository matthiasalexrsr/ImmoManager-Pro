import { useState, useEffect, useMemo } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';

const PAYMENT_LABELS = { bank_transfer: 'Überweisung', sepa_direct_debit: 'SEPA-Lastschrift', cash: 'Bar' };

export default function Tenants() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const { items: contracts } = useEntities('contracts', '/contracts');
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('active');

  const refreshData = () => {
    setLoading(true);
    api.get('/tenants?include_archived=true')
      .then(data => setTenants(data || []))
      .catch(() => setTenants([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    api.get('/tenants?include_archived=true')
      .then(data => { if (!cancelled) setTenants(data || []); })
      .catch(() => { if (!cancelled) setTenants([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const afterMutation = () => {
    refreshData();
    if (store) store.invalidateRelated('tenants', 'contracts');
  };

  // Build lookup maps
  const propMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u.label]));

  // Map tenant → active contract info
  const tenantContractMap = useMemo(() => {
    const map = {};
    for (const c of contracts) {
      if (c.status === 'active' && c.tenant_id) {
        map[c.tenant_id] = c;
      }
    }
    return map;
  }, [contracts]);

  const enriched = tenants.map(tn => {
    const activeContract = tenantContractMap[tn.id];
    return {
      ...tn,
      property_name: activeContract ? (propMap[activeContract.property_id] || '—') : '—',
      unit_label: activeContract ? (unitMap[activeContract.unit_id] || '—') : '—',
      contract_status: activeContract ? activeContract.status : 'kein Vertrag',
      has_sepa: tn.sepa_mandate ? '✓' : '—',
      payment_label: PAYMENT_LABELS[tn.payment_method] || tn.payment_method || '—',
    };
  });

  const filtered = useMemo(() => {
    if (filter === 'all') return enriched;
    if (filter === 'active') return enriched.filter(t => !t.archived);
    if (filter === 'archived') return enriched.filter(t => t.archived);
    if (filter === 'with_contract') return enriched.filter(t => t.contract_status === 'active');
    if (filter === 'no_sepa') return enriched.filter(t => !t.archived && !t.sepa_mandate);
    if (filter === 'no_email') return enriched.filter(t => !t.archived && !t.email);
    return enriched;
  }, [enriched, filter]);

  // Summary stats
  const activeTenants = enriched.filter(t => !t.archived);
  const archivedCount = enriched.filter(t => t.archived).length;
  const withSepa = activeTenants.filter(t => t.sepa_mandate).length;
  const withContract = activeTenants.filter(t => t.contract_status === 'active').length;
  const noEmail = activeTenants.filter(t => !t.email).length;

  const columns = [
    { key: 'full_name', label: 'Name', filterType: 'text' },
    { key: 'property_name', label: 'Immobilie', filterType: 'text' },
    { key: 'unit_label', label: 'Einheit', filterType: 'text' },
    { key: 'contract_status', label: 'Vertragsstatus', filterType: 'select',
      render: v => <StatusBadge status={v === 'kein Vertrag' ? 'warning' : v} /> },
    { key: 'email', label: 'E-Mail', filterType: 'text' },
    { key: 'phone', label: 'Telefon' },
    { key: 'city', label: 'Stadt', filterType: 'text' },
    { key: 'payment_label', label: 'Zahlungsart', filterType: 'select' },
    { key: 'has_sepa', label: 'SEPA', filterType: 'select' },
    { key: 'status_label', label: 'Archiv',
      render: (_, row) => row.archived
        ? <span className="badge badge-gray">Archiviert</span>
        : <span className="badge badge-green">Aktiv</span> },
  ];

  const fields = [
    { key: 'full_name', label: 'Vollständiger Name', required: true },
    { key: 'email', label: 'E-Mail', type: 'email' },
    { key: 'phone', label: 'Telefon' },
    { key: 'address_line', label: 'Straße' },
    { key: 'postal_code', label: 'PLZ' },
    { key: 'city', label: 'Stadt' },
    { key: 'country', label: 'Land', default: 'DE' },
    { key: 'payment_method', label: 'Zahlungsart', type: 'select', options: [
      { value: 'bank_transfer', label: 'Überweisung' },
      { value: 'sepa_direct_debit', label: 'SEPA-Lastschrift' },
      { value: 'cash', label: 'Bar' },
    ]},
    { key: 'sepa_mandate', label: 'SEPA-Mandat', placeholder: 'Mandatsreferenz' },
    { key: 'notes', label: 'Notizen', type: 'textarea' },
  ];

  const handleSave = async (data) => {
    if (modal === 'create') {
      await api.post('/tenants', data);
    } else {
      await api.put(`/tenants/${modal.id}`, data);
    }
    afterMutation();
  };

  const handleDelete = async (row) => {
    const name = row.full_name || row.id;
    if (!await confirm(`"${name}" ${t('modals.confirmDelete.body')}`)) return;
    setError(null);
    try {
      await api.del(`/tenants/${row.id}`);
      afterMutation();
    } catch (err) {
      setError(err.message || 'Löschen fehlgeschlagen');
    }
  };

  const handleArchiveToggle = async (tenant) => {
    const isArchived = tenant.archived;
    if (!isArchived) {
      if (!await confirm(`"${tenant.full_name}" ${t('pages.tenants.archiveConfirm') || 'archivieren? Der Mieter wird aus der aktiven Liste entfernt.'}`)) return;
    }
    setError(null);
    try {
      await api.patch(`/tenants/${tenant.id}/${isArchived ? 'unarchive' : 'archive'}`, {});
      afterMutation();
    } catch (err) {
      setError(err.message || 'Aktion fehlgeschlagen');
    }
  };

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;

  return (
    <div className="page">
      <h1 className="page-title">Mieter</h1>

      {error && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
          {error}
          <button onClick={() => setError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}

      {/* Summary cards */}
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--success)' }}>{activeTenants.length}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Aktiv</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{archivedCount}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Archiviert</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{withContract}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Mit Vertrag</div>
        </div>
        <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{withSepa}</div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>Mit SEPA</div>
        </div>
        {noEmail > 0 && (
          <div className="panel" style={{ padding: '0.75rem 1rem', minWidth: '140px', textAlign: 'center' }}>
            <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--warning)' }}>{noEmail}</div>
            <div className="text-muted" style={{ fontSize: '0.8rem' }}>Ohne E-Mail</div>
          </div>
        )}
      </div>

      {/* Filter tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        {[
          { key: 'active', label: 'Aktiv' },
          { key: 'all', label: 'Alle' },
          { key: 'archived', label: 'Archiviert' },
          { key: 'with_contract', label: 'Mit Vertrag' },
          { key: 'no_sepa', label: 'Ohne SEPA' },
          { key: 'no_email', label: 'Ohne E-Mail' },
        ].map(f => (
          <button key={f.key} className={`btn btn-sm ${filter === f.key ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setFilter(f.key)}>
            {f.label}
          </button>
        ))}
      </div>

      <DataTable
        title={`Mieter (${filtered.length})`}
        columns={columns}
        data={filtered}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
      />

      {/* Inline archive/unarchive actions per visible tenant */}
      {filtered.length > 0 && (
        <div style={{ marginTop: '0.5rem', display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
          {filtered.map(tn => (
            <button
              key={tn.id}
              className="btn btn-sm btn-secondary"
              onClick={() => handleArchiveToggle(tn)}
              title={tn.archived ? 'Wiederherstellen' : 'Archivieren'}
            >
              {tn.archived ? '↩' : '📦'} {tn.full_name}
            </button>
          ))}
        </div>
      )}

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Mieter erstellen' : 'Mieter bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
