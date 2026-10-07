import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Download, FileSearch, FileText, LayoutGrid, List, Plus, Search } from 'lucide-react';
import { api } from '../../api';
import { useCanWrite } from '../../contexts/AuthContext';
import { formatDate } from '../../utils/format';
import { downloadFile, resolveFileUrl } from './files';
import { usePartyText } from './text';

const PAGE_SIZE = 25;
const initialState = path => ({ path, items: [], total: 0, next: 0, hasMore: false, loading: true, loadingMore: false, error: null, failedPage: false });

function readPage(data, previousSkip = -1) {
  if (!data || !Array.isArray(data.items) || !Number.isFinite(data.total)) throw new Error('Ungültige Serverantwort');
  const next = Number(data.skip) + Number(data.limit);
  if (data.has_more && (!data.items.length || !Number.isFinite(next) || next <= previousSkip)) throw new Error('Die nächste Dokumentenseite ist nicht verfügbar.');
  return { items: data.items, total: data.total, next, hasMore: Boolean(data.has_more) };
}

function useDocumentPages(path) {
  const [state, setState] = useState(() => initialState(path));
  const [attempt, setAttempt] = useState(0);
  const requestRef = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    const request = { path, controller };
    requestRef.current = request;
    setState(initialState(path));
    api.get(`${path}&skip=0&limit=${PAGE_SIZE}`, { signal: controller.signal })
      .then(data => {
        if (requestRef.current !== request || controller.signal.aborted) return;
        const page = readPage(data);
        setState({ ...initialState(path), ...page, loading: false });
      })
      .catch(error => {
        if (requestRef.current !== request || controller.signal.aborted) return;
        setState(previous => ({ ...previous, loading: false, error, failedPage: false }));
      });
    return () => {
      controller.abort();
      if (requestRef.current?.path === path) requestRef.current.controller.abort();
    };
  }, [path, attempt]);

  const loadMore = useCallback(async () => {
    if (state.path !== path || state.loading || state.loadingMore || !state.hasMore) return;
    requestRef.current?.controller.abort();
    const controller = new AbortController();
    const request = { path, controller };
    requestRef.current = request;
    setState(previous => ({ ...previous, loadingMore: true, error: null }));
    try {
      const data = await api.get(`${path}&skip=${state.next}&limit=${PAGE_SIZE}`, { signal: controller.signal });
      if (requestRef.current !== request || controller.signal.aborted) return;
      const page = readPage(data, state.next);
      setState(previous => {
        const seen = new Set(previous.items.map(item => item.id));
        const added = page.items.filter(item => !seen.has(item.id));
        if (page.hasMore && !added.length) return { ...previous, loadingMore: false, error: new Error('Die nächste Dokumentenseite enthält keine neuen Dokumente.'), failedPage: true };
        return { ...previous, ...page, items: [...previous.items, ...added], loadingMore: false, error: null, failedPage: false };
      });
    } catch (error) {
      if (requestRef.current !== request || controller.signal.aborted) return;
      setState(previous => ({ ...previous, loadingMore: false, error, failedPage: true }));
    }
  }, [path, state]);

  return { ...(state.path === path ? state : initialState(path)), loadMore, retry: () => state.failedPage ? loadMore() : setAttempt(value => value + 1) };
}

function DocumentCard({ document, contracts, onPreview, view }) {
  const { text } = usePartyText();
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState(null);
  const controllerRef = useRef(null);
  useEffect(() => () => controllerRef.current?.abort(), []);
  const safeUrl = resolveFileUrl(document.file_url);
  const contract = contracts.find(item => item.id === document.contract_id);
  const handleDownload = async () => {
    const controller = new AbortController();
    controllerRef.current?.abort();
    controllerRef.current = controller;
    setDownloading(true);
    setError(null);
    try {
      await downloadFile(document.file_url, document.title, { signal: controller.signal });
    } catch (err) {
      if (!controller.signal.aborted) setError(err.message || text.downloadFailed);
    } finally {
      if (!controller.signal.aborted) setDownloading(false);
    }
  };
  return (
    <li className={`party-document-card party-document-${view}`}>
      <div className="party-file-icon" aria-hidden="true"><FileText size={22} /></div>
      <div className="party-document-main">
        <div className="party-document-meta"><span className="party-tag">{document.document_type || text.unknownType}</span><time dateTime={document.document_date || document.created_at}>{formatDate(document.document_date || document.created_at, { blank: text.noDate })}</time></div>
        <button type="button" className="party-document-title" onClick={() => onPreview(document)} disabled={!safeUrl}>{document.title || text.unknownType}</button>
        {document.description && <p className="party-document-description">{document.description}</p>}
        {document.contract_id && <p className="party-document-contract">{text.contract}: {contract?.contract_number || document.contract_number || document.contract_id}{contract?.unit_label && ` · ${contract.unit_label}`}</p>}
        {!safeUrl && <small className="party-muted">{document.file_url ? text.invalidFile : text.noFile}</small>}
        {error && <p className="party-inline-error" role="alert">{error}</p>}
      </div>
      <div className="party-document-actions">
        <button type="button" className="btn btn-sm btn-secondary" onClick={() => onPreview(document)} disabled={!safeUrl} aria-label={`${text.preview}: ${document.title}`}><FileSearch size={15} aria-hidden="true" />{text.preview}</button>
        <button type="button" className="party-icon-button" onClick={handleDownload} disabled={!safeUrl || downloading} aria-label={`${downloading ? text.downloading : text.download}: ${document.title}`} title={text.download}><Download size={17} aria-hidden="true" /></button>
      </div>
    </li>
  );
}

export default function PartyDocuments({ tenantId, overview, onPreview, contractFilter, onContractFilter }) {
  const { text } = usePartyText();
  const canUpload = useCanWrite('/documents');
  const [query, setQuery] = useState('');
  const [type, setType] = useState('');
  const [view, setView] = useState('list');
  const contracts = overview?.contracts || [];
  const types = overview?.document_types || [];
  const params = new URLSearchParams();
  if (query.trim()) params.set('q', query.trim());
  if (type) params.set('document_type', type);
  if (contractFilter) params.set('contract_id', contractFilter);
  const path = `/tenants/${encodeURIComponent(tenantId)}/documents?${params}`;
  const { items, total, loading, loadingMore, error, hasMore, loadMore, retry } = useDocumentPages(path);
  const documents = items;
  const filtered = Boolean(query.trim() || type || contractFilter);
  const clearFilters = () => { setQuery(''); setType(''); onContractFilter(''); };
  const pageLink = `/documents?tenant_id=${encodeURIComponent(tenantId)}`;

  return (
    <div className="party-documents">
      <div className="party-section-heading"><div><h3>{text.documents}</h3><p className="party-muted">{text.newest}</p></div>{canUpload && <Link className="btn btn-sm btn-primary" to={`${pageLink}&create=1`}><Plus size={16} aria-hidden="true" />{text.upload}</Link>}</div>
      <div className="party-document-tools">
        <label className="party-search"><span className="party-sr-only">{text.search}</span><Search size={17} aria-hidden="true" /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder={text.searchPlaceholder} /></label>
        <div className="party-document-filters">
          <label><span>{text.type}</span><select value={type} onChange={event => setType(event.target.value)}><option value="">{text.allTypes}</option>{types.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
          <label><span>{text.contract}</span><select value={contractFilter} onChange={event => onContractFilter(event.target.value)}><option value="">{text.allContracts}</option>{contracts.map(contract => <option key={contract.id} value={contract.id}>{contract.contract_number}{contract.unit_label ? ` · ${contract.unit_label}` : ''}</option>)}</select></label>
        </div>
      </div>
      <div className="party-document-results"><p className="party-muted" role="status">{!loading && `${documents.length} / ${total} ${text.count}`}</p><div className="party-view-switch" role="group" aria-label={text.documents}><button type="button" aria-label={text.list} title={text.list} aria-pressed={view === 'list'} onClick={() => setView('list')}><List size={17} aria-hidden="true" /></button><button type="button" aria-label={text.grid} title={text.grid} aria-pressed={view === 'grid'} onClick={() => setView('grid')}><LayoutGrid size={17} aria-hidden="true" /></button></div></div>
      {error && <div className="party-error" role="alert"><p>{text.documentFailed}</p><p className="party-muted">{error.message}</p>{documents.length > 0 && <p className="party-muted">{text.previousResults}</p>}<button type="button" className="btn btn-sm btn-secondary" onClick={retry}>{text.retry}</button></div>}
      {loading ? <div className="party-loading" role="status">{text.loading}</div> : documents.length > 0 ? <ul className={`party-document-collection party-document-collection-${view}`} aria-label={text.documents}>{documents.map(document => <DocumentCard key={document.id} document={document} contracts={contracts} onPreview={onPreview} view={view} />)}</ul> : !error && <div className="party-empty"><FileSearch size={34} aria-hidden="true" /><h4>{filtered ? text.noMatches : text.noDocuments}</h4><p>{filtered ? text.noMatchesHelp : text.noDocumentsHelp}</p>{filtered && <button type="button" className="btn btn-sm btn-secondary" onClick={clearFilters}>{text.clearFilters}</button>}</div>}
      {hasMore && !error && <div className="party-load-more"><button type="button" className="btn btn-secondary" onClick={loadMore} disabled={loadingMore}>{loadingMore ? text.loadingMore : text.more}</button></div>}
      <Link className="party-management-link" to={pageLink}>{text.allDocuments} →</Link>
    </div>
  );
}
