/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { CheckCircleIcon, XCircleIcon, AlertIcon, InfoIcon, CloseIcon } from './Icons';
import { useTranslation } from '../i18n';

const ToastContext = createContext(null);
const MAX_VISIBLE = 5;

const TOAST_ICONS = {
  success: CheckCircleIcon,
  error: XCircleIcon,
  warning: AlertIcon,
  info: InfoIcon,
};

export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }) {
  const { t } = useTranslation();
  const translatedClose = t('ui.buttons.close');
  const closeLabel = translatedClose && translatedClose !== 'ui.buttons.close' ? translatedClose : 'Meldung schließen';
  const [toasts, setToasts] = useState([]);
  const sequence = useRef(0);
  const timers = useRef(new Map());

  const clearTimer = useCallback(id => {
    const entry = timers.current.get(id);
    if (entry?.timeout != null) clearTimeout(entry.timeout);
    timers.current.delete(id);
  }, []);

  const removeToast = useCallback(id => {
    clearTimer(id);
    setToasts(prev => prev.filter(toast => toast.id !== id));
  }, [clearTimer]);

  const addToast = useCallback((message, type = 'info', duration = 4000) => {
    const id = ++sequence.current;
    // Bounded stacking: many background updates must not cover the workspace.
    setToasts(prev => [...prev.slice(-(MAX_VISIBLE - 1)), { id, message, type }]);
    if (duration > 0) {
      const timeout = setTimeout(() => {
        timers.current.delete(id);
        setToasts(prev => prev.filter(toast => toast.id !== id));
      }, duration);
      timers.current.set(id, { timeout, remaining: duration, started: Date.now(), pauses: new Set() });
    }
  }, []);

  // Remove timers of notifications evicted by the visible limit.
  useEffect(() => {
    const displayed = new Set(toasts.map(toast => toast.id));
    for (const id of timers.current.keys()) {
      if (!displayed.has(id)) clearTimer(id);
    }
  }, [toasts, clearTimer]);

  useEffect(() => () => {
    for (const item of timers.current.values()) {
      if (item.timeout != null) clearTimeout(item.timeout);
    }
    timers.current.clear();
  }, []);

  // Give people time to read longer errors: auto-dismiss pauses on hover and
  // while the keyboard is focused on the explicit close button.
  const pauseToast = useCallback((id, reason) => {
    const timer = timers.current.get(id);
    if (!timer) return;
    timer.pauses.add(reason);
    if (timer.timeout == null) return;
    clearTimeout(timer.timeout);
    timer.remaining = Math.max(1, timer.remaining - (Date.now() - timer.started));
    timer.timeout = null;
  }, []);
  const resumeToast = useCallback((id, reason) => {
    const timer = timers.current.get(id);
    if (!timer) return;
    timer.pauses.delete(reason);
    if (timer.pauses.size || timer.timeout != null) return;
    timer.started = Date.now();
    timer.timeout = setTimeout(() => {
      timers.current.delete(id);
      setToasts(prev => prev.filter(toast => toast.id !== id));
    }, timer.remaining);
  }, []);

  // Stable across renders: changing the toast object once repeated failed
  // requests endlessly in effects that depend on it.
  const toast = useMemo(() => ({
    success: msg => addToast(msg, 'success'),
    error: msg => addToast(msg, 'error', 6000),
    info: msg => addToast(msg, 'info'),
    warning: msg => addToast(msg, 'warning', 5000),
  }), [addToast]);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="toast-container" aria-label="Benachrichtigungen">
        {toasts.map(item => {
          const IconComp = TOAST_ICONS[item.type] || InfoIcon;
          return (
            <div key={item.id} className={`toast toast-${item.type}`}
              role={item.type === 'error' ? 'alert' : 'status'}
              onMouseEnter={() => pauseToast(item.id, 'pointer')}
              onMouseLeave={() => resumeToast(item.id, 'pointer')}
              onFocus={() => pauseToast(item.id, 'focus')}
              onBlur={event => {
                if (!event.currentTarget.contains(event.relatedTarget)) resumeToast(item.id, 'focus');
              }}>
              <span className="toast-icon" aria-hidden="true"><IconComp size={18} /></span>
              <span className="toast-message">{item.message}</span>
              <button type="button" className="toast-dismiss" aria-label={closeLabel}
                title={closeLabel} onClick={() => removeToast(item.id)}>
                <CloseIcon size={16} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
