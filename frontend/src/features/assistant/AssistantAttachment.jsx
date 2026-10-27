import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { File, Image, X, Download } from 'lucide-react';
import { api } from '../../api';
import { formatBytes } from '../../utils/format';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import { assistantApi } from './assistantApi';
import PdfPreview from '../../components/PdfPreview';
import '../partyWorkspace/fileViewer.css';

export default function AssistantAttachment({ attachment, onRemove, disabled }) {
  const [open, setOpen] = useState(false);
  return <div className="assistant-attachment">
    {attachment.mime?.startsWith('image/') ? <Image size={22} aria-hidden="true" /> : <File size={22} aria-hidden="true" />}
    <button type="button" className="assistant-attachment-name" onClick={() => setOpen(true)} aria-label={`Datei ansehen: ${attachment.name}`}>
      {attachment.name}<small>{formatBytes(attachment.byte_length)}{attachment.status && attachment.status !== 'ready' ? ` · ${attachment.status === 'processing' ? 'Wird verarbeitet' : attachment.status === 'failed' ? 'Analyse fehlgeschlagen' : 'Angehängt'}` : ''}</small>
    </button>
    {onRemove && <button type="button" className="assistant-remove" disabled={disabled} aria-label={`Datei entfernen: ${attachment.name}`} onClick={onRemove}><X size={15} /></button>}
    {open && <AttachmentPreview attachment={attachment} onClose={() => setOpen(false)} />}
  </div>;
}

function AttachmentPreview({ attachment, onClose }) {
  const ref = useRef(null);
  const [source, setSource] = useState(null);
  const [text, setText] = useState(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useModalDialog(ref, onClose);
  useEffect(() => {
    const controller = new AbortController(); const session = api.captureSession(); let url;
    setError(''); setSource(null);
    assistantApi.download(attachment.id, { signal: controller.signal }).then(async blob => {
      session(); if (controller.signal.aborted) return;
      if (attachment.mime === 'text/plain' || attachment.mime === 'text/csv') {
        const value = await blob.slice(0, 200000).text(); session(); if (controller.signal.aborted) return;
        setText(value);
      }
      url = URL.createObjectURL(blob); setSource(url);
    }).catch(failure => { if (!controller.signal.aborted) setError(failure.message); });
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [attachment.id, attachment.mime, attempt]);
  return createPortal(<div className="modal-overlay" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={ref} role="dialog" aria-modal="true" aria-label={attachment.name} tabIndex={-1} className="modal assistant-file-dialog">
      <header className="modal-header"><h2>{attachment.name}</h2><button type="button" className="assistant-remove" aria-label="Dateivorschau schließen" onClick={onClose}><X /></button></header>
      <div className="modal-body">
        {error ? <p role="alert">{error} <button type="button" onClick={() => setAttempt(value => value + 1)}>Vorschau erneut laden</button></p> : !source ? <p role="status">Datei wird geschützt geladen …</p>
          : attachment.mime?.startsWith('image/') && attachment.mime !== 'image/svg+xml' ? <img src={source} alt={attachment.name} onError={() => setError('Dieses Bild kann im Browser nicht dargestellt werden.')} />
            : attachment.mime === 'application/pdf' ? <PdfPreview url={source} title={attachment.name} />
              : text != null ? <pre>{text}</pre> : <p>Für diesen Dateityp steht der Download bereit.</p>}
        {source && <a className="btn btn-secondary" href={source} download={attachment.name}><Download size={15} /> Original herunterladen</a>}
      </div>
    </section>
  </div>, document.body);
}
