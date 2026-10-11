import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import { PartyLink } from '../features/partyWorkspace/PartyWorkspace';
import FormModal from '../components/FormModal';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';
import { RentIcon } from '../components/Icons';
import { ClipboardCheck, FileCheck, Users } from 'lucide-react';
import HousingConfirmationDialog from '../features/housingConfirmation/HousingConfirmationDialog';
import HandoverProtocolsDialog from '../features/handoverProtocol/HandoverProtocolsDialog';
import { handoverText } from '../features/handoverProtocol/handoverProtocolText';
import OccupancyDialog from '../features/contracts/OccupancyDialog';
import { formatDate, formatMoney } from '../utils/format';

const RENT_MODEL_LABELS = { index: 'Indexmiete', stepped: 'Staffelmiete', fixed: 'Festmiete' };

function remainingDays(endDate) {
  if (!endDate) return null;
  const end = new Date(endDate);
  const today = new Date();
  return Math.ceil((end - today) / (1000 * 60 * 60 * 24));
}

const RENT_SOURCE_LABELS = { contract_start: 'Vertragsbeginn', adjustment: 'Mietanpassung', manual: 'Manuell' };

export default function Contracts() {
  const { t, locale } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const store = useDataStore();
  const propertyState = useEntities('properties', '/properties');
  const unitState = useEntities('units', '/units');
  const tenantState = useEntities('tenants_all', '/tenants?include_archived=true');
  const properties = propertyState.items;
  const units = unitState.items;
  const tenants = tenantState.items;
  const [contracts, setContracts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [filter, setFilter] = useState('all');
  const [rents, setRents] = useState({});
  const [history, setHistory] = useState(null);
  const [housing, setHousing] = useState(null);
  const [handover, setHandover] = useState(null);
  const [occupants, setOccupants] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const loadRef = useRef(null);

  const openHistory = async (row) => {
    try {
      setHistory({ contract: row, periods: await api.get(`/contracts/${row.id}/rent-periods`) });
    } catch (err) {
      toast.error(err.message);
    }
  };

  const refreshData = useCallback(async () => {
    loadRef.current?.abort();
    const request = new AbortController();
    loadRef.current = request;
    setLoading(true);
    setLoadError(null);
    const results = await Promise.allSettled([
      api.list('/contracts', { signal: request.signal }),
      api.get('/contracts/current-rents', { signal: request.signal }),
    ]);
    if (request.signal.aborted) return;
    const errors = [];
    if (results[0].status === 'fulfilled' && Array.isArray(results[0].value)) {
      setContracts(results[0].value);
    } else {
      errors.push(results[0].reason?.message || 'Der Server hat keine gültige Vertragsliste geliefert');
    }
    // Keep the last successfully loaded rents if the refresh fails.
    if (results[1].status === 'fulfilled' && results[1].value && typeof results[1].value === 'object' && !Array.isArray(results[1].value)) {
      setRents(results[1].value);
    } else {
      errors.push(results[1].reason?.message || 'Die Vertragsmieten konnten nicht geladen werden');
    }
    setLoadError(errors.length ? errors.join(' · ') : null);
    setLoading(false);
  }, []);

  useEffect(() => {
    refreshData();
    return () => loadRef.current?.abort();
  }, [refreshData]);

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
      cold_rent: rents[c.id]?.cold_rent,
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
    { key: 'property_name', hidden: true, label: 'Immobilie', filterType: 'text' },
    { key: 'unit_label', subKey: 'property_name', label: 'Einheit', filterType: 'text' },
    { key: 'tenant_name', label: 'Mieter', filterType: 'text',
      render: (v, row) => row.tenant_id ? <PartyLink tenantId={row.tenant_id}>{v === '—' ? 'Partei öffnen' : v}</PartyLink> : v },
    { key: 'cold_rent', label: 'Kaltmiete (€)', type: 'number', align: 'right',
      render: v => formatMoney(v) },
    { key: 'start_date', label: t('tenantsContracts.contracts.form.startDate') || 'Beginn', type: 'date', filterType: 'dateRange' },
    { key: 'end_date', label: t('tenantsContracts.contracts.form.endDate') || 'Ende', type: 'date', filterType: 'dateRange',
      render: (v, row) => {
        if (!v) return <span className="text-muted">unbefristet</span>;
        const soon = row.status === 'active' && row.remaining_days != null && row.remaining_days <= 90;
        return <span style={soon ? { color: 'var(--warning)', fontWeight: 600 } : undefined}
                     title={soon ? `noch ${row.remaining_days} Tage` : undefined}>{formatDate(v)}</span>;
      }},
    { key: 'remaining_days', hidden: true, label: 'Restlaufzeit', type: 'number', align: 'right',
      render: (v) => {
        if (v == null) return <span className="text-muted">unbefristet</span>;
        if (v < 0) return <span style={{ color: 'var(--danger)', fontWeight: 600 }}>abgelaufen</span>;
        const color = v <= 30 ? 'var(--danger)' : v <= 90 ? 'var(--warning)' : 'inherit';
        return <span style={{ color, fontWeight: v <= 90 ? 600 : 400 }}>{v} Tage</span>;
      }},
    { key: 'rent_model', hidden: true, label: 'Mietmodell', filterType: 'select',
      render: v => RENT_MODEL_LABELS[v] || v || '—' },
    { key: 'notice_period', hidden: true, label: 'Kündigungsfrist' },
    { key: 'deposit_amount', hidden: true, label: t('tenantsContracts.contracts.form.deposit') || 'Kaution (€)', type: 'number', align: 'right',
      render: v => formatMoney(v) },
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
      options: tenants.filter(tn => !tn.archived || (modal !== 'create' && tn.id === modal?.tenant_id))
        .map(tn => ({ value: tn.id, label: `${tn.full_name}${tn.archived ? ' (archiviert)' : ''}` })) },
    { key: 'start_date', label: t('tenantsContracts.contracts.form.startDate') || 'Vertragsbeginn', type: 'date', required: true },
    { key: 'end_date', label: t('tenantsContracts.contracts.form.endDate') || 'Vertragsende', type: 'date' },
    { key: 'deposit_amount', label: t('tenantsContracts.contracts.form.deposit') || 'Kaution (€)', type: 'number' },
    { key: 'persons', label: t('tenantsContracts.contracts.form.persons') || 'Personen im Haushalt', type: 'number',
      hint: t('tenantsContracts.contracts.form.personsHint') || 'für die Umlage nach Personen' },
    { key: 'index_rent', label: t('tenantsContracts.contracts.form.indexRent') || 'Mietanpassung', type: 'select', options: [
      { value: 'index', label: t('tenantsContracts.contracts.indexRentTypes.index') || 'Indexmiete' },
      { value: 'stepped', label: t('tenantsContracts.contracts.indexRentTypes.stepped') || 'Staffelmiete' },
      { value: 'fixed', label: t('tenantsContracts.contracts.indexRentTypes.fixed') || 'Festmiete' },
    ]},
    { key: 'service_charge_settlement', label: t('tenantsContracts.contracts.form.serviceChargeSettlement') || 'NK-Abrechnung', type: 'select', options: [
      { value: 'annual', label: t('tenantsContracts.contracts.settlement.annual') || 'Jährlich' },
      { value: 'monthly', label: t('tenantsContracts.contracts.settlement.monthly') || 'Monatlich' },
    ]},
    { key: 'notice_period', label: t('tenantsContracts.contracts.form.noticePeriod') || 'Kündigungsfrist', placeholder: 'z.B. 3 Monate' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'select', default: 'active', options: [
      { value: 'active', label: t('status.general.active') || 'Aktiv' },
      { value: 'terminated', label: t('status.contract.terminated') || 'Gekündigt' },
      { value: 'expired', label: t('status.contract.expired') || 'Ausgelaufen' },
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
    if (store) store.invalidateRelated('contracts', 'properties', 'units', 'tenants', 'tenants_all', 'deposits', 'receivables', 'rent_adjustments');
  };

  const handleDelete = async (row) => {
    if (!await confirm(`"${row.contract_number}" ${t('modals.confirmDelete.body')}`)) return;
    try {
      await api.del(`/contracts/${row.id}`);
    } catch (err) {
      toast.error(err.message);
      return;
    }
    refreshData();
    if (store) store.invalidateRelated('contracts', 'properties', 'units', 'tenants', 'tenants_all', 'deposits', 'receivables', 'rent_adjustments');
  };

  const lookupErrors = [propertyState.error, unitState.error, tenantState.error].filter(Boolean);
  const retry = () => {
    refreshData();
    if (propertyState.error) propertyState.reload();
    if (unitState.error) unitState.reload();
    if (tenantState.error) tenantState.reload();
  };
  if (loading && contracts.length === 0 && !loadError) return <div className="page-loading">Lade Verträge...</div>;

  return (
    <div className="page">
      <h1 className="page-title">{t('tenantsContracts.contracts.title') || 'Verträge'}</h1>
      {(loadError || lookupErrors.length > 0) && <div className="alert-error" role="alert">
        {[loadError, ...lookupErrors].filter(Boolean).join(' · ')}{' '}
        <button className="btn btn-secondary btn-sm" onClick={retry} disabled={loading}>Erneut laden</button>
      </div>}
      {loading && contracts.length > 0 && <p role="status">Verträge werden aktualisiert…</p>}

      {/* Summary cards */}
      <div className="kpi-row">
        <div className="kpi">
          <div className="kpi-value">{enriched.length}</div>
          <div className="kpi-label">Gesamt</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: 'var(--success)' }}>{totalActive}</div>
          <div className="kpi-label">Aktiv</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: 'var(--warning)' }}>{endingSoon}</div>
          <div className="kpi-label">Endet &lt; 90 Tage</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: 'var(--danger)' }}>{terminated}</div>
          <div className="kpi-label">Gekündigt</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: noDeposit > 0 ? 'var(--danger)' : 'inherit' }}>{noDeposit}</div>
          <div className="kpi-label">Ohne Kaution</div>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="filter-chips">
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

      {history && (
        <div className="modal-overlay" onClick={() => setHistory(null)} role="presentation">
          <div className="modal modal-wide" role="dialog" aria-modal="true" aria-label="Mietverlauf" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Mietverlauf {history.contract.contract_number}</h2>
              <button onClick={() => setHistory(null)} className="btn-close" aria-label="Schließen">✕</button>
            </div>
            <div className="modal-body">
              <table className="data-table">
                <thead><tr><th>Gültig ab</th><th className="text-right">Kaltmiete</th><th className="text-right">NK-Vorausz.</th><th className="text-right">Heizkosten</th><th>Herkunft</th></tr></thead>
                <tbody>
                  {history.periods.map(p => (
                    <tr key={p.id}>
                      <td>{formatDate(p.valid_from)}</td>
                      <td className="text-right td-num">{formatMoney(p.cold_rent)}</td>
                      <td className="text-right td-num">{formatMoney(p.service_charge_advance)}</td>
                      <td className="text-right td-num">{formatMoney(p.heating_advance)}</td>
                      <td>{RENT_SOURCE_LABELS[p.source] || p.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-muted" style={{ marginTop: '0.75rem' }}>
                Mieterhöhungen kommen über „Mietanpassungen → Anwenden“ in den Verlauf. Die Miete an der Einheit gilt nur für neue Verträge.
              </p>
            </div>
          </div>
        </div>
      )}

      <DataTable
        title={t('tenantsContracts.contracts.title') || 'Verträge'}
        columns={columns}
        data={filtered}
        onAdd={() => setModal('create')}
        onEdit={row => setModal(row)}
        onDelete={handleDelete}
        rowActions={() => [
          { label: 'Mietverlauf', icon: <RentIcon size={15} />, onClick: openHistory },
          { label: 'Wohnungsgeberbestätigung', icon: <FileCheck size={15} aria-hidden="true" />, onClick: row => setHousing(row.id) },
          { label: handoverText(locale, 'action'), icon: <ClipboardCheck size={15} aria-hidden="true" />, onClick: row => setHandover(row.id) },
          { label: t('tenantsContracts.contracts.occupants.action'), icon: <Users size={15} aria-hidden="true" />, onClick: row => setOccupants(row) },
        ]}
      />

      {occupants && <OccupancyDialog contract={occupants} onClose={() => setOccupants(null)} />}

      {handover && <HandoverProtocolsDialog contractId={handover} onClose={() => setHandover(null)}
        onChanged={() => store?.invalidateRelated('documents', 'handover_protocols')} />}

      {housing && <HousingConfirmationDialog contractId={housing} onClose={() => setHousing(null)} onPublished={() => store?.invalidateRelated('documents')} />}

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
