import { useRef, useState } from 'react';
import { api } from '../../api';
import { workspace } from '../../utils/workspaceClient';

export default function UndoNotice({ change, onUndone, onDismiss }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const lock = useRef(false);
  const command = useRef(workspace.command());
  const undo = async () => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(null);
    try {
      const result = await api.post(`/work-center/quick-edits/${encodeURIComponent(change.undo_id)}/undo`, {
        base_revision: change.revision, idempotency_key: command.current,
      });
      onUndone?.(result);
    } catch (failure) { setError(failure.message); }
    finally { lock.current = false; setBusy(false); }
  };
  return <aside className="work-undo" aria-label="Letzte Änderung">
    <span>Änderung gespeichert{change.record?.title ? `: ${change.record.title}` : ''}.</span>
    <button type="button" className="btn btn-sm btn-secondary" onClick={undo} disabled={busy}>{busy ? 'Wird zurückgenommen…' : 'Rückgängig'}</button>
    <button type="button" className="btn btn-sm btn-ghost" onClick={onDismiss} disabled={busy}>Schließen</button>
    {error && <span role="alert" className="work-inline-error">{error} Ihre Änderung bleibt bestehen.</span>}
  </aside>;
}
