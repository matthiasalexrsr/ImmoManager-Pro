import { useEffect, useRef, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { workspace } from '../utils/workspaceClient';
import './workspace.css';

export default function NamedViews({ context, config, onApply, anchor }) {
  const auth = useAuth();
  const [items, setItems] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [selected, setSelected] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const lock = useRef(false);
  const command = useRef(null);
  const owner = auth?.user?.id;
  const anchorKey = anchor ? `${anchor.kind}:${anchor.id}` : '';
  const identity = `${owner}:${context}:${anchorKey}`;
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;
  const loadedIdentity = useRef(null);
  const epoch = useRef(0);
  useEffect(() => {
    epoch.current += 1; loadedIdentity.current = identity;
    lock.current = false; setBusy(false); setName('');
    setItems([]); setSelected(''); setCursor(null); setError(''); command.current = null;
    if (!owner || !context) return;
    let live = true;
    workspace.list('views', { context }).then(page => {
      if (live) { setItems(page.items || []); setCursor(page.next_cursor); }
    }).catch(failure => { if (live) setError(failure.message); });
    return () => { live = false; epoch.current += 1; };
  }, [owner, context, anchorKey, identity]);
  if (!owner || !context) return null;
  const visibleItems = loadedIdentity.current === identity ? items : [];
  const current = visibleItems.find(item => item.id === selected);
  const run = async action => {
    const generation = epoch.current;
    const current = () => generation === epoch.current && currentIdentity.current === identity;
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { await action(current); }
    catch (failure) { if (current()) setError(failure.statusCode === 409 ? 'Die Ansicht wurde inzwischen geändert. Bitte laden Sie die Ansichten neu, bevor Sie sie ersetzen.' : failure.message); }
    finally { if (current()) { lock.current = false; setBusy(false); } }
  };
  const save = replace => run(async live => {
    if (!name.trim() && !replace) { setError('Bitte einen Namen eingeben.'); return; }
    const body = { context, anchor: anchor || null, name: replace ? current.name : name.trim(),
      config, base_revision: replace ? current.revision : 0 };
    const signature = JSON.stringify(body);
    if (command.current?.signature !== signature) command.current = {
      signature, id: replace ? current.id : workspace.command(), body: { ...body, idempotency_key: workspace.command() },
    };
    const saved = await workspace.put('views', command.current.id, command.current.body);
    if (!live()) return;
    command.current = null;
    setItems(rows => [...rows.filter(item => item.id !== saved.id), saved]); setSelected(saved.id); setName('');
  });
  return <div>
    <div className="named-views" aria-label="Gespeicherte Ansichten">
      <label htmlFor={`named-view-${context}`}>Ansicht</label>
      <select id={`named-view-${context}`} value={selected} disabled={busy} onChange={event => {
        const id = event.target.value; setSelected(id);
        const view = visibleItems.find(item => item.id === id); if (view) onApply(view.config);
      }}><option value="">Aktuelle Auswahl</option>{visibleItems.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
      {cursor && <button type="button" className="btn btn-sm btn-secondary" disabled={busy} onClick={() => run(async live => {
        const page = await workspace.list('views', { context, cursor });
        if (!live()) return;
        setItems(rows => [...rows, ...(page.items || []).filter(item => !rows.some(row => row.id === item.id))]); setCursor(page.next_cursor);
      })}>Weitere Ansichten</button>}
      <input aria-label="Name der neuen Ansicht" placeholder="Neue Ansicht benennen" value={name} disabled={busy} onChange={event => setName(event.target.value)} />
      <button type="button" className="btn btn-sm btn-secondary" disabled={busy || !name.trim()} onClick={() => save(false)}>Ansicht speichern</button>
      {current && <>
        <button type="button" className="btn btn-sm btn-secondary" disabled={busy} onClick={() => save(true)}>Ansicht aktualisieren</button>
        <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={() => run(async live => {
          const body = { base_revision: current.revision, idempotency_key: workspace.command() };
          await workspace.remove('views', current.id, body);
          if (!live()) return;
          setItems(rows => rows.filter(item => item.id !== current.id)); setSelected('');
        })}>Ansicht löschen</button>
      </>}
    </div>
    {error && loadedIdentity.current === identity && <p role="alert" className="error-message">{error}<button type="button" className="btn btn-sm btn-ghost" onClick={() => run(async live => {
      const page = await workspace.list('views', { context }); if (!live()) return; setItems(page.items || []); setCursor(page.next_cursor); setSelected(''); command.current = null;
    })}>Ansichten neu laden</button></p>}
  </div>;
}
