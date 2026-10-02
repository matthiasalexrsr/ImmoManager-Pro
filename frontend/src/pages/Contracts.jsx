import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown, Pencil, Trash2 } from 'lucide-react';
import { api } from '../api';
import { revisionOptions } from '../editRevision';
import { useAuth } from '../contexts/AuthContext';
import { useDataStore } from '../contexts/DataStoreContext';
import useWriteAccess from '../hooks/useWriteAccess';
import useContractWorkspacePage from '../hooks/useContractWorkspacePage';
import useContractChoices from '../hooks/useContractChoices';
import ContractEditor from '../components/ContractEditor';
import ContractLifecycle from '../components/ContractLifecycle';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { useTranslation } from '../i18n';
import '../components/SharedComponents.css';
import './Contracts.css';

const EMPTY_FILTERS = { search: '', property_id: '', unit_id: '', tenant_id: '', status: '',
  date_from: '', date_to: '', view: 'all' };
const SORT_KEYS = new Set(['contract_number', 'property_name', 'unit_label', 'tenant_name', 'start_date', 'end_date', 'deposit_amount', 'status']);
const DAY = 86400000;
const daysRemaining = (end, reference) => end && reference ? Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${reference}T00:00:00Z`)) / DAY) : null;
const csvCell = value => {
  // Imported names are plain text, never spreadsheet formulas. Numeric DTO
  // cells remain numeric; the receipt/source records are left untouched.
  const original = String(value ?? '');
  const text = typeof value === 'string' && /^\s*[=+\-@]/.test(original) ? `'${original}` : original;
  return /[;"\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};

function ReferenceFilter({ kind, value, propertyId, label, onChange }) {
  const { t } = useTranslation();
  const choices = useContractChoices(kind, value, label, propertyId);
  return <div className="contract-reference-filter"><label>{label}<select value={value} disabled={choices.disabled}
    onChange={event => onChange(event.target.value)}><option value="">{t('contractWorkspace.all')}</option>
    {choices.options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>{choices.hint}</div>;
}

function ContractWorkspace() {
  const { t, locale } = useTranslation();
  const label = key => t(`contractWorkspace.${key}`);
  const confirm = useConfirm();
  const store = useDataStore();
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [draftFilters, setDraftFilters] = useState(EMPTY_FILTERS);
  const [sort, setSort] = useState({ sort_by: 'contract_number', sort_order: 'asc' });
  const [pageSize, setPageSize] = useState(25);
  const [cursors, setCursors] = useState([null]);
  const [pageIndex, setPageIndex] = useState(0);
  const [generation, setGeneration] = useState(0);
  const [showReferences, setShowReferences] = useState(false);
  const [modal, setModal] = useState(null);
  const [lifecycle, setLifecycle] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const deletePending = useRef(false);
  const alive = useRef(true);
  const requests = useRef(new Set());
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/contracts', () => setModal(null));
  const result = useContractWorkspacePage({ ...filters, ...sort }, cursors[pageIndex], pageSize, generation);
  const money = new Intl.NumberFormat(locale || 'de-DE', { style: 'currency', currency: 'EUR' });
  const tableLabel = t('tenantsContracts.contracts.title');
  const headingRef = useRef(null);
  const workspaceRef = useRef(null);
  const returnFocus = useRef(null);
  useEffect(() => {
    const ownedRequests = requests.current;
    alive.current = true;
    return () => { alive.current = false; for (const request of ownedRequests) request.abort(); ownedRequests.clear(); };
  }, []);
  useEffect(() => {
    if (result.error?.statusCode === 401 || result.error?.statusCode === 403) {
      setModal(null); setLifecycle(null);
    }
    if (result.loading || !returnFocus.current) return;
    const target = [...(workspaceRef.current?.querySelectorAll('[data-workspace-focus]') || [])]
      .find(element => element.dataset.workspaceFocus === returnFocus.current && !element.disabled);
    (target || headingRef.current)?.focus(); returnFocus.current = null;
  }, [result.loading, result.error]);
  const firstPage = () => { setCursors([null]); setPageIndex(0); setGeneration(value => value + 1); };
  const refreshData = () => setGeneration(value => value + 1);
  const applyFilters = event => { event.preventDefault(); setFilters({ ...draftFilters }); setActionError(null); firstPage(); };
  const changeView = (status, view = 'all') => {
    setFilters(current => ({ ...current, status, view }));
    setDraftFilters(current => ({ ...current, status, view })); firstPage();
  };
  const changeSort = key => {
    if (!SORT_KEYS.has(key)) return;
    returnFocus.current = `sort-${key}`;
    setSort(current => ({ sort_by: key, sort_order: current.sort_by === key && current.sort_order === 'asc' ? 'desc' : 'asc' }));
    firstPage();
  };
  const mutate = async operation => {
    requireWrite();
    if (!alive.current) return;
    const request = new AbortController(); requests.current.add(request);
    try { await operation(request.signal); if (!alive.current || request.signal.aborted || !isAllowed()) return;
      refreshData(); store?.invalidateRelated('contracts', 'properties', 'units', 'tenants', 'deposits', 'receivables', 'rent_adjustments');
    } catch (error) {
      if (alive.current && !request.signal.aborted && [401, 403].includes(error.statusCode)) {
        setModal(null); setLifecycle(null); setActionError(error.message);
      }
      throw error;
    } finally { requests.current.delete(request); }
  };
  const handleSave = data => mutate(signal => modal === 'create' ? api.post('/contracts', data, { signal })
    // FormModal keeps the original payload revision until the user explicitly
    // reconciles a conflict. Do not override that reviewed token with the row.
    : api.put(`/contracts/${encodeURIComponent(modal.id)}`, data, { signal }));
  const handleDelete = async row => {
    if (deletePending.current || !isAllowed()) return;
    deletePending.current = true; setDeleting(true); setActionError(null);
    try {
      if (!await confirm(`"${row.contract_number}" ${t('modals.confirmDelete.body')}`) || !alive.current || !isAllowed()) return;
      await mutate(signal => api.del(`/contracts/${encodeURIComponent(row.id)}`, { ...revisionOptions(row), signal }));
    } catch (error) { if (alive.current && error.name !== 'AbortError') setActionError(error.message); }
    finally { deletePending.current = false; if (alive.current) setDeleting(false); }
  };
  const columns = [
    ['contract_number', t('tenantsContracts.contracts.number')], ['property_name', t('tenantsContracts.contracts.property')],
    ['unit_label', t('tenantsContracts.contracts.unit')], ['tenant_name', t('tenantsContracts.contracts.tenant')],
    ['unit_cold_rent', label('unitColdRent')], ['start_date', t('tenantsContracts.contracts.start')],
    ['end_date', label('endDate')], ['remaining_days', label('remaining')], ['index_rent', t('tenantsContracts.contracts.indexRent')],
    ['notice_period', t('tenantsContracts.contracts.noticePeriod')], ['deposit_amount', t('tenantsContracts.contracts.deposit')],
    ['status', t('tenantsContracts.contracts.status')],
  ];
  const renderCell = (row, key) => {
    if (key === 'status') return <StatusBadge status={row.status} />;
    if (key === 'unit_cold_rent' || key === 'deposit_amount') return row[key] == null ? '—' : money.format(row[key]);
    if (key === 'end_date') return row.end_date ?? label('unlimited');
    if (key === 'remaining_days') {
      const days = daysRemaining(row.end_date, result.referenceDate);
      return days == null ? label('unlimited') : days < 0 ? label('ended') : t(`contractWorkspace.${days === 1 ? 'day' : 'days'}`, { count: days });
    }
    if (key === 'index_rent' && ['index', 'stepped', 'fixed'].includes(row[key])) return label(`rent_${row[key]}`);
    return row[key] ?? '—';
  };
  const restartError = ['cursor_expired', 'cursor_invalid', 'cursor_filter_mismatch'].includes(result.error?.code);
  const sizeError = result.error?.code === 'page_size_exceeded';
  const active = result.items.filter(row => row.status === 'active').length;
  const ending = result.items.filter(row => row.status === 'active' && daysRemaining(row.end_date, result.referenceDate) > 0
    && daysRemaining(row.end_date, result.referenceDate) <= 90).length;
  const exportPage = () => {
    const rows = [columns.map(([, name]) => csvCell(name)).join(';'), ...result.items.map(row =>
      columns.map(([key]) => csvCell(key === 'remaining_days' ? daysRemaining(row.end_date, result.referenceDate) : row[key])).join(';'))];
    const url = URL.createObjectURL(new Blob(['\uFEFF', rows.join('\r\n')], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = `contracts-page-${result.referenceDate}.csv`;
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <div className="page contract-workspace" ref={workspaceRef}>
    <header className="contract-workspace-heading"><div><h1 className="page-title" tabIndex={-1} ref={headingRef}>{tableLabel}</h1>
      <p className="text-muted">{label('description')}</p></div>
      {canWrite && <button type="button" className="btn btn-primary" disabled={deleting || result.error?.statusCode === 403}
        onClick={() => { if (isAllowed()) setModal('create'); }}>{t('ui.buttons.new')}</button>}</header>
    {actionError && <p className="alert alert-error" role="alert">{actionError}</p>}
    <form className="panel contract-workspace-filters" onSubmit={applyFilters} onKeyDownCapture={event => {
      if (event.key === 'Enter' && event.target.name?.startsWith('lookup_contract_')) event.preventDefault();
    }}><div className="contract-workspace-filter-grid">
      <label>{label('search')}<input type="search" value={draftFilters.search}
        onChange={event => setDraftFilters(current => ({ ...current, search: event.target.value }))} /></label>
      <label>{t('tenantsContracts.contracts.status')}<select value={draftFilters.status}
        onChange={event => setDraftFilters(current => ({ ...current, status: event.target.value }))}>
        <option value="">{label('all')}</option>{['active', 'terminated', 'expired', 'draft'].map(value =>
          <option key={value} value={value}>{label(`status_${value}`)}</option>)}</select></label>
      <label>{label('dateFrom')}<input type="date" value={draftFilters.date_from} max={draftFilters.date_to || undefined}
        onChange={event => setDraftFilters(current => ({ ...current, date_from: event.target.value }))} /></label>
      <label>{label('dateTo')}<input type="date" value={draftFilters.date_to} min={draftFilters.date_from || undefined}
        onChange={event => setDraftFilters(current => ({ ...current, date_to: event.target.value }))} /></label>
    </div>
      <button type="button" className="btn btn-secondary" aria-expanded={showReferences}
        onClick={() => setShowReferences(value => !value)}>{label('references')}</button>
      {showReferences && <div className="contract-workspace-reference-grid">
        {['properties', 'units', 'tenants'].map((kind, index) => <ReferenceFilter key={kind} kind={kind}
          value={draftFilters[['property_id', 'unit_id', 'tenant_id'][index]]} propertyId={kind === 'units' ? draftFilters.property_id : ''}
          label={t(`tenantsContracts.contracts.${['property', 'unit', 'tenant'][index]}`)}
          onChange={value => setDraftFilters(current => ({ ...current, [['property_id', 'unit_id', 'tenant_id'][index]]: value,
            ...(kind === 'properties' ? { unit_id: '' } : {}) }))} />)}
      </div>}
      <div className="contract-workspace-filter-actions"><button type="submit" className="btn btn-primary">{label('apply')}</button>
        <button type="button" className="btn btn-secondary" onClick={() => { setFilters(EMPTY_FILTERS); setDraftFilters(EMPTY_FILTERS); firstPage(); }}>{label('reset')}</button></div>
    </form>
    <nav className="contract-workspace-views" aria-label={label('views')}>
      {[['', 'all', 'all'], ['active', 'all', 'status_active'], ['', 'ending_soon', 'endingSoon'],
        ['terminated', 'all', 'status_terminated'], ['draft', 'all', 'status_draft'], ['', 'no_deposit', 'noDeposit']].map(([status, view, key]) =>
        <button type="button" key={key} className={`btn btn-sm ${filters.status === status && filters.view === view ? 'btn-primary' : 'btn-secondary'}`}
          aria-pressed={filters.status === status && filters.view === view} onClick={() => changeView(status, view)}>{label(key)}</button>)}
    </nav>
    {result.loading && <p role="status">{t('ui.table.loading')}</p>}
    {result.error && <div role="alert" className="alert alert-error">
      {result.error.message === 'contractWorkspace.invalidResult' ? label('invalidResult') : result.error.message}
      <button type="button" className="btn btn-secondary" onClick={sizeError ? () => { setPageSize(1); firstPage(); } : restartError ? firstPage : refreshData}>
        {label(sizeError ? 'smallPage' : restartError ? 'restart' : 'retry')}</button></div>}
    {!result.loading && !result.error && <>
      <div className="contract-workspace-page-actions">
        <p role="status" className="contract-workspace-summary">{t('contractWorkspace.pageSummary', { count: result.items.length, active, ending })}</p>
        <button type="button" className="btn btn-secondary" disabled={!result.items.length} onClick={exportPage}>{label('exportPage')}</button>
      </div>
      <div className="data-table-wrapper shared-data-table"><div className="table-scroll" tabIndex={0} role="region" aria-label={tableLabel}>
        <table className="data-table" aria-label={tableLabel}><caption className="contract-workspace-caption">{label('unitRentHint')}</caption>
          <thead><tr>{columns.map(([key, name]) => <th key={key} scope="col"
            aria-sort={SORT_KEYS.has(key) ? sort.sort_by === key ? sort.sort_order === 'asc' ? 'ascending' : 'descending' : 'none' : undefined}>
            {SORT_KEYS.has(key) ? <button type="button" data-workspace-focus={`sort-${key}`} className="contract-workspace-sort" onClick={() => changeSort(key)} aria-label={t('contractWorkspace.sort', { column: name })}>
              {name}{sort.sort_by === key ? sort.sort_order === 'asc' ? <ArrowUp size={14} aria-hidden="true" /> : <ArrowDown size={14} aria-hidden="true" /> : <ArrowUpDown size={14} aria-hidden="true" />}</button> : name}
          </th>)}<th scope="col">{label('actions')}</th></tr></thead>
          <tbody>{result.items.map(row => <tr key={row.id}>{columns.map(([key]) => <td key={key}>{renderCell(row, key)}</td>)}
            <td><div className="contract-workspace-row-actions"><button type="button" className="btn btn-sm btn-secondary contract-lifecycle-row-action"
              data-lifecycle-contract={row.id} disabled={deleting}
              onClick={event => setLifecycle({ contract: row, opener: event.currentTarget })}>{t('contractLifecycle.open')}</button>
              {canWrite && <><button type="button" className="btn btn-sm btn-secondary" disabled={deleting} aria-label={`${label('edit')} ${row.contract_number}`}
                onClick={() => { if (isAllowed()) setModal(row); }}><Pencil size={14} aria-hidden="true" />{label('edit')}</button>
                <button type="button" className="btn btn-sm btn-danger" disabled={deleting} aria-label={`${label('delete')} ${row.contract_number}`}
                  onClick={() => handleDelete(row)}><Trash2 size={14} aria-hidden="true" />{label('delete')}</button></>}
            </div></td></tr>)}
            {!result.items.length && <tr><td colSpan={columns.length + 1}>{label('empty')}</td></tr>}</tbody>
        </table></div></div>
      <nav className="contract-workspace-pagination" aria-label={label('pagination')}>
        <button type="button" data-workspace-focus="previous" className="btn btn-secondary" disabled={!pageIndex} onClick={() => {
          returnFocus.current = 'previous'; setPageIndex(value => value - 1);
        }}>{label('previous')}</button>
        <span>{t('contractWorkspace.pageNumber', { page: pageIndex + 1 })}</span>
        <button type="button" data-workspace-focus="next" className="btn btn-secondary" disabled={!result.hasMore} onClick={() => {
          returnFocus.current = 'next';
          setCursors(current => [...current.slice(0, pageIndex + 1), result.nextCursor]); setPageIndex(value => value + 1);
        }}>{label('next')}</button>
        <label>{label('pageSize')}<select data-workspace-focus="page-size" value={pageSize} onChange={event => {
          returnFocus.current = 'page-size'; setPageSize(Number(event.target.value)); firstPage();
        }}>
          {[1, 10, 25, 100, 250, 500].map(size => <option key={size} value={size}>{size}</option>)}</select></label>
        {pageIndex > 0 && <button type="button" className="btn btn-secondary" onClick={() => { returnFocus.current = 'first'; firstPage(); }}>{label('firstPage')}</button>}
      </nav>
    </>}
    {/* Keep these mounted across parent reads/errors; accepted commands and
        unknown outcomes must retain their private draft/review/retry state. */}
    {modal && canWrite && <ContractEditor key={modal === 'create' ? 'create' : modal.id} initial={modal === 'create' ? null : modal}
      onSave={handleSave} onClose={() => { setModal(null); headingRef.current?.focus(); }} />}
    {lifecycle && <ContractLifecycle contract={lifecycle.contract} opener={lifecycle.opener} onClose={() => {
      setLifecycle(null); if (!lifecycle.opener?.isConnected) headingRef.current?.focus();
    }} onChanged={refreshData} />}
  </div>;
}

export default function Contracts() {
  const user = useAuth()?.user;
  if (!user?.id || user.is_active === false) return null;
  const actor = JSON.stringify([user.id, user.role, user.portfolio_access,
    [...(user.portfolio_ids || [])].sort(), [...(user.write_permissions || [])].sort()]);
  return <ContractWorkspace key={actor} />;
}
