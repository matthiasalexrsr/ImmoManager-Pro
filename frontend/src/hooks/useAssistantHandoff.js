import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { api } from '../api';

// The URL identifies the private proposal; data and revision are freshly loaded.
// Reloading a final form never falls back to an unbound ordinary POST.
export default function useAssistantHandoff(kind, onReady) {
  const [params, setParams] = useSearchParams();
  const identifier = params.get('assistant_proposal');
  const owner = useAuth()?.user?.id;
  const ready = useRef(onReady);
  useLayoutEffect(() => { ready.current = onReady; }, [onReady]);
  const active = useRef(null);
  const pending = useRef(null);
  const [state, setState] = useState({ loading: false, error: '', proposal: null });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const identity = `${owner || ''}:${identifier || ''}`;
    active.current = identity; pending.current = null;
    setState({ loading: Boolean(identifier), error: '', proposal: null });
    if (identifier) api.get(`/assistant/proposals/${encodeURIComponent(identifier)}`, { signal: controller.signal }).then(proposal => {
      if (controller.signal.aborted || active.current !== identity) return;
      if (proposal.payload?.kind !== kind || !['applied', 'saved'].includes(proposal.state)) throw new Error('Dieser geprüfte Entwurf passt nicht zum Fachformular.');
      setState({ loading: false, error: '', proposal });
      if (proposal.state !== 'saved') ready.current(proposal.handoff?.values || proposal.payload.values || {});
    }).catch(error => { if (!controller.signal.aborted && active.current === identity) setState({ loading: false, error: error.message, proposal: null }); });
    return () => { controller.abort(); if (active.current === identity) active.current = null; };
  }, [owner, identifier, kind, attempt]);
  const clear = () => {
    active.current = null; pending.current = null;
    setParams(current => { const next = new URLSearchParams(current); next.delete('assistant_proposal'); return next; }, { replace: true });
    setState({ loading: false, error: '', proposal: null });
  };
  const save = async values => {
    if (!identifier) return null;
    const identity = `${owner || ''}:${identifier}`;
    if (active.current !== identity || !state.proposal || state.loading) throw new Error('Der geprüfte Entwurf muss vor dem Speichern vollständig geladen sein.');
    const normalized = Object.fromEntries(Object.entries(values).filter(([, value]) => value !== '' && value != null));
    const signature = JSON.stringify(normalized);
    if (!pending.current || pending.current.signature !== signature) pending.current = { signature,
      body: { expected_revision: state.proposal.revision, idempotency_key: crypto.randomUUID(), values: normalized } };
    const result = await api.post(`/assistant/proposals/${encodeURIComponent(identifier)}/save`, pending.current.body);
    if (active.current !== identity) throw new Error('Das Anwendungskonto oder der Entwurf wurde während des Speicherns gewechselt.');
    setState({ loading: false, error: '', proposal: result.proposal });
    pending.current = null;
    return result;
  };
  return { ...state, identifier, clear, save, returnHref: state.proposal?.conversation_id
    ? `/assistant?conversation=${encodeURIComponent(state.proposal.conversation_id)}` : '/assistant',
  retry: () => setAttempt(value => value + 1) };
}
