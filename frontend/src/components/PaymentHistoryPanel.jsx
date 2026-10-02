import { useEffect, useId, useRef, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useDataStore } from '../contexts/DataStoreContext';
import useWriteAccess from '../hooks/useWriteAccess';
import { euroCents, storedCents } from '../utils/accountMoney';
import { checkedPayments, checkedReversal, paymentPath } from '../utils/bankMatching';
import { useConfirm } from './ConfirmDialog';
import FormModal from './FormModal';
import './BankMatchingPanel.css';

export default function PaymentHistoryPanel({ path, onChanged, onClose, onBusyChange }) {
  const { t, locale } = useTranslation();
  const text = key => t(`bankMatching.${key}`);
  const confirm = useConfirm();
  const store = useDataStore();
  const [history, setHistory] = useState([null]);
  const [index, setIndex] = useState(0);
  const [revision, setRevision] = useState(0);
  const [page, setPage] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [reversing, setReversing] = useState(null);
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const operation = useRef(null);
  const identifier = useId();
  const previousPath = useRef(path);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess(path.startsWith('/invoices/') ? '/invoices' : '/bookings', () => {
    generation.current += 1; operation.current?.abort(); setReversing(null);
  });
  useEffect(() => () => { generation.current += 1; operation.current?.abort(); }, []);
  useEffect(() => { onBusyChange?.(busy); }, [busy, onBusyChange]);
  useEffect(() => {
    generation.current += 1; operation.current?.abort(); setReversing(null);
    if (previousPath.current !== path) { setHistory([null]); setIndex(0); previousPath.current = path; }
  }, [path]);
  const reload = () => { setHistory([null]); setIndex(0); setRevision(value => value + 1); };
  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ page_size: '25' });
    if (history[index]) params.set('cursor', history[index]);
    setLoading(true); setError(null); setPage(null);
    api.get(`${path}?${params}`, { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) setPage(checkedPayments(value));
    }).catch(failure => { if (!controller.signal.aborted) setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [path, history, index, revision]);
  const reverse = async values => {
    requireWrite();
    const captured = generation.current;
    setBusy(true);
    const controller = new AbortController();
    try {
      if (!await confirm(text('reverseConfirm')) || captured !== generation.current || !isAllowed()) return;
      operation.current = controller;
      requireWrite();
      const receipt = reversing.receipt;
      const request = { ...values, idempotency_key: reversing.key };
      const response = await api.post(`/${paymentPath(receipt.entity_type)}/${encodeURIComponent(receipt.entity_id)}/payments/${encodeURIComponent(receipt.id)}/reversal`,
        request, { signal: controller.signal });
      if (captured !== generation.current || controller.signal.aborted) return;
      checkedReversal(response, receipt, request);
      setReversing(null); reload(); onChanged?.();
      store?.invalidateRelated('bookings', 'accounts', 'invoices', 'rent-charges', 'receivables', 'contracts');
    } catch (failure) {
      if (captured !== generation.current || controller.signal.aborted) return;
      if (failure.message === 'bankMatching.invalidResponse') throw new Error(text('invalidResponse'));
      throw failure;
    } finally { if (operation.current === controller) operation.current = null; setBusy(false); }
  };
  const message = error === 'bankMatching.invalidResponse' ? text('invalidResponse') : error;
  return <section className="panel bank-payment-history" aria-labelledby={identifier}>
    <div className="bank-matching-heading"><h3 id={identifier}>{text('history')}</h3>
      {onClose && <button type="button" className="btn btn-secondary" disabled={busy} onClick={onClose}>{t('ui.buttons.close')}</button>}</div>
    <p className="text-muted">{text('historyHelp')}</p>
    {loading && <p role="status">{t('ui.table.loading')}</p>}
    {error && <div className="alert alert-error" role="alert">{message} <button type="button" className="btn btn-secondary" onClick={reload}>{text('renew')}</button></div>}
    {page && !loading && <>
      {!page.items.length && <p>{text('noHistory')}</p>}
      <ol className="bank-payment-list">{page.items.map(item => <li key={item.id}>
        <div><strong>{euroCents(storedCents(item.amount), locale)}</strong> · {item.payment_date} · {text(`kind.${item.entity_type}`)}
          <p><code>{item.id}</code></p>{item.note && <p>{item.note}</p>}
          {item.reversal && <p className="text-muted">{text('reversed')} · {item.reversal.reversal_date} · {item.reversal.reason}</p>}</div>
        {canWrite && !item.reversal && <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => {
          if (isAllowed()) setReversing({ receipt: item, key: crypto.randomUUID() });
        }}>{text('reverse')}</button>}
      </li>)}</ol>
      <nav className="bank-matching-paging" aria-label={text('historyPages')}>
        <button type="button" className="btn btn-secondary" disabled={!index} onClick={() => setIndex(value => value - 1)}>{t('bookingPages.previous')}</button>
        <span>{t('bookingPages.pageNumber', { page: index + 1 })}</span>
        <button type="button" className="btn btn-secondary" disabled={!page.has_more} onClick={() => {
          setHistory(current => [...current.slice(0, index + 1), page.next_cursor]); setIndex(value => value + 1);
        }}>{t('bookingPages.next')}</button>
      </nav>
    </>}
    {reversing && canWrite && <FormModal title={text('reverse')} saveLabel={text('reverse')} closeOnSave={false}
      fields={[{ key: 'reversal_date', label: text('reversalDate'), type: 'date', required: true, default: new Date().toISOString().slice(0, 10) },
        { key: 'reason', label: text('reason'), type: 'textarea', required: true, maxLength: 2000 }]}
      onSave={reverse} onClose={() => setReversing(null)}><p>{text('reverseHelp')}</p></FormModal>}
  </section>;
}
