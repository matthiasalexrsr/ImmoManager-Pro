import { useEffect, useRef, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import DraftDefaults from '../components/DraftDefaults';
import useLookupChoices from '../hooks/useLookupChoices';
import { useCanWrite } from '../contexts/AuthContext';
import { formatDate, formatMoney } from '../utils/format';
import { Empty, Modal, Pill } from '../features/maintenanceProject/ProjectUi';
import { PAYMENT_TONE, STATUS_TONE, compact, reviewApi } from '../features/invoiceReview/reviewApi';
import { fill, useReviewText } from '../features/invoiceReview/text';
import AiReadingPanel from '../features/aiReading/AiReadingPanel';
import { AiFieldNote, AiFormSummary, AiMarkChip } from '../features/aiReading/AiFieldMarks';
import { aiGroupClass, pendingMessage, useAiMarks } from '../features/aiReading/aiMarks';
import { INVOICE_FORM, aiReadingApi, formFromReading } from '../features/aiReading/aiReadingApi';
import { COST_CATEGORIES } from '../utils/costCategories';
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
  recoverable: false, duplicate_reason: '', kind: 'invoice', credit_for_invoice_id: '', due_date: '',
  performance_start: '', performance_end: '', iban: '' };

function NewInvoice({ properties, onClose, onSaved }) {
  const { tx } = useReviewText();
  const navigate = useNavigate();
  const [values, setValues] = useState(EMPTY_INVOICE);
  const [file, setFile] = useState(null);
  const [readFile, setReadFile] = useState(null);            // the receipt uploaded for reading: { fileUrl, name }
  const [marks, setMarks] = useState(null);
  const [markStart, setMarkStart] = useState(EMPTY_INVOICE);
  const reading = useRef(null);                              // the reading the values came from
  const aiForm = useAiMarks(marks, values, markStart);
  const [duplicates, setDuplicates] = useState([]);
  const [duplicateError, setDuplicateError] = useState(null);
  const [duplicateAttempt, setDuplicateAttempt] = useState(0);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [creditInvoices, setCreditInvoices] = useState([]);
  const [creditLoadError, setCreditLoadError] = useState(null);
  useEffect(() => {
    if (values.kind !== 'credit_note') return undefined;
    const controller = new AbortController();
    setCreditLoadError(null);
    api.list('/invoices', { signal: controller.signal }).then(items => {
      if (!controller.signal.aborted) setCreditInvoices(items);
    }).catch(failure => { if (!controller.signal.aborted) setCreditLoadError(failure.message); });
    return () => controller.abort();
  }, [values.kind]);
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
  const labels = { supplier: tx.supplier, invoice_number: tx.number, invoice_date: tx.invoiceDate, net_amount: tx.net, vat_rate: tx.vatRate,
    gross_amount: tx.gross, cost_category: tx.costCategory, skonto_percent: tx.skontoPercent, skonto_days: tx.skontoDays,
    payment_days: tx.paymentDays, due_date: tx.due, performance_start: 'Leistung von', performance_end: 'Leistung bis',
    iban: 'IBAN laut Beleg', kind: tx.kind };
  const pending = aiForm.pending(Object.keys(labels));
  const dropReading = () => {
    if (reading.current?.status === 'open') aiReadingApi.finish(reading.current, 'cancelled').catch(() => {});
    reading.current = null; setReadFile(null);                // read values stay marked in the form
  };
  const startReading = async () => {
    setError(null);
    try {
      const fileUrl = await aiReadingApi.upload(file);
      setReadFile({ fileUrl, name: file.name });
    } catch (failure) { setError(failure.message); }
  };
  const applyReading = found => {
    const { initial, aiMarks } = formFromReading(values, found, INVOICE_FORM, [], readFile?.name);
    reading.current = found;
    setMarkStart(values); setValues(initial); setMarks(aiMarks); setReadFile(current => ({ ...current, applied: true }));
  };
  const submit = async event => {
    event.preventDefault();
    if (pending.length) { setError(pendingMessage(pending.map(key => labels[key]))); return; }
    if (values.kind === 'credit_note' && !values.credit_for_invoice_id) {
      setError('Bitte die Rechnung auswählen, die durch die Gutschrift gemindert wird.'); return;
    }
    if (Boolean(values.performance_start) !== Boolean(values.performance_end)
      || (values.performance_start && values.performance_end < values.performance_start)) {
      setError('Leistungsbeginn und Leistungsende gemeinsam und in zeitlicher Reihenfolge angeben.'); return;
    }
    setSaving(true);
    setError(null);
    try {
      let documentId;
      if (readFile) {                                         // the receipt is already uploaded for reading
        documentId = (await api.post('/documents', compact({ title: `${values.supplier} ${values.invoice_number}`.trim(),
          document_type: 'invoice', file_url: readFile.fileUrl, property_id: values.property_id || undefined }))).id;
      } else if (file) {
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
        kind: values.kind, credit_for_invoice_id: values.kind === 'credit_note' ? values.credit_for_invoice_id : undefined,
        document_id: documentId, property_id: values.property_id, cost_category: values.cost_category,
        recoverable: values.recoverable, skonto_percent: values.skonto_percent ? Number(values.skonto_percent) : undefined,
        skonto_days: values.skonto_days ? Number(values.skonto_days) : undefined,
        payment_days: values.payment_days ? Number(values.payment_days) : undefined,
        accept_duplicate: sameNumber || undefined, duplicate_reason: sameNumber ? values.duplicate_reason : undefined,
        invoice: compact({ supplier: values.supplier, invoice_number: values.invoice_number,
          invoice_date: values.invoice_date, due_date: values.due_date,
          performance_start: values.performance_start, performance_end: values.performance_end,
          notes: values.iban ? `IBAN laut Beleg: ${values.iban}` : undefined,
          net_amount: net, vat_rate: Number(values.vat_rate),
          vat_amount: Math.round((gross - net) * 100) / 100, gross_amount: gross, property_id: values.property_id }),
      }));
      if (reading.current) aiReadingApi.finish(reading.current, 'taken_over', { kind: 'invoice', id: created.invoice.id }).catch(() => {});
      reading.current = null;
      onSaved();
      navigate(`/invoice-review/${encodeURIComponent(created.invoice.id)}`);
    } catch (failure) {
      setError(failure.message);
      setSaving(false);
    }
  };

  const input = (key, label, type = 'text', extra = {}) => {
    const state = aiForm.state(key);
    const mark = aiForm.mark(key);
    return <div className={`form-group${aiGroupClass(state)}`}>
      <label htmlFor={`ir-new-${key}`}>{label} <AiMarkChip state={state} mark={mark} /></label>
      <input id={`ir-new-${key}`} type={type} value={values[key]} onChange={event => set(key, event.target.value)} {...extra} />
      <AiFieldNote label={label} state={state} mark={mark} onConfirm={() => aiForm.confirm([key])} disabled={saving} />
    </div>;
  };
  const costCategory = () => {
    const state = aiForm.state('cost_category');
    const mark = aiForm.mark('cost_category');
    const known = COST_CATEGORIES.some(([value]) => value === values.cost_category);
    return <div className={`form-group${aiGroupClass(state)}`}>
      <label htmlFor="ir-new-cost_category">{tx.costCategory} <AiMarkChip state={state} mark={mark} /></label>
      <select id="ir-new-cost_category" value={values.cost_category} onChange={event => set('cost_category', event.target.value)}>
        <option value="">{tx.none}</option>
        {!known && values.cost_category && <option value={values.cost_category}>{values.cost_category}</option>}
        {COST_CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      <AiFieldNote label={tx.costCategory} state={state} mark={mark} onConfirm={() => aiForm.confirm(['cost_category'])} disabled={saving} />
    </div>;
  };
  const close = () => { dropReading(); onClose(); };
  return (
    <Modal title={tx.newInvoice} onClose={close} wide>
      <form onSubmit={submit}>
        <div className="modal-body">
          {error && <div className="alert-error" role="alert">{error}</div>}
          {readFile && !readFile.applied && <div className="panel ai-reading-inline">
            <AiReadingPanel surface="invoice" autoStart source={readFile} params={values.property_id ? { property_id: values.property_id } : {}}
              title="Beleg einlesen" applyLabel="In die Rechnung übernehmen" onApply={applyReading}
              onCancel={() => { reading.current = null; setReadFile(null); }}
              onOpenExisting={item => { setReadFile(null); onClose(); navigate(item.href); }} />
          </div>}
          <AiFormSummary aiMarks={marks} filled={aiForm.filled(Object.keys(labels))} pending={pending}
            onConfirmAll={() => aiForm.confirm(pending)} disabled={saving} />
          <div className="mp-form-grid">
            <div className={`form-group${aiGroupClass(aiForm.state('kind'))}`}>
              <label htmlFor="ir-new-kind">{tx.kind} <AiMarkChip state={aiForm.state('kind')} mark={aiForm.mark('kind')} /></label>
              <select id="ir-new-kind" value={values.kind} onChange={event => set('kind', event.target.value)}>
                <option value="invoice">{tx.kind_invoice}</option><option value="credit_note">{tx.kind_credit_note}</option>
              </select>
              <AiFieldNote label={tx.kind} state={aiForm.state('kind')} mark={aiForm.mark('kind')}
                onConfirm={() => aiForm.confirm(['kind'])} disabled={saving} />
            </div>
            {values.kind === 'credit_note' && <label className="form-group">Mindert Rechnung
              <select required value={values.credit_for_invoice_id} onChange={event => set('credit_for_invoice_id', event.target.value)}>
                <option value="">Bitte Rechnung wählen</option>
                {creditInvoices.map(invoice => <option key={invoice.id} value={invoice.id}>
                  {invoice.supplier} · {invoice.invoice_number || formatDate(invoice.invoice_date)} · {formatMoney(invoice.gross_amount)}
                </option>)}
              </select>
              {creditLoadError && <span role="alert">Rechnungen konnten nicht geladen werden: {creditLoadError}</span>}
            </label>}
            {input('supplier', tx.supplier, 'text', { required: true })}
            {input('invoice_number', tx.number)}
            {input('invoice_date', tx.invoiceDate, 'date', { required: true })}
            {input('due_date', tx.due, 'date')}
            {input('performance_start', 'Leistung von', 'date')}
            {input('performance_end', 'Leistung bis', 'date')}
            {input('iban', 'IBAN laut Beleg')}
            <small className="form-hint">Die IBAN wird als Belegnotiz gespeichert. Zahlungsdaten werden dadurch nicht geändert.</small>
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
            {costCategory()}
            {input('skonto_percent', tx.skontoPercent, 'number', { step: '0.01', min: '0', max: '99' })}
            {input('skonto_days', tx.skontoDays, 'number', { min: '0' })}
            {input('payment_days', tx.paymentDays, 'number', { min: '0' })}
            <div className="form-group">
              <label htmlFor="ir-new-file">{tx.document}</label>
              <input id="ir-new-file" type="file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff"
                onChange={event => { dropReading(); setFile(event.target.files?.[0] || null); }} />
              {file && !readFile && <button type="button" className="btn btn-sm btn-secondary" disabled={saving} onClick={startReading}>
                <Sparkles size={14} aria-hidden="true" /> Beleg einlesen</button>}
              {readFile?.applied && <small className="form-hint">Werte aus „{readFile.name}“ übernommen.</small>}
            </div>
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
