import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import FileViewer from '../../components/FileViewer';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import { downloadVersion } from '../documentWork/documentWorkApi';
import DocumentPreview from './DocumentPreview';
import { documentDetailService, shownFilename } from './documentDetailApi';
import { entityHref } from '../../utils/entityLinks';
import './documentDetail.css';
import '../partyWorkspace/fileViewer.css';

/** Every "Ansehen" action opens the current archived version, not a superseded upload. */
export default function CurrentDocumentViewer({ document: record, onClose, service = documentDetailService }) {
  const [state, setState] = useState({ loading: true, details: null, error: null });
  const [attempt, setAttempt] = useState(0);
  const [downloadError, setDownloadError] = useState(null);
  const [busy, setBusy] = useState(false);
  const dialog = useRef(null);
  const head = state.details?.versions?.items?.[0];
  const original = !state.loading && !state.error && !head;
  useModalDialog(dialog, onClose, !original);
  useEffect(() => {
    const controller = new AbortController();
    setState({ loading: true, details: null, error: null });
    service.load(record.id, { signal: controller.signal }).then(details => {
      if (!details?.document || !Array.isArray(details.versions?.items)) throw new Error('Die aktuelle Dokumentfassung konnte nicht eindeutig gelesen werden.');
      if (!controller.signal.aborted) setState({ loading: false, details, error: null });
    }).catch(error => {
      if (!controller.signal.aborted) setState({ loading: false, details: null, error: error.message || 'Das Dokument konnte nicht geladen werden.' });
    });
    return () => controller.abort();
  }, [record.id, service, attempt]);
  if (original) return <FileViewer fileUrl={state.details.document.file_url} title={state.details.document.title} onClose={onClose} />;
  const download = async () => {
    if (busy) return;
    setBusy(true); setDownloadError(null);
    try { await downloadVersion(record.id, head.id, shownFilename(head.filename)); }
    catch (error) { setDownloadError(error.message || 'Die Fassung konnte nicht heruntergeladen werden.'); }
    finally { setBusy(false); }
  };
  return createPortal(<div className="modal-overlay file-viewer-overlay" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={dialog} className="file-viewer-modal current-document-viewer" role="dialog" aria-modal="true" aria-label={record.title} tabIndex={-1}>
      <header className="modal-header file-viewer-header"><h3>{record.title}</h3>
        <button type="button" className="btn-close" aria-label="Schließen" onClick={onClose}>✕</button></header>
      <div className="file-viewer-body current-document-body">
        {state.loading && <p role="status">Aktuelle Dokumentfassung wird geladen …</p>}
        {state.error && <div role="alert" className="alert alert-error">{state.error}
          <button type="button" className="btn btn-secondary" onClick={() => setAttempt(value => value + 1)}>Erneut laden</button></div>}
        {head && <><p className="document-dossier-note">Aktuelle Fassung {head.number} · {shownFilename(head.filename)}</p>
          <DocumentPreview key={head.id} id={record.id} head={head} document={state.details.document} service={service} />
          {downloadError && <p role="alert" className="text-red">{downloadError}</p>}
          <button type="button" className="btn btn-secondary" disabled={busy} onClick={download}>Aktuelle Fassung herunterladen</button></>}
        <Link className="btn btn-secondary" to={entityHref('document', record.id)} onClick={onClose}>Dokumentakte öffnen</Link>
      </div>
    </section>
  </div>, window.document.body);
}
