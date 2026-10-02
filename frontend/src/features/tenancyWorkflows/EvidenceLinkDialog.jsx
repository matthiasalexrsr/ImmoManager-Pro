import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import BoundedReferencePicker from './BoundedReferencePicker';
import DocumentVersionPicker from './DocumentVersionPicker';
import WorkflowCommandNotice from './WorkflowCommandNotice';
import useWorkflowCommand from './useWorkflowCommand';
import { workflowText } from './workflowCopy';
import './TenancyWorkflows.css';

function preferredKind(step) {
  if (step.evidence_requirement === 'handover_protocol') return 'handover_protocol';
  if (step.evidence_requirement === 'meter_reading') return 'meter_reading';
  return 'document_version';
}

export default function EvidenceLinkDialog({
  step,
  locale = 'de-DE',
  principalKey = '',
  propertyId,
  unitId,
  contractId,
  loadDocuments,
  loadDocumentVersions,
  loadHandoverProtocols,
  loadMeterReadings,
  canSelectEvidence,
  prepareLink,
  onLinked,
  onClose,
}) {
  const [kind, setKind] = useState(() => preferredKind(step));
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [documentVersion, setDocumentVersion] = useState(null);
  const [reference, setReference] = useState(null);
  const [localError, setLocalError] = useState(null);
  const dialog = useRef(null);
  const command = useWorkflowCommand(principalKey);
  const tr = useCallback((key, params) => workflowText(locale, key, params), [locale]);

  useEffect(() => {
    dialog.current?.querySelector('button, input, select')?.focus();
    const listener = event => {
      if (event.key === 'Escape' && !command.busy && command.state.phase !== 'unknown') onClose?.();
    };
    document.addEventListener('keydown', listener);
    return () => document.removeEventListener('keydown', listener);
  }, [command.busy, command.state.phase, onClose]);

  const kinds = useMemo(() => [
    typeof loadDocuments === 'function' && typeof loadDocumentVersions === 'function'
      ? ['document_version', tr('evidence_document_original')] : null,
    typeof loadHandoverProtocols === 'function'
      ? ['handover_protocol', tr('evidence_handover_protocol')] : null,
    typeof loadMeterReadings === 'function'
      ? ['meter_reading', tr('evidence_meter_reading')] : null,
  ].filter(Boolean), [loadDocumentVersions, loadDocuments, loadHandoverProtocols, loadMeterReadings, tr]);

  const documentLoader = args => loadDocuments?.({
    ...args, propertyId, unitId, contractId, direction: step.direction,
  });
  const handoverLoader = args => loadHandoverProtocols?.({
    ...args, propertyId, unitId, contractId, direction: step.direction,
  });
  const meterLoader = args => loadMeterReadings?.({
    ...args, propertyId, unitId, contractId, direction: step.direction,
  });

  const selectable = useCallback((candidateKind, item) => {
    if (typeof canSelectEvidence === 'function') return canSelectEvidence(candidateKind, item, step);
    return Boolean(item?.id) && ['document_version', 'handover_protocol', 'meter_reading'].includes(candidateKind);
  }, [canSelectEvidence, step]);

  const selection = useMemo(() => {
    if (kind === 'document_version' && selectedDocument?.id && documentVersion?.id) {
      return { kind, document_id: selectedDocument.id, document_version_id: documentVersion.id };
    }
    if (kind !== 'document_version' && reference) return { kind, item: reference };
    return null;
  }, [documentVersion, kind, reference, selectedDocument]);

  const changeKind = value => {
    setKind(value);
    setSelectedDocument(null);
    setDocumentVersion(null);
    setReference(null);
    setLocalError(null);
    command.reset();
  };

  const link = () => {
    if (!selection) return;
    const prepared = prepareLink?.({ step, selection });
    if (!prepared || !prepared.payload || typeof prepared.send !== 'function') {
      setLocalError(tr('missingAdapter'));
      return;
    }
    command.execute({
      label: 'link-workflow-evidence',
      payload: prepared.payload,
      send: prepared.send,
      onSuccess: result => {
        onLinked?.(result);
        onClose?.();
      },
    });
  };

  return (
    <div className="workflow-modal-backdrop" role="presentation" onMouseDown={event => {
      if (event.target === event.currentTarget && !command.busy && command.state.phase !== 'unknown') onClose?.();
    }}>
      <section ref={dialog} className="workflow-modal" role="dialog" aria-modal="true"
        aria-labelledby="workflow-evidence-title" aria-busy={command.busy}>
        <header>
          <div>
            <span className="workflow-eyebrow">{tr('evidence')}</span>
            <h3 id="workflow-evidence-title">{tr('addEvidence')}</h3>
            <p>{step.title_snapshot}</p>
          </div>
          <button type="button" className="btn btn-secondary btn-sm"
            disabled={command.busy || command.state.phase === 'unknown'} onClick={onClose}>{tr('close')}</button>
        </header>

        <WorkflowCommandNotice state={command.state} locale={locale}
          onRetryExact={command.retryExact} onDismiss={command.reset} />
        {localError && <div className="workflow-inline-error" role="alert">{localError}</div>}

        <label className="workflow-field">
          <span>{tr('evidenceRequirement')}</span>
          <select value={kind} disabled={command.busy || command.state.phase === 'unknown'}
            onChange={event => changeKind(event.target.value)}>
            {kinds.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>

        {kind === 'document_version' && (
          <>
            <BoundedReferencePicker label={tr('selectDocument')} locale={locale}
              value={selectedDocument?.id || null} selectedItem={selectedDocument} loadPage={documentLoader}
              sourceKey={`${propertyId}:${unitId}:${contractId}:${step.direction}:documents`}
              getLabel={item => item.title || item.id}
              getDescription={item => [item.document_type, item.document_date].filter(Boolean).join(' · ')}
              isSelectable={item => selectable('document_version', item)}
              disabled={command.busy || command.state.phase === 'unknown'}
              onChange={item => { setSelectedDocument(item); setDocumentVersion(null); }} required />
            {selectedDocument && (
              <DocumentVersionPicker documentId={selectedDocument.id} locale={locale}
                value={documentVersion?.id || null} loadPage={loadDocumentVersions}
                disabled={command.busy || command.state.phase === 'unknown'}
                onChange={setDocumentVersion} />
            )}
          </>
        )}

        {kind === 'handover_protocol' && (
          <BoundedReferencePicker label={tr('evidence_handover_protocol')} locale={locale}
            value={reference?.id || null} selectedItem={reference} loadPage={handoverLoader}
            sourceKey={`${propertyId}:${unitId}:${contractId}:${step.direction}:handovers`}
            getLabel={item => [item.protocol_type, item.protocol_date].filter(Boolean).join(' · ') || item.id}
            getDescription={item => item.status || ''}
            isSelectable={item => selectable('handover_protocol', item)}
            disabled={command.busy || command.state.phase === 'unknown'}
            onChange={setReference} required />
        )}

        {kind === 'meter_reading' && (
          <BoundedReferencePicker label={tr('evidence_meter_reading')} locale={locale}
            value={reference?.id || null} selectedItem={reference} loadPage={meterLoader}
            sourceKey={`${propertyId}:${unitId}:${contractId}:${step.direction}:meter-readings`}
            getLabel={item => [item.meter_number, item.reading_value, item.unit].filter(value => value != null).join(' · ') || item.id}
            getDescription={item => item.reading_date || item.created_at || ''}
            isSelectable={item => selectable('meter_reading', item)}
            disabled={command.busy || command.state.phase === 'unknown'}
            onChange={setReference} required />
        )}

        <footer className="workflow-actions">
          <button type="button" className="btn btn-primary"
            disabled={!selection || command.busy || command.state.phase === 'unknown'} onClick={link}>
            {command.busy ? tr('working') : tr('linkEvidence')}
          </button>
        </footer>
      </section>
    </div>
  );
}
