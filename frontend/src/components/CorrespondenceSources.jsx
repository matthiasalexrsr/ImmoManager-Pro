import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useConfirm } from './ConfirmDialog';
import useWriteAccess from '../hooks/useWriteAccess';
import { key, PAGE_SIZE, unknownOutcome } from '../utils/contractCorrespondence';

const validTemplate = (row, portfolio) => row && row.portfolio_id === portfolio && typeof row.id === 'string'
  && row.id && typeof row.root_id === 'string' && Number.isSafeInteger(row.version) && row.version > 0
  && typeof row.title === 'string' && typeof row.body === 'string';

export default function CorrespondenceSources({ portfolioId, contract, templateId, lifecycleId, reviewedTemplate,
  onTemplateChange, onLifecycleChange, locked, onBusyChange, onRetryChange, onDenied }) {
  const { t } = useTranslation();
  const tr = (name, params) => t(`contractCorrespondence.${name}`, params);
  const confirm = useConfirm();
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/contracts');
  const [templates, setTemplates] = useState(null), [offset, setOffset] = useState(0);
  const [lifecycle, setLifecycle] = useState(null), [before, setBefore] = useState(null);
  const [editing, setEditing] = useState(null), [error, setError] = useState(null);
  const [busy, setBusy] = useState(false), [retry, setRetry] = useState(null), [generation, setGeneration] = useState(0);
  const request = useRef(null), active = useRef(true), writing = useRef(false);
  const updateBusy = useRef(onBusyChange), denied = useRef(onDenied);
  useEffect(() => { updateBusy.current = onBusyChange; denied.current = onDenied; }, [onBusyChange, onDenied]);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; request.current?.abort(); updateBusy.current?.(false); };
  }, []);
  useEffect(() => { onRetryChange?.(Boolean(retry)); }, [retry, onRetryChange]);
  useEffect(() => () => onRetryChange?.(false), [onRetryChange]);
  useEffect(() => {
    const ctl = new AbortController();
    setTemplates(null); setError(null);
    api.get(`/contract-wizard/templates?portfolio_id=${encodeURIComponent(portfolioId)}&offset=${offset}&limit=${PAGE_SIZE}`, { signal: ctl.signal })
      .then(page => {
        if (ctl.signal.aborted) return;
        if (!Array.isArray(page?.items) || page.items.length > PAGE_SIZE || !page.items.every(row => validTemplate(row, portfolioId))
            || !Number.isSafeInteger(page.total) || page.total < 0 || page.offset !== offset || page.limit !== PAGE_SIZE
            || new Set(page.items.map(row => row.id)).size !== page.items.length) throw new Error('invalidResponse');
        setTemplates(page);
      }).catch(error => { if (!ctl.signal.aborted) { denied.current?.(error); setError(error.message); } });
    return () => ctl.abort();
  }, [portfolioId, offset, generation]);
  useEffect(() => {
    const ctl = new AbortController(); setLifecycle(null);
    api.get(`/contracts/${encodeURIComponent(contract.id)}/lifecycle/history?limit=${PAGE_SIZE}${before ? `&before=${encodeURIComponent(before)}` : ''}`, { signal: ctl.signal })
      .then(page => {
        if (ctl.signal.aborted) return;
        if (!Array.isArray(page?.items) || page.items.length > PAGE_SIZE
            || !(page.next_before === null || typeof page.next_before === 'string')) throw new Error('invalidResponse');
        const items = page.items.map(row => {
          const source = row?.result;
          if (!row.id || !['confirm', 'finalize'].includes(row.operation) || source?.contract_id !== contract.id
              || source.property_id !== contract.property_id || source.unit_id !== contract.unit_id || source.tenant_id !== contract.tenant_id
              || typeof source.data?.reason !== 'string') throw new Error('invalidResponse');
          return { id: row.id, state: row.current_state || source.state, reason: source.data.reason };
        }).filter(row => row.state !== 'superseded');
        if (items.some(row => !['confirmed', 'pending_effective', 'completed'].includes(row.state))
            || new Set(items.map(row => row.id)).size !== items.length) throw new Error('invalidResponse');
        setLifecycle({ items, next: page.next_before });
      }).catch(error => { if (!ctl.signal.aborted) { denied.current?.(error); setError(error.message); } });
    return () => ctl.abort();
  }, [contract.id, contract.property_id, contract.unit_id, contract.tenant_id, before, generation]);
  const sendTemplate = async command => {
    if (writing.current || locked || !isAllowed()) return;
    writing.current = true; setBusy(true); updateBusy.current?.(true); setError(null);
    const ctl = new AbortController(); request.current = ctl;
    try {
      requireWrite();
      const result = await api.post('/contract-wizard/templates', command, { signal: ctl.signal });
      if (!active.current || ctl.signal.aborted || !isAllowed()) return;
      if (!validTemplate(result, portfolioId) || result.title !== command.title || result.body !== command.body) throw new Error('invalidResponse');
      onTemplateChange(result.id); setEditing(null); setRetry(null); setOffset(0); setGeneration(value => value + 1);
    } catch (failure) {
      if (active.current && !ctl.signal.aborted) {
        denied.current?.(failure);
        setError(failure.message);
        if (unknownOutcome(failure)) setRetry(command);
      }
    } finally {
      writing.current = false;
      if (active.current) { setBusy(false); updateBusy.current?.(false); }
    }
  };
  const saveTemplate = async () => {
    if (!editing?.title.trim() || !editing.body.trim() || writing.current || locked || !isAllowed()) return;
    const payload = { ...editing, title: editing.title.trim(), body: editing.body, portfolio_id: portfolioId, idempotency_key: key() };
    writing.current = true; setBusy(true); updateBusy.current?.(true);
    let accepted = false;
    try { accepted = await confirm(tr('saveTemplateConfirm')); }
    finally { writing.current = false; if (active.current) { setBusy(false); updateBusy.current?.(false); } }
    if (accepted && active.current && isAllowed()) await sendTemplate(payload);
  };
  const selected = templates?.items.find(row => row.id === templateId);
  const disabled = locked || busy || Boolean(retry);
  return <section className="contract-correspondence-sources">
    <label>{tr('template')}<select value={templateId} disabled={disabled || !templates}
      onChange={event => onTemplateChange(event.target.value)}>
      <option value="">{tr('selectTemplate')}</option>
      {templateId && !selected && <option value={templateId}>{reviewedTemplate?.id === templateId
        ? `${reviewedTemplate.title} · v${reviewedTemplate.version}` : tr('savedTemplate')}</option>}
      {templates?.items.map(row => <option key={row.id} value={row.id}>{row.title} · v{row.version}</option>)}
    </select></label>
    <div className="contract-correspondence-actions">
      <button type="button" disabled={disabled || !offset} onClick={() => setOffset(value => Math.max(0, value - PAGE_SIZE))}>{tr('previousTemplates')}</button>
      <button type="button" disabled={disabled || !templates || offset + templates.items.length >= templates.total} onClick={() => setOffset(value => value + PAGE_SIZE)}>{tr('nextTemplates')}</button>
      {canWrite && <>
        <button type="button" disabled={disabled} onClick={() => setEditing({ title: '', body: '', previous_id: null })}>{tr('newTemplate')}</button>
        <button type="button" disabled={disabled || !selected} onClick={() => setEditing({ title: selected.title, body: selected.body, previous_id: selected.id })}>{tr('newTemplateVersion')}</button>
      </>}
    </div>
    <p className="text-muted">{tr('templatePolicy')}</p>
    {editing && <fieldset disabled={disabled} onKeyDown={event => {
      if (event.key === 'Enter' && event.target.tagName === 'INPUT') event.preventDefault();
    }}>
      <legend>{tr(editing.previous_id ? 'newTemplateVersion' : 'newTemplate')}</legend>
      <label>{tr('templateTitle')}<input value={editing.title} onChange={event => setEditing(current => ({ ...current, title: event.target.value }))} /></label>
      <label>{tr('templateBody')}<textarea rows={8} value={editing.body} onChange={event => setEditing(current => ({ ...current, body: event.target.value }))} /></label>
      <p className="text-muted">{tr('placeholders')}</p>
      {selected && editing.previous_id && selected.id !== editing.previous_id && <button type="button" disabled={disabled}
        onClick={() => setEditing(current => ({ ...current, previous_id: selected.id }))}>{tr('usePredecessor')}</button>}
      <button type="button" disabled={disabled || !editing.title.trim() || !editing.body.trim()} onClick={saveTemplate}>{tr('saveTemplate')}</button>
      <button type="button" disabled={disabled} onClick={() => setEditing(null)}>{tr('cancel')}</button>
    </fieldset>}
    {error && <div role="alert">{error === 'invalidResponse' ? tr('invalidResponse') : error}
      {retry ? <><p>{tr('unknown')}</p><button type="button" disabled={busy || locked} onClick={() => sendTemplate(retry)}>{tr('retryExact')}</button></>
        : <button type="button" disabled={busy || locked} onClick={() => setGeneration(value => value + 1)}>{tr('reloadSources')}</button>}</div>}
    <label>{tr('lifecycleLink')}<select value={lifecycleId} disabled={disabled || !lifecycle}
      onChange={event => onLifecycleChange(event.target.value)}>
      <option value="">{tr('noLifecycleLink')}</option>
      {lifecycleId && !lifecycle?.items.some(row => row.id === lifecycleId) && <option value={lifecycleId}>{tr('savedLifecycle')}</option>}
      {lifecycle?.items.map(row => <option value={row.id} key={row.id}>{row.reason} · {tr(`lifecycle_${row.state}`)}</option>)}
    </select></label>
    <div className="contract-correspondence-actions">
      <button type="button" disabled={disabled || !before} onClick={() => setBefore(null)}>{tr('firstLifecycle')}</button>
      <button type="button" disabled={disabled || !lifecycle?.next} onClick={() => setBefore(lifecycle.next)}>{tr('moreLifecycle')}</button>
    </div>
  </section>;
}
