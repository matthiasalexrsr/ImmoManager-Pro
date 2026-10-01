import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import useWriteAccess from '../hooks/useWriteAccess';
import FormModal from './FormModal';
import DataTable from './DataTable';
import './RentBatchPanel.css';
import { checkedRentBatch } from '../utils/rentBatch';

const emptyFields = [];
function readableError(error) {
  if (error?.details?.message) return error.details.message;
  try { return JSON.parse(error.message).message || error.message; } catch { return error.message; }
}

export default function RentBatchPanel({ initialBatch, onChange, onGenerated, onClose }) {
  const { t, locale } = useTranslation();
  const text = useCallback(key => t(`pages.rentBatch.${key}`), [t]);
  const [job, setJob] = useState(() => checkedRentBatch(initialBatch));
  const jobRef = useRef(job);
  const [budget, setBudget] = useState(() => Math.min(100, initialBatch.maximum_step_size || 500));
  const [pumping, setPumping] = useState(false);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState(null);
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [previewCursors, setPreviewCursors] = useState([null]);
  const [previewPage, setPreviewPage] = useState(0);
  const [previewRetry, setPreviewRetry] = useState(0);
  const run = useRef(false);
  const mounted = useRef(true);
  const pending = useRef(null);
  const request = useRef(null);
  const controlBusy = useRef(false);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/rent-charges', onClose);
  const money = value => new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(value);
  const update = useCallback(value => {
    const next = checkedRentBatch(value);
    jobRef.current = next;
    if (mounted.current) { setJob(next); onChange?.(next); }
    return next;
  }, [onChange]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; run.current = false; request.current?.abort(); };
  }, []);
  useEffect(() => { setPreviewCursors([null]); setPreviewPage(0); }, [job.plan_hash]);

  const step = useCallback(async () => {
    requireWrite();
    const controller = new AbortController();
    request.current = controller;
    const current = jobRef.current;
    const operation = api.post(`/rent-charges/batches/${encodeURIComponent(current.id)}/advance`,
      { cursor: current.cursor, budget: Number(budget) }, { signal: controller.signal });
    pending.current = operation;
    try {
      const value = await operation;
      if (mounted.current && isAllowed()) return update(value);
    } finally { pending.current = null; }
  }, [budget, requireWrite, isAllowed, update]);

  const pump = useCallback(() => {
    if (run.current || !isAllowed()) return;
    run.current = true; setPumping(true); setError(null);
    (async () => {
      try {
        while (run.current && mounted.current && isAllowed() && ['preparing', 'running'].includes(jobRef.current.state)) {
          await step();
        }
      } catch (failure) {
        if (mounted.current && failure.name !== 'AbortError') setError(readableError(failure));
      } finally {
        run.current = false;
        if (mounted.current) setPumping(false);
      }
    })();
  }, [isAllowed, step]);

  const control = async action => {
    requireWrite();
    if (controlBusy.current) return;
    controlBusy.current = true;
    run.current = false;
    setActing(true); setError(null);
    try {
      if (pending.current) {
        try { await pending.current; } catch {
          // A lost response may still have committed. Refresh before any new
          // cursor-bearing operation; never blindly repeat the old POST.
          update(await api.get(`/rent-charges/batches/${encodeURIComponent(jobRef.current.id)}`));
        }
      }
      requireWrite();
      const current = jobRef.current;
      const value = await api.post(`/rent-charges/batches/${encodeURIComponent(current.id)}/${action}`,
        { cursor: current.cursor, ...(action === 'confirm' ? { plan_hash: current.plan_hash } : {}) });
      if (mounted.current && isAllowed()) return update(value);
    } catch (failure) {
      if (mounted.current) setError(readableError(failure));
    } finally { controlBusy.current = false; if (mounted.current) setActing(false); }
  };

  const refresh = async () => {
    if (controlBusy.current) return;
    controlBusy.current = true;
    run.current = false; setActing(true); setError(null);
    try {
      if (pending.current) { try { await pending.current; } catch { /* GET resolves uncertainty below. */ } }
      const value = await api.get(`/rent-charges/batches/${encodeURIComponent(jobRef.current.id)}`);
      if (mounted.current && isAllowed()) update(value);
    } catch (failure) { if (mounted.current) setError(readableError(failure)); }
    finally { controlBusy.current = false; if (mounted.current) setActing(false); }
  };

  const primary = async () => {
    requireWrite();
    if (job.state === 'done') {
      onGenerated({ created_count: job.created_count, skipped_count: job.existing_count, batch_id: job.id });
      return;
    }
    if (job.state === 'ready' && !await control('confirm')) return;
    if (job.state === 'paused' && !await control('resume')) return;
    pump();
  };

  const previewCursor = previewCursors[previewPage];
  useEffect(() => {
    if (!job.plan_hash) return;
    const controller = new AbortController();
    let live = true;
    setPreview(null); setPreviewError(null);
    const params = new URLSearchParams({ page_size: '25' });
    if (previewCursor) params.set('cursor', previewCursor);
    api.get(`/rent-charges/batches/${encodeURIComponent(job.id)}/preview?${params}`, { signal: controller.signal })
      .then(value => {
        if (!value || !Array.isArray(value.items) || value.plan_hash !== job.plan_hash || typeof value.has_more !== 'boolean') throw new Error(text('invalidPreview'));
        if (live) setPreview(value);
      }).catch(failure => { if (live && failure.name !== 'AbortError') setPreviewError(readableError(failure)); });
    return () => { live = false; controller.abort(); };
  }, [job.id, job.plan_hash, previewCursor, previewRetry, text]);

  if (!canWrite) return null;
  const disabled = pumping || acting;
  const primaryKey = job.state === 'ready' ? 'confirm' : job.state === 'done' ? 'finish' : job.state === 'paused' ? 'resume' : 'continue';
  return <FormModal title={text('title')} fields={emptyFields} onSave={primary} onClose={onClose}
    closeOnSave={false} saveLabel={text(primaryKey)} saveDisabled={disabled || !!error || (job.state === 'ready' && !preview)}>
    <div className="rent-batch-summary" aria-live="polite">
      <p><strong>{text(`states.${job.state}`)}</strong> · {job.parameters.start_month} — {job.parameters.end_month}</p>
      <p>{text('prepared')}: {job.contract_count} · {text('prices')}: {job.price_count}<br />
        {text('created')}: {job.created_count} · {text('existing')}: {job.existing_count}</p>
      <p className="rent-batch-id">{text('identifier')}: <code>{job.id}</code></p>
      {!job.persistent && <p role="status">{text('memory')}</p>}
      {job.sealed_at && <p>{text('priceSnapshot')}: <time dateTime={job.sealed_at}>{new Date(job.sealed_at + 'Z').toLocaleString(locale)}</time></p>}
    </div>
    <p>{text('help')}</p>
    <p>{t('pages.rentGeneration.policy')}</p>
    {error && <div role="alert" className="alert-error">{error}</div>}
    <div className="rent-batch-actions">
      <label>{text('stepSize')} <input type="number" min="1" max={job.maximum_step_size || 500} step="1" value={budget}
        disabled={disabled} onChange={event => { setBudget(event.target.value); setError(null); }} /></label>
      <button type="button" className="btn btn-secondary" onClick={refresh} disabled={acting}>{text('refresh')}</button>
      {['preparing', 'running'].includes(job.state) && <button type="button" className="btn btn-secondary"
        onClick={() => control('pause')} disabled={acting}>{text('pause')}</button>}
      {job.state !== 'done' && job.created_count === 0 && job.existing_count === 0 && <button type="button"
        className="btn btn-secondary" onClick={() => control('restart')} disabled={disabled}>{text('restart')}</button>}
    </div>
    {previewError && <div role="alert">{previewError}<button type="button" className="btn btn-secondary"
      onClick={() => { setPreviewCursors([null]); setPreviewPage(0); setPreviewRetry(value => value + 1); }}>{text('retryPreview')}</button></div>}
    {preview && <>
      <p>{text('previewPage')} {previewPage + 1} · {text('previewHelp')}</p>
      <DataTable title={text('preview')} data={preview.items} columns={[
        { key: 'contract_number', label: t('pages.rentGeneration.contract') },
        { key: 'month', label: t('pages.rentGeneration.month') },
        { key: 'total_amount', label: t('pages.rentGeneration.amount'), render: money },
        { key: 'existing_charge_id', label: text('existing'), render: value => value ? text('yes') : '—' },
      ]} />
      <div className="rent-batch-actions">
        <button type="button" className="btn btn-secondary" disabled={!previewPage}
          onClick={() => setPreviewPage(value => value - 1)}>{text('previous')}</button>
        <button type="button" className="btn btn-secondary" disabled={!preview.next_cursor}
          onClick={() => { setPreviewCursors(value => [...value.slice(0, previewPage + 1), preview.next_cursor]); setPreviewPage(value => value + 1); }}>{text('next')}</button>
      </div>
    </>}
  </FormModal>;
}
