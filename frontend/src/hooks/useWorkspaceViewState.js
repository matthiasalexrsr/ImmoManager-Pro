import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { workspace } from '../utils/workspaceClient';

export default function useWorkspaceViewState(context, state, apply) {
  const owner = useAuth()?.user?.id;
  const row = useRef(null);
  const ready = useRef(false);
  const latest = useRef(state);
  const initial = useRef(JSON.stringify(state));
  const pending = useRef(null);
  const restoring = useRef(null);
  const running = useRef(false);
  const applyRef = useRef(apply);
  const identity = `${owner}:${context}`;
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;
  const epoch = useRef(0);
  const [loaded, setLoaded] = useState(0);
  const [reloadId, setReloadId] = useState(0);
  const reloadRequested = useRef(null);
  const [failure, setFailure] = useState(null);
  applyRef.current = apply;
  latest.current = state;
  useLayoutEffect(() => {
    // A committed render acknowledges restoration even if the person later
    // deliberately changes back to the exact value they had before loading.
    if (restoring.current !== null && JSON.stringify(state) !== restoring.current) restoring.current = null;
  }, [state]);
  useEffect(() => {
    const generation = ++epoch.current;
    const explicitReload = reloadRequested.current === identity;
    reloadRequested.current = null;
    row.current = null; ready.current = false; pending.current = null; restoring.current = null;
    setFailure(null);
    running.current = false;
    initial.current = JSON.stringify(latest.current);
    if (!owner || !context) return;
    let live = true;
    // null: nothing saved for this list yet (a 404 from an older server means the same).
    workspace.get('view-state', context, undefined, { missing_ok: true }).then(saved => {
      if (!live || generation !== epoch.current || currentIdentity.current !== identity) return;
      row.current = saved || null; ready.current = true;
      if (saved && initial.current === JSON.stringify(latest.current)) {
        const before = JSON.stringify(latest.current);
        // Applying React state can be deferred. Until it is committed, the old
        // local state must not be written using the newly loaded revision.
        if (before !== JSON.stringify(saved.state)) restoring.current = before;
        if (applyRef.current(saved.state, { reload: explicitReload }) === false) restoring.current = null;
      }
      setLoaded(value => value + 1);
    }).catch(failure => {
      if (live && generation === epoch.current && currentIdentity.current === identity && failure.statusCode === 404) {
        ready.current = true; setLoaded(value => value + 1);
      } else if (live && generation === epoch.current && currentIdentity.current === identity) {
        setFailure({ message: 'Die gespeicherte Tabellenansicht konnte nicht geladen werden. ' + failure.message, conflict: false });
      }
    });
    return () => { live = false; epoch.current += 1; };
  }, [owner, context, identity, reloadId]);
  useEffect(() => {
    if (!owner || !context) return;
    const generation = epoch.current;
    const current = () => generation === epoch.current && currentIdentity.current === identity;
    const timer = setTimeout(async () => {
      if (!current() || !ready.current || running.current) return;
      if (restoring.current !== null) {
        if (JSON.stringify(latest.current) === restoring.current) return;
        restoring.current = null;
      }
      running.current = true;
      try {
        while (current()) {
          if (!pending.current && row.current && JSON.stringify(row.current.state) === JSON.stringify(latest.current)) break;
          pending.current ||= { base_revision: row.current?.revision || 0, idempotency_key: workspace.command(), state: latest.current };
          const command = pending.current;
          const saved = await workspace.put('view-state', context, command);
          if (!current()) return;
          row.current = saved; pending.current = null;
          setFailure(null);
          if (JSON.stringify(command.state) === JSON.stringify(latest.current)) break;
        }
      } catch (failure) {
        if (!current()) return;
        // A changed view in another tab is intentionally not overwritten.
        if (failure.statusCode === 409) {
          ready.current = false; pending.current = null;
          try {
            const saved = await workspace.get('view-state', context, undefined, { missing_ok: true });
            if (!current()) return;
            if (saved && JSON.stringify(saved.state) === JSON.stringify(latest.current)) {
              row.current = saved; ready.current = true; setFailure(null);
              return;
            }
          } catch { /* Keep the conflict visible until the server state can be loaded. */ }
          if (!current()) return;
          setFailure({ message: 'Die Tabellenansicht wurde in einem anderen Fenster geändert. Ihre aktuellen Einstellungen sind noch nicht gespeichert. Laden Sie die Serveransicht, um damit weiterzuarbeiten.', conflict: true });
        } else {
          setFailure({ message: 'Ihre Tabellenansicht konnte nicht gespeichert werden. ' + failure.message, conflict: false });
        }
      } finally { if (current()) running.current = false; }
    }, 900);
    return () => clearTimeout(timer);
  }, [owner, context, state, identity, loaded]);
  const reload = () => {
    reloadRequested.current = identity;
    setReloadId(value => value + 1);
  };
  return {
    error: failure?.message || '', conflict: failure?.conflict || false,
    reload,
    retry: () => { if (ready.current) setLoaded(value => value + 1); else reload(); },
  };
}
