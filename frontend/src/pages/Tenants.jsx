import { useState, useEffect, useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { PartyLink, usePartyWorkspace } from '../features/partyWorkspace/PartyWorkspace';
import { useCanWrite } from '../contexts/AuthContext';
import { DocumentIcon, PlusIcon } from '../components/Icons';
import { Archive, ArchiveRestore } from 'lucide-react';
import './ListWorkspace.css';

const PAYMENT_LABELS = { bank_transfer: 'Überweisung', sepa_direct_debit: 'SEPA-Lastschrift', cash: 'Bar' };

export default function Tenants() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const { openParty } = usePartyWorkspace();
  const canWrite = useCanWrite('/tenants');
  const [searchParams, setSearchParams] = useSearchParams();
  const store = useDataStore();
  const contractSource = useEntities('contracts', '/contracts');
  const propertySource = useEntities('properties', '/properties');
  const unitSource = useEntities('units', '/units');
  const { items: contracts } = contractSource;
  const { items: properties } = propertySource;
  const { items: units } = unitSource;
  const relatedSources = [contractSource, propertySource, unitSource];
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('active');
  const [revision, setRevision] = useState(0);

  const refreshData = () => setRevision(value => value + 1);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.list('/tenants?include_archived=true', { signal: controller.signal })
      .then(data => { if (!cancelled) setTenants(data || []); })
      .catch(err => { if (!cancelled) setError(err.message || 'Mieter konnten nicht geladen werden.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; controller.abort(); };
  }, [revision]);

  const editId = searchParams.get('edit');
  useEffect(() => {
    if (!editId || !canWrite) return;
    let cancelled = false;
    const controller = new AbortController();
    api.get(`/tenants/${encodeURIComponent(editId)}`, { signal: controller.signal })
      .then(data => { if (!cancelled) setModal(data); })
      .catch(err => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; controller.abort(); };
  }, [editId, canWrite]);

  const closeModal = () => {
    setModal(null);
    if (editId) {
      const next = new URLSearchParams(searchParams);
      next.delete('edit');
      setSearchParams(next, { replace: true });
    }
  };

  const afterMutation = () => {
    refreshData();
    if (store) store.invalidateRelated('tenants', 'tenants_all', 'contracts');
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
    { key: 'full_name', label: 'Name', filterType: 'text',
      render: (v, row) => (
        <span className="list-identity">
          <span className="list-avatar" aria-hidden="true">{String(v || '?').trim().split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase()}</span>
          <span className="list-identity-copy"><PartyLink tenantId={row.id}>{v}</PartyLink>
            <Link className="list-secondary-link" to={`/tenants/${encodeURIComponent(row.id)}/account`}>Mietkonto öffnen <span aria-hidden="true">↗</span></Link>
          </span>
        </span>
      ) },
    { key: 'property_name', hidden: true, label: 'Immobilie', filterType: 'text' },
    { key: 'unit_label', subKey: 'property_name', label: 'Einheit', filterType: 'text' },
    { key: 'contract_status', label: 'Vertragsstatus', filterType: 'select',
      render: v => v === 'kein Vertrag' ? <span className="badge badge-gray">Kein aktiver Vertrag</span> : <StatusBadge status={v} /> },
    { key: 'email', label: 'E-Mail', filterType: 'text' },
    { key: 'phone', label: 'Telefon' },
    { key: 'city', hidden: true, label: 'Stadt', filterType: 'text' },
    { key: 'payment_label', hidden: true, label: 'Zahlungsart', filterType: 'select' },
    { key: 'has_sepa', hidden: true, label: 'SEPA', filterType: 'select' },
    { key: 'status_label', hidden: true, label: 'Archiv',
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

  if (loading || relatedSources.some(source => source.loading)) return <div className="page-loading">{t('ui.table.loading')}</div>;
  const relatedError = relatedSources.find(source => source.error)?.error;
  if (relatedError) return <div className="page list-workspace"><h1 className="page-title">Mieter</h1><div className="alert alert-error" role="alert">{relatedError}</div><button className="btn btn-secondary" onClick={() => relatedSources.filter(source => source.error).forEach(source => source.reload())}>Erneut laden</button></div>;
  if (error && !tenants.length) return <div className="page"><h1 className="page-title">Mieter</h1><div className="alert alert-error" role="alert">{error}</div><button className="btn btn-secondary" onClick={refreshData}>Erneut laden</button></div>;

  return (
    <div className="page list-workspace">
      <header className="list-page-header">
        <div><p className="list-eyebrow">PARTEIEN</p><h1 className="page-title">Mieter</h1><p className="list-description">Alle Parteien mit ihren Kontakten, Mietkonten und Dokumenten.</p></div>
        {canWrite && <button className="btn btn-primary" onClick={() => setModal('create')}><PlusIcon size={18} /> Partei anlegen</button>}
      </header>

      {error && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: '1rem' }}>
          {error}
          <button className="btn btn-sm btn-secondary" onClick={refreshData}>Erneut laden</button>
          <button aria-label="Fehlermeldung schließen" onClick={() => setError(null)} style={{ marginLeft: '1rem', cursor: 'pointer' }}>✕</button>
        </div>
      )}

      {/* Summary cards */}
      <div className="kpi-row list-summary" aria-label="Parteienübersicht">
        <div className="kpi">
          <div className="kpi-value">{activeTenants.length}</div>
          <div className="kpi-label">Aktive Parteien</div>
        </div>
        <div className="kpi">
          <div className="kpi-value">{archivedCount}</div>
          <div className="kpi-label">Archiviert</div>
        </div>
        <div className="kpi">
          <div className="kpi-value">{withContract}</div>
          <div className="kpi-label">Mit Vertrag</div>
        </div>
        <div className="kpi">
          <div className="kpi-value">{withSepa}</div>
          <div className="kpi-label">Mit SEPA</div>
        </div>
        {noEmail > 0 && (
          <div className="kpi">
            <div className="kpi-value">{noEmail}</div>
            <div className="kpi-label">Ohne E-Mail</div>
          </div>
        )}
      </div>

      {/* Filter tabs */}
      <div className="filter-chips list-view-filters" role="group" aria-label="Parteien filtern">
        {[
          { key: 'active', label: 'Aktiv' },
          { key: 'all', label: 'Alle' },
          { key: 'archived', label: 'Archiviert' },
          { key: 'with_contract', label: 'Mit Vertrag' },
          { key: 'no_sepa', label: 'Ohne SEPA' },
          { key: 'no_email', label: 'Ohne E-Mail' },
        ].map(f => (
          <button key={f.key} aria-pressed={filter === f.key} className={`btn btn-sm ${filter === f.key ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setFilter(f.key)}>
            {f.label}
          </button>
        ))}
      </div>

      <DataTable
        hideTitle
        title={`Mieter (${filtered.length})`}
        columns={columns}
        data={filtered}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
        rowActions={row => [
          { label: 'Dokumente der Partei', icon: <DocumentIcon size={16} />, onClick: () => openParty(row.id, { tab: 'documents' }) },
          { label: row.archived ? 'Wiederherstellen' : 'Archivieren', icon: row.archived ? <ArchiveRestore size={16} aria-hidden="true" /> : <Archive size={16} aria-hidden="true" />, write: true, onClick: handleArchiveToggle },
        ]}
      />

      {modal && (
        <FormModal
          title={modal === 'create' ? 'Mieter erstellen' : 'Mieter bearbeiten'}
          fields={fields}
          initial={modal === 'create' ? null : modal}
          onSave={handleSave}
          onClose={closeModal}
        />
      )}
    </div>
  );
}
