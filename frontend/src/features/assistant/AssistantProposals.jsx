import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { CheckCheck, FilePenLine } from 'lucide-react';
import { assistantApi } from './assistantApi';
import { readAssistantCommand, writeAssistantCommand, clearAssistantCommand } from './assistantDrafts';
import ConversationDialog from '../workCenter/ConversationDialog';
import { contextHref } from './assistantLinks';

const labels = { title: 'Titel', description: 'Beschreibung', notes: 'Notiz', content: 'Inhalt', body: 'Notiz', conversation_kind: 'Art', due_date: 'Fällig am', priority: 'Priorität',
  property_id: 'Immobilie', unit_id: 'Einheit', tenant_id: 'Partei', supplier: 'Lieferant', invoice_number: 'Rechnungsnummer',
  invoice_date: 'Rechnungsdatum', net_amount: 'Netto (€)', vat_rate: 'MwSt-Satz (%)', vat_amount: 'MwSt (€)', gross_amount: 'Brutto (€)', document_type: 'Dokumenttyp' };
const kindLabels = { task: 'Aufgabe', note: 'Aktennotiz', invoice: 'Rechnungsentwurf', document: 'Dokumententwurf' };

export default function AssistantProposals({ owner, proposals, perform, disabled, onChanged }) {
  return <>{proposals.map(proposal => <Proposal key={proposal.id} owner={owner} proposal={{ ...proposal.payload, ...proposal }} perform={perform} disabled={disabled} onChanged={onChanged} />)}</>;
}

function Proposal({ owner, proposal, perform, disabled, onChanged }) {
  const navigate = useNavigate();
  const commandIdentity = `proposal:${proposal.id}`;
  const [pending, setPending] = useState(() => readAssistantCommand(owner, commandIdentity));
  const [values, setValues] = useState(pending?.request?.values || proposal.values || {});
  const [review, setReview] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [handoff, setHandoff] = useState(proposal.handoff || null);
  const [rejected, setRejected] = useState(proposal.state === 'rejected');
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteSaved, setNoteSaved] = useState(false);
  const preview = () => perform(async current => {
    const result = await assistantApi.previewProposal(proposal.id, { expected_revision: proposal.revision, values }); current();
    setReview(result.review || result); setConfirmed(false);
  });
  const decide = action => perform(async current => {
    const command = pending || { kind: action, idempotency_key: crypto.randomUUID(), request: action === 'apply'
      ? { expected_revision: proposal.revision, values, review_hash: review.review_hash }
      : { expected_revision: proposal.revision, reason: 'Vom Benutzer verworfen.' } };
    writeAssistantCommand(owner, commandIdentity, command); setPending(command);
    try {
      const result = await (command.kind === 'apply' ? assistantApi.applyProposal : assistantApi.rejectProposal)(proposal.id, { ...command.request, idempotency_key: command.idempotency_key }); current();
      clearAssistantCommand(owner, commandIdentity, command); setPending(null);
      if (command.kind === 'apply') setHandoff(result.handoff); else setRejected(true);
      onChanged?.(result.proposal);
    } catch (failure) {
      current(); if ([400, 403, 404, 409, 422].includes(failure.statusCode)) { clearAssistantCommand(owner, commandIdentity, command); setPending(null); }
      throw failure;
    }
  });
  return <section className="assistant-proposal" aria-label={`Vorschlag prüfen: ${kindLabels[proposal.kind] || 'Entwurf'}`}>
    <h3><FilePenLine size={16} aria-hidden="true" /> {kindLabels[proposal.kind] || 'Entwurf'} vorgeschlagen</h3>
    <p>{proposal.reason || proposal.explanation || 'Prüfen Sie die vorgeschlagenen Angaben und ihre Quellen, bevor Sie einen Entwurf übernehmen.'}</p>
    <dl>{Object.entries(values).map(([key, value]) => <div key={key} style={{ display: 'contents' }}><dt>{labels[key] || key}</dt><dd>{value == null ? 'Nicht erfasst' : typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>
    {!handoff && !rejected && <details><summary>Vorgeschlagene Angaben bearbeiten</summary>{Object.entries(values).filter(([key, value]) => labels[key] && (value == null || typeof value !== 'object')).map(([key, value]) => <label key={key}>{labels[key]}<input aria-label={`Vorschlag: ${labels[key]}`} value={value ?? ''} disabled={disabled || Boolean(pending)} onChange={event => { setValues(previous => ({ ...previous, [key]: event.target.value })); setReview(null); setConfirmed(false); }} /></label>)}</details>}
    {(proposal.evidence || []).length > 0 && <details><summary>Belegte Quellen ({proposal.evidence.length})</summary>{proposal.evidence.map((source, index) => <p key={index}>{contextHref(source) ? <Link to={contextHref(source)}>{source.title || source.kind}</Link> : source.title || source.kind} · Stand {source.revision}{source.sha256 ? ` · ${source.sha256}` : ''}</p>)}</details>}
    {pending && <p role="status">Die Entwurfsentscheidung ist unbestätigt. <button type="button" disabled={disabled} onClick={() => decide(pending.kind)}>Entscheidung abgleichen</button></p>}
    {rejected ? <p role="status">Vorschlag verworfen.</p> : handoff ? <><p role="status"><CheckCheck size={15} /> Persönlicher Entwurf vorbereitet. Kennung {handoff.draft_id?.slice(0, 12)}</p><button className="btn btn-primary" type="button" onClick={() => {
      if (proposal.kind === 'note' && handoff.anchor?.id && handoff.anchor_revision) { setNoteOpen(true); return; }
      const path = handoff.to || handoff.path || handoff.route;
      if (typeof path === 'string' && /^\/(tasks|documents|invoices)(\?|$)/.test(path)) navigate(path, { state: handoff.state || { prefill: handoff.prefill || handoff.values } });
    }}>Entwurf im Fachformular öffnen</button></> : <>
      <div className="finance-actions"><button className="btn btn-secondary" type="button" disabled={disabled || Boolean(pending)} onClick={preview}>Angaben und Quellen prüfen</button><button className="btn btn-secondary" type="button" disabled={disabled || Boolean(pending)} onClick={() => decide('reject')}>Verwerfen</button></div>
      {review && <><p role="status">{review.allowed ? 'Die Angaben wurden geprüft. Der Entwurf wird noch nicht fachlich gespeichert.' : 'Dieser Vorschlag kann derzeit nicht übernommen werden.'}</p>
        {(review.warnings || []).map((warning, index) => <p role="status" key={index}>{typeof warning === 'string' ? warning : warning.message}</p>)}
        {review.allowed && <><label className="assistant-proposal-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} disabled={disabled || Boolean(pending)} />Ich habe die Angaben und ihre Quellen geprüft.</label><button type="button" className="btn btn-primary" disabled={disabled || Boolean(pending) || !confirmed} onClick={() => decide('apply')}>Entwurf übernehmen</button></>}
      </>}
    </>}
    {noteOpen && <ConversationDialog entityType={handoff.anchor.kind} entityId={handoff.anchor.id} entityRevision={handoff.anchor_revision} title={handoff.title || 'KI-Notizentwurf'} initial={handoff.values || handoff.state?.prefill}
      onClose={() => setNoteOpen(false)} onSaved={() => { setNoteOpen(false); setNoteSaved(true); }} />}
    {noteSaved && <p role="status">Die Notiz wurde im bestehenden Fachablauf gespeichert.</p>}
  </section>;
}
