import { useState, useEffect, useMemo, useCallback } from 'react';
import { api } from '../api';
import { useEntities } from '../contexts/DataStoreContext';
import StatusBadge from '../components/StatusBadge';
import { useTranslation } from '../i18n';
import FormModal from '../components/FormModal';
import { useSearchParams } from 'react-router-dom';
import useMessageConversation from '../hooks/useMessageConversation';
import './messages.css';
import { useCanWrite } from '../contexts/AuthContext';

export default function Messages() {
  const [params, setParams] = useSearchParams();
  const [threads, setThreads] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const recordThread = useCallback(thread => {
    setThreads(current => current.map(item => item.id === thread.id ? thread : item));
  }, []);
  const conversation = useMessageConversation(recordThread);
  const { selectedThread, page: threadPage, draft: newMessage, notice } = conversation;
  const threadMessages = threadPage.items;
  const canWrite = useCanWrite('/messages');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const { t } = useTranslation();
  const [view, setView] = useState('notifications');
  const [selected, setSelected] = useState(null);
  const [filter, setFilter] = useState(() => params.get('status') === 'unread' ? 'unread' : params.get('severity') || 'all');
  const [notificationReady, setNotificationReady] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const linkedStatus = params.get('status') || params.get('severity');
  useEffect(() => { setFilter(['unread', 'error', 'warning', 'info'].includes(linkedStatus) ? linkedStatus : 'all'); if (linkedStatus) setView('notifications'); }, [linkedStatus]);
  const chooseFilter = value => { setFilter(value); setParams(current => { const next = new URLSearchParams(current);
    next.delete('status'); next.delete('severity');
    if (value === 'unread') next.set('status', 'unread'); else if (value !== 'all') next.set('severity', value); return next; }); };
  const [modal, setModal] = useState(null);
  const setNewMessage = conversation.setDraft;
  const [contacts, setContacts] = useState([]);
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');
  const { items: contracts } = useEntities('contracts', '/contracts');

  useEffect(() => {
    const request = new AbortController();
    const sameSession = api.captureSession();
    const invalidate = () => request.abort();
    window.addEventListener('workspace-logout', invalidate);
    window.addEventListener('workspace-owner', invalidate);
    api.list('/contacts', { signal: request.signal }).then(values => {
      if (request.signal.aborted) return;
      sameSession();
      if (!Array.isArray(values)) throw new Error('Die Kontaktliste ist unvollständig.');
      setContacts(values);
    }).catch(failure => { if (!request.signal.aborted && failure.code !== 'SESSION_CHANGED') setError(failure.message || 'Kontakte konnten nicht geladen werden.'); });
    return () => { request.abort(); window.removeEventListener('workspace-logout', invalidate); window.removeEventListener('workspace-owner', invalidate); };
  }, []);

  useEffect(() => {
    const request = new AbortController(); setLoading(true); setError(null);
    const sameSession = api.captureSession();
    const invalidate = () => {
      request.abort(); setThreads([]); setNotifications([]); setContacts([]); setSelected(null); setModal(null);
      setLoading(false); setNotificationReady(false); setError('Die Sitzung wurde geändert. Bitte erneut anmelden.');
    };
    window.addEventListener('workspace-logout', invalidate);
    window.addEventListener('workspace-owner', invalidate);
    Promise.allSettled([api.list('/notifications', { signal: request.signal }), api.list('/messages/threads', { signal: request.signal })])
      .then(([notifs, thr]) => {
        if (request.signal.aborted) return;
        try { sameSession(); } catch { invalidate(); return; }
        const failures = [];
        if (notifs.status === 'fulfilled' && Array.isArray(notifs.value)) { setNotifications(notifs.value); setNotificationReady(true); }
        else { setNotificationReady(false); failures.push(notifs.reason?.message || 'Hinweise konnten nicht gelesen werden.'); }
        if (thr.status === 'fulfilled' && Array.isArray(thr.value)) setThreads(thr.value);
        else failures.push(thr.reason?.message || 'Konversationen konnten nicht gelesen werden.');
        if (failures.length) setError(failures.join(' · '));
      }).finally(() => { if (!request.signal.aborted) setLoading(false); });
    return () => { request.abort(); window.removeEventListener('workspace-logout', invalidate); window.removeEventListener('workspace-owner', invalidate); };
  }, [attempt]);

  const markRead = async (id) => {
    try { await api.patch(`/notifications/${id}`, { status: 'read' });
      setNotifications(prev => prev.map(n => n.id === id ? { ...n, status: 'read' } : n));
    } catch (failure) { setError(failure.message || 'Der Hinweis konnte nicht als gelesen markiert werden.'); }
  };

  const loadThreadMessages = conversation.selectThread;
  const handleSendMessage = () => conversation.send();

  const handleCreateThread = async (data) => {
    const sameSession = api.captureSession();
    const thread = await api.post('/messages/threads', data);
    sameSession();
    if (!thread?.id) throw new Error('Die neue Konversation wurde nicht bestätigt.');
    setThreads(current => [thread, ...current.filter(item => item.id !== thread.id)]);
    loadThreadMessages(thread);
    setView('threads');
  };

  const threadFields = [
    { key: 'subject', label: t('pages.messages.subject') || 'Betreff', required: true },
    { key: 'participant_ids', label: t('pages.messages.participants') || 'Teilnehmer', type: 'select',
      options: contacts.map(c => ({ value: c.id, label: c.name || c.email || c.id })) },
  ];

  // Entity lookup maps for references
  const propMap = useMemo(() => Object.fromEntries(properties.map(p => [p.id, p.name])), [properties]);
  const unitMap = useMemo(() => Object.fromEntries(units.map(u => [u.id, u.label])), [units]);
  const contractMap = useMemo(() => Object.fromEntries(contracts.map(c => [c.id, c.contract_number])), [contracts]);

  // Helper to resolve entity reference from a notification
  const resolveEntityRef = (n) => {
    if (n.entity_type === 'property' && n.entity_id) return propMap[n.entity_id];
    if (n.entity_type === 'unit' && n.entity_id) return unitMap[n.entity_id];
    if (n.entity_type === 'contract' && n.entity_id) return contractMap[n.entity_id];
    return null;
  };

  // Thread entity references
  const resolveThreadRef = (thr) => {
    const parts = [];
    if (thr.property_id && propMap[thr.property_id]) parts.push(propMap[thr.property_id]);
    if (thr.unit_id && unitMap[thr.unit_id]) parts.push(unitMap[thr.unit_id]);
    if (thr.contract_id && contractMap[thr.contract_id]) parts.push(contractMap[thr.contract_id]);
    return parts.length > 0 ? parts.join(' / ') : null;
  };

  const unreadCount = notifications.filter(n => n.status === 'unread').length;

  const filteredNotifs = useMemo(() => {
    if (filter === 'all') return notifications;
    if (filter === 'unread') return notifications.filter(n => n.status === 'unread');
    // Filter by severity
    return notifications.filter(n => n.severity === filter);
  }, [notifications, filter]);

  if (loading && !modal) return <div className="page-loading">{t('pages.loading')}</div>;

  return (
    <div className="page messages-page">
      <h1 className="page-title">{t('pages.messages.title')}</h1>

      {error && (
        <div role="alert" className="alert alert-danger" style={{ marginBottom: '1rem', padding: '0.75rem', background: 'var(--color-error-bg, #fef2f2)', border: '1px solid var(--color-error, #dc2626)', borderRadius: '6px', color: 'var(--color-error, #dc2626)' }}>
          {error}
          <button type="button" className="btn btn-sm btn-secondary" onClick={() => setAttempt(value => value + 1)}>Erneut laden</button>
          <button className="btn btn-sm" onClick={() => setError(null)} style={{ float: 'right' }}>&times;</button>
        </div>
      )}

      <div className="tab-bar" style={{ marginBottom: '1rem' }}>
        <button
          className={`detail-tab ${view === 'notifications' ? 'active' : ''}`}
          onClick={() => setView('notifications')}
        >
          {t('pages.messages.notifications') || 'Benachrichtigungen'} ({notifications.length})
        </button>
        <button
          className={`detail-tab ${view === 'threads' ? 'active' : ''}`}
          onClick={() => setView('threads')}
        >
          {t('pages.messages.conversations') || 'Konversationen'} ({threads.length})
        </button>
      </div>

      {view === 'notifications' && (
        <div className="messages-layout">
          <div className="messages-sidebar">
            <div className="messages-filters" style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem' }}>
              <button className={`btn btn-sm ${filter === 'all' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => chooseFilter('all')}>
                Alle ({notifications.length})
              </button>
              <button className={`btn btn-sm ${filter === 'unread' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => chooseFilter('unread')}>
                Ungelesen ({unreadCount})
              </button>
              <button className={`btn btn-sm ${filter === 'error' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => chooseFilter('error')}>
                Fehler
              </button>
              <button className={`btn btn-sm ${filter === 'warning' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => chooseFilter('warning')}>
                Warnungen
              </button>
            </div>
            <div className="messages-list">
              {filteredNotifs.length === 0 ? (
                <p className="panel-empty">{notificationReady ? t('pages.messages.noMessages') : 'Hinweise noch nicht verfügbar.'}</p>
              ) : filteredNotifs.map(n => (
                <div
                  key={n.id}
                  className={`message-item ${n.status === 'unread' ? 'unread' : ''} ${selected?.id === n.id ? 'active' : ''}`}
                  onClick={() => { setSelected(n); if (n.status === 'unread') markRead(n.id); }}
                >
                  <div className="message-item-header">
                    <span className="message-item-title">{n.title}</span>
                    <StatusBadge status={n.severity} />
                  </div>
                  <div className="message-item-preview">
                    {(n.content || '').slice(0, 80)}{(n.content || '').length > 80 ? '...' : ''}
                  </div>
                  {resolveEntityRef(n) && (
                    <div className="text-muted" style={{ fontSize: '0.7rem', marginTop: '2px' }}>
                      📎 {resolveEntityRef(n)}
                    </div>
                  )}
                  <div className="message-item-date">{n.created_at?.slice(0, 10)}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="message-detail">
            {selected ? (
              <>
                <div className="message-detail-header">
                  <h2>{selected.title}</h2>
                  <StatusBadge status={selected.severity} />
                </div>
                <div className="message-detail-meta">
                  {selected.notification_type && <span>{t('pages.messages.type')}: {selected.notification_type}</span>}
                  {selected.created_at && <span>{selected.created_at.slice(0, 10)}</span>}
                </div>
                <div className="message-detail-body">
                  {selected.content || t('pages.messages.noContent')}
                </div>
              </>
            ) : (
              <div className="message-detail-empty">
                {t('pages.messages.selectMessage')}
              </div>
            )}
          </div>
        </div>
      )}

      {view === 'threads' && (
        <div className="messages-layout">
          <div className="messages-sidebar">
            <div className="messages-filters">
              {canWrite && <button className="btn btn-sm btn-primary" onClick={() => setModal('create')}>
                + {t('pages.messages.newConversation') || 'Neue Konversation'}
              </button>}
            </div>
            <div className="messages-list">
              {threads.length === 0 ? (
                <p className="panel-empty">{t('pages.messages.noConversations') || 'Keine Konversationen'}</p>
              ) : threads.map(thr => (
                <div
                  key={thr.id}
                  className={`message-item ${selectedThread?.id === thr.id ? 'active' : ''}`}
                  role="button" tabIndex={0}
                  aria-pressed={selectedThread?.id === thr.id}
                  onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); loadThreadMessages(thr); } }}
                  onClick={() => loadThreadMessages(thr)}
                >
                  <div className="message-item-header">
                    <span className="message-item-title">{thr.subject}</span>
                    <span className="text-muted" style={{ fontSize: '0.75rem' }}>
                      {thr.message_count} {t('pages.messages.messagesCount') || 'Nachrichten'}
                    </span>
                  </div>
                  {resolveThreadRef(thr) && (
                    <div className="text-muted" style={{ fontSize: '0.7rem' }}>
                      📎 {resolveThreadRef(thr)}
                    </div>
                  )}
                  <div className="message-item-date">
                    {thr.last_message_at?.slice(0, 10) || thr.created_at?.slice(0, 10)}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="message-detail">
            {selectedThread ? (
              <>
                <div className="message-detail-header">
                  <h2>{selectedThread.subject}</h2>
                </div>
                <nav className="thread-pagination" aria-label="Nachrichtenseiten">
                  <button type="button" className="btn btn-sm btn-secondary" onClick={conversation.newer} disabled={threadPage.status === 'loading' || !threadPage.history.length}>Neuere Nachrichten</button>
                  <span>Seite {threadPage.number}{threadPage.total !== null ? ` · ${threadPage.total} Nachrichten insgesamt` : ''}</span>
                  <button type="button" className="btn btn-sm btn-secondary" onClick={conversation.older} disabled={threadPage.status === 'loading' || !threadPage.nextCursor}>Ältere Nachrichten</button>
                  <button type="button" className="btn btn-sm btn-secondary" onClick={conversation.refresh} disabled={threadPage.status === 'loading'}>Aktualisieren</button>
                </nav>
                {threadPage.status === 'loading' && <p role="status">Nachrichten werden geladen …</p>}
                {threadPage.error && <div role="alert" className="alert alert-danger">{threadPage.error}
                  <button type="button" className="btn btn-sm btn-secondary" onClick={conversation.retryRead}>Nachrichten erneut laden</button>
                </div>}
                {notice.error && <div role="alert" className="alert alert-danger">{notice.error}
                  {notice.uncertain && <><p>Die Speicherung ist unbestätigt. Der ursprüngliche Vorgang wird mit derselben Kennung abgeglichen, nicht als neue Nachricht gesendet.</p>
                    <button type="button" className="btn btn-sm btn-secondary" disabled={notice.sending} onClick={() => conversation.send({ retry: true })}>Speicherung abgleichen</button></>}
                </div>}
                <div className="thread-messages" aria-busy={threadPage.status === 'loading'}>
                  {threadPage.status === 'ready' && threadMessages.length === 0 ? (
                    <p className="empty-text" style={{ padding: '1rem' }}>{t('pages.messages.noThreadMessages') || 'Noch keine Nachrichten in diesem Thread'}</p>
                  ) : threadMessages.map(m => (
                    <div key={m.id} className="thread-message">
                      <div className="thread-message-header">
                        <strong>{m.sender_name}</strong>
                        <span className="text-muted">{m.sent_at?.slice(0, 16).replace('T', ' ')}</span>
                      </div>
                      <div className="thread-message-body">{m.body}</div>
                    </div>
                  ))}
                </div>
                {canWrite && <div className="thread-composer">
                  <label htmlFor="thread-reply">Antwort an „{selectedThread.subject}“</label>
                  <textarea id="thread-reply"
                    value={newMessage}
                    onChange={e => setNewMessage(e.target.value)}
                    placeholder={t('pages.messages.writePlaceholder') || 'Nachricht schreiben...'}
                    rows={3}
                    onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) handleSendMessage(); }}
                  />
                  <button className="btn btn-primary" onClick={handleSendMessage} disabled={!newMessage.trim() || notice.sending || notice.uncertain}>
                    {notice.sending ? 'Wird gespeichert …' : t('pages.messages.send') || 'Senden'}
                  </button>
                </div>}
              </>
            ) : (
              <div className="message-detail-empty">
                {t('pages.messages.selectOrCreateConversation') || 'Konversation auswählen oder neue erstellen'}
              </div>
            )}
          </div>
        </div>
      )}

      {modal && (
        <FormModal
          title={t('pages.messages.newConversation') || 'Neue Konversation'}
          fields={threadFields}
          initial={null}
          onSave={handleCreateThread}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
