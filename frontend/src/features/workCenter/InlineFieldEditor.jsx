import { useRef, useState } from 'react';
import { Pencil } from 'lucide-react';
import { api } from '../../api';
import { workspace } from '../../utils/workspaceClient';

// Restricted to the task fields the business API can safely reverse. No local
// optimistic overwrite: both success and undo use the server-returned record.
export default function InlineFieldEditor({ record, field, label, type = 'text', options, children, canEdit, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const lock = useRef(false);
  const openedRevision = useRef(null);
  const command = useRef(null);
  const payload = useRef(null);
  const start = () => {
    openedRevision.current = record.updated_at;
    command.current = workspace.command(); payload.current = null;
    setValue(record[field] ?? ''); setError(null); setEditing(true);
  };
  const save = async event => {
    event.preventDefault(); event.stopPropagation();
    if (lock.current) return;
    const changes = { [field]: value || null };
    const serialized = JSON.stringify(changes);
    if (payload.current !== null && payload.current !== serialized) command.current = workspace.command();
    payload.current = serialized;
    lock.current = true; setBusy(true); setError(null);
    try {
      const result = await api.post('/work-center/quick-edits', { entity_type: 'task', entity_id: record.id,
        base_revision: openedRevision.current, changes, idempotency_key: command.current });
      onSaved?.(result); setEditing(false);
    } catch (failure) { setError(failure.message); }
    finally { lock.current = false; setBusy(false); }
  };
  if (!canEdit) return children ?? record[field] ?? '—';
  return <div className="work-inline" onClick={event => event.stopPropagation()}>
    {editing ? <form onSubmit={save} onKeyDown={event => { if (event.key === 'Escape' && !busy) { event.preventDefault(); setEditing(false); } }}>
      {options ? <select aria-label={label} value={value} onChange={event => setValue(event.target.value)} disabled={busy} autoFocus>
        {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select> : <input aria-label={label} type={type} value={value} onChange={event => setValue(event.target.value)} disabled={busy} autoFocus />}
      <button type="submit" className="btn btn-sm btn-primary" disabled={busy}>Speichern</button>
      <button type="button" className="btn btn-sm btn-ghost" onClick={() => setEditing(false)} disabled={busy}>Abbrechen</button>
      {error && <span className="work-inline-error" role="alert">{error} Eingabe bleibt erhalten.</span>}
    </form> : <><span>{children ?? record[field] ?? '—'}</span><button type="button" className="btn btn-sm btn-ghost" aria-label={`${label} bearbeiten: ${record.title || record.id}`} title={`${label} bearbeiten`} onClick={start}><Pencil size={13} aria-hidden="true" /></button></>}
  </div>;
}
