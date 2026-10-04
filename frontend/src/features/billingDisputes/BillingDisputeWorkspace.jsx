import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { useTranslation } from '../../i18n';
import useWriteAccess from '../../hooks/useWriteAccess';
import { principalKey } from '../unitInventory/read';
import { appendCommand, openCommand } from './disputeModel';
import { disputeText } from './disputeCopy';
import { DisputeFailure } from './DisputeOriginals';
import BillingDisputeRead from './BillingDisputeRead';
import DisputeCommandPanel from './DisputeCommandPanel';
import './BillingDisputes.css';

function Workspace({ periodId, propertyId, principal }) {
  const [entry, setEntry] = useState(null); const [generation, setGeneration] = useState(0); const [fenced, setFenced] = useState(false);
  const root = useRef(null); const returning = useRef(false);
  useLayoutEffect(() => { if (!entry && returning.current) { returning.current = false; root.current?.querySelector('h2')?.focus(); } }, [entry]);
  const { locale } = useTranslation(); const tr = key => disputeText(locale, key);
  const onDenied = useCallback(() => { setEntry(null); setFenced(true); }, []);
  const { canWrite, isAllowed } = useWriteAccess('/billing', () => setEntry(null));
  const newCase = () => {
    if (!isAllowed() || entry) return;
    const command = openCommand(periodId, { id: null, revision: null, snapshot_hash: null });
    setEntry({ command, caseId: '' });
  };
  const newEvent = (caseRow, kind, target) => {
    if (!isAllowed() || entry) return;
    const command = appendCommand(caseRow, kind);
    if (kind === 'correction') {
      if (!target || target.case_id !== caseRow.id || target.revision > caseRow.revision) return;
      command.corrects_event_id = target.id;
    }
    setEntry({ command, caseId: caseRow.id });
  };
  if (fenced) return <section className="billing-disputes panel" aria-label={tr('title')}><DisputeFailure error={{ statusCode: 403 }} tr={tr}
    onRetry={() => { setFenced(false); setGeneration(value => value + 1); }} /></section>;
  return <div ref={root}><BillingDisputeRead periodId={periodId} generation={generation} onDenied={onDenied}
    onNewCase={canWrite && !entry ? newCase : undefined} onEvent={canWrite && !entry ? newEvent : undefined} />
    {entry && canWrite && <DisputeCommandPanel key={entry.command.idempotency_key} periodId={periodId} propertyId={propertyId} principal={principal} caseId={entry.caseId} initialCommand={entry.command}
      onDenied={onDenied} onSaved={() => setGeneration(value => value + 1)} onClose={() => { returning.current = true; setEntry(null); }} />}</div>;
}

/** Billing owns period selection; this component owns one isolated file context. */
export default function BillingDisputeWorkspace({ periodId, propertyId }) {
  const principal = principalKey(useAuth()?.user);
  if (!principal || !periodId || !propertyId) return null;
  return <Workspace key={`${principal}:${periodId}:${propertyId}`} periodId={periodId} propertyId={propertyId} principal={principal} />;
}
