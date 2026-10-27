import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link, useLocation } from 'react-router-dom';
import { FolderClock, X } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import EntityShelf from './EntityShelf';
import './quickAccess.css';

/** The same server-authorized shelves as the work center, reachable from every page. */
export default function QuickAccess() {
  const auth = useAuth();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  useEffect(() => { setOpen(false); }, [location, auth?.user?.id]);
  useEffect(() => {
    const keydown = event => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || !event.altKey || event.code !== 'KeyO') return;
      if (event.target?.closest?.('input, textarea, select, [contenteditable]:not([contenteditable="false"])') || document.querySelector('[aria-modal="true"]')) return;
      event.preventDefault(); setOpen(true);
    };
    document.addEventListener('keydown', keydown);
    return () => document.removeEventListener('keydown', keydown);
  }, []);
  if (!auth?.user?.id) return null;
  return <>
    <button type="button" className="top-bar-icon-btn quick-access-trigger" aria-label="Akten öffnen" aria-haspopup="dialog"
      aria-expanded={open} title="Gemerkte und zuletzt geöffnete Akten (Alt+O)" onClick={() => setOpen(true)}><FolderClock size={19} aria-hidden="true" /><span>Akten</span></button>
    {open && <AccessDialog onClose={close} />}
  </>;
}

function AccessDialog({ onClose }) {
  const ref = useRef(null);
  const id = useId();
  useModalDialog(ref, onClose);
  return createPortal(<div className="quick-access-backdrop" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="quick-access-dialog" role="dialog" aria-modal="true" aria-labelledby={id} aria-describedby={`${id}-description`} tabIndex={-1} ref={ref}>
      <header className="quick-access-header"><div><h2 id={id}>Akten öffnen</h2><p id={`${id}-description`}>Ihre gemerkten Vorgänge und zuletzt geöffneten Akten, direkt zur Hand.</p></div>
        <button type="button" className="btn btn-ghost" aria-label="Aktenübersicht schließen" onClick={onClose}><X size={20} aria-hidden="true" /></button></header>
      <EntityShelf onOpen={onClose} />
      <footer><Link to="/work-center" className="btn btn-secondary" onClick={onClose}>Zur Arbeitszentrale</Link><span>Mit Escape schließen</span></footer>
    </section>
  </div>, document.body);
}
