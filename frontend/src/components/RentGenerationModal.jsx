import useWriteAccess from '../hooks/useWriteAccess';
import { useMemo, useRef, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import FormModal from './FormModal';
import DataTable from './DataTable';
import { useAuth } from '../contexts/AuthContext';
import RentBatchPanel from './RentBatchPanel';
import { checkedRentBatch } from '../utils/rentBatch';

export default function RentGenerationModal({ contracts, onGenerated, onClose }) {
  const { t, locale } = useTranslation();
  const [preview, setPreview] = useState(null);
  const auth = useAuth();
  const storageKey = auth?.user?.id ? `immo.rent-batch.${auth.user.id}` : null;
  const [batch, setBatch] = useState(null);
  const [durable, setDurable] = useState(false);
  const [resumeError, setResumeError] = useState(null);
  const [restoring, setRestoring] = useState(false);
  const createKey = useRef(null);
  const batchRef = useRef(null);
  const [history, setHistory] = useState(null);
  const savedBatchId = storageKey ? localStorage.getItem(storageKey) : null;
  const [parameters, setParameters] = useState(() => ({
    start_month: new Date().toLocaleDateString('sv-SE').slice(0, 7),
    end_month: new Date().toLocaleDateString('sv-SE').slice(0, 7), contract_ids: [],
  }));
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/rent-charges', onClose);
  const text = key => t(`pages.rentGeneration.${key}`);
  const money = value => new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(Number(value));
  const fields = useMemo(() => [
    { key: 'start_month', label: t('pages.rentGeneration.startMonth'), type: 'month', required: true },
    { key: 'end_month', label: t('pages.rentGeneration.endMonth'), type: 'month', required: true },
    { key: 'contract_ids', label: t('pages.rentGeneration.contracts'), type: 'multiselect', default: [],
      options: contracts.filter(contract => contract.status === 'active').map(contract => ({ value: contract.id, label: contract.contract_number })) },
  ], [contracts, t]);

  const inspect = async values => {
    requireWrite();
    if (values.start_month > values.end_month) throw new Error(text('invalidRange'));
    const request = { start_month: values.start_month, end_month: values.end_month,
      ...(values.contract_ids.length ? { contract_ids: values.contract_ids } : {}) };
    let result;
    if (durable) {
      const signature = JSON.stringify(request);
      if (createKey.current?.signature !== signature) createKey.current = { signature, key: crypto.randomUUID() };
      result = { policy: 'durable_batch', batch: await api.post('/rent-charges/batches', { ...request, idempotency_key: createKey.current.key }) };
    } else result = await api.post('/rent-charges/preview', request);
    if (result?.policy === 'durable_batch') {
      if (isAllowed()) rememberBatch(checkedRentBatch(result.batch));
      return;
    }
    if (!result || result.policy !== 'full_month' || !Array.isArray(result.candidates)
      || !Array.isArray(result.existing) || !Array.isArray(result.skipped_contracts)
      || typeof result.preview_hash !== 'string'
      || !Number.isFinite(Number(result.total_amount))) throw new Error(text('invalidPreview'));
    if (!isAllowed()) return;
    setParameters(values);
    setPreview(result);
  };
  const generate = async () => {
    requireWrite();
    const result = await api.post('/rent-charges/generate', {
      start_month: parameters.start_month, end_month: parameters.end_month,
      ...(parameters.contract_ids.length ? { contract_ids: parameters.contract_ids } : {}),
      preview_hash: preview.preview_hash,
    });
    if (result?.policy === 'durable_batch') {
      if (isAllowed()) rememberBatch(checkedRentBatch(result.batch));
      return;
    }
    if (!Number.isInteger(result?.created_count) || !Number.isInteger(result?.skipped_count)) {
      throw new Error(text('invalidPreview'));
    }
    if (isAllowed()) onGenerated(result);
  };

  const rememberBatch = value => {
    batchRef.current = value;
    if (storageKey) localStorage.setItem(storageKey, value.id);
    setBatch(value);
  };
  const restoreBatch = async () => {
    requireWrite(); setRestoring(true); setResumeError(null);
    try {
      const value = checkedRentBatch(await api.get(`/rent-charges/batches/${encodeURIComponent(savedBatchId)}`));
      if (isAllowed()) rememberBatch(value);
    } catch (error) { setResumeError(error.message); }
    finally { setRestoring(false); }
  };
  const loadHistory = async cursor => {
    requireWrite(); setRestoring(true); setResumeError(null);
    try {
      const params = new URLSearchParams({ page_size: '25' });
      if (cursor) params.set('cursor', cursor);
      const value = await api.get(`/rent-charges/batches?${params}`);
      if (!value || !Array.isArray(value.items) || typeof value.has_more !== 'boolean') throw new Error(t('pages.rentBatch.invalidPreview'));
      if (isAllowed()) setHistory(value);
    } catch (error) { setResumeError(error.message); }
    finally { setRestoring(false); }
  };
  const openHistory = async id => {
    requireWrite(); setRestoring(true); setResumeError(null);
    try {
      const value = checkedRentBatch(await api.get(`/rent-charges/batches/${encodeURIComponent(id)}`));
      if (isAllowed()) rememberBatch(value);
    } catch (error) { setResumeError(error.message); }
    finally { setRestoring(false); }
  };

  if (!canWrite) return null;
  if (batch) return <RentBatchPanel initialBatch={batch} onChange={rememberBatch} onGenerated={onGenerated} onClose={onClose} />;
  return <FormModal title={text('title')} fields={preview ? [] : fields} initial={parameters}
    onSave={preview ? generate : inspect} onClose={() => { if (!batchRef.current) onClose(); }} closeOnSave={!!preview}
    saveLabel={text(preview ? 'generate' : 'preview')} saveDisabled={!!preview && !preview.candidates.length}>
    <p>{text(preview ? 'policy' : 'selectionHelp')}</p>
    {!preview && <>
      <label><input type="checkbox" checked={durable} onChange={event => setDurable(event.target.checked)} /> {t('pages.rentBatch.saveWorkflow')}</label>
      {savedBatchId && <p><button type="button" className="btn btn-secondary" onClick={restoreBatch} disabled={restoring}>
        {t('pages.rentBatch.restore')}</button></p>}
      <p><button type="button" className="btn btn-secondary" onClick={() => loadHistory(null)} disabled={restoring}>{t('pages.rentBatch.history')}</button></p>
      {history && <div className="rent-batch-history">
        {history.items.length === 0 && <p>{t('pages.rentBatch.noHistory')}</p>}
        {history.items.map(item => <p key={item.id}>
          <button type="button" className="btn btn-secondary" disabled={restoring || !item.available} onClick={() => openHistory(item.id)}>
            {new Date(item.created_at + 'Z').toLocaleString(locale)} · {t(`pages.rentBatch.states.${item.state}`)}</button>
          {!item.available && <span> {t('pages.rentBatch.scopeChanged')}</span>}
        </p>)}
        {history.next_cursor && <button type="button" className="btn btn-secondary" disabled={restoring}
          onClick={() => loadHistory(history.next_cursor)}>{t('pages.rentBatch.next')}</button>}
      </div>}
      {resumeError && <div role="alert">{resumeError}</div>}
    </>}
    {preview && <>
      <p>{text('newItems')}: <strong>{preview.candidates.length}</strong> · {text('total')}: <strong>{money(preview.total_amount)}</strong></p>
      <p>{text('existing')}: {preview.existing.length} · {text('skipped')}: {preview.skipped_contracts.length}</p>
      <DataTable title={text('preview')} data={preview.candidates} columns={[
        { key: 'contract_number', label: text('contract') },
        { key: 'month', label: text('month') },
        { key: 'due_date', label: text('dueDate'), type: 'date' },
        { key: 'total_amount', label: text('amount'), render: money },
        { key: 'partial_month', label: text('partialMonth'), render: value => value ? text('yes') : '—' },
      ]} />
      <button className="btn btn-secondary" type="button" onClick={() => setPreview(null)}>{text('changeSelection')}</button>
    </>}
  </FormModal>;
}
