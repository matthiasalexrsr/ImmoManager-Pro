import { useEffect, useId, useRef, useState } from 'react';
import { BellIcon } from './Icons';
import useNotificationInbox from '../hooks/useNotificationInbox';
import NotificationInbox from './NotificationInbox';
import { useLocation } from 'react-router-dom';

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const popupId = useId();
  const ref = useRef(null);
  const button = useRef(null);
  const { page } = useNotificationInbox('unread', null, 1);
  const location = useLocation();
  useEffect(() => { setOpen(false); }, [location.key]);

  useEffect(() => {
    // A closed bell must not capture Escape used by forms or confirmations.
    if (!open) return;
    const onKeyDown = event => {
      if (event.key !== 'Escape' || !ref.current?.contains(event.target)) return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      button.current?.focus();
    };
    const onOutsideClick = event => {
      if (!ref.current?.contains(event.target)) setOpen(false);
    };
    const onFocusChange = event => {
      // Tabbing away closes the non-modal preview without stealing focus.
      if (!ref.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('mousedown', onOutsideClick);
    document.addEventListener('focusin', onFocusChange);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('mousedown', onOutsideClick);
      document.removeEventListener('focusin', onFocusChange);
    };
  }, [open]);

  return <div className="notification-bell" ref={ref}>
    <button type="button" ref={button} className="notification-bell-btn"
      onClick={() => setOpen(value => !value)}
      aria-label="Benachrichtigungen" aria-expanded={open}
      aria-controls={open ? popupId : undefined}>
      <BellIcon size={18} />
      {page?.unread_count > 0 && <span className="notification-badge"
        aria-label={`${page.unread_count} ungelesen`}>{page.unread_count}</span>}
    </button>
    {open && <div id={popupId} className="notification-dropdown"
      role="region" aria-label="Benachrichtigungs-Vorschau">
      <NotificationInbox compact />
    </div>}
  </div>;
}
