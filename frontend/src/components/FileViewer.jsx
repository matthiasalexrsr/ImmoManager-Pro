import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../api';
import { CloseIcon } from './Icons';
import PdfPreview from './PdfPreview';
import { downloadFile, fileKind, resolveFileUrl } from '../features/partyWorkspace/files';
import { useModalDialog } from '../features/partyWorkspace/useModalDialog';
import { usePartyText } from '../features/partyWorkspace/text';
import { isOwnUploadUrl, prepareUploadAccess } from '../utils/uploadAccess';
import '../features/partyWorkspace/fileViewer.css';

export default function FileViewer({ fileUrl, title, onClose }) {
  const { text } = usePartyText();
  const [ocr, setOcr] = useState(null);
  const [showOcr, setShowOcr] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(null);
  const [imageFailed, setImageFailed] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [opening, setOpening] = useState(false);
  const [access, setAccess] = useState(null);
  const [accessAttempt, setAccessAttempt] = useState(0);
  const dialogRef = useRef(null);
  const sessionRef = useRef(null);
  const downloadRef = useRef(null);
  const openRef = useRef(null);
  const timerRef = useRef(null);
  const resolvedUrl = resolveFileUrl(fileUrl);
  const kind = fileKind(fileUrl);
  const label = title || text.fileView;
  const ocrText = ocr?.fileUrl === fileUrl ? ocr.text : null;
  const ownFile = isOwnUploadUrl(resolvedUrl);
  const activeAccess = access?.url === resolvedUrl && access.attempt === accessAttempt ? access : null;
  const accessReady = !ownFile || kind === 'pdf' || activeAccess?.ready;
  useModalDialog(dialogRef, onClose, Boolean(fileUrl));

  useEffect(() => {
    const controller = new AbortController();
    sessionRef.current = controller;
    setOcr(null);
    setShowOcr(false);
    setCopied(false);
    setError(null);
    setImageFailed(false);
    setDownloading(false);
    setOpening(false);
    clearTimeout(timerRef.current);
    if (fileUrl && resolvedUrl && ownFile) {
      api.get(`/files/ocr-text?file_url=${encodeURIComponent(fileUrl)}`, { signal: controller.signal })
        .then(data => {
          if (controller.signal.aborted || sessionRef.current !== controller) return;
          setOcr({ fileUrl, text: data?.has_ocr && typeof data.text === 'string' ? data.text : null });
        })
        .catch(() => {}); // OCR is optional; the original file remains available.
    }
    return () => {
      controller.abort();
      downloadRef.current?.abort();
      openRef.current?.controller.abort();
      openRef.current?.popup.close();
      openRef.current = null;
      clearTimeout(timerRef.current);
    };
  }, [fileUrl, resolvedUrl, ownFile]);

  useEffect(() => {
    if (!resolvedUrl || !ownFile || kind === 'pdf') return;
    const controller = new AbortController();
    setAccess({ url: resolvedUrl, attempt: accessAttempt, ready: false });
    prepareUploadAccess(resolvedUrl, { signal: controller.signal }).then(() => {
      if (!controller.signal.aborted) setAccess({ url: resolvedUrl, attempt: accessAttempt, ready: true });
    }).catch(failure => {
      if (!controller.signal.aborted) setAccess({ url: resolvedUrl, attempt: accessAttempt, ready: false, error: failure.message });
    });
    return () => controller.abort();
  }, [resolvedUrl, ownFile, kind, accessAttempt]);

  const retryPreview = () => { setImageFailed(false); setAccessAttempt(value => value + 1); };

  const handleOpen = async event => {
    if (!ownFile) return;
    event.preventDefault();
    if (opening) return;
    // Reserve the user's new tab before awaiting the cookie, avoiding a blocked
    // asynchronous popup. The blank tab has no access to the originating window.
    const popup = window.open('about:blank', '_blank');
    if (!popup) { setError(text.openFailed); return; }
    popup.opener = null;
    const controller = new AbortController();
    const request = { controller, popup };
    openRef.current = request;
    setOpening(true);
    setError(null);
    try {
      await prepareUploadAccess(resolvedUrl, { signal: controller.signal });
      if (!controller.signal.aborted) popup.location.replace(resolvedUrl);
    } catch (failure) {
      popup.close();
      if (!controller.signal.aborted) setError(failure.message || text.openFailed);
    } finally {
      if (openRef.current === request) openRef.current = null;
      if (!controller.signal.aborted) setOpening(false);
    }
  };

  const handleCopy = async () => {
    if (!ocrText) return;
    const owner = sessionRef.current;
    try {
      await navigator.clipboard.writeText(ocrText);
      if (owner?.signal.aborted || sessionRef.current !== owner) return;
      setCopied(true);
      setError(null);
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      if (!owner?.signal.aborted && sessionRef.current === owner) setError(text.copyFailed);
    }
  };

  const handleDownload = async () => {
    const controller = new AbortController();
    downloadRef.current?.abort();
    downloadRef.current = controller;
    setDownloading(true);
    setError(null);
    try {
      await downloadFile(fileUrl, title, { signal: controller.signal });
    } catch (err) {
      if (!controller.signal.aborted) setError(err.message || text.downloadFailed);
    } finally {
      if (!controller.signal.aborted) setDownloading(false);
    }
  };

  if (!fileUrl) return null;
  return createPortal(
    <div className="modal-overlay file-viewer-overlay" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="file-viewer-modal" ref={dialogRef} role="dialog" aria-modal="true" aria-label={label} tabIndex={-1}>
        <div className="modal-header file-viewer-header">
          <h3>{label}</h3>
          <div className="file-viewer-actions">
            {ocrText && <button type="button" className={`btn btn-sm ${showOcr ? 'btn-primary' : 'btn-secondary'}`} aria-pressed={showOcr} onClick={() => setShowOcr(value => !value)}>{showOcr ? text.original : text.ocr}</button>}
            {resolvedUrl && <><a href={resolvedUrl} target="_blank" rel="noopener noreferrer" className="btn btn-sm btn-secondary" onClick={handleOpen} aria-busy={opening || undefined}>{text.open}</a><button type="button" className="btn btn-sm btn-secondary" onClick={handleDownload} disabled={downloading}>{downloading ? text.downloading : text.download}</button></>}
            <button type="button" onClick={onClose} className="btn-close" aria-label={text.close}><CloseIcon size={18} /></button>
          </div>
        </div>
        {error && <p className="file-viewer-error" role="alert">{error}</p>}
        <div className="file-viewer-body">
          {!resolvedUrl ? <div className="file-viewer-fallback" role="alert"><p>{text.invalidFile}</p></div> : showOcr && ocrText ? <div className="ocr-overlay"><div className="ocr-toolbar"><button type="button" className="btn btn-sm btn-secondary" onClick={handleCopy}>{copied ? text.copied : text.copyText}</button><span className="file-viewer-status" role="status">{copied ? text.copied : ''}</span></div><pre className="ocr-text">{ocrText}</pre></div> : !accessReady ? activeAccess?.error ? <div role="alert"><p>{text.fileAccessFailed}</p><p>{activeAccess.error}</p><button type="button" className="btn btn-secondary" onClick={retryPreview}>{text.retry}</button></div> : <p role="status">{text.loading}</p> : kind === 'image' && !imageFailed ? <img src={resolvedUrl} alt={label} className="file-viewer-image" onError={() => setImageFailed(true)} /> : kind === 'pdf' ? <PdfPreview key={resolvedUrl} url={resolvedUrl} title={label} /> : <div className="file-viewer-fallback"><p>{imageFailed ? text.imageFailed : text.noPreview}</p>{imageFailed && <button type="button" className="btn btn-secondary" onClick={retryPreview}>{text.retry}</button>}<button type="button" className="btn btn-primary" onClick={handleDownload} disabled={downloading}>{downloading ? text.downloading : text.download}</button></div>}
        </div>
      </div>
    </div>, document.body);
}
