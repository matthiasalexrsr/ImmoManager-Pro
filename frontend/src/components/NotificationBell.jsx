import { useEffect, useRef, useState } from 'react';
import { BellIcon } from './Icons';
import useNotificationInbox from '../hooks/useNotificationInbox';
import NotificationInbox from './NotificationInbox';

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const button = useRef(null);
  const { page } = useNotificationInbox('unread', null, 1);
  useEffect(() => {
    const close = event => { if (event.key === 'Escape') { setOpen(false); button.current?.focus(); } else if (!ref.current?.contains(event.target)) setOpen(false); };
    document.addEventListener('mousedown', close); document.addEventListener('keydown', close);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', close); };
  }, []);
  return <div className="notification-bell" ref={ref}>
    <button ref={button} className="notification-bell-btn" onClick={() => setOpen(value => !value)} aria-label="Benachrichtigungen" aria-expanded={open}><BellIcon size={18} />{page?.unread_count > 0 && <span className="notification-badge" aria-label={`${page.unread_count} ungelesen`}>{page.unread_count}</span>}</button>
    {open && <div className="notification-dropdown"><NotificationInbox compact /></div>}
  </div>;
}
