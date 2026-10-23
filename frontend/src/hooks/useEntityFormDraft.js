import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { workspace } from '../utils/workspaceClient';
import useFormDraft from './useFormDraft';

const snapshot = value => JSON.stringify([value.revision, value.dependency_etags]);
const changed = () => Object.assign(new Error('Die Akte wurde zwischenzeitlich geändert. Bitte erneut vergleichen.'), { statusCode: 409 });

// Custom business dialogs retain their own validation and uncertain commands.
// This hook stores editable values only; it never restores approval/preview state.
export default function useEntityFormDraft({ context, kind, id, fields, enabled = true }) {
  const owner = useAuth()?.user?.id;
  const [source, setSource] = useState(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [conflicted, setConflicted] = useState(false);
  const epoch = `${owner}:${context}:${kind}:${id}`;
  const current = source?.epoch === epoch ? source : null;
  const alive = useRef(true);
  const identity = useRef(epoch);
  const comparison = useRef(null);
  useLayoutEffect(() => { identity.current = epoch; }, [epoch]);
  useEffect(() => {
    alive.current = true;
    comparison.current = null;
    setConflicted(false);
    setSource(null); setError('');
    if (!enabled || !owner || !id) return;
    const controller = new AbortController();
    workspace.get('source', `${kind}/${id}`, { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) setSource({ ...value, epoch });
    }).catch(failure => { if (!controller.signal.aborted) setError(failure.message); });
    return () => { alive.current = false; controller.abort(); };
  }, [epoch, enabled, owner, id, kind, attempt]);
  const draft = useFormDraft({ fields, initial: current ? { id, updated_at: current.revision } : null,
    context, anchor: { kind, id }, source: current ? { kind, id, revision: current.revision } : null,
    enabled: enabled && Boolean(current) });
  const compare = useCallback(async load => {
    const before = await workspace.get('source', `${kind}/${id}`);
    if (!alive.current || identity.current !== epoch) throw new DOMException('Die geöffnete Akte wurde gewechselt.', 'AbortError');
    const values = await load?.();
    const after = await workspace.get('source', `${kind}/${id}`);
    if (!alive.current || identity.current !== epoch) throw new DOMException('Die geöffnete Akte wurde gewechselt.', 'AbortError');
    if (snapshot(before) !== snapshot(after)) { comparison.current = null; setConflicted(true); throw changed(); }
    comparison.current = after;
    return values || after.values || { title: after.title };
  }, [kind, id, epoch]);
  const recover = useCallback(async values => {
    const fresh = await workspace.get('source', `${kind}/${id}`);
    if (!alive.current || identity.current !== epoch) throw new DOMException('Die geöffnete Akte wurde gewechselt.', 'AbortError');
    const expected = comparison.current || current;
    if (!expected || snapshot(expected) !== snapshot(fresh)) { comparison.current = null; setConflicted(true); throw changed(); }
    try { await draft.resume(values, fresh.revision, fresh.dependency_etags); }
    catch (failure) { if (failure.statusCode === 409) { comparison.current = null; setConflicted(true); } throw failure; }
    if (!alive.current || identity.current !== epoch) throw new DOMException('Die geöffnete Akte wurde gewechselt.', 'AbortError');
    setSource(old => ({ ...old, ...fresh }));
    comparison.current = null;
    setConflicted(false);
    return fresh;
  }, [draft, kind, id, epoch, current]);
  const clear = async options => {
    await draft.clear(options);
    if (!alive.current || identity.current !== epoch) return;
    comparison.current = null; setConflicted(false);
    if (enabled && owner && id) {
      const fresh = await workspace.get('source', `${kind}/${id}`);
      if (!alive.current || identity.current !== epoch) return;
      draft.resetSource({ kind, id, revision: fresh.revision });
      if (alive.current) setSource(old => ({ ...old, ...fresh }));
    }
  };
  return { ...draft, enabled: enabled && Boolean(owner), loading: enabled && owner && !current && !error,
    status: conflicted ? 'changed' : draft.status,
    error: error || draft.error, recover, compare, clear, retry: error ? () => setAttempt(value => value + 1) : draft.retry,
    sessionKey: epoch, isCurrent: token => alive.current && identity.current === token };
}
