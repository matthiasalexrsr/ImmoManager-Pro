/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useCallback } from 'react';
import { CheckCircleIcon, XCircleIcon, AlertIcon, InfoIcon } from './Icons';

const ToastContext = createContext(null);

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
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback((message, type = 'info', duration = 4000) => {
    const id = Date.now() + Math.random();
    setToasts(prev => [...prev, { id, message, type }]);
    if (duration > 0) {
      setTimeout(() => {
        setToasts(prev => prev.filter(t => t.id !== id));
      }, duration);
    }
  }, []);

  const removeToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const toast = {
    success: (msg) => addToast(msg, 'success'),
    error: (msg) => addToast(msg, 'error', 6000),
    info: (msg) => addToast(msg, 'info'),
    warning: (msg) => addToast(msg, 'warning', 5000),
  };

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="toast-container" aria-live="polite" aria-atomic="true" role="status">
        {toasts.map(t => {
          const IconComp = TOAST_ICONS[t.type] || InfoIcon;
          return (
            <div
              key={t.id}
              className={`toast toast-${t.type}`}
              onClick={() => removeToast(t.id)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === 'Escape') removeToast(t.id); }}
              role={t.type === 'error' ? 'alert' : 'status'}
              tabIndex={0}
            >
              <span className="toast-icon" aria-hidden="true">
                <IconComp size={18} />
              </span>
              <span className="toast-message">{t.message}</span>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
