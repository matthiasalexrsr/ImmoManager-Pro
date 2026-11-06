import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { SettingField } from './SettingsCatalogue';
import { safeInternalHref } from '../../utils/internalLinks';
import { ReminderDraftLink } from '../../features/communication/ReminderArrival';
import QuickMessageComposer from '../../features/communication/QuickMessageComposer';
import ReminderPlanner from '../../features/communication/ReminderPlanner';
import { reminderDate } from '../../features/communication/quickMessages';
import useReminders from '../../features/communication/useReminders';
import { useAuth } from '../../contexts/AuthContext';

const STATUS = { scheduled: 'Geplant', due: 'Fällig', done: 'Erledigt', cancelled: 'Entfernt', blocked: 'Quelle nicht zugänglich' };

export default function MessagingSection() {
  const owner = useAuth()?.user?.id;
  const [items, setItems] = useState(null); const [error, setError] = useState(''); const [attempt, setAttempt] = useState(0); const [composer, setComposer] = useState(false);
  const [editor, setEditor] = useState(null);
  const visibleItems = items?.owner === owner ? items.values : null;
  const [view, setView] = useState('active'); const { page, error: planError, busy, change, offset, setOffset } = useReminders(view);
  useEffect(() => {
    let live = true; const controller = new AbortController();
    const invalidate = () => { live = false; controller.abort(); setItems(null); setComposer(false); setEditor(null); setError('Die Sitzung wurde geändert. Bitte erneut laden.'); };
    window.addEventListener('workspace-owner', invalidate); window.addEventListener('workspace-logout', invalidate);
    (async () => {
      const same = api.captureSession();
      const result = await api.get('/auth/users/me/settings', { signal: controller.signal });
      same(); if (!live) return;
      if (!Array.isArray(result?.items)) throw new Error('Nachrichteneinstellungen wurden nicht vollständig geladen.');
      setItems({ owner, values: result.items.filter(item => item.scope === 'personal' && item.group === 'Benachrichtigungen') }); setError('');
    })().catch(failure => { if (live && failure.name !== 'AbortError') { setItems(null); setError(failure.message); } });
    return () => { live = false; controller.abort(); window.removeEventListener('workspace-owner', invalidate); window.removeEventListener('workspace-logout', invalidate); };
  }, [attempt, owner]);
  return <section className="panel messaging-settings" aria-label="Nachrichten und Erinnerungen"><div className="panel-header">Nachrichten und Erinnerungen</div><div className="panel-body">
    <p>Wählen Sie Ihre persönlichen Nachrichtenwege, Uhrzeit und Ruhezeiten. Erinnerungen planen Sie direkt in der Aufgaben- oder Vertragsübersicht.</p>
    <div className="reminder-actions"><button type="button" className="btn btn-primary" onClick={() => setComposer(true)}>Nachricht vorbereiten</button><a className="btn btn-secondary" href="https://web.whatsapp.com/" target="_blank" rel="noopener noreferrer">WhatsApp Web öffnen / anmelden</a></div>
    <p>WhatsApp Web und Ihr E-Mail-Programm öffnen vorbereitete Entwürfe zum manuellen Versand. Für den Versand über eine eingerichtete SMTP- oder WhatsApp-Business-Verbindung nutzen Sie den <Link to="/messages">Nachrichtenausgang</Link> und die <Link to="/integration-connections">Verbindungseinstellungen</Link>.</p>
    {error && <p role="alert">{error} <button type="button" onClick={() => setAttempt(value => value + 1)}>Erneut laden</button></p>}
    {!visibleItems && !error && <p role="status">Nachrichteneinstellungen werden geladen …</p>}
    {visibleItems && <div className="setting-grid">{visibleItems.map(item => <SettingField key={`${owner}:${item.scope}:${item.key}`} item={item} onSaved={() => setAttempt(value => value + 1)} />)}</div>}
    <h3>Meine Erinnerungen</h3><label>Ansicht <select value={view} onChange={event => setView(event.target.value)}><option value="active">Geplant und fällig</option><option value="due">Jetzt fällig</option><option value="done">Erledigt</option><option value="cancelled">Entfernt</option></select></label>
    {planError && <p role="alert">{planError}</p>}{!page && !planError && <p role="status">Erinnerungen werden geladen …</p>}{page && !page.items.length && <p>Keine Erinnerungen in dieser Ansicht.</p>}
    <ul className="reminder-items">{page?.items.map(row => <li key={row.id}>
      <strong>{safeInternalHref(row.source?.href) ? <Link to={row.source.href}>{row.source.title}</Link> : row.source?.title || 'Quelle nicht mehr zugänglich'}</strong>
      <p>{reminderDate(row.due_at)} · {STATUS[row.status] || row.status}{row.delivery_paused ? ' · Persönlich pausiert / Ruhezeit' : ''}</p>
      {row.message && <p>{row.message}</p>}<div className="reminder-actions">{row.source && ['scheduled', 'due'].includes(row.status) && <ReminderDraftLink row={row} />}
        {safeInternalHref(row.source?.href) && ['scheduled', 'due'].includes(row.status) && <button type="button" className="btn btn-sm btn-secondary" disabled={busy} onClick={() => setEditor({ owner, plan: row })}>Zeitpunkt ändern</button>}
        {!['done', 'cancelled'].includes(row.status) && <><button type="button" className="btn btn-sm btn-secondary" disabled={busy} onClick={() => change(row, 'done')}>Erinnerung erledigt</button><button type="button" className="btn btn-sm btn-secondary" disabled={busy} onClick={() => change(row, 'cancel')}>Erinnerung entfernen</button></>}</div>
    </li>)}</ul>
    {page && <nav className="reminder-actions" aria-label="Erinnerungsseiten">{offset > 0 && <button type="button" onClick={() => setOffset(Math.max(0, offset - 100))}>Zurück</button>}{page.next_offset !== null && page.next_offset !== undefined && <button type="button" onClick={() => setOffset(page.next_offset)}>Weitere Erinnerungen</button>}</nav>}
    <p className="text-muted">Geplante Erinnerungen bleiben beim Neustart erhalten. Sie erscheinen, sobald ImmoManager läuft und die persönliche Ruhezeit beendet ist.</p>
    {composer && <QuickMessageComposer onClose={() => setComposer(false)} />}
    {editor && editor.owner === owner && <ReminderPlanner key={`${owner}:${editor.plan.id}:${editor.plan.revision}`} plan={editor.plan} sourceTitle={editor.plan.source.title} onClose={() => setEditor(null)} />}
  </div></section>;
}
