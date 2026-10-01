import { useState, useRef, useCallback, useEffect } from 'react';
import { api } from '../api';
import { PlusIcon, TrashIcon } from './Icons';
import { useConfirm } from './ConfirmDialog';
import useProtectedFile from '../hooks/useProtectedFile';

function PhotoThumbnail({ photo, onDelete }) {
  const file = useProtectedFile(photo.file_url);
  return <div className="photo-thumb">
    {file.loading && <span role="status">Foto wird geladen...</span>}
    {file.error && <div role="alert"><p>{file.error}</p><button onClick={file.retry}>Erneut versuchen</button></div>}
    {file.url && (file.kind === 'image'
      ? <img src={file.url} alt={photo.caption || 'Foto'} />
      : <p role="alert">Keine Bildvorschau verfügbar.</p>)}
    {photo.caption && <span className="photo-caption">{photo.caption}</span>}
    <button className="photo-delete-btn" onClick={() => onDelete(photo.id)} title="Löschen" aria-label="Foto löschen"><TrashIcon size={14} /></button>
  </div>;
}

export default function PhotoDropZone({ entityType, entityId }) {
  const confirm = useConfirm();
  const [photos, setPhotos] = useState({ entity: null, items: [] });
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState(null);
  const fileRef = useRef(null);
  const requestRef = useRef(null);
  const entity = `${entityType}:${entityId}`;

  const loadPhotos = useCallback(async (signal) => {
    if (!entityId) return;
    try {
      const items = await api.get(`/photos?entity_type=${encodeURIComponent(entityType)}&entity_id=${encodeURIComponent(entityId)}`, { signal });
      if (!signal.aborted) { setPhotos({ entity: `${entityType}:${entityId}`, items }); setError(null); }
    } catch (err) { if (!signal.aborted) setError(err.message); }
  }, [entityType, entityId]);

  useEffect(() => {
    const controller = new AbortController();
    requestRef.current = controller;
    setPhotos({ entity, items: [] }); setUploading(false); setError(null);
    loadPhotos(controller.signal);
    return () => controller.abort();
  }, [entity, loadPhotos]);

  const uploadFiles = useCallback(async (files) => {
    const controller = requestRef.current;
    if (!controller || controller.signal.aborted || uploading) return;
    setUploading(true); setError(null);
    try {
      for (const file of files) {
        if (!file.type.startsWith('image/')) throw new Error('Bitte wählen Sie eine Bilddatei.');
        const formData = new FormData(); formData.append('file', file);
        await api.postForm(`/photos/upload?entity_type=${encodeURIComponent(entityType)}&entity_id=${encodeURIComponent(entityId)}`, formData, { signal: controller.signal });
      }
      await loadPhotos(controller.signal);
    } catch (err) { if (!controller.signal.aborted) setError(err.message); }
    finally { if (!controller.signal.aborted) { setUploading(false); if (fileRef.current) fileRef.current.value = ''; } }
  }, [entityType, entityId, loadPhotos, uploading]);

  const handleDelete = async photoId => {
    const controller = requestRef.current;
    if (!await confirm('Foto wirklich löschen?') || controller.signal.aborted) return;
    try { await api.del(`/photos/${photoId}`, { signal: controller.signal }); await loadPhotos(controller.signal); }
    catch (err) { if (!controller.signal.aborted) setError(err.message); }
  };

  if (!entityId) return null;
  const items = photos.entity === entity ? photos.items : [];
  return <div className="photo-drop-zone-container">
    {error && <div role="alert"><p>{error}</p><button className="btn btn-secondary" onClick={() => loadPhotos(requestRef.current.signal)}>Fotos erneut laden</button></div>}
    <div className={`photo-drop-zone ${dragActive ? 'drag-active' : ''}`}
      onDragOver={event => { event.preventDefault(); setDragActive(true); }} onDragLeave={() => setDragActive(false)}
      onDrop={event => { event.preventDefault(); setDragActive(false); uploadFiles(Array.from(event.dataTransfer?.files || [])); }}
      onClick={() => { if (!uploading) fileRef.current?.click(); }}>
      <input ref={fileRef} aria-label="Fotos hochladen" type="file" accept="image/*" multiple disabled={uploading} style={{ display: 'none' }} onChange={event => uploadFiles(Array.from(event.target.files || []))} />
      <PlusIcon size={24} /><span>{uploading ? 'Wird hochgeladen...' : 'Fotos hierher ziehen oder klicken (automatisch speichern)'}</span>
    </div>
    {items.length > 0 && <div className="photo-grid">{items.map(photo => <PhotoThumbnail key={photo.id} photo={photo} onDelete={handleDelete} />)}</div>}
  </div>;
}
