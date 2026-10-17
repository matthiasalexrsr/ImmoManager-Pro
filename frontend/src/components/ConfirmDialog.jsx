/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useCallback, useEffect, useRef, useId } from 'react';
import { useTranslation } from '../i18n';
import { useModalDialog } from '../features/partyWorkspace/useModalDialog';

const ConfirmContext = createContext(null);

export function useConfirm() {
  return useContext(ConfirmContext);
}

export function ConfirmProvider({ children }) {
  const [state, setState] = useState(null);
  const queue = useRef([]);
  const sequence = useRef(0);
  const mounted = useRef(true);

  const confirm = useCallback((message) => {
    return new Promise((resolve) => {
      if (!mounted.current) { resolve(false); return; }
      const entry = { message, resolve, id: ++sequence.current };
      queue.current.push(entry);
      if (queue.current.length === 1) setState(entry);
    });
  }, []);

  const settle = useCallback((id, answer) => {
    if (queue.current[0]?.id !== id) return;
    const current = queue.current.shift();
    current?.resolve(answer);
    setState(queue.current[0] || null);
  }, []);
  useEffect(() => {
    mounted.current = true;
    const pending = queue.current;
    const cancelAll = () => { pending.splice(0).forEach(entry => entry.resolve(false)); setState(null); };
    window.addEventListener('workspace-logout', cancelAll);
    return () => {
      mounted.current = false;
      window.removeEventListener('workspace-logout', cancelAll);
      pending.splice(0).forEach(entry => entry.resolve(false));
    };
  }, []);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {state && (
        <ConfirmDialog
          key={state.id}
          message={state.message}
          onConfirm={() => settle(state.id, true)}
          onCancel={() => settle(state.id, false)}
        />
      )}
    </ConfirmContext.Provider>
  );
}

function ConfirmDialog({ message, onConfirm, onCancel }) {
  const { t } = useTranslation();
  const tr = (key, fallback) => {
    const text = t(key);
    return text && text !== key ? text : fallback;
  };
  const ref = useRef(null);
  const id = useId();
  useModalDialog(ref, onCancel);

  return (
    <div className="modal-overlay" style={{ zIndex: 280 }} onClick={onCancel}>
      <div className="modal confirm-dialog" role="dialog" aria-modal="true" aria-labelledby={id} aria-describedby={`${id}-message`} tabIndex={-1} ref={ref} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2 id={id}>{tr('modals.confirmDelete.title', 'Bestätigung')}</h2>
        </div>
        <div className="modal-body">
          <p id={`${id}-message`}>{message}</p>
        </div>
        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" onClick={onCancel}>
            {tr('modals.confirmDelete.cancel', 'Abbrechen')}
          </button>
          <button type="button" className="btn btn-danger" onClick={onConfirm}>
            {tr('modals.confirmDelete.confirm', 'Bestätigen')}
          </button>
        </div>
      </div>
    </div>
  );
}
