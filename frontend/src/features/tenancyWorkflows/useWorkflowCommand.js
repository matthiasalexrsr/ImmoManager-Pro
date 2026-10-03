import { useCallback, useEffect, useRef, useState } from 'react';
import { isConflictOutcome, isUnknownOutcome } from './tenancyWorkflowModel';

const idleState = Object.freeze({ phase: 'idle', error: null, label: null });

function jsonClone(value) {
  if (typeof structuredClone === 'function') return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

function freezeTree(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
  Object.values(value).forEach(freezeTree);
  return Object.freeze(value);
}

export default function useWorkflowCommand(principalKey = '') {
  const [state, setState] = useState(idleState);
  const pending = useRef(null);
  const active = useRef(null);
  const mounted = useRef(true);
  const busy = state.phase === 'sending';

  useEffect(() => () => {
    mounted.current = false;
    active.current?.abort();
  }, []);

  useEffect(() => {
    active.current?.abort();
    active.current = null;
    pending.current = null;
    setState(idleState);
  }, [principalKey]);

  const deliver = useCallback(async entry => {
    if (active.current) return undefined;
    const controller = new AbortController();
    active.current = controller;
    setState({ phase: 'sending', error: null, label: entry.label });
    try {
      const result = await entry.send(entry.payload, { signal: controller.signal });
      if (controller.signal.aborted || !mounted.current) return undefined;
      pending.current = null;
      setState({ phase: 'success', error: null, label: entry.label });
      await entry.onSuccess?.(result);
      return result;
    } catch (error) {
      if (controller.signal.aborted || error?.name === 'AbortError' || !mounted.current) return undefined;
      if (isUnknownOutcome(error)) {
        pending.current = entry;
        setState({ phase: 'unknown', error, label: entry.label });
      } else if (isConflictOutcome(error)) {
        pending.current = entry;
        setState({ phase: 'conflict', error, label: entry.label });
      } else {
        pending.current = null;
        setState({ phase: 'error', error, label: entry.label });
      }
      return undefined;
    } finally {
      if (active.current === controller) active.current = null;
    }
  }, []);

  const execute = useCallback(({ label, payload, send, onSuccess }) => {
    if (active.current || typeof send !== 'function') return Promise.resolve(undefined);
    const entry = {
      label,
      payload: freezeTree(jsonClone(payload)),
      send,
      onSuccess,
    };
    pending.current = entry;
    return deliver(entry);
  }, [deliver]);

  const retryExact = useCallback(() => {
    if (state.phase !== 'unknown' || !pending.current || active.current) return Promise.resolve(undefined);
    return deliver(pending.current);
  }, [deliver, state.phase]);

  const reset = useCallback(() => {
    if (active.current) return;
    pending.current = null;
    setState(idleState);
  }, []);

  const abort = useCallback(() => {
    active.current?.abort();
    active.current = null;
    pending.current = null;
    setState(idleState);
  }, []);

  return {
    state,
    busy,
    execute,
    retryExact,
    reset,
    abort,
    hasExactRetry: state.phase === 'unknown' && Boolean(pending.current),
  };
}
