import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { revisionOptions } from '../editRevision';
import { useTranslation } from '../i18n';
import { useDataStore } from '../contexts/DataStoreContext';
import useWriteAccess from '../hooks/useWriteAccess';
import useBookingPage, { bookingFilterParams } from '../hooks/useBookingPage';
import useBookingChoices from '../hooks/useBookingChoices';
import BookingEditor from '../components/BookingEditor';
import StatusBadge from '../components/StatusBadge';
import { useConfirm } from '../components/ConfirmDialog';
import { saveBlob, streamBookingCsv } from '../utils/bookingCsv';
import '../components/SharedComponents.css';
import './Bookings.css';

const emptyFilters = { search: '', date_from: '', date_to: '', status: '', view: 'all', account_id: '', property_id: '', tenant_id: '' };
const advancedKinds = ['accounts', 'properties', 'tenants'];

function ReferenceFilter({ kind, value, label, onChange }) {
  const { t } = useTranslation();
  const choices = useBookingChoices(kind, value, label);
  return <div className="booking-reference-filter"><label>{label}<select value={value} disabled={choices.disabled}
    onChange={event => onChange(event.target.value)}><option value="">{t('bookingPages.all')}</option>
    {choices.options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>{choices.hint}</div>;
}

export default function Bookings() {
  const { t, locale } = useTranslation();
  const confirm = useConfirm();
  const store = useDataStore();
  const [filters, setFilters] = useState(emptyFilters);
  const [draft, setDraft] = useState(emptyFilters);
  const [pageSize, setPageSize] = useState(25);
  const [history, setHistory] = useState([null]);
  const [pageIndex, setPageIndex] = useState(0);
  const [revision, setRevision] = useState(0);
  const [modal, setModal] = useState(null);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/bookings', () => setModal(null));
  const [actionError, setActionError] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState(false);
  const exportController = useRef(null);
  const [extraColumns, setExtraColumns] = useState([]);
  const result = useBookingPage(filters, history[pageIndex], pageSize, revision);
  const money = new Intl.NumberFormat(locale || 'de-DE', { style: 'currency', currency: 'EUR' });
  const reload = () => setRevision(value => value + 1);
  const restart = () => { setHistory([null]); setPageIndex(0); setPageSize(25); reload(); };
  useEffect(() => () => exportController.current?.abort(), []);
  const applyFilters = event => {
    event.preventDefault();
    setFilters({ ...draft });
    setHistory([null]);
    setPageIndex(0);
    setExported(false);
    setActionError(null);
  };
  const handleSave = async data => {
    requireWrite();
    if (modal === 'create') await api.post('/bookings', data);
    else await api.put(`/bookings/${modal.id}`, data);
    setModal(null);
    restart();
    store?.invalidateRelated('bookings', 'accounts', 'categories');
  };
  const handleDelete = async row => {
    if (!isAllowed() || !await confirm(`"${row.payment_text || row.id}" ${t('modals.confirmDelete.body')}`)) return;
    if (!isAllowed()) return;
    setActionError(null);
    try {
      await api.del(`/bookings/${row.id}`, revisionOptions(row));
      restart();
      store?.invalidateRelated('bookings', 'accounts', 'categories');
    } catch (error) { setActionError(error.message); }
  };
  const exportCsv = async direct => {
    if (exportController.current) return;
    const controller = new AbortController();
    exportController.current = controller;
    setExporting(true); setExported(false); setActionError(null);
    const path = `/bookings/export.csv?${bookingFilterParams(filters)}`;
    try {
      if (direct) await streamBookingCsv(path, { signal: controller.signal });
      else saveBlob(await api.getBlob(path, { signal: controller.signal }));
      if (!controller.signal.aborted) setExported(true);
    } catch (error) {
      if (error.name !== 'AbortError' && !controller.signal.aborted) setActionError(error.message);
    } finally {
      exportController.current = null;
      if (!controller.signal.aborted) setExporting(false);
    }
  };
  const optional = [
    ['unit_label', t('units.list.columns.label')], ['tenant_name', t('tenantsContracts.tenants.title')], ['receipt_url', t('finance.bookings.form.receiptUrl')],
  ];
  const columns = [
    ['booking_date', t('finance.bookings.form.date')], ['account_name', t('bookingPages.account')],
    ['category_name', t('finance.bookings.form.category')], ['amount', t('finance.bookings.form.amount')],
    ['payment_text', t('finance.bookings.form.paymentText')], ['property_name', t('bookingPages.property')],
    ...optional.filter(([key]) => extraColumns.includes(key)), ['status', t('ui.form.status')],
  ];
  const errorMessage = result.error?.message === 'bookingPages.invalidResult' ? t(result.error.message) : result.error?.message;
  const restartError = ['cursor_expired', 'cursor_invalid', 'cursor_filter_mismatch', 'page_size_exceeded'].includes(result.error?.code);
  const income = result.items.reduce((sum, item) => sum + Math.max(0, Number(item.amount)), 0);
  const expense = result.items.reduce((sum, item) => sum + Math.max(0, -Number(item.amount)), 0);

  return <div className="page booking-page">
    <div className="booking-heading"><div><h1 className="page-title">{t('finance.bookings.title')}</h1>
      <p className="text-muted">{t('bookingPages.description')}</p></div>
      {canWrite && <button className="btn btn-primary" disabled={result.loading || Boolean(result.error)}
        onClick={() => { if (isAllowed()) setModal('create'); }}>{t('ui.buttons.new')}</button>}</div>
    {actionError && <div className="alert alert-error" role="alert">{actionError}</div>}
    <form className="panel booking-filters" onSubmit={applyFilters} onKeyDownCapture={event => {
      if (event.key === 'Enter' && event.target.name?.startsWith('lookup_')) event.preventDefault();
    }}>
      <div className="booking-filter-grid">
        <label>{t('bookingPages.search')}<input type="search" maxLength={200} value={draft.search}
          onChange={event => setDraft(current => ({ ...current, search: event.target.value }))} /></label>
        <label>{t('bookingPages.dateFrom')}<input type="date" value={draft.date_from} max={draft.date_to || undefined}
          onChange={event => setDraft(current => ({ ...current, date_from: event.target.value }))} /></label>
        <label>{t('bookingPages.dateTo')}<input type="date" value={draft.date_to} min={draft.date_from || undefined}
          onChange={event => setDraft(current => ({ ...current, date_to: event.target.value }))} /></label>
        <label>{t('ui.form.status')}<select value={draft.status} onChange={event => setDraft(current => ({ ...current, status: event.target.value }))}>
          <option value="">{t('bookingPages.all')}</option><option value="open">{t('ui.filterChips.open')}</option>
          <option value="matched">{t('finance.bookings.statusOptions.matched')}</option><option value="booked">{t('finance.bookings.statusOptions.booked')}</option>
          <option value="confirmed">{t('finance.bookings.statusOptions.confirmed')}</option></select></label>
        <label>{t('bookingPages.view')}<select value={draft.view} onChange={event => setDraft(current => ({ ...current, view: event.target.value }))}>
          {['all', 'uncategorized', 'no_receipt', 'income', 'expense'].map(view => <option key={view} value={view}>{t(`bookingPages.${view}`)}</option>)}</select></label>
      </div>
      <details className="booking-advanced"><summary>{t('bookingPages.references')}</summary><div className="booking-reference-grid">
        {advancedKinds.map((kind, index) => <ReferenceFilter key={kind} kind={kind} value={draft[['account_id', 'property_id', 'tenant_id'][index]]}
          label={t(['bookingPages.account', 'bookingPages.property', 'bookingPages.tenant'][index])}
          onChange={value => setDraft(current => ({ ...current, [['account_id', 'property_id', 'tenant_id'][index]]: value }))} />)}
      </div></details>
      <div className="booking-filter-actions"><button className="btn btn-primary" type="submit">{t('bookingPages.apply')}</button>
        <button className="btn btn-secondary" type="button" onClick={() => { setDraft(emptyFilters); setFilters(emptyFilters); restart(); }}>{t('bookingPages.reset')}</button></div>
    </form>
    <div className="booking-toolbar">
      <p className="text-muted">{t('bookingPages.order')}</p>
      <div className="booking-export-actions"><a className="btn btn-secondary" href="/datev">{t('pages.datev.title')}</a><button className="btn btn-secondary" disabled={exporting} onClick={() => exportCsv(false)}>{t('bookingPages.csv')}</button>
        {typeof window.showSaveFilePicker === 'function' && <button className="btn btn-secondary" disabled={exporting} onClick={() => exportCsv(true)}>{t('bookingPages.directCsv')}</button>}</div>
      <details className="booking-columns"><summary>{t('bookingPages.columns')}</summary>
        {optional.map(([key, label]) => <label key={key}><input type="checkbox" checked={extraColumns.includes(key)}
          onChange={() => setExtraColumns(current => current.includes(key) ? current.filter(item => item !== key) : [...current, key])} />{label}</label>)}</details>
    </div>
    {(exporting || exported) && <p role="status">{t(exporting ? 'bookingPages.exporting' : 'bookingPages.exported')}</p>}
    {result.loading && <p role="status">{t('ui.table.loading')}</p>}
    {result.error && <div className="alert alert-error" role="alert">{errorMessage} <button className="btn btn-secondary" onClick={restartError ? restart : reload}>
      {t(restartError ? 'bookingPages.restart' : 'bookingPages.retry')}</button></div>}
    {!result.loading && !result.error && <>
      <p className="booking-summary" role="status">{t('bookingPages.pageSummary', { count: result.items.length, income: money.format(income), expense: money.format(expense) })}</p>
      <div className="data-table-wrapper shared-data-table"><div className="table-scroll" tabIndex={0} role="region" aria-label={t('finance.bookings.title')}>
        <table className="data-table"><caption className="booking-table-caption">{t('bookingPages.order')}</caption><thead><tr>
          {columns.map(([key, label]) => <th key={key} scope="col" aria-sort={key === 'booking_date' ? 'descending' : undefined}>{label}</th>)}
          {canWrite && <th scope="col">{t('bookingPages.actions')}</th>}</tr></thead><tbody>
          {result.items.map(row => <tr key={row.id}>
            {columns.map(([key]) => <td key={key}>{key === 'amount' ? <span className={Number(row.amount) < 0 ? 'text-red' : 'text-green'}>{money.format(Number(row.amount))}</span>
              : key === 'status' ? row.status === 'confirmed'
                ? <span className="badge badge-green">{t('finance.bookings.statusOptions.confirmed')}</span>
                : <StatusBadge status={row.status} /> : row[key] || '—'}</td>)}
            {canWrite && <td><div className="booking-row-actions"><button className="btn btn-sm btn-secondary" onClick={() => { if (isAllowed()) setModal(row); }}
              aria-label={`${t('bookingPages.edit')} ${row.payment_text || row.id}`}>{t('bookingPages.edit')}</button>
              <button className="btn btn-sm btn-danger" onClick={() => handleDelete(row)}
                aria-label={`${t('bookingPages.delete')} ${row.payment_text || row.id}`}>{t('bookingPages.delete')}</button></div></td>}
          </tr>)}
          {!result.items.length && <tr><td colSpan={columns.length + (canWrite ? 1 : 0)}>{t('bookingPages.empty')}</td></tr>}
        </tbody></table></div></div>
      <nav className="booking-pagination" aria-label={t('bookingPages.pagination')}>
        <button className="btn btn-secondary" disabled={!pageIndex} onClick={() => setPageIndex(value => value - 1)}>{t('bookingPages.previous')}</button>
        <span>{t('bookingPages.pageNumber', { page: pageIndex + 1 })}</span>
        <button className="btn btn-secondary" disabled={!result.hasMore} onClick={() => {
          setHistory(previous => [...previous.slice(0, pageIndex + 1), result.nextCursor]); setPageIndex(value => value + 1);
        }}>{t('bookingPages.next')}</button>
        <label>{t('bookingPages.pageSize')}<select value={pageSize} onChange={event => {
          setPageSize(Number(event.target.value)); setHistory([null]); setPageIndex(0);
        }}>{[25, 100, 250, 500].map(size => <option key={size} value={size}>{size}</option>)}</select></label>
      </nav>
    </>}
    {modal && canWrite && <BookingEditor key={modal === 'create' ? 'create' : modal.id} initial={modal === 'create' ? null : modal}
      onSave={handleSave} onClose={() => setModal(null)} />}
  </div>;
}
