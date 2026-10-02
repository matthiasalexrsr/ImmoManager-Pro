/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useCallback, useEffect, useRef, useId } from 'react';
import { useTranslation } from '../i18n';

const ConfirmContext = createContext(null);

export function useConfirm() {
  return useContext(ConfirmContext);
}

export function ConfirmProvider({ children }) {
  const [state, setState] = useState(null);
  const resolveRef = useRef(null);

  const confirm = useCallback((message) => {
    return new Promise((resolve) => {
      resolveRef.current = resolve;
      setState({ message });
    });
  }, []);

  const handleConfirm = useCallback(() => {
    resolveRef.current?.(true);
    setState(null);
  }, []);

  const handleCancel = useCallback(() => {
    resolveRef.current?.(false);
    setState(null);
  }, []);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {state && (
        <ConfirmDialog
          message={state.message}
          onConfirm={handleConfirm}
          onCancel={handleCancel}
        />
      )}
    </ConfirmContext.Provider>
  );
}

function ConfirmDialog({ message, onConfirm, onCancel }) {
  const { t } = useTranslation();
  const confirmRef = useRef(null);
  const dialogRef = useRef(null);
  const id = useId();

  useEffect(() => {
    const previous = document.activeElement;
    confirmRef.current?.focus();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, []);

  useEffect(() => {
    const handler = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault(); e.stopImmediatePropagation(); onCancel();
      } else if (e.key === 'Tab') {
        const buttons = dialogRef.current?.querySelectorAll('button:not([disabled])');
        if (!buttons?.length) return;
        const first = buttons[0]; const last = buttons[buttons.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault(); e.stopImmediatePropagation(); last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault(); e.stopImmediatePropagation(); first.focus();
        } else {
          e.stopImmediatePropagation();
        }
      }
    };
    document.addEventListener('keydown', handler, true);
    return () => document.removeEventListener('keydown', handler, true);
  }, [onCancel]);

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal confirm-dialog" role="alertdialog" aria-modal="true"
        aria-labelledby={`${id}-title`} aria-describedby={`${id}-message`}
        ref={dialogRef} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2 id={`${id}-title`}>{t('modals.confirmAction.title')}</h2>
        </div>
        <div className="modal-body">
          <p id={`${id}-message`}>{message}</p>
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onCancel}>
            {t('modals.confirmAction.cancel')}
          </button>
          <button className="btn btn-danger" ref={confirmRef} onClick={onConfirm}>
            {t('modals.confirmAction.confirm')}
          </button>
        </div>
      </div>
    </div>
  );
}
