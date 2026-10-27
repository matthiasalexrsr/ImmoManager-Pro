import { useEffect, useRef } from 'react';
import useEntityFormDraft from '../../hooks/useEntityFormDraft';

// Only caller-allowlisted editable values are staged. Business commands remain
// explicit, and private cleanup can never turn an accepted command into a retry.
export default function useEditableDraft({ context, kind, id, fields, values, enabled = true }) {
  const draft = useEntityFormDraft({ context, kind, id, fields: fields.map(key => ({ key })), enabled });
  const snapshot = JSON.stringify(Object.fromEntries(fields.map(key => [key, values[key]])));
  const previous = useRef(snapshot);
  const { enabled: active, loading, ready, recovery, status, stage } = draft;
  useEffect(() => {
    if (!active || loading || !ready || recovery || status === 'changed') return;
    if (snapshot !== previous.current) { previous.current = snapshot; stage(JSON.parse(snapshot)); }
  }, [snapshot, active, loading, ready, recovery, status, stage]);
  return { ...draft, blocked: draft.enabled && (draft.loading || !draft.ready || Boolean(draft.recovery) || draft.status === 'changed'),
    finish: async action => {
      const result = await action();
      previous.current = snapshot;
      await draft.clear({ completed: true }).catch(() => {});
      return result;
    },
    resetSnapshot: next => { previous.current = JSON.stringify(Object.fromEntries(fields.map(key => [key, next[key]]))); },
  };
}
