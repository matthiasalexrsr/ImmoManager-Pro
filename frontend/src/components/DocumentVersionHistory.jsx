import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useAuth } from '../contexts/AuthContext';
import useWriteAccess from '../hooks/useWriteAccess';
import { useConfirm } from './ConfirmDialog';
import './DocumentVersionHistory.css';

const validId = value => typeof value === 'string' && value.length > 0 && ![...value].some(char =>
  char === '/' || char === '\\' || char.charCodeAt(0) < 32);
const validRow = (row, id) => row && validId(row.id) && row.document_id === id
  && Number.isSafeInteger(row.number) && row.number > 0 && Number.isSafeInteger(row.size_bytes) && row.size_bytes >= 0
  && /^[a-f0-9]{64}$/.test(row.sha256) && typeof row.filename === 'string' && typeof row.comment === 'string'
  && typeof row.created_at === 'string' && Number.isFinite(Date.parse(row.created_at))
  && typeof row.actor_id === 'string' && row.metadata_snapshot && typeof row.metadata_snapshot === 'object' && !Array.isArray(row.metadata_snapshot);
const validHistory = (data, id) => data?.document_id === id && typeof data.document_etag === 'string'
  && Array.isArray(data.items) && data.items.every(row => validRow(row, id))
  && new Set(data.items.map(row => row.id)).size === data.items.length
  && (data.head === null || validRow(data.head, id))
  && (data.next_before === null || (Number.isSafeInteger(data.next_before) && data.next_before > 0));
const key = () => `doc-version:${crypto.randomUUID()}`;
const reachable = container => [...container.querySelectorAll('button, input, textarea, select, summary, a[href], [tabindex="0"]')]
  .filter(element => {
    if (element.tabIndex < 0 || element.matches(':disabled') || element.closest('[hidden], [inert], [aria-hidden="true"]')) return false;
    for (let parent = element; parent && parent !== container.parentElement; parent = parent.parentElement) {
      const style = getComputedStyle(parent);
      if (style.display === 'none' || style.visibility === 'hidden') return false;
    }
    return true;
  });

export default function DocumentVersionHistory(props) {
  const user = useAuth()?.user;
  // Private unfinished choices belong to one document and one actor.
  return <VersionHistory key={`${props.document.id}:${user?.id || ''}`} {...props} />;
}

function VersionHistory({ document: sourceDocument, onClose, onViewOriginal }) {
  const { t, locale } = useTranslation();
  const tr = useCallback((name, params) => t(`pages.documents.versions.${name}`, params), [t]);
  const { canWrite, requireWrite, isAllowed } = useWriteAccess('/documents');
  const confirm = useConfirm();
  const id = sourceDocument.id;
  const base = `/documents/${encodeURIComponent(id)}`;
  const [history, setHistory] = useState(null);
  const [preview, setPreview] = useState(null);
  const [comment, setComment] = useState('');
  const [file, setFile] = useState(null);
  const [compare, setCompare] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [previous, setPrevious] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const dialog = useRef(null);
  const alert = useRef(null);
  const fileInput = useRef(null);
  const busyRef = useRef(false);
  const alive = useRef(true);
  const request = useRef(null);
  const writeRequest = useRef(null);
  const pending = useRef(null);
  const urls = useRef(new Set());
  const close = useRef(onClose);
  const fieldId = useId();
  useEffect(() => { close.current = onClose; }, [onClose]);

  const load = useCallback(async (before = null) => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true); setError(null);
    try {
      const result = await api.get(`${base}/versions?limit=25${before === null ? '' : `&before=${before}`}`, { signal: controller.signal });
      if (controller.signal.aborted || !alive.current) return;
      if (!validHistory(result, id)) throw new Error(tr('invalidResponse'));
      setHistory(result);
    } catch (failure) {
      if (!controller.signal.aborted && alive.current) {
        setError(failure.message);
        if ([401, 403, 404].includes(failure.statusCode ?? failure.status)) setHistory(null);
      }
    } finally { if (!controller.signal.aborted && alive.current) setLoading(false); }
  }, [base, id, tr]);

  useEffect(() => {
    alive.current = true;
    const opener = window.document.activeElement;
    const ownedUrls = urls.current;
    dialog.current?.querySelector('button')?.focus();
    const keyboard = event => {
      if (event.defaultPrevented) return;
      if (event.key === 'Escape') {
        event.preventDefault(); if (!busyRef.current) close.current();
      } else if (event.key === 'Tab') {
        const controls = reachable(dialog.current);
        if (!controls.length) { event.preventDefault(); dialog.current.focus(); return; }
        const first = controls[0], last = controls.at(-1);
        if (event.shiftKey && window.document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && window.document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    window.document.addEventListener('keydown', keyboard);
    return () => {
      alive.current = false; request.current?.abort(); writeRequest.current?.abort();
      window.document.removeEventListener('keydown', keyboard);
      ownedUrls.forEach(url => URL.revokeObjectURL(url)); ownedUrls.clear();
      if (opener?.isConnected) opener.focus();
    };
  }, []);
  useEffect(() => { load(cursor); }, [load, cursor]);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);

  const reviewOriginal = async () => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError(null);
    setPreview(null);
    const controller = new AbortController(); writeRequest.current = controller;
    try {
      const result = await api.get(`${base}/version-source`, { signal: controller.signal });
      if (!alive.current || controller.signal.aborted) return;
      if (!/^[a-f0-9]{64}$/.test(result?.sha256) || !Number.isSafeInteger(result?.size_bytes)
          || result.size_bytes < 0 || typeof result.filename !== 'string') throw new Error(tr('invalidResponse'));
      if (result.document_etag !== history?.document_etag) throw new Error(tr('staleReview'));
      setPreview(result);
    } catch (failure) { if (alive.current) { setError(failure.message); if ([401, 403, 404].includes(failure.statusCode ?? failure.status)) setHistory(null); } }
    finally { busyRef.current = false; if (alive.current) setBusy(false); }
  };

  const publish = async (mode, restored = null) => {
    if (busyRef.current || !history) return;
    busyRef.current = true; setBusy(true); setError(null); setNotice(null);
    try {
      requireWrite();
      if (!comment.trim()) throw new Error(tr('commentRequired'));
      if (mode === 'upload' && !file) throw new Error(tr('fileRequired'));
      if (mode === 'archive' && !preview) throw new Error(tr('previewRequired'));
      if (!await confirm(tr(mode === 'restore' ? 'confirmRestore' : mode === 'archive' ? 'confirmArchive' : 'confirmUpload',
        { name: mode === 'upload' ? file.name : mode === 'restore' ? restored.filename : preview.filename }))) return;
      if (!alive.current || !isAllowed()) return;
      requireWrite();
      const signature = JSON.stringify({ mode, comment: comment.trim(), etag: history.document_etag,
        head: history.head?.id, restore: restored?.id, sha: preview?.sha256,
        file: file && [file.name, file.size, file.lastModified] });
      if (pending.current?.signature !== signature || pending.current?.file !== file) {
        const payload = { idempotency_key: key(), expected_document_etag: history.document_etag,
          expected_head_id: history.head?.id || null, comment: comment.trim(), confirmed: true,
          ...(mode === 'archive' ? { expected_sha256: preview.sha256 } : {}),
          ...(mode === 'restore' ? { source_version_id: restored.id } : {}) };
        pending.current = { signature, file, payload };
      }
      const controller = new AbortController(); writeRequest.current = controller;
      let result;
      if (mode === 'upload') {
        const form = new FormData(); form.append('command', JSON.stringify(pending.current.payload)); form.append('file', file);
        result = await api.postForm(`${base}/versions`, form, { signal: controller.signal });
      } else result = await api.post(`${base}/versions/${mode === 'archive' ? 'archive-original' : 'restore'}`,
        pending.current.payload, { signal: controller.signal });
      if (controller.signal.aborted || !alive.current) return;
      if (!validRow(result, id)) throw new Error(tr('invalidResponse'));
      setNotice(tr('saved', { number: result.number })); setComment(''); setFile(null); setPreview(null); pending.current = null;
      if (fileInput.current) fileInput.current.value = '';
      setHistory(current => ({ ...current, head: result }));
      setCursor(null); setPrevious([]); await load(null);
    } catch (failure) { if (alive.current && failure.name !== 'AbortError') { setError(failure.message); if ([401, 403, 404].includes(failure.statusCode ?? failure.status)) setHistory(null); } }
    finally { busyRef.current = false; if (alive.current) setBusy(false); }
  };

  const download = async row => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError(null);
    const controller = new AbortController(); writeRequest.current = controller;
    try {
      // Never forward a server-supplied arbitrary URL with the user's bearer.
      const blob = await api.getBlob(`${base}/versions/${encodeURIComponent(row.id)}/download`, { signal: controller.signal });
      if (!(blob instanceof Blob) || blob.size !== row.size_bytes || /json|html/i.test(blob.type)) throw new Error(tr('invalidDownload'));
      const checksum = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
      const hex = [...new Uint8Array(checksum)].map(value => value.toString(16).padStart(2, '0')).join('');
      if (hex !== row.sha256) throw new Error(tr('invalidDownload'));
      if (controller.signal.aborted || !alive.current) return;
      const url = URL.createObjectURL(blob); urls.current.add(url);
      const link = window.document.createElement('a'); link.href = url;
      link.download = [...row.filename].map(char => char === '/' || char === '\\' || char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127 ? '_' : char).join('') || 'document.bin'; link.click();
      URL.revokeObjectURL(url); urls.current.delete(url);
    } catch (failure) { if (alive.current && failure.name !== 'AbortError') { setError(failure.message); if ([401, 403, 404].includes(failure.statusCode ?? failure.status)) setHistory(null); } }
    finally { busyRef.current = false; if (alive.current) setBusy(false); }
  };

  return <div className="modal-overlay" onClick={() => { if (!busyRef.current) onClose(); }}>
    <section className="modal document-version-history" ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby={`${fieldId}-title`}
      aria-busy={busy || loading} onClick={event => event.stopPropagation()}>
      <header className="modal-header"><div><span className="document-version-eyebrow">{tr('eyebrow')}</span>
        <h2 id={`${fieldId}-title`}>{tr('title')}</h2><p>{sourceDocument.title}</p></div>
        <button type="button" className="btn btn-secondary" disabled={busy} onClick={onClose}>{tr('close')}</button></header>
      <div className="modal-body">
        <p className="document-version-note">{tr('originalPolicy')}</p>
        <div className="document-version-tools"><button type="button" className="btn btn-secondary" disabled={busy || loading} onClick={() => { setPreview(null); load(cursor); }}>{tr('refresh')}</button>
          {onViewOriginal && <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => onViewOriginal(sourceDocument)}>{tr('viewOriginal')}</button>}</div>
        {loading && <p role="status">{tr('loading')}</p>}
        {error && <div ref={alert} tabIndex={-1} role="alert" className="form-error">{error}</div>}
        {notice && <p role="status">{notice}</p>}
        {history && <>
          <div className="document-version-summary"><strong>{history.head ? tr('current', { number: history.head.number }) : tr('notArchived')}</strong>
            <span>{history.head ? `${history.head.filename} · ${history.head.size_bytes.toLocaleString(locale)} B` : tr('explicitArchive')}</span></div>
          {!history.persistent && <p className="document-version-note">{tr('memoryWarning')}</p>}
          {canWrite && <form onSubmit={event => { event.preventDefault(); publish(history.head ? 'upload' : 'archive'); }}>
            <label htmlFor={`${fieldId}-comment`}>{tr('comment')}</label><textarea id={`${fieldId}-comment`} value={comment} disabled={busy} required onChange={event => setComment(event.target.value)} />
            {history.head ? <><label htmlFor={`${fieldId}-file`}>{tr('newFile')}</label><input ref={fileInput} id={`${fieldId}-file`} type="file" disabled={busy} onChange={event => setFile(event.target.files?.[0] || null)} />
              {file && <p>{file.name} · {file.size.toLocaleString(locale)} B</p>}</> : <>
              <button type="button" className="btn btn-secondary" disabled={busy || loading} onClick={reviewOriginal}>{tr('reviewOriginal')}</button>
              {preview && <div className="document-version-proof"><strong>{preview.filename} · {preview.size_bytes.toLocaleString(locale)} B</strong><code>SHA256 {preview.sha256}</code></div>}</>}
            <button type="submit" className="btn btn-primary" disabled={busy || loading || !comment.trim() || (!history.head && !preview) || (history.head && !file)}>
              {busy ? tr('working') : history.head ? tr('publish') : tr('archive')}</button>
          </form>}
          {history.items.length === 0 && <p>{tr('empty')}</p>}
          <ol className="document-version-list">{history.items.map(row => <li key={row.id}>
            <div className="document-version-row"><div><h3>{tr('version', { number: row.number })}{row.id === history.head?.id && <span>{tr('head')}</span>}</h3>
              <p>{row.filename} · {row.size_bytes.toLocaleString(locale)} B</p><time>{new Date(row.created_at).toLocaleString(locale)}</time>
              <p>{row.comment}</p>{row.restored_from_id && <p>{tr('restored', { id: row.restored_from_id })}</p>}
              <details><summary>{tr('evidence')}</summary><p>{tr('actor')}: {row.actor_id}</p><code>SHA256 {row.sha256}</code><p>{tr('reference')}: {row.id}</p></details></div>
              <div className="document-version-actions"><button type="button" className="btn btn-secondary" disabled={busy} onClick={() => download(row)}>{tr('download')}</button>
                {canWrite && row.id !== history.head?.id && <button type="button" className="btn btn-secondary" disabled={busy || loading || !comment.trim()} onClick={() => publish('restore', row)}>{tr('restore')}</button>}
                <label><input type="checkbox" checked={compare.some(item => item.id === row.id)} disabled={!compare.some(item => item.id === row.id) && compare.length === 2}
                  onChange={event => setCompare(current => event.target.checked ? [...current, row] : current.filter(item => item.id !== row.id))} />{tr('compareVersion', { number: row.number })}</label></div></div>
          </li>)}</ol>
          {compare.length === 2 && <section className="document-version-compare" aria-label={tr('comparison')}><h3>{tr('comparison')}</h3>
            <p>{tr('compareNumbers', { a: compare[0].number, b: compare[1].number })}</p>
            <p>{compare[0].sha256 === compare[1].sha256 ? tr('sameBytes') : tr('differentBytes')}</p>
            <dl>{['title', 'document_type', 'document_date', 'tags', 'description'].map(field =>
              compare[0].metadata_snapshot[field] !== compare[1].metadata_snapshot[field] && <div key={field}><dt>{tr(`metadata.${field}`)}</dt>
                <dd>{String(compare[0].metadata_snapshot[field] ?? '—')} → {String(compare[1].metadata_snapshot[field] ?? '—')}</dd></div>)}</dl></section>}
          <nav className="document-version-tools" aria-label={tr('historyPages')}><button type="button" className="btn btn-secondary" disabled={busy || loading || previous.length === 0} onClick={() => { setCursor(previous.at(-1)); setPrevious(current => current.slice(0, -1)); }}>{tr('previous')}</button>
            <button type="button" className="btn btn-secondary" disabled={busy || loading || !history.next_before} onClick={() => { setPrevious(current => [...current, cursor]); setCursor(history.next_before); }}>{tr('next')}</button></nav>
        </>}
      </div>
    </section>
  </div>;
}
