import { useState, useEffect, useMemo, useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import { PartyLink } from '../features/partyWorkspace/PartyWorkspace';
import FormModal from '../components/FormModal';
import FileViewer from '../components/FileViewer';
import { resolveFileUrl } from '../features/partyWorkspace/files';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';
import { useCanWrite } from '../contexts/AuthContext';
import { formatDate, formatMoney } from '../utils/format';
import './bookingReview.css';

export default function Bookings() {
  const [params] = useSearchParams();
  const bookingId = params.get('booking_id');
  // A navigation starts a new editing/viewing session; old requests cannot own it.
  return <BookingsWorkspace key={bookingId === null ? 'list' : `booking:${bookingId}`} bookingId={bookingId} />;
}

function BookingsWorkspace({ bookingId }) {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const canWrite = useCanWrite();
  const store = useDataStore();
  const contractSource = useEntities('contracts', '/contracts');
  const { items: contracts } = contractSource;
  const { items: accounts } = useEntities('accounts', '/accounts');
  const { items: categories } = useEntities('categories', '/categories');
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');
  const { items: tenants } = useEntities('tenants', '/tenants');

  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [modal, setModal] = useState(null);
  const modalGeneration = useRef(0);
  const [filter, setFilter] = useState('all');
  const [allocations, setAllocations] = useState([]);
  const [allocationStatus, setAllocationStatus] = useState('loading');
  const [allocationError, setAllocationError] = useState(null);
  const [allocationAttempt, setAllocationAttempt] = useState(0);
  const [split, setSplit] = useState(null);
  const [splitError, setSplitError] = useState(null);
  const [splitSaving, setSplitSaving] = useState(false);
  const [selected, setSelected] = useState(null);
  const [selectedLoading, setSelectedLoading] = useState(bookingId !== null);
  const [selectedError, setSelectedError] = useState(null);
  const [selectedAttempt, setSelectedAttempt] = useState(0);
  const [viewer, setViewer] = useState(null);
  const [reversing, setReversing] = useState(false);
  const mounted = useRef(false);
  const splitRequest = useRef(null);
  const splitSession = useRef(null);

  const noneOpt = t('ui.form.none') || '— Keine —';
  const allocationReady = allocationStatus === 'ready';
  const canSplit = canWrite && allocationReady && !contractSource.loading && !contractSource.error;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const refreshData = () => setRefreshVersion(value => value + 1);
  const openModal = initial => setModal({ generation: ++modalGeneration.current, initial });
  // An old save may finish after cancellation and reopening; only its own session may close.
  const closeModal = session => setModal(current => current === session ? null : current);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    api.list('/bookings', { signal: controller.signal })
      .then(data => {
        if (controller.signal.aborted) return;
        if (!Array.isArray(data)) throw new Error('Die Buchungen konnten nicht gelesen werden.');
        setBookings(data);
      })
      .catch(err => { if (!controller.signal.aborted) setLoadError(err.message || 'Buchungen konnten nicht geladen werden.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refreshVersion]);

  useEffect(() => {
    const controller = new AbortController();
    setAllocationStatus('loading');
    setAllocationError(null);
    api.get('/bookings/allocations', { signal: controller.signal })
      .then(data => {
        if (controller.signal.aborted) return;
        if (!Array.isArray(data)) throw new Error('Die Zuordnungen konnten nicht gelesen werden.');
        setAllocations(data);
        setAllocationStatus('ready');
      })
      .catch(err => {
        if (controller.signal.aborted) return;
        setAllocationError(err.message || 'Zuordnungen konnten nicht geladen werden.');
        setAllocationStatus('error');
      });
    return () => controller.abort();
  }, [refreshVersion, allocationAttempt]);

  useEffect(() => {
    if (bookingId === null) return;
    const controller = new AbortController();
    setSelected(null);
    setSelectedError(null);
    if (!bookingId.trim()) {
      setSelectedError('Die Buchungs-ID ist ungültig.');
      setSelectedLoading(false);
      return () => controller.abort();
    }
    setSelectedLoading(true);
    api.get(`/bookings/${encodeURIComponent(bookingId)}`, { signal: controller.signal })
      .then(data => {
        if (controller.signal.aborted) return;
        if (!data || data.id !== bookingId) throw new Error('Die Antwort gehört nicht zur ausgewählten Buchung.');
        setSelected(data);
      })
      .catch(err => { if (!controller.signal.aborted) setSelectedError(err.message || 'Die ausgewählte Buchung konnte nicht geladen werden.'); })
      .finally(() => { if (!controller.signal.aborted) setSelectedLoading(false); });
    return () => controller.abort();
  }, [bookingId, refreshVersion, selectedAttempt]);

  // Lookup maps
  const accountMap = Object.fromEntries(accounts.map(a => [a.id, a.name]));
  const categoryMap = Object.fromEntries(categories.map(c => [c.id, c.name]));
  const propertyMap = Object.fromEntries(properties.map(p => [p.id, p.name]));
  const unitMap = Object.fromEntries(units.map(u => [u.id, u.label]));
  const tenantMap = Object.fromEntries(tenants.map(tn => [tn.id, tn.full_name]));
  const contractNumber = Object.fromEntries(contracts.map(c => [c.id, c.contract_number]));
  const allocationsByBooking = {};
  allocations.forEach(a => { (allocationsByBooking[a.booking_id] ||= []).push(a); });

  // Short label for the list (contract numbers), the amounts per contract as tooltip.
  const allocationInfo = (b) => {
    if (!b.tenant_id) return { label: '—', detail: '', unassigned: 0 };
    if (!allocationReady) return {
      label: allocationStatus === 'loading' ? 'Zuordnung wird geladen …' : 'Zuordnung nicht verfügbar',
      detail: '', unassigned: null,
    };
    const own = allocationsByBooking[b.id] || [];
    const rest = Math.round((Number(b.amount) - own.reduce((s, a) => s + Number(a.amount), 0)) * 100) / 100;
    const parts = own.map(a => `${contractNumber[a.contract_id] || '?'}: ${formatMoney(a.amount)}`);
    if (rest) parts.push(`nicht zugeordnet: ${formatMoney(rest)}`);
    return {
      label: own.map(a => contractNumber[a.contract_id] || '?').join(' + ') || '—',
      detail: parts.join('\n'),
      unassigned: rest,
    };
  };

  // Enriched data
  const enriched = bookings.map(b => ({
    ...b,
    ...(info => ({ allocation_label: info.label, allocation_detail: info.detail, unassigned: info.unassigned }))(allocationInfo(b)),
    account_name: accountMap[b.account_id] || '—',
    category_name: categoryMap[b.category_id] || '—',
    property_name: propertyMap[b.property_id] || '—',
    unit_label: unitMap[b.unit_id] || '—',
    tenant_name: tenantMap[b.tenant_id] || '—',
    has_receipt: resolveFileUrl(b.receipt_url) ? 'Vorhanden' : b.receipt_url?.trim() ? 'Ungültig' : 'Fehlt',
  }));

  // Filtered data
  const filtered = useMemo(() => {
    switch (filter) {
      case 'open': return enriched.filter(b => b.status === 'open');
      case 'unassigned': return enriched.filter(b => b.unassigned);
      case 'no_category': return enriched.filter(b => !b.category_id);
      case 'no_receipt': return enriched.filter(b => !resolveFileUrl(b.receipt_url));
      case 'income': return enriched.filter(b => Number(b.amount) > 0);
      case 'expense': return enriched.filter(b => Number(b.amount) < 0);
      default: return enriched;
    }
  }, [enriched, filter]);

  // Summary stats
  const totalCount = enriched.length;
  const totalIncome = enriched.filter(b => Number(b.amount) > 0).reduce((s, b) => s + Number(b.amount), 0);
  const totalExpense = enriched.filter(b => Number(b.amount) < 0).reduce((s, b) => s + Math.abs(Number(b.amount)), 0);
  const noCategory = enriched.filter(b => !b.category_id).length;
  const noReceipt = enriched.filter(b => !resolveFileUrl(b.receipt_url)).length;

  const receiptAction = row => resolveFileUrl(row.receipt_url)
    ? <button type="button" className="btn btn-sm btn-secondary" onClick={() => setViewer({ fileUrl: row.receipt_url, title: `Beleg: ${row.payment_text || formatDate(row.booking_date)}` })}>Beleg öffnen</button>
    : <span className="text-muted">{row.receipt_url?.trim() ? 'Belegadresse ist ungültig.' : 'Kein Beleg hinterlegt.'}</span>;
  const selectedAllocation = selected ? allocationInfo(selected) : null;

  const columns = [
    { key: 'booking_date', label: t('finance.bookings.form.date') || 'Datum', type: 'date', filterType: 'dateRange' },
    { key: 'account_name', hidden: true, label: t('finance.accounts.form.name') || 'Konto', filterType: 'text' },
    { key: 'category_name', label: t('finance.bookings.form.category') || 'Kategorie', filterType: 'text' },
    { key: 'amount', label: t('finance.bookings.form.amount') || 'Betrag (€)', type: 'number', align: 'right', filterType: 'numberRange',
      render: (v, row) => {
        const n = Number(v);
        const cls = n < 0 ? 'text-red' : 'text-green';
        return <span className="cell-inline"><span className={cls}>{formatMoney(n)}</span>
          {row.reverses_booking_id && <span className="badge badge-gray" title="Storno: zählt mit der stornierten Buchung zusammen">Storno</span>}</span>;
      }},
    { key: 'payment_text', label: t('finance.bookings.form.paymentText') || 'Buchungstext', filterType: 'text' },
    { key: 'property_name', label: t('portfolio.properties.form.name') || 'Immobilie', filterType: 'text' },
    { key: 'unit_label', label: t('units.list.columns.label') || 'Einheit', filterType: 'text', hidden: true },
    { key: 'tenant_name', label: t('tenantsContracts.tenants.title') || 'Mieter', filterType: 'text', hidden: true,
      render: (v, row) => row.tenant_id && v !== '—' ? <PartyLink tenantId={row.tenant_id}>{v}</PartyLink> : v },
    { key: 'allocation_label', label: 'Vertrag', filterType: 'text',
      render: (v, row) => (row.tenant_id
        ? (
          <span className="cell-inline" title={row.allocation_detail}>
            <span>{v}</span>
            {row.unassigned !== null && row.unassigned !== 0 && <span className="badge badge-yellow">offen {formatMoney(row.unassigned)}</span>}
            {canSplit && <button className="btn btn-sm btn-ghost btn-link" onClick={() => openSplit(row)}>Aufteilen</button>}
          </span>
        )
        : v) },
    { key: 'has_receipt', label: 'Beleg', filterType: 'text', render: (_value, row) => receiptAction(row) },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
  ];

  const fields = [
    { key: 'account_id', label: t('finance.accounts.form.name') || 'Konto', required: true, type: 'select',
      options: accounts.map(a => ({ value: a.id, label: a.name })) },
    { key: 'category_id', label: t('finance.bookings.form.category') || 'Kategorie', type: 'select',
      options: [{ value: '', label: noneOpt }, ...categories.map(c => ({ value: c.id, label: c.name }))] },
    { key: 'property_id', label: t('portfolio.properties.form.name') || 'Immobilie', type: 'select',
      options: [{ value: '', label: noneOpt }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'unit_id', label: t('units.list.columns.label') || 'Einheit', type: 'select',
      options: [{ value: '', label: noneOpt }, ...units.map(u => ({ value: u.id, label: u.label }))] },
    { key: 'tenant_id', label: t('tenantsContracts.tenants.title') || 'Mieter', type: 'select',
      options: [{ value: '', label: noneOpt }, ...tenants.map(tn => ({ value: tn.id, label: tn.full_name }))] },
    { key: 'booking_date', label: t('finance.bookings.form.bookingDate') || 'Buchungsdatum', type: 'date', required: true },
    { key: 'amount', label: t('finance.bookings.form.amount') || 'Betrag (€)', type: 'number', required: true },
    { key: 'payment_text', label: t('finance.bookings.form.paymentText') || 'Buchungstext' },
    { key: 'receipt_url', label: t('finance.bookings.form.receiptUrl') || 'Beleg-URL', placeholder: '/uploads/beleg.pdf' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: t('ui.filterChips.open') || 'Offen' },
      { value: 'matched', label: t('status.booking.matched') || 'Zugeordnet' },
      { value: 'booked', label: t('status.booking.booked') || 'Gebucht' },
    ]},
  ];

  const handleSave = async (data) => {
    if (!canWrite) return;
    if (modal.initial === 'create') {
      await api.post('/bookings', data);
    } else {
      await api.put(`/bookings/${encodeURIComponent(modal.initial.id)}`, data);
    }
    if (store) store.invalidateRelated('bookings', 'accounts', 'categories');
    if (mounted.current) refreshData();
  };

  const openSplit = (row) => {
    if (!canSplit) return;
    splitSession.current = {};
    setSplitError(null);
    const own = allocationsByBooking[row.id] || [];
    const tenantContracts = contracts.filter(c => c.tenant_id === row.tenant_id);
    setSplit({ booking: row, values: Object.fromEntries(tenantContracts.map(c => [c.id,
      String(own.find(a => a.contract_id === c.id)?.amount ?? '')])) });
  };

  const closeSplit = () => {
    splitSession.current = null;
    setSplit(null);
  };

  const saveSplit = async () => {
    if (!canSplit || splitRequest.current) return;
    const request = { session: splitSession.current };
    splitRequest.current = request;
    setSplitSaving(true);
    setSplitError(null);
    const items = Object.entries(split.values)
      .filter(([, v]) => v !== '' && Number(v) !== 0)
      .map(([contract_id, v]) => ({ contract_id, amount: Number(v) }));
    try {
      await api.put(`/bookings/${encodeURIComponent(split.booking.id)}/allocations`, items);
      if (store) store.invalidateRelated('bookings');
      if (!mounted.current) return;
      if (splitSession.current === request.session) closeSplit();
      refreshData();
      toast.success('Zuordnung gespeichert');
    } catch (err) {
      if (mounted.current && splitSession.current === request.session) setSplitError(err.message || 'Die Zuordnung konnte nicht gespeichert werden.');
    } finally {
      if (splitRequest.current === request) splitRequest.current = null;
      if (mounted.current) setSplitSaving(false);
    }
  };

  // A reversal (Storno) is a linked counter-booking: reports net both, nothing is deleted.
  const reverseBooking = async (row) => {
    if (!canWrite || reversing) return;
    if (!await confirm(`„${row.payment_text || formatDate(row.booking_date)}“ stornieren? Es wird eine Gegenbuchung über den `
      + 'noch nicht stornierten Betrag angelegt; beide zusammen zählen in allen Auswertungen null.')) return;
    setReversing(true);
    try {
      await api.post(`/bookings/${encodeURIComponent(row.id)}/reverse`, {});
      if (store) store.invalidateRelated('bookings', 'accounts');
      if (!mounted.current) return;
      refreshData();
      toast.success('Storno gebucht');
    } catch (err) {
      if (mounted.current) toast.error(err.message || 'Die Buchung konnte nicht storniert werden.');
    } finally {
      if (mounted.current) setReversing(false);
    }
  };

  const handleDelete = async (row) => {
    if (!canWrite) return;
    if (!await confirm(`"${row.payment_text || row.id}" ${t('modals.confirmDelete.body')}`)) return;
    try {
      await api.del(`/bookings/${encodeURIComponent(row.id)}`);
      if (store) store.invalidateRelated('bookings', 'accounts', 'categories');
      if (mounted.current) refreshData();
    } catch (err) {
      if (mounted.current) toast.error(err.message);
    }
  };

  return (
    <div className="page">
      <h1 className="page-title">{t('finance.bookings.title') || 'Buchungen'}</h1>

      {bookingId !== null && <section className="booking-selection" aria-label="Ausgewählte Buchung">
        <header className="booking-selection-header">
          <h2>Ausgewählte Buchung</h2>
          <Link className="btn btn-sm btn-secondary" to="/review">Zur Prüfliste</Link>
        </header>
        {selectedLoading && <p role="status">Die ausgewählte Buchung wird geladen …</p>}
        {selectedError && <div className="alert alert-error" role="alert">
          <p>Die ausgewählte Buchung konnte nicht geöffnet werden.</p><p>{selectedError}</p>
          <button type="button" className="btn btn-secondary" onClick={() => setSelectedAttempt(value => value + 1)}>Erneut laden</button>
        </div>}
        {selected && <>
          <h3>{selected.payment_text || 'Ohne Buchungstext'}</h3>
          <dl className="booking-selection-details">
            <div><dt>Datum</dt><dd>{formatDate(selected.booking_date)}</dd></div>
            <div><dt>Betrag</dt><dd>{formatMoney(selected.amount)}</dd></div>
            <div><dt>Konto</dt><dd>{accountMap[selected.account_id] || selected.account_id}</dd></div>
            <div><dt>Immobilie</dt><dd>{propertyMap[selected.property_id] || selected.property_id || 'Nicht zugeordnet'}</dd></div>
            <div><dt>Einheit</dt><dd>{unitMap[selected.unit_id] || selected.unit_id || 'Nicht zugeordnet'}</dd></div>
            <div><dt>Mieter</dt><dd>{selected.tenant_id ? tenantMap[selected.tenant_id] || selected.tenant_id : 'Noch nicht zugeordnet'}</dd></div>
            <div><dt>Kategorie</dt><dd>{categoryMap[selected.category_id] || (selected.category_id ? `Kategorie ${selected.category_id} (Name nicht verfügbar)` : 'Noch nicht zugeordnet')}</dd></div>
            <div><dt>Vertrag</dt><dd title={selectedAllocation.detail}>{selectedAllocation.label}</dd></div>
            {selected.reverses_booking_id && <div><dt>Storno von</dt><dd>
              <Link to={`/bookings?booking_id=${encodeURIComponent(selected.reverses_booking_id)}`}>Stornierte Buchung öffnen</Link>
            </dd></div>}
          </dl>
          {selectedAllocation.unassigned !== null && selectedAllocation.unassigned !== 0 && <p>Noch keinem Vertrag zugeordnet: {formatMoney(selectedAllocation.unassigned)}</p>}
          <div className="booking-selection-actions">
            {receiptAction(selected)}
            {canWrite && <button type="button" className="btn btn-sm btn-primary" onClick={() => openModal(selected)}>Bearbeiten</button>}
            {selected.tenant_id && canSplit && <button type="button" className="btn btn-sm btn-secondary" onClick={() => openSplit(selected)}>Aufteilen</button>}
            {canWrite && !selected.reverses_booking_id && <button type="button" className="btn btn-sm btn-secondary" disabled={reversing}
              onClick={() => reverseBooking(selected)}>Stornieren</button>}
          </div>
        </>}
      </section>}

      {allocationError && <div className="alert alert-error booking-load-error" role="alert">
        <p>Zahlungszuordnungen konnten nicht geladen werden. Der Zuordnungsstand ist unbekannt.</p><p>{allocationError}</p>
        <button type="button" className="btn btn-secondary" onClick={() => setAllocationAttempt(value => value + 1)}>Erneut laden</button>
      </div>}
      {contractSource.error && <div className="alert alert-error booking-load-error" role="alert">
        <p>Verträge konnten nicht geladen werden. Die Aufteilung ist vorübergehend nicht verfügbar.</p>
        <button type="button" className="btn btn-secondary" onClick={contractSource.reload}>Verträge erneut laden</button>
      </div>}
      {loading && <p role="status">Lade Buchungen...</p>}
      {loadError && <div className="alert alert-error booking-load-error" role="alert">
        <p>Buchungen konnten nicht geladen werden.</p><p>{loadError}</p>
        <button type="button" className="btn btn-secondary" onClick={refreshData}>Erneut laden</button>
      </div>}

      {!loading && !loadError && <>
      {/* Summary cards */}
      <div className="kpi-row">
        <div className="kpi">
          <div className="kpi-value">{totalCount}</div>
          <div className="kpi-label">Gesamt</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: 'var(--success)' }}>{formatMoney(totalIncome)}</div>
          <div className="kpi-label">Einnahmen</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: 'var(--danger)' }}>{formatMoney(totalExpense)}</div>
          <div className="kpi-label">Ausgaben</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: noCategory > 0 ? 'var(--warning)' : undefined }}>{noCategory}</div>
          <div className="kpi-label">Ohne Kategorie</div>
        </div>
        <div className="kpi">
          <div className="kpi-value" style={{ color: noReceipt > 0 ? 'var(--warning)' : undefined }}>{noReceipt}</div>
          <div className="kpi-label">Ohne nutzbaren Beleg</div>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="filter-chips">
        {[
          { key: 'all', label: 'Alle' },
          { key: 'open', label: 'Offen' },
          { key: 'unassigned', label: 'Nicht zugeordnet' },
          { key: 'no_category', label: 'Ohne Kategorie' },
          { key: 'no_receipt', label: 'Ohne Beleg' },
          { key: 'income', label: 'Einnahmen' },
          { key: 'expense', label: 'Ausgaben' },
        ].map(f => (
          <button
            key={f.key}
            className={`btn btn-sm ${filter === f.key ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setFilter(f.key)}
            disabled={f.key === 'unassigned' && !allocationReady}
          >{f.label}</button>
        ))}
      </div>

      {filter === 'unassigned' && !allocationReady ? <p>Der Zuordnungsstand ist derzeit nicht verfügbar.</p> : <DataTable
        title={t('finance.bookings.title') || 'Buchungen'}
        columns={columns}
        data={filtered}
        onAdd={() => openModal('create')}
        onEdit={openModal}
        onDelete={handleDelete}
      />}
      </>}

      {split && (
        <div className="modal-overlay" onClick={closeSplit} role="presentation">
          <div className="modal" role="dialog" aria-modal="true" aria-label="Zahlung aufteilen" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Zahlung aufteilen ({formatMoney(split.booking.amount)})</h2>
              <button onClick={closeSplit} className="btn-close" aria-label="Schließen">✕</button>
            </div>
            <div className="modal-body">
              {splitError && <div className="alert alert-error" role="alert">{splitError}</div>}
              {Object.keys(split.values).length === 0 && <p className="text-muted">Der Mieter hat keine Verträge.</p>}
              {Object.entries(split.values).map(([contractId, value]) => (
                <div key={contractId} className="form-group">
                  <label htmlFor={`split-${contractId}`}>Vertrag {contractNumber[contractId]} (€)</label>
                  <input id={`split-${contractId}`} type="number" step="0.01" value={value}
                    disabled={splitSaving && splitRequest.current?.session === splitSession.current}
                    onChange={e => setSplit(s => ({ ...s, values: { ...s.values, [contractId]: e.target.value } }))} />
                </div>
              ))}
              <p className="text-muted">Was keinem Vertrag zugeordnet wird, bleibt „nicht zugeordnet“.</p>
              <div className="modal-footer">
                <button className="btn btn-secondary" onClick={closeSplit}>Abbrechen</button>
                <button className="btn btn-primary" onClick={saveSplit} disabled={splitSaving || !canSplit}>{splitSaving ? 'Speichert …' : 'Speichern'}</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {modal && (
        <FormModal
          key={modal.generation}
          title={modal.initial === 'create' ? 'Buchung erstellen' : 'Buchung bearbeiten'}
          fields={fields}
          initial={modal.initial === 'create' ? null : modal.initial}
          onSave={handleSave}
          onClose={() => closeModal(modal)}
        />
      )}
      {viewer && <FileViewer fileUrl={viewer.fileUrl} title={viewer.title} onClose={() => setViewer(null)} />}
    </div>
  );
}
