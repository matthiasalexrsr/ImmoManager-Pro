import { useCallback, useEffect, useRef, useState } from 'react';
import {
  isConflictOutcome,
  isPrivateForgetOutcome,
  isUnknownOutcome,
} from './housingConfirmationModel';

const idle = binding => Object.freeze({ binding, phase: 'idle', error: null, label: null });

function jsonClone(value) {
  if (typeof structuredClone === 'function') return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

function freezeTree(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
  Object.values(value).forEach(freezeTree);
  return Object.freeze(value);
}

export default function useHousingConfirmationCommand(bindingKey = '', onForget) {
  const [stored, setStored] = useState(() => idle(bindingKey));
  const pending = useRef(null);
  const active = useRef(null);
  const mounted = useRef(true);
  const state = stored.binding === bindingKey ? stored : idle(bindingKey);

  useEffect(() => () => {
    mounted.current = false;
    active.current?.abort();
  }, []);

  useEffect(() => {
    active.current?.abort();
    active.current = null;
    pending.current = null;
    setStored(idle(bindingKey));
  }, [bindingKey]);

  const deliver = useCallback(async entry => {
    if (active.current || entry.binding !== bindingKey) return undefined;
    const controller = new AbortController();
    active.current = controller;
    setStored({ binding: bindingKey, phase: 'sending', error: null, label: entry.label });
    try {
      const result = await entry.send(entry.payload, { signal: controller.signal });
      if (controller.signal.aborted || !mounted.current || entry.binding !== bindingKey) return undefined;
      pending.current = null;
      setStored({ binding: bindingKey, phase: 'success', error: null, label: entry.label });
      await entry.onSuccess?.(result);
      return result;
    } catch (error) {
      if (controller.signal.aborted || error?.name === 'AbortError' || !mounted.current) return undefined;
      if (isPrivateForgetOutcome(error)) {
        pending.current = null;
        setStored({ binding: bindingKey, phase: 'private_error', error, label: entry.label });
        onForget?.(error);
      } else if (isUnknownOutcome(error)) {
        pending.current = entry;
        setStored({ binding: bindingKey, phase: 'unknown', error, label: entry.label });
      } else if (isConflictOutcome(error)) {
        pending.current = null;
        setStored({ binding: bindingKey, phase: 'conflict', error, label: entry.label });
      } else {
        pending.current = null;
        setStored({ binding: bindingKey, phase: 'error', error, label: entry.label });
      }
      return undefined;
    } finally {
      if (active.current === controller) active.current = null;
    }
  }, [bindingKey, onForget]);

  const execute = useCallback(({ label, payload, send, onSuccess }) => {
    if (active.current || typeof send !== 'function' || !bindingKey) return Promise.resolve(undefined);
    const entry = {
      binding: bindingKey,
      label,
      payload: freezeTree(jsonClone(payload)),
      send,
      onSuccess,
    };
    pending.current = entry;
    return deliver(entry);
  }, [bindingKey, deliver]);

  const retryExact = useCallback(() => {
    if (state.phase !== 'unknown' || !pending.current || active.current) return Promise.resolve(undefined);
    return deliver(pending.current);
  }, [deliver, state.phase]);

  const reset = useCallback(() => {
    if (active.current) return;
    pending.current = null;
    setStored(idle(bindingKey));
  }, [bindingKey]);

  const abort = useCallback(() => {
    active.current?.abort();
    active.current = null;
    pending.current = null;
    setStored(idle(bindingKey));
  }, [bindingKey]);

  return {
    state,
    busy: state.phase === 'sending',
    execute,
    retryExact,
    reset,
    abort,
    hasExactRetry: state.phase === 'unknown' && Boolean(pending.current),
  };
}
