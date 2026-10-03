import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { denied, PAGE_SIZE, readManifest } from './disputeModel';

export function DisputeFailure({ error, tr, onRetry }) {
  return <div className="dispute-error" role="alert">{denied(error) ? tr('unavailable')
    : error?.message === 'invalidDisputeResponse' ? tr('invalidDisputeResponse') : error?.message || tr('invalidDisputeResponse')}
    {onRetry && <button type="button" className="btn btn-secondary" onClick={onRetry}>{tr('retry')}</button>}</div>;
}

export function OriginalSnapshot({ snapshot, locale, tr, selected = [], onSelect, disabled = false }) {
  const [page, setPage] = useState(0);
  const money = value => typeof value === 'number' && Number.isFinite(value)
    ? new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(value) : '—';
  const rows = Array.isArray(snapshot.line_items) ? snapshot.line_items : snapshot.owner_cost_share?.line_items || [];
  const safePage = Math.min(page, Math.max(0, Math.ceil(rows.length / PAGE_SIZE) - 1));
  const start = safePage * PAGE_SIZE;
  return <section aria-label={tr('original')} className="dispute-original">
    <h3>{tr('original')}</h3>
    {snapshot.original_party && <section aria-label={tr('originalParty')}><h4>{tr('originalParty')}</h4><p>{tr('partyFrozen')}</p>
      <p>{snapshot.original_party.identity.full_name}</p><address>{[snapshot.original_party.identity.address_line,
        [snapshot.original_party.identity.postal_code, snapshot.original_party.identity.city].filter(Boolean).join(' '), snapshot.original_party.identity.country].filter(Boolean).map((line, index) => <div key={index}>{line}</div>)}</address>
      <small>{tr('created')}: {new Date(snapshot.original_party.captured_at).toLocaleString(locale)}</small></section>}
    <dl className="dispute-facts">{[['revision', snapshot.revision], ['total', snapshot.total_cost], ['advance', snapshot.advance_paid], ['balance', snapshot.balance]].map(([key, value]) => value != null && <div key={key}><dt>{tr(key)}</dt><dd>{key === 'revision' ? value : money(value)}</dd></div>)}</dl>
    {rows.length > 0 && <><h4>{tr('positions')}</h4><div className="dispute-table" role="region" tabIndex={0} aria-label={tr('positions')}><table>
      <thead><tr>{onSelect && <th scope="col">{tr('positions')}</th>}<th scope="col">{tr('position')}</th><th scope="col">{tr('description')}</th><th scope="col">{tr('amount')}</th></tr></thead>
      <tbody>{rows.slice(start, start + PAGE_SIZE).map((row, offset) => {
        const index = start + offset;
        return <tr key={index}>{onSelect && <td><input type="checkbox" aria-label={`${tr('position')} ${index + 1}: ${row.description || '—'}`} checked={selected.includes(index)} disabled={disabled}
          onChange={event => onSelect(event.target.checked ? [...selected, index].sort((a, b) => a - b) : selected.filter(value => value !== index))} /></td>}
          <th scope="row">{index + 1}{!onSelect && selected.includes(index) ? ' ✓' : ''}</th><td>{row.description || '—'}</td><td>{money(row.allocated_amount)}</td></tr>;
      })}</tbody></table></div>
      <nav className="dispute-actions" aria-label={tr('positions')}><button type="button" className="btn btn-secondary" disabled={!safePage} onClick={() => setPage(safePage - 1)}>{tr('previous')}</button><span>{tr('page')} {safePage + 1}</span><button type="button" className="btn btn-secondary" disabled={start + PAGE_SIZE >= rows.length} onClick={() => setPage(safePage + 1)}>{tr('next')}</button></nav></>}
    <details><summary>{tr('originalJson')}</summary><pre>{JSON.stringify(snapshot, null, 2)}</pre></details>
  </section>;
}

export function OriginalEvidence({ items, tr, locale, onDenied }) {
  const [error, setError] = useState(null);
  const [working, setWorking] = useState(null);
  const request = useRef(null); const alive = useRef(true); const urls = useRef(new Set());
  useEffect(() => { alive.current = true; const liveUrls = urls.current; return () => {
    alive.current = false; request.current?.abort(); liveUrls.forEach(url => URL.revokeObjectURL(url)); liveUrls.clear();
  }; }, []);
  const download = async manifest => {
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setError(null); setWorking(manifest.version_id);
    try {
      readManifest(manifest);
      const blob = await api.getBlob(`/documents/${encodeURIComponent(manifest.document_id)}/versions/${encodeURIComponent(manifest.version_id)}/download`, { signal: controller.signal });
      if (controller.signal.aborted || !alive.current) return;
      if (blob.size !== manifest.size_bytes) throw new Error('invalidDisputeResponse');
      const url = URL.createObjectURL(new Blob([blob], { type: 'application/octet-stream' })); urls.current.add(url);
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = manifest.filename;
      document.body.appendChild(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(url); urls.current.delete(url);
    } catch (failure) { if (!controller.signal.aborted && alive.current) { setError(failure); if (denied(failure)) onDenied?.(); } }
    finally { if (!controller.signal.aborted && alive.current) setWorking(null); }
  };
  return <section className="dispute-evidence" aria-label={tr('evidence')}><h4>{tr('evidence')}</h4>
    {error && <DisputeFailure error={error} tr={tr} />}
    {!items.length ? <p>{tr('noEvidence')}</p> : <ul>{items.map(row => <li key={row.version_id}><strong>{row.filename}</strong>
      <span>{new Intl.NumberFormat(locale).format(row.size_bytes)} {tr('bytes')}</span>
      <button className="btn btn-secondary" type="button" disabled={working !== null} onClick={() => download(row)}>{working === row.version_id ? tr('loading') : tr('download')}</button>
      <details><summary>{tr('technical')}</summary><dl><dt>SHA-256</dt><dd>{row.sha256}</dd><dt>{tr('revision')}</dt><dd>{row.version_id}</dd></dl></details></li>)}</ul>}
  </section>;
}

export function EventOriginal({ event, tr, locale, onDenied }) {
  return <article className="dispute-event"><h4>{tr(event.kind)} · {tr('revision')} {event.revision}</h4>
    <dl className="dispute-facts"><div><dt>{tr('actualDate')}</dt><dd>{event.observed_on}</dd></div><div><dt>{tr('created')}</dt><dd>{new Date(event.created_at).toLocaleString(locale)}</dd></div><div><dt>{tr('author')}</dt><dd>{event.actor_id}</dd></div></dl>
    <p className="dispute-reason">{event.reason}</p>
    {event.line_item_refs.length > 0 && <p>{tr('positions')}: {event.line_item_refs.map(index => index + 1).join(', ')}</p>}
    {event.corrects_event_id && <p>{tr('correctionTarget')}: <code>{event.corrects_event_id}</code></p>}
    {event.correction_statement_id && <p>{tr('statementLink')}: <code>{event.correction_statement_id}</code></p>}
    <OriginalEvidence key={event.id} items={event.evidence} tr={tr} locale={locale} onDenied={onDenied} />
  </article>;
}
