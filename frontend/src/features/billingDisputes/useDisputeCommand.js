import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import useFormDraft from '../../hooks/useFormDraft';
import useWriteAccess from '../../hooks/useWriteAccess';
import { copy, denied, DISPUTES, readPreview, readReceipt, restoreEnvelope } from './disputeModel';

const fields = ['period_id', 'case_id', 'command_json', 'review_json'].map(key => ({ key, type: 'text' }));
const ready = new Set(['ready', 'saved', 'restored', 'saving']);

/** Exact domain commands live only in the common private encrypted draft core. */
export default function useDisputeCommand({ periodId, caseId = '', initialCommand, onDenied, onSaved, onClose }) {
  const original = useRef({ period_id: periodId, case_id: caseId, command_json: JSON.stringify(initialCommand), review_json: '' });
  const editRevision = useRef(null); const [values, setValues] = useState(original.current);
  const [phase, setPhase] = useState('editing'); const [error, setError] = useState(null); const [receipt, setReceipt] = useState(null);
  const active = useRef(false); const request = useRef(null); const alive = useRef(true); const notified = useRef(false);
  const { canWrite, requireWrite } = useWriteAccess('/billing', onDenied);
  useEffect(() => { alive.current = true; return () => { alive.current = false; request.current?.abort(); }; }, []);
  const draft = useFormDraft({ config: { collection: 'billing/disputes', formKey: `${caseId ? 'event' : 'open'}:${caseId || periodId}` },
    fields, values, original, editRevision, onRestore: saved => {
      const restored = restoreEnvelope(saved.values, periodId, caseId);
      if (saved.submission_pending && !restored.review) throw new Error('invalidDisputeResponse');
      original.current = saved.original_values; setValues(copy(saved.values)); setError(null);
      setPhase(saved.submission_pending ? 'unknown' : restored.review ? 'review' : 'editing');
    } });
  let command = null; let review = null; let envelopeError = null;
  try { ({ command, review } = restoreEnvelope(values, periodId, caseId)); } catch (failure) { envelopeError = failure; }
  const enabled = canWrite && draft.enabled && ready.has(draft.status) && !active.current && !envelopeError;
  const change = patch => {
    if (!enabled || !['editing', 'review', 'conflict'].includes(phase)) return;
    const { preview_hash: _hash, ...before } = command;
    setValues(current => ({ ...current, command_json: JSON.stringify({ ...before, ...patch }), review_json: '' }));
    setPhase('editing'); setError(null);
  };
  const failure = problem => { if (denied(problem)) onDenied?.(); setError(problem); };
  const preview = async () => {
    if (!enabled || active.current || !['editing', 'conflict'].includes(phase)) return;
    requireWrite(); active.current = true; request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setError(null); setPhase('preparing');
    try {
      const { preview_hash: _hash, ...input } = command;
      const result = readPreview(await api.post(caseId ? `${DISPUTES}/${encodeURIComponent(caseId)}/preview` : `${DISPUTES}/preview`, input, { signal: controller.signal }), input, caseId || null);
      if (controller.signal.aborted || !alive.current) return;
      setValues(current => ({ ...current, command_json: JSON.stringify(result.command), review_json: JSON.stringify(result.review) }));
      setPhase('review');
    } catch (problem) { if (!controller.signal.aborted && alive.current) { failure(problem); setPhase([409, 412].includes(problem.statusCode) ? 'conflict' : 'editing'); } }
    finally { active.current = false; }
  };
  const cleanup = async () => {
    if (!receipt || active.current) return;
    active.current = true;
    try { if (await draft.complete() && alive.current) onClose?.(); } finally { active.current = false; }
  };
  const confirm = async () => {
    if (active.current || !canWrite || !draft.enabled || envelopeError || !['review', 'unknown'].includes(phase)) return;
    requireWrite(); if (!review) { failure(new Error('invalidDisputeResponse')); return; }
    active.current = true; request.current?.abort(); const controller = new AbortController(); request.current = controller;
    const previous = phase; setError(null); setPhase('confirming');
    let sent = false;
    try {
      const outbound = copy(readPreview(review, command, caseId || null).command);
      // Failed persistence blocks the domain command. The saved JSON contains
      // the exact preview hash, expected revision and existing idempotency key.
      if (!await draft.prepareSubmit()) { if (alive.current) setPhase(previous); return; }
      if (controller.signal.aborted || !alive.current) return;
      requireWrite(); sent = true;
      const result = readReceipt(await api.post(caseId ? `${DISPUTES}/${encodeURIComponent(caseId)}/events` : DISPUTES, outbound, { signal: controller.signal }), outbound, caseId || null);
      if (controller.signal.aborted || !alive.current) return;
      setReceipt(result); setPhase('saved');
      if (!notified.current) { notified.current = true; onSaved?.(result); }
      if (await draft.complete() && alive.current) onClose?.();
    } catch (problem) {
      if (!controller.signal.aborted && alive.current) {
        failure(problem);
        if (sent) await draft.failedSubmit(problem);
        const uncertain = sent && (!problem.statusCode || problem.statusCode >= 500);
        setPhase(uncertain ? 'unknown' : [409, 412].includes(problem.statusCode) ? 'conflict' : previous);
      }
    } finally { active.current = false; }
  };
  const close = async () => {
    if (active.current) return;
    if (phase === 'saved') return cleanup();
    // Unrestored drafts remain untouched. Unknown submitted commands are
    // already durable and may be closed without changing their contents.
    if (draft.status === 'available' || phase === 'unknown') { onClose?.(); return; }
    if (await draft.flush() && alive.current) onClose?.();
  };
  return { command, review, phase, error: error || envelopeError, receipt, draft, enabled, canWrite,
    locked: !enabled || !['editing', 'review', 'conflict'].includes(phase), change, preview, confirm, cleanup, close };
}
