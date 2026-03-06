import { useState, useEffect, useCallback, useMemo } from 'react';
import { api } from '../api';
import { CloseIcon } from './Icons';

const API_BASE = import.meta.env.VITE_API_URL || '/api/v1';

function resolveFileUrl(url) {
  if (!url) return '';
  if (/^https?:\/\//i.test(url) || /^s3:\/\//i.test(url)) return url;
  if (url.startsWith('/uploads/')) {
    const origin = API_BASE.startsWith('http') ? new URL(API_BASE).origin : window.location.origin;
    return `${origin}${url}`;
  }
  return url;
}

export default function FileViewer({ fileUrl, onClose }) {
  const [ocrText, setOcrText] = useState(null);
  const [showOcr, setShowOcr] = useState(false);
  const [copied, setCopied] = useState(false);

  const resolvedUrl = useMemo(() => resolveFileUrl(fileUrl), [fileUrl]);

  useEffect(() => {
    if (!fileUrl) return;
    api.get(`/files/ocr-text?file_url=${encodeURIComponent(fileUrl)}`)
      .then((data) => {
        if (data?.has_ocr) setOcrText(data.text);
      })
      .catch((err) => console.warn('[FileViewer] OCR load:', err.message));
  }, [fileUrl]);

  const handleCopy = useCallback(() => {
    if (!ocrText) return;
    navigator.clipboard.writeText(ocrText).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [ocrText]);

  if (!fileUrl) return null;

  const isImage = /\.(png|jpe?g|gif|bmp|tiff?|webp)$/i.test(fileUrl);
  const isPdf = /\.pdf$/i.test(fileUrl);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="file-viewer-modal" onClick={(e) => e.stopPropagation()}>
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
            <a href={resolvedUrl} target="_blank" rel="noopener noreferrer" className="btn btn-sm btn-secondary">
              Öffnen
            </a>
            <button onClick={onClose} className="btn-close" aria-label="Close">
              <CloseIcon size={18} />
            </button>
          </div>
        </div>
        <div className="file-viewer-body">
          {showOcr && ocrText ? (
            <div className="ocr-overlay">
              <div className="ocr-toolbar">
                <button className="btn btn-sm btn-secondary" onClick={handleCopy}>
                  {copied ? 'Kopiert!' : 'Text kopieren'}
                </button>
              </div>
              <pre className="ocr-text">{ocrText}</pre>
            </div>
          ) : isImage ? (
            <img src={resolvedUrl} alt="Dokument" className="file-viewer-image" />
          ) : isPdf ? (
            <iframe src={resolvedUrl} title="PDF Viewer" className="file-viewer-pdf" />
          ) : (
            <div className="file-viewer-fallback">
              <p>Vorschau nicht verfügbar</p>
              <a href={resolvedUrl} target="_blank" rel="noopener noreferrer" className="btn btn-primary">
                Datei herunterladen
              </a>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
