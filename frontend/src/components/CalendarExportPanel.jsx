import { useEffect, useId, useRef, useState } from 'react';
import { Download, CalendarDays } from 'lucide-react';
import { api } from '../api';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from '../i18n';
import './CalendarExportPanel.css';

const PAGE_SIZE = 50;

// Inspect bounded boundaries only; the backend validates the entire prepared
// snapshot. Never decode a second full copy of a potentially large calendar.
function readBoundary(blob, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException('Aborted', 'AbortError')); return; }
    const reader = new FileReader();
    const abort = () => reader.abort();
    const finish = action => value => { signal.removeEventListener('abort', abort); action(value); };
    signal.addEventListener('abort', abort, { once: true });
    reader.onload = finish(() => resolve(String.fromCharCode(...new Uint8Array(reader.result))));
    reader.onerror = finish(() => reject(new Error('invalid_calendar')));
    reader.onabort = finish(() => reject(new DOMException('Aborted', 'AbortError')));
    reader.readAsArrayBuffer(blob);
  });
}

async function validateCalendar(blob, signal) {
  if (!(blob instanceof Blob) || blob.type.split(';')[0].trim().toLowerCase() !== 'text/calendar' || blob.size < 45) {
    throw new Error('invalid_calendar');
  }
  const [start, end] = await Promise.all([
    readBoundary(blob.slice(0, 64), signal), readBoundary(blob.slice(-32), signal),
  ]);
  if (!start.startsWith('BEGIN:VCALENDAR\r\nVERSION:2.0\r\n') || !end.endsWith('\r\nEND:VCALENDAR\r\n')) {
    throw new Error('invalid_calendar');
  }
}

function ExportForActor() {
  const { t } = useTranslation();
  const label = key => t(`pages.calendar.export.${key}`);
  const selectId = useId();
  const [page, setPage] = useState(0);
  const [revision, setRevision] = useState(0);
  const [portfolios, setPortfolios] = useState([]);
  const [hasNext, setHasNext] = useState(false);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const request = useRef(null);
  const urls = useRef(new Map());

  useEffect(() => () => {
    request.current?.abort();
    for (const [url, timer] of urls.current) { clearTimeout(timer); URL.revokeObjectURL(url); }
    urls.current.clear();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null);
    api.get(`/portfolios?skip=${page * PAGE_SIZE}&limit=${PAGE_SIZE + 1}&sort_by=id`, { signal: controller.signal })
      .then(rows => {
        if (controller.signal.aborted) return;
        if (!Array.isArray(rows) || rows.length > PAGE_SIZE + 1 || rows.some(row =>
          !row || typeof row.id !== 'string' || !row.id || typeof row.name !== 'string' || !row.name.trim()
          || typeof row.timezone !== 'string' || !row.timezone.trim()) || new Set(rows.map(row => row.id)).size !== rows.length) {
          throw new Error(label('invalidPortfolios'));
        }
        setPortfolios(rows.slice(0, PAGE_SIZE)); setHasNext(rows.length > PAGE_SIZE);
      })
      .catch(reason => { if (!controller.signal.aborted) { setError(reason.message || label('failed')); setPortfolios([]); setHasNext(false); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
    // Locale changes translate the view without restarting an authenticated read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, revision]);

  const cancel = () => {
    request.current?.abort(); request.current = null;
    setBusy(false); setError(null); setSuccess(null);
  };
  const changePage = next => { cancel(); setSelected(''); setPortfolios([]); setPage(next); };
  const download = async () => {
    if (request.current || loading) return;
    const portfolio = portfolios.find(row => row.id === selected);
    if (!portfolio) return;
    const controller = new AbortController();
    request.current = controller; setBusy(true); setError(null); setSuccess(null);
    try {
      const blob = await api.getBlob(`/calendar/export.ics?portfolio_id=${encodeURIComponent(portfolio.id)}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      await validateCalendar(blob, controller.signal);
      if (controller.signal.aborted || request.current !== controller) return;
      const url = URL.createObjectURL(blob);
      const timer = setTimeout(() => { URL.revokeObjectURL(url); urls.current.delete(url); }, 1000);
      urls.current.set(url, timer);
      const link = document.createElement('a'); link.href = url; link.download = 'immomanager-calendar.ics';
      document.body.append(link);
      try { link.click(); } finally { link.remove(); }
      setSuccess(portfolio.name);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason.message === 'invalid_calendar' ? label('invalidCalendar') : reason.message || label('failed'));
    } finally {
      if (request.current === controller) { request.current = null; setBusy(false); }
    }
  };

  return <section className="calendar-export-panel" aria-labelledby={`${selectId}-title`} aria-busy={busy || loading}>
    <div className="calendar-export-panel__intro">
      <CalendarDays size={23} aria-hidden="true" />
      <div><h2 id={`${selectId}-title`}>{label('title')}</h2><p>{label('description')}</p></div>
    </div>
    <div className="calendar-export-panel__controls">
      <div className="calendar-export-panel__choice">
        <label htmlFor={selectId}>{label('portfolio')}</label>
        <select id={selectId} value={selected} disabled={loading} aria-describedby={`${selectId}-hint`}
          onChange={event => { cancel(); setSelected(event.target.value); }}>
          <option value="">{label('choose')}</option>
          {portfolios.map(portfolio => <option key={portfolio.id} value={portfolio.id}>{portfolio.name} · {portfolio.timezone}</option>)}
        </select>
      </div>
      <button type="button" className="btn btn-primary" disabled={!selected || busy || loading} onClick={download}>
        <Download size={17} aria-hidden="true" />{label(busy ? 'preparing' : 'download')}
      </button>
    </div>
    <p className="calendar-export-panel__hint" id={`${selectId}-hint`}>{label('hint')}</p>
    {(page > 0 || hasNext) && <nav className="calendar-export-panel__paging" aria-label={label('paging')}>
      <button type="button" className="btn btn-sm btn-secondary" disabled={page === 0 || loading} onClick={() => changePage(page - 1)}>{label('previous')}</button>
      <span>{t('pages.calendar.export.page', { page: page + 1 })}</span>
      <button type="button" className="btn btn-sm btn-secondary" disabled={!hasNext || loading} onClick={() => changePage(page + 1)}>{label('next')}</button>
    </nav>}
    {loading && <p role="status">{label('loading')}</p>}
    {!loading && !error && portfolios.length === 0 && <p role="status">{label('empty')}</p>}
    {busy && <p role="status">{label('preparing')}</p>}
    {success && <p role="status">{t('pages.calendar.export.downloaded', { portfolio: success })}</p>}
    {error && <div className="calendar-export-panel__error" role="alert"><span>{error}</span>
      {!portfolios.length && <button type="button" className="btn btn-sm btn-secondary" onClick={() => setRevision(value => value + 1)}>{label('retry')}</button>}
    </div>}
  </section>;
}

export default function CalendarExportPanel() {
  const auth = useAuth();
  const user = auth?.user;
  if (!user?.id || user.is_active === false) return null;
  const actor = JSON.stringify([user.id, user.role, user.portfolio_access, [...(user.portfolio_ids || [])].sort()]);
  return <ExportForActor key={actor} />;
}
