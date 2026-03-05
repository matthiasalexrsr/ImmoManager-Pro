import { useState, useEffect } from 'react';
import { api } from '../api';
import StatusBadge from '../components/StatusBadge';
import FormModal from '../components/FormModal';

export default function Messages() {
  const [threads, setThreads] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [selectedThread, setSelectedThread] = useState(null);
  const [threadMessages, setThreadMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState('notifications');
  const [selected, setSelected] = useState(null);
  const [filter, setFilter] = useState('all');
  const [modal, setModal] = useState(null);
  const [newMessage, setNewMessage] = useState('');

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
    await api.patch(`/notifications/${id}`, { status: 'read' }).catch(() => {});
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, status: 'read' } : n));
  };

  const loadThreadMessages = async (thread) => {
    setSelectedThread(thread);
    const msgs = await api.get(`/messages/threads/${thread.id}/messages`).catch(() => []);
    setThreadMessages(msgs || []);
  };

  const handleSendMessage = async () => {
    if (!newMessage.trim() || !selectedThread) return;
    await api.post(`/messages/threads/${selectedThread.id}/messages`, {
      thread_id: selectedThread.id,
      sender_name: 'Ich',
      body: newMessage,
    }).catch(() => {});
    setNewMessage('');
    loadThreadMessages(selectedThread);
    const thr = await api.get('/messages/threads').catch(() => []);
    setThreads(thr || []);
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
    { key: 'subject', label: 'Betreff', required: true },
    { key: 'participant_ids', label: 'Teilnehmer (IDs)', placeholder: 'Kommagetrennte Kontakt-IDs' },
  ];

  const filteredNotifs = filter === 'all'
    ? notifications
    : notifications.filter(n => n.status === filter);

  if (loading) return <div className="page-loading">Laden...</div>;

  return (
    <div className="page">
      <h1 className="page-title">Nachrichten</h1>

      <div className="tab-bar" style={{ marginBottom: '1rem' }}>
        <button
          className={`detail-tab ${view === 'notifications' ? 'active' : ''}`}
          onClick={() => setView('notifications')}
        >
          Benachrichtigungen ({notifications.length})
        </button>
        <button
          className={`detail-tab ${view === 'threads' ? 'active' : ''}`}
          onClick={() => setView('threads')}
        >
          Konversationen ({threads.length})
        </button>
      </div>

      {view === 'notifications' && (
        <div className="messages-layout">
          <div className="messages-sidebar">
            <div className="messages-filters">
              <button
                className={`btn btn-sm ${filter === 'all' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setFilter('all')}
              >Alle ({notifications.length})</button>
              <button
                className={`btn btn-sm ${filter === 'unread' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setFilter('unread')}
              >Ungelesen ({notifications.filter(n => n.status === 'unread').length})</button>
            </div>
            <div className="messages-list">
              {filteredNotifs.length === 0 ? (
                <p className="panel-empty">Keine Nachrichten</p>
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
                  {selected.notification_type && <span>Typ: {selected.notification_type}</span>}
                  {selected.created_at && <span>{selected.created_at.slice(0, 10)}</span>}
                </div>
                <div className="message-detail-body">
                  {selected.content || 'Kein Inhalt'}
                </div>
              </>
            ) : (
              <div className="message-detail-empty">
                Nachricht auswählen, um Details anzuzeigen
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
                + Neue Konversation
              </button>
            </div>
            <div className="messages-list">
              {threads.length === 0 ? (
                <p className="panel-empty">Keine Konversationen</p>
              ) : threads.map(t => (
                <div
                  key={t.id}
                  className={`message-item ${selectedThread?.id === t.id ? 'active' : ''}`}
                  onClick={() => loadThreadMessages(t)}
                >
                  <div className="message-item-header">
                    <span className="message-item-title">{t.subject}</span>
                    <span className="text-muted" style={{ fontSize: '0.75rem' }}>
                      {t.message_count} Nachrichten
                    </span>
                  </div>
                  <div className="message-item-date">
                    {t.last_message_at?.slice(0, 10) || t.created_at?.slice(0, 10)}
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
                    <p className="empty-text" style={{ padding: '1rem' }}>Noch keine Nachrichten in diesem Thread</p>
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
                    placeholder="Nachricht schreiben..."
                    rows={3}
                    onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) handleSendMessage(); }}
                  />
                  <button className="btn btn-primary" onClick={handleSendMessage} disabled={!newMessage.trim()}>
                    Senden
                  </button>
                </div>
              </>
            ) : (
              <div className="message-detail-empty">
                Konversation auswählen oder neue erstellen
              </div>
            )}
          </div>
        </div>
      )}

      {modal && (
        <FormModal
          title="Neue Konversation"
          fields={threadFields}
          initial={null}
          onSave={handleCreateThread}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
