import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../api';
import { CloseIcon } from './Icons';
import useProtectedFile from '../hooks/useProtectedFile';

export default function FileViewer({ fileUrl, onClose }) {
  const [ocr, setOcr] = useState({ reference: null, text: null, error: null });
  const [ocrRevision, setOcrRevision] = useState(0);
  const [showOcr, setShowOcr] = useState(false);
  const [copied, setCopied] = useState(false);

  const file = useProtectedFile(fileUrl);
  const ocrText = ocr.reference === fileUrl ? ocr.text : null;
  const ocrError = ocr.reference === fileUrl ? ocr.error : null;
  const copyTimer = useRef(null);
  const currentFile = useRef(fileUrl);

  useEffect(() => {
    const controller = new AbortController();
    currentFile.current = fileUrl;
    setOcr({ reference: fileUrl, text: null, error: null });
    setShowOcr(false);
    setCopied(false);
    if (fileUrl) api.get(`/files/ocr-text?file_url=${encodeURIComponent(fileUrl)}`, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setOcr({ reference: fileUrl, text: data?.has_ocr ? data.text : null, error: null });
      })
      .catch((err) => { if (!controller.signal.aborted) setOcr({ reference: fileUrl, text: null, error: err.message }); });
    return () => { controller.abort(); currentFile.current = null; clearTimeout(copyTimer.current); };
  }, [fileUrl, ocrRevision]);

  const handleCopy = useCallback(() => {
    if (!ocrText) return;
    navigator.clipboard.writeText(ocrText).then(() => {
      if (currentFile.current !== fileUrl) return;
      setCopied(true);
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(false), 2000);
    }).catch(() => { if (currentFile.current === fileUrl) setOcr(current => ({ ...current, error: 'Text konnte nicht kopiert werden.' })); });
  }, [ocrText, fileUrl]);

  if (!fileUrl) return null;

  const kind = file.kind;
  const filename = file.key.split('/').pop();

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="file-viewer-modal" style={{ background: 'var(--color-surface)' }} role="dialog" aria-modal="true" aria-label="Dateiansicht" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Dateiansicht</h3>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            {ocrText && (
              <button
                className={`btn btn-sm ${showOcr ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setShowOcr(!showOcr)}
              >
                {showOcr ? 'Original' : 'OCR-Text'}
              </button>
            )}
            {file.url && <a href={file.url} download={filename} className="btn btn-sm btn-secondary">Herunterladen</a>}
            <button onClick={onClose} className="btn-close" aria-label="Schließen">
              <CloseIcon size={18} />
            </button>
          </div>
        </div>
        <div className="file-viewer-body">
          {file.loading && <p role="status">Datei wird geladen...</p>}
          {file.error && <div role="alert"><p>{file.error}</p><button className="btn btn-secondary" onClick={file.retry}>Erneut versuchen</button></div>}
          {file.previewError && <p role="alert">{file.previewError}</p>}
          {ocrError && <div><p>OCR-Text nicht verfügbar: {ocrError}</p><button className="btn btn-sm btn-secondary" onClick={() => setOcrRevision(value => value + 1)}>OCR erneut laden</button></div>}
          {showOcr && ocrText ? (
            <div className="ocr-overlay">
              <div className="ocr-toolbar">
                <button className="btn btn-sm btn-secondary" onClick={handleCopy}>
                  {copied ? 'Kopiert!' : 'Text kopieren'}
                </button>
              </div>
              <pre className="ocr-text">{ocrText}</pre>
            </div>
          ) : file.url && kind === 'image' ? (
            <img src={file.url} alt="Dokument" className="file-viewer-image" />
          ) : file.url && kind === 'pdf' ? (
            <iframe src={file.url} title="PDF Viewer" className="file-viewer-pdf" />
          ) : file.url ? (
            <div className="file-viewer-fallback">
              <p>Vorschau nicht verfügbar</p>
              <a href={file.url} download={filename} className="btn btn-primary">
                Datei herunterladen
              </a>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
