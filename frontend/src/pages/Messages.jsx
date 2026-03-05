import { useState, useEffect } from 'react';
import { api } from '../api';
import StatusBadge from '../components/StatusBadge';
import { useTranslation } from '../i18n';

export default function Messages() {
  const [notifications, setNotifications] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const { t } = useTranslation();
  const [filter, setFilter] = useState('all');

  useEffect(() => {
    api.get('/notifications').then(setNotifications).catch(err => console.warn('[Messages]', err.message)).finally(() => setLoading(false));
  }, []);

  const markRead = async (id) => {
    await api.patch(`/notifications/${id}`, { status: 'read' }).catch(err => console.warn('[Messages] mark read:', err.message));
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, status: 'read' } : n));
  };

  const filtered = filter === 'all'
    ? notifications
    : notifications.filter(n => n.status === filter);

  if (loading) return <div className="page-loading">{t('pages.loading')}</div>;

  return (
    <div className="page">
      <h1 className="page-title">{t('pages.messages.title')}</h1>
      <div className="messages-layout">
        <div className="messages-sidebar">
          <div className="messages-filters">
            <button
              className={`btn btn-sm ${filter === 'all' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setFilter('all')}
            >{t('pages.messages.all')} ({notifications.length})</button>
            <button
              className={`btn btn-sm ${filter === 'unread' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setFilter('unread')}
            >{t('pages.messages.unread')} ({notifications.filter(n => n.status === 'unread').length})</button>
          </div>
          <div className="messages-list">
            {filtered.length === 0 ? (
              <p className="panel-empty">{t('pages.messages.noMessages')}</p>
            ) : filtered.map(n => (
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
    </div>
  );
}
