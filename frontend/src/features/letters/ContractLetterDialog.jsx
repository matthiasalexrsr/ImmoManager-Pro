import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { mayWrite } from '../../utils/permissions';
import { entityHref } from '../../utils/entityLinks';
import PdfPreview from '../../components/PdfPreview';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import { checkPreview, letterData, letterSignature, lettersService, pdfHash } from './lettersApi';
import './letters.css';

const TEXT_FIELDS = [
  { key: 'recipient_name', label: 'Empfänger', required: true },
  { key: 'recipient_address', label: 'Empfängeranschrift', rows: 3, required: true },
  { key: 'issue_date', label: 'Briefdatum', type: 'date', required: true },
  { key: 'subject', label: 'Betreff', required: true, wide: true },
  { key: 'salutation', label: 'Anrede', wide: true },
  { key: 'body', label: 'Text', rows: 14, wide: true },
  { key: 'closing', label: 'Schlussformel', rows: 2 },
  { key: 'signature', label: 'Unterschrift / Name' },
  { key: 'appendix', label: 'Anhang nach der Unterschrift', rows: 5, wide: true },
];
const LEVEL = { error: { icon: XCircle, label: 'Fehler' }, warning: { icon: AlertTriangle, label: 'Hinweis' }, info: { icon: Info, label: 'Info' } };
const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);

function Checks({ checks }) {
  if (!checks?.length) return null;
  return <ul className="letter-checks">{checks.map((check, index) => {
    const { icon: Icon, label } = LEVEL[check.level] || LEVEL.info;
    return <li key={index} className={`letter-check letter-check-${check.level}`}><Icon size={16} aria-hidden="true" /><span><strong>{label}:</strong> {check.text}</span></li>;
  })}</ul>;
}

function InputField({ field, value, onChange, id }) {
  const common = { id, required: field.required, value: value ?? '', onChange: event => onChange(event.target.value) };
  if (field.type === 'bool') {
    return <label className="letters-check letters-field-wide"><input type="checkbox" checked={Boolean(value)} onChange={event => onChange(event.target.checked)} /> {field.label}</label>;
  }
  return <div className={`letters-field${field.multiline ? ' letters-field-wide' : ''}`}>
    <label htmlFor={id}>{field.label}{field.required ? ' *' : ''}</label>
    {field.type === 'choice' ? <select {...common}>{field.choices.map(choice => <option key={choice.value} value={choice.value}>{choice.label}</option>)}</select>
      : field.multiline ? <textarea rows={3} {...common} />
        : <input type={field.type === 'date' ? 'date' : field.type === 'time' ? 'time' : 'text'} inputMode={field.type === 'amount' ? 'decimal' : undefined} {...common} />}
    {field.hint && <small>{field.hint}</small>}
  </div>;
}

/** Write a letter to the tenant of a contract from a template, check it as PDF and archive the original. */
export default function ContractLetterDialog({ contractId, onClose, onPublished, service = lettersService }) {
  const auth = useAuth();
  const id = useId();
  const dialog = useRef(null);
  const controllers = useRef(new Set());
  const ticket = useRef(0);
  const pending = useRef(null);
  const urls = useRef([]);
  const [context, setContext] = useState(null);
  const [templateId, setTemplateId] = useState('');
  const [issueDate, setIssueDate] = useState(today);
  const [composed, setComposed] = useState(null);
  const [inputs, setInputs] = useState({});
  const [form, setForm] = useState(null);
  const [baseline, setBaseline] = useState('');
  const [preview, setPreview] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [published, setPublished] = useState(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const [leave, setLeave] = useState(false);
  const [stale, setStale] = useState(false);
  const allowed = Boolean(auth?.user?.id && auth.user.role !== 'readonly'
    && mayWrite(auth?.write ?? null, `/contracts/${contractId}/letters`) && mayWrite(auth?.write ?? null, '/documents'));
  const dirty = Boolean(form && letterSignature(form, inputs) !== baseline && !published);

  const start = () => { const controller = new AbortController(); controllers.current.add(controller); return controller; };
  const finish = controller => controllers.current.delete(controller);
  const remember = url => { urls.current.push(url); return url; };
  useEffect(() => () => {
    controllers.current.forEach(controller => controller.abort());
    urls.current.forEach(url => URL.revokeObjectURL(url));
  }, []);

  const loadContext = async () => {
    const controller = start(); setBusy('load'); setError('');
    try {
      const next = await service.context(contractId, { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (typeof next?.source_revision !== 'string' || !Array.isArray(next.templates)) throw new Error('Die Briefdaten sind unvollständig. Bitte erneut laden.');
      setContext(next);
      setTemplateId(old => old || next.templates[0]?.id || '');
    } catch (problem) { if (!controller.signal.aborted) setError(problem.message || 'Die Briefdaten konnten nicht geladen werden.'); }
    finally { finish(controller); if (!controller.signal.aborted) setBusy(''); }
  };
  useEffect(() => { void loadContext(); // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contractId]);

  const invalidate = () => { ticket.current += 1; setPreview(null); setConfirmed(false); };

  const compose = async withInputs => {
    if (busy || !templateId) return;
    invalidate(); const mine = ticket.current;
    const controller = start(); setBusy('compose'); setError('');
    try {
      const result = await service.compose(contractId, { template_id: templateId, inputs: withInputs ? inputs : null, issue_date: issueDate }, { signal: controller.signal });
      if (controller.signal.aborted || mine !== ticket.current) return;
      setComposed(result);
      setInputs(result.inputs || {});
      setStale(false);
      if (result.data) {
        const data = letterData(result.data);
        setForm(data); setBaseline(letterSignature(data, result.inputs));
      } else setForm(null);
    } catch (problem) { if (!controller.signal.aborted) setError(problem.message || 'Der Brief konnte nicht erstellt werden.'); }
    finally { finish(controller); if (!controller.signal.aborted) setBusy(''); }
  };

  const changeInput = (key, value) => { invalidate(); if (form) setStale(true); setInputs(old => ({ ...old, [key]: value })); };
  const changeField = (key, value) => { invalidate(); setPublished(null); setForm(old => ({ ...old, [key]: value })); };

  const payload = () => ({ source_revision: composed.source_revision, template_id: composed.template.id, inputs, data: letterData(form) });

  const makePreview = async event => {
    event?.preventDefault();
    if (busy || !form || !composed || stale) return;
    invalidate(); const mine = ticket.current;
    const body = payload();
    const controller = start(); setBusy('preview'); setError('');
    try {
      const review = checkPreview(await service.preview(contractId, body, { signal: controller.signal }), body);
      const blob = await service.previewPdf(contractId, body, { signal: controller.signal });
      const hash = await pdfHash(blob);
      if (controller.signal.aborted || mine !== ticket.current) return;
      if (hash !== review.pdf_sha256) throw new Error('Die PDF-Datei stimmt nicht mit der geprüften Vorschau überein. Bitte neu erstellen.');
      setPreview({ ...review, url: remember(URL.createObjectURL(blob)), payload: body });
    } catch (problem) {
      if (controller.signal.aborted) return;
      setError(problem?.statusCode === 412 ? 'Vertrag, Miete oder Briefkopf wurden inzwischen geändert. Bitte „Text neu erstellen“ wählen; Ihre Eingaben bei den Angaben bleiben erhalten.' : problem.message || 'Die Vorschau konnte nicht erstellt werden.');
    } finally { finish(controller); if (!controller.signal.aborted) setBusy(''); }
  };

  const publish = async () => {
    if (busy || !context?.can_publish) return;
    if (!pending.current) {
      if (!preview || preview.review.draft || !confirmed) return;
      pending.current = { ...preview.payload, review_hash: preview.review_hash, idempotency_key: crypto.randomUUID() };
    }
    const command = pending.current;
    const controller = start(); setBusy('publish'); setError('');
    try {
      const result = await service.publish(contractId, command, { signal: controller.signal });
      if (!result?.document_id || result.review_hash !== command.review_hash) throw new Error('Die Archivierung konnte nicht eindeutig bestätigt werden. Bitte erneut prüfen.');
      pending.current = null; setUncertain(false); setPublished(result); setConfirmed(false);
      setContext(old => ({ ...old, originals: [result, ...(old?.originals || []).filter(item => item.document_id !== result.document_id)] }));
      onPublished?.(result);
    } catch (problem) {
      if (controller.signal.aborted) return;
      if ([400, 403, 404, 409, 412, 422].includes(problem?.statusCode)) { pending.current = null; setUncertain(false); setError(problem.message); }
      else { setUncertain(true); setError('Die Antwort zur Archivierung ist unklar. „Archivierung erneut prüfen“ wiederholt denselben Auftrag und erzeugt kein zweites Original.'); }
    } finally { finish(controller); if (!controller.signal.aborted) setBusy(''); }
  };

  const download = async record => {
    const controller = start();
    try {
      const blob = await service.original(record, { signal: controller.signal });
      const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `${record.subject || 'Brief'}.pdf`; document.body.appendChild(anchor); anchor.click(); anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (problem) { if (!controller.signal.aborted) setError(problem.message || 'Das Original konnte nicht geladen werden.'); }
    finally { finish(controller); }
  };

  const requestClose = () => {
    if (busy === 'publish' || pending.current) { setError('Die Archivierung muss zuerst eindeutig abgeschlossen werden.'); return; }
    if (dirty) setLeave(true); else onClose();
  };
  useModalDialog(dialog, () => { if (leave) setLeave(false); else requestClose(); });

  const kind = context?.kinds?.find(item => item.kind === composed?.template?.kind);
  const templates = context?.templates || [];
  const groups = [['Mitgeliefert', templates.filter(item => item.builtin)], ['Eigene Vorlagen', templates.filter(item => !item.builtin)]];
  const checks = preview ? preview.review.checks : composed?.checks;
  const errors = (checks || []).filter(check => check.level === 'error').length;

  return createPortal(<div className="modal-overlay contract-letter-overlay" onClick={event => { if (event.target === event.currentTarget) requestClose(); }}>
    <section className="contract-letter-dialog" ref={dialog} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} tabIndex={-1}>
      <header className="contract-letter-header"><div><h2 id={`${id}-title`}>Brief schreiben</h2><p>Vorlage wählen, Angaben prüfen, Text anpassen und als Original in der Akte ablegen. Der Brief wird nicht versendet.</p></div>
        <button type="button" className="btn-close" aria-label="Briefdialog schließen" onClick={requestClose}>×</button></header>
      <div className="contract-letter-body">
        {error && <p className="letters-error" role="alert">{error}</p>}
        {busy === 'load' && <p role="status">Briefdaten werden geladen …</p>}
        {!context && busy !== 'load' && <button type="button" className="btn btn-secondary" onClick={loadContext}>Erneut laden</button>}
        {context && <>
          {context.warnings?.length > 0 && <ul className="letter-checks">{context.warnings.map((warning, index) => <li key={index} className="letter-check letter-check-warning"><AlertTriangle size={16} aria-hidden="true" /><span>{warning} <Link to="/settings?section=letterhead">Briefkopf öffnen</Link></span></li>)}</ul>}
          <section className="contract-letter-step" aria-labelledby={`${id}-step1`}>
            <h3 id={`${id}-step1`}><span className="letter-step-number">1</span> Vorlage</h3>
            <div className="letters-grid">
              <div className="letters-field letters-field-wide"><label htmlFor={`${id}-template`}>Vorlage</label>
                <select id={`${id}-template`} value={templateId} disabled={Boolean(busy)} onChange={event => { setTemplateId(event.target.value); setComposed(null); setForm(null); invalidate(); }}>
                  {groups.filter(([, items]) => items.length).map(([label, items]) => <optgroup key={label} label={label}>{items.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</optgroup>)}
                </select>
                <small>{context.kinds?.find(item => item.kind === templates.find(entry => entry.id === templateId)?.kind)?.description} <Link to="/letter-templates">Vorlagen verwalten</Link></small></div>
              <div className="letters-field"><label htmlFor={`${id}-issue`}>Briefdatum</label>
                <input id={`${id}-issue`} type="date" value={issueDate} disabled={Boolean(busy)} onChange={event => { setIssueDate(event.target.value); invalidate(); }} /></div>
            </div>
            <div className="letters-actions"><button type="button" className="btn btn-secondary" disabled={Boolean(busy) || !templateId} onClick={() => compose(false)}>{composed ? 'Vorlage neu laden' : 'Weiter'}</button></div>
          </section>
          {composed && kind?.inputs?.length > 0 && <section className="contract-letter-step" aria-labelledby={`${id}-step2`}>
            <h3 id={`${id}-step2`}><span className="letter-step-number">2</span> Angaben</h3>
            <form className="letters-grid" onSubmit={event => { event.preventDefault(); void compose(true); }}>
              {kind.inputs.map(field => <InputField key={field.key} id={`${id}-input-${field.key}`} field={field} value={inputs[field.key]} onChange={value => changeInput(field.key, value)} />)}
              <div className="letters-actions letters-field-wide"><button type="submit" className="btn btn-primary" disabled={Boolean(busy)}>{busy === 'compose' ? 'Text wird erstellt …' : form ? 'Text neu erstellen' : 'Text erstellen'}</button>
                {form && <small>{stale ? 'Die Angaben wurden geändert: bitte den Text neu erstellen.' : 'Neu erstellen ersetzt Ihre Änderungen am Text.'}</small>}</div>
            </form>
          </section>}
          {form && <section className="contract-letter-step" aria-labelledby={`${id}-step3`}>
            <h3 id={`${id}-step3`}><span className="letter-step-number">{kind?.inputs?.length ? 3 : 2}</span> Text und Vorschau</h3>
            <Checks checks={checks} />
            <div className="contract-letter-columns">
              <form className="letters-grid" onSubmit={makePreview}>
                <fieldset className="letters-grid letters-field-wide" disabled={busy === 'publish' || Boolean(pending.current)}>
                  <legend className="sr-only">Brieftext</legend>
                  {TEXT_FIELDS.map(field => <div key={field.key} className={`letters-field${field.wide ? ' letters-field-wide' : ''}`}>
                    <label htmlFor={`${id}-${field.key}`}>{field.label}{field.required ? ' *' : ''}</label>
                    {field.rows ? <textarea id={`${id}-${field.key}`} rows={field.rows} value={form[field.key]} onChange={event => changeField(field.key, event.target.value)} />
                      : <input id={`${id}-${field.key}`} type={field.type || 'text'} required={field.required} value={form[field.key]} onChange={event => changeField(field.key, event.target.value)} />}
                  </div>)}
                </fieldset>
                <p className="letters-hint letters-field-wide">Zeilen wie <code>{'{{tabelle.mieterhoehung}}'}</code> werden im PDF zur Tabelle. „[bitte ergänzen: …]“ muss ausgefüllt oder entfernt werden.</p>
                <div className="letters-actions letters-field-wide"><button type="submit" className="btn btn-secondary" disabled={Boolean(busy) || Boolean(pending.current) || stale}>{busy === 'preview' ? 'PDF wird erstellt …' : 'PDF-Vorschau erstellen'}</button></div>
              </form>
              <section className="contract-letter-preview" aria-label="Briefvorschau">
                <h4>{published ? 'Archiviertes Original' : preview?.review.draft ? 'Entwurf – so nicht archivierbar' : preview ? 'PDF-Vorschau – noch nicht archiviert' : 'PDF-Vorschau'}</h4>
                {preview ? <PdfPreview key={preview.url} url={preview.url} title="Brief" /> : <p className="letters-hint">Nach Änderungen bitte eine neue PDF-Vorschau erstellen.</p>}
              </section>
            </div>
          </section>}
          {published && <div className="letters-notice" role="status"><CheckCircle2 size={16} aria-hidden="true" /> Der Brief ist als Original in den Dokumenten des Vertrags abgelegt. <Link to={entityHref('document', published.document_id)}>Dokument öffnen</Link></div>}
          <section className="contract-letter-history" aria-label="Archivierte Briefe"><h3>Archivierte Briefe zu diesem Vertrag</h3>
            {!context.originals?.length ? <p className="letters-hint">Noch keine.</p> : <ul>{context.originals.map(record => <li key={record.document_id}>
              <span><strong>{record.subject}</strong> · {record.issue_date ? new Date(record.issue_date).toLocaleDateString('de-DE') : ''}</span>
              <Link to={entityHref('document', record.document_id)}>Dokument öffnen</Link>
              <button type="button" className="btn btn-sm btn-secondary" onClick={() => download(record)}>Original herunterladen</button></li>)}</ul>}
          </section>
        </>}
      </div>
      <footer className="contract-letter-footer">
        <button type="button" className="btn btn-secondary" onClick={requestClose}>Schließen</button>
        {uncertain ? <button type="button" className="btn btn-primary" disabled={Boolean(busy)} onClick={publish}>Archivierung erneut prüfen</button>
          : form && <div>
            {!allowed || !context?.can_publish ? <span className="letters-hint">Briefe archivieren Eigentümer und Verwaltung.</span> : <>
              <label className="letters-check"><input type="checkbox" checked={confirmed} disabled={!preview || preview.review.draft || Boolean(busy)} onChange={event => setConfirmed(event.target.checked)} />Ich habe die PDF geprüft und möchte sie als Original ablegen.</label>
              <button type="button" className="btn btn-primary" disabled={!confirmed || !preview || preview.review.draft || Boolean(busy) || Boolean(published)} onClick={publish}>{busy === 'publish' ? 'Wird archiviert …' : 'Als Original archivieren'}</button>
              {preview?.review.draft && <small className="letters-error-text">{errors} Fehler verhindern die Archivierung.</small>}
            </>}
          </div>}
      </footer>
      {leave && <div className="contract-letter-leave" role="alertdialog" aria-modal="true" aria-labelledby={`${id}-leave`}>
        <h3 id={`${id}-leave`}>Brief verwerfen?</h3><p>Der Brief ist noch nicht archiviert. Ihre Änderungen gehen verloren.</p>
        <div className="letters-actions"><button type="button" className="btn btn-secondary" onClick={() => setLeave(false)}>Weiter bearbeiten</button><button type="button" className="btn btn-danger" onClick={onClose}>Verwerfen</button></div>
      </div>}
    </section>
  </div>, document.body);
}
