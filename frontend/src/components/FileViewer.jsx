import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../api';
import { CloseIcon } from './Icons';
import { downloadFile, fileKind, resolveFileUrl } from '../features/partyWorkspace/files';
import { useModalDialog } from '../features/partyWorkspace/useModalDialog';
import { usePartyText } from '../features/partyWorkspace/text';
import '../features/partyWorkspace/fileViewer.css';

export default function FileViewer({ fileUrl, title, onClose }) {
  const { text } = usePartyText();
  const [ocr, setOcr] = useState(null);
  const [showOcr, setShowOcr] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(null);
  const [imageFailed, setImageFailed] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const dialogRef = useRef(null);
  const sessionRef = useRef(null);
  const downloadRef = useRef(null);
  const timerRef = useRef(null);
  const resolvedUrl = resolveFileUrl(fileUrl);
  const kind = fileKind(fileUrl);
  const label = title || text.fileView;
  const ocrText = ocr?.fileUrl === fileUrl ? ocr.text : null;
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
    clearTimeout(timerRef.current);
    if (fileUrl && resolvedUrl) {
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
      clearTimeout(timerRef.current);
    };
  }, [fileUrl, resolvedUrl]);

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
            {resolvedUrl && <><a href={resolvedUrl} target="_blank" rel="noopener noreferrer" className="btn btn-sm btn-secondary">{text.open}</a><button type="button" className="btn btn-sm btn-secondary" onClick={handleDownload} disabled={downloading}>{downloading ? text.downloading : text.download}</button></>}
            <button type="button" onClick={onClose} className="btn-close" aria-label={text.close}><CloseIcon size={18} /></button>
          </div>
        </div>
        {error && <p className="file-viewer-error" role="alert">{error}</p>}
        <div className="file-viewer-body">
          {!resolvedUrl ? <div className="file-viewer-fallback" role="alert"><p>{text.invalidFile}</p></div> : showOcr && ocrText ? <div className="ocr-overlay"><div className="ocr-toolbar"><button type="button" className="btn btn-sm btn-secondary" onClick={handleCopy}>{copied ? text.copied : text.copyText}</button><span className="file-viewer-status" role="status">{copied ? text.copied : ''}</span></div><pre className="ocr-text">{ocrText}</pre></div> : kind === 'image' && !imageFailed ? <img src={resolvedUrl} alt={label} className="file-viewer-image" onError={() => setImageFailed(true)} /> : kind === 'pdf' ? <iframe src={resolvedUrl} title={label} className="file-viewer-pdf" /> : <div className="file-viewer-fallback"><p>{imageFailed ? text.imageFailed : text.noPreview}</p><button type="button" className="btn btn-primary" onClick={handleDownload} disabled={downloading}>{downloading ? text.downloading : text.download}</button></div>}
        </div>
      </div>
    </div>, document.body);
}
