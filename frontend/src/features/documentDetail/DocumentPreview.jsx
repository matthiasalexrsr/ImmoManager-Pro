import { useEffect, useState } from 'react';
import PdfPreview from '../../components/PdfPreview';
import { fileKind, resolveFileUrl } from '../partyWorkspace/files';
import { previewKind, sizeLabel } from './documentDetailApi';

const PREVIEW_LIMIT = 20 * 1024 * 1024;

export default function DocumentPreview({ id, head, document, service }) {
  const [state, setState] = useState({ url: null, error: null, wanted: Boolean(head && head.size_bytes <= PREVIEW_LIMIT) });
  const [attempt, setAttempt] = useState(0);
  const kind = head ? previewKind(head.media_type, head.filename) : fileKind(document.file_url);
  const headId = head?.id;
  useEffect(() => {
    if (!headId || !state.wanted || kind === 'other') return undefined;
    const controller = new AbortController();
    setState(current => ({ ...current, url: null, error: null }));
    let url = null;
    service.versionBlob(id, headId, { signal: controller.signal })
      .then(blob => { if (!controller.signal.aborted) { url = URL.createObjectURL(blob); setState(current => ({ ...current, url, error: null })); } })
      .catch(failure => { if (!controller.signal.aborted) setState(current => ({ ...current, error: failure.message || 'Die Fassung konnte nicht geladen werden.' })); });
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [id, headId, kind, service, state.wanted, attempt]);

  if (!head && !document.file_url) return <p className="text-muted">Keine Datei vorhanden.</p>;
  if (kind === 'other') return <p className="text-muted">Für dieses Dateiformat gibt es keine Vorschau. {head ? 'Die Fassung lässt sich unten herunterladen' : 'Die Datei lässt sich über „Hochgeladene Datei ansehen“ öffnen'}{head?.media_type?.includes('word') || /\.docx?$/i.test(head?.filename || '') ? ' oder in den Dokumentwerkzeugen bearbeiten.' : '.'}</p>;
  if (!head) {
    const url = resolveFileUrl(document.file_url);
    return kind === 'pdf' ? <PdfPreview url={url} title={document.title} />
      : <p className="text-muted">Bilder öffnen Sie über „Hochgeladene Datei ansehen“.</p>;
  }
  if (!state.wanted) return <p className="text-muted">Die Fassung ist {sizeLabel(head.size_bytes)} groß. <button type="button" className="btn btn-sm btn-secondary" onClick={() => setState(current => ({ ...current, wanted: true }))}>Vorschau trotzdem laden</button></p>;
  if (state.error) return <p role="alert" className="text-red">{state.error} <button type="button" className="btn btn-secondary" onClick={() => setAttempt(value => value + 1)}>Vorschau erneut laden</button></p>;
  if (!state.url) return <p role="status" className="text-muted">Vorschau wird geladen …</p>;
  return kind === 'pdf' ? <PdfPreview url={state.url} title={document.title} />
    : <img className="document-preview-image" src={state.url} alt={`Fassung ${head.number} von ${document.title}`} />;
}
