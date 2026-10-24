import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { CheckCheck, FilePenLine } from 'lucide-react';
import { api } from '../../api';
import FormModal from '../../components/FormModal';
import { formatMoney, formatDate } from '../../utils/format';
import { assistantApi } from './assistantApi';
import { readAssistantCommand, writeAssistantCommand, clearAssistantCommand } from './assistantDrafts';
import { contextHref, safeLocalHref } from './assistantLinks';
import AssistantAttachment from './AssistantAttachment';

const labels = { title: 'Titel', description: 'Beschreibung', body: 'Notiz', due_date: 'Fällig am', priority: 'Priorität',
  property_id: 'Immobilie', unit_id: 'Einheit', supplier: 'Lieferant', invoice_number: 'Rechnungsnummer', invoice_date: 'Rechnungsdatum',
  performance_start: 'Leistungsbeginn', performance_end: 'Leistungsende', net_amount: 'Netto', vat_rate: 'Umsatzsteuersatz', vat_amount: 'Umsatzsteuer', gross_amount: 'Brutto', payment_terms: 'Zahlungsbedingungen' };
const kindLabels = { task: 'Aufgabe', note: 'Aktennotiz', invoice: 'Rechnung' };
const rejectedStatus = failure => [400, 403, 404, 409, 422].includes(failure.statusCode);

export default function AssistantProposals({ owner, proposals, attachments = [], perform, disabled, onChanged }) {
  return <>{proposals.map(proposal => <Proposal key={proposal.id} owner={owner} attachments={attachments} proposal={{ ...proposal.payload, ...proposal }} perform={perform} disabled={disabled} onChanged={onChanged} />)}</>;
}

function Proposal({ owner, proposal, attachments, perform, disabled, onChanged }) {
  const navigate = useNavigate(); const commandIdentity = `proposal:${proposal.id}`;
  const [pending, setPending] = useState(() => readAssistantCommand(owner, commandIdentity));
  const [handoff, setHandoff] = useState(proposal.handoff || null);
  const [review, setReview] = useState(null); const [noteOpen, setNoteOpen] = useState(false);
  const saved = proposal.record || proposal.handoff?.record || handoff?.record;
  const sourceList = review?.evidence || proposal.evidence || [];
  const values = proposal.values || {};
  const openForm = result => {
    if (proposal.kind === 'note') { setNoteOpen(true); return; }
    const target = result?.to;
    if (typeof target === 'string' && /^\/(tasks|invoices)(\?|$)/.test(target)) navigate(target, { state: result.state || { prefill: result.values } });
  };
  const prepare = () => perform(async current => {
    if (!pending && (handoff || proposal.handoff)) { openForm(handoff || proposal.handoff); return; }
    let command = pending;
    if (!command) {
      const checked = await assistantApi.previewProposal(proposal.id, { expected_revision: proposal.revision, values }); current();
      const checkedReview = checked.review || checked; setReview(checkedReview);
      if (!checkedReview.allowed) return;
      command = { kind: 'apply', idempotency_key: crypto.randomUUID(), request: { expected_revision: proposal.revision, values, review_hash: checkedReview.review_hash } };
      writeAssistantCommand(owner, commandIdentity, command); setPending(command);
    }
    try {
      const result = await assistantApi.applyProposal(proposal.id, { ...command.request, idempotency_key: command.idempotency_key }); current();
      clearAssistantCommand(owner, commandIdentity, command); setPending(null); setHandoff(result.handoff); onChanged?.(result.proposal); openForm(result.handoff);
    } catch (failure) { current(); if (rejectedStatus(failure)) { clearAssistantCommand(owner, commandIdentity, command); setPending(null); } throw failure; }
  });
  const reject = () => perform(async current => {
    const command = { kind: 'reject', idempotency_key: crypto.randomUUID(), request: { expected_revision: proposal.revision, reason: 'Vom Benutzer verworfen.' } };
    writeAssistantCommand(owner, commandIdentity, command); setPending(command);
    try { const result = await assistantApi.rejectProposal(proposal.id, { ...command.request, idempotency_key: command.idempotency_key }); current(); clearAssistantCommand(owner, commandIdentity, command); setPending(null); onChanged?.(result.proposal); }
    catch (failure) { current(); if (rejectedStatus(failure)) { clearAssistantCommand(owner, commandIdentity, command); setPending(null); } throw failure; }
  });
  const reconcileReject = () => perform(async current => {
    try { const result = await assistantApi.rejectProposal(proposal.id, { ...pending.request, idempotency_key: pending.idempotency_key }); current(); clearAssistantCommand(owner, commandIdentity, pending); setPending(null); onChanged?.(result.proposal); }
    catch (failure) { current(); if (rejectedStatus(failure)) { clearAssistantCommand(owner, commandIdentity, pending); setPending(null); } throw failure; }
  });
  const display = (key, value) => {
    if (value == null || value === '') return 'Nicht erfasst';
    if (['property_id', 'unit_id'].includes(key)) return sourceList.find(source => source.kind === key.replace('_id', '') && source.id === value)?.title || 'Zuordnung im Fachformular prüfen';
    if (key.endsWith('_amount')) return formatMoney(value, { currency: 'EUR' });
    if (key === 'priority') return { low: 'Niedrig', medium: 'Mittel', high: 'Hoch' }[value] || value;
    if (key === 'vat_rate') return `${String(value).replace('.', ',')}\u00a0%`;
    if (['due_date', 'invoice_date', 'performance_start', 'performance_end'].includes(key)) return formatDate(value);
    return String(value);
  };
  return <section className={`assistant-proposal ${saved ? 'saved' : ''}`} aria-label={`Vorschlag prüfen: ${kindLabels[proposal.kind] || 'Entwurf'}`}>
    <h3><FilePenLine size={16} aria-hidden="true" /> {kindLabels[proposal.kind] || 'Entwurf'}{saved ? ' gespeichert' : proposal.state === 'rejected' ? ' verworfen' : ' vorbereiten'}</h3>
    {saved ? <p role="status"><CheckCheck size={15} /> Fachlich gespeichert. {safeLocalHref(saved.href) && <Link to={safeLocalHref(saved.href)}>{saved.title || 'Gespeicherten Eintrag öffnen'} →</Link>}</p> : <>
      <dl>{Object.entries(values).filter(([key]) => labels[key]).map(([key, value]) => <div key={key} style={{ display: 'contents' }}><dt>{labels[key]}</dt><dd>{display(key, value)}</dd></div>)}</dl>
      {sourceList.length > 0 && <details><summary>Belegte Quellen ({sourceList.length})</summary>{sourceList.map((source, index) => source.kind === 'attachment' ? <AssistantAttachment key={source.id} attachment={attachments.find(item => item.id === source.id) || { id: source.id, name: source.title || 'Chatdatei', byte_length: 0 }} /> : <div key={index}>{contextHref(source) ? <Link to={contextHref(source)}>{source.title || 'Originalakte öffnen'}</Link> : source.title || 'Quelle'}<details><summary>Nachweisdetails</summary><small>Stand {source.revision}{source.sha256 ? ` · SHA-256 ${source.sha256}` : ''}</small></details></div>)}</details>}
      {proposal.state === 'rejected' ? <p role="status">Vorschlag verworfen.</p> : <>
        <p>Die Angaben werden im bestehenden Fachformular geprüft. Erst „Speichern“ legt den Eintrag an.</p>
        {review?.allowed === false && <p role="status">Die Vorbereitung ist noch unvollständig. Bitte fehlende Angaben im Chat klären.</p>}
        {(review?.warnings || []).map((warning, index) => <p role="status" key={index}>{typeof warning === 'string' ? warning : warning.message}</p>)}
        {pending ? <p role="status">Die Bestätigung der Vorbereitung fehlt. Ihre Angaben bleiben erhalten. <button type="button" className="btn btn-secondary" disabled={disabled} onClick={pending.kind === 'reject' ? reconcileReject : prepare}>Vorbereitung abgleichen</button></p>
          : <div className="assistant-inline-actions"><button type="button" className="btn btn-primary" disabled={disabled} onClick={prepare}>Im Fachformular prüfen</button><button type="button" className="btn btn-secondary" disabled={disabled} onClick={reject}>Verwerfen</button></div>}
      </>}
    </>}
    {noteOpen && <NoteReview owner={owner} proposal={proposal} handoff={handoff || proposal.handoff} onClose={() => setNoteOpen(false)} onSaved={result => { setHandoff(previous => ({ ...previous, record: result.record })); onChanged?.(result.proposal); setNoteOpen(false); }} />}
  </section>;
}

function NoteReview({ owner, proposal, handoff, onClose, onSaved }) {
  const alive = useRef(true); useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const saved = useRef(null);
  const identity = `save:${proposal.id}`;
  const initialSave = useRef(readAssistantCommand(owner, identity));
  const save = async values => {
    const session = api.captureSession(); const original = readAssistantCommand(owner, identity);
    const normalized = { body: values.body, conversation_kind: 'note' };
    if (original && JSON.stringify(original.request.values) !== JSON.stringify(normalized)) throw new Error('Eine Speicherung ist unbestätigt. Bitte zuerst dieselben Angaben erneut speichern; anschließend können Sie den gespeicherten Eintrag bearbeiten.');
    const command = original || { kind: 'save', idempotency_key: crypto.randomUUID(), request: { expected_revision: proposal.revision, values: normalized } };
    writeAssistantCommand(owner, identity, command);
    try {
      const result = await assistantApi.saveProposal(proposal.id, { ...command.request, idempotency_key: command.idempotency_key }); session();
      if (!alive.current) throw new Error('Die Unterhaltung wurde gewechselt. Die Speicherung wird beim nächsten Öffnen abgeglichen.');
      clearAssistantCommand(owner, identity, command); saved.current = result;
    } catch (failure) { if (alive.current && rejectedStatus(failure)) clearAssistantCommand(owner, identity, command); throw failure; }
  };
  return <FormModal title={`Aktennotiz prüfen · ${handoff?.title || 'Vorgang'}`} fields={[{ key: 'body', label: 'Gesprächsnotiz', type: 'textarea', required: true }]} initial={{ body: initialSave.current?.request?.values?.body || handoff?.values?.body || proposal.values?.body || '' }} onSave={save} onClose={() => { if (saved.current && alive.current) onSaved(saved.current); else onClose(); }}
    draftContext="conversation-note" draftAnchor={handoff?.anchor?.kind !== 'attachment' ? handoff?.anchor : undefined} />;
}
