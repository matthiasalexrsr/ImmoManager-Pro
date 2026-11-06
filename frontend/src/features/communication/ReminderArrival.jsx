import { useState } from 'react';
import { Link } from 'react-router-dom';
import { safeInternalHref } from '../../utils/internalLinks';
import { emailClientLink, reminderDate, whatsAppWebLink } from './quickMessages';
import useReminders from './useReminders';
import './reminders.css';

export function ReminderDraftLink({ row }) {
  const source = safeInternalHref(row.source?.href);
  const message = row.message || `Erinnerung: ${row.source?.title || ''}`;
  const withSource = `${message}${source ? `\n\n${new URL(source, window.location.origin).href}` : ''}`;
  // Keep every character the user saved; the source remains linked in ImmoManager.
  const text = withSource.length <= 2000 ? withSource : message;
  const subject = (row.source?.title || 'Erinnerung').replace(/[\r\n\0]/g, ' ').slice(0, 200);
  const href = row.channel === 'whatsapp_web' ? whatsAppWebLink(row.recipient, text) : row.channel === 'email_draft' ? emailClientLink(row.recipient, subject, text) : '';
  return href ? <a className="btn btn-sm btn-primary" href={href} target={row.channel === 'whatsapp_web' ? '_blank' : undefined} rel="noopener noreferrer">{row.channel === 'whatsapp_web' ? 'WhatsApp-Entwurf öffnen' : 'E-Mail-Entwurf öffnen'}</a> : null;
}

export default function ReminderArrival() {
  const { page, error, busy, change } = useReminders('due'); const [hidden, setHidden] = useState(() => new Set());
  const row = page?.items.find(item => item.source && !item.delivery_paused && !hidden.has(`${item.id}:${item.due_at}`));
  if (!row) return null;
  const href = safeInternalHref(row.source.href);
  return <aside className="reminder-arrival" aria-label="Fällige Erinnerung" role="status">
    <strong>Erinnerung · {reminderDate(row.due_at)}</strong>
    <p>{href ? <Link to={href}>{row.source.title}</Link> : row.source.title}</p>
    {row.message && <p>{row.message}</p>}
    {error && <p role="alert">{error}</p>}
    <div className="reminder-actions"><ReminderDraftLink row={row} /><button type="button" className="btn btn-sm btn-secondary" disabled={busy} onClick={() => change(row, 'done')}>Erinnerung erledigt</button>
      <button type="button" className="btn btn-sm btn-secondary" onClick={() => setHidden(previous => new Set([...previous, `${row.id}:${row.due_at}`]))}>Später ansehen</button></div>
    <p><Link to="/settings?section=notifications">Alle Erinnerungen</Link></p>
  </aside>;
}
