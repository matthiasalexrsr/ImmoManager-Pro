import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useDataStore } from '../contexts/DataStoreContext';
import useWriteAccess from '../hooks/useWriteAccess';
import useBookingChoices from '../hooks/useBookingChoices';
import { useConfirm } from './ConfirmDialog';
import { checkedBankImport, checkedBankPreview } from '../utils/bankImport';
import './BankImportPanel.css';

const initialMapping = { version: 1, format: 'csv', encoding: 'utf-8-sig', delimiter: ';', date_column: 'date',
  amount_column: 'amount', text_column: 'text', date_format: '%Y-%m-%d', decimal_separator: 'legacy',
  thousands_separator: null, reference_column: null, reference_namespace: 'bank_transaction_id', currency: 'EUR' };

export default function BankImportPanel({ initialAccount = '', onClose, onImported }) {
  const { t, locale } = useTranslation();
  const text = key => t(`bankImport.${key}`);
  const store = useDataStore();
  const confirm = useConfirm();
  const [accountId, setAccountId] = useState(initialAccount);
  const accountRef = useRef(accountId);
  useEffect(() => { accountRef.current = accountId; }, [accountId]);
  const choices = useBookingChoices('accounts', accountId, text('account'));
  const [mapping, setMapping] = useState(initialMapping);
  const [file, setFile] = useState(null);
  const [job, setJob] = useState(null);
  const [imports, setImports] = useState({ items: [], next_cursor: null, has_more: false });
  const [listHistory, setListHistory] = useState([null]);
  const [listPage, setListPage] = useState(0);
  const [revision, setRevision] = useState(0);
  const [preview, setPreview] = useState(null);
  const [previewHistory, setPreviewHistory] = useState([null]);
  const [previewPage, setPreviewPage] = useState(0);
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const operation = useRef(null);
  const generation = useRef(0);
  const submitting = useRef(false);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/bookings', () => {
    generation.current += 1;
    operation.current?.abort();
    setFile(null);
    setBusy(false);
  });
  useEffect(() => () => { generation.current += 1; operation.current?.abort(); }, []);

  useEffect(() => {
    if (!accountId) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ account_id: accountId, page_size: '25' });
    if (listHistory[listPage]) params.set('cursor', listHistory[listPage]);
    api.get(`/bookings/imports?${params}`, { signal: controller.signal }).then(value => {
      if (controller.signal.aborted) return;
      if (!Array.isArray(value?.items) || typeof value.has_more !== 'boolean'
        || (value.has_more ? typeof value.next_cursor !== 'string' : value.next_cursor !== null)) throw new Error('bankImport.invalidResponse');
      value.items.forEach(item => checkedBankImport(item, accountId));
      setImports(value);
    }).catch(failure => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, [accountId, listHistory, listPage, revision]);

  useEffect(() => {
    if (!job) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ page_size: String(Math.min(100, job.maximum_page_size)), errors_only: String(errorsOnly) });
    if (previewHistory[previewPage]) params.set('cursor', previewHistory[previewPage]);
    setLoading(true); setPreview(null);
    api.get(`/bookings/imports/${encodeURIComponent(job.id)}/preview?${params}`, { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) setPreview(checkedBankPreview(value, job));
    }).catch(failure => { if (!controller.signal.aborted) setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [job, errorsOnly, previewHistory, previewPage, revision]);

  const accept = value => {
    const checked = checkedBankImport(value, accountRef.current);
    setJob(checked); setPreviewHistory([null]); setPreviewPage(0); setPreview(null);
    return checked;
  };
  const changeAccount = value => {
    generation.current += 1; operation.current?.abort();
    accountRef.current = value; setAccountId(value); setJob(null); setPreview(null);
    setImports({ items: [], has_more: false, next_cursor: null }); setListHistory([null]); setListPage(0); setError(null);
  };
  const changeMapping = (key, value) => { setMapping(current => ({ ...current, [key]: value })); setJob(null); setPreview(null); setError(null); };
  const perform = async action => {
    if (submitting.current) return;
    const capturedGeneration = generation.current;
    submitting.current = true; setBusy(true); setError(null);
    const controller = new AbortController();
    operation.current = controller;
    try {
      await action(controller.signal, capturedGeneration);
    } catch (failure) {
      if (!controller.signal.aborted && capturedGeneration === generation.current) setError(failure.message);
    } finally {
      submitting.current = false;
      if (operation.current === controller) operation.current = null;
      if (capturedGeneration === generation.current) setBusy(false);
    }
  };
  const upload = event => {
    event.preventDefault();
    if (!file || !accountId || !isAllowed()) return;
    perform(async (signal, captured) => {
      requireWrite();
      const body = new FormData();
      body.set('account_id', accountId); body.set('mapping', JSON.stringify(mapping)); body.set('file', file);
      const value = await api.postForm('/bookings/imports', body, { signal });
      if (signal.aborted || captured !== generation.current || !isAllowed()) return;
      accept(value); setRevision(value => value + 1);
    });
  };
  const open = id => perform(async (signal, captured) => {
    const value = await api.get(`/bookings/imports/${encodeURIComponent(id)}`, { signal });
    if (!signal.aborted && captured === generation.current) { accept(value); setError(null); }
  });
  const approve = () => {
    if (!job || !isAllowed()) return;
    perform(async (signal, captured) => {
      requireWrite();
      if (!await confirm(text('confirmQuestion'))) return;
      if (signal.aborted || captured !== generation.current || !isAllowed()) return;
      requireWrite();
      const value = await api.post(`/bookings/imports/${encodeURIComponent(job.id)}/confirm`,
        { revision: job.revision, preview_hash: job.preview_hash }, { signal });
      if (signal.aborted || captured !== generation.current || !isAllowed()) return;
      accept(value); setRevision(value => value + 1);
      store?.invalidateRelated('bookings', 'accounts'); onImported?.();
    });
  };
  const money = cents => cents === null ? '—' : new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(cents / 100);
  const errorMessage = error === 'bankImport.invalidResponse' ? text('invalidResponse') : error;
  return <section className="card bank-import-panel" aria-label={text('title')} aria-busy={busy}>
    <div className="card-header"><h2>{text('title')}</h2><button type="button" className="btn btn-secondary" disabled={busy} onClick={onClose}>{t('ui.buttons.close')}</button></div>
    <div className="card-body"><p>{text('description')}</p><p className="text-muted">{text('duplicatesHint')}</p>
      <label>{text('account')}<select value={accountId} disabled={busy || choices.disabled} onChange={event => changeAccount(event.target.value)}>
        <option value="">{text('chooseAccount')}</option>{choices.options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select></label>{choices.hint}
      {errorMessage && <div className="alert alert-error" role="alert">{errorMessage}<button className="btn btn-secondary" type="button" disabled={busy} onClick={() => {
        setError(null); setPreviewHistory([null]); setPreviewPage(0); setRevision(value => value + 1);
        if (job) open(job.id);
      }}>{t('ui.buttons.retry')}</button></div>}
      {canWrite && <form onSubmit={upload} onKeyDownCapture={event => { if (event.key === 'Enter' && event.target.name?.startsWith('lookup_')) event.preventDefault(); }}>
        <fieldset disabled={busy}><legend>{text('fileAndMapping')}</legend><div className="bank-import-grid">
          <label>{text('file')}<input type="file" accept=".csv,.sta,.940,.mt940,.txt" required onChange={event => { setFile(event.target.files?.[0] || null); setJob(null); setPreview(null); }} /></label>
          <label>{text('format')}<select value={mapping.format} onChange={event => changeMapping('format', event.target.value)}><option value="csv">CSV</option><option value="mt940">MT940</option></select></label>
          <label>{text('encoding')}<select value={mapping.encoding} onChange={event => changeMapping('encoding', event.target.value)}><option value="utf-8-sig">UTF-8</option><option value="utf-16">UTF-16 (BOM)</option><option value="cp1252">Windows-1252</option></select></label>
          {mapping.format === 'csv' && <>
            <label>{text('delimiter')}<select value={mapping.delimiter} onChange={event => changeMapping('delimiter', event.target.value)}><option value=";">;</option><option value=",">,</option><option value={'\t'}>Tab</option></select></label>
            {['date_column', 'amount_column', 'text_column', 'reference_column'].map(key => <label key={key}>{text(key)}<input value={mapping[key] || ''} maxLength={200} required={['date_column', 'amount_column'].includes(key)}
              onChange={event => changeMapping(key, event.target.value || (['text_column', 'reference_column'].includes(key) ? null : ''))} /></label>)}
            <label>{text('dateFormat')}<select value={mapping.date_format} onChange={event => changeMapping('date_format', event.target.value)}><option value="%Y-%m-%d">YYYY-MM-DD</option><option value="%d.%m.%Y">DD.MM.YYYY</option><option value="%m/%d/%Y">MM/DD/YYYY</option></select></label>
            <label>{text('decimal')}<select value={mapping.decimal_separator} onChange={event => changeMapping('decimal_separator', event.target.value)}><option value="legacy">{text('legacyDecimal')}</option><option value=",">,</option><option value=".">.</option></select></label>
            <label>{text('thousands')}<select value={mapping.thousands_separator || ''} onChange={event => changeMapping('thousands_separator', event.target.value || null)}><option value="">{text('none')}</option><option value=".">.</option><option value=",">,</option><option value=" ">{text('space')}</option><option value={'\u00a0'}>NBSP (U+00A0)</option><option value={'\u202f'}>NNBSP (U+202F)</option></select></label>
          </>}
        </div><p>{text(mapping.format === 'mt940' ? 'mt940Hint' : 'referenceHint')}</p>
          <button type="submit" className="btn btn-primary" disabled={!accountId || !file || choices.disabled}>{text(busy ? 'checking' : 'checkFile')}</button>
        </fieldset>
      </form>}
      {accountId && <details className="bank-import-history"><summary>{text('history')}</summary>
        {imports.items.map(item => <button type="button" className="btn btn-secondary bank-import-history-item" disabled={busy} key={item.id} onClick={() => open(item.id)}>
          {item.filename} · {text(item.state)} · {item.row_count} {text('rows')}</button>)}
        {!imports.items.length && <p>{text('noImports')}</p>}
        <div className="bank-import-paging"><button type="button" className="btn btn-secondary" disabled={busy || !listPage} onClick={() => setListPage(value => value - 1)}>{t('bookingPages.previous')}</button>
          <button type="button" className="btn btn-secondary" disabled={busy || !imports.has_more} onClick={() => { setListHistory(current => [...current.slice(0, listPage + 1), imports.next_cursor]); setListPage(value => value + 1); }}>{t('bookingPages.next')}</button></div>
      </details>}
      {job && <div className="bank-import-preview">
        <h3>{text('preview')}: {job.filename}</h3><p role="status">{text(job.state)} · {job.row_count} {text('rows')} · {job.error_count} {text('errors')} · {job.duplicate_count} {text('duplicates')}</p>
        {!job.persistent && <p className="alert alert-warning">{text('memoryHint')}</p>}
        <dl className="bank-import-provenance"><dt>SHA-256</dt><dd>{job.source_sha256}</dd><dt>{text('mappingHash')}</dt><dd>{job.mapping_hash}</dd></dl>
        <label><input type="checkbox" checked={errorsOnly} onChange={event => { setErrorsOnly(event.target.checked); setPreviewHistory([null]); setPreviewPage(0); }} />{text('errorsOnly')}</label>
        {loading && <p role="status">{t('ui.table.loading')}</p>}
        {preview && <><div className="table-scroll" tabIndex={0} role="region" aria-label={text('preview')}><table className="data-table"><thead><tr>
          {[text('line'), text('date'), text('amount'), text('text'), text('bankReference'), text('result')].map(label => <th scope="col" key={label}>{label}</th>)}
        </tr></thead><tbody>{preview.items.map(row => <tr key={row.ordinal}><td>{row.source_line}</td><td>{row.booking_date || '—'}</td><td>{money(row.amount_cents)}</td>
          <td>{row.payment_text}</td><td>{row.bank_reference || '—'}</td><td>{row.error_message || text(row.duplicate_booking_id ? 'duplicate' : 'valid')}</td></tr>)}</tbody></table></div>
          {!preview.items.length && <p>{text('noRows')}</p>}
          <div className="bank-import-paging"><button type="button" className="btn btn-secondary" disabled={busy || !previewPage} onClick={() => setPreviewPage(value => value - 1)}>{t('bookingPages.previous')}</button>
            <span>{previewPage + 1}</span><button type="button" className="btn btn-secondary" disabled={busy || !preview.has_more} onClick={() => { setPreviewHistory(current => [...current.slice(0, previewPage + 1), preview.next_cursor]); setPreviewPage(value => value + 1); }}>{t('bookingPages.next')}</button></div></>}
        {job.state === 'invalid' && <p className="alert alert-error">{text('invalidHint')}</p>}
        {job.state === 'ready' && canWrite && <button className="btn btn-primary" type="button" disabled={busy || loading || !preview || Boolean(error)} onClick={approve}>{text(busy ? 'publishing' : 'approve')}</button>}
        {job.state === 'committed' && <p className="alert alert-success" role="status">{text('published')}: {job.published_count}</p>}
      </div>}
    </div>
  </section>;
}
