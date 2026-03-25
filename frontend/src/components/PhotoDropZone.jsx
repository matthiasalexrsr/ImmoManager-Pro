import { useState, useRef, useCallback, useEffect } from 'react';
import { api } from '../api';
import { PlusIcon, TrashIcon } from './Icons';
import { useConfirm } from './ConfirmDialog';

const BASE = (import.meta.env.VITE_API_URL || '/api/v1');

export default function PhotoDropZone({ entityType, entityId }) {
  const confirm = useConfirm();
  const [photos, setPhotos] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const fileRef = useRef(null);

  const loadPhotos = useCallback(() => {
    if (!entityId) return;
    api.get(`/photos?entity_type=${entityType}&entity_id=${entityId}`)
      .then(setPhotos)
      .catch(err => console.warn('[PhotoDropZone] load:', err.message));
  }, [entityType, entityId]);

  useEffect(() => { loadPhotos(); }, [loadPhotos]);

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
      setUploading(false);
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
      {photos.length > 0 && (
        <div className="photo-grid">
          {photos.map(p => (
            <div key={p.id} className="photo-thumb">
              <img src={p.file_url} alt={p.caption || 'Foto'} />
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
