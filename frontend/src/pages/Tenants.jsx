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
import KpiAction from '../components/KpiAction';
import { currentContractsOn } from '../utils/occupancy';

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
  const focusId = searchParams.get('focus_id');
  const activeFilter = focusId ? 'all' : filter;
  const [drilldown, setDrilldown] = useState(0);
  const openSources = value => { setSearchParams(current => { const next = new URLSearchParams(current); next.delete('focus_id'); next.delete('suche'); return next; }); setFilter(value); setDrilldown(number => number + 1); };
  const [revision, setRevision] = useState(0);

  const refreshData = () => setRevision(value => value + 1);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.list('/tenants?include_archived=true', { signal: controller.signal })
      .then(data => { if (!Array.isArray(data)) throw new Error('Die Parteienquelle konnte nicht gelesen werden.'); if (!cancelled) setTenants(data); })
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
    for (const c of currentContractsOn(contracts)) {
      if (!c.tenant_id) continue;
      (map[c.tenant_id] ||= []).push(c);
    }
    for (const rows of Object.values(map)) rows.sort((a, b) => String(a.contract_number || a.id).localeCompare(String(b.contract_number || b.id), 'de'));
    return map;
  }, [contracts]);

  const enriched = tenants.map(tn => {
    const current = tenantContractMap[tn.id] || [];
    const activeContract = current[0];
    return {
      ...tn,
      property_name: activeContract ? [...new Set(current.map(contract => propMap[contract.property_id] || '—'))].join(' · ') : '—',
      unit_label: activeContract ? current.map(contract => unitMap[contract.unit_id] || '—').join(' · ') : '—',
      primary_unit_label: activeContract ? (unitMap[activeContract.unit_id] || '—') : '—',
      primary_property_name: activeContract ? (propMap[activeContract.property_id] || '—') : '—',
      // where the current contract is, for the links in the list (not tenant fields)
      link_unit_id: activeContract?.unit_id || null,
      link_property_id: activeContract?.property_id || null,
      contract_status: activeContract ? activeContract.status : 'kein Vertrag',
      current_contracts: current,
      has_sepa: tn.sepa_mandate ? '✓' : '—',
      payment_label: PAYMENT_LABELS[tn.payment_method] || tn.payment_method || '—',
    };
  });

  const filtered = useMemo(() => {
    if (focusId || filter === 'all') return enriched;
    if (filter === 'active') return enriched.filter(t => !t.archived);
    if (filter === 'archived') return enriched.filter(t => t.archived);
    if (filter === 'with_contract') return enriched.filter(t => !t.archived && t.current_contracts.length > 0);
    if (filter === 'with_sepa') return enriched.filter(t => !t.archived && t.sepa_mandate);
    if (filter === 'no_sepa') return enriched.filter(t => !t.archived && !t.sepa_mandate);
    if (filter === 'no_email') return enriched.filter(t => !t.archived && !t.email);
    return enriched;
  }, [enriched, filter, focusId]);

  // Summary stats
  const activeTenants = enriched.filter(t => !t.archived);
  const archivedCount = enriched.filter(t => t.archived).length;
  const withSepa = activeTenants.filter(t => t.sepa_mandate).length;
  const withContract = activeTenants.filter(t => t.current_contracts.length > 0).length;
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
    { key: 'unit_label', subKey: 'property_name', label: 'Einheit', filterType: 'text',
      render: (value, row) => <span className="cell-stack"><span>{row.link_unit_id ? <Link to={`/units/${encodeURIComponent(row.link_unit_id)}`}>{row.primary_unit_label}</Link> : value}</span>
        {row.link_property_id && <Link className="td-sub" to={`/properties/${encodeURIComponent(row.link_property_id)}`}>{row.primary_property_name}</Link>}
        {row.current_contracts.length > 1 && <button type="button" className="list-secondary-link list-additional-contracts" onClick={() => openParty(row.id)}
          aria-label={`Alle ${row.current_contracts.length} laufenden Verträge von ${row.full_name} ansehen`}>+ {row.current_contracts.length - 1} weitere</button>}</span>,
      link: { kind: 'unit', idKey: 'link_unit_id' }, subLink: { kind: 'property', idKey: 'link_property_id' } },
    { key: 'contract_status', label: 'Vertragsstatus', filterType: 'select',
      render: v => v === 'kein Vertrag' ? <span className="badge badge-gray">Kein aktiver Vertrag</span> : <StatusBadge status={v} /> },
    { key: 'email', label: 'E-Mail', filterType: 'text', render: value => value ? <a href={`mailto:${value}`}>{value}</a> : '—' },
    { key: 'phone', label: 'Telefon', render: value => value ? <a href={`tel:${value.replace(/[^+\d]/g, '')}`}>{value}</a> : '—' },
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

  // Saving refreshes both sources before FormModal has finished its private draft cleanup.
  if (!modal && (loading || relatedSources.some(source => source.loading))) return <div className="page-loading">{t('ui.table.loading')}</div>;
  const relatedError = relatedSources.find(source => source.error)?.error;
  if (relatedError && !modal) return <div className="page list-workspace"><h1 className="page-title">Mieter</h1><div className="alert alert-error" role="alert">{relatedError}</div><button className="btn btn-secondary" onClick={() => relatedSources.filter(source => source.error).forEach(source => source.reload())}>Erneut laden</button></div>;
  if (error && !tenants.length && !modal) return <div className="page"><h1 className="page-title">Mieter</h1><div className="alert alert-error" role="alert">{error}</div><button className="btn btn-secondary" onClick={refreshData}>Erneut laden</button></div>;

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
        <KpiAction label="Aktive Parteien" value={activeTenants.length} onClick={() => openSources('active')} />
        <KpiAction label="Archiviert" value={archivedCount} onClick={() => openSources('archived')} />
        <KpiAction label="Mit Vertrag" value={withContract} onClick={() => openSources('with_contract')} />
        <KpiAction label="Mit SEPA" value={withSepa} onClick={() => openSources('with_sepa')} />
        {noEmail > 0 && <KpiAction label="Ohne E-Mail" value={noEmail} onClick={() => openSources('no_email')} />}
      </div>

      {/* Filter tabs */}
      {focusId && <div className="alert" role="status">Direkt geöffnete Partei – auch archivierte Einträge bleiben sichtbar.
        <button type="button" className="btn btn-sm btn-secondary" onClick={() => openSources('all')}>Alle Parteien anzeigen</button>
      </div>}
      <div className="filter-chips list-view-filters" role="group" aria-label="Parteien filtern">
        {[
          { key: 'active', label: 'Aktiv' },
          { key: 'all', label: 'Alle' },
          { key: 'archived', label: 'Archiviert' },
          { key: 'with_contract', label: 'Mit Vertrag' },
          { key: 'with_sepa', label: 'Mit SEPA' },
          { key: 'no_sepa', label: 'Ohne SEPA' },
          { key: 'no_email', label: 'Ohne E-Mail' },
        ].map(f => (
          <button key={f.key} aria-pressed={activeFilter === f.key} className={`btn btn-sm ${activeFilter === f.key ? 'btn-primary' : 'btn-secondary'}`} onClick={() => openSources(f.key)}>
            {f.label}
          </button>
        ))}
      </div>

      <DataTable
        settingsKey="tenants-main"
        hideTitle
        title={`Mieter (${filtered.length})`}
        columns={columns}
        data={filtered}
        drilldownKey={drilldown}
        viewConfig={{ column_filters: { tenant_filter: filter } }}
        onApplyView={config => setFilter(['all', 'active', 'archived', 'with_contract', 'with_sepa', 'no_sepa', 'no_email'].includes(config.column_filters?.tenant_filter) ? config.column_filters.tenant_filter : 'active')}
        onAdd={() => setModal('create')}
        addLabel="Partei anlegen"
        hideAddButton
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
