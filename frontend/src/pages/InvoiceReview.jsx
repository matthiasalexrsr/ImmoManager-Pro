import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import DraftDefaults from '../components/DraftDefaults';
import useLookupChoices from '../hooks/useLookupChoices';
import { useCanWrite } from '../contexts/AuthContext';
import { formatDate, formatMoney } from '../utils/format';
import { Empty, Modal, Pill } from '../features/maintenanceProject/ProjectUi';
import { PAYMENT_TONE, STATUS_TONE, compact, reviewApi } from '../features/invoiceReview/reviewApi';
import { fill, useReviewText } from '../features/invoiceReview/text';
import '../features/maintenanceProject/maintenanceProject.css';
import '../features/invoiceReview/invoiceReview.css';

const PAGE = 50;
const STATUSES = ['pending', 'received', 'query', 'approved', 'partially_approved', 'rejected', 'dispute', 'legacy'];

// Finanzen → Rechnungsprüfung: every invoice with its review state, filtered on the server.
export default function InvoiceReview() {
  const { tx } = useReviewText();
  const [tab, setTab] = useState('inbox');
  const propertyChoices = useLookupChoices({ properties: '/properties' });
  const properties = propertyChoices.data.properties || [];
  const canReceive = useCanWrite('/invoice-review/receipts');
  const canSettings = useCanWrite('/invoice-review/settings');
  const [dialog, setDialog] = useState(null);
  const [revision, setRevision] = useState(0);

  return (
    <div className="page ir-page">
      <div className="page-header ir-header">
        <h1>{tx.title}</h1>
        <div className="mp-actions">
          {canSettings && <button type="button" className="btn btn-secondary btn-sm" onClick={() => setDialog('settings')}>
            {tx.settings}</button>}
          {canReceive && <button type="button" className="btn btn-primary btn-sm" disabled={!propertyChoices.ready} onClick={() => setDialog('new')}>
            {tx.newInvoice}</button>}
        </div>
      </div>
      {propertyChoices.error && <p className="alert-error" role="alert">Die Immobilienauswahl ist nicht verfügbar. {propertyChoices.error}{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={propertyChoices.reload}>Auswahl erneut laden</button></p>}
      <div className="detail-tabs" role="tablist" aria-label={tx.title}>
        {['inbox', 'proposals'].map(key => (
          <button key={key} type="button" role="tab" aria-selected={tab === key}
            className={`detail-tab${tab === key ? ' active' : ''}`} onClick={() => setTab(key)}>{tx[key]}</button>
        ))}
      </div>
      {tab === 'inbox' ? <Inbox properties={properties} choicesReady={propertyChoices.ready} revision={revision} /> : <Proposals revision={revision} />}
      {dialog === 'new' && propertyChoices.ready && <NewInvoice properties={properties} onClose={() => setDialog(null)}
        onSaved={() => setRevision(value => value + 1)} />}
      {dialog === 'settings' && <Settings onClose={() => setDialog(null)} />}
    </div>
  );
}

function Inbox({ properties, choicesReady, revision }) {
  const { tx } = useReviewText();
  const [filters, setFilters] = useState({ status: '', due: '', skonto: false, property_id: '', q: '' });
  const [skip, setSkip] = useState(0);
  const [page, setPage] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    reviewApi.inbox({ ...filters, skip, limit: PAGE }, { signal: controller.signal })
      .then(setPage)
      .catch(failure => { if (failure.name !== 'AbortError') setError(failure.message || tx.loadFailed); });
    return () => controller.abort();
  }, [filters, skip, revision, attempt, tx]);

  const set = (key, value) => { setSkip(0); setFilters(current => ({ ...current, [key]: value })); };

  return (
    <section aria-label={tx.inbox}>
      <form className="ir-filters" role="search" onSubmit={event => event.preventDefault()}>
        <label className="form-group">{tx.search}
          <input type="search" value={filters.q} onChange={event => set('q', event.target.value)} />
        </label>
        <label className="form-group">{tx.status}
          <select value={filters.status} onChange={event => set('status', event.target.value)}>
            <option value="">{tx.all}</option>
            {STATUSES.map(key => <option key={key} value={key}>{tx[`status_${key}`]}</option>)}
          </select>
        </label>
        <label className="form-group">{tx.due}
          <select value={filters.due} onChange={event => set('due', event.target.value)}>
            <option value="">{tx.all}</option>
            {['overdue', 'week', 'month'].map(key => <option key={key} value={key}>{tx[`due_${key}`]}</option>)}
          </select>
        </label>
        <label className="form-group">{tx.property}
          <select disabled={!choicesReady} value={filters.property_id} onChange={event => set('property_id', event.target.value)}>
            <option value="">{tx.all}</option>
            {properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label className="ir-check">
          <input type="checkbox" checked={filters.skonto} onChange={event => set('skonto', event.target.checked)} />
          {tx.onlySkonto}
        </label>
      </form>
      {error && <div className="alert-error" role="alert">{error}
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAttempt(v => v + 1)}>{tx.retry}</button></div>}
      {!error && !page && <p className="text-muted" role="status">{tx.loading}</p>}
      {page && (page.items.length === 0 ? <Empty>{tx.noResults}</Empty> : (
        <>
          <p className="text-muted ir-count" role="status">{fill(tx.page, { from: skip + 1, to: skip + page.items.length,
            total: page.total })}</p>
          <ul className="ir-list">
            {page.items.map(row => <InboxRow key={row.invoice_id} row={row} />)}
          </ul>
          <div className="ir-paging">
            <button type="button" className="btn btn-secondary btn-sm" disabled={skip === 0}
              onClick={() => setSkip(Math.max(0, skip - PAGE))}>{tx.previous}</button>
            <button type="button" className="btn btn-secondary btn-sm" disabled={!page.has_more}
              onClick={() => setSkip(skip + PAGE)}>{tx.next}</button>
          </div>
        </>
      ))}
    </section>
  );
}

function InboxRow({ row }) {
  const { tx } = useReviewText();
  const s = row.settlement || {};
  return (
    <li className="ir-row">
      <Link to={`/invoice-review/${encodeURIComponent(row.invoice_id)}`} className="ir-row-link">
        <span className="ir-row-main">
          <strong>{row.supplier}</strong>
          <span className="text-muted">{row.invoice_number || tx.none} · {formatDate(row.invoice_date)}
            {row.property_name ? ` · ${row.property_name}` : ''}</span>
        </span>
        <span className="ir-row-amount">{formatMoney(row.gross_amount)}</span>
        <span className="ir-row-state">
          <Pill tone={STATUS_TONE[row.status]}>{row.kind === 'credit_note' ? tx.creditNote : tx[`status_${row.status}`]}</Pill>
          {row.status !== 'legacy' && <Pill tone={PAYMENT_TONE[s.payment_status]}>{tx[`pay_${s.payment_status}`]}</Pill>}
          {s.overdue && <Pill tone="red">{tx.overdue}</Pill>}
          {s.skonto_available && <Pill tone="green">{tx.skontoUntil} {formatDate(s.skonto_until)}</Pill>}
          {row.dispute_status === 'open' && <Pill tone="orange">{tx.disputeOpen}</Pill>}
        </span>
      </Link>
    </li>
  );
}

function Proposals({ revision }) {
  const { tx } = useReviewText();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    reviewApi.proposals({}, { signal: controller.signal }).then(setData)
      .catch(failure => { if (failure.name !== 'AbortError') setError(failure.message || tx.loadFailed); });
    return () => controller.abort();
  }, [revision, tx]);
  if (error) return <div className="alert-error" role="alert">{error}</div>;
  if (!data) return <p className="text-muted" role="status">{tx.loading}</p>;
  return (
    <section aria-label={tx.proposals}>
      <p className="text-muted">{tx.proposalsNote}</p>
      {data.items.length === 0 ? <Empty>{tx.noProposals}</Empty> : (
        <>
          <ul className="ir-list">
            {data.items.map(item => (
              <li key={item.invoice_id} className="ir-row">
                <Link to={`/invoice-review/${encodeURIComponent(item.invoice_id)}`} className="ir-row-link">
                  <span className="ir-row-main">
                    <strong>{item.supplier}</strong>
                    <span className="text-muted">{item.payment_reference || tx.none} · {tx.payBy} {formatDate(item.pay_by)}</span>
                  </span>
                  <span className="ir-row-amount">{formatMoney(item.proposed_amount)}</span>
                  <span className="ir-row-state">
                    {item.skonto_until && <Pill tone="green">{tx.skontoAmount} {formatMoney(item.skonto_amount)}</Pill>}
                    {item.overdue && <Pill tone="red">{tx.overdue}</Pill>}
                    {item.dispute_open > 0 && <Pill tone="orange">{tx.disputed} {formatMoney(item.dispute_open)}</Pill>}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <p className="ir-total"><strong>{tx.total}: {formatMoney(data.total_amount)}</strong> · {fill(tx.count, { count: data.total })}</p>
        </>
      )}
    </section>
  );
}

const EMPTY_INVOICE = { supplier: '', invoice_number: '', invoice_date: '', net_amount: '', vat_rate: '19',
  gross_amount: '', property_id: '', skonto_percent: '', skonto_days: '', payment_days: '', cost_category: '',
  recoverable: false, duplicate_reason: '' };

function NewInvoice({ properties, onClose, onSaved }) {
  const { tx } = useReviewText();
  const navigate = useNavigate();
  const [values, setValues] = useState(EMPTY_INVOICE);
  const [file, setFile] = useState(null);
  const [duplicates, setDuplicates] = useState([]);
  const [duplicateError, setDuplicateError] = useState(null);
  const [duplicateAttempt, setDuplicateAttempt] = useState(0);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const set = (key, value) => setValues(current => ({ ...current, [key]: value }));
  const ready = values.supplier && values.gross_amount && values.invoice_date;

  useEffect(() => {
    setDuplicates([]); setDuplicateError(null);
    if (!ready) return undefined;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      reviewApi.duplicates({ supplier: values.supplier, invoice_number: values.invoice_number,
        gross_amount: values.gross_amount, invoice_date: values.invoice_date }, { signal: controller.signal })
        .then(result => {
          if (controller.signal.aborted) return;
          if (!Array.isArray(result?.duplicates)) throw new Error(tx.duplicateCheckFailed);
          setDuplicates(result.duplicates);
        }).catch(failure => { if (!controller.signal.aborted) setDuplicateError(failure.message || tx.duplicateCheckFailed); });
    }, 300);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [ready, values.supplier, values.invoice_number, values.gross_amount, values.invoice_date, duplicateAttempt, tx.duplicateCheckFailed]);

  const sameNumber = duplicates.some(d => d.reason === 'same_number');
  const submit = async event => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      let documentId;
      if (file) {
        const form = new FormData();
        form.append('file', file);
        form.append('title', `${values.supplier} ${values.invoice_number}`.trim());
        form.append('document_type', 'invoice');
        if (values.property_id) form.append('property_id', values.property_id);
        documentId = (await api.upload('/documents/import', form)).id;
      }
      const net = Number(values.net_amount);
      const gross = Number(values.gross_amount);
      const created = await reviewApi.newReceipt(compact({
        document_id: documentId, property_id: values.property_id, cost_category: values.cost_category,
        recoverable: values.recoverable, skonto_percent: values.skonto_percent ? Number(values.skonto_percent) : undefined,
        skonto_days: values.skonto_days ? Number(values.skonto_days) : undefined,
        payment_days: values.payment_days ? Number(values.payment_days) : undefined,
        accept_duplicate: sameNumber || undefined, duplicate_reason: sameNumber ? values.duplicate_reason : undefined,
        invoice: compact({ supplier: values.supplier, invoice_number: values.invoice_number,
          invoice_date: values.invoice_date, net_amount: net, vat_rate: Number(values.vat_rate),
          vat_amount: Math.round((gross - net) * 100) / 100, gross_amount: gross, property_id: values.property_id }),
      }));
      onSaved();
      navigate(`/invoice-review/${encodeURIComponent(created.invoice.id)}`);
    } catch (failure) {
      setError(failure.message);
      setSaving(false);
    }
  };

  const input = (key, label, type = 'text', extra = {}) => (
    <label className="form-group">{label}
      <input type={type} value={values[key]} onChange={event => set(key, event.target.value)} {...extra} />
    </label>
  );
  return (
    <Modal title={tx.newInvoice} onClose={onClose} wide>
      <form onSubmit={submit}>
        <div className="modal-body">
          {error && <div className="alert-error" role="alert">{error}</div>}
          <div className="mp-form-grid">
            {input('supplier', tx.supplier, 'text', { required: true })}
            {input('invoice_number', tx.number)}
            {input('invoice_date', tx.invoiceDate, 'date', { required: true })}
            {input('net_amount', tx.net, 'number', { step: '0.01', min: '0', required: true })}
            {input('vat_rate', tx.vatRate, 'number', { step: '0.01', min: '0', max: '100' })}
            {input('gross_amount', tx.gross, 'number', { step: '0.01', min: '0.01', required: true })}
            <label className="form-group">{tx.property}
              <select value={values.property_id} onChange={event => set('property_id', event.target.value)}>
                <option value="">{tx.none}</option>
                {properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <DraftDefaults context="invoice-review" propertyId={values.property_id} disabled={saving}
              onApply={defaults => setValues(current => ({ ...current, cost_category: current.cost_category || defaults.cost_category || '', recoverable: defaults.recoverable ?? current.recoverable }))} />
            {input('cost_category', tx.costCategory)}
            {input('skonto_percent', tx.skontoPercent, 'number', { step: '0.01', min: '0', max: '99' })}
            {input('skonto_days', tx.skontoDays, 'number', { min: '0' })}
            {input('payment_days', tx.paymentDays, 'number', { min: '0' })}
            <label className="form-group">{tx.document}
              <input type="file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff" onChange={event => setFile(event.target.files?.[0] || null)} />
            </label>
            <label className="ir-check">
              <input type="checkbox" checked={values.recoverable} onChange={event => set('recoverable', event.target.checked)} />
              {tx.recoverable}
            </label>
          </div>
          {duplicates.length > 0 && <DuplicateList duplicates={duplicates} />}
          {duplicateError && <div role="alert" className="alert-error">{tx.duplicateCheckFailed} {duplicateError}{' '}
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setDuplicateAttempt(value => value + 1)}>{tx.retry}</button></div>}
          {sameNumber && input('duplicate_reason', `${tx.acceptDuplicate} – ${tx.duplicateReason}`, 'text', { required: true })}
        </div>
        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" onClick={onClose}>{tx.cancel}</button>
          <button type="submit" className="btn btn-primary" disabled={saving}>{tx.save}</button>
        </div>
      </form>
    </Modal>
  );
}

export function DuplicateList({ duplicates }) {
  const { tx } = useReviewText();
  return (
    <div className="ir-duplicates" role="alert">
      <strong>{tx.duplicates}</strong>
      <ul>
        {duplicates.map(d => (
          <li key={d.invoice_id}>
            <Link to={`/invoice-review/${encodeURIComponent(d.invoice_id)}`}>{d.invoice_number || tx.none}</Link>
            {' '}· {formatDate(d.invoice_date)} · {formatMoney(d.gross_amount)} · {tx[`dup_${d.reason}`]}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Settings({ onClose }) {
  const { tx } = useReviewText();
  const [values, setValues] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    reviewApi.settings().then(found => setValues({
      four_eyes_limit: found.four_eyes_limit ?? '', small_invoice_limit: found.small_invoice_limit,
      duplicate_window_days: found.duplicate_window_days })).catch(failure => setError(failure.message));
  }, []);
  const submit = async event => {
    event.preventDefault();
    try {
      await reviewApi.saveSettings({
        four_eyes_limit: values.four_eyes_limit === '' ? null : Number(values.four_eyes_limit),
        small_invoice_limit: Number(values.small_invoice_limit),
        duplicate_window_days: Number(values.duplicate_window_days) });
      onClose();
    } catch (failure) { setError(failure.message); }
  };
  const set = (key, value) => setValues(current => ({ ...current, [key]: value }));
  return (
    <Modal title={tx.settings} onClose={onClose}>
      <form onSubmit={submit}>
        <div className="modal-body">
          {error && <div className="alert-error" role="alert">{error}</div>}
          {!values ? <p className="text-muted">{tx.loading}</p> : (
            <div className="mp-form-grid">
              <label className="form-group">{tx.fourEyesLimit}
                <input type="number" step="0.01" min="0" value={values.four_eyes_limit}
                  onChange={event => set('four_eyes_limit', event.target.value)} /></label>
              <label className="form-group">{tx.smallLimit}
                <input type="number" step="0.01" min="0" value={values.small_invoice_limit}
                  onChange={event => set('small_invoice_limit', event.target.value)} /></label>
              <label className="form-group">{tx.duplicateWindow}
                <input type="number" min="0" max="365" value={values.duplicate_window_days}
                  onChange={event => set('duplicate_window_days', event.target.value)} /></label>
            </div>
          )}
        </div>
        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" onClick={onClose}>{tx.cancel}</button>
          <button type="submit" className="btn btn-primary" disabled={!values}>{tx.save}</button>
        </div>
      </form>
    </Modal>
  );
}
