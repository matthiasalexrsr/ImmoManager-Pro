import { useState, useRef, useCallback, useEffect } from 'react';
import { api } from '../api';
import { PlusIcon, TrashIcon } from './Icons';
import { useConfirm } from './ConfirmDialog';
import { resolveFileUrl } from '../features/partyWorkspace/files';
import { prepareUploadAccess } from '../utils/uploadAccess';

const BASE = (import.meta.env.VITE_API_URL || '/api/v1');

export default function PhotoDropZone({ entityType, entityId }) {
  return entityId ? <PhotoDropZoneSession key={`${entityType}:${entityId}`} entityType={entityType} entityId={entityId} /> : null;
}

function PhotoDropZoneSession({ entityType, entityId }) {
  const confirm = useConfirm();
  const [photos, setPhotos] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [photoRevision, setPhotoRevision] = useState(0);
  const fileRef = useRef(null);
  const requestRef = useRef(null);
  const mounted = useRef(false);

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
        setPhotos(rows);
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

  const uploadFile = async (file) => {
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const token = localStorage.getItem('access_token');
      const res = await fetch(
        `${BASE}/photos/upload?entity_type=${entityType}&entity_id=${entityId}`,
        { method: 'POST', body: formData, headers: { Authorization: `Bearer ${token}` } }
      );
      if (!res.ok) throw new Error('Upload fehlgeschlagen');
      loadPhotos();
    } catch (err) {
      console.warn('[PhotoDropZone] upload:', err.message);
    } finally {
      if (mounted.current) setUploading(false);
    }
  };

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragActive(false);
    const files = Array.from(e.dataTransfer?.files || []);
    files.filter(f => f.type.startsWith('image/')).forEach(uploadFile);
  }, [entityType, entityId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDelete = async (photoId) => {
    if (!await confirm('Foto wirklich löschen?')) return;
    try {
      await api.del(`/photos/${photoId}`);
      loadPhotos();
    } catch (err) {
      console.warn('[PhotoDropZone] delete:', err.message);
    }
  };

  if (!entityId) return null;

  return (
    <div className="photo-drop-zone-container">
      <div
        className={`photo-drop-zone ${dragActive ? 'drag-active' : ''}`}
        onDragOver={e => { e.preventDefault(); setDragActive(true); }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
        onClick={() => fileRef.current?.click()}
      >
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          multiple
          style={{ display: 'none' }}
          onChange={e => Array.from(e.target.files).forEach(uploadFile)}
        />
        <PlusIcon size={24} />
        <span>{uploading ? 'Wird hochgeladen...' : 'Fotos hierher ziehen oder klicken (automatisch speichern)'}</span>
      </div>
      {loadError && <div role="alert"><p>{loadError}</p><button type="button" className="btn btn-secondary" onClick={loadPhotos}>Erneut versuchen</button></div>}
      {photos.length > 0 && (
        <div className="photo-grid">
          {photos.map(p => (
            <div key={`${photoRevision}:${p.id}`} className="photo-thumb">
              {resolveFileUrl(p.file_url) ? <img src={resolveFileUrl(p.file_url)} alt={p.caption || 'Foto'} onError={() => setLoadError('Ein Foto konnte nicht geladen werden. Bitte erneut versuchen.')} /> : <span>Kein gültiger Dateiverweis</span>}
              {p.caption && <span className="photo-caption">{p.caption}</span>}
              <button className="photo-delete-btn" onClick={() => handleDelete(p.id)} title="Löschen">
                <TrashIcon size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
