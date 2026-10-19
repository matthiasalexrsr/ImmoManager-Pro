import { useEffect, useRef, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { workspace } from '../utils/workspaceClient';

export default function useWorkspaceViewState(context, state, apply) {
  const owner = useAuth()?.user?.id;
  const row = useRef(null);
  const ready = useRef(false);
  const latest = useRef(state);
  const initial = useRef(JSON.stringify(state));
  const pending = useRef(null);
  const running = useRef(false);
  const applyRef = useRef(apply);
  const identity = `${owner}:${context}`;
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;
  const epoch = useRef(0);
  const [loaded, setLoaded] = useState(0);
  applyRef.current = apply;
  latest.current = state;
  useEffect(() => {
    const generation = ++epoch.current;
    row.current = null; ready.current = false; pending.current = null;
    running.current = false;
    initial.current = JSON.stringify(latest.current);
    if (!owner || !context) return;
    let live = true;
    // null: nothing saved for this list yet (a 404 from an older server means the same).
    workspace.get('view-state', context, undefined, { missing_ok: true }).then(saved => {
      if (!live || generation !== epoch.current || currentIdentity.current !== identity) return;
      row.current = saved || null; ready.current = true;
      if (saved && initial.current === JSON.stringify(latest.current)) applyRef.current(saved.state);
      setLoaded(value => value + 1);
    }).catch(failure => {
      if (live && generation === epoch.current && currentIdentity.current === identity && failure.statusCode === 404) {
        ready.current = true; setLoaded(value => value + 1);
      }
    });
    return () => { live = false; epoch.current += 1; };
  }, [owner, context, identity]);
  useEffect(() => {
    if (!owner || !context) return;
    const generation = epoch.current;
    const current = () => generation === epoch.current && currentIdentity.current === identity;
    const timer = setTimeout(async () => {
      if (!current() || !ready.current || running.current) return;
      running.current = true;
      try {
        while (current()) {
          pending.current ||= { base_revision: row.current?.revision || 0, idempotency_key: workspace.command(), state: latest.current };
          const command = pending.current;
          const saved = await workspace.put('view-state', context, command);
          if (!current()) return;
          row.current = saved; pending.current = null;
          if (JSON.stringify(command.state) === JSON.stringify(latest.current)) break;
        }
      } catch (failure) {
        if (!current()) return;
        // A changed view in another tab is intentionally not overwritten.
        if (failure.statusCode === 409) { ready.current = false; pending.current = null; }
      } finally { if (current()) running.current = false; }
    }, 900);
    return () => clearTimeout(timer);
  }, [owner, context, state, identity, loaded]);
}
