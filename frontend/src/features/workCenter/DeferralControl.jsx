import { useRef, useState } from 'react';
import FormModal from '../../components/FormModal';
import { workspace } from '../../utils/workspaceClient';
import { useAuth } from '../../contexts/AuthContext';

export default function DeferralControl({ item, onChanged }) {
  const auth = useAuth();
  const [record, setRecord] = useState(undefined);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const command = useRef(null);
  const payload = useRef(null);
  const lock = useRef(false);
  if (!auth?.user?.id) return null;
  const load = async () => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(null);
    try {
      let current;
      try { current = await workspace.get('deferrals', item.work_item_key); }
      catch (failure) { if (failure.statusCode !== 404) throw failure; current = null; }
      setRecord(current); setOpen(true); command.current = workspace.command(); payload.current = null;
    } catch (failure) { setError(failure.message); }
    finally { lock.current = false; setBusy(false); }
  };
  const save = async values => {
    if (values.action !== 'remove' && !values.due_on) throw new Error('Bitte ein Datum für die Wiedervorlage eintragen.');
    if (values.action !== 'remove' && !values.reason?.trim()) throw new Error('Bitte eine kurze Notiz für die Wiedervorlage eintragen.');
    const serialized = JSON.stringify(values);
    if (payload.current !== null && payload.current !== serialized) command.current = workspace.command();
    payload.current = serialized;
    const body = { base_revision: record?.revision ?? 0, idempotency_key: command.current };
    if (values.action === 'remove' && record) await workspace.remove('deferrals', item.work_item_key, body);
    else await workspace.put('deferrals', item.work_item_key, { ...body, due_on: values.due_on, reason: values.reason.trim() });
    onChanged?.();
  };
  return <>
    <button type="button" className="btn btn-sm btn-secondary" onClick={load} disabled={busy}>Später bearbeiten</button>
    {error && <span role="alert" className="work-inline-error">{error}</span>}
    {open && <FormModal title={`Persönliche Wiedervorlage · ${item.title}`} fields={[
      ...(record ? [{ key: 'action', label: 'Wiedervorlage', type: 'select', default: 'keep', options: [
        { value: 'keep', label: 'Datum ändern' }, { value: 'remove', label: 'Wiedervorlage aufheben' },
      ] }] : []),
      { key: 'due_on', label: 'Wieder anzeigen am', type: 'date' },
      { key: 'reason', label: 'Notiz', type: 'textarea', hint: 'Beim Anlegen oder Ändern erforderlich. Die fachliche Fälligkeit des Vorgangs bleibt bestehen.' },
    ]} initial={record} onSave={save} onClose={() => { if (!busy) setOpen(false); }} />}
  </>;
}
