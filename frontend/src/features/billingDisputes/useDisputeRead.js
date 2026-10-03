import { useLayoutEffect } from 'react';
import { usePrivateRead } from '../unitInventory/read';
import { denied } from './disputeModel';

/** Validate domain replies; hide the whole private workspace on scope denial. */
export default function useDisputeRead(path, principal, generation, parse, onDenied) {
  const state = usePrivateRead(path, principal, generation);
  let data = null; let error = state.error;
  if (!state.loading && !error) { try { data = parse(state.data); } catch (failure) { error = failure; } }
  useLayoutEffect(() => { if (denied(error)) onDenied?.(); }, [error, onDenied]);
  return { data, error, loading: state.loading };
}
