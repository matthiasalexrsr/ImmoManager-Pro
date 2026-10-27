import { AI_CONFIDENCE, AI_MARK } from './aiMarks';
import './aiReading.css';

export function AiMarkChip({ state, mark }) {
  if (!state) return null;
  return <span className={`ai-mark is-${state}`} title={state === 'changed' && mark ? `Die KI las: ${mark.value}` : undefined}>{AI_MARK[state]}</span>;
}

/** The confirm button of a pending value and where the value stands in the document. */
export function AiFieldNote({ label, state, mark, onConfirm, disabled }) {
  return <>
    {state === 'pending' && <button type="button" className="btn btn-sm btn-secondary ai-confirm" disabled={disabled}
      aria-label={`${label}: von der KI eingetragenen Wert bestätigen`} onClick={onConfirm}>Bestätigen</button>}
    {mark && (mark.evidence || mark.confidence) && <small className="ai-evidence-hint">
      {mark.evidence ? `Beleg: „${mark.evidence}“` : ''}{mark.evidence && mark.confidence ? ' · ' : ''}
      {mark.confidence ? AI_CONFIDENCE[mark.confidence] : ''}</small>}
    {mark?.citation?.verified ? <small className="ai-evidence-hint">Fundstelle geprüft: Zeile {mark.citation.line} im extrahierten Text{mark.citation.version_id ? ' · archivierte Originalversion' : ' · Datei mit Prüfsumme'}</small>
      : mark?.evidence_status && <small className="ai-evidence-hint">Keine bestätigte Textfundstelle. Angabe am Original prüfen.</small>}
  </>;
}

export function AiFormSummary({ aiMarks, filled, pending, onConfirmAll, disabled }) {
  if (!aiMarks || filled === 0) return null;
  return <div className="ai-form-summary" role="status">
    <strong>{filled} {filled === 1 ? 'Wert' : 'Werte'} von {aiMarks.label || 'der KI'}</strong>
    {aiMarks.document && <span>aus „{aiMarks.document}“</span>}
    <span>{aiMarks.mode === 'confirm' ? (pending.length ? `${pending.length} noch zu bestätigen` : 'alle geprüft')
      : 'markiert: von der KI eingetragen, geändert oder neu'}</span>
    {pending.length > 0 && <button type="button" className="btn btn-sm btn-secondary" disabled={disabled}
      onClick={onConfirmAll}>Alle bestätigen</button>}
  </div>;
}
