import NotificationArrival from '../components/NotificationArrival';
import { useState, useEffect, useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import { PartyLink } from '../features/partyWorkspace/PartyWorkspace';
import FormModal from '../components/FormModal';
import KpiAction from '../components/KpiAction';
import FileViewer from '../components/FileViewer';
import { resolveFileUrl } from '../features/partyWorkspace/files';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';
import { useCanWrite } from '../contexts/AuthContext';
import { formatDate, formatMoney, plainLabel } from '../utils/format';
import './bookingReview.css';
import { Copy as CopyIcon } from 'lucide-react';
import { duplicateOf } from '../utils/duplicate';
import BankImport from '../components/BankImport';
import FinTSImport from '../components/FinTSImport';
import BankOriginal from '../components/BankOriginal';
import { bankOriginalPath } from '../utils/bankOriginal';
import { aktenwerkBulkAction, receiptExchangeId, useAktenwerkReady } from '../features/aktenwerk/aktenwerkApi';

const hasReceipt = value => Boolean(resolveFileUrl(value) || bankOriginalPath(value));

export default function Bookings() {
  const [params, setParams] = useSearchParams();
  const bookingId = params.get('booking_id');
  // /bookings?konto=<id>: the bookings of one account (from the account list), removable
  const accountId = params.get('konto');
  const sourceFilters = Object.fromEntries(['date_from', 'date_to', 'property_id', 'unit_id', 'portfolio_id', 'tenant_id', 'category_id', 'status', 'flow', 'owner_contact_id'].map(key => [key, params.get(key) || '']));
  const clearAccount = () => setParams(current => { const next = new URLSearchParams(current); next.delete('konto'); return next; });
  const applySourceFilters = config => setParams(current => {
    const next = new URLSearchParams(current);
    for (const key of Object.keys(sourceFilters)) {
      const value = key === 'flow' ? config.column_filters?.workflow_filter : config.column_filters?.[key];
      if (value && value !== 'all') next.set(key, value); else next.delete(key);
    }
    if (config.column_filters?.account_id) next.set('konto', config.column_filters.account_id); else next.delete('konto');
    return next;
  });
  // ?owner_contact_id=<id|none>: the bookings an owner has a part of, with that part
  const chooseOwner = value => setParams(current => {
    const next = new URLSearchParams(current);
    if (value) next.set('owner_contact_id', value); else next.delete('owner_contact_id');
    return next;
  });
  // A navigation starts a new editing/viewing session; old requests cannot own it.
  return <BookingsWorkspace key={bookingId === null ? 'list' : `booking:${bookingId}`} bookingId={bookingId}
    accountId={accountId} sourceFilters={sourceFilters} onApplySourceFilters={applySourceFilters} onClearAccount={clearAccount}
    onOwner={chooseOwner} initialSearch={params.get('suche') || ''} />;
}

function BookingsWorkspace({ bookingId, accountId, onClearAccount, sourceFilters, onApplySourceFilters, onOwner, initialSearch }) {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const canWrite = useCanWrite();
  const store = useDataStore();
  const aktenwerkReady = useAktenwerkReady();
  const contractSource = useEntities('contracts', '/contracts');
  const { items: contracts } = contractSource;
  const accountSource = useEntities('accounts', '/accounts');
  const { items: accounts } = accountSource;
  const categorySource = useEntities('categories', '/categories');
  const { items: categories } = categorySource;
  const { items: properties } = useEntities('properties', '/properties');
  const unitSource = useEntities('units', '/units');
  const { items: units } = unitSource;
  const { items: tenants } = useEntities('tenants', '/tenants');
  const { items: owners } = useEntities('owners', '/ownership-shares/owners');

  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [hasLoaded, setHasLoaded] = useState(false);
  const owner = sourceFilters.owner_contact_id;
  const [page, setPage] = useState(0), [pageSize, setPageSize] = useState(25);
  const [searchInput, setSearchInput] = useState(initialSearch), [search, setSearch] = useState(initialSearch);
  const [sortBy, setSortBy] = useState('booking_date'), [sortOrder, setSortOrder] = useState('desc');
  const [pageInfo, setPageInfo] = useState({ total: 0, summary: {} });
  const [columnDraft, setColumnDraft] = useState({}), [columnFilters, setColumnFilters] = useState({});
  const restoredPage = useRef(null), [viewGeneration, setViewGeneration] = useState(0);
  const [loadError, setLoadError] = useState(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [modal, setModal] = useState(null);
  const modalGeneration = useRef(0);
  const [filter, setFilter] = useState(sourceFilters.flow || 'all');
  useEffect(() => { setFilter(sourceFilters.flow || 'all'); }, [sourceFilters.flow]);
  const [drilldown, setDrilldown] = useState(0);
  const openSources = key => { setFilter(key); setDrilldown(value => value + 1); };
  const [allocations, setAllocations] = useState([]);
  const [reservedAmounts, setReservedAmounts] = useState({});
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
  const [selectedAllocations, setSelectedAllocations] = useState({ id: null, ready: false, error: '', allocations: [], reserved_amounts: {} });
  const [viewer, setViewer] = useState(null);
  const [reversing, setReversing] = useState(false);
  const mounted = useRef(false);
  const splitRequest = useRef(null);
  const splitSession = useRef(null);

  const noneOpt = t('ui.form.none') || '— Keine —';
  const basisLoading = categorySource.loading || (sourceFilters.property_id && unitSource.loading) || (sourceFilters.portfolio_id && accountSource.loading);
  const basisError = categorySource.error || (sourceFilters.property_id && unitSource.error) || (sourceFilters.portfolio_id && accountSource.error);
  const allocationReady = allocationStatus === 'ready';
  const splitRights = canWrite && !contractSource.loading && !contractSource.error;
  const canSplit = splitRights && allocationReady;
  const canSplitSelected = splitRights && selectedAllocations.ready;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const refreshData = () => setRefreshVersion(value => value + 1);
  const openModal = initial => setModal({ generation: ++modalGeneration.current, initial });
  // a new booking prefilled from an existing one (not its reversal link, receipt or state)
  const openDuplicate = row => setModal({ generation: ++modalGeneration.current, initial: 'create',
    prefill: duplicateOf(row, ['reverses_booking_id', 'receipt_url', 'status']) });
  // An old save may finish after cancellation and reopening; only its own session may close.
  const closeModal = session => setModal(current => current === session ? null : current);

  useEffect(() => { setSearchInput(initialSearch); }, [initialSearch]);
  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput), 250);
    return () => clearTimeout(timer);
  }, [searchInput]);
  const columnKey = JSON.stringify(columnDraft);
  useEffect(() => {
    const timer = setTimeout(() => setColumnFilters(JSON.parse(columnKey)), 250);
    return () => clearTimeout(timer);
  }, [columnKey]);
  const sourceKey = JSON.stringify(sourceFilters);
  const appliedColumnsKey = JSON.stringify(columnFilters);
  useEffect(() => { if (!owner && sortBy === 'owner_part') setSortBy('amount'); }, [owner, sortBy]);
  useEffect(() => {
    const restore = restoredPage.current;
    restoredPage.current = null;
    if (restore) {
      // The user may have paged while the saved view was being applied.
      setPage(current => current === restore.before ? restore.target : current);
    } else {
      setPage(0);
    }
  }, [sourceKey, accountId, search, sortBy, sortOrder, pageSize, filter, appliedColumnsKey, viewGeneration]);
  const query = new URLSearchParams(Object.fromEntries(Object.entries(sourceFilters).filter(([key, value]) => value && key !== 'flow')));
  if (accountId) query.set('account_id', accountId);
  query.set('search', search); query.set('flow', filter); query.set('sort_by', sortBy); query.set('sort_order', sortOrder);
  if (Object.keys(columnFilters).length) query.set('column_filters', appliedColumnsKey);
  const selectionQuery = query.toString();
  query.set('skip', String(page * pageSize)); query.set('limit', String(pageSize));
  const pageQuery = query.toString();

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    setAllocationStatus('loading'); setAllocationError(null);
    api.get(`/bookings/page?${pageQuery}`, { signal: controller.signal })
      .then(data => {
        if (controller.signal.aborted) return;
        if (!Array.isArray(data?.items) || !Number.isSafeInteger(data.total) || data.total < 0 || !data.summary
            || ['count', 'income', 'expense', 'withdrawal', 'contribution', 'no_category', 'no_receipt'].some(key => !Number.isFinite(data.summary[key])))
          throw new Error('Die Buchungsseite oder ihre vollständigen Summen konnten nicht gelesen werden.');
        setBookings(data.items); setPageInfo({ total: data.total, summary: data.summary }); setHasLoaded(true);
        if (Array.isArray(data.allocations) && data.reserved_amounts && !Array.isArray(data.reserved_amounts)
            && Object.values(data.reserved_amounts).every(value => Number.isFinite(value))) {
          setAllocations(data.allocations); setReservedAmounts(data.reserved_amounts); setAllocationStatus('ready');
        } else {
          setAllocations([]); setReservedAmounts({}); setAllocationStatus('error');
          setAllocationError('Die Zuordnungen konnten nicht gelesen werden.');
        }
        if (page * pageSize >= data.total && page > 0) setPage(Math.max(0, Math.ceil(data.total / pageSize) - 1));
      })
      .catch(err => { if (!controller.signal.aborted) { setLoadError(err.message || 'Buchungen konnten nicht geladen werden.'); setAllocationStatus('error'); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refreshVersion, pageQuery, allocationAttempt, page, pageSize]);

  useEffect(() => {
    const controller = new AbortController();
    if (bookingId === null || !bookingId.trim()) return undefined;
    setSelectedAllocations({ id: bookingId, ready: false, error: '', allocations: [], reserved_amounts: {} });
    api.get(`/bookings/${encodeURIComponent(bookingId)}/allocation-overview`, { signal: controller.signal })
      .then(data => {
        if (controller.signal.aborted) return;
        if (!Array.isArray(data?.allocations) || !data.reserved_amounts || Array.isArray(data.reserved_amounts)
            || typeof data.reserved_amounts !== 'object' || Object.values(data.reserved_amounts).some(v => !Number.isFinite(v)))
          throw new Error('Die Zuordnungen konnten nicht gelesen werden.');
        setSelectedAllocations({ id: bookingId, ready: true, error: '', ...data });
      })
      .catch(err => {
        if (controller.signal.aborted) return;
        setSelectedAllocations({ id: bookingId, ready: false, error: err.message || 'Zuordnungen konnten nicht geladen werden.', allocations: [], reserved_amounts: {} });
      });
    return () => controller.abort();
  }, [bookingId, refreshVersion, selectedAttempt]);

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
  const allAllocations = new Map(allocations.map(row => [row.id, row]));
  if (selectedAllocations.id === bookingId) selectedAllocations.allocations.forEach(row => allAllocations.set(row.id, row));
  allAllocations.forEach(a => { (allocationsByBooking[a.booking_id] ||= []).push(a); });
  const allReserved = { ...reservedAmounts, ...(selectedAllocations.id === bookingId ? selectedAllocations.reserved_amounts : {}) };

  // Short label for the list (contract numbers), the amounts per contract as tooltip.
  const allocationInfo = (b) => {
    if (!b.tenant_id) return { label: '—', detail: '', unassigned: 0 };
    if (!allocationReady || (b.id === bookingId && !selectedAllocations.ready)) return {
      label: allocationStatus === 'loading' || (b.id === bookingId && !selectedAllocations.error) ? 'Zuordnung wird geladen …' : 'Zuordnung nicht verfügbar',
      detail: '', unassigned: null,
    };
    const own = allocationsByBooking[b.id] || [];
    const reserved = Number(allReserved[b.id] || 0);
    const rest = (Math.round(Number(b.amount) * 100) - Math.round(reserved * 100)
      - own.reduce((s, a) => s + Math.round(Number(a.amount) * 100), 0)) / 100;
    const parts = own.map(a => `${contractNumber[a.contract_id] || '?'}: ${formatMoney(a.amount)}`);
    if (reserved) parts.push(`Kaution / Forderung: ${formatMoney(reserved)}`);
    if (rest) parts.push(`nicht zugeordnet: ${formatMoney(rest)}`);
    return {
      label: own.map(a => contractNumber[a.contract_id] || '?').join(' + ') || (reserved ? 'Kaution / Forderung' : '—'),
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
    has_receipt: hasReceipt(b.receipt_url) ? 'Vorhanden' : b.receipt_url?.trim() ? 'Ungültig' : 'Fehlt',
  }));
  const totalCount = pageInfo.summary.count || 0;
  const totalIncome = pageInfo.summary.income || 0;
  const totalExpense = pageInfo.summary.expense || 0;
  const totalWithdrawn = pageInfo.summary.withdrawal || 0;
  const totalContributed = pageInfo.summary.contribution || 0;
  const noCategory = pageInfo.summary.no_category || 0;
  const noReceipt = pageInfo.summary.no_receipt || 0;

  const receiptAction = row => bankOriginalPath(row.receipt_url) ? <BankOriginal value={row.receipt_url} /> : resolveFileUrl(row.receipt_url)
    ? <button type="button" className="btn btn-sm btn-secondary" onClick={() => setViewer({ fileUrl: row.receipt_url, title: `Beleg: ${row.payment_text || formatDate(row.booking_date)}` })}>Beleg öffnen</button>
    : <span className="text-muted">{row.receipt_url?.trim() ? 'Belegadresse ist ungültig.' : 'Kein Beleg hinterlegt.'}</span>;
  const selectedAllocation = selected ? allocationInfo(selected) : null;
  const allocation = row => (
    <span className="cell-inline" title={row.allocation_detail}>
      <span>{row.allocation_label}</span>
      {row.unassigned !== null && row.unassigned !== 0 && <span className="badge badge-yellow">offen {formatMoney(row.unassigned)}</span>}
      {canSplit && !row.reverses_booking_id && <button className="btn btn-sm btn-ghost btn-link" onClick={() => openSplit(row)}>Aufteilen</button>}
    </span>
  );

  const columns = [
    { key: 'booking_date', label: t('finance.bookings.form.date') || 'Datum', type: 'date', filterType: 'dateRange' },
    { key: 'account_name', hidden: true, label: t('finance.bookings.account') || 'Konto', filterType: 'text',
      render: (v, row) => (row.account_id ? <Link to={`/bookings?konto=${encodeURIComponent(row.account_id)}`} className="entity-link"
        onClick={e => e.stopPropagation()}>{v}</Link> : v) },
    { key: 'category_name', narrow: true, label: t('finance.bookings.form.category') || 'Kategorie', filterType: 'text' },
    { key: 'amount', label: t('finance.bookings.form.amount') || 'Betrag (€)', type: 'number', sum: true, align: 'right', filterType: 'numberRange',
      render: (v, row) => {
        const n = Number(v);
        const cls = n < 0 ? 'text-red' : 'text-green';
        return <span className="cell-inline"><span className={cls}>{formatMoney(n)}</span>
          {row.reverses_booking_id && <span className="badge badge-gray" title="Storno: zählt mit der stornierten Buchung zusammen">Storno</span>}</span>;
      }},
    ...(owner ? [{ key: 'owner_part', label: 'Anteil des Eigentümers (€)', type: 'number', sum: true, align: 'right', filterType: 'numberRange',
      render: v => <span className={Number(v) < 0 ? 'text-red' : 'text-green'}>{formatMoney(Number(v))}</span> }] : []),
    { key: 'payment_text', narrow: true, label: t('finance.bookings.form.paymentText') || 'Buchungstext', filterType: 'text' },
    { key: 'property_name', label: t('portfolio.properties.form.name') || 'Immobilie', filterType: 'text', link: 'property' },
    { key: 'unit_label', label: t('units.list.columns.label') || 'Einheit', filterType: 'text', hidden: true, link: 'unit' },
    // the payer: a click opens the party file (contracts, account, documents); beneath it the contract the payment
    // went to, so the list fits a monitor without a column of its own (that one can still be shown)
    { key: 'tenant_name', label: t('tenantsContracts.tenants.title') || 'Mieter', filterType: 'text',
      render: (v, row) => (row.tenant_id && v !== '—'
        ? <span className="cell-stack"><PartyLink tenantId={row.tenant_id}>{v}</PartyLink><span className="td-sub">{allocation(row)}</span></span>
        : v) },
    { key: 'allocation_label', hidden: true, label: 'Vertrag', filterType: 'text', render: (v, row) => (row.tenant_id ? allocation(row) : v) },
    { key: 'has_receipt', hidden: true, label: 'Beleg', filterType: 'text', render: (_value, row) => receiptAction(row) },
    { key: 'status', hidden: true, label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select',
      render: v => <StatusBadge status={v} /> },
  ];

  const fields = [
    { key: 'account_id', label: t('finance.bookings.account') || 'Konto', required: true, type: 'select',
      options: accounts.map(a => ({ value: a.id, label: a.name })) },
    { key: 'category_id', label: t('finance.bookings.form.category') || 'Kategorie', type: 'select',
      options: [{ value: '', label: noneOpt }, ...categories.map(c => ({ value: c.id, label: c.name }))] },
    { key: 'property_id', label: t('portfolio.properties.form.name') || 'Immobilie', type: 'select',
      options: [{ value: '', label: noneOpt }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'unit_id', label: t('units.list.columns.label') || 'Einheit', type: 'select',
      options: [{ value: '', label: noneOpt }, ...units.map(u => ({ value: u.id, label: u.label }))] },
    { key: 'tenant_id', label: t('tenantsContracts.tenants.title') || 'Mieter', type: 'select',
      options: [{ value: '', label: noneOpt }, ...tenants.map(tn => ({ value: tn.id, label: tn.full_name }))] },
    // money of one owner alone (a withdrawal, their own cost); otherwise the owners' shares split it
    ...(owners.length ? [{ key: 'owner_contact_id', label: 'Gehört allein dem Eigentümer', type: 'select',
      options: [{ value: '', label: 'Nach den Eigentumsanteilen' }, ...owners.map(owner => ({ value: owner.id, label: owner.name }))],
      hint: 'Nur für Geld, das einem Eigentümer allein gehört, z. B. eine Entnahme. Leer: nach den Anteilen an Einheit oder Objekt.' }] : []),
    { key: 'booking_date', label: t('finance.bookings.form.bookingDate') || 'Buchungsdatum', type: 'date', required: true },
    { key: 'amount', label: t('finance.bookings.form.amount') || 'Betrag (€)', type: 'number', required: true },
    { key: 'payment_text', label: t('finance.bookings.form.paymentText') || 'Buchungstext' },
    { key: 'receipt_url', label: t('finance.bookings.form.receiptUrl') || 'Beleg-URL', placeholder: '/uploads/beleg.pdf' },
    // § 11 Abs. 1 Satz 2 EStG: a regularly recurring payment within ten days around the turn of the year
    { key: 'tax_year', label: 'Steuerjahr (nur zum Jahreswechsel)', type: 'number', step: '1',
      hint: 'Leer: das Jahr des Buchungsdatums. Eine regelmäßige Zahlung vom 22.12. bis 10.01. (z. B. die Januarmiete am 29.12.) gehört steuerlich in das Jahr, für das sie gezahlt wird.' },
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

  const loadSplit = async (row, session, keepValues = false) => {
    setSplit(current => ({ ...current, loading: true, revision: null }));
    setSplitError(null);
    try {
      const data = await api.get(`/bank-imports/matching/${encodeURIComponent(row.id)}`);
      if (!mounted.current || splitSession.current !== session) return;
      if (!/^[a-f0-9]{64}$/.test(data.expected_revision) || !Array.isArray(data.allocations)
          || !Number.isFinite(data.budget_cents) || data.tenant_id !== row.tenant_id)
        throw new Error('Die Buchungszuordnung wurde geändert. Bitte die Buchung neu öffnen.');
      setSplit(current => ({ ...current, loading: false, revision: data.expected_revision,
        budget: data.budget_cents / 100, reserved: data.reserved_cents / 100,
        values: keepValues ? current.values : Object.fromEntries(Object.keys(current.values).map(id => [id,
          String(data.allocations.filter(a => a.contract_id === id).reduce((sum, a) => sum + Math.round(Number(a.amount) * 100), 0) / 100 || '')])) }));
    } catch (error) {
      if (mounted.current && splitSession.current === session) {
        setSplit(current => ({ ...current, loading: false }));
        setSplitError(error.message);
      }
    }
  };

  const openSplit = (row) => {
    if (!(row.id === selected?.id ? canSplitSelected : canSplit)) return;
    const session = {};
    splitSession.current = session;
    setSplitError(null);
    const own = allocationsByBooking[row.id] || [];
    const tenantContracts = contracts.filter(c => c.tenant_id === row.tenant_id);
    setSplit({ booking: row, loading: true, revision: null, values: Object.fromEntries(tenantContracts.map(c => [c.id,
      String(own.find(a => a.contract_id === c.id)?.amount ?? '')])) });
    void loadSplit(row, session);
  };

  const closeSplit = () => {
    splitSession.current = null;
    setSplit(null);
  };

  const saveSplit = async () => {
    if (!splitRights || splitRequest.current || split.loading || !split.revision) return;
    const request = { session: splitSession.current };
    splitRequest.current = request;
    setSplitSaving(true);
    setSplitError(null);
    const items = Object.entries(split.values)
      .filter(([, v]) => v !== '' && Number(v) !== 0)
      .map(([contract_id, v]) => ({ contract_id, amount: Number(v) }));
    try {
      if (items.some(item => !Number.isFinite(item.amount) || Math.abs(item.amount * 100 - Math.round(item.amount * 100)) > 0.000001))
        throw new Error('Bitte Teilbeträge mit höchstens zwei Nachkommastellen eingeben.');
      const payload = { expected_revision: split.revision, tenant_id: split.booking.tenant_id,
        allocations: Object.fromEntries(items.map(item => [item.contract_id, Math.round(item.amount * 100)])) };
      const signature = JSON.stringify(payload);
      if (request.session.signature !== signature) {
        request.session.signature = signature;
        request.session.key = crypto.randomUUID();
      }
      await api.post(`/bank-imports/matching/${encodeURIComponent(split.booking.id)}`,
        { ...payload, idempotency_key: request.session.key });
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
      + 'noch nicht stornierten Betrag angelegt; beide zusammen zählen in allen Auswertungen null.',
    { action: 'reverse' })) return;
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
    if (!await confirm(`"${row.payment_text || row.id}" ${t('modals.confirmDelete.body')}`, { action: 'delete' })) return;
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
      {canWrite && <BankImport accounts={accounts} onImported={() => {
        if (store) store.invalidateRelated('bookings', 'accounts', 'categories');
        refreshData();
      }} />}
      {canWrite && <FinTSImport accounts={accounts} />}

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
          <NotificationArrival record={selected} ready={!selectedLoading && !selectedError} />
          <h3>{selected.payment_text || 'Ohne Buchungstext'}</h3>
          <dl className="booking-selection-details">
            <div><dt>Datum</dt><dd>{formatDate(selected.booking_date)}</dd></div>
            <div><dt>Betrag</dt><dd>{formatMoney(selected.amount)}</dd></div>
            <div><dt>Konto</dt><dd>{accountMap[selected.account_id] || selected.account_id}</dd></div>
            <div><dt>Immobilie</dt><dd>{selected.property_id ? <Link to={`/properties/${encodeURIComponent(selected.property_id)}`}>{propertyMap[selected.property_id] || selected.property_id}</Link> : 'Nicht zugeordnet'}</dd></div>
            <div><dt>Einheit</dt><dd>{selected.unit_id ? <Link to={`/units/${encodeURIComponent(selected.unit_id)}`}>{unitMap[selected.unit_id] || selected.unit_id}</Link> : 'Nicht zugeordnet'}</dd></div>
            <div><dt>Mieter</dt><dd>{selected.tenant_id ? <PartyLink tenantId={selected.tenant_id}>{tenantMap[selected.tenant_id] || selected.tenant_id}</PartyLink> : 'Noch nicht zugeordnet'}</dd></div>
            <div><dt>Kategorie</dt><dd>{categoryMap[selected.category_id] || (selected.category_id ? `Kategorie ${selected.category_id} (Name nicht verfügbar)` : 'Noch nicht zugeordnet')}</dd></div>
            <div><dt>Vertrag</dt><dd title={selectedAllocation.detail}>{selectedAllocation.label}</dd></div>
            {selected.reverses_booking_id && <div><dt>Storno von</dt><dd>
              <Link to={`/bookings?booking_id=${encodeURIComponent(selected.reverses_booking_id)}`}>Stornierte Buchung öffnen</Link>
            </dd></div>}
          </dl>
          {selectedAllocation.unassigned !== null && selectedAllocation.unassigned !== 0 && <p>Noch keinem Vertrag zugeordnet: {formatMoney(selectedAllocation.unassigned)}</p>}
          <div className="booking-selection-actions">
            {receiptAction(selected)}
            {selected.tenant_id && <Link className="btn btn-sm btn-secondary" to={`/tenants/${encodeURIComponent(selected.tenant_id)}/account?as_of=${encodeURIComponent(selected.booking_date)}`}>Mieterkonto zum Buchungsdatum</Link>}
            {canWrite && <button type="button" className="btn btn-sm btn-primary" onClick={() => openModal(selected)}>Bearbeiten</button>}
            {selected.tenant_id && canSplitSelected && !selected.reverses_booking_id && <button type="button" className="btn btn-sm btn-secondary" onClick={() => openSplit(selected)}>Aufteilen</button>}
            {canWrite && !selected.reverses_booking_id && <button type="button" className="btn btn-sm btn-secondary" disabled={reversing}
              onClick={() => reverseBooking(selected)}>Stornieren</button>}
          </div>
        </>}
      </section>}

      {selected && selectedAllocations.error && <div className="alert alert-error" role="alert">
        <p>Zuordnungen konnten nicht geladen werden. {selectedAllocations.error}</p>
        <button type="button" className="btn btn-secondary" onClick={() => setSelectedAttempt(value => value + 1)}>Erneut laden</button>
      </div>}

      <div className="filter-chips" role="search" aria-label="Buchungen suchen und sortieren">
        <label>Buchungen durchsuchen<input type="search" value={searchInput} onChange={event => setSearchInput(event.target.value)} placeholder="Text, Partei, Objekt oder Vertrag" /></label>
        <label>Sortieren nach<select value={sortBy} onChange={event => setSortBy(event.target.value)}>
          {[['booking_date', 'Datum'], ['amount', 'Betrag'], ...(owner ? [['owner_part', 'Eigentümeranteil']] : []), ['payment_text', 'Buchungstext'], ['tenant_name', 'Mieter'], ['account_name', 'Konto'], ['category_name', 'Kategorie'], ['property_name', 'Immobilie'], ['unit_label', 'Einheit'], ['status', 'Status']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        <label>Reihenfolge<select value={sortOrder} onChange={event => setSortOrder(event.target.value)}><option value="desc">Absteigend</option><option value="asc">Aufsteigend</option></select></label>
      </div>
      <details><summary>Spaltenfilter</summary><div className="filter-chips">
        {columns.filter(column => column.filterType).map(column => {
          const label = plainLabel(column.label), value = column.key === 'status' ? sourceFilters.status : columnDraft[column.key];
          const change = next => {
            if (column.key === 'status') { onApplySourceFilters({ column_filters: { ...sourceFilters, account_id: accountId || '', workflow_filter: filter, status: next } }); return; }
            setColumnDraft(current => {
            const result = { ...current };
            if (Array.isArray(next) ? next.some(Boolean) : Boolean(next)) result[column.key] = next; else delete result[column.key];
            return result;
            });
          };
          if (['dateRange', 'numberRange'].includes(column.filterType)) return <span key={column.key}>
            <label>{label} ab<input aria-label={`${label} ab`} type={column.filterType === 'dateRange' ? 'date' : 'number'} step="any" value={value?.[0] || ''} onChange={event => change([event.target.value, value?.[1] || ''])} /></label>
            <label>{label} bis<input aria-label={`${label} bis`} type={column.filterType === 'dateRange' ? 'date' : 'number'} step="any" value={value?.[1] || ''} onChange={event => change([value?.[0] || '', event.target.value])} /></label>
          </span>;
          if (column.key === 'status') return <label key={column.key}>{label}<select aria-label={`${label} filtern`} value={value || ''} onChange={event => change(event.target.value)}>
            <option value="">Alle</option>{[...new Set(['open', 'matched', 'booked', ...(sourceFilters.status ? [sourceFilters.status] : [])])].map(option => <option key={option} value={option}>{option === 'open' ? 'Offen' : option === 'booked' ? 'Gebucht' : option === 'matched' ? 'Zugeordnet' : option}</option>)}
          </select></label>;
          return <label key={column.key}>{label}<input type="text" aria-label={`${label} filtern`} value={value || ''} onChange={event => change(event.target.value)} /></label>;
        })}
      </div></details>
      {Object.keys(columnFilters).length > 0 && <p role="status">Spaltenfilter sind aktiv. <button type="button" className="btn btn-sm btn-secondary" onClick={() => { setColumnDraft({}); setColumnFilters({}); }}>Spaltenfilter zurücksetzen</button></p>}

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

      {/* Keep view persistence mounted while another bounded page loads. A
          remount would restore the old server view over the new page/search.
          The hidden container removes stale controls from focus and access. */}
      {hasLoaded && <div hidden={loading || Boolean(loadError)} aria-busy={loading || undefined}>
      {Object.entries(sourceFilters).some(([key, value]) => value && key !== 'owner_contact_id') && <p role="status" className="draft-status">Quellenauswahl: {sourceFilters.date_from && `ab ${formatDate(sourceFilters.date_from)} `}{sourceFilters.date_to && `bis ${formatDate(sourceFilters.date_to)} `}{(sourceFilters.property_id || sourceFilters.unit_id || sourceFilters.portfolio_id || sourceFilters.tenant_id || sourceFilters.category_id || sourceFilters.status) && 'mit übernommener Objekt- und Vorgangsauswahl'}</p>}
      {/* Summary cards */}
      {basisLoading && <p role="status">Finanzgrundlage wird geladen …</p>}
      {basisError && <p role="alert">Die Finanzgrundlage konnte nicht vollständig geladen werden. Bitte die Ansicht erneut laden.</p>}
      {!basisLoading && !basisError && <div className="kpi-row">
        <KpiAction label="Gesamt" value={totalCount} onClick={() => openSources('all')} />
        <KpiAction label="Einnahmen" value={formatMoney(totalIncome)} color="var(--success)" onClick={() => openSources('income')} />
        <KpiAction label="Ausgaben" value={formatMoney(totalExpense)} color="var(--danger)" onClick={() => openSources('expense')} />
        {(totalWithdrawn !== 0 || totalContributed !== 0) && <>
          <KpiAction label="Entnahmen" value={formatMoney(totalWithdrawn)} onClick={() => openSources('withdrawal')} />
          <KpiAction label="Einlagen" value={formatMoney(totalContributed)} onClick={() => openSources('contribution')} />
        </>}
        <KpiAction label="Ohne Kategorie" value={noCategory} onClick={() => openSources('no_category')} />
        <KpiAction label="Ohne nutzbaren Beleg" value={noReceipt} onClick={() => openSources('no_receipt')} />
      </div>}

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
        {(owners.length > 0 || owner) && <label className="booking-owner-filter">Eigentümer{' '}
          <select value={owner} onChange={event => onOwner(event.target.value)}>
            <option value="">Alle (ganze Beträge)</option>
            {owners.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
            <option value="none">Ohne Eigentümer</option>
          </select></label>}
        {accountId && (
          <span className="filter-chip-active" role="status">
            Konto: {accountMap[accountId] || 'unbekannt'}
            <button type="button" className="btn btn-sm btn-ghost" onClick={onClearAccount} aria-label="Kontofilter entfernen">✕</button>
          </span>
        )}
      </div>

      {filter === 'unassigned' && !allocationReady && <p>Der Zuordnungsstand ist derzeit nicht verfügbar.</p>}
      <div hidden={filter === 'unassigned' && !allocationReady}><DataTable
        title={t('finance.bookings.title') || 'Buchungen'}
        columns={columns}
        data={enriched}
        serverPaged
        persistServerView={bookingId === null && !accountId && !initialSearch && !Object.values(sourceFilters).some(Boolean)}
        loadExportData={async visible => ({ ...(await api.getFile(`/bookings/page/export?${selectionQuery}&columns=${encodeURIComponent(visible.map(column => column.key).join(','))}`)), filename: 'Buchungen.csv' })}
        drilldownKey={drilldown}
        viewConfig={{ search, sort: { key: sortBy, direction: sortOrder }, page_size: pageSize, page_cursor: String(page), column_filters: { ...columnFilters, ...sourceFilters, account_id: accountId || '', workflow_filter: filter } }}
        onApplyView={config => {
          const restored = Object.fromEntries(Object.entries(config.column_filters || {}).filter(([key]) => !Object.hasOwn(sourceFilters, key) && !['account_id', 'workflow_filter'].includes(key) && columns.some(column => column.key === key && column.filterType)));
          const target = /^\d+$/.test(config.page_cursor || '') ? Number(config.page_cursor) : 0;
          restoredPage.current = { before: page, target };
          setViewGeneration(value => value + 1);
          setColumnDraft(restored); setColumnFilters(restored); setFilter(config.column_filters?.workflow_filter || 'all'); setSearchInput(config.search || ''); setSearch(config.search || '');
          setSortBy(config.sort?.key || 'booking_date'); setSortOrder(config.sort?.direction || 'desc'); setPageSize([10,25,50,100].includes(config.page_size) ? config.page_size : 25); onApplySourceFilters(config);
        }}
        onAdd={values => setModal({ generation: ++modalGeneration.current, initial: 'create', prefill: values || null })}
        onEdit={openModal}
        onDelete={handleDelete}
        rowActions={() => [{ label: 'Duplizieren', write: true, icon: <CopyIcon size={15} />, onClick: openDuplicate }]}
        rowName={row => row.payment_text || formatDate(row.booking_date)}
        // receipts (deductible ones above all) for the document management system
        bulkActions={aktenwerkReady ? [aktenwerkBulkAction(row => (resolveFileUrl(row.receipt_url) ? receiptExchangeId(row.id) : null), 'Belege an Aktenwerk')] : []}
      /></div>
      </div>}
      <nav className="table-footer table-footer-controls" aria-label="Buchungsseiten">
        <label className="inline-field">Zeilen pro Seite<select className="page-size-select" value={pageSize} onChange={event => setPageSize(Number(event.target.value))}>{[10, 25, 50, 100].map(size => <option key={size} value={size}>{size}</option>)}</select></label>
        <span role="status">{loading ? 'Buchungsseite wird geladen …' : loadError ? 'Buchungsseite nicht verfügbar' : `${pageInfo.total ? page * pageSize + 1 : 0}–${Math.min(page * pageSize + bookings.length, pageInfo.total)} von ${pageInfo.total} Buchungen`}</span>
        <button type="button" className="btn btn-secondary" disabled={!page || loading} onClick={() => setPage(value => value - 1)}>Zurück</button>
        <button type="button" className="btn btn-secondary" disabled={loading || (page + 1) * pageSize >= pageInfo.total} onClick={() => setPage(value => value + 1)}>Weiter</button>
      </nav>

      {split && (
        <div className="modal-overlay" onClick={closeSplit} role="presentation">
          <div className="modal" role="dialog" aria-modal="true" aria-label="Zahlung aufteilen" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Zahlung aufteilen ({formatMoney(split.booking.amount)})</h2>
              <button onClick={closeSplit} className="btn-close" aria-label="Schließen">✕</button>
            </div>
            <div className="modal-body">
              {splitError && <div className="alert alert-error" role="alert">{splitError}</div>}
              {split.loading && <p role="status">Aktueller Zuordnungsstand wird geladen …</p>}
              {!split.loading && split.revision && <p>Für Miete verfügbar: {formatMoney(split.budget)}
                {Boolean(split.reserved) && ` · Kaution / Forderung: ${formatMoney(split.reserved)}`}</p>}
              {splitError && <button type="button" className="btn btn-secondary btn-sm" disabled={split.loading || splitSaving}
                onClick={() => void loadSplit(split.booking, splitSession.current, true)}>Aktuellen Stand laden · Eingaben behalten</button>}
              {Object.keys(split.values).length === 0 && <p className="text-muted">Der Mieter hat keine Verträge.</p>}
              {Object.entries(split.values).map(([contractId, value]) => (
                <div key={contractId} className="form-group">
                  <label htmlFor={`split-${contractId}`}>Vertrag {contractNumber[contractId]} (€)</label>
                  <input id={`split-${contractId}`} type="number" step="0.01" value={value}
                    disabled={split.loading || (splitSaving && splitRequest.current?.session === splitSession.current)}
                    onChange={e => setSplit(s => ({ ...s, values: { ...s.values, [contractId]: e.target.value } }))} />
                </div>
              ))}
              <p className="text-muted">Was keinem Vertrag zugeordnet wird, bleibt „nicht zugeordnet“.</p>
              <div className="modal-footer">
                <button className="btn btn-secondary" onClick={closeSplit}>Abbrechen</button>
                <button className="btn btn-primary" onClick={saveSplit} disabled={splitSaving || split.loading || !split.revision || !splitRights}>{splitSaving ? 'Speichert …' : 'Speichern'}</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {modal && (
        <FormModal
          key={modal.generation}
          title={modal.initial === 'create' ? 'Buchung erstellen' : 'Buchung bearbeiten'}
          repeatKeep={['account_id', 'category_id', 'property_id', 'booking_date', 'status']}
          fields={fields}
          initial={modal.initial === 'create' ? (modal.prefill || null) : modal.initial}
          onSave={handleSave}
          onClose={() => closeModal(modal)}
        />
      )}
      {viewer && <FileViewer fileUrl={viewer.fileUrl} title={viewer.title} onClose={() => setViewer(null)} />}
    </div>
  );
}
