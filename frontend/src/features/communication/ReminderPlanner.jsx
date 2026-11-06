import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../../api';
import { useAuth } from '../../contexts/AuthContext';
import { usePreferences } from '../../contexts/PreferencesContext';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import { berlinLocal, normalizedChatNumber, reminderDefault, reminderDate } from './quickMessages';
import './reminders.css';

export default function ReminderPlanner({ sourceKind, sourceId, sourceTitle = '', dueDate = null, plan = null, onSaved, onClose }) {
  const prefs = usePreferences()?.prefs || {}; const user = useAuth()?.user;
  const editing = Boolean(plan);
  const id = useId(); const dialog = useRef(null); const pending = useRef(null); const writing = useRef(false);
  const current = useRef(true);
  const [when, setWhen] = useState(() => editing ? berlinLocal(new Date(plan.due_at)) : reminderDefault(dueDate, prefs.reminder_days, prefs.reminder_time));
  const [channel, setChannel] = useState(prefs.reminder_channel || 'in_app');
  const [recipient, setRecipient] = useState(prefs.reminder_channel === 'whatsapp_web' ? prefs.reminder_phone || '' : user?.email || '');
  const [message, setMessage] = useState(sourceTitle ? `Erinnerung: ${sourceTitle}` : '');
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [saved, setSaved] = useState(null); const [invalid, setInvalid] = useState(false);
  useModalDialog(dialog, onClose);
  useEffect(() => {
    current.current = true;
    const invalidate = () => { current.current = false; setInvalid(true); setWhen(''); setRecipient(''); setMessage(''); setSaved(null); setError(''); pending.current = null; };
    window.addEventListener('workspace-owner', invalidate); window.addEventListener('workspace-logout', invalidate);
    return () => { current.current = false; window.removeEventListener('workspace-owner', invalidate); window.removeEventListener('workspace-logout', invalidate); };
  }, []);
  const save = async event => {
    event.preventDefault(); if (writing.current || invalid) return; writing.current = true; setBusy(true); setError('');
    try {
      if (editing && (!plan.id || !Number.isSafeInteger(plan.revision) || plan.revision < 1)) throw new Error('Die gespeicherte Erinnerung ist unvollständig. Bitte neu laden.');
      const endpoint = editing ? `/notifications/reminders/${encodeURIComponent(plan.id)}/command` : '/notifications/reminders';
      const data = editing ? { action: 'reschedule', base_revision: plan.revision, local_due_at: when }
        : { source_kind: sourceKind, source_id: sourceId, local_due_at: when, channel,
          recipient: channel === 'in_app' ? '' : channel === 'whatsapp_web' ? '+' + normalizedChatNumber(recipient) : recipient.trim(), message };
      const identity = JSON.stringify([endpoint, data]);
      if (pending.current?.identity !== identity) pending.current = { identity, body: { ...data, idempotency_key: crypto.randomUUID() } };
      const same = api.captureSession(); const result = await api.post(endpoint, pending.current.body); same();
      if (current.current) { setSaved(result); onSaved?.(result); window.dispatchEvent(new Event('reminder-change')); }
    } catch (failure) { if (current.current && failure.code !== 'SESSION_CHANGED') setError(failure.message || 'Erinnerung nicht bestätigt. Denselben Befehl erneut versuchen.'); }
    finally { writing.current = false; if (current.current) setBusy(false); }
  };
  return createPortal(<div className="modal-overlay"><div ref={dialog} className="modal message-quick-dialog" role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} tabIndex={-1}>
    <div className="modal-header"><h3 id={`${id}-title`}>{editing ? 'Erinnerungszeitpunkt ändern' : 'Erinnerung planen'}</h3><button type="button" className="btn-close" aria-label="Schließen" onClick={onClose}>×</button></div>
    <div className="modal-body">{!invalid && <p><strong>{sourceTitle}</strong></p>}{invalid ? <p role="alert">Die Sitzung wurde geändert. Bitte das Fenster schließen.</p> : saved ? <p role="status">Erinnerung gespeichert: {reminderDate(saved.due_at)} (Europe/Berlin).</p> : <form id={`${id}-form`} className="reminder-form" onSubmit={save}>
      <label>Datum und Uhrzeit (Europe/Berlin)<input type="datetime-local" required disabled={busy} value={when} onChange={event => setWhen(event.target.value)} /></label>
      {editing ? <p>Sie ändern nur den Zeitpunkt. Erinnerungsweg, Empfänger und Erinnerungstext bleiben gespeichert.</p> : <><label>Erinnerungsweg<select disabled={busy} value={channel} onChange={event => { setChannel(event.target.value); setRecipient(event.target.value === 'whatsapp_web' ? prefs.reminder_phone || '' : user?.email || ''); }}><option value="in_app">In der Anwendung</option><option value="email_draft">E-Mail-Entwurf</option><option value="whatsapp_web">WhatsApp-Web-Chat</option></select></label>
      {channel !== 'in_app' && <label>Empfänger der Erinnerung<input disabled={busy} type={channel === 'email_draft' ? 'email' : 'tel'} required value={recipient} onChange={event => setRecipient(event.target.value)} placeholder={channel === 'whatsapp_web' ? '+49 170 1234567' : ''} /></label>}
      <label>Erinnerungstext<textarea disabled={busy} rows={4} maxLength={2000} value={message} onChange={event => setMessage(event.target.value)} /></label></>}
      <p>Die Erinnerung erscheint zum gewählten Zeitpunkt in ImmoManager. E-Mail und WhatsApp öffnen dann einen vorbereiteten Entwurf, den Sie selbst senden. Persönliche Ruhezeiten werden berücksichtigt.</p>
      {prefs.reminders_enabled === false && <p role="status">Persönliche Erinnerungen sind in Ihren Einstellungen pausiert. Der Plan wird gespeichert und nach dem Einschalten wieder berücksichtigt.</p>}
    </form>}{error && <p role="alert">{error}</p>}</div>
    <div className="modal-footer">{!saved && !invalid && <button type="submit" form={`${id}-form`} className="btn btn-primary" disabled={busy}>{busy ? 'Speichern …' : editing ? 'Zeitpunkt speichern' : 'Erinnerung speichern'}</button>}<button type="button" className="btn btn-secondary" onClick={onClose}>{saved ? 'Fertig' : 'Schließen'}</button></div>
  </div></div>, document.body);
}
