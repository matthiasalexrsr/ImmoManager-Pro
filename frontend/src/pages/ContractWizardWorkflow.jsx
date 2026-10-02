import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useAuth } from '../contexts/AuthContext';
import { useConfirm } from '../components/ConfirmDialog';
import ContractReferencePicker from '../components/ContractReferencePicker';
import useWriteAccess from '../hooks/useWriteAccess';
import './ContractWizard.css';

const LegacyBuilder = lazy(() => import('./LegacyContractWizard'));
const endpoint = '/contract-wizard';
const blank = () => ({ property_id: '', unit_id: '', tenant_id: null, new_tenant: { full_name: '', email: null },
  contract_number: '', contract_status: 'draft', start_date: new Date().toISOString().slice(0, 10), end_date: null,
  notice_period: null, deposit_amount: '0.00', index_rent: 'fixed', service_charge_settlement: 'annual',
  landlord_name: '', landlord_address: '', template_id: null, terms: '', attachment_ids: [], metadata_only_attachment_ids: [], create_handover: false });
const verified = result => result?.id && Number.isSafeInteger(result.revision) && result.revision > 0
  && ['draft', 'reviewed', 'committed', 'signed'].includes(result.state) && result.data?.property_id
  && Array.isArray(result.data.attachment_ids) && Array.isArray(result.data.metadata_only_attachment_ids)
  && (result.state === 'draft' || (result.review?.property?.name && result.review?.unit && result.review?.tenant?.full_name
    && result.review?.parameters && Array.isArray(result.review.attachments) && /^[a-f0-9]{64}$/.test(result.review_hash || '')
    && /^[a-f0-9]{64}$/.test(result.pdf_sha256 || '') && result.preview_url))
  && (!['committed', 'signed'].includes(result.state) || (result.contract_id && result.document_id && result.pdf_url));
const reference = (ref, path, body) => {
  const encoded = JSON.stringify({ path, body });
  if (ref.current?.encoded !== encoded) ref.current = { encoded, key: crypto.randomUUID() };
  return ref.current.key;
};

export default function ContractWizardWorkflow() {
  const { t, locale } = useTranslation();
  const label = key => t(`contractWizard.workflow.${key}`);
  const { user } = useAuth();
  const { canWrite, requireWrite, isAllowed } = useWriteAccess('/contract-wizard');
  const confirm = useConfirm();
  const [params, setParams] = useSearchParams();
  const selectedId = params.get('draft');
  const [legacy, setLegacy] = useState(false);
  const [row, setRow] = useState(null);
  const [form, setForm] = useState(null);
  const [journal, setJournal] = useState({ items: [], total: 0 });
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [uncertain, setUncertain] = useState(null);
  const [propertyInfo, setPropertyInfo] = useState(null);
  const [templates, setTemplates] = useState({ items: [], total: 0 });
  const [templateDraft, setTemplateDraft] = useState(null);
  const [attachmentId, setAttachmentId] = useState('');
  const [attachments, setAttachments] = useState({ items: [], has_more: false });
  const [signatures, setSignatures] = useState({ items: [], has_more: false });
  const [signature, setSignature] = useState(null);
  const running = useRef(false);
  const operation = useRef(null);
  const principal = useRef(user?.id);
  const previewRef = useRef(null);
  const activePortfolio = useRef(null);
  activePortfolio.current = propertyInfo?.portfolio_id;
  const mutable = row?.state === 'draft' || row?.state === 'reviewed' || !row;
  const dirty = row && JSON.stringify(row.data) !== JSON.stringify(form);
  const blocked = busy || loading || !canWrite || !!uncertain;
  const boundProperty = useCallback(value => setPropertyInfo(previous => previous?.id === value?.id
    && previous?.portfolio_id === value?.portfolio_id ? previous : value), []);
  const reloadJournal = useCallback(async signal => {
    const result = await api.get(`${endpoint}/drafts?offset=${page * 10}&limit=10`, { signal });
    if (!Array.isArray(result?.items) || !Number.isSafeInteger(result.total)) throw new Error(t('contractWizard.workflow.malformed'));
    if (!signal?.aborted) setJournal(result);
  }, [page, t]);
  useEffect(() => {
    principal.current = user?.id;
    setRow(null); setForm(null); setError(''); setUncertain(null); operation.current = null;
    setPropertyInfo(null); setTemplates({ items: [], total: 0 }); setTemplateDraft(null); setSignature(null);
    setAttachments({ items: [], has_more: false }); setSignatures({ items: [], has_more: false }); setAttachmentId(''); setNotice('');
  }, [user?.id]);
  useEffect(() => {
    const controller = new AbortController();
    reloadJournal(controller.signal).catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [reloadJournal, user?.id]);
  useEffect(() => {
    if (!selectedId) return undefined;
    const controller = new AbortController();
    setLoading(true);
    api.get(`${endpoint}/drafts/${encodeURIComponent(selectedId)}`, { signal: controller.signal }).then(result => {
      if (!verified(result)) throw new Error(t('contractWizard.workflow.malformed'));
      if (!controller.signal.aborted) { setRow(result); setForm(structuredClone(result.data)); setUncertain(null); }
    }).catch(err => { if (!controller.signal.aborted) setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  // A language change must not replace the user's edited fields.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, user?.id]);
  useEffect(() => {
    const controller = new AbortController();
    if (!propertyInfo?.portfolio_id) { setTemplates({ items: [], total: 0 }); return undefined; }
    api.get(`${endpoint}/templates?portfolio_id=${encodeURIComponent(propertyInfo.portfolio_id)}&offset=0&limit=25`, { signal: controller.signal })
      .then(result => { if (Array.isArray(result?.items) && !controller.signal.aborted) setTemplates(result); })
      .catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [propertyInfo?.portfolio_id]);
  useEffect(() => {
    if (!row?.contract_id) { setAttachments({ items: [], has_more: false }); setSignatures({ items: [], has_more: false }); return undefined; }
    const controller = new AbortController();
    Promise.all([api.get(`${endpoint}/drafts/${row.id}/attachments`, { signal: controller.signal }),
      api.get(`${endpoint}/drafts/${row.id}/signatures`, { signal: controller.signal })]).then(([files, evidence]) => {
        if (!Array.isArray(files?.items) || !Array.isArray(evidence?.items)) throw new Error(t('contractWizard.workflow.malformed'));
        if (!controller.signal.aborted) { setAttachments(files); setSignatures(evidence); }
      }).catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [row?.id, row?.contract_id, row?.revision, t]);

  const field = (key, value) => setForm(current => ({ ...current, [key]: value }));
  const accept = result => {
    if (!verified(result)) throw new Error(label('malformed'));
    setRow(result); setForm(structuredClone(result.data)); setUncertain(null); setNotice(label('saved'));
    if (result.state === 'signed') setSignature(null);
    setParams({ draft: result.id }, { replace: true });
    if (result.state === 'reviewed') requestAnimationFrame(() => { previewRef.current?.focus(); previewRef.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' }); });
    reloadJournal().catch(err => setError(err.message));
  };
  const execute = async (path, body, { confirmation, template = false } = {}) => {
    if (running.current) return;
    running.current = true; setBusy(true); setError(''); setNotice('');
    const actor = user?.id;
    try {
      requireWrite();
      if (confirmation && !await confirm(confirmation)) return;
      if (!isAllowed() || principal.current !== actor) return;
      const command = { ...body, idempotency_key: reference(operation, path, body) };
      let result;
      try {
        result = await api.post(path, command);
        if (template ? (!result?.id || !Number.isSafeInteger(result.version) || !result.body) : !verified(result)) throw new Error(label('malformed'));
      }
      catch (err) { if (err.isNetwork || !err.statusCode) setUncertain({ path, command, template }); throw err; }
      if (!isAllowed() || principal.current !== actor) return;
      if (template) {
        if (!result?.id || !Number.isSafeInteger(result.version) || !result.body) throw new Error(label('malformed'));
        setTemplates(current => ({ items: [result, ...current.items.filter(item => item.id !== result.id)], total: current.total + 1 }));
        field('template_id', result.id); setTemplateDraft(null); setNotice(label('versionSaved'));
      } else accept(result);
    } catch (err) { if (principal.current === actor) setError(err.message); }
    finally { running.current = false; setBusy(false); }
  };
  const retry = async () => {
    if (running.current || !uncertain) return;
    running.current = true; setBusy(true); setError('');
    const actor = user?.id;
    try {
      requireWrite();
      const result = await api.post(uncertain.path, uncertain.command);
      if (!isAllowed() || principal.current !== actor) return;
      if (uncertain.template) {
        if (!result?.id || !result.body || !Number.isSafeInteger(result.version)) throw new Error(label('malformed'));
        setTemplates(current => ({ ...current, items: [result, ...current.items.filter(item => item.id !== result.id)] }));
        field('template_id', result.id); setTemplateDraft(null); setUncertain(null);
      } else accept(result);
    } catch (err) { if (principal.current === actor) setError(err.message); }
    finally { running.current = false; setBusy(false); }
  };
  const save = event => {
    event.preventDefault();
    execute(row ? `${endpoint}/drafts/${row.id}/edit` : `${endpoint}/drafts`,
      row ? { expected_revision: row.revision, data: form } : { data: form });
  };
  const download = async (path, name, sha256, pdf = false) => {
    if (running.current) return;
    running.current = true; setBusy(true); setError('');
    const actor = user?.id;
    let url;
    try {
      const blob = await api.getBlob(path);
      if (!blob?.size || (pdf && blob.type.split(';')[0] !== 'application/pdf')) throw new Error(label('malformed'));
      const bytes = await blob.arrayBuffer();
      if (pdf && new TextDecoder().decode(bytes.slice(0, 5)) !== '%PDF-') throw new Error(label('malformed'));
      if (sha256) {
        const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(value => value.toString(16).padStart(2, '0')).join('');
        if (hash !== sha256) throw new Error(label('malformed'));
      }
      if (principal.current !== actor) return;
      url = URL.createObjectURL(blob);
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = name;
      document.body.appendChild(anchor); anchor.click(); anchor.remove(); setNotice(label('downloaded'));
    } catch (err) { if (principal.current === actor) setError(err.message); }
    finally { if (url) URL.revokeObjectURL(url); running.current = false; setBusy(false); }
  };
  const money = value => {
    const currency = row?.review?.portfolio?.currency || 'EUR';
    try { return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(Number(value || 0)); }
    catch { return `${new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value || 0))} ${currency}`; }
  };
  const moreTemplates = async () => {
    if (running.current || !activePortfolio.current) return;
    running.current = true; setBusy(true); setError('');
    const actor = user?.id, portfolio = activePortfolio.current;
    try {
      const result = await api.get(`${endpoint}/templates?portfolio_id=${encodeURIComponent(portfolio)}&offset=${templates.items.length}&limit=25`);
      if (!Array.isArray(result?.items) || !Number.isSafeInteger(result.total)) throw new Error(label('malformed'));
      if (principal.current !== actor || activePortfolio.current !== portfolio) return;
      setTemplates(current => ({ ...result, items: [...current.items, ...result.items] }));
    } catch (err) { if (principal.current === actor) setError(err.message); }
    finally { running.current = false; setBusy(false); }
  };
  const moreEvidence = async kind => {
    if (running.current) return;
    running.current = true; setBusy(true); setError('');
    const actor = user?.id;
    try {
      const current = kind === 'attachments' ? attachments : signatures;
      const result = await api.get(`${endpoint}/drafts/${row.id}/${kind}?offset=${current.items.length}&limit=25`);
      if (!Array.isArray(result?.items) || typeof result.has_more !== 'boolean') throw new Error(label('malformed'));
      if (principal.current !== actor) return;
      const setter = kind === 'attachments' ? setAttachments : setSignatures;
      setter(previous => ({ ...result, items: [...previous.items, ...result.items] }));
    } catch (err) { if (principal.current === actor) setError(err.message); }
    finally { running.current = false; setBusy(false); }
  };
  const switchDraft = async id => {
    if (running.current || uncertain) return;
    if (form && (dirty || !row) && !await confirm(label('switchConfirm'))) return;
    setError(''); setNotice(''); setSignature(null); setTemplateDraft(null); setPropertyInfo(null);
    if (id) setParams({ draft: id });
    else if (isAllowed()) { setRow(null); setForm(blank()); operation.current = null; setParams({}, { replace: true }); }
  };

  return <div className="contract-workspace" aria-busy={busy || loading}>
    <header className="contract-heading"><div><p className="contract-eyebrow">{label('eyebrow')}</p><h1>{label('title')}</h1><p>{label('description')}</p></div>
      <div className="contract-actions"><Link to="/contracts" className="btn btn-secondary">{label('contracts')}</Link>
        <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => setLegacy(value => !value)}>{legacy ? label('backWorkflow') : label('legacy')}</button></div></header>
    {error && <div role="alert" className="contract-alert">{error}</div>}
    {notice && <p role="status">{notice}</p>}
    {uncertain && <div className="contract-alert" role="alert"><p>{label('uncertain')}</p>
      <button type="button" className="btn btn-primary" disabled={busy || !canWrite} onClick={retry}>{label('retryExact')}</button></div>}
    {legacy ? <Suspense fallback={<p role="status">{label('loading')}</p>}><LegacyBuilder /></Suspense> : <>
      <section className="contract-panel"><div className="contract-panel-heading"><h2>{label('journal')}</h2>
        <button type="button" className="btn btn-primary" disabled={blocked} onClick={() => switchDraft(null)}>{label('newDraft')}</button></div>
        {!journal.items.length && <p>{label('empty')}</p>}
        <div className="contract-journal">{journal.items.map(item => <button type="button" key={item.id} disabled={busy || !!uncertain || item.available === false}
          aria-pressed={selectedId === item.id} onClick={() => switchDraft(item.id)}><strong>{item.data?.contract_number || label('unavailable')}</strong><span>{label(item.state || 'unavailable')} · {item.revision || '–'}</span></button>)}</div>
        <div className="contract-pagination"><span>{journal.total} {label('savedDrafts')}</span>
          <button type="button" disabled={busy || page === 0} onClick={() => setPage(page - 1)}>{label('previous')}</button>
          <button type="button" disabled={busy || (page + 1) * 10 >= journal.total} onClick={() => setPage(page + 1)}>{label('next')}</button></div></section>
      {loading && <p role="status">{label('loading')}</p>}
      {form && <>
        {row?.persistent === false && <p className="contract-alert">{label('transient')}</p>}
        {mutable && <form onSubmit={save} className="contract-panel" aria-busy={busy}>
          <div className="contract-panel-heading"><h2>{label('prepare')}</h2><span>{row ? `${label('revision')} ${row.revision}` : label('unsaved')}</span></div>
          <fieldset disabled={blocked}>
            <legend>1 · {label('objectParties')}</legend><div className="contract-grid">
              <ContractReferencePicker kind="properties" label={label('property')} value={form.property_id} required disabled={blocked}
                onSelected={boundProperty} onChange={(id, selected) => { field('property_id', id); field('unit_id', ''); field('attachment_ids', []); field('metadata_only_attachment_ids', []); field('template_id', null); setAttachmentId(''); boundProperty(selected); }} />
              <ContractReferencePicker kind="units" label={label('unit')} propertyId={form.property_id} value={form.unit_id} required disabled={blocked} onChange={id => field('unit_id', id)} />
              <label>{label('landlord')} *<input required value={form.landlord_name} onChange={event => field('landlord_name', event.target.value)} /></label>
              <label>{label('landlordAddress')} *<textarea required value={form.landlord_address} onChange={event => field('landlord_address', event.target.value)} /></label>
            </div>
            <div className="contract-tenant-choice"><label><input type="radio" name="tenant-mode" checked={!!form.new_tenant} onChange={() => { field('tenant_id', null); field('new_tenant', { full_name: '', email: null }); }} />{label('newTenant')}</label>
              <label><input type="radio" name="tenant-mode" checked={!form.new_tenant} onChange={() => { field('new_tenant', null); field('tenant_id', ''); }} />{label('existingTenant')}</label></div>
            {form.new_tenant ? <div className="contract-grid">{['full_name', 'email', 'phone', 'address_line', 'postal_code', 'city', 'country', 'payment_method', 'sepa_mandate'].map(key => <label key={key}>{label(`tenant_${key}`)}{key === 'full_name' && ' *'}<input required={key === 'full_name'} type={key === 'email' ? 'email' : 'text'}
              value={form.new_tenant[key] || ''} onChange={event => field('new_tenant', { ...form.new_tenant, [key]: event.target.value || null })} /></label>)}</div>
              : <ContractReferencePicker kind="tenants" label={label('existingTenant')} value={form.tenant_id || ''} required disabled={blocked} onChange={id => field('tenant_id', id)} />}
          </fieldset>
          <fieldset disabled={blocked}><legend>2 · {label('tenancy')}</legend><div className="contract-grid">
            <label>{label('number')} *<input required value={form.contract_number} onChange={event => field('contract_number', event.target.value)} /></label>
            <label>{label('status')}<select value={form.contract_status} onChange={event => field('contract_status', event.target.value)}><option value="draft">{label('draftNonReserving')}</option><option value="active">{label('activeReserved')}</option></select></label>
            <label>{label('start')} *<input type="date" required value={form.start_date} onChange={event => field('start_date', event.target.value)} /></label>
            <label>{label('end')}<input type="date" min={form.start_date} value={form.end_date || ''} onChange={event => field('end_date', event.target.value || null)} /></label>
            <label>{label('noticePeriod')}<input value={form.notice_period || ''} onChange={event => field('notice_period', event.target.value || null)} /></label>
            <label>{label('deposit')}<input inputMode="decimal" type="number" step="0.01" min="0" value={form.deposit_amount} onChange={event => field('deposit_amount', event.target.value)} /></label>
            <label>{label('rentModel')}<select value={form.index_rent} onChange={event => field('index_rent', event.target.value)}>{['fixed', 'index', 'stepped'].map(value => <option key={value} value={value}>{label(value)}</option>)}</select></label>
            <label>{label('settlement')}<select value={form.service_charge_settlement} onChange={event => field('service_charge_settlement', event.target.value)}><option value="annual">{label('annual')}</option><option value="monthly">{label('monthly')}</option></select></label>
          </div><p className="contract-hint">{label('noCash')}</p><p className="contract-hint">{label('rentHint')}</p>
            <label className="contract-checkbox"><input type="checkbox" checked={form.create_handover} onChange={event => field('create_handover', event.target.checked)} />{label('handover')}</label></fieldset>
          <fieldset disabled={blocked}><legend>3 · {label('termsAttachments')}</legend>
            <label>{label('template')}<select value={form.template_id || ''} onChange={event => field('template_id', event.target.value || null)}><option value="">{label('ownTerms')}</option>
              {form.template_id && !templates.items.some(value => value.id === form.template_id) && <option value={form.template_id}>{label('savedVersion')} · {form.template_id}</option>}
              {templates.items.map(value => <option key={value.id} value={value.id}>{value.title} · v{value.version}</option>)}</select></label>
            {templates.items.length < templates.total && <button type="button" disabled={blocked} onClick={moreTemplates}>{label('moreVersions')}</button>}
            <div className="contract-actions"><button type="button" disabled={blocked || !propertyInfo?.portfolio_id} onClick={() => setTemplateDraft({ title: '', body: '', previous_id: null })}>{label('newTemplate')}</button>
              <button type="button" disabled={blocked || !templates.items.find(value => value.id === form.template_id)} onClick={() => {
                const selected = templates.items.find(value => value.id === form.template_id); setTemplateDraft({ title: selected.title, body: selected.body, previous_id: selected.id });
              }}>{label('newVersion')}</button></div>
            {templateDraft && <section className="contract-template-editor"><h3>{label('versionEditor')}</h3><p>{label('immutableVersion')}</p>
              <label>{label('templateTitle')}<input value={templateDraft.title} onChange={event => setTemplateDraft(current => ({ ...current, title: event.target.value }))} /></label>
              <label>{label('templateBody')}<textarea rows={8} value={templateDraft.body} onChange={event => setTemplateDraft(current => ({ ...current, body: event.target.value }))} /></label>
              <button type="button" className="btn btn-secondary" disabled={blocked || !templateDraft.title.trim() || !templateDraft.body.trim()}
                onClick={() => execute(`${endpoint}/templates`, { ...templateDraft, portfolio_id: propertyInfo.portfolio_id }, { template: true })}>{label('saveVersion')}</button>
              <button type="button" disabled={blocked} onClick={() => setTemplateDraft(null)}>{label('cancel')}</button></section>}
            <label>{label('terms')}<textarea rows={10} value={form.terms} placeholder={label('termsPlaceholder')} onChange={event => field('terms', event.target.value)} /></label>
            <p className="contract-hint">{label('termsHint')}</p>
            <ContractReferencePicker kind="documents" label={label('attachment')} value={attachmentId} propertyId={form.property_id} disabled={blocked}
              onChange={id => setAttachmentId(id)} />
            <button type="button" disabled={blocked || !attachmentId || form.attachment_ids.includes(attachmentId)} onClick={() => { field('attachment_ids', [...form.attachment_ids, attachmentId]); setAttachmentId(''); }}>{label('addAttachment')}</button>
            <p className="contract-hint">{label('attachmentHint')}</p>
            <ul className="contract-attachments">{form.attachment_ids.map(id => <li key={id}><span>{row?.review?.attachments?.find(value => value.id === id)?.title || id}</span>
              <label><input type="checkbox" checked={form.metadata_only_attachment_ids.includes(id)} onChange={event => field('metadata_only_attachment_ids', event.target.checked ? [...form.metadata_only_attachment_ids, id] : form.metadata_only_attachment_ids.filter(value => value !== id))} />{label('metadataOnly')}</label>
              <button type="button" disabled={blocked} onClick={() => { field('attachment_ids', form.attachment_ids.filter(value => value !== id)); field('metadata_only_attachment_ids', form.metadata_only_attachment_ids.filter(value => value !== id)); }}>{label('remove')}</button></li>)}</ul>
          </fieldset>
          <div className="contract-actions"><button type="submit" className="btn btn-primary" disabled={blocked || !!templateDraft}>{label('saveDraft')}</button>
            {row && <button type="button" className="btn btn-secondary" disabled={blocked || !!dirty || !!templateDraft}
              onClick={() => execute(`${endpoint}/drafts/${row.id}/review`, { expected_revision: row.revision })}>{label('review')}</button>}
            {row && <button type="button" disabled={busy} onClick={async () => { if (dirty && !await confirm(label('switchConfirm'))) return;
              try { accept(await api.get(`${endpoint}/drafts/${row.id}`)); } catch (err) { setError(err.message); } }}>{label('reload')}</button>}</div>
          {dirty && <p>{label('unsavedChanges')}</p>}
        </form>}
        {row?.review && <section className="contract-panel contract-review" ref={previewRef} tabIndex={-1}>
          <div className="contract-panel-heading"><h2>4 · {label('reviewTitle')}</h2><span>{label(row.state)}</span></div>
          <dl className="contract-review-grid"><div><dt>{label('property')}</dt><dd>{row.review.property.name} / {row.review.unit.label}</dd></div>
            <div><dt>{label('parties')}</dt><dd>{row.review.parameters.landlord_name}<br />{row.review.tenant.full_name}</dd></div>
            <div><dt>{label('tenancy')}</dt><dd>{row.review.parameters.start_date} – {row.review.parameters.end_date || label('indefinite')}</dd></div>
            <div><dt>{label('coldRent')}</dt><dd>{money(row.review.unit.cold_rent)}</dd></div>
            <div><dt>{label('operating')}</dt><dd>{money(row.review.unit.service_charge_advance)} + {money(row.review.unit.heating_advance)}</dd></div>
            <div><dt>{label('deposit')}</dt><dd>{money(row.review.parameters.deposit_amount)}</dd></div>
            <div><dt>{label('template')}</dt><dd>{row.review.template ? `${row.review.template.title} · v${row.review.template.version}` : label('ownTerms')}</dd></div>
            <div><dt>{label('status')}</dt><dd>{row.review.parameters.contract_status === 'active' ? label('activeReserved') : label('draftNonReserving')}</dd></div></dl>
          <p>{label('noCash')}</p><p className="contract-hint">{label('manualHint')}</p>
          <details><summary>{label('terms')}</summary><p className="contract-terms">{row.review.terms}</p></details>
          <ul className="contract-attachments">{row.review.attachments.map(file => <li key={file.id}><strong>{file.title}</strong><span>{file.mode === 'frozen_bytes' ? `${label('originalBytes')} · ${file.size_bytes} B` : label('metadataOnly')}</span>{file.sha256 && <code>{file.sha256}</code>}</li>)}</ul>
          <p className="contract-hash">{label('reviewReference')}: <code>{row.review_hash}</code></p>
          <div className="contract-actions"><button type="button" className="btn btn-secondary" disabled={busy}
            onClick={() => download(row.preview_url, 'mietvertrag-vorschau.pdf', row.pdf_sha256, true)}>{label('previewPdf')}</button>
            {row.state === 'reviewed' && <button type="button" className="btn btn-primary" disabled={blocked || !!dirty}
              onClick={() => execute(`${endpoint}/drafts/${row.id}/publish`, { expected_revision: row.revision, reviewed_hash: row.review_hash, confirmed: true }, { confirmation: label('publishConfirm') })}>{label('publish')}</button>}</div>
        </section>}
        {row?.contract_id && <section className="contract-panel contract-result"><h2>{label('published')}</h2><p>{label('publishedHint')}</p>
          <p>{label('contractId')}: <code>{row.contract_id}</code><br />{label('documentId')}: <code>{row.document_id}</code></p>
          <div className="contract-actions"><button type="button" className="btn btn-primary" disabled={busy} onClick={() => download(row.pdf_url, 'mietvertrag.pdf', row.pdf_sha256, true)}>{label('downloadPdf')}</button><Link className="btn btn-secondary" to="/documents">{label('documents')}</Link></div>
          <ul className="contract-attachments">{attachments.items.map(file => <li key={file.id}><strong>{file.title}</strong><span>{file.mode === 'frozen_bytes' ? `${label('originalBytes')} · ${file.size_bytes} B` : label('metadataOnly')}</span>
            {file.download_url && <button type="button" disabled={busy} onClick={() => download(file.download_url, `${file.title}.bin`, file.sha256)}>{label('downloadAttachment')}</button>}</li>)}</ul>
          {attachments.has_more && <button type="button" disabled={busy} onClick={() => moreEvidence('attachments')}>{label('moreEvidence')}</button>}
          <h3>{label('signatureJournal')}</h3><p>{label('manualHint')}</p>
          {signatures.items.map(value => <p key={value.id}>{value.signed_date} · {value.tenant_signer} / {value.landlord_signer}<br />{value.reference}<br />{value.note}</p>)}
          {signatures.has_more && <button type="button" disabled={busy} onClick={() => moreEvidence('signatures')}>{label('moreEvidence')}</button>}
          {row.state === 'committed' && canWrite && <button type="button" disabled={blocked} onClick={() => setSignature({ signed_date: new Date().toISOString().slice(0, 10), tenant_signer: row.review.tenant.full_name, landlord_signer: row.review.parameters.landlord_name, reference: '', note: '', signed_document_id: null })}>{label('recordSignature')}</button>}
          {signature && <form onSubmit={event => { event.preventDefault(); execute(`${endpoint}/drafts/${row.id}/signatures`, { ...signature, expected_revision: row.revision, confirmed: true }, { confirmation: label('signatureConfirm') }); }}>
            <fieldset disabled={blocked}><legend>{label('manualSignature')}</legend><div className="contract-grid">{['signed_date', 'tenant_signer', 'landlord_signer', 'reference', 'note'].map(key => <label key={key}>{label(`signature_${key}`)}<input required={key !== 'note'} type={key === 'signed_date' ? 'date' : 'text'} value={signature[key]} onChange={event => setSignature(current => ({ ...current, [key]: event.target.value }))} /></label>)}</div>
              <ContractReferencePicker kind="documents" label={label('signedDocument')} value={signature.signed_document_id || ''} propertyId={row.data.property_id} disabled={blocked} onChange={id => setSignature(current => ({ ...current, signed_document_id: id || null }))} />
              <button type="submit" className="btn btn-primary" disabled={blocked}>{label('saveSignature')}</button><button type="button" disabled={blocked} onClick={() => setSignature(null)}>{label('cancel')}</button></fieldset></form>}
        </section>}
      </>}
    </>}
  </div>;
}
