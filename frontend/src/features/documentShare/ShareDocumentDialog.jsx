import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Download, Link2, Mail, MessageCircle, Share2 } from 'lucide-react';
import { api } from '../../api';
import { CloseIcon } from '../../components/Icons';
import { useAuth } from '../../contexts/AuthContext';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import { canShareFiles, currentFile, emailDraft, saveBlob, whatsAppLink, whatsAppNumber } from './documentShare';
import './documentShare.css';

function greeting(name) {
  return name ? `Guten Tag ${name},` : 'Guten Tag,';
}

/** Passing a document on: the system share dialog, an e-mail draft with the file attached, WhatsApp or a
 *  link for colleagues. Nothing is sent from here; the person sends it from the program that opens. */
export default function ShareDocumentDialog({ document: record, partyId, onClose, service = { currentFile, emailDraft } }) {
  const id = useId();
  const dialog = useRef(null);
  const sender = useAuth()?.user?.full_name || '';
  const [recipient, setRecipient] = useState({ name: '', email: '', phone: '' });
  const [subject, setSubject] = useState(record.title || 'Dokument');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const shareable = canShareFiles();
  useModalDialog(dialog, onClose, true);

  useEffect(() => {
    const text = name => `${greeting(name)}\n\nanbei erhalten Sie „${record.title || 'das Dokument'}“.\n\nMit freundlichen Grüßen${sender ? `\n${sender}` : ''}`;
    setMessage(text(''));
    if (!partyId) return undefined;
    const controller = new AbortController();
    api.get(`/tenants/${encodeURIComponent(partyId)}`, { signal: controller.signal }).then(tenant => {
      if (controller.signal.aborted || !tenant) return;
      setRecipient({ name: tenant.full_name || '', email: tenant.email || '', phone: tenant.phone || '' });
      setMessage(text(tenant.full_name || ''));
    }).catch(() => {});                      // without the party the fields stay empty to fill in
    return () => controller.abort();
  }, [partyId, record.title, sender]);

  const run = async (key, task) => {
    if (busy) return;
    setBusy(key); setError(''); setNote('');
    try { await task(); }
    catch (failure) { if (failure?.name !== 'AbortError') setError(failure?.message || 'Das hat nicht geklappt.'); }
    finally { setBusy(''); }
  };
  const file = () => service.currentFile(record.id, record.title);
  const systemShare = () => run('system', async () => {
    const shared = await file();
    try {
      await navigator.share({ files: [shared], title: subject, text: message });
      setNote('An das gewählte Programm übergeben.');
    } catch (failure) {
      if (failure?.name !== 'AbortError') throw failure;          // closed without choosing
    }
  });
  const email = () => run('email', async () => {
    await service.emailDraft(record.id, { to: recipient.email.trim() ? [recipient.email.trim()] : [], subject, body: message });
    setNote('Der E-Mail-Entwurf mit Anhang wurde heruntergeladen. Öffnen Sie die Datei: Sie öffnet sich in Outlook, Thunderbird oder Windows Mail als fertige E-Mail, die Sie dort prüfen und senden.');
  });
  const whatsApp = () => run('whatsapp', async () => {
    const popup = window.open('about:blank', '_blank');      // reserved now, before awaiting the file
    const shared = await file();
    saveBlob(shared, shared.name);
    const link = whatsAppLink(recipient.phone, message);
    if (popup) { popup.opener = null; popup.location.replace(link); } else window.open(link, '_blank', 'noopener');
    setNote(`WhatsApp öffnet sich${whatsAppNumber(recipient.phone) ? ` mit dem Chat von ${recipient.name || recipient.phone}` : ''} und der Nachricht. Die Datei „${shared.name}“ liegt in Ihren Downloads: Ziehen Sie sie in den Chat oder hängen Sie sie über die Büroklammer an.`);
  });
  const copyLink = () => run('link', async () => {
    await navigator.clipboard.writeText(`${window.location.origin}/documents/${encodeURIComponent(record.id)}`);
    setNote('Link zur Dokumentseite kopiert. Er öffnet das Dokument für Kolleginnen und Kollegen mit Zugang zu ImmoManager.');
  });
  const download = () => run('download', async () => { const shared = await file(); saveBlob(shared, shared.name); });
  const phoneProblem = recipient.phone.trim() && !whatsAppNumber(recipient.phone);

  return createPortal(
    <div className="modal-overlay" role="presentation" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={dialog} className="modal share-dialog" role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} tabIndex={-1}>
        <div className="modal-header">
          <h3 id={`${id}-title`}>Teilen: {record.title}</h3>
          <button type="button" className="btn-close" aria-label="Schließen" onClick={onClose}><CloseIcon size={18} /></button>
        </div>
        <div className="modal-body share-dialog-body">
          <fieldset className="share-recipient">
            <legend>Empfänger</legend>
            <label>Name<input value={recipient.name} onChange={event => setRecipient(current => ({ ...current, name: event.target.value }))} /></label>
            <label>E-Mail<input type="email" value={recipient.email} placeholder="name@beispiel.de"
              onChange={event => setRecipient(current => ({ ...current, email: event.target.value }))} /></label>
            <label>Mobilnummer<input type="tel" value={recipient.phone} placeholder="0170 1234567"
              onChange={event => setRecipient(current => ({ ...current, phone: event.target.value }))}
              aria-invalid={phoneProblem || undefined} />
              {phoneProblem && <small className="text-red">Diese Nummer erkennt WhatsApp nicht; bitte mit Vorwahl angeben.</small>}</label>
            <label className="share-wide">Betreff<input value={subject} onChange={event => setSubject(event.target.value)} /></label>
            <label className="share-wide">Nachricht<textarea rows={6} value={message} onChange={event => setMessage(event.target.value)} /></label>
          </fieldset>
          <div className="share-options" role="group" aria-label="Weg wählen">
            <button type="button" className="share-option" onClick={email} disabled={Boolean(busy)}>
              <Mail size={20} aria-hidden="true" /><span><strong>E-Mail mit Anhang</strong>
                <small>Fertiger Entwurf für Outlook, Thunderbird oder Windows Mail</small></span></button>
            <button type="button" className="share-option" onClick={whatsApp} disabled={Boolean(busy)}>
              <MessageCircle size={20} aria-hidden="true" /><span><strong>WhatsApp</strong>
                <small>{whatsAppNumber(recipient.phone) ? 'Chat mit der Mobilnummer öffnen, Datei anhängen' : 'WhatsApp öffnen, Kontakt wählen, Datei anhängen'}</small></span></button>
            {shareable && <button type="button" className="share-option" onClick={systemShare} disabled={Boolean(busy)}>
              <Share2 size={20} aria-hidden="true" /><span><strong>Mit Windows teilen …</strong>
                <small>Datei direkt an WhatsApp, Outlook, Teams oder ein anderes Programm geben</small></span></button>}
            <button type="button" className="share-option" onClick={copyLink} disabled={Boolean(busy)}>
              <Link2 size={20} aria-hidden="true" /><span><strong>Link für Kollegen kopieren</strong>
                <small>Öffnet die Dokumentseite in ImmoManager</small></span></button>
            <button type="button" className="share-option" onClick={download} disabled={Boolean(busy)}>
              <Download size={20} aria-hidden="true" /><span><strong>Herunterladen</strong>
                <small>Datei speichern, um sie selbst weiterzugeben</small></span></button>
          </div>
          <p className="share-status" role="status">{busy ? 'Einen Moment …' : note}</p>
          {error && <p role="alert" className="alert alert-error">{error}</p>}
          <p className="text-muted share-hint">Personenbezogene Unterlagen nur an Berechtigte weitergeben. E-Mail-Entwürfe werden mit Empfänger im Änderungsprotokoll vermerkt.</p>
        </div>
        <div className="modal-footer"><button type="button" className="btn btn-secondary" onClick={onClose}>Schließen</button></div>
      </div>
    </div>, globalThis.document.body);
}
