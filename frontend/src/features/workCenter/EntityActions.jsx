import { useEffect, useRef, useState } from 'react';
import { Star, MessageSquare } from 'lucide-react';
import { createPortal } from 'react-dom';
import { useAuth } from '../../contexts/AuthContext';
import { useDataStore } from '../../contexts/DataStoreContext';
import { workspace } from '../../utils/workspaceClient';
import { api } from '../../api';
import { mayWrite } from '../../utils/permissions';
import ConversationDialog from './ConversationDialog';
import { notifyEntityShelf } from './entityShelfEvents';
import './workCenter.css';


export default function EntityActions(props) {
  const auth = useAuth();
  if (!auth?.user?.id || !props.entityId) return null;
  return <Controls key={`${auth.user.id}:${props.entityType}:${props.entityId}`} {...props} auth={auth} />;
}

function Controls({ auth, entityType, entityId, entityRevision, title, onChanged, onDialogChange }) {
  const store = useDataStore();
  const [favorite, setFavorite] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [conversation, setConversation] = useState(null);
  const lock = useRef(false);
  const active = useRef(false);
  const command = useRef(null);
  const resource = `favorites/${entityType}`;
  useEffect(() => { onDialogChange?.(Boolean(conversation)); return () => onDialogChange?.(false); }, [conversation, onDialogChange]);
  useEffect(() => {
    active.current = true;
    const request = new AbortController();
    // null: not marked (a 404 from an older server means the same).
    workspace.get(resource, entityId, { signal: request.signal }, { missing_ok: true }).then(result => {
      if (!request.signal.aborted) { setFavorite(result || null); setLoaded(true); }
    }).catch(failure => {
      if (request.signal.aborted) return;
      if (failure.statusCode === 404) { setFavorite(null); setLoaded(true); }
      else setError(failure.message);
    });
    workspace.touch(entityType, entityId).then(notifyEntityShelf).catch(failure => { if (!request.signal.aborted) setError(failure.message); });
    return () => { active.current = false; request.abort(); };
  }, [resource, entityId, entityType]);
  const toggleFavorite = async () => {
    if (lock.current || !loaded) return;
    lock.current = true; setBusy(true); setError(null);
    command.current ||= workspace.command();
    const body = { base_revision: favorite?.revision ?? 0, idempotency_key: command.current };
    try {
      if (favorite) await workspace.remove(resource, entityId, body);
      else {
        const result = await workspace.put(resource, entityId, body);
        if (active.current) setFavorite(result);
      }
      if (active.current && favorite) setFavorite(null);
      command.current = null;
      notifyEntityShelf();
    } catch (failure) {
      if (active.current) setError(failure.message);
      // A confirmed conflict needs fresh state; keep the user's choice explicit.
      if (failure.statusCode === 409) {
        command.current = null;
        try { const current = await workspace.get(resource, entityId); if (active.current) setFavorite(current); }
        catch (readError) { if (active.current && readError.statusCode === 404) setFavorite(null); }
      }
    } finally { lock.current = false; if (active.current) setBusy(false); }
  };
  const openConversation = async () => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(null);
    try {
      const context = await api.get(`/work-center/timeline?entity_type=${encodeURIComponent(entityType)}&entity_id=${encodeURIComponent(entityId)}&limit=1`);
      if (!context.can_note) throw new Error('Für diesen Vorgang können Sie keine Notizen erfassen.');
      const revision = context.entity_revision || entityRevision;
      if (!revision) throw new Error('Der aktuelle Stand des Vorgangs ist nicht verfügbar. Bitte die Akte neu laden.');
      if (active.current) setConversation(revision);
    } catch (failure) { if (active.current) setError(failure.message); }
    finally { lock.current = false; if (active.current) setBusy(false); }
  };
  const canNote = mayWrite(auth.write, '/tasks');
  return <div className="entity-actions">
    <button type="button" className="btn btn-sm btn-secondary" onClick={toggleFavorite} disabled={busy || !loaded} aria-pressed={Boolean(favorite)}
      aria-label={favorite ? `Favorit entfernen: ${title}` : `Als Favorit merken: ${title}`}><Star size={14} aria-hidden="true" fill={favorite ? 'currentColor' : 'none'} />{favorite ? 'Gemerkt' : 'Merken'}</button>
    {canNote && <button type="button" className="btn btn-sm btn-secondary" onClick={openConversation} disabled={busy}><MessageSquare size={14} aria-hidden="true" />Gespräch / Wiedervorlage</button>}
    {error && <span role="alert" className="work-inline-error">{error}</span>}
    {conversation && createPortal(<ConversationDialog entityType={entityType} entityId={entityId} entityRevision={conversation} title={title}
      onClose={() => setConversation(null)} onSaved={() => { store?.invalidateRelated('tasks'); onChanged?.(); }} />, document.body)}
  </div>;
}
