import { useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { CloseIcon } from '../../components/Icons';
import { useModalDialog } from '../partyWorkspace/useModalDialog';

/** The reading panel in a dialog of its own (between an upload and the form it fills). */
export default function AiReadingDialog({ title = 'Dokument einlesen', onClose, children }) {
  const id = useId();
  const dialog = useRef(null);
  useModalDialog(dialog, onClose, true);
  return createPortal(
    <div className="modal-overlay" role="presentation" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={dialog} className="modal modal-wide ai-reading-dialog" role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} tabIndex={-1}>
        <div className="modal-header">
          <h3 id={`${id}-title`}>{title}</h3>
          <button type="button" className="btn-close" aria-label="Schließen" onClick={onClose}><CloseIcon size={18} /></button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>, globalThis.document.body);
}
