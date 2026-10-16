import NotificationArrival from './NotificationArrival';
import { useState, useRef, useCallback, useEffect } from 'react';
import { api } from '../api';
import { PlusIcon, TrashIcon } from './Icons';
import { useConfirm } from './ConfirmDialog';
import { resolveFileUrl } from '../features/partyWorkspace/files';
import { prepareUploadAccess } from '../utils/uploadAccess';
import { useCanWrite } from '../contexts/AuthContext';
import FileViewer from './FileViewer';
import './photoTools.css';

// onChange (optional) runs after a photo was added or removed, e.g. to refresh a record that lists them.
export default function PhotoDropZone({ entityType, entityId, onChange }) {
  return entityId ? <PhotoDropZoneSession key={`${entityType}:${entityId}`} entityType={entityType} entityId={entityId}
    onChange={onChange} /> : null;
}

function PhotoDropZoneSession({ entityType, entityId, onChange }) {
  const confirm = useConfirm();
  const [photos, setPhotos] = useState([]);
  const [loadedPhotos, setLoadedPhotos] = useState({});
  const [uploading, setUploading] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [progress, setProgress] = useState('');
  const [viewer, setViewer] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [photoRevision, setPhotoRevision] = useState(0);
  const fileRef = useRef(null);
  const requestRef = useRef(null);
  const mounted = useRef(false);
  const busy = useRef(false);
  const canEdit = useCanWrite('/photos');

  const loadPhotos = useCallback(async () => {
    if (!mounted.current) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoadError(null);
    try {
      const rows = await api.get(`/photos?entity_type=${encodeURIComponent(entityType)}&entity_id=${encodeURIComponent(entityId)}`, { signal: controller.signal });
      if (!Array.isArray(rows)) throw new Error('Die Fotos konnten nicht gelesen werden.');
      await Promise.all(rows.map(photo => prepareUploadAccess(resolveFileUrl(photo.file_url), { signal: controller.signal })));
      if (!controller.signal.aborted) {
        setLoadedPhotos({}); setPhotos(rows);
        setPhotoRevision(value => value + 1);
      }
    } catch (error) {
      if (!controller.signal.aborted) setLoadError(error.message);
    }
  }, [entityType, entityId]);

  useEffect(() => {
    mounted.current = true;
    loadPhotos();
    return () => { mounted.current = false; requestRef.current?.abort(); };
  }, [loadPhotos]);

  const uploadFiles = async files => {
    if (busy.current || !canEdit || !files.length) return;
    busy.current = true; setUploading(true); setActionError(null);
    const errors = [];
    let saved = 0;
    try {
      const current = api.captureSession();
      for (const [index, file] of files.entries()) {
        if (!mounted.current) break;
        current();
        setProgress(`Foto ${index + 1} von ${files.length} wird gespeichert…`);
        const formData = new FormData();
        formData.append('file', file);
        try {
          await api.upload(`/photos/upload?entity_type=${encodeURIComponent(entityType)}&entity_id=${encodeURIComponent(entityId)}`, formData);
          current();
          saved += 1;
        } catch (error) {
          current();
          errors.push(`${file.name}: ${error.message || 'Speichern fehlgeschlagen.'}`);
        }
      }
      if (!mounted.current) return;
      setProgress(`${saved} von ${files.length} ${files.length === 1 ? 'Foto gespeichert' : 'Fotos gespeichert'}.`);
      if (errors.length) setActionError(`${errors.join(' · ')} Aktualisieren Sie die Fotoliste vor einem erneuten Upload, um doppelte Fotos zu vermeiden.`);
      await loadPhotos();
      if (mounted.current && saved) onChange?.();
    } catch (error) {
      if (mounted.current) setActionError(error.message || 'Der Upload wurde unterbrochen. Bitte Fotoliste aktualisieren.');
    } finally {
      busy.current = false;
      if (mounted.current) setUploading(false);
    }
  };

  const handleDrop = e => {
    e.preventDefault();
    setDragActive(false);
    const files = Array.from(e.dataTransfer?.files || []);
    uploadFiles(files);
  };

  const handleDelete = async (photoId) => {
    if (busy.current || !canEdit) return;
    busy.current = true;
    try {
      if (!await confirm('Foto wirklich löschen?')) return;
      if (!mounted.current) return;
      setUploading(true); setActionError(null); setProgress('Foto wird gelöscht…');
      const current = api.captureSession();
      await api.del(`/photos/${photoId}`);
      current();
      if (!mounted.current) return;
      setProgress('Foto gelöscht.');
      await loadPhotos();
      if (mounted.current) onChange?.();
    } catch (err) {
      if (mounted.current) { setActionError(err.message || 'Das Foto konnte nicht gelöscht werden.'); setProgress(''); }
    } finally { busy.current = false; if (mounted.current) setUploading(false); }
  };

  if (!entityId) return null;

  return (
    <div className="photo-drop-zone-container">
      <NotificationArrival rows={photos.filter(photo => loadedPhotos[photo.id])} ready={!loadError && photoRevision > 0} />
      {canEdit && <div className={`photo-drop-zone ${dragActive ? 'drag-active' : ''}`}
        onDragOver={e => { e.preventDefault(); if (!uploading) setDragActive(true); }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
      >
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          multiple
          aria-label="Fotos auswählen"
          disabled={uploading}
          style={{ display: 'none' }}
          onChange={e => { const files = Array.from(e.target.files || []); e.target.value = ''; uploadFiles(files); }}
        />
        <button type="button" className="btn btn-secondary" onClick={() => fileRef.current?.click()} disabled={uploading}><PlusIcon size={18} aria-hidden="true" />Fotos hinzufügen</button>
        <span>Oder Bilder hierher ziehen. Sie werden direkt gespeichert.</span>
      </div>}
      {progress && <p className="photo-tools-status" role="status">{progress}</p>}
      {actionError && <div className="alert alert-error photo-tools-error" role="alert"><p>{actionError}</p><button type="button" className="btn btn-sm btn-secondary" disabled={uploading} onClick={loadPhotos}>Fotoliste aktualisieren</button></div>}
      {loadError && <div role="alert"><p>{loadError}</p><button type="button" className="btn btn-secondary" onClick={loadPhotos}>Erneut versuchen</button></div>}
      {photos.length > 0 && (
        <div className="photo-grid">
          {photos.map(p => (
            <div key={`${photoRevision}:${p.id}`} className="photo-thumb">
              {resolveFileUrl(p.file_url) ? <button type="button" className="photo-preview-button" aria-label={`Foto ansehen: ${p.caption || 'Foto'}`} onClick={() => setViewer(p)}><img src={resolveFileUrl(p.file_url)} alt={p.caption || 'Foto'} onLoad={() => setLoadedPhotos(current => ({ ...current, [p.id]: true }))} onError={() => setLoadError('Ein Foto konnte nicht geladen werden. Bitte erneut versuchen.')} /></button> : <span>Kein gültiger Dateiverweis</span>}
              {p.caption && <span className="photo-caption">{p.caption}</span>}
              {canEdit && <button type="button" className="photo-delete-btn" disabled={uploading} onClick={() => handleDelete(p.id)} aria-label={`Foto löschen: ${p.caption || 'Foto'}`} title="Löschen">
                <TrashIcon size={14} />
              </button>}
            </div>
          ))}
        </div>
      )}
      {!canEdit && !loadError && photoRevision > 0 && !photos.length && <p className="text-muted">Keine Fotos hinterlegt.</p>}
      {viewer && <FileViewer fileUrl={viewer.file_url} title={viewer.caption || 'Foto'} onClose={() => setViewer(null)} />}
    </div>
  );
}
