import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import { usePreferences } from '../../contexts/PreferencesContext';
import { emailClientLink, whatsAppWebLink } from './quickMessages';
import ReminderPlanner from './ReminderPlanner';
import './reminders.css';

export default function QuickMessageComposer({ phone = '', email = '', recipientName = '', subject = '', message = '',
  sourceKind = '', sourceId = '', dueDate = null, onClose }) {
  const id = useId(); const dialog = useRef(null);
  const prefs = usePreferences()?.prefs || {};
  const [channel, setChannel] = useState(prefs.default_message_channel || 'whatsapp_web');
  const [number, setNumber] = useState(phone); const [address, setAddress] = useState(email);
  const [title, setTitle] = useState(subject); const [body, setBody] = useState(message);
  const [planner, setPlanner] = useState(false); const [invalid, setInvalid] = useState(false);
  useModalDialog(dialog, onClose);
  useEffect(() => {
    const invalidate = () => { setNumber(''); setAddress(''); setBody(''); setTitle(''); setPlanner(false); setInvalid(true); };
    window.addEventListener('workspace-owner', invalidate); window.addEventListener('workspace-logout', invalidate);
    return () => { window.removeEventListener('workspace-owner', invalidate); window.removeEventListener('workspace-logout', invalidate); };
  }, []);
  const href = invalid ? '' : channel === 'whatsapp_web' ? whatsAppWebLink(number, body) : emailClientLink(address, title, body);
  return createPortal(<div className="modal-overlay"><div className="modal message-quick-dialog" ref={dialog} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} tabIndex={-1}>
    <div className="modal-header"><h3 id={`${id}-title`}>Nachricht vorbereiten{!invalid && recipientName ? `: ${recipientName}` : ''}</h3><button className="btn-close" type="button" aria-label="Schließen" onClick={onClose}>×</button></div>
    <div className="modal-body reminder-form">
      {invalid ? <p role="alert">Die Sitzung wurde geändert. Bitte dieses Fenster schließen und erneut anmelden.</p> : <>
        <label>Nachrichtenweg<select value={channel} onChange={event => setChannel(event.target.value)}><option value="whatsapp_web">WhatsApp Web</option><option value="email_draft">E-Mail-Programm</option></select></label>
        {channel === 'whatsapp_web' ? <><label>Mobilnummer mit Vorwahl<input type="tel" value={number} onChange={event => setNumber(event.target.value)} placeholder="+49 170 1234567" /></label>
          <p>WhatsApp öffnet sich im Browser mit dem gewählten Chat und dem vorbereiteten Text. Dort melden Sie sich bei Bedarf an und senden die Nachricht.</p>
          <a href="https://web.whatsapp.com/" target="_blank" rel="noopener noreferrer">WhatsApp Web öffnen / anmelden</a></> : <>
          <label>E-Mail-Adresse<input type="email" value={address} onChange={event => setAddress(event.target.value)} /></label>
          <label>Betreff<input maxLength={200} value={title} onChange={event => setTitle(event.target.value)} /></label>
          <p>Ihr E-Mail-Programm öffnet einen Entwurf. Die Nachricht senden Sie anschließend dort.</p></>}
        <label>Nachricht<textarea rows={7} maxLength={2000} value={body} onChange={event => setBody(event.target.value)} /></label>
        {!href && <p className="text-muted">{body.length > 2000 ? 'Die Nachricht darf höchstens 2.000 Zeichen enthalten.' : title.length > 200 || /[\r\n\0]/.test(title) ? 'Der Betreff darf höchstens 200 Zeichen und keine Zeilenumbrüche enthalten.' : 'Bitte einen gültigen Empfänger angeben.'}</p>}
        {href && <a className="btn btn-primary" href={href} target={channel === 'whatsapp_web' ? '_blank' : undefined} rel="noopener noreferrer">{channel === 'whatsapp_web' ? 'WhatsApp-Chat mit Text öffnen' : 'E-Mail-Entwurf öffnen'}</a>}
        <p className="text-muted">Vorgaben und Erinnerungen: <Link to="/settings?section=notifications" onClick={onClose}>Nachrichten und Erinnerungen einstellen</Link></p>
      </>}
    </div><div className="modal-footer">{sourceKind && sourceId && !invalid && <button type="button" className="btn btn-secondary" onClick={() => setPlanner(true)}>Für diesen Vorgang erinnern</button>}<button type="button" className="btn btn-secondary" onClick={onClose}>Schließen</button></div>
    {planner && !invalid && <ReminderPlanner sourceKind={sourceKind} sourceId={sourceId} sourceTitle={subject} dueDate={dueDate} onClose={() => setPlanner(false)} />}
  </div></div>, document.body);
}
