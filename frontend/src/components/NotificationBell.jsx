import { useState, useEffect, useRef } from 'react';
import { api } from '../api';
import { BellIcon } from './Icons';

export default function NotificationBell() {
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

  return (
    <div className="notification-bell" ref={ref}>
      <button className="notification-bell-btn" onClick={() => setOpen(!open)} title="Benachrichtigungen">
        <BellIcon size={18} />
        {unreadCount > 0 && <span className="notification-badge">{unreadCount}</span>}
      </button>
      {open && (
        <div className="notification-dropdown">
          <div className="notification-dropdown-header">
            <span>Benachrichtigungen</span>
            {notifications.length > 0 && (
              <button className="notification-mark-all" onClick={markAllRead}>
                Alle gelesen
              </button>
            )}
          </div>
          <div className="notification-dropdown-body">
            {notifications.length === 0 ? (
              <div className="notification-empty">Keine neuen Benachrichtigungen</div>
            ) : (
              notifications.map(n => (
                <div key={n.id} className={`notification-item notification-${n.severity || 'info'}`} onClick={() => markRead(n.id)}>
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
