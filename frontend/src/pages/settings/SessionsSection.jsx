import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Monitor, RefreshCw, ShieldCheck } from 'lucide-react';
import { api, logout } from '../../api';
import { useAuth } from '../../contexts/AuthContext';
import { useTranslation } from '../../i18n';
import { useConfirm } from '../../components/ConfirmDialog';
import './SessionsSection.css';

const pageSize = 20;
const dateValid = value => typeof value === 'string' && Number.isFinite(Date.parse(value));
const validRow = row => row && typeof row.id === 'string' && row.id.length > 0
  && typeof row.device_label === 'string' && typeof row.current === 'boolean'
  && ['created_at', 'last_used_at', 'expires_at'].every(key => dateValid(row[key]))
  && ['active', 'revoked', 'expired'].includes(row.status)
  && (row.revoked_at === null || dateValid(row.revoked_at))
  && (row.status === 'revoked' ? dateValid(row.revoked_at) : row.revoked_at === null);
const publicRow = row => Object.fromEntries(['id', 'device_label', 'current', 'created_at', 'last_used_at', 'expires_at', 'revoked_at', 'revoke_reason', 'status'].map(key => [key, row[key]]));
const validList = value => value && Array.isArray(value.items) && value.items.every(validRow)
  && new Set(value.items.map(row => row.id)).size === value.items.length
  && Number.isInteger(value.total) && value.total >= 0 && Number.isInteger(value.offset) && value.offset >= 0
  && value.limit === pageSize && value.items.length <= pageSize
  && (value.items.length === 0 || value.offset + value.items.length <= value.total)
  && typeof value.legacy_current === 'boolean' && typeof value.persistent === 'boolean'
  && (value.current_session_id === null || (typeof value.current_session_id === 'string' && value.current_session_id.length > 0))
  && value.legacy_current === (value.current_session_id === null)
  && value.items.every(row => row.current === (row.id === value.current_session_id));

export default function SessionsSection() {
  const { t, locale } = useTranslation();
  const auth = useAuth();
  const confirm = useConfirm();
  const titleId = useId();
  const userId = auth?.user?.id;
  const [page, setPage] = useState({ account: userId, offset: 0 });
  const offset = page.account === userId ? page.offset : 0;
  const [sourceState, setSource] = useState({ account: userId, status: 'loading', items: [], total: 0, error: null });
  const source = sourceState.account === userId ? sourceState : { status: 'loading', items: [], total: 0, error: null };
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [actionError, setActionError] = useState(null);
  const mounted = useRef(false);
  const account = useRef(auth?.user?.id);
  account.current = auth?.user?.id;
  const running = useRef(false);
  const loadController = useRef(null);
  const mutationController = useRef(null);
  const errorRef = useRef(null);
  const text = key => t(`auth.sessions.${key}`);

  const load = useCallback(async () => {
    loadController.current?.abort();
    const controller = new AbortController();
    loadController.current = controller;
    const actor = userId;
    setSource(previous => ({ ...(previous.account === actor ? previous : { items: [], total: 0 }), account: actor, status: 'loading', error: null }));
    try {
      const result = await api.get(`/auth/sessions?offset=${offset}&limit=${pageSize}`, { signal: controller.signal });
      if (!validList(result) || result.offset !== offset) throw new Error(t('auth.sessions.invalidResponse'));
      if (mounted.current && !controller.signal.aborted && account.current === actor) setSource({ ...result, account: actor, items: result.items.map(publicRow), status: 'ready', error: null });
    } catch (error) {
      if (mounted.current && !controller.signal.aborted && account.current === actor) setSource(previous => ({ ...previous, status: 'error', error: error.message || t('auth.sessions.loadError') }));
    }
  }, [offset, t, userId]);

  useEffect(() => {
    mounted.current = true;
    setMessage(null); setActionError(null);
    void load();
    return () => { mounted.current = false; loadController.current?.abort(); mutationController.current?.abort(); };
  }, [load, auth?.user?.id]);

  useEffect(() => { if (actionError) errorRef.current?.focus(); }, [actionError]);

  const revoke = async row => {
    if (running.current || source.status !== 'ready' || row.status !== 'active' || !account.current) return;
    const actor = account.current;
    running.current = true;
    setBusy(true); setActionError(null); setMessage(null);
    try {
      if (!confirm || !await confirm(text(row.current ? 'confirmCurrent' : 'confirmOther'))) return;
      if (!mounted.current || account.current !== actor) return;
      const controller = new AbortController();
      mutationController.current = controller;
      const result = await api.post(`/auth/sessions/${encodeURIComponent(row.id)}/revoke`, { confirmed: true }, { signal: controller.signal });
      if (!validRow(result) || result.id !== row.id || result.status !== 'revoked' || result.current !== row.current) throw new Error(text('invalidResponse'));
      if (!mounted.current || controller.signal.aborted || account.current !== actor) return;
      if (row.current) {
        auth?.clearUser?.();
        await logout();
      } else {
        setSource(previous => ({ ...previous, items: previous.items.map(item => item.id === row.id ? publicRow(result) : item) }));
        setMessage(text('revokedSuccess'));
      }
    } catch (error) {
      if (mounted.current && account.current === actor) setActionError(error.message || text('revokeError'));
    } finally {
      running.current = false;
      if (mounted.current) setBusy(false);
    }
  };

  const formatDate = value => new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
  return <section className="panel sessions-section" aria-labelledby={titleId} aria-busy={busy || source.status === 'loading'}>
    <header className="sessions-header">
      <div><p className="sessions-kicker"><ShieldCheck size={16} aria-hidden="true" />{text('eyebrow')}</p><h2 id={titleId}>{text('title')}</h2></div>
      <button type="button" className="btn btn-secondary" onClick={load} disabled={busy || source.status === 'loading'}><RefreshCw size={16} aria-hidden="true" />{text('reload')}</button>
    </header>
    <p>{text('description')}</p>
    <p className="form-hint">{text('deviceHint')}</p>
    {source.legacy_current && <p className="sessions-note">{text('legacyCurrent')}</p>}
    {source.persistent === false && <p className="sessions-note">{text('memoryHint')}</p>}
    <p className="form-hint">{text('transitionHint')}</p>
    {source.status === 'loading' && <p role="status">{text('loading')}</p>}
    {source.error && <div role="alert" className="alert-error"><p>{source.error}</p><button type="button" className="btn btn-secondary" onClick={load} disabled={busy}>{text('retry')}</button></div>}
    {actionError && <p role="alert" ref={errorRef} tabIndex={-1} className="alert-error">{actionError}</p>}
    {message && <p role="status">{message}</p>}
    {source.status === 'ready' && source.items.length === 0 && <div className="sessions-empty"><Monitor size={30} aria-hidden="true" /><h3>{text('empty')}</h3><p>{text('emptyHint')}</p></div>}
    {source.items.length > 0 && <ul className="sessions-list" aria-label={text('listLabel')}>
      {source.items.map(row => <li key={row.id} className="sessions-card">
        <div className="sessions-device"><Monitor size={22} aria-hidden="true" /><div><h3>{row.device_label}</h3><span className={`sessions-state sessions-state-${row.status}`}>{text(`states.${row.status}`)}</span>{row.current && <span className="sessions-current">{text('current')}</span>}</div></div>
        <dl className="sessions-dates">{[['created', 'created_at'], ['lastUsed', 'last_used_at'], ['expires', 'expires_at'], ...(row.revoked_at ? [['revoked', 'revoked_at']] : [])].map(([label, key]) => <div key={key}><dt>{text(label)}</dt><dd><time dateTime={row[key]}>{formatDate(row[key])}</time></dd></div>)}</dl>
        {row.revoke_reason === 'refresh_reuse' && <p className="sessions-note">{text('reuseReason')}</p>}
        {row.revoke_reason === 'database_restore' && <p className="sessions-note">{text('restoreReason')}</p>}
        {row.status === 'active' && <button type="button" className="btn btn-danger" onClick={() => revoke(row)} disabled={busy || source.status !== 'ready'}>{text(row.current ? 'revokeCurrent' : 'revokeOther')}</button>}
      </li>)}
    </ul>}
    {source.total > 0 && <nav className="sessions-pagination" aria-label={text('pagination')}>
      <button type="button" className="btn btn-secondary" disabled={offset === 0 || busy || source.status === 'loading'} onClick={() => setPage({ account: userId, offset: Math.max(0, offset - pageSize) })}>{text('previous')}</button>
      <span>{t('auth.sessions.range', { start: offset + 1, end: offset + source.items.length, total: source.total })}</span>
      <button type="button" className="btn btn-secondary" disabled={offset + source.items.length >= source.total || busy || source.status === 'loading'} onClick={() => setPage({ account: userId, offset: offset + pageSize })}>{text('next')}</button>
    </nav>}
  </section>;
}
