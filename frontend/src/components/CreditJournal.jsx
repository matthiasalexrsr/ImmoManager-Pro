import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import useWriteAccess from '../hooks/useWriteAccess';
import { useConfirm } from './ConfirmDialog';
import DataTable from './DataTable';
import FormModal from './FormModal';
import './CreditJournal.css';

const decimal = value => typeof value === 'string' && /^\d+\.\d{2}$/.test(value);
const today = () => new Date().toISOString().slice(0, 10);

/** Accounting confirmation only: this workspace never initiates a bank transfer. */
export default function CreditJournal({ contractId, sourceId, onClose, onBusyChange }) {
  const { t, locale } = useTranslation();
  const text = key => t(`pages.statements.credits.${key}`);
  const confirm = useConfirm();
  const [modal, setModal] = useState(null);
  const { canWrite, requireWrite, isAllowed } = useWriteAccess('/billing', () => setModal(null));
  const [refresh, setRefresh] = useState(0);
  const [page, setPage] = useState(0);
  const [state, setState] = useState({ data: null, error: null });
  const [choices, setChoices] = useState(null);
  const [working, setWorking] = useState(false);
  const [success, setSuccess] = useState(null);
  const key = useRef(null);
  const submitting = useRef(false);
  useEffect(() => { onBusyChange?.(working); return () => onBusyChange?.(false); }, [onBusyChange, working]);
  const requestKey = `${contractId}:${page}:${refresh}`;
  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    setState({ key: requestKey, data: null, error: null });
    Promise.all([api.get(`/billing/contracts/${contractId}/credits`, options),
      api.get(`/billing/contracts/${contractId}/credit-receipts?offset=${page * 50}&limit=50`, options)])
      .then(([summary, journal]) => {
        if (controller.signal.aborted) return;
        if (summary?.contract_id !== contractId || journal?.contract_id !== contractId ||
            !Array.isArray(summary.sources) || !Array.isArray(journal.receipts) || !Number.isInteger(journal.total) || journal.total < 0 ||
            !['remaining_amount', 'reserved_amount', 'available_amount'].every(field => decimal(summary[field])) ||
            summary.sources.some(source => !source.id || !decimal(source.remaining_amount) || !decimal(source.available_amount))) {
          throw new Error(text('invalidResponse'));
        }
        setState({ key: requestKey, data: { summary, journal }, error: null });
      }).catch(error => { if (!controller.signal.aborted) setState({ key: requestKey, data: null, error }); });
    return () => controller.abort();
  // The request identity excludes translated labels so language changes preserve drafts.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contractId, requestKey]);
  const current = state.key === requestKey ? state : { data: null, error: null };
  const money = amount => new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(amount);
  const open = async (kind, receipt = null) => {
    if (submitting.current || !isAllowed()) return;
    submitting.current = true;
    setWorking(true);
    try {
      requireWrite();
      const values = kind === 'reversal' ? null : await Promise.all([
        api.getAll('/rent-charges'), api.getAll('/receivables'), api.getAll('/bookings')]);
      requireWrite();
      if (values) {
        const [charges, receivables, bookings] = values;
        setChoices({ targets: [...charges.map(row => ({ ...row, type: 'rent_charge', total: ['cold_rent', 'service_charge', 'heating_charge', 'other_charges'].reduce((sum, field) => sum + Number(row[field] || 0), 0) })),
          ...receivables.map(row => ({ ...row, type: 'receivable', total: Number(row.amount_due) }))]
          .filter(row => row.contract_id === contractId && !['cancelled', 'void', 'paid'].includes(row.status) && row.total > Number(row.amount_paid)),
        bookings: bookings.filter(row => Number(row.amount) < 0 && Math.abs(Number(row.amount)) > Number(row.allocated_amount || 0)) });
      }
      key.current = crypto.randomUUID();
      setModal({ kind, receipt });
    } catch (error) { setState(value => ({ ...value, error })); }
    finally { submitting.current = false; setWorking(false); }
  };
  const submit = async values => {
    if (submitting.current) return;
    submitting.current = true;
    setWorking(true);
    try {
      requireWrite();
      if (!confirm) throw new Error(text('confirmationRequired'));
      if (!await confirm(text(modal.kind === 'reversal' ? 'confirmReversal' : modal.kind === 'offset' ? 'confirmOffset' : 'confirmPayout'))) return;
      requireWrite();
      const shared = { idempotency_key: key.current, source_settlement_id: values.source_settlement_id,
        amount: values.amount, transaction_date: values.transaction_date, note: values.note || null };
      let path, body;
      if (modal.kind === 'reversal') {
        path = `/billing/credit-receipts/${modal.receipt.id}/reversal`;
        body = { idempotency_key: key.current, reversal_date: values.reversal_date, reason: values.reason };
      } else if (modal.kind === 'offset') {
        const selected = choices.targets.find(row => `${row.type}:${row.id}` === values.target);
        if (!selected) throw new Error(text('targetRequired'));
        path = '/billing/credit-offsets';
        body = { ...shared, target_type: selected.type, target_id: selected.id };
      } else {
        path = '/billing/credit-payouts';
        body = { ...shared, method: values.method, booking_id: values.method === 'bank' ? values.booking_id : null,
          confirmed_payment: values.confirmed_payment === 'confirmed' };
      }
      const result = await api.post(path, body);
      if (!result?.id || (modal.kind === 'reversal' ? result.receipt_id !== modal.receipt.id :
        result.contract_id !== contractId || result.source_settlement_id !== body.source_settlement_id || result.idempotency_key !== key.current)) {
        throw new Error(text('invalidResponse'));
      }
      setSuccess(result.id);
      setModal(null);
      setPage(0);
      setRefresh(value => value + 1);
    } finally { submitting.current = false; setWorking(false); }
  };
  const sources = current.data?.summary.sources || [];
  const fields = modal?.kind === 'reversal' ? [
    { key: 'reversal_date', label: text('date'), type: 'date', required: true },
    { key: 'reason', label: text('reason'), type: 'textarea', required: true, maxLength: 2000 },
  ] : [
    { key: 'source_settlement_id', label: text('source'), type: 'select', required: true,
      options: sources.filter(source => Number(source.remaining_amount) > 0).map(source => ({ value: source.id, label: `${source.id} · ${money(source.remaining_amount)}` })), hint: text('sourceHint') },
    { key: 'amount', label: text('amount'), required: true, pattern: '(0|[1-9][0-9]*)(\\.[0-9]{1,2})?', hint: text('amountHint') },
    { key: 'transaction_date', label: text('date'), type: 'date', required: true },
    ...(modal?.kind === 'offset' ? [{ key: 'target', label: text('target'), type: 'select', required: true,
      options: choices?.targets.map(row => ({ value: `${row.type}:${row.id}`, label: `${row.type === 'rent_charge' ? text('rentCharge') : text('receivable')} · ${row.month || row.due_date} · ${money(row.total - Number(row.amount_paid))} · ${row.id}` })), hint: text('offsetHint') }] : [
      { key: 'method', label: text('method'), type: 'select', required: true, options: [{ value: 'cash', label: text('cash') }, { value: 'bank', label: text('bank') }] },
      { key: 'booking_id', label: text('booking'), type: 'select', options: choices?.bookings.map(row => ({ value: row.id, label: `${row.booking_date} · ${money(Math.abs(Number(row.amount)) - Number(row.allocated_amount || 0))} · ${row.payment_text || row.id}` })), hint: text('bookingHint') },
      { key: 'confirmed_payment', label: text('completedPayment'), type: 'select', required: true, options: [{ value: 'confirmed', label: text('completedConfirmation') }], hint: text('payoutHint') },
    ]),
    { key: 'note', label: text('note'), type: 'textarea', maxLength: 2000 },
  ];
  const columns = [
    { key: 'transaction_date', label: text('date'), type: 'date' },
    { key: 'method', label: text('method'), render: value => text(value) },
    { key: 'amount', label: text('amount'), type: 'number', align: 'right', render: money },
    { key: 'id', label: text('receipt') },
    { key: 'payment_id', label: text('payment'), render: (value, row) => value || row.booking_id || '—' },
    { key: 'reversal', label: text('status'), render: value => value ? `${text('reversed')} · ${value.reversal_date} · ${value.reason}` : text('posted') },
    ...(canWrite ? [{ key: 'credit_action', label: text('reverse'), render: (_, row) => <button type="button" className="btn btn-secondary" disabled={working || Boolean(row.reversal)} onClick={() => open('reversal', row)}>{text('reverse')}</button> }] : []),
  ];
  return <section className="card credit-journal" aria-label={text('title')} style={{ marginTop: '1rem' }} aria-busy={working}>
    <div className="card-header"><h3>{text('title')}</h3><button type="button" className="btn btn-secondary" disabled={working} onClick={onClose}>{t('ui.buttons.close')}</button></div>
    <div className="card-body">
      <p>{text('payoutHint')}</p>
      {success && <p role="status">{text('saved')}: {success}</p>}
      {current.error && <div role="alert" className="alert-error">{current.error.message}<button type="button" className="btn btn-secondary" disabled={working} onClick={() => setRefresh(value => value + 1)}>{t('ui.buttons.retry')}</button></div>}
      {!current.data && !current.error && <p role="status">{t('ui.table.loading')}</p>}
      {current.data && <>
        <div className="stats-grid">{['remaining_amount', 'reserved_amount', 'available_amount'].map(field => <div className="stat-card" key={field}><div className="stat-label">{text(field)}</div><div className="stat-value">{money(current.data.summary[field])}</div></div>)}</div>
        <p>{text('reservationHint')}</p>
        {canWrite && <div className="btn-group" style={{ margin: '1rem 0' }}><button type="button" className="btn btn-primary" disabled={working || Number(current.data.summary.available_amount) <= 0} onClick={() => open('payout')}>{text('payout')}</button><button type="button" className="btn btn-secondary" disabled={working || Number(current.data.summary.remaining_amount) <= 0} onClick={() => open('offset')}>{text('offset')}</button></div>}
        <DataTable title={text('receipts')} data={current.data.journal.receipts} columns={columns} />
        <div className="btn-group" aria-label={text('pages')}><button type="button" className="btn btn-secondary" disabled={working || page === 0} onClick={() => setPage(value => value - 1)}>{t('ui.table.previousPage')}</button><span>{page + 1} · {current.data.journal.total} {text('receipts')}</span><button type="button" className="btn btn-secondary" disabled={working || (page + 1) * 50 >= current.data.journal.total} onClick={() => setPage(value => value + 1)}>{t('ui.table.nextPage')}</button></div>
      </>}
      {modal && <FormModal title={text(modal.kind === 'reversal' ? 'reverse' : modal.kind)} fields={fields}
        initial={modal.kind === 'reversal' ? { reversal_date: today(), reason: '' } : { source_settlement_id: sourceId || sources[0]?.id, amount: '', transaction_date: today(), method: 'cash', note: '' }}
        onSave={submit} onClose={() => setModal(null)} closeOnSave={false} saveDisabled={!canWrite} saveLabel={text('record')} />}
    </div>
  </section>;
}
