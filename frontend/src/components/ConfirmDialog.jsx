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

  // options: { action, title, confirmLabel, danger } — without them a deletion reads as one, anything else neutrally
  const confirm = useCallback((message, options = {}) => {
    return new Promise((resolve) => {
      if (!mounted.current) { resolve(false); return; }
      const entry = { message, options, resolve, id: ++sequence.current };
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
          options={state.options}
          onConfirm={() => settle(state.id, true)}
          onCancel={() => settle(state.id, false)}
        />
      )}
    </ConfirmContext.Provider>
  );
}

const DELETION = /\blösch|\bentfernen\?|\bdelete\b|\bremove\b|\beliminar/i;
// the button names the action (modals.confirm.<action>)
const ACTIONS = { archive: 'Archivieren', markPaid: 'Als bezahlt markieren', reverse: 'Stornieren', apply: 'Update anwenden',
  deactivate: 'Deaktivieren', withdraw: 'Kündigung zurücknehmen', unlink: 'Zuordnung lösen' };

function ConfirmDialog({ message, options = {}, onConfirm, onCancel }) {
  const { t } = useTranslation();
  const tr = (key, fallback) => {
    const text = t(key);
    return text && text !== key ? text : fallback;
  };
  const ref = useRef(null);
  const id = useId();
  useModalDialog(ref, onCancel);
  const deletion = options.action === 'delete' || (!options.action && DELETION.test(String(message ?? '')));
  const danger = options.danger ?? deletion;
  const title = options.title ?? (deletion ? tr('modals.confirmDelete.title', 'Wirklich löschen?')
    : tr('modals.confirm.title', 'Bitte bestätigen'));
  const confirmLabel = options.confirmLabel
    ?? (ACTIONS[options.action] ? tr(`modals.confirm.${options.action}`, ACTIONS[options.action]) : null)
    ?? (deletion ? tr('modals.confirmDelete.delete', 'Löschen') : tr('modals.confirmDelete.confirm', 'Bestätigen'));

  return (
    <div className="modal-overlay" style={{ zIndex: 280 }} onClick={onCancel}>
      <div className="modal confirm-dialog" role="dialog" aria-modal="true" aria-labelledby={id} aria-describedby={`${id}-message`} tabIndex={-1} ref={ref} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2 id={id}>{title}</h2>
        </div>
        <div className="modal-body">
          <p id={`${id}-message`}>{message}</p>
        </div>
        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" onClick={onCancel}>
            {tr('modals.confirmDelete.cancel', 'Abbrechen')}
          </button>
          <button type="button" className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
