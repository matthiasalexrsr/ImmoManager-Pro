import { useState, useEffect, useRef } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { BellIcon } from './Icons';

export default function NotificationBell() {
  const { t } = useTranslation();
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  const fetchNotifications = () => {
    api.get('/notifications?status=unread&limit=10')
      .then(data => {
        const items = Array.isArray(data) ? data : [];
        setNotifications(items);
        setUnreadCount(items.length);
      })
      .catch(err => {
        console.warn('[NotificationBell] Failed to fetch notifications:', err.message);
      });
  };

  useEffect(() => {
    fetchNotifications();
    const interval = setInterval(fetchNotifications, 60000);
    return () => clearInterval(interval);
  }, []);

  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Close on Escape key
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (e.key === 'Escape') {
        setOpen(false);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open]);

  const markRead = async (id) => {
    try {
      await api.patch(`/notifications/${id}`, { status: 'read' });
      fetchNotifications();
    } catch (err) {
      console.warn('[NotificationBell] Failed to mark notification read:', err.message);
    }
  };

  const markAllRead = async () => {
    for (const n of notifications) {
      try {
        await api.patch(`/notifications/${n.id}`, { status: 'read' });
      } catch (err) {
        console.warn('[NotificationBell] Failed to mark notification read:', err.message);
      }
    }
    fetchNotifications();
  };

  const handleKeyDown = (e, id) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      markRead(id);
    }
  };

  return (
    <div className="notification-bell" ref={ref}>
      <button
        className="notification-bell-btn"
        onClick={() => setOpen(!open)}
        aria-label={t('topBar.notifications')}
        aria-expanded={open}
        aria-haspopup="true"
      >
        <BellIcon size={18} />
        {unreadCount > 0 && <span className="notification-badge" aria-label={`${unreadCount} unread`}>{unreadCount}</span>}
      </button>
      {open && (
        <div className="notification-dropdown" role="menu" aria-label={t('topBar.notifications')}>
          <div className="notification-dropdown-header">
            <span>{t('topBar.notifications')}</span>
            {notifications.length > 0 && (
              <button className="notification-mark-all" onClick={markAllRead}>
                {t('notifications.actions.markAllRead')}
              </button>
            )}
          </div>
          <div className="notification-dropdown-body" role="list">
            {notifications.length === 0 ? (
              <div className="notification-empty" role="listitem">{t('emptyStates.generic.title')}</div>
            ) : (
              notifications.map(n => (
                <div
                  key={n.id}
                  className={`notification-item notification-${n.severity || 'info'}`}
                  onClick={() => markRead(n.id)}
                  onKeyDown={(e) => handleKeyDown(e, n.id)}
                  role="listitem"
                  tabIndex={0}
                >
                  <div className="notification-item-title">{n.title}</div>
                  <div className="notification-item-content">{n.content}</div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
