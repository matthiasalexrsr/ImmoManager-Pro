import { useState, useEffect, useMemo } from 'react';
import { api } from '../api';
import { useEntities } from '../contexts/DataStoreContext';
import StatusBadge from '../components/StatusBadge';
import { useTranslation } from '../i18n';
import FormModal from '../components/FormModal';

export default function Messages() {
  const [threads, setThreads] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [selectedThread, setSelectedThread] = useState(null);
  const [threadMessages, setThreadMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const { t } = useTranslation();
  const [view, setView] = useState('notifications');
  const [selected, setSelected] = useState(null);
  const [filter, setFilter] = useState('all');
  const [modal, setModal] = useState(null);
  const [newMessage, setNewMessage] = useState('');
  const [contacts, setContacts] = useState([]);
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');
  const { items: contracts } = useEntities('contracts', '/contracts');

  useEffect(() => {
    api.get('/contacts').then(c => setContacts(c || [])).catch(() => []);
  }, []);

  useEffect(() => {
    Promise.all([
      api.get('/notifications').catch(() => []),
      api.get('/messages/threads').catch(() => []),
    ]).then(([notifs, thr]) => {
      setNotifications(notifs || []);
      setThreads(thr || []);
    }).finally(() => setLoading(false));
  }, []);

  const markRead = async (id) => {
    await api.patch(`/notifications/${id}`, { status: 'read' }).catch(err => console.warn('[Messages] mark read:', err.message));
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, status: 'read' } : n));
  };

  const loadThreadMessages = async (thread) => {
    setSelectedThread(thread);
    const msgs = await api.get(`/messages/threads/${thread.id}/messages`).catch(() => []);
    setThreadMessages(msgs || []);
  };

  const handleSendMessage = async () => {
    if (!newMessage.trim() || !selectedThread) return;
    setError(null);
    try {
      await api.post(`/messages/threads/${selectedThread.id}/messages`, {
        thread_id: selectedThread.id,
        sender_name: 'Ich',
        body: newMessage,
      });
      setNewMessage('');
      loadThreadMessages(selectedThread);
      const thr = await api.get('/messages/threads').catch(() => []);
      setThreads(thr || []);
    } catch (err) {
      setError(err.message || 'Nachricht konnte nicht gesendet werden');
    }
  };

  const handleCreateThread = async (data) => {
    const thread = await api.post('/messages/threads', data);
    const thr = await api.get('/messages/threads').catch(() => []);
    setThreads(thr || []);
    if (thread) {
      loadThreadMessages(thread);
      setView('threads');
    }
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

  if (loading) return <div className="page-loading">{t('pages.loading')}</div>;

  return (
    <div className="page">
      <h1 className="page-title">{t('pages.messages.title')}</h1>

      {error && (
        <div className="alert alert-danger" style={{ marginBottom: '1rem', padding: '0.75rem', background: 'var(--color-error-bg, #fef2f2)', border: '1px solid var(--color-error, #dc2626)', borderRadius: '6px', color: 'var(--color-error, #dc2626)' }}>
          {error}
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
              <button className={`btn btn-sm ${filter === 'all' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setFilter('all')}>
                Alle ({notifications.length})
              </button>
              <button className={`btn btn-sm ${filter === 'unread' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setFilter('unread')}>
                Ungelesen ({unreadCount})
              </button>
              <button className={`btn btn-sm ${filter === 'error' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setFilter('error')}>
                Fehler
              </button>
              <button className={`btn btn-sm ${filter === 'warning' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setFilter('warning')}>
                Warnungen
              </button>
            </div>
            <div className="messages-list">
              {filteredNotifs.length === 0 ? (
                <p className="panel-empty">{t('pages.messages.noMessages')}</p>
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
              <button className="btn btn-sm btn-primary" onClick={() => setModal('create')}>
                + {t('pages.messages.newConversation') || 'Neue Konversation'}
              </button>
            </div>
            <div className="messages-list">
              {threads.length === 0 ? (
                <p className="panel-empty">{t('pages.messages.noConversations') || 'Keine Konversationen'}</p>
              ) : threads.map(thr => (
                <div
                  key={thr.id}
                  className={`message-item ${selectedThread?.id === thr.id ? 'active' : ''}`}
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
                <div className="thread-messages">
                  {threadMessages.length === 0 ? (
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
                <div className="thread-composer">
                  <textarea
                    value={newMessage}
                    onChange={e => setNewMessage(e.target.value)}
                    placeholder={t('pages.messages.writePlaceholder') || 'Nachricht schreiben...'}
                    rows={3}
                    onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) handleSendMessage(); }}
                  />
                  <button className="btn btn-primary" onClick={handleSendMessage} disabled={!newMessage.trim()}>
                    {t('pages.messages.send') || 'Senden'}
                  </button>
                </div>
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
