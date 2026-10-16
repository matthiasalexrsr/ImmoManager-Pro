import ChannelPanel from '../features/channels/ChannelPanel';
import NotificationArrival from '../components/NotificationArrival';
import { useState, useEffect, useMemo, useCallback } from 'react';
import { api } from '../api';
import { useEntities } from '../contexts/DataStoreContext';
import NotificationInbox from '../components/NotificationInbox';
import { useTranslation } from '../i18n';
import FormModal from '../components/FormModal';
import { useSearchParams } from 'react-router-dom';
import useMessageConversation from '../hooks/useMessageConversation';
import './messages.css';
import CommunicationCenter from '../features/communication/CommunicationCenter';
import InternalReplyComposer from '../features/communication/InternalReplyComposer';
import { useCanWrite } from '../contexts/AuthContext';

export default function Messages() {
  const [params] = useSearchParams();
  const [threads, setThreads] = useState([]);
  const [channelThread, setChannelThread] = useState(null);
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
  const [view, setView] = useState(params.get('focus_id') ? 'threads' : 'notifications');
  const [attempt, setAttempt] = useState(0);
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
      request.abort(); setThreads([]); setContacts([]); setModal(null);
      setLoading(false); setError('Die Sitzung wurde geändert. Bitte erneut anmelden.');
    };
    window.addEventListener('workspace-logout', invalidate);
    window.addEventListener('workspace-owner', invalidate);
    Promise.allSettled([api.list('/messages/threads', { signal: request.signal })])
      .then(([thr]) => {
        if (request.signal.aborted) return;
        try { sameSession(); } catch { invalidate(); return; }
        const failures = [];
        if (thr.status === 'fulfilled' && Array.isArray(thr.value)) setThreads(thr.value);
        else failures.push(thr.reason?.message || 'Konversationen konnten nicht gelesen werden.');
        if (failures.length) setError(failures.join(' · '));
      }).finally(() => { if (!request.signal.aborted) setLoading(false); });
    return () => { request.abort(); window.removeEventListener('workspace-logout', invalidate); window.removeEventListener('workspace-owner', invalidate); };
  }, [attempt]);

  const focusThread = params.get('notice_id') ? params.get('focus_id') : null;
  const focusMessage = params.get('notice_id') ? params.get('source_id') : null;
  const [arrivedMessage, setArrivedMessage] = useState(null);
  const loadThreadMessages = conversation.selectThread;
  useEffect(() => {
    if (!focusThread) return;
    let live = true; const same = api.captureSession(); setArrivedMessage(null);
    api.get(`/messages/threads/${encodeURIComponent(focusThread)}`).then(thread => {
      same(); if (!live) return; setView('threads'); loadThreadMessages(thread);
      if (focusMessage) return api.get(`/messages/threads/${encodeURIComponent(focusThread)}/messages/${encodeURIComponent(focusMessage)}`).then(message => {
        same(); if (live && message.thread_id === focusThread) setArrivedMessage(message);
      });
    }).catch(failure => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [focusThread, focusMessage, loadThreadMessages]);
  const handleSendMessage = () => conversation.send();
  const linkedThreadId = params.get('thread_id') || params.get('focus_id');
  useEffect(() => {
    if (focusThread || !linkedThreadId || selectedThread?.id === linkedThreadId) return;
    const linked = threads.find(item => item.id === linkedThreadId);
    if (linked) { setView('threads'); loadThreadMessages(linked); }
  }, [focusThread, linkedThreadId, selectedThread?.id, threads, loadThreadMessages]);


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

  // Thread entity references
  const resolveThreadRef = (thr) => {
    const parts = [];
    if (thr.property_id && propMap[thr.property_id]) parts.push(propMap[thr.property_id]);
    if (thr.unit_id && unitMap[thr.unit_id]) parts.push(unitMap[thr.unit_id]);
    if (thr.contract_id && contractMap[thr.contract_id]) parts.push(contractMap[thr.contract_id]);
    return parts.length > 0 ? parts.join(' / ') : null;
  };

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
          {t('pages.messages.notifications') || 'Benachrichtigungen'}
        </button>
        <button
          className={`detail-tab ${view === 'threads' ? 'active' : ''}`}
          onClick={() => setView('threads')}
        >
          {t('pages.messages.conversations') || 'Konversationen'} ({threads.length})
        </button>
        <button className={`detail-tab ${view === 'communication' ? 'active' : ''}`} onClick={() => setView('communication')}>E-Mail und Empfang</button>
      </div>

      {view === 'communication' && <CommunicationCenter threads={threads} onOpenThread={id => {
        const linked = threads.find(item => item.id === id);
        if (linked) { setView('threads'); loadThreadMessages(linked); }
      }} />}
      {view === 'notifications' && <NotificationInbox />}

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
                  <button type="button" className="btn btn-secondary" aria-expanded={channelThread === selectedThread.id}
                    onClick={() => setChannelThread(previous => previous === selectedThread.id ? null : selectedThread.id)}>WhatsApp-Vorgänge anzeigen</button>
                  {channelThread === selectedThread.id && <ChannelPanel key={selectedThread.id} sourceId={selectedThread.id} mode="whatsapp" />}
                  {!focusMessage && <NotificationArrival record={selectedThread} ready={threadPage.status === 'ready'} />}
                  {arrivedMessage && selectedThread.id === focusThread && <section aria-label="Nachricht aus dem Hinweis">
                    <h3>Ausgewählte Nachricht</h3><p>{arrivedMessage.body}</p><small>{arrivedMessage.sender_name} · {arrivedMessage.sent_at}</small>
                    <NotificationArrival record={arrivedMessage} ready={threadPage.status === 'ready'} />
                  </section>}
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
                {canWrite && <InternalReplyComposer key={selectedThread.id} thread={selectedThread}
                  value={newMessage} onChange={setNewMessage} onSend={handleSendMessage} notice={notice} />}
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
